const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/workspaceManager.ts'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exportsObject = {};
vm.runInNewContext(compiled, {
  exports: exportsObject, process,
  require: (name) => {
    if (['fs', 'path'].includes(name)) return require(name);
    if (name === './runtimeConfig') return { hasConfiguredLlmApiKey: () => true };
    if (name === './envManager') return { EnvManager: class { readEnv() { return {}; } } };
    return {};
  },
});

function managerFor(root) {
  const manager = Object.create(exportsObject.WorkspaceManager.prototype);
  manager.getWorkspacePath = () => root;
  manager.log = () => {};
  manager.ensureWorkspaceGitRepository = () => ({ initialized: false });
  manager.autoCommit = () => {};
  manager.syncClaudeCodeResources = () => ({ success: true, created: [] });
  manager.copyOfficialOfficeSkills = async () => ({ success: true, downloaded: [] });
  manager.seedClaudePluginMarketplaces = () => ({ success: true, written: false });
  manager.initCustomModules = () => assert.fail('must not regenerate existing custom modules');
  fs.writeFileSync(path.join(root, '.env'), '');
  return manager;
}

test('initialization repairs a skills-only custom directory and remains idempotent', async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'as2-init-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'custom/skills/my-skill'), { recursive: true });
  const skill = path.join(root, 'custom/skills/my-skill/SKILL.md');
  fs.writeFileSync(skill, 'user-authored skill');
  const manager = managerFor(root);
  const result = await manager.init({ topic: 'Test topic' });
  assert.equal(result.success, true, result.message);
  for (const relative of ['custom/agents', 'custom/envs']) {
    assert.equal(fs.statSync(path.join(root, relative)).isDirectory(), true);
    assert.ok(result.filesCreated.includes(`${relative}/`));
  }
  const agent = path.join(root, 'custom/agents/my_agent.py');
  fs.writeFileSync(agent, '# user code');
  const second = await manager.init({ topic: 'Another topic' });
  assert.equal(second.success, true, second.message);
  assert.equal(second.filesCreated.some(file => file.startsWith('custom/')), false);
  assert.equal(fs.readFileSync(skill, 'utf8'), 'user-authored skill');
  assert.equal(fs.readFileSync(agent, 'utf8'), '# user code');
  assert.match(fs.readFileSync(path.join(root, 'TOPIC.md'), 'utf8'), /Test topic/);
});

test('initialization reports a conflicting file without replacing it', async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'as2-init-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'custom'));
  const conflict = path.join(root, 'custom/agents');
  fs.writeFileSync(conflict, 'keep this file');
  const result = await managerFor(root).init({ topic: 'Test' });
  assert.equal(result.success, false);
  assert.match(result.message, /custom\/agents must be a directory/);
  assert.equal(fs.readFileSync(conflict, 'utf8'), 'keep this file');
});
