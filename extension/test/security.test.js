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
  vm.runInNewContext(code, { exports: exported, Buffer, process, console, URL,
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
