export type McpTransport = 'stdio' | 'http' | 'sse';

export type McpServerRecord = {
  id: string;
  name: string;
  transport: McpTransport;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  bearerTokenEnvVar?: string;
  httpHeaders?: Record<string, string>;
  enabledClaude: boolean;
  enabledCodex: boolean;
  builtin?: 'literature' | 'agentsociety';
};

export type McpProbeResult = {
  ok: boolean;
  status: number;
  tools: string[];
  error?: string;
};

export async function mcpJsonRpc(
  endpoint: string,
  headers: Record<string, string> | undefined,
  payload: Record<string, unknown>,
  timeoutMs = 20_000
): Promise<{ ok: boolean; status: number; data: unknown | null }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: {
        ...(headers ?? {}),
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const text = await res.text();
    let data: unknown = null;
    for (const line of text.split(/\r?\n/)) {
      if (line.startsWith('data: ')) {
        try {
          data = JSON.parse(line.slice('data: '.length));
        } catch {
          /* ignore */
        }
      }
    }
    if (data === null) {
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }
    return { ok: res.ok, status: res.status, data };
  } finally {
    clearTimeout(timer);
  }
}

export function normalizeMcpHttpEndpoint(mcpUrl: string): string | null {
  const trimmed = mcpUrl.trim();
  if (!trimmed) {
    return null;
  }
  const normalized = trimmed.endsWith('/mcp') ? `${trimmed}/` : trimmed;
  if (!normalized.endsWith('/mcp/')) {
    return null;
  }
  try {
    return new URL(normalized).toString();
  } catch {
    return null;
  }
}

export async function probeHttpMcpServer(
  url: string,
  headers?: Record<string, string>
): Promise<McpProbeResult> {
  try {
    return await probeHttpMcpServerInner(url, headers);
  } catch (err) {
    // F8(2026-11-06):网络异常(DNS/拒连)此前变成未处理 rejection,
    // webview 按钮永久转圈——统一转为失败结果。
    return {
      ok: false,
      status: 0,
      tools: [],
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

async function probeHttpMcpServerInner(
  url: string,
  headers?: Record<string, string>
): Promise<McpProbeResult> {
  const endpoint = normalizeMcpHttpEndpoint(url);
  if (!endpoint) {
    return { ok: false, status: 0, tools: [], error: 'invalid_mcp_url' };
  }
  const init = await mcpJsonRpc(endpoint, headers, {
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: { name: 'agentsociety-extension', version: '1.0.0' },
    },
  });
  if (!init.ok) {
    return {
      ok: false,
      status: init.status,
      tools: [],
      error: `initialize HTTP ${init.status}`,
    };
  }
  await mcpJsonRpc(endpoint, headers, {
    jsonrpc: '2.0',
    method: 'notifications/initialized',
    params: {},
  });
  const list = await mcpJsonRpc(endpoint, headers, {
    jsonrpc: '2.0',
    id: 2,
    method: 'tools/list',
    params: {},
  });
  const tools: string[] = [];
  if (list.data && typeof list.data === 'object') {
    const result = (list.data as Record<string, unknown>).result;
    if (result && typeof result === 'object') {
      const items = (result as Record<string, unknown>).tools;
      if (Array.isArray(items)) {
        for (const item of items) {
          if (item && typeof item === 'object' && typeof (item as Record<string, unknown>).name === 'string') {
            tools.push((item as Record<string, unknown>).name as string);
          }
        }
      }
    }
  }
  return { ok: list.ok, status: list.status, tools, error: list.ok ? undefined : 'tools/list failed' };
}
