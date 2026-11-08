import * as crypto from 'crypto';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { parse as parseToml, stringify as stringifyToml } from 'smol-toml';
import { isDeepStrictEqual } from 'util';
import { applyMcpImport, managedMcpId, parseMcpImport, type McpImportPreview, type McpImportSource } from './mcpImport';
import { EnvManager } from '../envManager';
import { readCodexConfigText, writeCodexConfigText } from './codexSettings';
import type { McpServerRecord, McpTransport } from './mcpClient';

const MCP_SERVERS_STATE_KEY = 'agentsociety.mcpServers.v1';
const MANAGED_PREFIX = 'agentsociety-';

export type McpServerInput = Omit<McpServerRecord, 'id'> & { id?: string };

function resolveClaudeJsonPath(): string {
  return path.join(os.homedir(), '.claude.json');
}

function readJsonFile(filePath: string): Record<string, unknown> {
  if (!fs.existsSync(filePath)) {
    return {};
  }
  try {
    const data: unknown = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    if (!data || typeof data !== 'object' || Array.isArray(data)) { throw new Error('invalid_claude_config'); }
    const servers = (data as Record<string, unknown>).mcpServers;
    if (servers !== undefined && (!servers || typeof servers !== 'object' || Array.isArray(servers))) { throw new Error('invalid_claude_config'); }
    return data as Record<string, unknown>;
  } catch {
    throw new Error('invalid_claude_config');
  }
}

function writeJsonFile(filePath: string, data: Record<string, unknown>): void {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  const json = `${JSON.stringify(data, null, 2)}\n`;
  // F2(2026-11-06):pid 后缀防多窗口同 tmp 路径交错。
  const tmp = `${filePath}.${process.pid}.${crypto.randomUUID()}.tmp`;
  fs.writeFileSync(tmp, json, 'utf-8');
  try {
    fs.chmodSync(tmp, 0o600);
  } catch {
    /* ignore */
  }
  fs.renameSync(tmp, filePath);
}

function toClaudeMcpEntry(server: McpServerRecord): Record<string, unknown> {
  if (server.transport === 'http' || server.transport === 'sse') {
    const entry: Record<string, unknown> = {
      ...server.claudeOptions,
      type: server.transport,
      url: server.url ?? '',
    };
    if (server.httpHeaders && Object.keys(server.httpHeaders).length > 0) {
      entry.headers = server.httpHeaders;
    }
    return entry;
  }
  const entry: Record<string, unknown> = {
    ...server.claudeOptions,
    command: server.command ?? '',
  };
  if (server.args && server.args.length > 0) {
    entry.args = server.args;
  }
  if (server.env && Object.keys(server.env).length > 0) {
    entry.env = server.env;
  }
  return entry;
}

function codexMcpBlockLines(server: McpServerRecord): string[] {
  if (server.transport === 'sse') { throw new Error('Legacy SSE MCP is supported by Claude only; use streamable HTTP for Codex.'); }
  const entry: Record<string, unknown> = { ...server.codexOptions };
  if (server.transport === 'http') {
    entry.url = server.url ?? '';
    if (server.bearerTokenEnvVar?.trim()) { entry.bearer_token_env_var = server.bearerTokenEnvVar.trim(); }
    if (server.httpHeaders) { entry.http_headers = server.httpHeaders; }
  } else {
    entry.command = server.command ?? '';
    if (server.args?.length) { entry.args = server.args; }
    if (server.env) { entry.env = server.env; }
  }
  return stringifyToml({ mcp_servers: { [server.id]: entry } } as Parameters<typeof stringifyToml>[0]).trim().split('\n');
}

function removeCodexMcpBlocks(text: string, serverIds: string[]): string {
  let updated = text;
  const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const id of serverIds) {
    const keys = [id, JSON.stringify(id), ...(!id.includes("'") && !id.includes('\n') ? ["'" + id + "'"] : [])].map(escape).join('|');
    updated = updated.replace(new RegExp(`\\n?\\[\\s*mcp_servers\\s*\\.\\s*(?:${keys})(?:\\s*\\.[^\\n]*)?\\s*\\][^\\n]*(?:\\n(?!\\s*\\[)[^\\n]*)*`, 'g'), '');
  }
  return updated;
}

function upsertCodexMcpBlocks(text: string, servers: McpServerRecord[]): string {
  const ids = servers.map((s) => s.id);
  let updated = removeCodexMcpBlocks(text, ids);
  if (!servers.some((server) => server.enabledCodex)) { return updated; }
  updated = updated.replace(/\n+$/, '');
  for (const server of servers) {
    if (!server.enabledCodex) {
      continue;
    }
    updated += ['', ...codexMcpBlockLines(server), ''].join('\n');
  }
  return updated;
}

