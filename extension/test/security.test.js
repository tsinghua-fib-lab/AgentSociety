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

test('MCP editor preserves argument boundaries and validates environment/header maps', () => {
  const { parseMcpArgs, parseMcpStringMap } = require('../out/shared/mcpServerDraft');
  assert.deepEqual(parseMcpArgs('["--name=a,b", "a path with spaces", "line\\nnext"]'), ['--name=a,b', 'a path with spaces', 'line\nnext']);
  assert.deepEqual(parseMcpStringMap('{"API_KEY":"private","X-Custom":"a,b"}'), { API_KEY: 'private', 'X-Custom': 'a,b' });
  for (const value of ['{"name":"wrong"}', '[1]', 'not JSON']) assert.throws(() => parseMcpArgs(value));
  for (const value of ['[]', 'null', '{"key":12}']) assert.throws(() => parseMcpStringMap(value));
});

test('MCP probe preserves endpoints and sessions, reads open SSE streams and all tool pages', async (t) => {
  const { probeHttpMcpServer, normalizeMcpHttpEndpoint } = require('../out/services/mcpClient');
  const calls = [];
  let released = false, streamClosed = false;
  const server = http.createServer(async (req, res) => {
    assert.equal(req.url, '/rpc/research?tenant=fixture');
    assert.equal(req.headers.authorization, 'Bearer fixture');
    if (req.method === 'DELETE') { released = true; res.writeHead(204); res.end(); return; }
    let text = ''; for await (const chunk of req) text += chunk;
    const body = JSON.parse(text); calls.push(body.method);
    if (body.method === 'initialize') {
      res.setHeader('Mcp-Session-Id', 'test-session'); res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ jsonrpc: '2.0', id: body.id, result: { protocolVersion: '2025-11-25', capabilities: { tools: {} } } })); return;
    }
    assert.equal(req.headers['mcp-session-id'], 'test-session');
    assert.equal(req.headers['mcp-protocol-version'], '2025-11-25');
    if (body.method === 'notifications/initialized') { res.writeHead(202); res.end(); return; }
    assert.equal(body.method, 'tools/list');
    if (body.params.cursor) {
      assert.equal(body.params.cursor, 'page-two'); res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ jsonrpc: '2.0', id: body.id, result: { tools: [{ name: 'paper_get' }, { name: 'paper_search' }] } })); return;
    }
    res.setHeader('content-type', 'text/event-stream');
    res.write('data: {"jsonrpc":"2.0","method":"notifications/progress"}\r\n\r\n');
    res.write('data: ' + JSON.stringify({ jsonrpc: '2.0', id: body.id, result: { tools: [{ name: 'paper_search' }], nextCursor: 'page-two' } }) + '\r\n\r\n');
    res.once('close', () => { streamClosed = true; });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); return new Promise((resolve) => server.close(resolve)); });
  const endpoint = `http://127.0.0.1:${server.address().port}/rpc/research?tenant=fixture`;
  assert.equal(normalizeMcpHttpEndpoint(endpoint), endpoint);
  for (const url of ['file:///tmp/mcp', 'https://user:secret@example.invalid/mcp', 'https://example.invalid/mcp#bad']) assert.equal(normalizeMcpHttpEndpoint(url), null);
  const result = await probeHttpMcpServer(endpoint, { Authorization: 'Bearer fixture' });
  assert.equal(result.ok, true);
  assert.deepEqual(result.tools, ['paper_search', 'paper_get']);
  assert.deepEqual(calls, ['initialize', 'notifications/initialized', 'tools/list', 'tools/list']);
  assert.equal(released, true);
  assert.equal(streamClosed, true);
});

