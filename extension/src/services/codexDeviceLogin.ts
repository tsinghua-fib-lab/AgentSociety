import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'child_process';
import { createInterface } from 'readline';

export type CodexDeviceLoginState = {
  status: 'idle' | 'starting' | 'waiting' | 'success' | 'cancelled' | 'error';
  userCode?: string;
  verificationUrl?: string;
  error?: 'missingCli' | 'startFailed' | 'loginFailed' | 'processExited' | 'invalidResponse';
};

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
    this.update({ status: 'starting' });
    // Windows npm installs expose a .cmd shim; all command arguments here are constants.
    const child = spawn('codex', ['app-server', '--listen', 'stdio://'], {
      stdio: 'pipe', windowsHide: true, shell: process.platform === 'win32',
      env: { ...process.env, ...proxyEnv },
    });
    this.child = child;
    child.stderr.resume();
    const lines = createInterface({ input: child.stdout });
    const finish = (error: NonNullable<CodexDeviceLoginState['error']>) => {
      if (this.child === child) {
        this.stop();
        if (this.state.status !== 'cancelled') { this.update({ status: 'error', error }); }
      }
    };
    child.on('error', (error: NodeJS.ErrnoException) => finish(error.code === 'ENOENT' ? 'missingCli' : 'startFailed'));
    child.stdin.on('error', () => finish('processExited'));
    child.on('close', () => { lines.close(); finish('processExited'); });
    lines.on('line', (line) => {
      if (this.child !== child) { return; }
      let message;
      try { message = JSON.parse(line); } catch { finish('invalidResponse'); return; }
      if (!message || typeof message !== 'object') { finish('invalidResponse'); return; }
      if (message.id === 1) {
        if (message.error || !message.result) { finish('startFailed'); return; }
        this.write({ method: 'initialized' });
        this.write({ id: 2, method: 'account/login/start', params: { type: 'chatgptDeviceCode' } });
        this.armTimeout(() => finish('startFailed'));
      } else if (message.id === 2) {
        this.clearTimer();
        const result = message.result;
        if (message.error || result?.type !== 'chatgptDeviceCode') { finish('startFailed'); return; }
        if (typeof result.loginId !== 'string' || !result.loginId ||
            typeof result.userCode !== 'string' || !result.userCode ||
            !isCodexDeviceVerificationUrl(result.verificationUrl)) {
          finish('invalidResponse'); return;
        }
        this.loginId = result.loginId;
        this.update({ status: 'waiting', userCode: result.userCode, verificationUrl: result.verificationUrl });
      } else if (message.method === 'account/login/completed' &&
                 this.loginId && message.params?.loginId === this.loginId) {
        const success = message.params.success === true;
        this.stop();
        this.update(success ? { status: 'success' } : { status: 'error', error: 'loginFailed' });
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
    this.armTimeout(() => finish('startFailed'));
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
