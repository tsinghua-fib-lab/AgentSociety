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
  claudeOptions?: Record<string, unknown>;
  codexOptions?: Record<string, unknown>;
  builtin?: 'literature' | 'agentsociety';
};

export function mcpConnectionKey(server: McpServerRecord): string {
  return JSON.stringify([server.transport, server.url, server.command, server.args, server.env, server.httpHeaders, server.bearerTokenEnvVar]);
}

export type McpProbeResult = {
  ok: boolean;
  status: number;
  tools: string[];
  error?: string;
};

export type McpRpcResponse = {
  ok: boolean;
  status: number;
  data: Record<string, unknown> | null;
  headers: Headers;
};

/** Read one JSON-RPC response, including SSE streams that remain open afterwards. */
async function readRpcResponse(response: Response, id: unknown): Promise<Record<string, unknown> | null> {
  if (!response.body || id === undefined || !response.ok) { await response.body?.cancel(); return null; }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const streaming = response.headers.get('content-type')?.includes('text/event-stream');
  let buffer = '', size = 0;
  const parse = (text: string) => {
    const value = JSON.parse(text) as Record<string, unknown>;
    return value && value.jsonrpc === '2.0' && value.id === id ? value : null;
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) { break; }
      size += value.length;
      if (size > 1024 * 1024) { throw new Error('mcp_response_too_large'); }
      buffer += decoder.decode(value, { stream: true });
      if (streaming) {
        buffer = buffer.replace(/\r\n/g, '\n');
        let boundary: number;
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
          const event = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
          const data = event.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).replace(/^ /, '')).join('\n');
          if (!data.trim()) { continue; }
          const result = parse(data);
          if (result) { return result; }
        }
      }
    }
    buffer += decoder.decode();
    return streaming || !buffer.trim() ? null : parse(buffer);
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
}

export async function mcpJsonRpc(
  endpoint: string,
  headers: Record<string, string> | undefined,
  payload: Record<string, unknown>,
  timeoutMs = 20_000
): Promise<McpRpcResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1, timeoutMs));
  try {
    const res = await fetch(endpoint, {
      method: 'POST', redirect: 'manual',
      headers: { ...(headers ?? {}), 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
      body: JSON.stringify(payload), signal: controller.signal,
    });
    const data = await readRpcResponse(res, payload.id);
    return { ok: res.ok && (payload.id === undefined || Boolean(data && !data.error && data.result)), status: res.status, data, headers: res.headers };
  } finally { clearTimeout(timer); }
}

export function normalizeMcpHttpEndpoint(mcpUrl: string): string | null {
  try {
    const url = new URL(mcpUrl.trim());
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !url.hash ? url.href : null;
  } catch { return null; }
}

export function mcpSessionHeaders(init: McpRpcResponse, headers?: Record<string, string>): Record<string, string> {
  const result = init.data?.result as { protocolVersion?: string } | undefined;
  const session = init.headers.get('mcp-session-id');
  return {
    ...headers,
    ...(session ? { 'Mcp-Session-Id': session } : {}),
    ...(result?.protocolVersion ? { 'MCP-Protocol-Version': result.protocolVersion } : {}),
  };
}

export async function probeHttpMcpServer(url: string, headers?: Record<string, string>): Promise<McpProbeResult> {
  const endpoint = normalizeMcpHttpEndpoint(url);
  if (!endpoint) { return { ok: false, status: 0, tools: [], error: 'invalid_mcp_url' }; }
  const deadline = Date.now() + 20_000;
  const request = (payload: Record<string, unknown>, auth = headers) => {
    const remaining = deadline - Date.now();
    if (remaining <= 0) { throw new Error('mcp_timeout'); }
    return mcpJsonRpc(endpoint, auth, payload, remaining);
  };
  let sessionHeaders: Record<string, string> | undefined;
  try {
    const init = await request({ jsonrpc: '2.0', id: 1, method: 'initialize', params: {
      protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'agentsociety-extension', version: '1.8.1' },
    } });
    if (!init.ok) { return { ok: false, status: init.status, tools: [], error: `initialize: HTTP ${init.status}${init.data?.error ? ' / JSON-RPC error' : ''}` }; }
    const auth = mcpSessionHeaders(init, headers);
    sessionHeaders = auth;
    const ready = await request({ jsonrpc: '2.0', method: 'notifications/initialized' }, auth);
    if (!ready.ok) { return { ok: false, status: ready.status, tools: [], error: `initialized: HTTP ${ready.status}` }; }
    const capabilities = (init.data?.result as { capabilities?: { tools?: unknown } } | undefined)?.capabilities;
    if (!capabilities?.tools) { return { ok: true, status: 200, tools: [] }; }
    const tools = new Set<string>(), cursors = new Set<string>();
    let cursor: string | undefined;
    do {
      const list = await request({ jsonrpc: '2.0', id: 2 + cursors.size, method: 'tools/list', params: cursor ? { cursor } : {} }, auth);
      const result = list.data?.result as { tools?: Array<{ name?: unknown }>; nextCursor?: unknown } | undefined;
      if (!list.ok || !Array.isArray(result?.tools)) { return { ok: false, status: list.status, tools: [], error: `tools/list: HTTP ${list.status} / invalid JSON-RPC result` }; }
      for (const tool of result.tools) { if (typeof tool.name === 'string') { tools.add(tool.name); } }
      cursor = typeof result.nextCursor === 'string' && result.nextCursor ? result.nextCursor : undefined;
      if (cursor && cursors.has(cursor)) { throw new Error('mcp_repeated_cursor'); }
      if (cursor) { cursors.add(cursor); }
    } while (cursor);
    return { ok: true, status: 200, tools: [...tools] };
  } catch (error) {
    const timeout = error instanceof Error && (error.name === 'AbortError' || error.message === 'mcp_timeout');
    return { ok: false, status: 0, tools: [], error: timeout ? 'mcp_timeout' : 'mcp_connection_or_protocol_error' };
  } finally {
    if (sessionHeaders?.['Mcp-Session-Id'] && Date.now() < deadline) {
      try {
        const response = await fetch(endpoint, { method: 'DELETE', headers: sessionHeaders, redirect: 'manual', signal: AbortSignal.timeout(Math.max(1, Math.min(1000, deadline - Date.now()))) });
        await response.body?.cancel();
      } catch { /* Probe results remain available when a server cannot terminate sessions. */ }
    }
  }
}
