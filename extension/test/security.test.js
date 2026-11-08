const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const vm = require('node:vm');
const ts = require('typescript');
const { parse } = require('smol-toml');


function load(relative, dependencies = {}, extra = '') {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src', relative), 'utf8') + extra, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText;
  const exported = {};
  vm.runInNewContext(code, { exports: exported, Buffer, process, console, URL, setTimeout, clearTimeout,
    require: (name) => dependencies[name] ?? (name.startsWith('.') || name === 'vscode' ? {} : require(name)),
  });
  return exported;
}

function request(base, token) {
  return new Promise((resolve, reject) => {
    http.get(`${base}/v1/models`, { headers: token ? { authorization: `Bearer ${token}` } : {}, agent: false }, (response) => {
      response.resume(); response.on('end', () => resolve(response.statusCode));
    }).on('error', reject);
  });
}

test('half-open circuit admits one probe and recovers after success', () => {
  const cb = require('../out/services/gatewayFailover');
  const states = new Map(); const base = 'https://example.invalid';
  for (let i = 0; i < cb.FAILOVER_FAILURE_THRESHOLD; i++) cb.recordUpstreamFailure(states, base, 0);
  const state = states.get(base); const now = cb.FAILOVER_COOLDOWN_MS + 1;
  assert.equal(cb.isCircuitOpen(state, now), false);
  assert.equal(cb.isHalfOpen(state, now), true);
  state.halfOpen = true;
  assert.equal(cb.isCircuitOpen(state, now), true);
  cb.recordUpstreamSuccess(states, base);
  assert.equal(cb.upstreamHealth(states.get(base)), 'healthy');
});

test('gateway rejects missing, placeholder and incorrect credentials before upstream access', async (t) => {
  let calls = 0;
  const upstream = http.createServer((_req, res) => { calls++; res.end('{}'); });
  await new Promise((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => upstream.close(resolve)));
  const { AiCliGateway } = require('../out/services/aiCliGateway');
  const { getOrCreateGatewayAuthToken } = require('../out/services/aiCliGatewayUpstream');
  const gateway = new AiCliGateway(); t.after(() => gateway.stop());
  const status = await gateway.start({ baseUrl: `http://127.0.0.1:${upstream.address().port}`, apiKey: 'upstream-key', apiKind: 'openai' });
  for (const token of [undefined, 'agentsociety-gateway', 'wrong']) assert.equal(await request(status.baseUrl, token), 401);
  assert.equal(calls, 0);
  assert.equal(await request(status.baseUrl, getOrCreateGatewayAuthToken()), 200);
});

test('MCP serialization quotes ids, headers and env keys without dropping data', () => {
  const helpers = load('services/mcpServerManager.ts', {}, '\nexports.serialize = codexMcpBlockLines; exports.upsert = upsertCodexMcpBlocks; exports.claude = toClaudeMcpEntry;');
  const id = 'agentsociety-x]\n[mcp_servers.evil'; const header = 'X-Token\n[mcp_servers.other]';
  const server = { id, name: 'sample', transport: 'http', url: 'https://example.invalid', enabledCodex: true, httpHeaders: { [header]: 'value' }, env: { 'key.with.dot': 'value' } };
  const doc = parse(helpers.serialize(server).join('\n'));
  assert.deepEqual(Object.keys(doc.mcp_servers), [id]);
  assert.equal(doc.mcp_servers[id].http_headers[header], 'value');
  const stdio = parse(helpers.serialize({ ...server, transport: 'stdio', command: 'python' }).join('\n'));
  assert.equal(stdio.mcp_servers[id].env['key.with.dot'], 'value');
  const once = helpers.upsert('', [server]);
  assert.equal(helpers.upsert(once, [server]), once);
  assert.equal(helpers.claude({ ...server, transport: 'sse' }).type, 'sse');
  assert.throws(() => helpers.serialize({ ...server, transport: 'sse' }), /SSE/);
});

