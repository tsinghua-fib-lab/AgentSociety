'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');
const ts = require('typescript');

const source = fs.readFileSync(
  path.join(__dirname, '../src/services/workspaceExportManager.ts'),
  'utf8',
);
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function loadManager() {
  const exportsObject = {};
  vm.runInNewContext(compiled, {
    exports: exportsObject,
    process,
    Buffer,
    setTimeout,
    clearTimeout,
    require: (name) => {
      if (['fs', 'path', 'os'].includes(name)) return require(name);
      if (name === 'vscode') {
        return {
          extensions: { getExtension: () => ({ packageJSON: { version: 'test' } }) },
          workspace: {},
          window: {},
          Uri: { file: (p) => ({ fsPath: p, scheme: 'file' }) },
          ProgressLocation: { Notification: 1 },
          QuickPickItemKind: { Separator: -1 },
        };
      }
      if (name === '../i18n') return { localize: (key) => key };
      if (name === '../shared/outputChannels') {
        return { getMainOutputChannel: () => ({ appendLine() {}, show() {} }) };
      }
      if (name === './agentsocietyPythonResolver') {
        return { resolveAgentsocietyPython: () => null };
      }
      if (name === './workspaceArchiveIo') {
        return require('../out/services/workspaceArchiveIo');
      }
      if (name === './workspaceExportManifest') {
        return require('../out/services/workspaceExportManifest');
      }
      throw new Error(`unexpected require: ${name}`);
    },
  });
  return exportsObject.WorkspaceExportManager;
}

const WorkspaceExportManager = loadManager();

function makeManager() {
  return new WorkspaceExportManager();
}

test('export copies internal directory symlinks and skips cycles', () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'as-export-ws-'));
  const target = fs.mkdtempSync(path.join(os.tmpdir(), 'as-export-out-'));
  const realDir = path.join(workspace, 'papers');
  fs.mkdirSync(realDir, { recursive: true });
  fs.writeFileSync(path.join(realDir, 'a.md'), 'a');
  fs.symlinkSync(realDir, path.join(workspace, 'papers-link'), 'dir');
  fs.symlinkSync(workspace, path.join(realDir, 'cycle'), 'dir');

  const manager = makeManager();
  const summary = { exportedRoots: ['papers-link'], copiedFiles: 0 };
  manager.copyEntry(
    path.join(workspace, 'papers-link'),
    path.join(target, 'papers-link'),
    'papers-link',
    workspace,
    summary,
    new Set(),
  );

  assert.equal(summary.copiedFiles, 1);
  assert.equal(fs.readFileSync(path.join(target, 'papers-link', 'a.md'), 'utf8'), 'a');
  assert.equal(fs.existsSync(path.join(target, 'papers-link', 'cycle')), false);
});

test('export size/count include internal directory symlinks once', () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'as-export-size-'));
  const realDir = path.join(workspace, 'papers');
  fs.mkdirSync(realDir, { recursive: true });
  fs.writeFileSync(path.join(realDir, 'a.md'), '12345');
  fs.symlinkSync(realDir, path.join(workspace, 'papers-link'), 'dir');

  const manager = makeManager();
  assert.equal(manager.getDirectorySize(path.join(workspace, 'papers-link'), '', workspace), 5);
  assert.equal(
    manager.countExportableFiles(path.join(workspace, 'papers-link'), 'papers-link', workspace),
    1,
  );
});
