import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'child_process';
import { createInterface } from 'readline';

export type CodexDeviceLoginState = {
  status: 'idle' | 'starting' | 'waiting' | 'success' | 'cancelled' | 'error';
  userCode?: string;
  verificationUrl?: string;
  error?: 'missingCli' | 'unsupportedCli' | 'startFailed' | 'loginFailed' | 'processExited' |
    'invalidResponse' | 'requestRejected' | 'authorizationRejected' | 'rateLimited' | 'serviceUnavailable' |
    'networkError' | 'tlsError' | 'policyBlocked' | 'configurationError' | 'deviceDisabled' | 'expired' | 'timeout';
  phase?: 'initializing' | 'requestingCode' | 'authorizing';
  httpStatus?: number;
  rpcCode?: number;
};

type LoginFailure = Pick<CodexDeviceLoginState, 'error' | 'phase' | 'httpStatus' | 'rpcCode'>;

/** Classify CLI diagnostics without forwarding response bodies, paths or credentials to the webview. */
function loginFailure(value: unknown, phase: CodexDeviceLoginState['phase'], fallback: CodexDeviceLoginState['error']): LoginFailure {
  const object = value && typeof value === 'object' ? value as { code?: unknown; message?: unknown } : {};
  const message = typeof value === 'string' ? value : typeof object.message === 'string' ? object.message : '';
  const rpcCode = typeof object.code === 'number' ? object.code : undefined;
  const match = message.match(/\b(?:HTTP(?:\/[\d.]+)?\s*|status(?:\s+code)?[:=]?\s*)([45]\d\d)\b/i);
  const httpStatus = match ? Number(match[1]) : undefined;
  let error = fallback;
  if (rpcCode === -32601 || (rpcCode === -32602 && /chatgptDeviceCode|unknown variant/i.test(message))) { error = 'unsupportedCli'; }
  else if (/forced_login_method|login.*(?:disabled|not allowed).*policy|authentication.*restricted/i.test(message)) { error = 'policyBlocked'; }
  else if (/device(?:[-_ ]code)? (?:login|auth(?:entication)?) (?:is )?(?:disabled|not enabled)/i.test(message)) { error = 'deviceDisabled'; }
  else if (/error (?:loading|parsing|reading) config|failed to (?:load|parse|read).*config/i.test(message)) { error = 'configurationError'; }
  else if (httpStatus === 429) { error = 'rateLimited'; }
  else if (httpStatus && httpStatus >= 500) { error = 'serviceUnavailable'; }
  else if (httpStatus) { error = phase === 'authorizing' ? 'authorizationRejected' : 'requestRejected'; }
  else if (/certificate|\bTLS\b|\bSSL\b|unknown issuer/i.test(message)) { error = 'tlsError'; }
  else if (phase === 'authorizing' && /expired|timed?\s*out/i.test(message)) { error = 'expired'; }
  else if (/timed?\s*out|timeout/i.test(message)) { error = 'timeout'; }
  else if (/error sending request|failed to connect|connection refused|connection reset|dns|name resolution|network is unreachable|proxy.*(?:failed|error)/i.test(message)) { error = 'networkError'; }
  return { error, phase, httpStatus, rpcCode };
}

/** Only the official CLI receives and persists credentials. The UI receives a one-time code. */
export class CodexDeviceLogin {
  private child?: ChildProcessWithoutNullStreams;
  private loginId?: string;
  private timer?: ReturnType<typeof setTimeout>;
  private state: CodexDeviceLoginState = { status: 'idle' };

  constructor(private readonly onChange: (state: CodexDeviceLoginState) => void, private readonly version: string) {}

  snapshot(): CodexDeviceLoginState {
    return { ...this.state };
  }

