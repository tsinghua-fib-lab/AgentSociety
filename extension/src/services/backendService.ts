import { isIP } from 'node:net';
import { EnvManager, type BackendEnvConfig } from '../envManager';
import { localize } from '../i18n';
import { getBackendBindHost, getBackendPort, normalizeBackendAccessHost } from '../runtimeConfig';

export interface BackendStatus {
  isRunning: boolean;
  url?: string;
  port?: number;
  pid?: number;
  error?: string;
}

export interface BackendRequestOptions {
  body?: unknown;
  signal?: AbortSignal;
}

export class BackendAccessError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'BackendAccessError';
  }
}

export class BackendConnectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BackendConnectionError';
  }
}

interface BackendTarget {
  url: URL;
  token: string;
}

interface ManagedBackendEnv {
  BACKEND_HOST: string;
  BACKEND_PORT: string;
  BACKEND_TOKEN?: string;
}

function parseBackendUrl(value: string, setting: string, allowPrefix = false): URL {
  // Validate the raw path and authority before URL normalization can remove segments or userinfo.
  const pathname = /^https?:\/\/[^/?#@\\\s]+((?:\/[a-z0-9._~-]+)*\/?)$/i.exec(value)?.[1];
  if (pathname !== undefined && (allowPrefix || pathname === '' || pathname === '/')) {
    try {
      const url = new URL(value);
      if (url.href === `${url.origin}${pathname || '/'}` && url.port !== '0') {
        if (!url.pathname.endsWith('/')) {
          url.pathname += '/';
        }
        return url;
      }
    } catch {
      // A URL parser error can contain the original value, including credentials.
    }
  }
  throw new BackendAccessError(localize(allowPrefix ? 'backendRequest.invalidUrl' : 'backendRequest.invalidOrigin', setting));
}

function formatBaseUrl(url: URL): string {
  return url.href.slice(0, -1); // parseBackendUrl normalizes the base to end in '/'.
}

function hostPortOrigin(config: BackendEnvConfig): URL {
  const host = normalizeBackendAccessHost(getBackendBindHost(config));
  const port = config.backendPort ?? getBackendPort();
  const literalHost = host.startsWith('[') && host.endsWith(']') ? host.slice(1, -1) : host;
  const ipv6 = isIP(literalHost) === 6;
  if ((!ipv6 && !/^[a-zA-Z0-9._-]+$/.test(host)) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new BackendAccessError(localize('backendRequest.invalidOrigin', 'BACKEND_HOST / BACKEND_PORT'));
  }
  return parseBackendUrl(`http://${ipv6 ? `[${literalHost}]` : host}:${port}`, 'BACKEND_HOST / BACKEND_PORT');
}

function makeTarget(url: URL, value?: string): BackendTarget {
  const token = value?.trim() ?? '';
  if (token) {
    if (!/^[!-~]+$/.test(token)) {
      throw new BackendAccessError(localize('backendRequest.invalidToken'));
    }
    const host = url.hostname;
    const loopback = host === 'localhost' || host === '[::1]' || (isIP(host) === 4 && host.startsWith('127.'));
    if (url.protocol !== 'https:' && !loopback) {
      throw new BackendAccessError(localize('backendRequest.httpsRequired'));
    }
  }
  return { url, token };
}

function requestFailure(signal?: AbortSignal): Error {
  if (signal?.aborted) {
    if (signal.reason?.name === 'TimeoutError') {
      return new BackendConnectionError(localize('backendRequest.timeout'));
    }
    const error = new Error('Backend request aborted');
    error.name = 'AbortError';
    return error;
  }
  return new BackendConnectionError(localize('backendRequest.offline'));
}

function discardBody(response: Response): void {
  void response.body?.cancel().catch(() => {});
}

/** Module test diagnostics reach both webviews and the output channel. */
function redactModuleTestDiagnostics(data: unknown, token: string): void {
  if (!data || typeof data !== 'object') {
    return;
  }
  const response = data as Record<string, unknown>;
  const redactFields = (result: Record<string, unknown>, outputKey: 'test_output' | 'output'): void => {
    for (const key of [outputKey, 'error']) {
      const value = result[key];
      if (value !== undefined) {
        result[key] = typeof value === 'string' ? value.split(token).join('…') : undefined;
      }
    }
  };
  redactFields(response, 'test_output');
  if (Array.isArray(response.results)) {
    for (const result of response.results) {
      if (result && typeof result === 'object') {
        redactFields(result as Record<string, unknown>, 'output');
      }
    }
  } else {
    delete response.results;
  }
}

/** HTTP transport for AS2 routes, used only in the extension host. */
export class BackendService {
  private managed?: { workspacePath: string; target: BackendTarget };

  constructor(private readonly envManager = new EnvManager()) {}

  readConfiguredEnv(): BackendEnvConfig {
    try {
      return this.envManager.readBackendEnv();
    } catch {
      throw new BackendAccessError(localize('backendRequest.envReadFailed'));
    }
  }

  /** Prepare one target from the child's launch environment, then pin it after spawn. */
  prepareManagedBackend(env: ManagedBackendEnv, workspacePath: string): () => void {
    const url = hostPortOrigin({ backendHost: env.BACKEND_HOST, backendPort: Number(env.BACKEND_PORT) });
    const target = makeTarget(url, env.BACKEND_TOKEN);
    return () => { this.managed = { workspacePath, target }; };
  }

  clearManagedBackend(): void {
    this.managed = undefined;
  }

  private getTarget(config?: BackendEnvConfig): BackendTarget {
    if (this.managed && this.managed.workspacePath === this.envManager.getWorkspacePath()) {
      return this.managed.target;
    }
    config ??= this.readConfiguredEnv();
    const explicitUrl = config.backendUrl?.trim();
    const url = explicitUrl ? parseBackendUrl(explicitUrl, 'BACKEND_URL', true) : hostPortOrigin(config);
    // An inherited token belongs only to a child we launch. An external token must be bound explicitly.
    const token = config.backendToken?.trim();
    if (token) {
      const binding = config.backendTokenOrigin?.trim();
      if (!binding) {
        throw new BackendAccessError(localize('backendRequest.tokenOriginRequired'));
      }
      if (parseBackendUrl(binding, 'BACKEND_TOKEN_ORIGIN').origin !== url.origin) {
        throw new BackendAccessError(localize('backendRequest.tokenOriginMismatch'));
      }
    }
    return makeTarget(url, token);
  }

  getBaseUrl(): string {
    return formatBaseUrl(this.getTarget().url);
  }

  async getBrowserUrl(): Promise<string | undefined> {
    const target = this.getTarget();
    if (target.token) {
      throw new BackendAccessError(localize('backendRequest.browserAuthRequired'));
    }
    try {
      return await this.checkHealth(target) ? formatBaseUrl(target.url) : undefined;
    } catch (error) {
      // A token may be configured only on the server, not in the extension's environment.
      if (error instanceof BackendAccessError && error.status === 401) {
        throw new BackendAccessError(localize('backendRequest.browserAuthRequired'), 401);
      }
      if (error instanceof BackendConnectionError) {
        return undefined;
      }
      throw error;
    }
  }

  async getStatus(): Promise<BackendStatus> {
    return this.probe(() => this.getTarget());
  }

  async getStartupStatus(config: BackendEnvConfig): Promise<BackendStatus> {
    if (this.managed || config.backendUrl?.trim() || config.backendTokenOrigin !== undefined || !config.backendToken?.trim()) {
      return this.probe(() => this.getTarget(config));
    }

    // An unbound token is only for a child we launch. Validate the local launch target,
    // then probe without credentials; do not adopt an existing service with that token.
    const status = await this.probe(() => {
      const { url } = makeTarget(hostPortOrigin(config), config.backendToken);
      return { url, token: '' };
    });
    return status.isRunning
      ? { ...status, isRunning: false, error: localize('backendRequest.tokenOriginRequired') }
      : status;
  }

  /** A managed startup must not accept a response from another workspace's endpoint. */
  async getManagedStatus(): Promise<BackendStatus> {
    const target = this.managed?.target;
    return target ? this.probe(() => target) : { isRunning: false };
  }

  private async probe(resolveTarget: () => BackendTarget): Promise<BackendStatus> {
    let address: Pick<BackendStatus, 'url' | 'port'> = {};
    try {
      const target = resolveTarget();
      address = {
        url: formatBaseUrl(target.url),
        port: Number(target.url.port || (target.url.protocol === 'https:' ? 443 : 80)),
      };
      return { ...address, isRunning: await this.checkHealth(target) };
    } catch (error) {
      return {
        ...address,
        isRunning: false,
        ...(error instanceof BackendAccessError ? { error: error.message } : {}),
      };
    }
  }

  private async checkHealth(target: BackendTarget): Promise<boolean> {
    const response = await this.send(target, '/health', { signal: AbortSignal.timeout(3000) });
    discardBody(response);
    return response.ok;
  }

  async requestJson<T>(route: string, options: BackendRequestOptions = {}): Promise<T> {
    const target = this.getTarget();
    const response = await this.send(target, route, options);
    if (!response.ok) {
      discardBody(response);
      throw new Error(localize('backendRequest.httpError', response.status));
    }
    try {
      const data: unknown = await response.json();
      // Use the credential captured for this request, even if the workspace config changed in flight.
      if (target.token && route.split('?', 1)[0] === '/api/v1/custom/test') {
        redactModuleTestDiagnostics(data, target.token);
      }
      return data as T;
    } catch {
      throw options.signal?.aborted ? requestFailure(options.signal) : new Error(localize('backendRequest.invalidResponse'));
    }
  }

  private async send(target: BackendTarget, route: string, options: BackendRequestOptions): Promise<Response> {
    let url: URL;
    try {
      url = new URL(route, target.url);
    } catch {
      throw new BackendAccessError(localize('backendRequest.invalidRoute'));
    }
    const pathname = route.split('?', 1)[0];
    if (url.origin !== target.url.origin || url.pathname !== pathname || url.hash ||
        (pathname !== '/health' && !pathname.startsWith('/api/v1/'))) {
      throw new BackendAccessError(localize('backendRequest.invalidRoute'));
    }
    url.pathname = `${target.url.pathname}${pathname.slice(1)}`;

    const body = options.body === undefined ? undefined : JSON.stringify(options.body);
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    if (target.token) {
      headers.Authorization = `Bearer ${target.token}`;
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method: body === undefined ? 'GET' : 'POST',
        headers,
        body,
        signal: options.signal,
        redirect: 'manual',
      });
    } catch {
      throw requestFailure(options.signal);
    }

    // Never surface a redirect Location, auth challenge, or error body to the UI or logs.
    const status = response.status;
    if (status === 401 || status === 403 || (status >= 300 && status < 400)) {
      discardBody(response);
      const key = status === 401 ? 'unauthorized' : status === 403 ? 'forbidden' : 'redirect';
      throw new BackendAccessError(localize(`backendRequest.${key}`, status), status);
    }
    return response;
  }
}
