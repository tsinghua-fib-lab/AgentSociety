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
    headers: { 'content-type': 'application/json' },
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
      headers: { 'content-type': 'application/json' },
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
      headers: { 'content-type': 'application/json' },
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
