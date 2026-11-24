const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter, once } = require('node:events');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const WORKSPACE = '/fixture/experiments';
const TOKEN = 'as2-fixture-token';
const FIXTURE_PORT = 49152;
const moduleCache = new Map();

// Load extension code without reading user settings or launching real child processes.
function load(relative, dependencies = {}, globals = {}) {
  let compiled = moduleCache.get(relative);
  if (!compiled) {
    const file = path.join(__dirname, '../src', relative);
    const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    });
    compiled = new vm.Script(outputText, { filename: file });
    moduleCache.set(relative, compiled);
  }
  const exported = {};
  compiled.runInNewContext({
    exports: exported,
    require: (name) => dependencies[name] ?? require(name),
    URL, URLSearchParams, AbortController, AbortSignal, console,
    ...globals,
  });
  return exported;
}

const { ApiClient } = load('apiClient.ts');

function harness({ env = '', inheritedEnv = {}, fetchImpl, spawn, vscodeOverrides } = {}) {
  const vscode = {
    workspace: {
      workspaceFolders: [{ uri: { fsPath: WORKSPACE } }],
      getConfiguration: () => ({ get: () => undefined }),
      onDidChangeWorkspaceFolders: () => ({ dispose() {} }),
    },
    env: { language: 'en-US' },
    window: { createStatusBarItem: () => ({ show() {}, dispose() {} }) },
    StatusBarAlignment: { Right: 2 },
    MarkdownString: class { appendMarkdown() {} },
    ThemeColor: class {},
    ...vscodeOverrides,
  };
  const fakeFs = {
    existsSync: () => true,
    readFileSync: () => env,
    writeFileSync: (_path, contents) => { env = contents; },
  };
  const channel = { appendLine() {}, show() {} };
  const outputChannels = {
    getMainOutputChannel: () => channel,
    getSharedOutputChannel: () => channel,
    appendSharedOutputLine() {},
  };
  const i18n = load('i18n.ts', { vscode });
  const envModule = load('envManager.ts', { vscode, fs: fakeFs, './shared/outputChannels': outputChannels });
  const runtimeConfig = load('runtimeConfig.ts', { vscode, './envManager': envModule });
  const shared = { '../envManager': envModule, '../runtimeConfig': runtimeConfig, '../i18n': i18n };
  const process = { env: inheritedEnv };
  const transport = load('services/backendService.ts', shared, { fetch: fetchImpl, process });
  const { BackendManager } = load('services/backendManager.ts', {
    ...shared, vscode, fs: fakeFs, child_process: { spawn }, './backendService': transport,
    '../portUtils': { isPortAvailable: async () => true },
    '../shared/outputChannels': outputChannels,
    '../shared/formatDuration': load('shared/formatDuration.ts'),
    '../configPageViewProvider': { ConfigPageViewProvider: { refreshBackendStatusIfOpen() {} } },
    './agentsocietyPythonResolver': {
      resolveAgentsocietyPython: () => 'fixture-python',
      pythonHasAgentsociety2: () => true,
    },
  }, { process, setTimeout: queueMicrotask, setInterval, clearInterval });
  const backend = new transport.BackendService();
  return { backend, client: new ApiClient(backend), BackendManager, transport, vscode, setEnv(value) { env = value; } };
}

function externalManager(healthy) {
  const { BackendManager } = harness();
  const manager = Object.create(BackendManager.prototype);
  manager.process = null;
  manager.externalBackend = false;
  const getStatus = async () => ({ isRunning: healthy, port: FIXTURE_PORT });
  manager.backend = { getStatus, getStartupStatus: getStatus, readConfiguredEnv: () => ({}) };
  manager.startHealthCheck = () => {};
  return manager;
}

function externalConfig(url, origin = new URL(url).origin) {
  return `BACKEND_URL=${url}\nBACKEND_TOKEN_ORIGIN=${origin}\nBACKEND_TOKEN=${TOKEN}\n`;
}

function authorization(init) {
  return new Headers(init.headers).get('authorization');
}

async function listen(t, handler) {
  const server = http.createServer(handler).listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return `http://127.0.0.1:${server.address().port}`;
}

