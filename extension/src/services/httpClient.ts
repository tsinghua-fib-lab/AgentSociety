import * as http from 'http';
import * as https from 'https';

export interface RequestJsonOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;
  timeoutMs?: number;
}

export interface JsonResponse<T = unknown> {
  ok: boolean;
  status: number;
  statusText: string;
  data: T;
  text: string;
  json(): Promise<T>;
}

const STATUS_TEXT: Record<number, string> = {
  400: 'Bad Request',
  401: 'Unauthorized',
  403: 'Forbidden',
  404: 'Not Found',
  408: 'Request Timeout',
  429: 'Too Many Requests',
  500: 'Internal Server Error',
  502: 'Bad Gateway',
  503: 'Service Unavailable',
  504: 'Gateway Timeout',
};

export function normalizeHttpUrl(urlString: string): string {
  try {
    const u = new URL(urlString);
    if (u.protocol === 'http:' && u.hostname === 'localhost') {
      u.hostname = '127.0.0.1';
    }
    return u.href;
  } catch {
    return urlString;
  }
}

function parseHttpUrl(resolvedUrl: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(resolvedUrl);
  } catch {
    throw new Error(`无效的 URL: ${resolvedUrl}`);
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(`不支持的协议: ${parsed.protocol}（仅支持 http 与 https）`);
  }
  return parsed;
}

function makeJsonResponse<T>(status: number, statusText: string, text: string): JsonResponse<T> {
  let data: T;
  try {
    data = text ? (JSON.parse(text) as T) : (undefined as T);
  } catch {
    data = text as T;
  }
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: statusText || STATUS_TEXT[status] || '',
    data,
    text,
    json: async () => data,
  };
}

async function requestJsonWithFetch<T>(
  resolvedUrl: string,
  options: RequestJsonOptions
): Promise<JsonResponse<T>> {
  parseHttpUrl(resolvedUrl);

  const method = options.method || 'GET';
  const serialized = options.body === undefined ? undefined : JSON.stringify(options.body);
  const headerObj: Record<string, string> = { ...(options.headers || {}) };
  if (serialized !== undefined) {
    const hasCt = Object.keys(headerObj).some(k => k.toLowerCase() === 'content-type');
    if (!hasCt) {
      headerObj['Content-Type'] = 'application/json';
    }
  }

  const headers = new Headers();
  for (const [k, v] of Object.entries(headerObj)) {
    if (k.toLowerCase() === 'content-length') {
      continue;
    }
    headers.set(k, v);
  }

  const init: RequestInit = { method, headers };
  if (serialized !== undefined) {
    init.body = serialized;
  }

  const timeoutMs = options.timeoutMs;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let abortForTimeout: AbortController | undefined;
  if (timeoutMs !== undefined) {
    abortForTimeout = new AbortController();
    init.signal = abortForTimeout.signal;
    timer = setTimeout(() => abortForTimeout!.abort(), timeoutMs);
  }

  try {
    const response = await fetch(resolvedUrl, init);
    const text = await response.text();
    return makeJsonResponse<T>(response.status, response.statusText, text);
  } catch (e) {
    if (
      timeoutMs !== undefined &&
      (abortForTimeout?.signal.aborted ||
        (e instanceof Error &&
          (e.name === 'AbortError' ||
            (e as NodeJS.ErrnoException).code === 'ABORT_ERR' ||
            e.message.includes('aborted'))))
    ) {
      throw new Error(`请求超时（${Math.round(timeoutMs / 1000)}秒）`);
    }
    throw e;
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}

function buildNodeRequestOptions(
  parsed: URL,
  method: string,
  headers: Record<string, string>
): { transport: typeof http | typeof https; reqOptions: http.RequestOptions } {
  const isHttps = parsed.protocol === 'https:';
  const transport = isHttps ? https : http;
  const defaultPort = isHttps ? 443 : 80;
  const port = parsed.port ? Number.parseInt(parsed.port, 10) : defaultPort;
  const pathWithQuery = `${parsed.pathname}${parsed.search}` || '/';

  const reqOptions: http.RequestOptions = {
    hostname: parsed.hostname,
    port,
    path: pathWithQuery,
    method,
    headers,
  };

  if (parsed.username !== '' || parsed.password !== '') {
    reqOptions.auth = `${decodeURIComponent(parsed.username)}:${decodeURIComponent(parsed.password)}`;
  }

  return { transport, reqOptions };
}

function requestJsonWithNode<T>(resolvedUrl: string, options: RequestJsonOptions): Promise<JsonResponse<T>> {
  const parsed = parseHttpUrl(resolvedUrl);
  const method = options.method || 'GET';
  const body = options.body === undefined ? undefined : JSON.stringify(options.body);
  const headers: Record<string, string> = {
    ...options.headers,
  };

  if (body !== undefined) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    headers['Content-Length'] = Buffer.byteLength(body).toString();
  }

  const { transport, reqOptions } = buildNodeRequestOptions(parsed, method, headers);
  const timeoutMs = options.timeoutMs;

  return new Promise((resolve, reject) => {
    let settled = false;
    let timeout: NodeJS.Timeout | undefined;

    const settle = (fn: () => void) => {
      if (settled) {
        return;
      }
      settled = true;
      if (timeout !== undefined) {
        clearTimeout(timeout);
      }
      fn();
    };

    const request = transport.request(
      reqOptions,
      response => {
        const chunks: Buffer[] = [];

        response.on('data', chunk => {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        });

        response.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          const status = response.statusCode || 0;
          const jr = makeJsonResponse<T>(status, response.statusMessage || '', text);
          settle(() => resolve(jr));
        });
      }
    );

    if (timeoutMs !== undefined) {
      timeout = setTimeout(() => {
        request.destroy();
        settle(() =>
          reject(new Error(`请求超时（${Math.round(timeoutMs / 1000)}秒）`))
        );
      }, timeoutMs);
    }

    request.on('error', error => {
      settle(() => reject(error));
    });

    if (body !== undefined) {
      request.write(body);
    }

    request.end();
  });
}

export async function requestJson<T = unknown>(
  url: string,
  options: RequestJsonOptions = {}
): Promise<JsonResponse<T>> {
  const resolvedUrl = normalizeHttpUrl(url);
  if (typeof globalThis.fetch === 'function') {
    return requestJsonWithFetch<T>(resolvedUrl, options);
  }
  return requestJsonWithNode<T>(resolvedUrl, options);
}