function literatureServerFromEnv(): McpServerRecord | null {
  const env = new EnvManager().readEnv();
  const url = env.literatureSearchMcpUrl?.trim();
  if (!url) {
    return null;
  }
  const headers: Record<string, string> = {};
  const apiKey = env.literatureSearchApiKey?.trim();
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }
  return {
    id: `${MANAGED_PREFIX}literature-search`,
    name: 'Literature Search',
    transport: 'http',
    url,
    httpHeaders: Object.keys(headers).length > 0 ? headers : undefined,
    enabledClaude: true,
    enabledCodex: false,
    builtin: 'literature',
  };
}

export class McpServerManager {
  private pendingImport?: { preview: McpImportPreview; baseline: string };
  constructor(private readonly context: vscode.ExtensionContext) { }

  listServers(): McpServerRecord[] {
    const stored = this.context.globalState.get<McpServerRecord[]>(MCP_SERVERS_STATE_KEY) ?? [];
    const literature = literatureServerFromEnv();
    if (!literature) {
      return stored.filter((s) => s.builtin !== 'literature');
    }
    const withoutLiterature = stored.filter((s) => s.builtin !== 'literature');
    return [literature, ...withoutLiterature];
  }

  async saveServer(input: McpServerInput): Promise<McpServerRecord[]> {
    if (input.builtin === 'literature') {
      throw new Error('literature_mcp_readonly');
    }
    if (input.transport === 'sse' && input.enabledCodex) {
      throw new Error('Legacy SSE MCP is supported by Claude only; use streamable HTTP for Codex.');
    }
    const servers = this.listServers().filter((s) => s.builtin !== 'literature');
    const id = input.id?.trim() || managedMcpId(input.name);
    if (!input.id && servers.some((server) => server.id === id || server.name === input.name.trim())) { throw new Error('mcp_server_exists'); }
    const record: McpServerRecord = {
      id,
      name: input.name.trim() || id,
      transport: input.transport,
      command: input.command,
      args: input.args,
      env: input.env,
      url: input.url,
      bearerTokenEnvVar: input.bearerTokenEnvVar,
      httpHeaders: input.httpHeaders,
      claudeOptions: input.claudeOptions,
      codexOptions: input.codexOptions,
      enabledClaude: input.enabledClaude,
      enabledCodex: input.enabledCodex,
    };
    const index = servers.findIndex((s) => s.id === id);
    if (index >= 0) {
      servers[index] = record;
    } else {
      servers.push(record);
    }
    await this.persistCustomServers(servers);
    await this.syncLiveConfigs([], [id]);
    return this.listServers();
  }

  async removeServer(id: string): Promise<McpServerRecord[]> {
    const target = this.listServers().find((s) => s.id === id);
    if (!target || target.builtin === 'literature') {
      throw new Error('mcp_server_protected');
    }
    const servers = this.listServers().filter((s) => s.builtin !== 'literature' && s.id !== id);
    await this.persistCustomServers(servers);
    await this.syncLiveConfigs([id], []);
    return this.listServers();
  }

  async toggleServerApp(id: string, app: 'claude' | 'codex', enabled: boolean): Promise<McpServerRecord[]> {
    const servers = this.listServers();
    const target = servers.find((s) => s.id === id);
    if (!target) {
      throw new Error('mcp_server_not_found');
    }
    if (target.builtin === 'literature') {
      throw new Error('literature_mcp_use_config_page');
    }
    if (target.transport === 'sse' && app === 'codex' && enabled) {
      throw new Error('Legacy SSE MCP is supported by Claude only; use streamable HTTP for Codex.');
    }
    const custom = servers.filter((s) => s.builtin !== 'literature').map((s) =>
      s.id === id
        ? {
          ...s,
          enabledClaude: app === 'claude' ? enabled : s.enabledClaude,
          enabledCodex: app === 'codex' ? enabled : s.enabledCodex,
        }
        : s
    );
    await this.persistCustomServers(custom);
    await this.syncLiveConfigs([], [id]);
    return this.listServers();
  }

  previewImport(source: McpImportSource, text?: string): McpImportPreview {
    const existing = this.listServers();
    const content = source === 'claude' ? JSON.stringify(readJsonFile(resolveClaudeJsonPath()))
      : source === 'codex' ? readCodexConfigText() : text ?? '';
    const preview: McpImportPreview = { token: crypto.randomUUID(), source, items: parseMcpImport(content, source, existing) };
    this.pendingImport = { preview, baseline: JSON.stringify(existing) };
    return preview;
  }