test('MCP probe handles resources-only servers and rejects JSON-RPC errors and redirects', async (t) => {
  const { probeHttpMcpServer } = require('../out/services/mcpClient');
  const server = http.createServer(async (req, res) => {
    if (req.url === '/redirect') { res.writeHead(307, { location: '/unexpected' }); res.end(); return; }
    assert.notEqual(req.url, '/unexpected');
    let text = ''; for await (const chunk of req) text += chunk;
    const body = JSON.parse(text); res.setHeader('content-type', 'application/json');
    if (req.url === '/resources') {
      if (body.method === 'initialize') { res.end(JSON.stringify({ jsonrpc: '2.0', id: body.id, result: { protocolVersion: '2025-11-25', capabilities: { resources: {} } } })); return; }
      assert.equal(body.method, 'notifications/initialized'); res.writeHead(202); res.end(); return;
    }
    res.end(JSON.stringify({ jsonrpc: '2.0', id: body.id, error: { code: -32603, message: 'private server detail' } }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); return new Promise((resolve) => server.close(resolve)); });
  const result = await probeHttpMcpServer(`http://127.0.0.1:${server.address().port}/rpc`);
  assert.equal(result.ok, false); assert.equal(result.status, 200);
  assert.ok(!result.error.includes('private server detail'));
  const resources = await probeHttpMcpServer(`http://127.0.0.1:${server.address().port}/resources`);
  assert.equal(resources.ok, true); assert.deepEqual(resources.tools, []);
  const redirect = await probeHttpMcpServer(`http://127.0.0.1:${server.address().port}/redirect`);
  assert.equal(redirect.ok, false); assert.equal(redirect.status, 307);
});

test('literature library embeds valid JavaScript and safely encodes index metadata', () => {
  const { LiteratureIndexViewer } = load('literatureIndexViewer.ts', {
    vscode: { workspace: { workspaceFolders: [{ uri: { fsPath: '/fixture' } }] } },
    './i18n': { isExtensionZh: () => true },
    './atReference': { filePathToAtReference: () => '@paper.md' },
  });
  const panel = { webview: { html: '' } };
  const payload = '</script><img src=x onerror="PWN()">';
  LiteratureIndexViewer.updateWebview(panel, { entries: [{ title: payload, keywords: [payload] }] }, '/fixture/index.json');
  assert.ok(!panel.webview.html.includes(payload));
  const scripts = [...panel.webview.html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1);
  assert.doesNotThrow(() => new vm.Script(scripts[0][1]));
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

test('MCP registry queries latest versions and follows opaque cursors without running servers', async (t) => {
  const { registryRequestUrl, parseRegistryPage, fetchRegistryPage } = require('../out/services/mcpRegistry');
  const seen = [];
  const server = http.createServer((req, res) => {
    seen.push(req.url);
    if (req.url.startsWith('/redirect/')) { res.writeHead(302, { Location: '/registry/servers' }); res.end(); return; }
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ servers: [null, { server: { name: 'old', version: '1' }, _meta: { 'io.modelcontextprotocol.registry/official': { status: 'deleted' } } },
      { server: { name: 'org.example/search', version: '2', remotes: [null, { type: 'streamable-http', url: 'https://example.invalid/mcp' }] } }], metadata: { nextCursor: 'name:a/b=2+3' } }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const source = `http://127.0.0.1:${server.address().port}/registry`;
  const url = new URL(registryRequestUrl(source, ' search ', 'name:a/b=2+3'));
  assert.equal(url.searchParams.get('version'), 'latest'); assert.equal(url.searchParams.get('search'), 'search');
  assert.equal(url.searchParams.get('cursor'), 'name:a/b=2+3');
  const page = await fetchRegistryPage({ source, search: 'search', cursor: 'name:a/b=2+3' });
  assert.deepEqual(page.servers.map((row) => row.name), ['org.example/search']);
  assert.equal(page.servers[0].remotes.length, 1); assert.equal(page.nextCursor, 'name:a/b=2+3');
  await assert.rejects(fetchRegistryPage({ source: source.replace('/registry', '/redirect') }), /registry_http_302/);
  assert.equal(seen.length, 2); assert.throws(() => parseRegistryPage({}), /invalid_registry_response/);
  assert.throws(() => registryRequestUrl('https://user:secret@example.invalid'), /invalid_registry_source/);
});

test('MCP registry templates preserve argv boundaries, variables and client opt-in', () => {
  const { registryVariants, resolveRegistryServer } = require('../out/shared/mcpRegistry');
  const server = { name: 'org.example/search', version: '2', remotes: [{ type: 'streamable-http', url: '{baseUrl}/mcp', variables: { baseUrl: { isRequired: true } }, headers: [{ name: 'Authorization', value: 'Bearer {token}', variables: { token: { isRequired: true, isSecret: true } } }] }], packages: [
    { registryType: 'npm', identifier: '@example/mcp', version: '2.1.0', transport: { type: 'stdio' }, packageArguments: [{ type: 'named', name: '--path', isRequired: true }, { type: 'positional', value: '{literal}' }], environmentVariables: [{ name: 'TOKEN', isRequired: true }] },
    { registryType: 'pypi', identifier: 'example-mcp', version: '2.1.0', registryBaseUrl: 'https://pypi.org', transport: { type: 'stdio' } },
    { registryType: 'oci', identifier: 'ghcr.io/example/mcp', version: '2.1.0', transport: { type: 'stdio' }, environmentVariables: [{ name: 'TOKEN', value: 'public-default' }] },
  ] };
  const variants = registryVariants(server);
  assert.throws(() => resolveRegistryServer(server, variants[0], {}), /required/);
  const remote = resolveRegistryServer(server, variants[0], { baseUrl: 'https://example.invalid', 'header:Authorization:variable:token': 'owned-token' });
  assert.equal(remote.url, 'https://example.invalid/mcp'); assert.equal(remote.httpHeaders.Authorization, 'Bearer owned-token');
  assert.equal(remote.enabledClaude, false); assert.equal(remote.enabledCodex, false);
  const scoped = { remote: { type: 'streamable-http', url: 'https://example.invalid/mcp', headers: ['One', 'Two'].map((name) => ({ name, value: '{token}', variables: { token: { isSecret: true } } })) } };
  assert.deepEqual(resolveRegistryServer(server, scoped, { 'header:One:variable:token': 'first', 'header:Two:variable:token': 'second' }).httpHeaders, { One: 'first', Two: 'second' });
  const npm = resolveRegistryServer(server, variants[1], { '--path': 'a folder;$(literal)', TOKEN: 'owned-token' });
  assert.deepEqual(npm.args, ['-y', '@example/mcp@2.1.0', '--path', 'a folder;$(literal)', '{literal}']);
  assert.equal(npm.env.TOKEN, 'owned-token');
  assert.deepEqual(resolveRegistryServer(server, variants[2], {}).args, ['--index-url', 'https://pypi.org/simple', '--from', 'example-mcp==2.1.0', 'example-mcp']);
  assert.deepEqual(resolveRegistryServer(server, variants[3], {}).args, ['run', '--rm', '-i', '-e', 'TOKEN', 'ghcr.io/example/mcp:2.1.0']);
  assert.throws(() => resolveRegistryServer(server, { package: { ...server.packages[0], fileSha256: 'a'.repeat(64) } }, { '--path': 'a', TOKEN: 'x' }), /registry_integrity_required/);
  const repeated = { package: { ...server.packages[0], environmentVariables: [], packageArguments: [{ type: 'named', name: '--scope', isRepeated: true }] } };
  assert.deepEqual(resolveRegistryServer(server, repeated, { '--scope': '["a b", "c"]' }).args.slice(-4), ['--scope', 'a b', '--scope', 'c']);
});

function mcpImportHarness() {
  const client = require('../out/services/mcpClient');
  return load('services/mcpImport.ts', { './mcpClient': client });
}

test('MCP import previews conflicts, isolates invalid rows and retains tool restrictions', () => {
  const { parseMcpImport, applyMcpImport, managedMcpId } = mcpImportHarness();
  const source = '[mcp_servers.research]\nurl="https://example.invalid/mcp"\nbearer_token_env_var="TOKEN"\nenabled_tools=["search"]\ndisabled_tools=["delete"]\ntool_timeout_sec=25\n[mcp_servers.research.http_headers]\nX-Scope="read"';
  const items = parseMcpImport(source, 'codex', []);
  assert.equal(items[0].state, 'new'); assert.equal(items[0].server.id, 'research');
  assert.equal(items[0].server.codexOptions.tool_timeout_sec, 25);
  assert.equal(items[0].server.codexOptions.enabled_tools[0], 'search');
  const imported = applyMcpImport([], items, ['research'], { claude: false, codex: false });
  assert.equal(imported.added, 1); assert.equal(imported.servers[0].enabledCodex, true);
  assert.equal(parseMcpImport(source, 'codex', imported.servers)[0].state, 'same');
  const conflict = parseMcpImport(source.replace('25', '26'), 'codex', imported.servers);
  assert.equal(conflict[0].state, 'conflict');
  assert.equal(applyMcpImport(imported.servers, conflict, [], { claude: false, codex: false }).servers[0].codexOptions.tool_timeout_sec, 25);
  const mixed = parseMcpImport(JSON.stringify({ mcpServers: { good: { command: 'python', args: ['two words'], env: { TOKEN: 'owned' } }, bad: { command: 1 }, legacy: { type: 'sse', url: 'https://example.invalid/sse' } } }), 'paste', []);
  assert.equal(mixed[0].state, 'new'); assert.equal(mixed[1].state, 'invalid');
  assert.throws(() => applyMcpImport([], mixed, ['legacy'], { codex: true, claude: false }), /sse_claude_only/);
  assert.notEqual(managedMcpId('文献'), managedMcpId('检索')); assert.notEqual(managedMcpId('a_b'), managedMcpId('a-b'));
});

function mcpManagerHarness(t) {
  const os = require('node:os');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'as2-mcp-import-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const codex = path.join(directory, 'config.toml'), claude = path.join(directory, '.claude.json');
  const state = new Map();
  const { McpServerManager } = load('services/mcpServerManager.ts', {
    os: { homedir: () => directory }, '../envManager': { EnvManager: class { readEnv() { return {}; } } },
    './mcpImport': mcpImportHarness(), './codexSettings': {
      readCodexConfigText: () => fs.existsSync(codex) ? fs.readFileSync(codex, 'utf8') : '',
      writeCodexConfigText: (text) => fs.writeFileSync(codex, text),
    },
  });
  const manager = new McpServerManager({ globalState: { get: (key) => state.get(key), update: async (key, value) => state.set(key, value) } });
  return { manager, codex, claude, state };
}

test('MCP import sync preserves unrelated settings and removes adopted IDs from both clients', async (t) => {
  const { manager, codex, claude } = mcpManagerHarness(t);
  fs.writeFileSync(codex, '# retain this comment\nmodel="owned-model"\n[mcp_servers.research]\nurl="https://example.invalid/mcp"\nenabled_tools=["search"]\ntool_timeout_sec=25\n[mcp_servers.research.http_headers]\nX-Scope="read"\n[mcp_servers.unselected]\ncommand="owned-command"\n');
  fs.writeFileSync(claude, JSON.stringify({ theme: 'owned-theme', mcpServers: { unrelated: { command: 'owned' } } }));
  const preview = manager.previewImport('codex');
  await manager.applyImport(preview.token, ['research'], { claude: true, codex: false });
  let saved = parse(fs.readFileSync(codex, 'utf8'));
  assert.equal(saved.model, 'owned-model'); assert.equal(saved.mcp_servers.unselected.command, 'owned-command');
  assert.equal(saved.mcp_servers.research.enabled_tools[0], 'search'); assert.equal(saved.mcp_servers.research.tool_timeout_sec, 25);
  assert.equal(saved.mcp_servers.research.http_headers['X-Scope'], 'read');
  assert.ok(fs.readFileSync(codex, 'utf8').includes('# retain this comment'));
  assert.equal(JSON.parse(fs.readFileSync(claude)).mcpServers.research.headers['X-Scope'], 'read');
  await manager.toggleServerApp('research', 'codex', false);
  assert.equal(parse(fs.readFileSync(codex, 'utf8')).mcp_servers.research, undefined);
  await manager.removeServer('research');
  assert.equal(JSON.parse(fs.readFileSync(claude)).mcpServers.research, undefined);
  assert.equal(JSON.parse(fs.readFileSync(claude)).theme, 'owned-theme');
  assert.equal(parse(fs.readFileSync(codex, 'utf8')).mcp_servers.unselected.command, 'owned-command');
});

test('MCP import refuses stale previews and protects malformed or unsupported client files', async (t) => {
  const { manager, codex, claude, state } = mcpManagerHarness(t);
  const text = JSON.stringify({ mcpServers: { new: { command: 'owned-command' } } });
  fs.writeFileSync(claude, '{"theme":"owned"}\n'); fs.writeFileSync(codex, 'model="owned"\n');
  const inventory = manager.previewImport('paste', text);
  await manager.applyImport(inventory.token, ['new'], { claude: false, codex: false });
  assert.equal(fs.readFileSync(claude, 'utf8'), '{"theme":"owned"}\n'); assert.equal(fs.readFileSync(codex, 'utf8'), 'model="owned"\n');
  const preview = manager.previewImport('paste', text);
  state.set('agentsociety.mcpServers.v1', [{ id: 'other', name: 'Other', command: 'owned', transport: 'stdio', enabledClaude: false, enabledCodex: false }]);
  await assert.rejects(manager.applyImport(preview.token, ['new'], { claude: true, codex: false }), /mcp_import_changed/);
  assert.equal(fs.readFileSync(claude, 'utf8'), '{"theme":"owned"}\n');
  fs.writeFileSync(claude, '{"broken":'); fs.writeFileSync(codex, 'model="owned"\n');
  await assert.rejects(manager.syncLiveConfigs(), /invalid_claude_config/);
  assert.equal(fs.readFileSync(claude, 'utf8'), '{"broken":'); assert.equal(fs.readFileSync(codex, 'utf8'), 'model="owned"\n');
  fs.writeFileSync(claude, '{}'); fs.writeFileSync(codex, 'mcp_servers={other={command="owned"}}\n');
  await assert.rejects(manager.toggleServerApp('other', 'codex', true));
  assert.equal(fs.readFileSync(codex, 'utf8'), 'mcp_servers={other={command="owned"}}\n');
});

test('Web provider import updates only selected clients and preserves permission policy', async () => {
  const writes = [];
  const { AiCliGatewayManager } = load('services/aiCliGatewayManager.ts', {
    '../aiCli/officialEndpoints': require('../out/aiCli/officialEndpoints'),
    '../aiCli/providerAuth': require('../out/aiCli/providerAuth'),
    './claudeCodeSettings': { readClaudeConfig: () => ({ permissionMode: 'default' }), writeClaudeConfig: (config) => writes.push(['claude', config]) },
  });
  const manager = Object.create(AiCliGatewayManager.prototype);
  let providers = [{ id: 'owned', name: 'Owned', baseUrl: 'https://owned.example/v1', apiKind: 'openai', authMode: 'api', apiKey: 'old-key', model: 'old-model', codexModel: 'old-model', activeClaude: true, activeCodex: true }];
  manager.initialize = async () => {}; manager.getProviders = () => providers.map((p) => ({ ...p }));
  manager.normalizeProvider = (provider) => ({ ...provider }); manager.saveProviders = async (next) => { providers = next; };
  manager.projectCodexProviderLive = async (provider) => writes.push(['codex', provider]);
  manager.providerToClaudeConfig = (provider) => ({ model: provider.model, permissionMode: provider.permissionMode });
  manager.providerToGatewayUpstream = () => ({}); manager.persistUpstream = async () => {};
  const draft = { name: 'Imported', baseUrl: 'https://owned.example/v1', apiKind: 'openai', apiKey: 'new-key', model: 'new-model', codexModel: 'new-model', permissionMode: 'bypassPermissions' };
  await manager.upsertImportedGatewayProvider(draft, { targets: { claude: false, codex: true } });
  assert.deepEqual(writes.map(([role]) => role), ['codex']);
  const original = providers.find((p) => p.id === 'owned'); assert.equal(original.apiKey, 'old-key'); assert.equal(original.activeClaude, true); assert.equal(original.activeCodex, false);
  assert.equal(providers.find((p) => p.activeCodex).permissionMode, 'default');
  writes.length = 0;
  await manager.upsertImportedGatewayProvider({ ...draft, apiKey: 'inventory-key' }, { targets: { claude: false, codex: false } });
  assert.equal(writes.length, 0); assert.equal(providers.find((p) => p.activeClaude).id, 'owned');
  await manager.upsertImportedGatewayProvider(draft, { targets: { claude: true, codex: false } });
  assert.deepEqual(writes.map(([role]) => role), ['claude']); assert.equal(writes[0][1].permissionMode, 'default');
  providers = [{ ...original, activeClaude: false, activeCodex: false, failoverClaude: true }];
  writes.length = 0;
  await manager.upsertImportedGatewayProvider(draft, { targets: { claude: false, codex: false } });
  assert.equal(providers.find((p) => p.id === 'owned').apiKey, 'old-key'); assert.equal(writes.length, 0);
});

test('LLM validation sends thinking controls on the selected protocol and detects ignored disable requests', async () => {
  const sent = []; let reply = { choices: [{ message: { content: 'OK', reasoning_content: 'fixture reasoning' } }] };
  const { LLMValidator } = load('services/llmValidator.ts', {
    './httpClient': { requestJson: async (url, request) => { sent.push({ url, request }); return { ok: true, status: 200, data: reply }; } },
    './validateTimeouts': { CONFIG_PAGE_API_VALIDATE_TIMEOUT_MS: 15000 },
    '../shared/outputChannels': { getMainOutputChannel: () => ({ appendLine() {} }) },
  });
  const validator = new LLMValidator();
  const config = { apiBase: 'https://owned.example/custom/v1', apiKey: 'owned-fixture', model: 'new-model-alias', thinking: 'off' };
  let result = await validator.validate(config);
  assert.equal(result.success, false); assert.match(result.error, /仍返回推理内容/);
  assert.equal(sent[0].request.body.reasoning_effort, 'none');
  reply = { content: [{ type: 'text', text: 'OK' }] };
  result = await validator.validate({ ...config, apiType: 'anthropic' });
  assert.equal(result.success, true); assert.equal(sent[1].url, 'https://owned.example/custom/v1/messages');
  assert.equal(sent[1].request.body.thinking.type, 'disabled'); assert.equal(sent[1].request.headers['x-api-key'], 'owned-fixture');
  await validator.validate({ ...config, apiType: 'anthropic', thinking: 'on' });
  assert.equal(sent[2].request.body.thinking.type, 'enabled'); assert.equal(sent[2].request.body.thinking.budget_tokens, 1024);
  await validator.validate({ ...config, thinking: 'off', extraBody: '{"chat_template_kwargs":{"enable_thinking":true,"custom":7}}' });
  assert.equal(sent[3].request.body.reasoning_effort, undefined); assert.equal(sent[3].request.body.chat_template_kwargs.enable_thinking, false);
  assert.equal(sent[3].request.body.chat_template_kwargs.custom, 7);
  await validator.validate({ ...config, thinking: '' });
  assert.equal(sent[4].request.body.reasoning_effort, undefined); assert.equal(sent[4].request.body.thinking, undefined);
});

test('Bedrock thinking optimization preserves explicit disable instructions', () => {
  const { optimizeBedrockThinking } = require('../out/services/bedrockRequestOptimizer');
  for (const model of ['claude-sonnet-4-6', 'claude-sonnet-4-5']) {
    const request = { model, thinking: { type: 'disabled' }, max_tokens: 2048 };
    assert.equal(optimizeBedrockThinking(request, { enabled: true, thinkingOptimizer: true, cacheInjection: false }), request);
  }
});

test('LLM validation translates explicit control formats while default mode leaves the request unchanged', async () => {
  let body;
  const { LLMValidator } = load('services/llmValidator.ts', {
    './httpClient': { requestJson: async (_url, request) => { body = request.body; return { ok: true, status: 200, data: { choices: [{ message: { content: 'OK', thinking_blocks: [{ type: 'thinking', thinking: '' }] } }] } }; } },
    './validateTimeouts': { CONFIG_PAGE_API_VALIDATE_TIMEOUT_MS: 15000 },
    '../shared/outputChannels': { getMainOutputChannel: () => ({ appendLine() {} }) },
  });
  const validator = new LLMValidator();
  const config = { apiBase: 'https://owned.example/v1', apiKey: 'fixture', model: 'arbitrary-alias', extraBody: '{"custom":7}' };
  for (const thinkingFormat of ['thinking', 'enable_thinking', 'chat_template_kwargs', 'reasoning']) {
    for (const thinking of ['on', 'off']) {
      const result = await validator.validate({ ...config, thinking, thinkingFormat });
      assert.equal(result.success, true); assert.equal(body.custom, 7); assert.equal(body.reasoning_effort, undefined);
      const expected = thinking === 'on';
      if (thinkingFormat === 'thinking') assert.equal(body.thinking.type, expected ? 'enabled' : 'disabled');
      if (thinkingFormat === 'enable_thinking') assert.equal(body.enable_thinking, expected);
      if (thinkingFormat === 'chat_template_kwargs') assert.equal(body.chat_template_kwargs.enable_thinking, expected);
      if (thinkingFormat === 'reasoning') assert.equal(body.reasoning.enabled, expected);
    }
    await validator.validate({ ...config, thinking: '', thinkingFormat });
    assert.equal(body.reasoning_effort, undefined); assert.equal(body[thinkingFormat], undefined); assert.equal(body.custom, undefined);
  }
});

test('quoted JSON reasoning settings reach the runtime while their .env lines remain intact', (t) => {
  const os = require('node:os');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'as2-thinking-env-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const { EnvManager } = load('envManager.ts', {
    vscode: { workspace: { workspaceFolders: [{ uri: { fsPath: directory } }] } },
    './shared/outputChannels': { getMainOutputChannel: () => ({ appendLine() {} }) },
  });
  const filename = path.join(directory, '.env'), json = '{"enable_thinking":false,"custom":7}';
  for (const text of [json, "'" + json + "'", JSON.stringify(json)]) {
    const original = 'AGENTSOCIETY_LLM_EXTRA_BODY=' + text + '\nAGENTSOCIETY_CODER_LLM_EXTRA_BODY=' + text + '\n';
    fs.writeFileSync(filename, original);
    const manager = new EnvManager();
    const read = manager.readEnv();
    assert.equal(JSON.parse(read.llmExtraBody).enable_thinking, false);
    assert.equal(JSON.parse(read.coderLlmExtraBody).custom, 7);
    manager.writeEnv({ llmThinking: 'off', llmThinkingFormat: 'enable_thinking' });
    const saved = fs.readFileSync(filename, 'utf8'); assert.ok(saved.startsWith(original));
    assert.equal(manager.readEnv().llmThinkingFormat, 'enable_thinking');
  }
});

test('MCP endpoint checks distinguish authentication challenges from access failures without exposing metadata', async (t) => {
  const { probeHttpMcpServer } = require('../out/services/mcpClient');
  const server = http.createServer(async (req, res) => {
    let text = ''; for await (const chunk of req) text += chunk;
    if (req.method === 'DELETE') { res.writeHead(204); res.end(); return; }
    const body = JSON.parse(text);
    if (req.url === '/needs-login') {
      res.writeHead(401, { 'www-authenticate': 'Bearer resource_metadata="https://auth.example/private-metadata"' }); res.end('private diagnostic'); return;
    }
    if (req.url === '/denied') { res.writeHead(403); res.end(); return; }
    if (body.method === 'initialize') { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ jsonrpc: '2.0', id: body.id, result: { protocolVersion: '2025-11-25', capabilities: { tools: {} } } })); return; }
    if (body.method === 'notifications/initialized') { res.writeHead(202); res.end(); return; }
    res.writeHead(403, { 'www-authenticate': 'Bearer error="insufficient_scope", scope="private-scope"' }); res.end();
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); return new Promise((resolve) => server.close(resolve)); });
  const base = `http://127.0.0.1:${server.address().port}`;
  for (const endpoint of ['/needs-login', '/needs-scope']) {
    const result = await probeHttpMcpServer(base + endpoint);
    assert.equal(result.authRequired, true); assert.equal(result.error, 'mcp_auth_required');
    assert.ok(!JSON.stringify(result).includes('private'));
  }
  const denied = await probeHttpMcpServer(base + '/denied');
  assert.equal(denied.ok, false); assert.equal(denied.status, 403); assert.equal(denied.authRequired, undefined);
});