test('paper and PID data are escaped in rendered HTML', () => {
  const payload = '<img src=x onerror="PWN()">';
  const { PaperArtifactViewer } = load('paperArtifactViewer.ts');
  for (const data of [{ score: payload, dimensions: { [payload]: payload } }, { blocking_issues: [payload], summary: payload }]) {
    const html = PaperArtifactViewer.renderReview(data, 'review.json', false);
    assert.ok(!html.includes(payload)); assert.ok(html.includes('&lt;img'));
  }
  assert.ok(!PaperArtifactViewer.renderFigureArgMap({ [payload]: { figure_id: payload, roles: [payload], claim_ids: [payload] } }, 'map.json', false).includes(payload));
  const { PidStatusViewer } = load('pidStatusViewer.ts');
  assert.ok(!PidStatusViewer.prototype.getWebviewContent({ pid: payload, status: payload, experiment_id: payload, start_time: payload, end_time: payload, step_count: payload, simulation_time: payload }, false).includes(payload));
});

test('both shipped env templates require replacing API key placeholders', () => {
  const { hasConfiguredLlmApiKey } = load('runtimeConfig.ts');
  for (const llmApiKey of ['', '   ', 'your_api_key', 'your-api-key-here', 'sk-your-litellm-virtual-key', 'your-litellm-api-key']) {
    assert.equal(hasConfiguredLlmApiKey({ llmApiKey }), false, llmApiKey);
  }
  assert.equal(hasConfiguredLlmApiKey({ llmApiKey: 'a-real-provider-key' }), true);
});