test('external backend status reads do not trigger another config page refresh', async () => {
  const manager = externalManager(true);
  let notifications = 0;
  manager.updateStatusBar = () => { notifications++; };
  for (let i = 0; i < 3; i++) {
    const status = await manager.getStatus();
    assert.equal(status.isRunning, true);
    assert.equal(status.port, FIXTURE_PORT);
  }
  assert.equal(manager.externalBackend, true);
  assert.equal(notifications, 0);
});

test('start reuses a healthy external backend without allocating another port', async () => {
  const manager = externalManager(true);
  manager.allocatePort = () => assert.fail('must not start another backend');
  manager.log = () => {};
  manager.updateStatusBar = (state) => assert.equal(state, 'running');
  assert.equal(await manager.start({ silent: true }), true);
  assert.equal(manager.externalBackend, true);
  assert.equal(manager.process, null);
});

test('an unreachable external backend is not reported as running', async () => {
  const manager = externalManager(false);
  assert.equal((await manager.getStatus()).isRunning, false);
  assert.equal(manager.externalBackend, false);
});

test('managed backend starts and serves authenticated business requests', async (t) => {
  const agents = { success: true, agents: {}, count: 0 };
  const responses = { '/health': { status: 'ok' }, '/api/v1/modules/agent_classes': agents };
  const prelaunchHeaders = [];
  let childEnv;
  const { BackendManager, backend, client } = harness({
    env: `BACKEND_PORT=18331\nBACKEND_TOKEN=${TOKEN}\nPYTHON_PATH=fixture-python\nAGENTSOCIETY_LLM_API_KEY=fixture-llm-key\n`,
    fetchImpl: async (url, init) => {
      const header = authorization(init);
      if (!childEnv) {
        prelaunchHeaders.push(header);
        throw new Error('Fixture backend has not started');
      }
      const endpoint = new URL(url);
      if (endpoint.origin !== `http://127.0.0.1:${childEnv.BACKEND_PORT}` ||
          childEnv.BACKEND_TOKEN !== TOKEN || header !== `Bearer ${childEnv.BACKEND_TOKEN}`) {
        return new Response(null, { status: 401 });
      }
      const data = responses[endpoint.pathname];
      return data ? Response.json(data) : new Response(null, { status: 404 });
    },
    spawn: (_python, _args, options) => {
      childEnv = options.env;
      return new EventEmitter();
    },
  });
  const manager = new BackendManager({ subscriptions: [], extensionPath: WORKSPACE }, backend);
  t.after(() => manager.dispose());

  assert.equal(await manager.start({ silent: true }), true);
  assert.deepEqual(await client.getAgentClasses(), agents);
  assert.ok(prelaunchHeaders.every((header) => header === null), 'the managed token must not be sent before launch');
});

test('external credentials are sent only to the matching HTTPS origin', async () => {
  const origin = 'https://as2.example.invalid';
  const sent = [];
  const { client, setEnv } = harness({
    env: externalConfig(`${origin}/tenant/as2/`),
    fetchImpl: async (url, init) => {
      sent.push([String(url), init.method, authorization(init), JSON.parse(init.body)]);
      return Response.json({ success: true, new_skills: [], total: 0 });
    },
  });

  assert.equal((await client.scanAgentSkills(WORKSPACE)).success, true);
  setEnv(externalConfig('https://other.example.invalid', origin));
  await assert.rejects(client.scanAgentSkills(WORKSPACE), /does not match BACKEND_TOKEN_ORIGIN/);
  setEnv(externalConfig('http://as2.example.invalid'));
  await assert.rejects(client.scanAgentSkills(WORKSPACE), /HTTPS/);
  assert.deepEqual(sent, [
    [`${origin}/tenant/as2/api/v1/agent-skills/scan`, 'POST', `Bearer ${TOKEN}`, { workspace_path: WORKSPACE }],
  ]);
});

test('local backend works without sending credentials when none are configured for it', async () => {
  const requests = [];
  const { backend, client } = harness({
    env: 'BACKEND_HOST=0.0.0.0\nBACKEND_PORT=18001\n',
    inheritedEnv: { BACKEND_TOKEN: TOKEN },
    fetchImpl: async (url, init) => {
      requests.push([String(url), authorization(init)]);
      return Response.json({ success: true, modules: {}, count: 0 });
    },
  });

  assert.equal((await backend.getStatus()).isRunning, true);
  assert.equal((await client.getEnvModules()).success, true);
  assert.deepEqual(requests, [
    ['http://127.0.0.1:18001/health', null],
    ['http://127.0.0.1:18001/api/v1/modules/env_module_classes', null],
  ]);
});

