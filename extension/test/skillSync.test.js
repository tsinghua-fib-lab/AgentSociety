'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/bundledSkillManager.ts'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function loadManagerClass() {
  const exportsObject = {};
  vm.runInNewContext(compiled, {
    exports: exportsObject,
    process,
    require: (name) => {
      if (['fs', 'path', 'os'].includes(name)) return require(name);
      if (name === './shared/outputChannels') {
        return { getMainOutputChannel: () => ({ appendLine() {}, show() {} }) };
      }
      return {};
    },
  });
  return exportsObject.BundledSkillManager;
}

const BundledSkillManager = loadManagerClass();

function makeManager(extensionPath) {
  return new BundledSkillManager({ extensionPath }, { appendLine() {}, show() {} });
}

function makeBundle() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'as-skill-sync-'));
  const skills = path.join(root, 'skills');
  const demo = path.join(skills, 'agentsociety-demo');
  fs.mkdirSync(path.join(demo, 'scripts'), { recursive: true });
  fs.writeFileSync(path.join(demo, 'SKILL.md'), '---\nname: demo\n---\nv1\n');
  fs.writeFileSync(path.join(demo, 'scripts', 'run.py'), 'print("ok")\n');
  fs.mkdirSync(path.join(skills, 'plain-skill'));
  fs.writeFileSync(path.join(skills, 'plain-skill', 'SKILL.md'), '---\nname: plain\n---\n');
  return { root, skills, demo };
}

test('sync copies flat managed skills as real directories', () => {
  const bundle = makeBundle();
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'as-skill-ws-'));
  const manager = makeManager(bundle.root);

  assert.equal(manager.listManagedSkills().join(','), 'agentsociety-demo');
  const result = manager.syncBundledSkills(workspace);

  assert.equal(Array.from(result.applied).join(','), 'agentsociety-demo');
  assert.equal(Array.from(result.errors).length, 0);
  const live = path.join(workspace, '.claude', 'skills', 'agentsociety-demo');
  assert.equal(fs.lstatSync(live).isSymbolicLink(), false);
  assert.match(fs.readFileSync(path.join(live, 'SKILL.md'), 'utf-8'), /v1/);
  assert.ok(fs.existsSync(path.join(live, 'scripts', 'run.py')));
});

test('sync replaces a legacy symlink with a real copy', () => {
  const bundle = makeBundle();
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'as-skill-ws-'));
  const live = path.join(workspace, '.claude', 'skills', 'agentsociety-demo');
  fs.mkdirSync(path.dirname(live), { recursive: true });
  fs.symlinkSync(bundle.demo, live, 'dir');

  const manager = makeManager(bundle.root);
  manager.syncBundledSkill(workspace, 'agentsociety-demo');

  assert.equal(fs.lstatSync(live).isSymbolicLink(), false);
  assert.match(fs.readFileSync(path.join(live, 'SKILL.md'), 'utf-8'), /v1/);
});

test('snapshot and restore round-trip the live skill', () => {
  const bundle = makeBundle();
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'as-skill-ws-'));
  const oldHome = process.env.HOME;
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), 'as-skill-home-'));
  process.env.HOME = fakeHome;
  try {
    const manager = makeManager(bundle.root);
    manager.syncBundledSkill(workspace, 'agentsociety-demo');
    const created = manager.createSnapshot(workspace, 'agentsociety-demo', 'stable');
    assert.equal(created.success, true, created.message);
    assert.equal(manager.countSnapshots('agentsociety-demo'), 1);

    const live = path.join(workspace, '.claude', 'skills', 'agentsociety-demo', 'SKILL.md');
    fs.writeFileSync(live, 'modified\n');
    const restored = manager.restoreSnapshot(workspace, 'agentsociety-demo', 'stable');
    assert.equal(restored.success, true, restored.message);
    assert.match(fs.readFileSync(live, 'utf-8'), /v1/);
  } finally {
    process.env.HOME = oldHome;
  }
});

test('restore rejects path-like snapshot tags', () => {
  const bundle = makeBundle();
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'as-skill-ws-'));
  const manager = makeManager(bundle.root);
  const result = manager.restoreSnapshot(workspace, 'agentsociety-demo', '../escape');
  assert.equal(result.success, false);
  assert.match(result.message, /tag/);
});

test('failed installation restores the workspace skill', (t) => {
  const bundle = makeBundle();
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'as-skill-ws-'));
  const manager = makeManager(bundle.root);
  manager.syncBundledSkill(workspace, 'agentsociety-demo');
  const live = path.join(workspace, '.claude', 'skills', 'agentsociety-demo');
  fs.writeFileSync(path.join(live, 'SKILL.md'), 'workspace copy');
  const rename = fs.renameSync;
  t.mock.method(fs, 'renameSync', (from, to) => {
    if (path.basename(from) === 'incoming' && to === live) throw new Error('install failed');
    return rename(from, to);
  });
  const result = manager.syncBundledSkill(workspace, 'agentsociety-demo');
  assert.match(result.errors[0].message, /install failed/);
  assert.equal(fs.readFileSync(path.join(live, 'SKILL.md'), 'utf8'), 'workspace copy');
});

test('bulk migration keeps the active user snapshot on the first sync', (t) => {
  const { root } = makeBundle();
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'as-skill-ws-'));
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'as-skill-home-'));
  t.mock.method(os, 'homedir', () => home);
  const name = 'agentsociety-demo';
  const snapshot = path.join(home, '.agentsociety', 'skill-versions', name, 'custom');
  fs.mkdirSync(snapshot, { recursive: true });
  fs.writeFileSync(path.join(snapshot, 'SKILL.md'), 'selected snapshot');
  const live = path.join(workspace, '.claude', 'skills', name);
  fs.mkdirSync(path.dirname(live), { recursive: true });
  fs.symlinkSync(snapshot, live, 'dir');
  const manager = makeManager(root);
  assert.equal(manager.syncBundledSkills(workspace).errors.length, 0);
  assert.equal(fs.lstatSync(live).isDirectory(), true);
  assert.equal(fs.readFileSync(path.join(live, 'SKILL.md'), 'utf8'), 'selected snapshot');
  assert.equal(manager.syncBundledSkill(workspace, name).errors.length, 0);
  assert.match(fs.readFileSync(path.join(live, 'SKILL.md'), 'utf8'), /v1/);
  assert.equal(fs.readFileSync(path.join(snapshot, 'SKILL.md'), 'utf8'), 'selected snapshot');
});
