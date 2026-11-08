const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function load(relative, dependencies = {}, extra = '') {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../../src', relative), 'utf8') + extra, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText;
  const exported = {};
  vm.runInNewContext(code, { exports: exported, Buffer, process, console,
    require: (name) => dependencies[name] ?? (name.startsWith('.') || name === 'vscode' ? {} : require(name)),
  });
  return exported;
}

module.exports = { load };
