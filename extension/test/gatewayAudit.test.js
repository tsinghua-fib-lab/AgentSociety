const test = require('node:test');
const assert = require('node:assert/strict');
const { load } = require('./helpers/loadSource');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');

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

test('explicit Codex route choice clears auto-enable ownership', async () => {
  const { AiCliGatewayManager } = load('services/aiCliGatewayManager.ts');
  const manager = Object.create(AiCliGatewayManager.prototype);
  const state = new Map([['aiCliGateway.routeCodex.auto', true]]);
  manager.context = { globalState: { get: (key, fallback) => state.has(key) ? state.get(key) : fallback, update: async (key, value) => state.set(key, value) } };
  manager.initialize = async () => {};
  manager.getOpenAiProviderForGateway = () => ({});
  manager.getAnthropicProviderForGateway = () => ({});
  manager.providerToClaudeConfig = () => ({});
  manager.gateway = { getStatus: () => ({ running: true }) };
  manager.applyGatewayRoutes = async () => {};
  manager.persistEnabled = async () => {};
  manager.getPublicStatus = () => ({});
  await manager.setGatewayRoute('codex', true);
  assert.equal(state.get('aiCliGateway.routeCodex.auto'), false);
});

test('Codex snapshot recognizes takeover tokens from an earlier process', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'as2-codex-test-'));
  try {
    fs.writeFileSync(path.join(temp, 'config.toml'), 'model_provider = "agentsociety-gateway"\n[model_providers.agentsociety-gateway]\nname = "AgentSociety Gateway"\nbase_url = "http://127.0.0.1:15721"\nexperimental_bearer_token = "previous-random-token"\n');
    const settings = load('services/codexSettings.ts', {
      './aiCliGatewayUpstream': require('../out/services/aiCliGatewayUpstream'),
      fs: { ...fs, existsSync: (file) => fs.existsSync(path.join(temp, path.basename(file))), readFileSync: (file, ...args) => fs.readFileSync(path.join(temp, path.basename(file)), ...args) },
    });
    assert.equal(settings.getCodexRoutingSnapshot().routedViaGateway, true);
  } finally { fs.rmSync(temp, { recursive: true, force: true }); }
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

test('request cap counts accepted requests before completion', () => {
  const { GatewayRuntimeStatsTracker } = require('../out/services/gatewayRuntimeStats');
  const saved = process.env.AGENTSOCIETY_GATEWAY_MAX_REQUESTS;
  try {
    process.env.AGENTSOCIETY_GATEWAY_MAX_REQUESTS = '2'; const tracker = new GatewayRuntimeStatsTracker();
    tracker.onRequestStart(); tracker.onRequestStart();
    assert.equal(tracker.limitReached(), true); assert.equal(tracker.snapshot().activeConnections, 2);
  } finally {
    if (saved === undefined) delete process.env.AGENTSOCIETY_GATEWAY_MAX_REQUESTS;
    else process.env.AGENTSOCIETY_GATEWAY_MAX_REQUESTS = saved;
  }
});
