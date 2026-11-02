const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

// Exercise the manager without creating VS Code UI or real child processes.
const source = fs.readFileSync(path.join(__dirname, '../src/services/backendManager.ts'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exportsObject = {};
vm.runInNewContext(compiled, {
  exports: exportsObject,
  require: () => ({}),
});

function externalManager(healthy) {
  const manager = Object.create(exportsObject.BackendManager.prototype);
  manager.process = null;
  manager.allocatedPort = null;
  manager.externalBackend = false;
  manager.healthCheck = async () => healthy;
  manager.getPortFromEnv = async () => 13337;
  return manager;
}

test('external backend status reads do not trigger another config page refresh', async () => {
  const manager = externalManager(true);
  let notifications = 0;
  manager.updateStatusBar = () => { notifications++; };
  for (let i = 0; i < 3; i++) {
    const status = await manager.getStatus();
    assert.equal(status.isRunning, true);
    assert.equal(status.port, 13337);
  }
  assert.equal(manager.externalBackend, true);
  assert.equal(notifications, 0);
});

test('start reuses a healthy external backend without allocating another port', async () => {
  const manager = externalManager(true);
  manager.reloadConfig = () => {};
  manager.log = () => {};
  manager.updateStatusBar = () => assert.fail('must not start another backend');
  assert.equal(await manager.start({ silent: true }), true);
  assert.equal(manager.externalBackend, true);
  assert.equal(manager.process, null);
});

test('an unreachable external backend is not reported as running', async () => {
  const manager = externalManager(false);
  assert.equal(await manager.isRunning(), false);
  assert.equal(manager.externalBackend, false);
});
