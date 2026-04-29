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

export async function requestJson<T = unknown>(
  url: string,
  options: RequestJsonOptions = {}
): Promise<JsonResponse<T>> {
  const parsedUrl = new URL(url);
  const transport = parsedUrl.protocol === 'https:' ? https : http;
  const method = options.method || 'GET';
  const body = options.body === undefined ? undefined : JSON.stringify(options.body);
  const headers: Record<string, string> = {
    ...options.headers,
  };

  if (body !== undefined) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    headers['Content-Length'] = Buffer.byteLength(body).toString();
  }

  return new Promise((resolve, reject) => {
    const request = transport.request(
      parsedUrl,
      {
        method,
        headers,
      },
      response => {
        const chunks: Buffer[] = [];

        response.on('data', chunk => {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        });

        response.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          let data: T;

          try {
            data = text ? JSON.parse(text) as T : undefined as T;
          } catch {
            data = text as T;
          }

          const status = response.statusCode || 0;
          resolve({
            ok: status >= 200 && status < 300,
            status,
            statusText: response.statusMessage || STATUS_TEXT[status] || '',
            data,
            text,
            json: async () => data,
          });
        });
      }
    );

    const timeoutMs = options.timeoutMs;
    let timeout: NodeJS.Timeout | undefined;

    if (timeoutMs !== undefined) {
      timeout = setTimeout(() => {
        request.destroy(new Error(`请求超时（${Math.round(timeoutMs / 1000)}秒）`));
      }, timeoutMs);
    }

    request.on('error', error => {
      reject(error);
    });

    request.on('close', () => {
      if (timeout !== undefined) {
        clearTimeout(timeout);
      }
    });

    if (body !== undefined) {
      request.write(body);
    }

    request.end();
  });
}
