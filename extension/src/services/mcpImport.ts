import { createHash } from 'crypto';
import { parse as parseToml } from 'smol-toml';
import { mcpConnectionKey, normalizeMcpHttpEndpoint, type McpServerRecord } from './mcpClient';

export type McpImportSource = 'claude' | 'codex' | 'file' | 'paste';
export type McpImportItem = {
  key: string;
  name: string;
  state: 'new' | 'same' | 'conflict' | 'invalid';
  server?: McpServerRecord;
  reason?: string;
};
export type McpImportPreview = { token: string; source: McpImportSource; items: McpImportItem[] };

export function managedMcpId(name: string): string {
  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48);
  return `agentsociety-${slug || 'server'}-${createHash('sha256').update(name.trim()).digest('hex').slice(0, 10)}`;
}

function stringMap(value: unknown): Record<string, string> | undefined {
  if (value === undefined) { return undefined; }
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.values(value).some((item) => typeof item !== 'string')) { throw new Error('invalid_mcp_map'); }
  return value as Record<string, string>;
}

export function parseMcpImport(text: string, source: McpImportSource, existing: McpServerRecord[]): McpImportItem[] {
  let document: Record<string, unknown>;
  try { document = JSON.parse(text); }
  catch { try { document = parseToml(text) as Record<string, unknown>; } catch { throw new Error('invalid_mcp_import'); } }
  if (!document || typeof document !== 'object' || Array.isArray(document)) { throw new Error('invalid_mcp_import'); }
  const rows = document.mcpServers ?? document.servers ?? document.mcp_servers;
  if (rows === undefined && (source === 'claude' || source === 'codex')) { return []; }
  if (!rows || typeof rows !== 'object' || Array.isArray(rows)) { throw new Error('invalid_mcp_import'); }
  return Object.entries(rows).map(([name, raw]) => {
    try {
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) { throw new Error('invalid_mcp_entry'); }
      const entry = raw as Record<string, unknown>;
      if (entry.type !== undefined && !['stdio', 'http', 'sse', 'streamable-http'].includes(String(entry.type))) { throw new Error('invalid_mcp_entry'); }
      const transport = entry.type === 'sse' ? 'sse' : typeof entry.url === 'string' ? 'http' : 'stdio';
      if (transport !== 'stdio' && !normalizeMcpHttpEndpoint(String(entry.url ?? ''))) { throw new Error('invalid_mcp_url'); }
      if (transport === 'stdio' && (typeof entry.command !== 'string' || !entry.command.trim())) { throw new Error('invalid_mcp_command'); }
      if (entry.args !== undefined && (!Array.isArray(entry.args) || entry.args.some((arg) => typeof arg !== 'string'))) { throw new Error('invalid_mcp_args'); }
      const target = existing.find((row) => row.id === name || row.name === name);
      if (target?.builtin === 'literature') { throw new Error('literature_mcp_readonly'); }
      if (transport === 'sse' && (source === 'codex' || target?.enabledCodex)) { throw new Error('sse_claude_only'); }
      const commonKeys = new Set(['type', 'command', 'args', 'env', 'url', 'headers', 'http_headers', 'bearer_token_env_var', 'enabled', 'disabled']);
      const extra = Object.fromEntries(Object.entries(entry).filter(([key]) => !commonKeys.has(key)));
      const server: McpServerRecord = {
        ...target,
        id: target?.id ?? (source === 'claude' || source === 'codex' ? name : managedMcpId(name)),
        name: target?.name ?? name, transport,
        command: transport === 'stdio' ? entry.command as string : undefined,
        args: transport === 'stdio' ? entry.args as string[] | undefined : undefined,
        env: transport === 'stdio' ? stringMap(entry.env) : undefined,
        url: transport === 'stdio' ? undefined : entry.url as string,
        httpHeaders: stringMap(entry.headers ?? entry.http_headers),
        bearerTokenEnvVar: typeof entry.bearer_token_env_var === 'string' ? entry.bearer_token_env_var : source === 'claude' ? target?.bearerTokenEnvVar : undefined,
        claudeOptions: source === 'claude' || (source !== 'codex' && !document.mcp_servers) ? extra : target?.claudeOptions,
        codexOptions: source === 'codex' || Boolean(document.mcp_servers) ? extra : target?.codexOptions,
        enabledClaude: source === 'claude' ? entry.disabled !== true : target?.enabledClaude ?? false,
        enabledCodex: source === 'codex' ? entry.enabled !== false : target?.enabledCodex ?? false,
      };
      const unchanged = target && mcpConnectionKey(target) === mcpConnectionKey(server) && target.enabledClaude === server.enabledClaude && target.enabledCodex === server.enabledCodex && JSON.stringify(target.claudeOptions ?? {}) === JSON.stringify(server.claudeOptions ?? {}) && JSON.stringify(target.codexOptions ?? {}) === JSON.stringify(server.codexOptions ?? {});
      return { key: name, name, state: unchanged ? 'same' : target ? 'conflict' : 'new', server };
    } catch (error) {
      return { key: name, name, state: 'invalid', reason: error instanceof Error ? error.message : 'invalid_mcp_entry' };
    }
  });
}

export function applyMcpImport(existing: McpServerRecord[], items: McpImportItem[], selected: string[], targets: { claude: boolean; codex: boolean }): { servers: McpServerRecord[]; added: number; updated: number; skipped: number } {
  const servers = new Map(existing.filter((row) => row.builtin !== 'literature').map((row) => [row.id, row]));
  let added = 0, updated = 0;
  const keys = new Set(selected);
  for (const item of items) {
    if (!keys.has(item.key) || !item.server || !['new', 'conflict'].includes(item.state)) { continue; }
    const record = { ...item.server };
    if (targets.claude) { record.enabledClaude = true; }
    if (targets.codex) {
      if (record.transport === 'sse') { throw new Error('sse_claude_only'); }
      record.enabledCodex = true;
    }
    if (servers.has(record.id)) { updated++; } else { added++; }
    servers.set(record.id, record);
  }
  return { servers: [...servers.values()], added, updated, skipped: items.length - added - updated };
}
