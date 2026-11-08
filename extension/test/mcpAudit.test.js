const test = require('node:test');
const assert = require('node:assert/strict');
const { load } = require('./helpers/loadSource');
const { parse } = require('smol-toml');

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

test('MCP sync clears the last managed block without creating an unused empty config', async () => {
  for (const original of ['', '[mcp_servers.agentsociety-last]\ncommand = "test"\n']) {
    const writes = [];
    const { McpServerManager } = load('services/mcpServerManager.ts', {
      fs: { existsSync: () => false, mkdirSync: () => {}, writeFileSync: () => {}, chmodSync: () => {}, renameSync: () => {} },
      './codexSettings': { readCodexConfigText: () => original, writeCodexConfigText: (value) => writes.push(value) },
    });
    const manager = Object.create(McpServerManager.prototype);
    manager.listServers = () => original ? [{ id: 'agentsociety-last', enabledCodex: false, enabledClaude: false, transport: 'stdio' }] : [];
    await manager.syncLiveConfigs();
    assert.deepEqual(writes, original ? [''] : []);
  }
});
