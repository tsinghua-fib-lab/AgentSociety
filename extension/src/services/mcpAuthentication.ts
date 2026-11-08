import { execFile } from 'child_process';
import * as vscode from 'vscode';
import { normalizeMcpHttpEndpoint, type McpServerRecord } from './mcpClient';

export type McpAuthApp = 'claude' | 'codex';

/** Credentials and OAuth discovery stay in the client that will use the server. */
export async function openMcpAuthentication(server: McpServerRecord, app: McpAuthApp, proxyEnv?: Record<string, string>): Promise<void> {
  if (server.transport !== 'http' || !server.url || !normalizeMcpHttpEndpoint(server.url)) { throw new Error('mcp_auth_http_required'); }
  if (!(app === 'codex' ? server.enabledCodex : server.enabledClaude)) { throw new Error('mcp_auth_client_disabled'); }
  // Windows npm shims require cmd.exe. Limit its sole variable argument to a server identifier.
  if (!/^[a-zA-Z0-9_][a-zA-Z0-9_-]*$/.test(server.id)) { throw new Error('mcp_auth_invalid_id'); }
  const name = `MCP OAuth · ${app === 'codex' ? 'Codex' : 'Claude Code'} · ${server.id}`;
  const running = vscode.window.terminals.find((terminal) => terminal.name === name && terminal.exitStatus === undefined);
  if (running) { running.show(); return; }
  const env = { ...process.env, ...proxyEnv };
  const help = await new Promise<string>((resolve, reject) => {
    execFile(app, ['mcp', 'login', '--help'], { env, timeout: 8000, maxBuffer: 64 * 1024, windowsHide: true, shell: process.platform === 'win32' }, (error, stdout) => {
      if (error) { reject(new Error((error as NodeJS.ErrnoException).code === 'ENOENT' ? 'mcp_auth_cli_missing' : 'mcp_auth_cli_unsupported')); }
      else { resolve(stdout); }
    });
  });
  const args = ['mcp', 'login', server.id];
  const remote = Boolean(vscode.env.remoteName) || (process.platform === 'linux' && !process.env.DISPLAY && !process.env.WAYLAND_DISPLAY);
  if (remote && help.includes('--no-browser')) { args.push('--no-browser'); }
  const terminal = vscode.window.createTerminal({
    name,
    shellPath: process.platform === 'win32' ? process.env.ComSpec || 'cmd.exe' : app,
    shellArgs: process.platform === 'win32' ? ['/d', '/c', [app, ...args].join(' ')] : args,
    cwd: vscode.workspace.workspaceFolders?.[0]?.uri,
    env: proxyEnv,
  });
  terminal.show();
}