test('MCP OAuth starts the selected official CLI, reuses running login and rejects disabled clients or unsafe IDs', async () => {
  const terminals = [], calls = [], created = [];
  const proxy = { HTTPS_PROXY: 'http://127.0.0.1:12345' };
  const vscode = { env: { remoteName: 'ssh-remote' }, workspace: { workspaceFolders: [{ uri: { fsPath: '/owned' } }] }, window: {
    terminals, createTerminal: (options) => { created.push(options); const terminal = { name: options.name, show: () => {}, exitStatus: undefined }; terminals.push(terminal); return terminal; },
  } };
  let failure;
  const { openMcpAuthentication } = load('services/mcpAuthentication.ts', {
    vscode, './mcpClient': require('../out/services/mcpClient'),
    child_process: { execFile: (app, args, options, callback) => { calls.push({ app, args, options }); callback(failure, 'Usage: mcp login --no-browser'); } },
  });
  const server = { id: 'agentsociety-notes', transport: 'http', url: 'https://example.invalid/mcp', enabledCodex: true, enabledClaude: true };
  await openMcpAuthentication(server, 'codex', proxy);
  assert.equal(calls.length, 1); assert.equal(calls[0].app, 'codex'); assert.deepEqual(Array.from(calls[0].args), ['mcp', 'login', '--help']);
  assert.deepEqual(Array.from(created[0].shellArgs), ['mcp', 'login', server.id, '--no-browser']); assert.equal(created[0].env, proxy);
  await openMcpAuthentication(server, 'codex', proxy); assert.equal(calls.length, 1); assert.equal(created.length, 1);
  terminals[0].exitStatus = { code: 0 };
  await openMcpAuthentication(server, 'claude', proxy); assert.equal(calls.at(-1).app, 'claude'); assert.equal(created.length, 2);
  for (const id of ['-flag', 'server with spaces', 'server;command', 'server\ncommand']) await assert.rejects(openMcpAuthentication({ ...server, id }, 'codex'), /mcp_auth_invalid_id/);
  await assert.rejects(openMcpAuthentication({ ...server, enabledCodex: false }, 'codex'), /mcp_auth_client_disabled/);
  await assert.rejects(openMcpAuthentication({ ...server, transport: 'stdio' }, 'codex'), /mcp_auth_http_required/);
  assert.equal(calls.length, 2);
  failure = Object.assign(new Error('unavailable'), { code: 'ENOENT' });
  await assert.rejects(openMcpAuthentication({ ...server, id: 'missing' }, 'codex'), /mcp_auth_cli_missing/);
  failure = new Error('private CLI diagnostics');
  await assert.rejects(openMcpAuthentication({ ...server, id: 'unsupported' }, 'claude'), /mcp_auth_cli_unsupported/);
  assert.equal(created.length, 2);
});