  async applyImport(token: string, selected: string[], targets: { claude: boolean; codex: boolean }): Promise<{ added: number; updated: number; skipped: number }> {
    const pending = this.pendingImport;
    if (!pending || pending.preview.token !== token || JSON.stringify(this.listServers()) !== pending.baseline) { throw new Error('mcp_import_changed'); }
    const result = applyMcpImport(this.listServers(), pending.preview.items, selected, targets);
    const changed = pending.preview.items.filter((item) => selected.includes(item.key) && ['new', 'conflict'].includes(item.state)).map((item) => item.server!.id);
    await this.persistCustomServers(result.servers);
    await this.syncLiveConfigs([], changed);
    this.pendingImport = undefined;
    return { added: result.added, updated: result.updated, skipped: result.skipped };
  }

  async syncLiveConfigs(removedIds: string[] = [], changedIds?: string[]): Promise<void> {
    const servers = this.listServers().filter((server) => !changedIds || changedIds.includes(server.id));
    const originalCodexText = readCodexConfigText();
    const codexText = upsertCodexMcpBlocks(removeCodexMcpBlocks(originalCodexText, removedIds), servers);
    const managedIds = new Set([...servers.map((server) => server.id), ...removedIds]);
    const before = parseToml(originalCodexText || '') as Record<string, unknown>;
    const after = parseToml(codexText || '') as Record<string, unknown>;
    for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
      if (key !== 'mcp_servers' && !isDeepStrictEqual(before[key], after[key])) { throw new Error('unsupported_codex_layout'); }
    }
    const previousMcp = (before.mcp_servers ?? {}) as Record<string, unknown>;
    const nextMcp = (after.mcp_servers ?? {}) as Record<string, unknown>;
    for (const id of managedIds) {
      const server = servers.find((entry) => entry.id === id && entry.enabledCodex);
      const expected = server ? (parseToml(codexMcpBlockLines(server).join('\n')).mcp_servers as Record<string, unknown>)[id] : undefined;
      if (!isDeepStrictEqual(nextMcp[id], expected)) { throw new Error('unsupported_codex_layout'); }
    }
    for (const key of Object.keys(previousMcp)) {
      if (!managedIds.has(key) && !isDeepStrictEqual(previousMcp[key], nextMcp[key])) { throw new Error('unsupported_codex_layout'); }
    }

    const claudePath = resolveClaudeJsonPath();
    const claudeJson = readJsonFile(claudePath);
    const existing =
      (claudeJson.mcpServers as Record<string, Record<string, unknown>> | undefined) ?? {};
    const next: Record<string, Record<string, unknown>> = Object.assign(Object.create(null), existing);
    for (const id of Object.keys(next)) {
      if (managedIds.has(id)) {
        delete next[id];
      }
    }
    for (const server of servers) {
      if (server.enabledClaude) {
        next[server.id] = toClaudeMcpEntry(server);
      }
    }
    if (!isDeepStrictEqual(existing, { ...next })) {
      claudeJson.mcpServers = next;
      writeJsonFile(claudePath, claudeJson);
    }

    // Removing the last managed block must clear the file; a truthiness guard
    // would leave the stale MCP enabled. Avoid creating an empty config when
    // nothing needs syncing to Codex.
    if (codexText !== originalCodexText) {
      writeCodexConfigText(codexText);
    }
  }

  private async persistCustomServers(servers: McpServerRecord[]): Promise<void> {
    await this.context.globalState.update(MCP_SERVERS_STATE_KEY, servers);
  }
}

export const MCP_SERVER_PRESETS: Array<
  Omit<McpServerRecord, 'id' | 'enabledClaude' | 'enabledCodex'> & { presetId: string; descriptionKey: string }
> = [
    {
      presetId: 'agentsociety-backend',
      descriptionKey: 'skillManagement.mcpPresetAgentsocietyDesc',
      name: 'AgentSociety Backend',
      transport: 'stdio',
      command: 'uv',
      args: ['run', 'python', '-m', 'agentsociety2.mcp'],
      env: { AGENTSOCIETY_BACKEND_URL: 'http://localhost:8001' },
    },
    {
      presetId: 'context7',
      descriptionKey: 'skillManagement.mcpPresetContext7Desc',
      name: 'Context7 Docs',
      transport: 'http',
      url: 'https://mcp.context7.com/mcp',
    },
  ];
