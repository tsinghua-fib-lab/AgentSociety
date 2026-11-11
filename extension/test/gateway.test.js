/**
 * Gateway / auth smoke tests.
 * Keep only invariants that protect auth routing, role eligibility, and usage accounting.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const {
  inferApiKindFromBaseUrl,
} = require('../out/aiCli/officialEndpoints');
const {
  isFiblabLlmBase,
} = require('../out/services/webConfigGatewayImport');
const {
  pythonHasAgentsociety2,
} = require('../out/services/agentsocietyPythonResolver');
const {
  applyUpstreamAuthHeaders,
  resolveAuthHeaderMode,
} = require('../out/aiCli/upstreamAuthHeaders');
const {
  clampProviderRoleFlags,
  countApiUpstreamsForRole,
  providerEligibleForRoleUpstream,
} = require('../out/aiCli/providerAuth');
const {
  aggregateUsage,
  extractTokenUsage,
  sanitizeUsageRecords,
} = require('../out/services/gatewayUsageTracker');
const {
  calculateCost,
  getModelPrice,
} = require('../out/services/gatewayModelPricing');
const {
  parseLiteLlmPricing,
  parseOpenRouterPricing,
} = require('../out/services/gatewayRemotePricing');
const {
  resolveUpstreamTargetUrl,
  upstreamTargetsLocalGateway,
} = require('../out/services/aiCliGatewayUpstream');
const { claudeSettingsBaseUrl } = require('../out/aiCli/officialEndpoints');
const { detectUsageTemplate, customUsageUrl, parseCustomUsage } = require('../out/shared/providerUsage');
const { queryProviderUsage, ProviderUsageCache, providerUsageCacheKey } = require('../out/services/gatewayProviderUsage');

test('usage cache identity tracks credentials, account sessions and query settings without exposing secrets', () => {
  const secret = Buffer.alloc(32, 1);
  const credentials = ['provider-api-key', { accessToken: 'session-token' }];
  const metadata = ['provider-id', 'https://provider.example/v1', { proxy: null }];
  const key = providerUsageCacheKey(secret, credentials, metadata);
  assert.equal(providerUsageCacheKey(secret, credentials, metadata), key);
  assert.notEqual(providerUsageCacheKey(secret, ['changed-key', credentials[1]], metadata), key);
  assert.notEqual(providerUsageCacheKey(secret, [credentials[0], { accessToken: 'new-session' }], metadata), key);
  assert.notEqual(providerUsageCacheKey(secret, credentials, [...metadata, 'changed-query']), key);
  assert.notEqual(providerUsageCacheKey(Buffer.alloc(32, 2), credentials, metadata), key);
  assert.ok(!key.includes('provider-api-key') && !key.includes('session-token'));
});

test('balance query detection respects disable and custom modes and exact official hosts', () => {
  assert.equal(detectUsageTemplate('https://api.deepseek.com/v1'), 'deepseek');
  assert.equal(detectUsageTemplate('https://api.deepseek.com/v1', { usageQuery: { mode: 'off' } }), null);
  assert.equal(detectUsageTemplate('https://relay.example/v1', { usageQuery: { mode: 'custom' } }), 'custom');
  for (const url of ['http://api.deepseek.com', 'https://api.deepseek.com:8443', 'https://relay.deepseek.com', 'https://evil.example/deepseek.com']) {
    assert.equal(detectUsageTemplate(url), null);
  }
});

test('custom balances preserve zero, convert units and reject missing or invalid amounts', () => {
  const config = { mode: 'custom', remainingPath: 'data.0.balance', usedPath: 'data.0.used', unit: 'USD', divisor: 100 };
  const result = parseCustomUsage({ data: [{ balance: '0', used: 200 }] }, config);
  assert.equal(result.plans[0].remaining, '0');
  assert.equal(result.plans[0].used, '2');
  assert.equal(result.plans[0].total, '2');
  assert.equal(result.plans[0].remainingPercent, 0);
  for (const balance of [null, true, '', 'unknown', Infinity]) {
    assert.throws(() => parseCustomUsage({ data: [{ balance, used: 1 }] }, config), /invalid_usage_response/);
  }
  assert.throws(() => parseCustomUsage({}, config), /invalid_usage_response/);
  assert.throws(() => parseCustomUsage({}, { ...config, divisor: 0 }), /invalid_usage_config/);
  assert.equal(customUsageUrl('https://relay.example/v1', { path: '/account/balance' }), 'https://relay.example/account/balance');
  for (const path of ['https://other.example/balance', '//other.example/balance', '/\\other.example/balance']) {
    assert.throws(() => customUsageUrl('https://relay.example/v1', { path }), /invalid_usage_config/);
  }
});

test('custom balance requests reuse provider auth, reject redirects and hide response error bodies', async (t) => {
  const paths = [];
  const upstream = http.createServer((req, res) => {
    paths.push(req.url);
    assert.equal(req.headers['x-api-key'], 'test-secret');
    if (req.url === '/redirect') { res.writeHead(302, { location: '/balance' }); res.end(); return; }
    if (req.url === '/error') { res.writeHead(403); res.end('test-secret private account details'); return; }
    res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ account: { balance: 12.5 } }));
  });
  await new Promise((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => upstream.close(resolve)));
  const base = `http://127.0.0.1:${upstream.address().port}/v1`;
  const options = { authHeaderMode: 'x-api-key', usageQuery: { mode: 'custom', path: '/balance', remainingPath: 'account.balance', unit: 'USD' } };
  const result = await queryProviderUsage(base, 'test-secret', options);
  assert.equal(result.ok, true);
  assert.equal(result.plans[0].remaining, '12.5');
  assert.ok(result.fetchedAt);
  for (const [path, error] of [['/redirect', 'http_302'], ['/error', 'http_403']]) {
    const failure = await queryProviderUsage(base, 'test-secret', { ...options, usageQuery: { ...options.usageQuery, path } });
    assert.equal(failure.error, error);
    assert.equal(failure.fetchedAt, undefined);
    assert.ok(!JSON.stringify(failure).includes('test-secret'));
  }
  assert.deepEqual(paths, ['/balance', '/redirect', '/error']);
});

test('provider balance refreshes merge in-flight requests and honor cache expiry and manual refresh', async (t) => {
  let now = 1000;
  t.mock.method(Date, 'now', () => now);
  const cache = new ProviderUsageCache();
  let resolve, calls = 0;
  const load = () => { calls++; return new Promise((done) => { resolve = done; }); };
  const first = cache.query('provider-and-credentials', load);
  const second = cache.query('provider-and-credentials', load, true);
  assert.equal(calls, 1);
  resolve({ ok: true, plans: [{ name: 'Account', remaining: '5' }] });
  assert.deepEqual(await first, await second);
  await cache.query('provider-and-credentials', load);
  assert.equal(calls, 1);
  const manual = cache.query('provider-and-credentials', load, true);
  assert.equal(calls, 2); resolve({ ok: true }); await manual;
  now += 60_001;
  const expired = cache.query('provider-and-credentials', load);
  assert.equal(calls, 3); resolve({ ok: false, error: 'http_429' }); await expired;
  const changed = cache.query('changed-credentials', load);
  assert.equal(calls, 4); resolve({ ok: true }); await changed;
});

test('DeepSeek balance queries use official API and retain currency and balance components', async (t) => {
  const https = require('node:https');
  const { EventEmitter } = require('node:events');
  const { Readable } = require('node:stream');
  t.mock.method(https, 'request', (url, options, callback) => {
    assert.equal(url.href, 'https://api.deepseek.com/user/balance');
    assert.equal(options.headers.Authorization, 'Bearer test-key');
    const request = new EventEmitter();
    request.end = () => queueMicrotask(() => {
      const response = Readable.from([Buffer.from(JSON.stringify({ is_available: false, balance_infos: [{ currency: 'CNY', total_balance: '0.00', granted_balance: '0.00', topped_up_balance: '0.00' }] }))]);
      response.statusCode = 200;
      response.once('end', () => request.emit('close'));
      callback(response);
    });
    request.destroy = (error) => { request.emit('error', error); request.emit('close'); };
    return request;
  });
  const result = await queryProviderUsage('https://api.deepseek.com/v1', 'test-key');
  assert.equal(result.available, false);
  assert.equal(result.scope, 'balance');
  assert.equal(result.plans[0].unit, 'CNY');
  assert.equal(result.plans[0].remaining, '0.00');
  assert.deepEqual(result.plans[0].details, [{ label: 'toppedUp', value: '0.00' }, { label: 'granted', value: '0.00' }]);
});

test('URL classification only inspects parsed host and path components', () => {
  assert.equal(
    inferApiKindFromBaseUrl('https://evil.example/siliconflow.cn/v1'),
    'anthropic',
  );
  assert.equal(inferApiKindFromBaseUrl('https://api.siliconflow.cn/v1'), 'openai');
  assert.equal(inferApiKindFromBaseUrl('https://llmapi.fiblab.net/v1'), 'openai');
  assert.equal(isFiblabLlmBase('not-a-url-llmapi.fiblab.net'), false);
  assert.equal(isFiblabLlmBase('https://llmapi.fiblab.net/v1'), true);
});

test('Python discovery never evaluates configured paths in a shell', () => {
  assert.equal(pythonHasAgentsociety2('python3; echo pwned'), false);
  assert.equal(pythonHasAgentsociety2('python3 && echo pwned'), false);
});

test('auth header mode: auto inference and explicit override', () => {
  assert.equal(
    resolveAuthHeaderMode({
      upstreamBaseUrl: 'https://api.openai.com/v1',
      requestHeaders: {},
    }),
    'bearer',
  );
  assert.equal(
    resolveAuthHeaderMode({
      upstreamBaseUrl: 'https://api.anthropic.com',
      requestHeaders: {},
    }),
    'both',
  );

  const bearerOnly = {};
  applyUpstreamAuthHeaders(bearerOnly, 'tok', {
    upstreamBaseUrl: 'https://api.anthropic.com',
    mode: 'bearer',
  });
  assert.equal(bearerOnly.authorization, 'Bearer tok');
  assert.equal(bearerOnly['x-api-key'], undefined);

  const both = {};
  applyUpstreamAuthHeaders(both, 'tok', {
    upstreamBaseUrl: 'https://api.openai.com/v1',
    mode: 'both',
  });
  assert.equal(both.authorization, 'Bearer tok');
  assert.equal(both['x-api-key'], 'tok');
});

test('Codex role eligibility excludes Anthropic upstreams', () => {
  const anthropic = {
    baseUrl: 'https://api.anthropic.com',
    apiKey: 'sk-ant',
    apiKind: 'anthropic',
    authMode: 'api',
  };
  const openai = {
    baseUrl: 'https://api.openai.com/v1',
    apiKey: 'sk-openai',
    apiKind: 'openai',
    authMode: 'api',
  };
  assert.equal(providerEligibleForRoleUpstream(anthropic, 'claude'), true);
  assert.equal(providerEligibleForRoleUpstream(anthropic, 'codex'), false);
  assert.equal(providerEligibleForRoleUpstream(openai, 'codex'), true);

  const clamped = clampProviderRoleFlags({
    ...anthropic,
    failoverClaude: true,
    failoverCodex: true,
  });
  assert.equal(clamped.failoverClaude, true);
  assert.equal(clamped.failoverCodex, false);

  assert.equal(countApiUpstreamsForRole([anthropic, openai], 'claude'), 2);
  assert.equal(countApiUpstreamsForRole([anthropic, openai], 'codex'), 1);
});

test('upstream URL joining does not double /v1', () => {
  assert.equal(
    resolveUpstreamTargetUrl('https://api.example.com/v1', '/v1/messages'),
    'https://api.example.com/v1/messages',
  );
  assert.equal(
    claudeSettingsBaseUrl('https://llmapi.fiblab.net/v1'),
    'https://llmapi.fiblab.net',
  );
});

test('local gateway detects exact self-forwarding endpoints', () => {
  assert.equal(upstreamTargetsLocalGateway('http://127.0.0.1:19090/v1', 19090), true);
  assert.equal(upstreamTargetsLocalGateway('http://localhost:19090', 19090), true);
  assert.equal(upstreamTargetsLocalGateway('http://[::1]:19090/v1', 19090), true);
  assert.equal(upstreamTargetsLocalGateway('http://127.0.0.1:19091/v1', 19090), false);
  assert.equal(upstreamTargetsLocalGateway('http://127.example.com:19090/v1', 19090), false);
  assert.equal(upstreamTargetsLocalGateway('https://api.example.com:19090/v1', 19090), false);
});

test('usage accounting requires an explicit claude/codex app', () => {
  const base = {
    model: 'gpt-5.5',
    inputTokens: 10,
    outputTokens: 5,
    cacheReadTokens: 0,
    cacheCreationTokens: 0,
    serverToolUseTokens: 0,
    requestId: 'r1',
    upstream: 'https://api.example.com/v1',
    ts: '2026-07-12T04:08:28.000Z',
  };
  const kept = sanitizeUsageRecords([
    { ...base, app: 'claude' },
    { ...base, requestId: 'r2' },
    { ...base, requestId: 'r3', app: 'unknown' },
  ]);
  assert.equal(kept.length, 1);
  assert.equal(kept[0].app, 'claude');

  const agg = aggregateUsage([{ ...base, app: 'codex' }, { ...base, requestId: 'r2' }]);
  assert.equal(agg.totalRequests, 1);
  assert.equal(agg.byApp.codex.requests, 1);
});

test('OpenAI usage accounting keeps regular input, cache reads, and cache writes exclusive', () => {
  const usage = extractTokenUsage({
    model: 'gpt-5.5',
    usage: {
      input_tokens: 12_000,
      output_tokens: 0,
      input_tokens_details: {
        cached_tokens: 4_000,
        cache_write_tokens: 7_000,
      },
    },
  });
  assert.deepEqual(usage, {
    inputTokens: 1_000,
    outputTokens: 0,
    cacheReadTokens: 4_000,
    cacheCreationTokens: 7_000,
    serverToolUseTokens: 0,
    model: 'gpt-5.5',
  });
  const cost = calculateCost(
    usage.model,
    usage.inputTokens,
    usage.outputTokens,
    usage.cacheReadTokens,
    usage.cacheCreationTokens,
    {
      'gpt-5.5': {
        inputPerMillion: 5,
        outputPerMillion: 30,
        cacheReadPerMillion: 0.5,
        cacheCreationPerMillion: 6.25,
      },
    },
    { app: 'codex' },
  );
  assert.ok(cost);
  assert.ok(Math.abs(cost.total - 0.05075) < 1e-12);
});

test('cache-write lifetime buckets use separate standard and extended rates', () => {
  const usage = extractTokenUsage({
    model: 'test-model',
    usage: {
      input_tokens: 12_000,
      output_tokens: 0,
      input_tokens_details: {
        cached_tokens: 4_000,
        cache_write_tokens: 7_000,
        cache_write_tokens_details: {
          ttl_30m_tokens: 3_000,
          ttl_12h_tokens: 4_000,
        },
      },
    },
  });
  assert.equal(usage.inputTokens, 1_000);
  assert.equal(usage.cacheCreationTokens, 7_000);
  assert.equal(usage.cacheCreationLongTokens, 4_000);
  const cost = calculateCost(
    usage.model,
    usage.inputTokens,
    usage.outputTokens,
    usage.cacheReadTokens,
    usage.cacheCreationTokens,
    {
      'test-model': {
        inputPerMillion: 1,
        outputPerMillion: 1,
        cacheReadPerMillion: 0.1,
        cacheCreationPerMillion: 1.25,
        cacheCreationLongPerMillion: 2.5,
      },
    },
    { cacheCreationLongTokens: usage.cacheCreationLongTokens },
  );
  assert.ok(Math.abs(cost.total - 0.01515) < 1e-12);

  const anthropic = extractTokenUsage({
    model: 'claude-sonnet-4-6',
    usage: {
      input_tokens: 50,
      output_tokens: 5,
      cache_creation_input_tokens: 300,
      cache_creation: {
        ephemeral_5m_input_tokens: 200,
        ephemeral_1h_input_tokens: 100,
      },
    },
  });
  assert.equal(anthropic.cacheCreationTokens, 300);
  assert.equal(anthropic.cacheCreationLongTokens, 100);
});

test('upstream-reported cost is preserved and takes precedence over local estimation', () => {
  const usage = extractTokenUsage({
    model: 'vendor/unknown-model',
    usage: {
      input_tokens: 10,
      output_tokens: 2,
      cost: 0.123456,
    },
  });
  assert.equal(usage.reportedCostUsd, 0.123456);
  const cost = calculateCost(
    usage.model,
    usage.inputTokens,
    usage.outputTokens,
    usage.cacheReadTokens,
    usage.cacheCreationTokens,
    undefined,
    { app: 'codex', reportedCostUsd: usage.reportedCostUsd },
  );
  assert.equal(cost.total, 0.123456);
});

test('built-in model pricing is exact, snapshot-aware, and never guesses unknown models', () => {
  assert.deepEqual(getModelPrice('gpt-5.4-pro'), {
    inputPerMillion: 30,
    outputPerMillion: 180,
  });
  assert.deepEqual(getModelPrice('openai/gpt-6.1-sol-2026-09-29'), {
    inputPerMillion: 2,
    outputPerMillion: 10,
    cacheReadPerMillion: 0.1,
    cacheCreationPerMillion: 2.5,
    cacheCreationLongPerMillion: 5,
  });
  assert.equal(getModelPrice('gpt-unknown-future'), null);
});

test('remote pricing parsers retain cache-read and short/long cache-write rates', () => {
  assert.deepEqual(parseOpenRouterPricing({
    data: [{
      id: 'vendor/model',
      pricing: {
        prompt: '0.000001',
        completion: '0.000002',
        input_cache_read: '0.0000001',
        input_cache_write: '0.00000125',
        input_cache_write_1h: '0.000002',
      },
    }],
  })['vendor/model'], {
    inputPerMillion: 1,
    outputPerMillion: 2,
    cacheReadPerMillion: 0.1,
    cacheCreationPerMillion: 1.25,
    cacheCreationLongPerMillion: 2,
  });
  assert.deepEqual(parseLiteLlmPricing({
    'vendor/model': {
      input_cost_per_token: 0.000001,
      output_cost_per_token: 0.000002,
      cache_read_input_token_cost: 0.0000001,
      cache_creation_input_token_cost: 0.00000125,
      cache_creation_input_token_cost_above_1hr: 0.000002,
    },
  })['vendor/model'], {
    inputPerMillion: 1,
    outputPerMillion: 2,
    cacheReadPerMillion: 0.1,
    cacheCreationPerMillion: 1.25,
    cacheCreationLongPerMillion: 2,
  });
});

test('gateway strips hop-by-hop and connection-nominated response headers', () => {
  const { filterProxyResponseHeaders } = require('../out/services/aiCliGateway');
  assert.deepEqual(filterProxyResponseHeaders({
    connection: 'keep-alive, x-remove-me',
    'keep-alive': 'timeout=5',
    'transfer-encoding': 'chunked',
    'x-remove-me': 'private',
    'content-type': 'application/json',
    'x-request-id': 'req-1',
  }), {
    'content-type': 'application/json',
    'x-request-id': 'req-1',
  });
});

test('gateway reuses one outbound proxy agent until proxy configuration changes', async () => {
  const { AiCliGateway } = require('../out/services/aiCliGateway');
  const gateway = new AiCliGateway();
  gateway.configureOutboundProxy({ url: 'http://127.0.0.1:7890' });
  const first = gateway.outboundAgent();
  const second = gateway.outboundAgent();
  assert.ok(first);
  assert.equal(first, second);
  gateway.configureOutboundProxy({ url: 'http://127.0.0.1:7891' });
  assert.notEqual(gateway.outboundAgent(), first);
  await gateway.stop();
});

test('gateway owns and releases reusable direct HTTP agents', async () => {
  const { AiCliGateway } = require('../out/services/aiCliGateway');
  const gateway = new AiCliGateway();
  const firstHttp = gateway.outboundAgent('http:');
  const firstHttps = gateway.outboundAgent('https:');
  assert.equal(gateway.outboundAgent('http:'), firstHttp);
  assert.equal(gateway.outboundAgent('https:'), firstHttps);
  assert.notEqual(firstHttp, firstHttps);
  await gateway.stop();
  assert.notEqual(gateway.outboundAgent('http:'), firstHttp);
  assert.notEqual(gateway.outboundAgent('https:'), firstHttps);
  await gateway.stop();
});

test('gateway aborts the upstream request when the downstream client disconnects', async () => {
  let finishUpstream;
  const upstreamClosed = new Promise((resolve) => { finishUpstream = resolve; });
  const upstream = http.createServer((req) => {
    req.once('aborted', finishUpstream);
    req.once('close', finishUpstream);
  });
  await new Promise((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  const upstreamPort = upstream.address().port;
  const { AiCliGateway } = require('../out/services/aiCliGateway');
  const gateway = new AiCliGateway(5_000);
  const status = await gateway.start({
    baseUrl: `http://127.0.0.1:${upstreamPort}`,
    apiKey: 'test',
    apiKind: 'anthropic',
  });
  const request = http.request(`${status.baseUrl}/v1/messages`, {
    method: 'POST',
    agent: false,
    headers: { 'content-type': 'application/json', authorization: `Bearer ${require('../out/services/aiCliGatewayUpstream').getOrCreateGatewayAuthToken()}` },
  });
  request.on('error', () => {});
  request.end(JSON.stringify({ model: 'claude-sonnet-4-6', messages: [] }));
  setTimeout(() => request.destroy(), 30);
  await Promise.race([
    upstreamClosed,
    new Promise((_, reject) => setTimeout(() => reject(new Error('upstream request remained open')), 1_000)),
  ]);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(gateway.getStatus().stats.activeConnections, 0);
  await gateway.stop();
  await new Promise((resolve) => upstream.close(resolve));
});

test('gateway terminates an idle upstream request with a bounded 504 response', async () => {
  const upstream = http.createServer(() => {});
  await new Promise((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  const upstreamPort = upstream.address().port;
  const { AiCliGateway } = require('../out/services/aiCliGateway');
  const gateway = new AiCliGateway(50);
  const status = await gateway.start({
    baseUrl: `http://127.0.0.1:${upstreamPort}`,
    apiKey: 'test',
    apiKind: 'anthropic',
  });
  const startedAt = Date.now();
  const result = await new Promise((resolve, reject) => {
    const request = http.request(`${status.baseUrl}/v1/messages`, {
      method: 'POST',
      agent: false,
      headers: { 'content-type': 'application/json', authorization: `Bearer ${require('../out/services/aiCliGatewayUpstream').getOrCreateGatewayAuthToken()}` },
    }, (response) => {
      response.resume();
      response.once('end', () => resolve({ status: response.statusCode, ms: Date.now() - startedAt }));
    });
    request.once('error', reject);
    request.end(JSON.stringify({ model: 'claude-sonnet-4-6', messages: [] }));
  });
  assert.equal(result.status, 504);
  assert.ok(result.ms < 1_000, `idle timeout took ${result.ms}ms`);
  await gateway.stop();
  await new Promise((resolve) => upstream.close(resolve));
});

test('gateway records the upstream response-cost header as authoritative USD cost', async () => {
  const upstream = http.createServer((_request, response) => {
    const body = JSON.stringify({
      model: 'unknown-vendor-model',
      usage: { input_tokens: 10, output_tokens: 2 },
      choices: [],
    });
    response.writeHead(200, {
      'content-type': 'application/json',
      'content-length': Buffer.byteLength(body),
      'x-litellm-response-cost': '0.123456',
    });
    response.end(body);
  });
  await new Promise((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  const upstreamPort = upstream.address().port;
  const { AiCliGateway } = require('../out/services/aiCliGateway');
  const gateway = new AiCliGateway();
  const records = [];
  gateway.onUsage((record) => records.push(record));
  const status = await gateway.start({
    baseUrl: `http://127.0.0.1:${upstreamPort}`,
    apiKey: 'test',
    apiKind: 'anthropic',
  });
  await new Promise((resolve, reject) => {
    const request = http.request(`${status.baseUrl}/v1/messages`, {
      method: 'POST',
      agent: false,
      headers: { 'content-type': 'application/json', authorization: `Bearer ${require('../out/services/aiCliGatewayUpstream').getOrCreateGatewayAuthToken()}` },
    }, (response) => {
      response.resume();
      response.once('end', resolve);
    });
    request.once('error', reject);
    request.end(JSON.stringify({ model: 'unknown-vendor-model', messages: [] }));
  });
  assert.equal(records.length, 1);
  assert.equal(records[0].reportedCostUsd, 0.123456);
  await gateway.stop();
  await new Promise((resolve) => upstream.close(resolve));
});

test('gateway start keeps authHeaderMode on the primary upstream', async () => {
  const { AiCliGateway } = require('../out/services/aiCliGateway');
  const gateway = new AiCliGateway();
  const status = await gateway.start({
    baseUrl: 'https://api.anthropic.com',
    apiKey: 'sk-test',
    apiKind: 'anthropic',
    authHeaderMode: 'x-api-key',
  });
  assert.equal(status.running, true);
  assert.equal(gateway.upstream.authHeaderMode, 'x-api-key');
  await assert.rejects(
    gateway.start({
      baseUrl: status.baseUrl,
      apiKey: 'loop',
      apiKind: 'anthropic',
    }),
    /gateway_upstream_points_to_itself/,
  );
  await gateway.stop();
});
