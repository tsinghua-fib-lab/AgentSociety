const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const extensionRoot = path.resolve(__dirname, '..');
const sourceRoot = path.join(extensionRoot, 'src');

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      return sourceFiles(target);
    }
    return /\.tsx?$/.test(entry.name) ? [target] : [];
  });
}

function parseSource(file) {
  return ts.createSourceFile(
    file,
    fs.readFileSync(file, 'utf8'),
    ts.ScriptTarget.Latest,
    true,
    file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

function stringCommandProperty(object) {
  if (!ts.isObjectLiteralExpression(object)) {
    return null;
  }
  for (const property of object.properties) {
    if (!ts.isPropertyAssignment(property)) {
      continue;
    }
    const name = ts.isIdentifier(property.name) || ts.isStringLiteral(property.name)
      ? property.name.text
      : '';
    if (name === 'command' && ts.isStringLiteral(property.initializer)) {
      return property.initializer.text;
    }
  }
  return null;
}

function collectContracts() {
  const registrations = new Map();
  const outboundWebviewCommands = new Set();
  const handledHostCommands = new Set();
  const referencedExtensionCommands = new Set();

  for (const file of sourceFiles(sourceRoot)) {
    const source = parseSource(file);
    const isWebview = file.includes(`${path.sep}webview${path.sep}`);
    const visit = (node) => {
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
        const method = node.expression.name.text;
        const firstArgument = node.arguments[0];
        if (method === 'registerCommand' && firstArgument && ts.isStringLiteral(firstArgument)) {
          const locations = registrations.get(firstArgument.text) ?? [];
          locations.push(`${path.relative(extensionRoot, file)}:${source.getLineAndCharacterOfPosition(node.pos).line + 1}`);
          registrations.set(firstArgument.text, locations);
        }
        if (
          method === 'executeCommand' &&
          firstArgument &&
          ts.isStringLiteral(firstArgument) &&
          /^(aiSocialScientist|agentsociety)\./.test(firstArgument.text)
        ) {
          referencedExtensionCommands.add(firstArgument.text);
        }
        if (isWebview && method === 'postMessage' && firstArgument) {
          const command = stringCommandProperty(firstArgument);
          if (command) {
            outboundWebviewCommands.add(command);
          }
        }
      }

      if (!isWebview && ts.isObjectLiteralExpression(node)) {
        const command = stringCommandProperty(node);
        if (command && /^(aiSocialScientist|agentsociety)\./.test(command)) {
          referencedExtensionCommands.add(command);
        }
      }

      if (!isWebview && ts.isCaseClause(node) && node.expression && ts.isStringLiteral(node.expression)) {
        handledHostCommands.add(node.expression.text);
      }
      if (
        !isWebview &&
        ts.isBinaryExpression(node) &&
        [ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.EqualsEqualsEqualsToken].includes(node.operatorToken.kind)
      ) {
        for (const [left, right] of [[node.left, node.right], [node.right, node.left]]) {
          if (
            ts.isStringLiteral(right) &&
            ts.isPropertyAccessExpression(left) &&
            left.name.text === 'command'
          ) {
            handledHostCommands.add(right.text);
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return {
    registrations,
    outboundWebviewCommands,
    handledHostCommands,
    referencedExtensionCommands,
  };
}

function collectManifestCommandReferences(value, references = new Set()) {
  if (Array.isArray(value)) {
    for (const entry of value) {
      collectManifestCommandReferences(entry, references);
    }
    return references;
  }
  if (!value || typeof value !== 'object') {
    return references;
  }
  for (const [key, entry] of Object.entries(value)) {
    if (
      key === 'command' &&
      typeof entry === 'string' &&
      /^(aiSocialScientist|agentsociety)\./.test(entry)
    ) {
      references.add(entry);
    }
    collectManifestCommandReferences(entry, references);
  }
  return references;
}

function loadModule(name, dependencies) {
  const source = fs.readFileSync(path.join(sourceRoot, name + '.ts'), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const exports = {};
  require('node:vm').runInNewContext(outputText, {
    exports, require: id => dependencies[id] || {}, clearTimeout,
  });
  return exports;
}

test('every contributed extension command has exactly one implementation', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf8'));
  const declared = manifest.contributes.commands.map((entry) => entry.command);
  assert.equal(new Set(declared).size, declared.length, 'package.json contains duplicate command ids');

  const { registrations } = collectContracts();
  const missing = declared.filter((command) => !registrations.has(command));
  const duplicates = declared.filter((command) => (registrations.get(command)?.length ?? 0) !== 1);
  assert.deepEqual(missing, []);
  assert.deepEqual(
    duplicates.map((command) => [command, registrations.get(command)]),
    [],
  );
});

test('every static webview action has an extension-host handler', () => {
  const { outboundWebviewCommands, handledHostCommands } = collectContracts();
  const missing = [...outboundWebviewCommands]
    .filter((command) => !handledHostCommands.has(command))
    .sort();
  assert.deepEqual(missing, []);
  assert.ok(outboundWebviewCommands.size >= 60, 'unexpectedly incomplete webview command inventory');
});

test('every menu, walkthrough, and source command reference resolves', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf8'));
  const declared = new Set(manifest.contributes.commands.map((entry) => entry.command));
  const manifestReferences = collectManifestCommandReferences(manifest.contributes);
  const { registrations, referencedExtensionCommands } = collectContracts();

  const menus = manifest.contributes.menus;
  for (const entries of Object.values(menus)) {
    const placements = entries.map(entry => JSON.stringify([entry.command, entry.when]));
    assert.equal(new Set(placements).size, placements.length, 'duplicate menu entry for the same context');
  }
  assert.deepEqual(
    [...manifestReferences].filter((command) => !declared.has(command)).sort(),
    [],
    'manifest UI references an undeclared extension command',
  );
  assert.deepEqual(
    [...referencedExtensionCommands].filter((command) => !registrations.has(command)).sort(),
    [],
    'extension source invokes an unregistered extension command',
  );
});

function projectTreeFixture(t) {
  const root = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'as2-tree-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const workspace = { workspaceFolders: [], onDidChangeWorkspaceFolders: () => ({ dispose() {} }) };
  const vscode = {
    workspace, TreeItem: class {}, ThemeIcon: class {}, ThemeColor: class {},
    TreeItemCollapsibleState: { None: 0, Collapsed: 1 }, Uri: { file: fsPath => ({ fsPath }) },
    EventEmitter: class { fire() {} dispose() {} },
  };
  const dependencies = {
    fs, path, vscode,
    './envManager': { EnvManager: class { readEnv() { return {}; } } },
    './runtimeConfig': { hasConfiguredLlmApiKey: () => true },
    './workspaceManager': { WorkspaceManager: class { dispose() {} } },
    './shared/outputChannels': { getMainOutputChannel: () => ({ appendLine() {} }) },
    './i18n': { localize: key => key, isExtensionZh: () => false },
  };
  const { ProjectStructureProvider } = loadModule('projectStructureProvider', dependencies);
  const tree = new ProjectStructureProvider({ subscriptions: [] }, {});
  t.after(() => tree.dispose());
  workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  return { root, tree };
}

test('literature groups retain file actions and refresh independently', async (t) => {
  const { root, tree } = projectTreeFixture(t);
  const group = name => ({
    type: 'paperPdfGroup', label: 'PDF', fileList: [{ name, path: path.join(root, 'papers', name) }],
  });
  const first = group('one.pdf'), second = group('two.pdf');
  const firstRows = await tree.getChildren(first);
  assert.equal(firstRows[0].contextValue, 'literatureFile pdf hasPath');
  assert.equal(firstRows[0].command.command, 'aiSocialScientist.openPdfPreview');
  for (const [name, command, editablePreview] of [
    ['note.md', 'markdown.showPreview', true],
    ['table.csv', 'aiSocialScientist.viewCsvFile', true],
    ['data.bin', 'vscode.open', false],
  ]) {
    const [file] = await tree.getChildren(group(name));
    assert.equal(file.command.command, command);
    assert.equal(file.contextValue.includes('sourceFile'), editablePreview);
  }
  assert.equal((await tree.getChildren(second))[0].label, 'two.pdf');
  assert.equal(await tree.getChildren(first), firstRows);
  const hypothesisDir = path.join(root, 'hypothesis_1');
  const experimentDir = path.join(hypothesisDir, 'experiment_2');
  fs.mkdirSync(experimentDir, { recursive: true });
  const hypothesis = (await tree.getChildren({ type: 'topic' })).find(item => item.type === 'hypothesis');
  assert.equal(hypothesis.directoryPath, hypothesisDir);
  assert.equal(hypothesis.contextValue, 'hypothesis hasPath');
  const [experiment] = await tree.getChildren(hypothesis);
  assert.equal(experiment.directoryPath, experimentDir);
  assert.equal(experiment.contextValue, 'experiment hasPath');
  const runDir = path.join(experimentDir, 'run');
  fs.mkdirSync(runDir);
  const pidFile = path.join(runDir, 'pid.json');
  fs.writeFileSync(pidFile, JSON.stringify({ status: 'completed' }));
  tree.refreshNow();
  const [finished] = await tree.getChildren(hypothesis);
  assert.equal(finished.runStatusPath, pidFile);
  assert.match(finished.contextValue, /\bhasRunStatus\b/);
  assert.equal((await tree.getChildren(finished)).length, 0);
  fs.writeFileSync(path.join(runDir, 'output.log'), 'done');
  tree.refreshNow();
  const [results] = await tree.getChildren(finished);
  assert.deepEqual(Array.from(await tree.getChildren(results), item => item.label), ['output.log']);
  tree.refreshNow();
  assert.notEqual(await tree.getChildren(first), firstRows);
});

test('experiment progress lists actionable unfinished runs and folds into one line when complete', async t => {
  const { root, tree } = projectTreeFixture(t);
  tree.checkWorkspaceHealth = () => ({ isHealthy: true });
  for (const name of ['TOPIC.md', '.env']) { fs.writeFileSync(path.join(root, name), ''); }
  const progress = async () => (await tree.getChildren()).find(item => item.type === 'projectStats');
  assert.equal(await progress(), undefined);
  const record = (h, e, contents) => {
    const dir = path.join(root, 'hypothesis_' + h, 'experiment_' + e, 'run');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'pid.json'), contents);
  };
  record(1, 1, '{"status":"running"}');
  record(2, 1, '{"status":"failed"}');
  record(1, 2, '{"status":"queued"}');
  record(1, 3, '{');
  record(1, 4, '{"status":"completed"}');
  tree.refreshNow();
  const summary = await progress();
  assert.equal(summary.collapsibleState, 1);
  const unfinished = await tree.getChildren(summary);
  assert.deepEqual(Array.from(unfinished, item => [item.hypothesisId, item.experimentId, item.description]), [
    ['2', '1', 'failed'], ['1', '3', 'unknown'], ['1', '1', 'running'], ['1', '2', 'pending'],
  ]);
  assert.notEqual(unfinished[0].label, unfinished[2].label);
  assert.match(unfinished[0].contextValue, /hasRunStatus/);
  assert.equal(unfinished[1].runStatusPath, undefined);
  for (const item of unfinished) { record(item.hypothesisId, item.experimentId, '{"status":"completed"}'); }
  tree.refreshNow();
  const done = await progress();
  assert.equal(done.collapsibleState, 0);
  assert.equal((await tree.getChildren(done)).length, 0);
});

test('opening chat and setting a default are independent actions', async () => {
  let selected = 'Codex';
  let preference = '';
  let workspaceOverride;
  const opened = [], updates = [], choices = [];
  const config = {
    get: () => workspaceOverride ?? preference,
    inspect: () => ({ workspaceValue: workspaceOverride }),
    update: (_key, value, scope) => {
      updates.push(scope);
      if (scope === 'workspace') { workspaceOverride = value; } else { preference = value; }
    },
  };
  const vscode = {
    workspace: { getConfiguration: () => config },
    ConfigurationTarget: { Global: 'global', Workspace: 'workspace' },
    extensions: { getExtension: id => id === 'openai.chatgpt'
      ? { packageJSON: { contributes: { commands: [{ command: 'chatgpt.openSidebar' }] } } }
      : undefined },

    commands: {
      getCommands: () => ['claude-vscode.editor.open'],
      executeCommand: command => opened.push(command),
    },
    window: {
      showQuickPick: items => {
        choices.push(Array.from(items, item => item.label));
        return items.find(item => item.label === selected);
      },
    },
  };
  const { AIChatInvoker } = loadModule('aiChatInvoker', { vscode, './i18n': { localize: key => key } });
  const chat = new AIChatInvoker();
  assert.equal(await chat.invokeChat(), true);
  assert.deepEqual(choices[0], ['Claude Code', 'Codex']);
  assert.deepEqual(updates, []);
  assert.deepEqual(opened, ['chatgpt.openSidebar']);
  selected = 'Claude Code';
  await chat.pickProvider();
  assert.deepEqual(updates, ['global']);
  assert.equal(opened.length, 1);
  await chat.invokeChat();
  assert.equal(choices.length, 2);
  assert.equal(opened.at(-1), 'claude-vscode.editor.open');
  workspaceOverride = 'claude-code';
  selected = 'Codex';
  await chat.pickProvider();
  assert.deepEqual(updates, ['global', 'workspace']);
  assert.equal(workspaceOverride, 'codex');
});
