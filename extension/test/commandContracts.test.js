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

  assert.ok(manifestReferences.size >= 41, 'unexpectedly incomplete manifest command inventory');
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