test('authenticated requests do not follow a backend redirect', async (t) => {
  let redirectedRequests = 0;
  const target = await listen(t, (_req, res) => {
    redirectedRequests++;
    res.end('{}');
  });
  const source = await listen(t, (_req, res) => {
    res.writeHead(307, { Location: `${target}/api/v1/modules/agent_classes` }).end();
  });
  const { client } = harness({
    env: externalConfig(source),
    fetchImpl: (url, init) => {
      assert.equal(new URL(url).origin, source);
      return fetch(url, init);
    },
  });

  await assert.rejects(client.getAgentClasses(), /HTTP 307/);
  assert.equal(redirectedRequests, 0);
});

test('replay requests stay authenticated in the host without exposing the token to the webview', async () => {
  let header;
  const { backend, transport, vscode } = harness({
    env: externalConfig('https://as2.example.invalid'),
    fetchImpl: async (_url, init) => {
      header = authorization(init);
      return new Response(`Fixture auth error: ${TOKEN}`, { status: 401 });
    },
  });
  const messages = [];
  const listeners = [];
  let changeLanguage;
  vscode.workspace.onDidChangeConfiguration = callback => { changeLanguage = callback; return { dispose() {} }; };
  vscode.ViewColumn = { One: 1 };
  vscode.Uri = { file: (file) => file };
  vscode.window.createWebviewPanel = () => ({
    onDidDispose() {},
    webview: {
      cspSource: 'fixture-webview',
      asWebviewUri: (uri) => uri,
      onDidReceiveMessage: (callback) => { listeners.push(callback); return { dispose() {} }; },
      postMessage: (message) => { messages.push(message); },
    },
  });
  const { ReplayWebviewProvider } = load('replayWebviewProvider.ts', { vscode, './i18n': load('i18n.ts', { vscode }), './services/backendService': transport });
  ReplayWebviewProvider.create({ extensionUri: { fsPath: '/fixture/extension' } }, backend, WORKSPACE, '1', '2');

  for (const command of ['ready', 'fetchExperimentInfo']) {
    for (const listener of listeners) { await listener({ command }); }
  }
  assert.equal(messages[0].type, 'extensionLanguageChanged');
  assert.equal(messages[0].language, 'en-US');
  vscode.env.language = 'zh-CN';
  changeLanguage({ affectsConfiguration: key => key === 'aiSocialScientist.language' });
  assert.equal(messages.at(-1).language, 'zh-CN');
  assert.equal(header, `Bearer ${TOKEN}`);
  assert.equal(messages[1].type, 'init');
  assert.equal(messages[2].type, 'error');
  assert.match(messages[2].message, /HTTP 401/);
  assert.ok(!JSON.stringify(messages).includes(TOKEN));
});

test('Swagger retains the backend prefix when Coder forwards a port', async () => {
  const uri = value => {
    const url = new URL(value);
    return { path: url.pathname, href: url.href, with: ({ path }) => {
      const next = new URL(url);
      next.pathname = path;
      return uri(next.href);
    } };
  };
  const opened = [];
  const { BackendManager, vscode } = harness({ vscodeOverrides: { Uri: { parse: uri }, UIKind: { Web: 2 } } });
  const manager = Object.create(BackendManager.prototype);
  manager.backend = { getBrowserUrl: async () => `http://127.0.0.1:${FIXTURE_PORT}/api` };
  vscode.env.uiKind = vscode.UIKind.Web;
  vscode.env.asExternalUri = async origin => {
    assert.equal(origin.href, `http://127.0.0.1:${FIXTURE_PORT}/`);
    return uri(`https://coder.example/workspace/proxy/${FIXTURE_PORT}/`);
  };
  vscode.env.openExternal = async target => { opened.push(target.href); return true; };
  assert.equal(await manager.openApiDocs(), true);
  assert.deepEqual(opened, [`https://coder.example/workspace/proxy/${FIXTURE_PORT}/api/docs`]);
});
