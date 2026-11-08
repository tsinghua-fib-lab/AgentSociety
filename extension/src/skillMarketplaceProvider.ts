import { DEFAULT_MCP_REGISTRY } from './shared/mcpRegistry';
import { fetchRegistryPage, normalizeRegistrySource, registryProxy } from './services/mcpRegistry';
import type { McpImportSource } from './services/mcpImport';
/**
 * 技能管理 Webview：Agent（后端 API）与 Claude（.claude/skills）；
 * 市场条目来自用户在设置中配置的 GitHub/GitLab/Gitee 源。
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { spawnSync } from 'child_process';
import type {
  MarketplaceSkill,
  AgentSkill,
  ClaudeCodeSkill,
  BuiltinSkill,
  BuiltinSkillVersionInfo,
  BundledPlugin,
  BundledPluginCommand,
  SkillPreset,
  SkillVersionRef,
  MarketplaceLoadError,
} from './webview/skillMarketplace/types';
import { ApiClient } from './apiClient';
import type { ProjectStructureProvider } from './projectStructureProvider';
import { SkillVersionManager } from './skillVersionManager';
import { getPlatformAdapter, type SkillSource } from './platforms';
import { getCurrentLanguageCode, localize } from './i18n';
import {
  CLAUDE_DISABLED_VAULT,
  CATEGORY_MAP,
  DEFAULT_CLAUDE_SKILL_SOURCES,
  DEFAULT_AGENT_SKILL_SOURCES,
  skillMdPathInDir,
  markdownBodyForPreview,
  parseFrontmatter,
  formatSkillName,
  normalizeSkillSources,
  isNetworkOrTimeoutError,
  dedupeMarketplaceSkills,
} from './skillMarketplace/utils';
import {
  isValidGitBranch,
  isValidGitRepoUrl,
  isValidSkillId,
  isSafeSkillRelativePath,
  isAllowedSkillSourceBaseUrl,
  isPathSafe,
  isUnderDir,
  canReadSkillDir,
} from './skillMarketplace/security';
import { ConfigPageViewProvider } from './configPageViewProvider';
import { McpServerManager, MCP_SERVER_PRESETS, type McpServerInput } from './services/mcpServerManager';
import { mcpConnectionKey, probeHttpMcpServer } from './services/mcpClient';
import { appendSharedOutputLine, OUTPUT_CHANNEL_MAIN } from './shared/outputChannels';

function hostFromMaybeUrl(value: string | undefined): string | undefined {
  const raw = (value ?? '').trim();
  if (!raw) {
    return undefined;
  }
  try {
    const withProtocol = /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(raw) ? raw : `https://${raw}`;
    const host = new URL(withProtocol).hostname.toLowerCase().replace(/^www\./, '');
    return host || undefined;
  } catch {
    return undefined;
  }
}

const PANEL_VIEW_TYPE = 'aiSocialScientist.skillMarketplace';

export class SkillMarketplacePanel {
  private _managedSkillNamesCache: Set<string> | null = null;

  /** F11(2026-11-06):扩展 skills/ 目录实际管理的技能名集合——
   * 守卫市场安装不得覆盖(此前只保护 agentsociety- 前缀,office
   * 平铺名 pdf/docx/xlsx/pptx 可被同名影子替换)。 */
  private getExtensionManagedSkillNames(): Set<string> {
    if (this._managedSkillNamesCache !== null) {
      return this._managedSkillNamesCache;
    }
    const names = new Set<string>();
    try {
      const skillsRoot = path.join(this._extensionUri.fsPath, 'skills');
      if (fs.existsSync(skillsRoot)) {
        for (const entry of fs.readdirSync(skillsRoot, { withFileTypes: true })) {
          if (entry.isDirectory() && !entry.name.startsWith('.')) {
            names.add(entry.name);
          }
        }
      }
    } catch {
      /* 目录不可读时退化为空前缀守卫 */
    }
    this._managedSkillNamesCache = names;
    return names;
  }


  public static current: SkillMarketplacePanel | undefined;

  private _registryRequest = 0;
  private readonly _context: vscode.ExtensionContext;
  private readonly _extensionUri: vscode.Uri;
  private readonly _panel: vscode.WebviewPanel;
  private readonly _webview: vscode.Webview;
  private readonly _apiClient: ApiClient;
  private readonly _projectStructureProvider: ProjectStructureProvider;
  private readonly _mcpManager: McpServerManager;

  private constructor(
    context: vscode.ExtensionContext,
    extensionUri: vscode.Uri,
    panel: vscode.WebviewPanel,
    apiClient: ApiClient,
    projectStructureProvider: ProjectStructureProvider
  ) {
    this._context = context;
    this._extensionUri = extensionUri;
    this._panel = panel;
    this._webview = panel.webview;
    this._apiClient = apiClient;
    this._projectStructureProvider = projectStructureProvider;
    this._mcpManager = new McpServerManager(context);

    this._webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri]
    };
    this._webview.html = this._getHtmlForWebview(this._webview);

    this._webview.onDidReceiveMessage(
      async (data) => {
        if (!data) {
          return;
        }
        switch (data.type) {
          case 'ready':
            // Installed skills, plugins and MCP servers have independent list requests.
            await Promise.all([this._loadSkillPresets(), this._loadMarketplaceSkills()]);
            break;

          // Agent Skills
          case 'listAgentSkills':
            await this._loadAgentSkills();
            break;

          // Claude Code Skills
          case 'listClaudeCodeSkills':
            await this._loadClaudeCodeSkills();
            break;
          case 'setClaudeSkillActive': {
            const pl = data.payload as { name?: string; origin?: string; active?: boolean };
            const name = typeof pl?.name === 'string' ? pl.name : '';
            const origin = pl?.origin === 'global' ? 'global' : 'workspace';
            if (typeof pl?.active !== 'boolean') {
              break;
            }
            await this._setClaudeSkillActive(name, origin, pl.active);
            break;
          }
          case 'purgeClaudeCodeSkill': {
            const pl = data.payload as { name?: string; origin?: string };
            const name = typeof pl?.name === 'string' ? pl.name : '';
            const origin = pl?.origin === 'global' ? 'global' : 'workspace';
            await this._purgeClaudeCodeSkill(name, origin);
            break;
          }

          // Marketplace
          case 'refreshMarketplace':
            await this._loadMarketplaceSkills();
            break;
          case 'installAgentSkill':
            await this._installAgentSkill(data.payload.skill);
            break;
          case 'installClaudeCodeSkill':
            await this._installClaudeCodeSkill(data.payload.skill);
            break;
          case 'importAgentSkill':
            await this._importAgentSkill();
            break;
          case 'importClaudeCodeSkill':
            await this._importClaudeCodeSkill();
            break;
          case 'listBuiltinSkills':
            await this._loadBuiltinSkills();
            break;
          case 'listBundledPlugins':
            await this._loadBundledPlugins();
            break;
          case 'scanAgentSkills':
            await this._scanAgentSkills();
            break;
          case 'updateExtensionSkills':
            await vscode.commands.executeCommand('aiSocialScientist.updateExtensionSkills');
            await this._loadBuiltinSkills();
            await this._loadClaudeCodeSkills();
            break;
          case 'openAgentSkillDoc':
            await vscode.commands.executeCommand(
              'aiSocialScientist.openAgentSkillDoc',
              data.payload.skillName,
              data.payload.skillPath,
              data.payload.isBuiltin,
              data.payload.skillId
            );
            break;
          case 'openLocalSkillMarkdown':
            this._openLocalSkillMarkdown(data.payload.skillDir);
            break;
          case 'openSkillFolder':
            this._openSkillFolder(data.payload.path);
            break;
          case 'fetchAgentSkillDetail':
            await this._fetchAgentSkillDetail(data.payload);
            break;
          case 'fetchLocalSkillMarkdown':
            await this._fetchLocalSkillMarkdown(data.payload.skillDir);
            break;
          case 'openExternal': {
            const uri = vscode.Uri.parse(String(data.payload.url ?? ''));
            if (uri.scheme === 'https' || uri.scheme === 'http') { await vscode.env.openExternal(uri); }
            break;
          }
          case 'openSkillSourcesSettings':
            await vscode.commands.executeCommand('workbench.action.openSettings', 'agentSkills.skillSources');
            break;
          case 'openClaudeSkillSourcesSettings':
            await vscode.commands.executeCommand('workbench.action.openSettings', 'agentSkills.claudeSkillSources');
            break;
          case 'syncOneClaudeSkillFromVsix': {
            const payload = data.payload as { name?: string } | undefined;
            const name = typeof payload?.name === 'string' ? payload.name : '';
            const r = this._projectStructureProvider.syncBundledClaudeSkillToWorkspace(name);
            if (r.success) {
              vscode.window.showInformationMessage(r.message);
            } else {
              vscode.window.showErrorMessage(r.message);
            }
            await this._loadClaudeCodeSkills();
            await this._loadBuiltinSkills();
            break;
          }

          // Skill Versioning
          case 'listSkillPresets':
            await this._loadSkillPresets();
            break;
          case 'applySkillPreset': {
            const pl = data.payload as { name?: string } | undefined;
            const name = typeof pl?.name === 'string' ? pl.name : '';
            await this._applySkillPreset(name);
            break;
          }
          case 'createSkillSnapshot': {
            const pl = data.payload as { skill?: string; tag?: string } | undefined;
            const skill = typeof pl?.skill === 'string' ? pl.skill : '';
            const tag = typeof pl?.tag === 'string' ? pl.tag : '';
            await this._createSkillSnapshot(skill, tag);
            break;
          }
          case 'savePreset': {
            const pl = data.payload as { name?: string; mapping?: Record<string, SkillVersionRef> } | undefined;
            const name = typeof pl?.name === 'string' ? pl.name : '';
            const mapping = pl?.mapping && typeof pl.mapping === 'object' ? pl.mapping : {};
            await this._savePreset(name, mapping);
            break;
          }
          case 'deletePreset': {
            const pl = data.payload as { name?: string } | undefined;
            const name = typeof pl?.name === 'string' ? pl.name : '';
            await this._deletePreset(name);
            break;
          }

          // Direct command-bridge from webview
          case 'invokeSwitchSkillVersionCommand':
            await vscode.commands.executeCommand('aiSocialScientist.switchSkillVersion');
            await this._loadBuiltinSkills();
            await this._loadSkillPresets();
            break;
          case 'invokeSnapshotSkillCommand': {
            const payload = data.payload as { skillName?: string } | undefined;
            await vscode.commands.executeCommand(
              'aiSocialScientist.snapshotCurrentSkill',
              payload?.skillName
            );
            await this._loadBuiltinSkills();
            break;
          }
          case 'invokeEditSkillPresetsCommand':
            await vscode.commands.executeCommand('aiSocialScientist.editSkillPresets');
            break;

          // Marketplace sources & GitHub token (from main)
          case 'getSkillSources': {
            const target = data.payload as 'agent' | 'claudeCode';
            await this._getSkillSources(target);
            break;
          }
          case 'saveSkillSources': {
            const payload = data.payload as {
              target: 'agent' | 'claudeCode';
              sources: Array<{
                owner: string;
                repo: string;
                branch?: string;
                skillsPath?: string;
                platform?: string;
                baseUrl?: string;
              }>;
            };
            await this._saveSkillSources(payload.target, payload.sources);
            break;
          }
          case 'getGithubToken': {
            await this._getGithubToken();
            break;
          }
          case 'saveGithubToken': {
            const payload = data.payload as { token: string };
            await this._saveGithubToken(payload.token);
            break;
          }
          case 'getSkillUpdateDiff': {
            const payload = data.payload as { skill: MarketplaceSkill } | undefined;
            if (payload?.skill) {
              await this._getSkillUpdateDiff(payload.skill);
            }
            break;
          }
          case 'confirmSkillUpdate': {
            const payload = data.payload as { skill: MarketplaceSkill } | undefined;
            if (payload?.skill) {
              await this._confirmSkillUpdate(payload.skill);
            }
            break;
          }

          case 'listMcpServers':
            await this._loadMcpServers();
            break;
          case 'saveMcpServer':
            await this._saveMcpServer(data.payload as McpServerInput, typeof data.requestId === 'string' ? data.requestId : undefined);
            break;
          case 'removeMcpServer': {
            const pl = data.payload as { id?: string } | undefined;
            const id = typeof pl?.id === 'string' ? pl.id : '';
            if (id) {
              await this._removeMcpServer(id);
            }
            break;
          }
          case 'toggleMcpServerApp': {
            const pl = data.payload as { id?: string; app?: 'claude' | 'codex'; enabled?: boolean } | undefined;
            const id = typeof pl?.id === 'string' ? pl.id : '';
            const app = pl?.app === 'codex' ? 'codex' : 'claude';
            const enabled = pl?.enabled === true;
            if (id) {
              await this._toggleMcpServerApp(id, app, enabled);
            }
            break;
          }
          case 'getMcpRegistrySource':
            await this._postMessage({ type: 'mcpRegistrySource', payload: { source: this._context.globalState.get<string>('agentsociety.mcpRegistrySource', DEFAULT_MCP_REGISTRY) } });
            break;
          case 'listMcpRegistry':
            await this._listMcpRegistry(data.payload);
            break;
          case 'previewMcpImport':
            await this._previewMcpImport(data.payload);
            break;
          case 'applyMcpImport':
            await this._applyMcpImport(data.payload);
            break;
          case 'syncMcpServers':
            await this._syncMcpServers();
            break;
          case 'probeMcpServer': {
            const pl = data.payload as { id?: string } | undefined;
            const id = typeof pl?.id === 'string' ? pl.id : '';
            if (id) {
              await this._probeMcpServer(id);
            }
            break;
          }
          case 'openLiteratureMcpConfig':
            await this._openLiteratureMcpConfig();
            break;
          case 'addMcpPreset': {
            const pl = data.payload as { presetId?: string } | undefined;
            await this._addMcpPreset(typeof pl?.presetId === 'string' ? pl.presetId : MCP_SERVER_PRESETS[0]?.presetId);
            break;
          }
        }
      },
      undefined,
      []
    );

    this._panel.onDidDispose(
      () => {
        SkillMarketplacePanel.current = undefined;
      },
      null,
      []
    );
  }

  public static createOrShow(
    context: vscode.ExtensionContext,
    apiClient: ApiClient,
    projectStructureProvider: ProjectStructureProvider,
    column: vscode.ViewColumn = vscode.ViewColumn.One
  ): void {
    if (SkillMarketplacePanel.current) {
      SkillMarketplacePanel.current._panel.reveal(column);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      PANEL_VIEW_TYPE,
      localize('skillMarketplace.title'),
      column,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [context.extensionUri]
      }
    );

    context.subscriptions.push(panel);
    SkillMarketplacePanel.current = new SkillMarketplacePanel(
      context,
      context.extensionUri,
      panel,
      apiClient,
      projectStructureProvider
    );
  }

  public reloadForLanguage(): void {
    this._panel.title = localize('skillMarketplace.title');
    this._webview.html = this._getHtmlForWebview(this._webview);
  }

  public static reloadLanguageIfOpen(): void {
    SkillMarketplacePanel.current?.reloadForLanguage();
  }

  private _log(message: string): void {
    appendSharedOutputLine(OUTPUT_CHANNEL_MAIN, message);
  }




  // ============ Agent Skills ============

  private async _loadAgentSkills(): Promise<void> {
    try {
      const response = await this._apiClient.listAgentSkills();
      if (response.success) {
        const skills: AgentSkill[] = response.skills.map(s => ({
          skill_id: s.skill_id,
          name: s.name,
          description: s.description,
          source: s.source,
          source_label: s.source_label,
          path: s.path,
          has_skill_md: s.has_skill_md,
          script: s.script,
        }));
        await this._postMessage({ type: 'agentSkillsLoaded', payload: skills });
      } else {
        await this._postMessage({ type: 'agentSkillsLoaded', payload: [] });
        await this._postMessage({ type: 'error', payload: 'Failed to load agent skills' });
      }
    } catch (error: any) {
      const message = error?.message || String(error);
      this._log(`[SkillManagement] Failed to load agent skills: ${message}`);
      await this._postMessage({ type: 'agentSkillsLoaded', payload: [] });
      await this._postMessage({ type: 'error', payload: message });
    }
  }

  private async _scanAgentSkills(options?: { quiet?: boolean }): Promise<void> {
    try {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      const response = await this._apiClient.scanAgentSkills(workspaceFolder?.uri.fsPath);
      if (response.success && !options?.quiet) {
        vscode.window.showInformationMessage(response.message);
      }
      await this._loadAgentSkills();
    } catch (error: any) {
      this._log(`[SkillManagement] Scan failed: ${error.message}`);
      await this._postMessage({ type: 'error', payload: error.message || String(error) });
    }
  }

  private async _loadBuiltinSkills(): Promise<void> {
    const skills: BuiltinSkill[] = [];
    const versionManager = this._projectStructureProvider.getSkillVersionManager();
    const wf = vscode.workspace.workspaceFolders?.[0];
    const presetMap = wf ? versionManager.getActivePreset(wf.uri.fsPath).map : {};

    const skillsDir = path.join(this._extensionUri.fsPath, 'skills');
    if (fs.existsSync(skillsDir)) {
      try {
        const names = fs.readdirSync(skillsDir).filter((name) => {
          const skillPath = path.join(skillsDir, name);
          if (!fs.statSync(skillPath).isDirectory()) {
            return false;
          }
          // Versioned skill: must have manifest.json
          if (SkillVersionManager.isVersioned(name)) {
            return fs.existsSync(path.join(skillPath, 'manifest.json'));
          }
          // Legacy/office skill: must have SKILL.md at top level
          return skillMdPathInDir(skillPath) !== null;
        });

        for (const name of names) {
          const skillPath = path.join(skillsDir, name);

          if (SkillVersionManager.isVersioned(name)) {
            const versions: BuiltinSkillVersionInfo[] = [
              ...versionManager.listBundledVersions(name),
              ...versionManager.listSnapshots(name),
            ];
            const ref = presetMap[name] ?? {
              source: 'bundled' as const,
              version: versionManager.defaultVersion(name) || undefined,
            };
            const activeId = ref.source === 'bundled' ? ref.version : ref.tag;

            // Use SKILL.md from active version dir for description preview
            const activePath =
              ref.source === 'bundled' && ref.version
                ? path.join(skillPath, ref.version)
                : skillPath;
            const mdPath = skillMdPathInDir(activePath);
            let description: string | undefined;
            if (mdPath) {
              try {
                const content = fs.readFileSync(mdPath, 'utf-8');
                const fm = parseFrontmatter(content);
                description = typeof fm.description === 'string' ? fm.description : undefined;
              } catch {
                /* ignore */
              }
            }

            skills.push({
              name,
              path: skillPath,
              hasSkillMd: mdPath !== null,
              description,
              isVersioned: true,
              activeVersion: activeId
                ? { source: ref.source, id: activeId }
                : undefined,
              availableVersions: versions,
              snapshotCount: versionManager.countSnapshots(name),
            });
          } else {
            // Legacy/office skill — flat layout
            const mdPath = skillMdPathInDir(skillPath)!;
            const content = fs.readFileSync(mdPath, 'utf-8');
            const frontmatter = parseFrontmatter(content);
            skills.push({
              name,
              path: skillPath,
              hasSkillMd: true,
              description:
                typeof frontmatter.description === 'string' ? frontmatter.description : undefined,
              isVersioned: false,
            });
          }
        }
      } catch (error: any) {
        this._log(`[SkillManagement] Failed to load extension skills: ${error.message}`);
      }
    }
    await this._postMessage({ type: 'builtinSkillsLoaded', payload: skills });
  }

  private async _loadBundledPlugins(): Promise<void> {
    const plugins: BundledPlugin[] = [];
    const pluginsDir = this._projectStructureProvider.getWorkspaceManager()?.getPluginsSourcePath();

    if (!pluginsDir || !fs.existsSync(pluginsDir)) {
      await this._postMessage({ type: 'bundledPluginsLoaded', payload: plugins });
      return;
    }

    for (const pluginName of fs.readdirSync(pluginsDir)) {
      const pluginPath = path.join(pluginsDir, pluginName);
      if (!fs.statSync(pluginPath).isDirectory()) {
        continue;
      }

      // Read plugin manifest
      const manifestPath = path.join(pluginPath, '.claude-plugin', 'plugin.json');
      if (!fs.existsSync(manifestPath)) {
        continue;
      }

      let manifest: any;
      try {
        manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
      } catch {
        continue;
      }

      // Scan plugin skills
      const pluginSkills: BuiltinSkill[] = [];
      const skillsDir = path.join(pluginPath, 'skills');
      if (fs.existsSync(skillsDir) && fs.statSync(skillsDir).isDirectory()) {
        for (const skillName of fs.readdirSync(skillsDir)) {
          const skillPath = path.join(skillsDir, skillName);
          if (!fs.statSync(skillPath).isDirectory()) {
            continue;
          }
          const mdPath = skillMdPathInDir(skillPath);
          let description: string | undefined;
          if (mdPath) {
            try {
              const content = fs.readFileSync(mdPath, 'utf-8');
              const fm = parseFrontmatter(content);
              description = typeof fm.description === 'string' ? fm.description : undefined;
            } catch { /* ignore */ }
          }
          pluginSkills.push({
            name: skillName,
            path: skillPath,
            hasSkillMd: mdPath !== null,
            description,
            isVersioned: false,
          });
        }
      }

      // Scan plugin commands
      const commands: BundledPluginCommand[] = [];
      const commandsDir = path.join(pluginPath, 'commands');
      if (fs.existsSync(commandsDir) && fs.statSync(commandsDir).isDirectory()) {
        for (const cmdFile of fs.readdirSync(commandsDir)) {
          if (!cmdFile.endsWith('.md')) {
            continue;
          }
          const cmdPath = path.join(commandsDir, cmdFile);
          let description: string | undefined;
          try {
            const content = fs.readFileSync(cmdPath, 'utf-8');
            // Extract first line as description (usually a summary)
            const firstLine = content.split('\n').find(l => l.trim().length > 0) || '';
            description = firstLine.replace(/^#+\s*/, '').trim() || undefined;
          } catch { /* ignore */ }
          commands.push({
            name: cmdFile.replace(/\.md$/, ''),
            path: cmdPath,
            description,
          });
        }
      }

      plugins.push({
        name: manifest.name || pluginName,
        version: manifest.version || '0.0.0',
        description: manifest.description || '',
        author: manifest.author?.name || manifest.author || '',
        path: pluginPath,
        skills: pluginSkills,
        commands,
      });
    }

    await this._postMessage({ type: 'bundledPluginsLoaded', payload: plugins });
  }

  private _openLocalSkillMarkdown(skillDir: string): void {
    const mdPath = skillMdPathInDir(skillDir);
    if (!mdPath) {
      vscode.window.showWarningMessage('SKILL.md not found');
      return;
    }
    void vscode.commands.executeCommand('markdown.showPreview', vscode.Uri.file(mdPath));
  }

  // ============ Claude Code Skills ============

  private async _loadClaudeCodeSkills(): Promise<void> {
    const skills: ClaudeCodeSkill[] = [];
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];

    if (workspaceFolder) {
      const workspaceSkillsPath = path.join(workspaceFolder.uri.fsPath, '.claude', 'skills');
      this._scanClaudeCodeSkills(workspaceSkillsPath, skills, 'workspace');
    }

    const globalSkillsPath = path.join(process.env.HOME || process.env.USERPROFILE || '', '.claude', 'skills');
    this._scanClaudeCodeSkills(globalSkillsPath, skills, 'global');

    await this._postMessage({ type: 'claudeCodeSkillsLoaded', payload: skills });
  }

  /**
   * Treat both real directories and symlinks-to-directories as valid skill dirs.
   * Dirent.isDirectory() uses lstat semantics and returns false for symlinks,
   * so version-managed skills (which we materialize as symlinks) would otherwise
   * be filtered out from the workspace skill listing.
   */
  private _isSkillDirEntry(entry: fs.Dirent, fullPath: string): boolean {
    if (entry.isDirectory()) {
      return true;
    }
    if (entry.isSymbolicLink()) {
      try {
        return fs.statSync(fullPath).isDirectory();
      } catch {
        return false;
      }
    }
    return false;
  }

  private _scanClaudeCodeSkills(dirPath: string, skills: ClaudeCodeSkill[], origin: 'workspace' | 'global'): void {
    if (!fs.existsSync(dirPath)) {
      return;
    }

    try {
      const entries = fs.readdirSync(dirPath, { withFileTypes: true });
      for (const entry of entries) {
        if (entry.name.startsWith('.')) {
          continue;
        }
        const skillPath = path.join(dirPath, entry.name);
        if (!this._isSkillDirEntry(entry, skillPath)) {
          continue;
        }
        const mdPath = skillMdPathInDir(skillPath);
        const hasSkillMd = mdPath !== null;

        let description: string | undefined;
        if (hasSkillMd && mdPath) {
          const content = fs.readFileSync(mdPath, 'utf-8');
          const frontmatter = parseFrontmatter(content);
          description = typeof frontmatter.description === 'string' ? frontmatter.description : undefined;
        }

        const files = fs.readdirSync(skillPath).filter(f => !f.startsWith('.'));

        skills.push({
          name: entry.name,
          path: skillPath,
          hasSkillMd,
          description,
          files,
          origin,
          active: true,
        });
      }
    } catch (error: any) {
      this._log(`[SkillManagement] Failed to scan ${dirPath}: ${error.message}`);
    }

    this._scanClaudeDisabledVault(dirPath, skills, origin);
  }

  private _scanClaudeDisabledVault(parentSkillsDir: string, skills: ClaudeCodeSkill[], origin: 'workspace' | 'global'): void {
    const vault = path.join(parentSkillsDir, CLAUDE_DISABLED_VAULT);
    if (!fs.existsSync(vault)) {
      return;
    }
    try {
      const entries = fs.readdirSync(vault, { withFileTypes: true });
      for (const entry of entries) {
        if (entry.name.startsWith('.')) {
          continue;
        }
        const skillPath = path.join(vault, entry.name);
        if (!this._isSkillDirEntry(entry, skillPath)) {
          continue;
        }
        const mdPath = skillMdPathInDir(skillPath);
        const hasSkillMd = mdPath !== null;
        let description: string | undefined;
        if (hasSkillMd && mdPath) {
          const content = fs.readFileSync(mdPath, 'utf-8');
          const frontmatter = parseFrontmatter(content);
          description = typeof frontmatter.description === 'string' ? frontmatter.description : undefined;
        }
        const files = fs.readdirSync(skillPath).filter(f => !f.startsWith('.'));
        skills.push({
          name: entry.name,
          path: skillPath,
          hasSkillMd,
          description,
          files,
          origin,
          active: false,
        });
      }
    } catch (error: any) {
      this._log(`[SkillManagement] Failed to scan vault ${vault}: ${error.message}`);
    }
  }

  private async _setClaudeSkillActive(name: string, origin: 'workspace' | 'global', active: boolean): Promise<void> {
    const wf = vscode.workspace.workspaceFolders?.[0];
    if (!name.trim()) {
      return;
    }
    if (origin === 'workspace' && !wf) {
      vscode.window.showErrorMessage('请先打开工作区文件夹');
      return;
    }
    const home = process.env.HOME || process.env.USERPROFILE || '';
    const skillsRoot =
      origin === 'workspace'
        ? path.join(wf!.uri.fsPath, '.claude', 'skills')
        : path.join(home, '.claude', 'skills');
    const vaultDir = path.join(skillsRoot, CLAUDE_DISABLED_VAULT);
    const activePath = path.join(skillsRoot, name);
    const vaultPath = path.join(vaultDir, name);

    try {
      if (active) {
        if (!fs.existsSync(vaultPath)) {
          vscode.window.showWarningMessage(`未在保管目录找到已关闭的技能: ${name}`);
          return;
        }
        if (fs.existsSync(activePath)) {
          vscode.window.showErrorMessage(`技能目录已存在，无法启用: ${name}`);
          return;
        }
        fs.renameSync(vaultPath, activePath);
        vscode.window.showInformationMessage(`已启用 Claude 技能「${name}」`);
      } else {
        if (!fs.existsSync(activePath)) {
          vscode.window.showWarningMessage(`未找到启用的技能目录: ${name}`);
          return;
        }
        fs.mkdirSync(vaultDir, { recursive: true });
        if (fs.existsSync(vaultPath)) {
          vscode.window.showErrorMessage(`保管目录已有同名技能，请手动处理冲突: ${name}`);
          return;
        }
        fs.renameSync(activePath, vaultPath);
        vscode.window.showInformationMessage(`已关闭 Claude 技能「${name}」（文件在 .claude/skills/${CLAUDE_DISABLED_VAULT}/）`);
      }
      await this._loadClaudeCodeSkills();
    } catch (error: any) {
      vscode.window.showErrorMessage(error?.message || String(error));
    }
  }

  private async _purgeClaudeCodeSkill(name: string, origin: 'workspace' | 'global'): Promise<void> {
    const wf = vscode.workspace.workspaceFolders?.[0];
    const home = process.env.HOME || process.env.USERPROFILE || '';
    const roots: string[] = [];
    if (origin === 'workspace' && wf) {
      roots.push(path.join(wf.uri.fsPath, '.claude', 'skills'));
    }
    if (origin === 'global' && home) {
      roots.push(path.join(home, '.claude', 'skills'));
    }
    if (!name.trim()) {
      return;
    }
    try {
      for (const skillsRoot of roots) {
        const activePath = path.join(skillsRoot, name);
        const vaultPath = path.join(skillsRoot, CLAUDE_DISABLED_VAULT, name);
        for (const p of [activePath, vaultPath]) {
          if (fs.existsSync(p)) {
            fs.rmSync(p, { recursive: true, force: true });
            this._log(`[SkillManagement] Purged Claude skill: ${p}`);
          }
        }
      }
      vscode.window.showInformationMessage(`已永久删除磁盘上的技能目录: ${name}`);
      await this._postMessage({ type: 'claudeCodeSkillDeleted', payload: { name } });
      await this._loadClaudeCodeSkills();
    } catch (error: any) {
      await this._postMessage({ type: 'error', payload: `Failed to purge skill: ${error.message}` });
    }
  }

  private _readLocalSkillMarkdown(skillDir: string): string | null {
    if (!canReadSkillDir(skillDir, this._extensionUri)) {
      return null;
    }
    const mdPath = skillMdPathInDir(skillDir);
    if (!mdPath) {
      return '';
    }
    const stat = fs.statSync(mdPath);
    const max = 512 * 1024;
    if (stat.size > max) {
      return null;
    }
    const raw = fs.readFileSync(mdPath, 'utf-8');
    const body = markdownBodyForPreview(raw);
    if (body.length > 0) {
      return body;
    }
    return raw.replace(/^\uFEFF/, '').trim().length > 0 ? raw : '';
  }

  private async _fetchAgentSkillDetail(skill: AgentSkill): Promise<void> {
    const skillId = skill.skill_id?.trim();
    if (skillId) {
      try {
        const r = await this._apiClient.getAgentSkillInfo(skillId);
        if (r.success) {
          await this._postMessage({
            type: 'agentSkillDetailLoaded',
            payload: {
              success: true,
              skill_id: r.skill_id,
              name: r.name,
              description: r.description,
              source: r.source,
              path: r.path,
              script: r.script,
              skill_md: r.skill_md,
            },
          });
          return;
        }
      } catch (error: any) {
        this._log(
          `[SkillManagement] Skill detail API failed for ${skillId}: ${error?.message || String(error)}`
        );
      }
    }

    const localMd = this._readLocalSkillMarkdown(skill.path);
    await this._postMessage({
      type: 'agentSkillDetailLoaded',
      payload: {
        success: true,
        skill_id: skillId,
        name: skill.name,
        description: skill.description,
        source: skill.source,
        path: skill.path,
        script: skill.script,
        skill_md: localMd ?? '',
      },
    });
  }

  private async _fetchLocalSkillMarkdown(skillDir: string): Promise<void> {
    if (!canReadSkillDir(skillDir, this._extensionUri)) {
      await this._postMessage({
        type: 'skillDetailError',
        payload: { key: `path:${skillDir}`, error: 'Path not allowed' }
      });
      return;
    }
    const mdPath = skillMdPathInDir(skillDir);
    if (!mdPath) {
      await this._postMessage({
        type: 'localSkillMarkdownLoaded',
        payload: { path: skillDir, content: '' }
      });
      return;
    }
    const stat = fs.statSync(mdPath);
    const max = 512 * 1024;
    if (stat.size > max) {
      await this._postMessage({
        type: 'skillDetailError',
        payload: { key: `path:${skillDir}`, error: 'SKILL.md too large' }
      });
      return;
    }
    const raw = fs.readFileSync(mdPath, 'utf-8');
    const body = markdownBodyForPreview(raw);
    const content =
      body.length > 0
        ? body
        : raw.replace(/^\uFEFF/, '').trim().length > 0
          ? '__SKILL_MD_META_ONLY__'
          : '';
    await this._postMessage({ type: 'localSkillMarkdownLoaded', payload: { path: skillDir, content } });
  }

  // ============ Marketplace ============

  private _configuredGitHosts(): string[] {
    const agentRaw = vscode.workspace.getConfiguration('agentSkills').get<unknown>('skillSources');
    const claudeRaw = vscode.workspace.getConfiguration('agentSkills').get<unknown>('claudeSkillSources');
    const agentSources = normalizeSkillSources(Array.isArray(agentRaw) ? agentRaw : []);
    const claudeSources = normalizeSkillSources(Array.isArray(claudeRaw) ? claudeRaw : []);
    const hosts = new Set<string>();
    for (const source of [...agentSources, ...claudeSources]) {
      if (source.baseUrl && !isAllowedSkillSourceBaseUrl(source.baseUrl)) {
        continue;
      }
      const fromBase = hostFromMaybeUrl(source.baseUrl);
      if (fromBase) {
        hosts.add(fromBase);
      }
      try {
        const fromRepo = hostFromMaybeUrl(getPlatformAdapter(source.platform).getRepoUrl(source));
        if (fromRepo) {
          hosts.add(fromRepo);
        }
      } catch {
        // ignore malformed source entries
      }
    }
    return [...hosts];
  }

  private async _loadMarketplaceSkills(): Promise<void> {
    const agentRaw = vscode.workspace.getConfiguration('agentSkills').get<unknown>('skillSources');
    const claudeRaw = vscode.workspace.getConfiguration('agentSkills').get<unknown>('claudeSkillSources');

    // 如果配置为空或非数组，使用默认值
    const agentSources = normalizeSkillSources(
      Array.isArray(agentRaw) && agentRaw.length > 0 ? agentRaw : DEFAULT_AGENT_SKILL_SOURCES
    );
    const claudeSources = normalizeSkillSources(
      Array.isArray(claudeRaw) && claudeRaw.length > 0 ? claudeRaw : DEFAULT_CLAUDE_SKILL_SOURCES
    );

    const loadOneChannel = async (
      sources: SkillSource[],
      channel: 'agent' | 'claude',
      installTarget: 'agent' | 'claudeCode'
    ): Promise<{ skills: MarketplaceSkill[]; errors: MarketplaceLoadError[] }> => {
      const errors: MarketplaceLoadError[] = [];
      const remote: MarketplaceSkill[] = [];

      if (sources.length === 0) {
        errors.push({ code: 'NO_SKILL_SOURCES', channel });
        return { skills: [], errors };
      }

      for (const source of sources) {
        const label = `${source.owner}/${source.repo} (${source.platform})`;
        if (source.baseUrl && !isAllowedSkillSourceBaseUrl(source.baseUrl)) {
          errors.push({
            code: 'GITHUB_SOURCE_FAILED',
            source: label,
            message: `Disallowed baseUrl for ${label}`,
          });
          continue;
        }
        try {
          const skills = await this._fetchSkillsFromSource(source, installTarget);
          remote.push(...skills);
        } catch (error: any) {
          const msg = error?.message || String(error);
          this._log(`[SkillManagement] Marketplace source ${label}: ${msg}`);
          if (isNetworkOrTimeoutError(error)) {
            errors.push({ code: 'NETWORK', message: `${label}: ${msg}` });
          } else {
            errors.push({ code: 'GITHUB_SOURCE_FAILED', source: label, message: msg });
          }
        }
      }

      return { skills: dedupeMarketplaceSkills(remote), errors };
    };

    const [agentPayload, claudePayload] = await Promise.all([
      loadOneChannel(agentSources, 'agent', 'agent'),
      loadOneChannel(claudeSources, 'claude', 'claudeCode'),
    ]);

    await this._postMessage({
      type: 'marketplaceSkillsLoaded',
      payload: { agent: agentPayload, claude: claudePayload },
    });
  }

  private async _fetchSkillsFromSource(
    source: SkillSource,
    installTarget: 'agent' | 'claudeCode'
  ): Promise<MarketplaceSkill[]> {
    const adapter = getPlatformAdapter(source.platform);

    this._log(
      `[SkillMarketplace] Fetching skills from ${source.platform}: ${source.owner}/${source.repo}`
    );

    const contents = await adapter.fetchRepoContents(source);
    const dirs = contents.filter((item) => item.type === 'dir');

    const skills: MarketplaceSkill[] = [];
    const concurrency = 6;
    for (let i = 0; i < dirs.length; i += concurrency) {
      const batch = dirs.slice(i, i + concurrency);
      const batchResults = await Promise.all(
        batch.map((item) =>
          this._fetchSkillInfoFromAdapter(source, item.path, item.name, installTarget, adapter)
        )
      );
      for (const skillInfo of batchResults) {
        if (skillInfo) {
          skills.push(skillInfo);
        }
      }
    }

    return skills;
  }

  private async _fetchSkillInfoFromAdapter(
    source: SkillSource,
    skillPath: string,
    skillName: string,
    installTarget: 'agent' | 'claudeCode',
    adapter: ReturnType<typeof getPlatformAdapter>
  ): Promise<MarketplaceSkill | null> {
    try {
      const content = await adapter.fetchFileContent(source, `${skillPath}/SKILL.md`);
      const frontmatter = parseFrontmatter(content);

      const catInfo = CATEGORY_MAP[skillName] || { id: 'other', name: 'Other', nameZh: '其他' };

      // 获取本地已安装版本和内容
      const { version: installedVersion, content: localContent } = this._getLocalSkillInfo(skillName, installTarget);

      // 比较版本，检测是否有更新
      const remoteVersion = frontmatter.version || '1.0.0';
      let updateAvailable = false;

      if (installedVersion) {
        // 版本号比较
        const versionDiff = this._compareVersions(remoteVersion, installedVersion);
        if (versionDiff > 0) {
          updateAvailable = true;
        } else if (versionDiff === 0 && localContent) {
          // 版本号相同，比较内容哈希检测内容变化
          const localHash = this._hashContent(localContent);
          const remoteHash = this._hashContent(content);
          updateAvailable = localHash !== remoteHash;
        }
      }

      return {
        id: skillName,
        name: frontmatter.name || formatSkillName(skillName),
        description:
          typeof frontmatter.description === 'string' && frontmatter.description.trim()
            ? frontmatter.description
            : '',
        descriptionZh:
          typeof frontmatter.descriptionZh === 'string' && frontmatter.descriptionZh.trim()
            ? frontmatter.descriptionZh
            : undefined,
        category: catInfo.id,
        author: typeof frontmatter.author === 'string' && frontmatter.author.trim() ? frontmatter.author : source.owner,
        repo: adapter.getRepoUrl(source),
        branch: source.branch,
        path: skillPath,
        tags: Array.isArray(frontmatter.tags) ? frontmatter.tags : [skillName],
        compatibility: installTarget === 'claudeCode' ? ['claude', 'copilot', 'cursor'] : ['agent'],
        version: remoteVersion,
        installTarget,
        // 新增字段
        installedVersion,
        updateAvailable,
        skillMdContent: content,  // 缓存 SKILL.md 内容用于预览
      };
    } catch (error: any) {
      this._log(`[SkillManagement] Skip ${skillName}: ${error.message}`);
      return null;
    }
  }

  /**
   * 获取本地已安装技能的版本和内容
   */
  private _getLocalSkillInfo(skillId: string, installTarget: 'agent' | 'claudeCode'): { version?: string; content?: string } {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      return {};
    }

    let skillDir: string;
    if (installTarget === 'agent') {
      skillDir = path.join(workspaceFolder.uri.fsPath, 'custom', 'skills', skillId);
    } else {
      skillDir = path.join(workspaceFolder.uri.fsPath, '.claude', 'skills', skillId);
    }

    const skillMdPath = path.join(skillDir, 'SKILL.md');
    if (!fs.existsSync(skillMdPath)) {
      return {};
    }

    try {
      const content = fs.readFileSync(skillMdPath, 'utf-8');
      const frontmatter = parseFrontmatter(content);
      return { version: frontmatter.version, content };
    } catch {
      return {};
    }
  }

  /**
   * 计算内容的简单哈希（用于检测内容变化）
   */
  private _hashContent(content: string): string {
    // 使用简单的字符串哈希算法
    let hash = 0;
    for (let i = 0; i < content.length; i++) {
      const char = content.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // Convert to 32bit integer
    }
    return hash.toString(16);
  }

  /**
   * 比较版本号
   * @returns >0 如果 v1 > v2, <0 如果 v1 < v2, 0 如果相等
   */
  private _compareVersions(v1: string, v2: string): number {
    const parts1 = v1.split('.').map(p => parseInt(p, 10) || 0);
    const parts2 = v2.split('.').map(p => parseInt(p, 10) || 0);

    const maxLen = Math.max(parts1.length, parts2.length);
    for (let i = 0; i < maxLen; i++) {
      const p1 = parts1[i] || 0;
      const p2 = parts2[i] || 0;
      if (p1 !== p2) {
        return p1 - p2;
      }
    }
    return 0;
  }



  /**
   * 统一的技能安装逻辑
   */
  private async _installSkill(
    skill: MarketplaceSkill,
    installTarget: 'agent' | 'claudeCode'
  ): Promise<void> {
    const skillTypeLabel = installTarget === 'agent' ? 'Agent Skill' : 'Claude Code Skill';
    let tempDir: string | undefined;
    try {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        throw new Error('Open a workspace folder before installing skills.');
      }

      if (!isValidSkillId(skill.id)) {
        throw new Error(`Invalid skill id: ${skill.id}`);
      }
      const skillRelPath = (skill.path || '.').trim() || '.';
      if (!isSafeSkillRelativePath(skillRelPath)) {
        throw new Error(`Invalid skill path: ${skill.path}`);
      }

      await this._postMessage({ type: 'installProgress', payload: { skillId: skill.id, status: 'downloading' } });

      const skillsRoot = installTarget === 'agent'
        ? path.join(workspaceFolder.uri.fsPath, 'custom', 'skills')
        : path.join(workspaceFolder.uri.fsPath, '.claude', 'skills');
      const targetDir = path.join(skillsRoot, skill.id);
      if (!isUnderDir(path.resolve(targetDir), path.resolve(skillsRoot))) {
        throw new Error(`Install path escapes skills directory: ${skill.id}`);
      }

      const managedNames = this.getExtensionManagedSkillNames();
      const clash = managedNames.has(skill.id)
        ? skill.id
        : (skill.id.startsWith('agentsociety-') ? skill.id : null);
      if (clash) {
        // F11(2026-11-06):守卫从「agentsociety- 前缀」扩为「扩展 skills/
        // 目录实际存在的技能名」——office 技能(pdf/docx/xlsx/pptx)平铺
        // 同步进 .claude/skills,市场同名安装即影子替换扩展管理的副本。
        throw new Error(`Skill "${skill.id}" clashes with extension-managed skill "${clash}"; do not overwrite from marketplace.`);
      }

      const branch = skill.branch || 'main';
      if (!isValidGitBranch(branch)) {
        throw new Error(`Invalid branch name: ${branch}`);
      }
      if (!isValidGitRepoUrl(skill.repo, this._configuredGitHosts())) {
        throw new Error(`Invalid or disallowed repository URL: ${skill.repo}`);
      }

      if (fs.existsSync(targetDir)) {
        fs.rmSync(targetDir, { recursive: true, force: true });
      }
      fs.mkdirSync(skillsRoot, { recursive: true });

      await this._postMessage({ type: 'installProgress', payload: { skillId: skill.id, status: 'installing' } });

      tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-install-'));
      const cloneResult = spawnSync('git', ['clone', '--depth', '1', '--branch', branch, skill.repo, tempDir], {
        encoding: 'utf-8',
        timeout: 120000
      });
      if (cloneResult.status !== 0) {
        throw new Error(`git clone failed: ${cloneResult.stderr || 'unknown error'}`);
      }

      const sourcePath = skillRelPath === '.' || skillRelPath === ''
        ? tempDir
        : path.join(tempDir, skillRelPath);
      if (!isPathSafe(sourcePath, tempDir)) {
        throw new Error(`Skill path escapes clone directory: ${skill.path}`);
      }
      if (fs.existsSync(sourcePath) && skillRelPath !== '.' && skillRelPath !== '') {
        fs.cpSync(sourcePath, targetDir, { recursive: true });
      } else if (skillRelPath === '.' || skillRelPath === '' || skillRelPath === skill.id) {
        fs.mkdirSync(targetDir, { recursive: true });
        for (const entry of fs.readdirSync(tempDir, { withFileTypes: true })) {
          if (entry.name === '.git') {
            continue;
          }
          fs.cpSync(path.join(tempDir, entry.name), path.join(targetDir, entry.name), { recursive: true });
        }
      } else {
        throw new Error(`Skill path not found: ${sourcePath}`);
      }

      await this._postMessage({
        type: 'installComplete',
        payload: { skillId: skill.id, name: skill.name, skillType: installTarget }
      });
      if (installTarget === 'agent') {
        await this._scanAgentSkills({ quiet: true });
      } else {
        await this._loadClaudeCodeSkills();
      }
      await this._loadMarketplaceSkills();
      this._log(`[SkillManagement] Successfully installed ${skillTypeLabel}: ${skill.name}`);
    } catch (error: any) {
      const message = error?.message || String(error);
      this._log(`[SkillManagement] Failed to install ${skill.name}: ${message}`);
      await this._postMessage({ type: 'installFailed', payload: { skillId: skill.id, error: message } });
    } finally {
      if (tempDir && fs.existsSync(tempDir)) {
        fs.rmSync(tempDir, { recursive: true, force: true });
      }
    }
  }

  private async _installAgentSkill(skill: MarketplaceSkill): Promise<void> {
    await this._installSkill(skill, 'agent');
  }

  private async _installClaudeCodeSkill(skill: MarketplaceSkill): Promise<void> {
    await this._installSkill(skill, 'claudeCode');
  }

  private async _importAgentSkill(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const uris = await vscode.window.showOpenDialog({
      canSelectFolders: true,
      canSelectFiles: false,
      canSelectMany: false,
      openLabel: 'Import Skill Directory'
    });
    if (!uris?.[0]) {
      return;
    }
    try {
      const response = await this._apiClient.importAgentSkill(uris[0].fsPath, workspaceFolder?.uri.fsPath);
      if (response.success) {
        vscode.window.showInformationMessage(response.message);
        await this._postMessage({ type: 'agentSkillImported', payload: { name: path.basename(uris[0].fsPath) } });
        await this._scanAgentSkills({ quiet: true });
      }
    } catch (error: any) {
      this._log(`[SkillManagement] Failed to import skill: ${error.message}`);
      await this._postMessage({ type: 'error', payload: error.message || String(error) });
    }
  }

  private async _importClaudeCodeSkill(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage('请先打开工作区文件夹，再导入 Claude Code 技能。');
      return;
    }
    const uris = await vscode.window.showOpenDialog({
      canSelectFolders: true,
      canSelectFiles: false,
      canSelectMany: false,
      openLabel: 'Import Claude Code Skill Directory'
    });
    if (!uris?.[0]) {
      return;
    }
    const src = uris[0].fsPath;
    const dirName = path.basename(src);
    const skillMd = path.join(src, 'SKILL.md');
    if (!fs.existsSync(skillMd)) {
      vscode.window.showErrorMessage('所选目录必须包含 SKILL.md');
      return;
    }
    const destRoot = path.join(workspaceFolder.uri.fsPath, '.claude', 'skills');
    const dest = path.join(destRoot, dirName);
    try {
      fs.mkdirSync(destRoot, { recursive: true });
      if (fs.existsSync(dest)) {
        vscode.window.showErrorMessage(`目标已存在同名技能目录：${dirName}`);
        return;
      }
      fs.cpSync(src, dest, { recursive: true });
      vscode.window.showInformationMessage(`已导入 Claude Code 技能：${dirName}`);
      await this._postMessage({ type: 'claudeCodeSkillImported', payload: { name: dirName } });
      await this._loadClaudeCodeSkills();
    } catch (error: any) {
      this._log(`[SkillManagement] Claude import failed: ${error.message}`);
      await this._postMessage({ type: 'error', payload: error.message || String(error) });
    }
  }

  /** 获取市场源配置 */
  private async _getSkillSources(target: 'agent' | 'claudeCode'): Promise<void> {
    const configKey = target === 'agent' ? 'skillSources' : 'claudeSkillSources';
    const raw = vscode.workspace.getConfiguration('agentSkills').get<unknown[]>(configKey);

    // 如果配置为空或非数组，使用默认值
    const defaultSources = target === 'agent' ? DEFAULT_AGENT_SKILL_SOURCES : DEFAULT_CLAUDE_SKILL_SOURCES;
    const sources = normalizeSkillSources(
      Array.isArray(raw) && raw.length > 0 ? raw : defaultSources
    );

    await this._postMessage({
      type: 'skillSourcesLoaded',
      payload: { target, sources },
    });
  }

  /** 保存市场源配置 */
  private async _saveSkillSources(
    target: 'agent' | 'claudeCode',
    sources: Array<{
      owner: string;
      repo: string;
      branch?: string;
      skillsPath?: string;
      platform?: string;
      baseUrl?: string;
    }>
  ): Promise<void> {
    const configKey = target === 'agent' ? 'skillSources' : 'claudeSkillSources';
    try {
      // 验证并规范化源配置
      const normalized: any[] = [];
      for (const s of sources) {
        if (!s.owner?.trim() || !s.repo?.trim()) {
          continue;
        }
        const item: any = {
          owner: s.owner.trim(),
          repo: s.repo.trim(),
          branch: s.branch?.trim() || 'main',
        };
        if (s.skillsPath?.trim()) {
          const skillsPath = s.skillsPath.trim().replace(/^\/+|\/+$/g, '');
          if (!isSafeSkillRelativePath(skillsPath)) {
            throw new Error(`Invalid skillsPath: ${s.skillsPath}`);
          }
          item.skillsPath = skillsPath;
        }
        if (s.platform && s.platform !== 'github') {
          item.platform = s.platform;
        }
        if (s.baseUrl?.trim()) {
          const baseUrl = s.baseUrl.trim().replace(/\/+$/, '');
          if (!isAllowedSkillSourceBaseUrl(baseUrl)) {
            throw new Error(`Invalid or disallowed baseUrl: ${s.baseUrl}`);
          }
          item.baseUrl = baseUrl;
        }
        if (!isValidGitBranch(item.branch)) {
          throw new Error(`Invalid branch: ${item.branch}`);
        }
        normalized.push(item);
      }
      await vscode.workspace.getConfiguration('agentSkills').update(
        configKey,
        normalized,
        vscode.ConfigurationTarget.Global
      );
      await this._postMessage({
        type: 'skillSourcesSaved',
        payload: { target, sources: normalized },
      });
      // 刷新市场列表
      await this._loadMarketplaceSkills();
    } catch (error: any) {
      this._log(`[SkillManagement] Save sources failed: ${error.message}`);
      await this._postMessage({
        type: 'skillSourcesError',
        payload: { target, error: error.message || String(error) },
      });
    }
  }

  private async _getGithubToken(): Promise<void> {
    const token = vscode.workspace.getConfiguration('agentSkills').get<string>('githubToken', '');
    await this._postMessage({
      type: 'githubTokenLoaded',
      payload: { token },
    });
  }

  private async _saveGithubToken(token: string): Promise<void> {
    try {
      await vscode.workspace.getConfiguration('agentSkills').update(
        'githubToken',
        token,
        vscode.ConfigurationTarget.Global
      );
      await this._postMessage({
        type: 'githubTokenSaved',
        payload: { success: true },
      });
    } catch (error: any) {
      this._log(`[SkillManagement] Save GitHub token failed: ${error.message}`);
    }
  }

  private _parseGitNoIndexDiff(
    diffText: string,
    localRoot: string,
    remoteRoot: string,
    _skill: MarketplaceSkill
  ): {
    filesAdded: string[];
    filesDeleted: string[];
    filesModified: string[];
    fileDiffs: Array<{
      path: string;
      status: 'added' | 'deleted' | 'modified';
      hunks: Array<{
        oldStart: number;
        oldLines: number;
        newStart: number;
        newLines: number;
        lines: string[];
      }>;
    }>;
  } {
    const filesAdded: string[] = [];
    const filesDeleted: string[] = [];
    const filesModified: string[] = [];
    const fileDiffs: Array<{
      path: string;
      status: 'added' | 'deleted' | 'modified';
      hunks: Array<{
        oldStart: number;
        oldLines: number;
        newStart: number;
        newLines: number;
        lines: string[];
      }>;
    }> = [];

    const normalizePath = (p: string): string => {
      const cleaned = p.replace(/^a\//, '').replace(/^b\//, '');
      if (cleaned.startsWith(localRoot)) {
        return cleaned.slice(localRoot.length).replace(/^\/+/, '');
      }
      if (cleaned.startsWith(remoteRoot)) {
        return cleaned.slice(remoteRoot.length).replace(/^\/+/, '');
      }
      return cleaned;
    };

    const lines = diffText.split(/\r?\n/);
    let current:
      | {
        path: string;
        status: 'added' | 'deleted' | 'modified';
        hunks: Array<{
          oldStart: number;
          oldLines: number;
          newStart: number;
          newLines: number;
          lines: string[];
        }>;
      }
      | undefined;
    let currentHunk:
      | {
        oldStart: number;
        oldLines: number;
        newStart: number;
        newLines: number;
        lines: string[];
      }
      | undefined;

    const flushHunk = () => {
      if (current && currentHunk) {
        current.hunks.push(currentHunk);
      }
      currentHunk = undefined;
    };

    const flushFile = () => {
      flushHunk();
      if (current) {
        fileDiffs.push(current);
      }
      current = undefined;
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.startsWith('diff --git ')) {
        flushFile();
        const m = /^diff --git a\/(.+?) b\/(.+)$/.exec(line);
        const rawPath = m?.[2] ?? m?.[1] ?? `file-${fileDiffs.length}`;
        current = { path: normalizePath(rawPath), status: 'modified', hunks: [] };
        continue;
      }
      if (!current) {
        continue;
      }
      if (line.startsWith('new file mode ')) {
        current.status = 'added';
        continue;
      }
      if (line.startsWith('deleted file mode ')) {
        current.status = 'deleted';
        continue;
      }
      if (line.startsWith('@@ ')) {
        flushHunk();
        const m = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(line);
        currentHunk = {
          oldStart: Number(m?.[1] ?? 0),
          oldLines: Number(m?.[2] ?? 1),
          newStart: Number(m?.[3] ?? 0),
          newLines: Number(m?.[4] ?? 1),
          lines: [],
        };
        currentHunk.lines.push(line);
        continue;
      }
      if (currentHunk) {
        if (line.startsWith('+') || line.startsWith('-') || line.startsWith(' ')) {
          currentHunk.lines.push(line);
        }
      }
    }
    flushFile();

    for (const f of fileDiffs) {
      if (f.status === 'added') {
        filesAdded.push(f.path);
      } else if (f.status === 'deleted') {
        filesDeleted.push(f.path);
      } else {
        filesModified.push(f.path);
      }
    }

    return { filesAdded, filesDeleted, filesModified, fileDiffs };
  }

  private async _getSkillUpdateDiff(skill: MarketplaceSkill): Promise<void> {
    try {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        throw new Error('No workspace folder opened');
      }

      if (!isValidSkillId(skill.id)) {
        throw new Error(`Invalid skill id: ${skill.id}`);
      }
      const skillRelPath = (skill.path || '.').trim() || '.';
      if (!isSafeSkillRelativePath(skillRelPath)) {
        throw new Error(`Invalid skill path: ${skill.path}`);
      }

      const skillsRoot = skill.installTarget === 'agent'
        ? path.join(workspaceFolder.uri.fsPath, 'custom', 'skills')
        : path.join(workspaceFolder.uri.fsPath, '.claude', 'skills');
      const localRoot = path.join(skillsRoot, skill.id);
      if (!isUnderDir(path.resolve(localRoot), path.resolve(skillsRoot))) {
        throw new Error(`Local skill path escapes skills directory: ${skill.id}`);
      }

      if (!fs.existsSync(localRoot)) {
        throw new Error(`Local skill not found: ${localRoot}`);
      }

      const branch = skill.branch || 'main';
      if (!isValidGitBranch(branch)) {
        throw new Error(`Invalid branch name: ${branch}`);
      }
      if (!isValidGitRepoUrl(skill.repo, this._configuredGitHosts())) {
        throw new Error(`Invalid or disallowed repository URL: ${skill.repo}`);
      }

      const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-diff-'));
      const cloneResult = spawnSync('git', ['clone', '--depth', '1', '--branch', branch, skill.repo, tempDir], {
        encoding: 'utf-8',
        timeout: 120000,
      });
      if (cloneResult.status !== 0) {
        fs.rmSync(tempDir, { recursive: true, force: true });
        throw new Error(`git clone failed: ${cloneResult.stderr || 'unknown error'}`);
      }

      const remoteRoot = skillRelPath === '.' || skillRelPath === ''
        ? tempDir
        : path.join(tempDir, skillRelPath);
      if (!isPathSafe(remoteRoot, tempDir) || !fs.existsSync(remoteRoot)) {
        fs.rmSync(tempDir, { recursive: true, force: true });
        throw new Error(`Skill path not found: ${remoteRoot}`);
      }

      const r = spawnSync('git', ['diff', '--no-index', '--', localRoot, remoteRoot], {
        encoding: 'utf-8',
        timeout: 120000,
      });
      const diffText = (r.stdout || '') + (r.stderr || '');

      fs.rmSync(tempDir, { recursive: true, force: true });

      const parsed = this._parseGitNoIndexDiff(diffText, localRoot, remoteRoot, skill);

      await this._postMessage({
        type: 'skillUpdateDiffLoaded',
        payload: {
          skillId: skill.id,
          skillName: skill.name,
          localVersion: skill.installedVersion || '',
          remoteVersion: skill.version || '',
          filesAdded: parsed.filesAdded,
          filesDeleted: parsed.filesDeleted,
          filesModified: parsed.filesModified,
          fileDiffs: parsed.fileDiffs,
        },
      });
    } catch (error: any) {
      await this._postMessage({
        type: 'skillUpdateDiffError',
        payload: { error: error.message || String(error), skillId: skill.id },
      });
    }
  }

  private async _confirmSkillUpdate(skill: MarketplaceSkill): Promise<void> {
    if (skill.installTarget === 'agent') {
      await this._installAgentSkill(skill);
      return;
    }
    await this._installClaudeCodeSkill(skill);
  }

  private _openSkillFolder(skillPath: string): void {
    if (fs.existsSync(skillPath)) {
      const uri = vscode.Uri.file(skillPath);
      vscode.commands.executeCommand('revealInExplorer', uri);
    }
  }

  // ============ Skill Versioning ============

  private async _loadSkillPresets(): Promise<void> {
    const wf = vscode.workspace.workspaceFolders?.[0];
    if (!wf) {
      await this._postMessage({ type: 'skillPresetsLoaded', payload: { active: '', presets: [] } });
      return;
    }
    const versionManager = this._projectStructureProvider.getSkillVersionManager();
    const file = versionManager.ensureDefaultPresetExists(wf.uri.fsPath);
    const presets: SkillPreset[] = Object.entries(file.presets).map(([name, mapping]) => ({
      name,
      active: name === file.active,
      mapping: mapping as Record<string, SkillVersionRef>,
    }));
    await this._postMessage({
      type: 'skillPresetsLoaded',
      payload: { active: file.active, presets },
    });
  }

  private async _applySkillPreset(name: string): Promise<void> {
    const wf = vscode.workspace.workspaceFolders?.[0];
    if (!wf) {
      vscode.window.showErrorMessage('请先打开工作区文件夹');
      return;
    }
    if (!name.trim()) {
      return;
    }
    const versionManager = this._projectStructureProvider.getSkillVersionManager();
    const result = versionManager.applyPreset(wf.uri.fsPath, name);
    const summary =
      `已切换到 preset「${result.preset}」：` +
      `应用 ${result.applied.length} 个，` +
      `回退 ${result.fallbacks.length} 个，` +
      `错误 ${result.errors.length} 个`;
    if (result.errors.length === 0) {
      vscode.window.showInformationMessage(summary);
    } else {
      vscode.window.showWarningMessage(summary);
    }
    await this._postMessage({ type: 'skillPresetApplied', payload: { name, summary } });
    await this._loadBuiltinSkills();
    await this._loadClaudeCodeSkills();
    await this._loadSkillPresets();
  }

  private async _createSkillSnapshot(skill: string, tag: string): Promise<void> {
    const wf = vscode.workspace.workspaceFolders?.[0];
    if (!wf) {
      vscode.window.showErrorMessage('请先打开工作区文件夹');
      return;
    }
    const versionManager = this._projectStructureProvider.getSkillVersionManager();
    const result = versionManager.createSnapshot(wf.uri.fsPath, skill, tag);
    if (result.success) {
      vscode.window.showInformationMessage(result.message);
      await this._postMessage({
        type: 'skillSnapshotCreated',
        payload: { skill, tag, path: result.path },
      });
      await this._loadBuiltinSkills();
    } else {
      vscode.window.showErrorMessage(result.message);
    }
  }

  private async _savePreset(name: string, mapping: Record<string, SkillVersionRef>): Promise<void> {
    const wf = vscode.workspace.workspaceFolders?.[0];
    if (!wf) {
      vscode.window.showErrorMessage('请先打开工作区文件夹');
      return;
    }
    const trimmed = name.trim();
    if (!trimmed) {
      vscode.window.showErrorMessage('preset 名称为空');
      return;
    }
    const versionManager = this._projectStructureProvider.getSkillVersionManager();
    const file = versionManager.ensureDefaultPresetExists(wf.uri.fsPath);
    file.presets[trimmed] = mapping;
    const r = versionManager.savePresets(wf.uri.fsPath, file);
    if (!r.success) {
      vscode.window.showErrorMessage(r.message);
      return;
    }
    vscode.window.showInformationMessage(`已保存 preset「${trimmed}」`);
    await this._loadSkillPresets();
  }

  private async _deletePreset(name: string): Promise<void> {
    const wf = vscode.workspace.workspaceFolders?.[0];
    if (!wf) {
      vscode.window.showErrorMessage('请先打开工作区文件夹');
      return;
    }
    if (name === 'default') {
      vscode.window.showErrorMessage('不能删除 default preset');
      return;
    }
    const versionManager = this._projectStructureProvider.getSkillVersionManager();
    const file = versionManager.ensureDefaultPresetExists(wf.uri.fsPath);
    if (!file.presets[name]) {
      return;
    }
    delete file.presets[name];
    if (file.active === name) {
      file.active = 'default';
    }
    const r = versionManager.savePresets(wf.uri.fsPath, file);
    if (!r.success) {
      vscode.window.showErrorMessage(r.message);
      return;
    }
    vscode.window.showInformationMessage(`已删除 preset「${name}」`);
    await this._loadSkillPresets();
    await this._loadBuiltinSkills();
  }

  private async _loadMcpServers(): Promise<void> {
    const servers = this._mcpManager.listServers();
    await this._postMessage({
      type: 'mcpServersLoaded',
      payload: {
        servers,
        presets: MCP_SERVER_PRESETS.map((preset) => ({
          presetId: preset.presetId,
          name: preset.name,
          descriptionKey: preset.descriptionKey,
          transport: preset.transport,
        })),
      },
    });
  }

  private async _saveMcpServer(input: McpServerInput, requestId?: string): Promise<void> {
    try {
      const servers = await this._mcpManager.saveServer(input);
      await this._postMessage({ type: 'mcpServersLoaded', payload: servers });
      await this._postMessage({ type: 'mcpServerSaved', payload: { requestId } });
      vscode.window.showInformationMessage(`MCP server「${input.name}」已保存`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await this._postMessage({ type: 'mcpError', payload: { error: message, requestId } });
    }
  }

  private async _removeMcpServer(id: string): Promise<void> {
    try {
      const servers = await this._mcpManager.removeServer(id);
      await this._postMessage({ type: 'mcpServersLoaded', payload: servers });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await this._postMessage({ type: 'mcpError', payload: { error: message } });
    }
  }

  private async _toggleMcpServerApp(id: string, app: 'claude' | 'codex', enabled: boolean): Promise<void> {
    try {
      const servers = await this._mcpManager.toggleServerApp(id, app, enabled);
      await this._postMessage({ type: 'mcpServersLoaded', payload: servers });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await this._postMessage({ type: 'mcpError', payload: { error: message } });
    }
  }

  private async _listMcpRegistry(payload: { source?: string; search?: string; cursor?: string; requestId?: number }): Promise<void> {
    const request = ++this._registryRequest;
    try {
      const source = normalizeRegistrySource(payload.source ?? DEFAULT_MCP_REGISTRY);
      const page = await fetchRegistryPage({ source, search: payload.search, cursor: payload.cursor,
        proxy: registryProxy(source, vscode.workspace.getConfiguration('http').get<string>('proxy')) });
      if (request !== this._registryRequest) { return; }
      await this._context.globalState.update('agentsociety.mcpRegistrySource', source);
      await this._postMessage({ type: 'mcpRegistryPage', payload: { ...page, source, requestId: payload.requestId } });
    } catch (error) {
      if (request !== this._registryRequest) { return; }
      const code = error instanceof Error && /^(invalid_registry_|registry_)/.test(error.message) ? error.message : 'registry_network_error';
      await this._postMessage({ type: 'mcpRegistryError', payload: { error: code, requestId: payload.requestId } });
    }
  }

  private async _previewMcpImport(payload: { source?: McpImportSource; text?: string; requestId?: number }): Promise<void> {
    try {
      const source = payload.source ?? 'paste';
      if (!['claude', 'codex', 'file', 'paste'].includes(source)) { throw new Error('invalid_mcp_import'); }
      let text = payload.text;
      if (source === 'file') {
        const uris = await vscode.window.showOpenDialog({ canSelectMany: false, filters: { 'MCP configuration': ['json', 'toml'] } });
        if (!uris?.[0]) { await this._postMessage({ type: 'mcpImportCancelled', payload: { requestId: payload.requestId } }); return; }
        text = fs.readFileSync(uris[0].fsPath, 'utf-8');
      }
      const preview = this._mcpManager.previewImport(source, text);
      const items = preview.items.map((item) => ({ ...item, server: item.server ? {
        ...item.server, args: item.server.args?.map(() => '••••'),
        url: item.server.url ? new URL(item.server.url).origin + new URL(item.server.url).pathname : undefined,
        env: item.server.env ? Object.fromEntries(Object.keys(item.server.env).map((key) => [key, '••••'])) : undefined,
        httpHeaders: item.server.httpHeaders ? Object.fromEntries(Object.keys(item.server.httpHeaders).map((key) => [key, '••••'])) : undefined,
        claudeOptions: undefined, codexOptions: undefined,
      } : undefined }));
      await this._postMessage({ type: 'mcpImportPreview', payload: { ...preview, items, requestId: payload.requestId } });
    } catch {
      await this._postMessage({ type: 'mcpImportError', payload: { error: 'invalid_mcp_import', requestId: payload.requestId } });
    }
  }

  private async _applyMcpImport(payload: { token?: string; selected?: string[]; claude?: boolean; codex?: boolean; requestId?: number }): Promise<void> {
    try {
      const result = await this._mcpManager.applyImport(payload.token ?? '', payload.selected ?? [], { claude: payload.claude === true, codex: payload.codex === true });
      await this._loadMcpServers();
      await this._postMessage({ type: 'mcpImportApplied', payload: { ...result, requestId: payload.requestId } });
    } catch (error) {
      const code = error instanceof Error && ['mcp_import_changed', 'sse_claude_only', 'unsupported_codex_layout', 'invalid_claude_config'].includes(error.message) ? error.message : 'mcp_import_failed';
      await this._postMessage({ type: 'mcpImportError', payload: { error: code, requestId: payload.requestId } });
    }
  }

  private async _syncMcpServers(): Promise<void> {
    try {
      await this._mcpManager.syncLiveConfigs();
      const servers = this._mcpManager.listServers();
      await this._postMessage({ type: 'mcpServersLoaded', payload: servers });
      vscode.window.showInformationMessage('MCP 配置已同步到 Claude / Codex');
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await this._postMessage({ type: 'mcpError', payload: { error: message } });
    }
  }

  private async _probeMcpServer(id: string): Promise<void> {
    const server = this._mcpManager.listServers().find((s) => s.id === id);
    if (!server || server.transport !== 'http' || !server.url) {
      return;
    }
    const headers = { ...server.httpHeaders };
    if (server.bearerTokenEnvVar && !Object.keys(headers).some((name) => name.toLowerCase() === 'authorization')) {
      const token = process.env[server.bearerTokenEnvVar];
      if (!token) {
        await this._postMessage({ type: 'mcpProbeResult', payload: { id, result: { ok: false, status: 0, tools: [], error: `Missing environment variable: ${server.bearerTokenEnvVar}` } } });
        return;
      }
      headers.Authorization = `Bearer ${token}`;
    }
    const connection = mcpConnectionKey(server);
    const result = await probeHttpMcpServer(server.url, headers);
    const current = this._mcpManager.listServers().find((row) => row.id === id);
    const response = current && mcpConnectionKey(current) === connection ? result
      : { ok: false, status: 0, tools: [], error: 'mcp_configuration_changed' };
    await this._postMessage({ type: 'mcpProbeResult', payload: { id, result: response } });
  }

  private async _openLiteratureMcpConfig(): Promise<void> {
    await vscode.commands.executeCommand('aiSocialScientist.openConfigPage');
    ConfigPageViewProvider.currentPanel?.navigateToAdvancedTab('literature');
  }

  private async _addMcpPreset(presetId: string): Promise<void> {
    const preset = MCP_SERVER_PRESETS.find((item) => item.presetId === presetId);
    if (!preset) {
      return;
    }
    const { presetId: _id, descriptionKey: _desc, ...record } = preset;
    await this._saveMcpServer({
      ...record,
      enabledClaude: true,
      enabledCodex: preset.presetId === 'context7',
    });
  }

  private async _postMessage(message: { type: string; payload?: any }): Promise<void> {
    await this._webview.postMessage(message);
  }

  private _getHtmlForWebview(webview: vscode.Webview): string {
    const scriptPath = path.join(this._extensionUri.fsPath, 'out', 'webview', 'skillMarketplace.js');
    const scriptUri = webview.asWebviewUri(vscode.Uri.file(scriptPath));
    const lang = getCurrentLanguageCode();

    // F15(2026-11-06):补 CSP(configPage/replay 等 5 个 provider 均有,
    // 本面板是唯一缺口)。React 应用:script-src 限 webview 资源 + nonce,
    // style-src 加 'unsafe-inline'(内联 style 块)。
    const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16)))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');

    return `<!DOCTYPE html>
<html lang="${lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} https: data:; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource} 'nonce-${nonce}'; font-src ${webview.cspSource}; connect-src ${webview.cspSource};">
  <title>${localize('skillMarketplace.title')}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { height: 100vh; overflow: auto; }
    #root { min-height: 100vh; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}">window.__AS_LANG__=${JSON.stringify(lang).replace(/</g, '\\u003c')};</script>
  <script src="${scriptUri}"></script>
</body>
</html>`;
  }
}