test('model discovery returns only provider data and reports unsupported endpoints', async (t) => {
  const { fetchProviderModels } = require('../out/services/providerModels');
  const seen = [];
  let missing = false;
  const server = http.createServer((req, res) => {
    seen.push({ path: req.url, key: req.headers.authorization });
    if (missing || req.url !== '/api/v7/models') { res.writeHead(404); res.end(); return; }
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ data: [{ id: 'account-model-new' }, { id: 'account-model-new' }, null, { id: 42 }] }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const base = `http://127.0.0.1:${server.address().port}/api/v7`;
  const available = await fetchProviderModels(base, 'owned-test-key', 'openai');
  assert.equal(available.ok, true);
  assert.deepEqual(available.models, [{ id: 'account-model-new' }]);
  assert.deepEqual(seen, [{ path: '/api/v7/models', key: 'Bearer owned-test-key' }]);
  missing = true;
  const unavailable = await fetchProviderModels(base, 'owned-test-key', 'openai');
  assert.equal(unavailable.ok, false);
  assert.equal(unavailable.error, 'models_not_supported');
  const urls = [];
  const official = load('services/providerModels.ts', {
    '../aiCli/officialEndpoints': require('../out/aiCli/officialEndpoints'),
    './httpClient': { requestJson: async (url) => {
      urls.push(url);
      return { ok: true, status: 200, json: async () => ({ data: [{ id: 'official-account-only' }] }) };
    } },
  });
  const listed = await official.fetchProviderModels('https://api.openai.com/v1', 'owned-key', 'openai');
  assert.deepEqual(urls, ['https://api.openai.com/v1/models']);
  assert.equal(JSON.stringify(listed.models), '[{"id":"official-account-only"}]');
});

test('EasyPaper save preserves advanced settings and persists VLM disablement', (t) => {
  const os = require('node:os');
  const yaml = require('js-yaml');
  const { readEasyPaperConfig, writeEasyPaperConfig } = require('../out/services/easyPaperWorkspaceConfig');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'as2-paper-config-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const filename = path.join(directory, 'paper.yaml');
  const template = path.join(__dirname, '../plugins/easypaper/skills/easypaper-setup-environment/config.example.yaml');
  fs.writeFileSync(filename, yaml.dump({
    tools: { paper_search: { timeout: 37 } },
    skills: { venue_profile: 'custom-venue' },
    agents: [
      { name: 'writer', model: { model_name: 'before', temperature: 0.2 }, writer_config: { max_review_iterations: 7 } },
      { name: 'custom', model: { model_name: 'untouched' } },
      { name: 'vlm_review', vlm_review_config: { render_dpi: 200 } },
    ],
  }));
  const config = { llmModelName: 'account-model-new', llmApiKey: 'test-key', llmBaseUrl: 'https://example.invalid/v1', vlmEnabled: false, vlmProvider: 'openai', vlmModel: 'vision-custom', vlmApiKey: 'vision-key', vlmBaseUrl: 'https://example.invalid/v1' };
  writeEasyPaperConfig(filename, config, template);
  const saved = yaml.load(fs.readFileSync(filename, 'utf8'));
  assert.equal(saved.tools.paper_search.timeout, 37);
  assert.equal(saved.skills.venue_profile, 'custom-venue');
  assert.equal(saved.agents.find((a) => a.name === 'writer').writer_config.max_review_iterations, 7);
  assert.equal(saved.agents.find((a) => a.name === 'writer').model.temperature, 0.2);
  assert.equal(saved.agents.find((a) => a.name === 'custom').model.model_name, 'untouched');
  assert.equal(saved.agents.find((a) => a.name === 'vlm_review').vlm_review_config.render_dpi, 200);
  assert.equal(readEasyPaperConfig(filename).vlmEnabled, false);
  assert.equal(saved.agents.find((a) => a.name === 'vlm_review').vlm_review_config.enabled, false);
  assert.equal(fs.statSync(filename).mode & 0o777, 0o600);
  const before = fs.readFileSync(filename, 'utf8');
  assert.throws(() => writeEasyPaperConfig(filename, { ...config, llmModelName: '' }, template));
  assert.equal(fs.readFileSync(filename, 'utf8'), before);
});

function deviceLoginHarness(t) {
  const { EventEmitter } = require('node:events');
  const { PassThrough } = require('node:stream');
  const children = []; const states = [];
  const { CodexDeviceLogin } = load('services/codexDeviceLogin.ts', {
    child_process: { spawn(command, args, options) {
      assert.equal(command, 'codex');
      assert.deepEqual(Array.from(args), ['app-server', '--listen', 'stdio://']);
      const child = Object.assign(new EventEmitter(), {
        stdin: new PassThrough(), stdout: new PassThrough(), stderr: new PassThrough(), options, sent: [],
        kill() { this.killed = true; this.exitCode = 0; this.emit('close'); },
        reply(message) { this.stdout.write(`${JSON.stringify(message)}\n`); },
      });
      child.stdin.on('data', (line) => child.sent.push(JSON.parse(String(line))));
      children.push(child); return child;
    } },
  });
  const login = new CodexDeviceLogin((state) => states.push(state), 'test');
  t.after(() => login.dispose());
  const begin = () => {
    login.start({ HTTPS_PROXY: 'http://localhost:1234' });
    const child = children.at(-1); child.emit('spawn'); child.reply({ id: 1, result: { userAgent: 'test' } });
    return child;
  };
  const issued = { type: 'chatgptDeviceCode', loginId: 'private-login-id', userCode: 'TEST-CODE', verificationUrl: 'https://auth.openai.com/codex/device' };
  return { login, children, states, begin, issued };
}

test('device sign-in uses official RPC, cancels cleanly and ignores an earlier login completion', (t) => {
  const { login, children, begin, issued } = deviceLoginHarness(t);
  const first = begin(); login.start(); assert.equal(children.length, 1);
  assert.deepEqual(first.sent.map((m) => m.method), ['initialize', 'initialized', 'account/login/start']);
  assert.equal(first.sent[2].params.type, 'chatgptDeviceCode');
  assert.equal(first.options.env.HTTPS_PROXY, 'http://localhost:1234');
  assert.equal(first.options.env.PATH, process.env.PATH);
  first.reply({ id: 2, result: issued });
  assert.equal(login.snapshot().userCode, 'TEST-CODE');
  assert.equal(login.snapshot().loginId, undefined);
  login.cancel();
  assert.equal(first.sent.at(-1).method, 'account/login/cancel');
  assert.equal(login.snapshot().status, 'cancelled');
  assert.equal(login.snapshot().userCode, undefined);
  const second = begin(); assert.ok(first.killed);
  first.reply({ method: 'account/login/completed', params: { loginId: issued.loginId, success: true } });
  assert.equal(login.snapshot().status, 'starting');
  second.reply({ id: 2, result: issued });
  second.reply({ method: 'account/login/completed', params: { loginId: 'different', success: true } });
  assert.equal(login.snapshot().status, 'waiting');
  second.reply({ method: 'account/login/completed', params: { loginId: issued.loginId, success: true } });
  assert.equal(login.snapshot().status, 'success');
  assert.equal(login.snapshot().userCode, undefined); assert.ok(second.killed);
});

test('device sign-in rejects unofficial URLs and clears codes on failure, cancellation and disposal', (t) => {
  const { login, begin, issued, states } = deviceLoginHarness(t);
  for (const [message, code, expected, httpStatus] of [
    ['failed to request device code: device code request failed with status 403 Forbidden', -32603, 'requestRejected', 403],
    ['status 429 Too Many Requests', -32603, 'rateLimited', 429],
    ['HTTP 503 Service Unavailable', -32603, 'serviceUnavailable', 503],
    ['error sending request for url (https://auth.openai.com/api/accounts/deviceauth/usercode)', -32603, 'networkError'],
    ['certificate verify failed', -32603, 'tlsError'],
    ['unknown variant chatgptDeviceCode', -32602, 'unsupportedCli'],
    ['forced_login_method is api', -32603, 'policyBlocked'],
  ]) {
    begin().reply({ id: 2, error: { code, message } });
    assert.equal(login.snapshot().error, expected);
    assert.equal(login.snapshot().httpStatus, httpStatus);
    assert.equal(login.snapshot().rpcCode, code);
    assert.equal(login.snapshot().phase, 'requestingCode');
    assert.equal(login.snapshot().userCode, undefined);
  }
  for (const url of ['http://auth.openai.com/codex/device', 'https://auth.openai.com.example/codex/device', 'https://user@auth.openai.com/codex/device', 'https://auth.openai.com/other']) {
    begin().reply({ id: 2, result: { ...issued, verificationUrl: url } });
    assert.equal(login.snapshot().error, 'invalidResponse');
  }
  const failed = begin(); failed.reply({ id: 2, result: issued });
  failed.reply({ method: 'account/login/completed', params: { loginId: issued.loginId, success: false, error: 'private-server-details' } });
  assert.equal(login.snapshot().error, 'loginFailed');
  assert.equal(JSON.stringify(states).includes('private-server-details'), false);
  const missing = begin(); missing.emit('error', Object.assign(new Error('private-path'), { code: 'ENOENT' }));
  assert.equal(login.snapshot().error, 'missingCli');
  const expired = begin(); expired.reply({ id: 2, result: issued });
  expired.reply({ method: 'account/login/completed', params: { loginId: issued.loginId, success: false, error: 'device code expired' } });
  assert.equal(login.snapshot().error, 'expired');
  assert.equal(login.snapshot().phase, 'authorizing');
  const cancelled = begin(); login.cancel(); assert.ok(cancelled.killed);
  assert.equal(login.snapshot().status, 'cancelled');
  const closed = begin(); closed.emit('close'); assert.equal(login.snapshot().error, 'processExited');
  const disposed = begin(); disposed.reply({ id: 2, result: issued });
  login.dispose(); assert.ok(disposed.killed); assert.equal(login.snapshot().userCode, undefined);
});

test('device sign-in opens the browser when clipboard access fails and reports each action separately', async () => {
  const messages = []; const opened = [];
  const { ConfigPageViewProvider } = load('configPageViewProvider.ts', {
    vscode: { env: {
      clipboard: { writeText: async () => { throw new Error('clipboard unavailable'); } },
      openExternal: async (url) => { opened.push(url); return true; },
    }, Uri: { parse: (url) => url } },
  });
  const panel = Object.create(ConfigPageViewProvider.prototype);
  let state = { status: 'waiting', userCode: 'TEST-CODE', verificationUrl: 'https://auth.openai.com/codex/device' };
  panel._codexDeviceLogin = { snapshot: () => state };
  panel._panel = { webview: { postMessage: async (message) => { messages.push(message); } } };
  await panel._handleCodexDeviceLoginAction('copyAndOpen');
  assert.deepEqual(opened, [state.verificationUrl]);
  assert.equal(messages[0].command, 'codexDeviceLoginActionError');
  assert.equal(messages[0].action, 'copy');
  state = { status: 'error' };
  await panel._handleCodexDeviceLoginAction('open'); assert.equal(opened.length, 1);
  await panel._handleCodexDeviceLoginAction('help');
  assert.equal(opened.at(-1), 'https://developers.openai.com/codex/auth');
  assert.equal(JSON.stringify(messages).includes('TEST-CODE'), false);
});

test('CLI primary selection enforces subscription and API protocol compatibility', async () => {
  const auth = require('../out/aiCli/providerAuth');
  const { providerSupportsRole, clampProviderRoleFlags } = auth;
  for (const [baseUrl, apiKind, authMode, claude, codex] of [
    ['https://api.openai.com/v1', 'openai', 'subscription', false, true],
    ['https://api.anthropic.com', 'anthropic', 'subscription', true, false],
    ['https://custom.example/v1', 'openai', 'subscription', false, false],
    ['https://custom.example/v1', 'openai', 'api', true, true],
    ['https://custom.example', 'anthropic', 'api', true, false],
  ]) {
    const provider = { baseUrl, apiKind, authMode, apiKey: 'test', activeClaude: true, activeCodex: true };
    assert.equal(providerSupportsRole(provider, 'claude'), claude);
    assert.equal(providerSupportsRole(provider, 'codex'), codex);
    const normalized = clampProviderRoleFlags(provider);
    assert.equal(normalized.activeClaude, claude); assert.equal(normalized.activeCodex, codex);
  }
  const { AiCliGatewayManager } = load('services/aiCliGatewayManager.ts', {
    '../aiCli/providerAuth': auth,
    './codexSettings': { detectCodexOfficialLogin: async () => ({ present: true }) },
  });
  const manager = Object.create(AiCliGatewayManager.prototype);
  let providers = [
    { id: 'subscription', baseUrl: 'https://api.openai.com/v1', apiKind: 'openai', authMode: 'subscription', apiKey: '', activeClaude: false, activeCodex: false },
    { id: 'api', baseUrl: 'https://owned.example/v1', apiKind: 'openai', authMode: 'api', apiKey: 'test', activeClaude: true, activeCodex: true },
  ];
  manager.initialize = async () => {}; manager.getProviders = () => providers.map((p) => ({ ...p }));
  manager.normalizeProvider = clampProviderRoleFlags; manager.saveProviders = async (next) => { providers = next; };
  manager.applyActiveCodexProvider = async () => ({}); manager.getPublicStatus = () => ({});
  manager.yieldCodexRouteToOfficialLoginIfNeeded = async () => { throw new Error('Unexpected route change'); };
  await manager.refreshCodexOfficialLogin({ preserveRoute: true });
  await assert.rejects(() => manager.activateProvider('subscription', 'claude'), /not_eligible_for_claude/);
  await manager.activateProvider('subscription', 'codex');
  assert.equal(providers[0].activeCodex, true); assert.equal(providers[1].activeCodex, false);
  assert.equal(providers[1].activeClaude, true);
});
