import * as crypto from 'crypto';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
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
    return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as Record<string, unknown>;
  } catch {
    return {};
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

function managedId(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `${MANAGED_PREFIX}${slug || 'server'}`;
}

function toClaudeMcpEntry(server: McpServerRecord): Record<string, unknown> {
  if (server.transport === 'http' || server.transport === 'sse') {
    const entry: Record<string, unknown> = {
      type: server.transport,
      url: server.url ?? '',
    };
    if (server.httpHeaders && Object.keys(server.httpHeaders).length > 0) {
      entry.headers = server.httpHeaders;
    }
    return entry;
  }
  const entry: Record<string, unknown> = {
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
  if (server.transport === 'sse') {
    throw new Error('Legacy SSE MCP is supported by Claude only; use streamable HTTP for Codex.');
  }
  const lines: string[] = [`[mcp_servers.${JSON.stringify(server.id)}]`];
  if (server.transport === 'http') {
    lines.push(`url = ${JSON.stringify(server.url ?? '')}`);
    if (server.bearerTokenEnvVar?.trim()) {
      lines.push(`bearer_token_env_var = ${JSON.stringify(server.bearerTokenEnvVar.trim())}`);
    }
    if (server.httpHeaders) {
      for (const [key, value] of Object.entries(server.httpHeaders)) {
        lines.push(`http_headers.${JSON.stringify(key)} = ${JSON.stringify(value)}`);
      }
    }
    return lines;
  }
  lines.push(`command = ${JSON.stringify(server.command ?? '')}`);
  if (server.args && server.args.length > 0) {
    lines.push(`args = ${JSON.stringify(server.args)}`);
  }
  if (server.env) {
    for (const [key, value] of Object.entries(server.env)) {
      lines.push(`env.${JSON.stringify(key)} = ${JSON.stringify(value)}`);
    }
  }
  return lines;
}

function removeCodexMcpBlocks(text: string, serverIds: string[]): string {
  let updated = text;
  for (const id of serverIds) {
    const escapeRegex = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const escaped = `(?:${escapeRegex(id)}|${escapeRegex(JSON.stringify(id))})`;
    updated = updated.replace(
      new RegExp(`\\n?\\[mcp_servers\\.${escaped}\\][^\\n]*(?:\\n(?!\\[)[^\\n]*)*`, 'g'),
      ''
    );
  }
  return updated;
}

function upsertCodexMcpBlocks(text: string, servers: McpServerRecord[]): string {
  const ids = servers.map((s) => s.id);
  let updated = removeCodexMcpBlocks(text, ids).replace(/\n+$/, '');
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
    const id = input.id?.trim() || managedId(input.name);
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
    await this.syncLiveConfigs();
    return this.listServers();
  }

  async removeServer(id: string): Promise<McpServerRecord[]> {
    const target = this.listServers().find((s) => s.id === id);
    if (!target || target.builtin === 'literature') {
      throw new Error('mcp_server_protected');
    }
    const servers = this.listServers().filter((s) => s.builtin !== 'literature' && s.id !== id);
    await this.persistCustomServers(servers);
    await this.syncLiveConfigs();
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
    await this.syncLiveConfigs();
    return this.listServers();
  }

  async importFromClaude(): Promise<McpServerRecord[]> {
    const claudeJson = readJsonFile(resolveClaudeJsonPath());
    const mcpServers = (claudeJson.mcpServers as Record<string, Record<string, unknown>> | undefined) ?? {};
    const custom = this.listServers().filter((s) => s.builtin !== 'literature');
    const byId = new Map(custom.map((s) => [s.id, s]));
    for (const [name, entry] of Object.entries(mcpServers)) {
      const id = name.startsWith(MANAGED_PREFIX) ? name : managedId(name);
      // F6(2026-11-06):Claude 的旧 HTTP+SSE 传输保留 sse 语义——
      // 此前一律降级成 http,回写改写 type,纯 SSE 服务器会坏。
      const transport: McpTransport =
        entry.type === 'http' || entry.type === 'sse' || typeof entry.url === 'string'
          ? (entry.type === 'sse' ? 'sse' : 'http')
          : 'stdio';
      byId.set(id, {
        id,
        name,
        transport,
        command: typeof entry.command === 'string' ? entry.command : undefined,
        args: Array.isArray(entry.args) ? entry.args.map(String) : undefined,
        env:
          entry.env && typeof entry.env === 'object'
            ? Object.fromEntries(
              Object.entries(entry.env as Record<string, unknown>).map(([k, v]) => [k, String(v)])
            )
            : undefined,
        url: typeof entry.url === 'string' ? entry.url : undefined,
        httpHeaders:
          entry.headers && typeof entry.headers === 'object'
            ? Object.fromEntries(
              Object.entries(entry.headers as Record<string, unknown>).map(([k, v]) => [k, String(v)])
            )
            : undefined,
        enabledClaude: true,
        enabledCodex: false,
      });
    }
    await this.persistCustomServers([...byId.values()]);
    await this.syncLiveConfigs();
    return this.listServers();
  }

  async syncLiveConfigs(): Promise<void> {
    const servers = this.listServers();
    const originalCodexText = readCodexConfigText();
    const codexServers = servers.filter((s) => s.id.startsWith(MANAGED_PREFIX) || s.enabledCodex);
    const codexText = upsertCodexMcpBlocks(originalCodexText, codexServers);

    const claudePath = resolveClaudeJsonPath();
    const claudeJson = readJsonFile(claudePath);
    const existing =
      (claudeJson.mcpServers as Record<string, Record<string, unknown>> | undefined) ?? {};
    const managedIds = new Set(servers.map((s) => s.id));
    const next: Record<string, Record<string, unknown>> = { ...existing };
    for (const id of Object.keys(next)) {
      if (id.startsWith(MANAGED_PREFIX) || managedIds.has(id)) {
        delete next[id];
      }
    }
    for (const server of servers) {
      if (server.enabledClaude) {
        next[server.id] = toClaudeMcpEntry(server);
      }
    }
    claudeJson.mcpServers = next;
    writeJsonFile(claudePath, claudeJson);

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