  start(proxyEnv?: Record<string, string>): void {
    if (this.state.status === 'cancelled') { this.stop(); }
    if (this.child) { return; }
    let phase: CodexDeviceLoginState['phase'] = 'initializing';
    this.update({ status: 'starting', phase });
    // Windows npm installs expose a .cmd shim; all command arguments here are constants.
    const child = spawn('codex', ['app-server', '--listen', 'stdio://'], {
      stdio: 'pipe', windowsHide: true, shell: process.platform === 'win32',
      env: { ...process.env, ...proxyEnv },
    });
    this.child = child;
    let diagnostics = '';
    child.stderr.on('data', (chunk) => { diagnostics = (diagnostics + String(chunk)).slice(-8192); });
    const lines = createInterface({ input: child.stdout });
    const finish = (failure: LoginFailure) => {
      if (this.child === child) {
        this.stop();
        if (this.state.status !== 'cancelled') { this.update({ status: 'error', ...failure }); }
      }
    };
    child.on('error', (error: NodeJS.ErrnoException) => finish({ error: error.code === 'ENOENT' ? 'missingCli' : 'startFailed', phase }));
    child.stdin.on('error', () => finish(loginFailure(diagnostics, phase, 'processExited')));
    child.on('close', () => { lines.close(); finish(loginFailure(diagnostics, phase, 'processExited')); });
    lines.on('line', (line) => {
      if (this.child !== child) { return; }
      let message;
      try { message = JSON.parse(line); } catch { finish({ error: 'invalidResponse', phase }); return; }
      if (!message || typeof message !== 'object') { finish({ error: 'invalidResponse', phase }); return; }
      if (message.id === 1) {
        if (message.error || !message.result) { finish(loginFailure(message.error, phase, 'startFailed')); return; }
        this.write({ method: 'initialized' });
        phase = 'requestingCode';
        this.update({ status: 'starting', phase });
        this.write({ id: 2, method: 'account/login/start', params: { type: 'chatgptDeviceCode' } });
        this.armTimeout(() => finish({ error: 'timeout', phase }));
      } else if (message.id === 2) {
        this.clearTimer();
        const result = message.result;
        if (message.error || result?.type !== 'chatgptDeviceCode') { finish(loginFailure(message.error, phase, 'startFailed')); return; }
        if (typeof result.loginId !== 'string' || !result.loginId ||
            typeof result.userCode !== 'string' || !result.userCode ||
            !isCodexDeviceVerificationUrl(result.verificationUrl)) {
          finish({ error: 'invalidResponse', phase }); return;
        }
        this.loginId = result.loginId;
        phase = 'authorizing';
        this.update({ status: 'waiting', phase, userCode: result.userCode, verificationUrl: result.verificationUrl });
      } else if (message.method === 'account/login/completed' &&
                 this.loginId && message.params?.loginId === this.loginId) {
        const success = message.params.success === true;
        this.stop();
        this.update(success ? { status: 'success' } : { status: 'error', ...loginFailure(message.params.error, phase, 'loginFailed') });
      } else if (message.id === 3) {
        this.stop();
      }
    });
    child.once('spawn', () => {
      if (this.child !== child) { return; }
      this.write({ id: 1, method: 'initialize', params: {
        clientInfo: { name: 'agentsociety', title: 'AgentSociety', version: this.version },
      } });
    });
    this.armTimeout(() => finish({ error: 'timeout', phase }));
  }

  cancel(): void {
    if (this.loginId && this.child) {
      this.write({ id: 3, method: 'account/login/cancel', params: { loginId: this.loginId } });
      this.loginId = undefined;
      this.armTimeout(() => this.stop(), 1000);
    } else {
      this.stop();
    }
    this.update({ status: 'cancelled' });
  }

  dispose(): void {
    this.stop();
    this.state = { status: 'idle' };
  }

  private update(state: CodexDeviceLoginState): void {
    this.state = state;
    this.onChange(this.snapshot());
  }

  private write(message: object): void {
    this.child?.stdin.write(`${JSON.stringify(message)}\n`);
  }

  private armTimeout(callback: () => void, ms = 30_000): void {
    this.clearTimer();
    this.timer = setTimeout(callback, ms);
    this.timer.unref();
  }

  private clearTimer(): void {
    if (this.timer) { clearTimeout(this.timer); this.timer = undefined; }
  }

  private stop(): void {
    this.clearTimer();
    const child = this.child;
    this.child = undefined;
    this.loginId = undefined;
    if (!child) { return; }
    child.stdin.end();
    if (process.platform === 'win32' && child.pid) {
      execFile('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true }, () => {});
    } else {
      child.kill();
      const killTimer = setTimeout(() => { if (child.exitCode === null && child.signalCode === null) { child.kill('SIGKILL'); } }, 2000);
      killTimer.unref();
      child.once('close', () => clearTimeout(killTimer));
    }
  }
}

export function isCodexDeviceVerificationUrl(value: unknown): value is string {
  if (typeof value !== 'string') { return false; }
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'auth.openai.com' &&
      !url.port && !url.username && !url.password && url.pathname === '/codex/device';
  } catch { return false; }
}
