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
  vm.runInNewContext(code, { exports: exported, Buffer, process, console,
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
