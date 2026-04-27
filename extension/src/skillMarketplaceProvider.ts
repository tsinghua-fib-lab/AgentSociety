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
  MarketplaceLoadError,
  SkillFrontmatter,
} from './webview/skillMarketplace/types';
import { ApiClient } from './apiClient';
import type { ProjectStructureProvider } from './projectStructureProvider';
import { getPlatformAdapter, type SkillSource } from './platforms';
import {
  CLAUDE_DISABLED_VAULT,
  CATEGORY_MAP,
  GITHUB_API_TIMEOUT_MS,
  GITHUB_RAW_TIMEOUT_MS,
  DEFAULT_CLAUDE_SKILL_SOURCES,
  DEFAULT_AGENT_SKILL_SOURCES,
  skillMdPathInDir,
  markdownBodyForPreview,
  parseFrontmatter,
  formatSkillName,
  normalizeSkillSources,
  isNetworkOrTimeoutError,
  dedupeMarketplaceSkills,
  type GitHubContentItem,
} from './skillMarketplace/utils';
import {
  isValidGitBranch,
  isValidGitRepoUrl,
  canReadSkillDir,
} from './skillMarketplace/security';

const PANEL_VIEW_TYPE = 'aiSocialScientist.skillMarketplace';

export class SkillMarketplacePanel {
  public static current: SkillMarketplacePanel | undefined;

  private readonly _extensionUri: vscode.Uri;
  private readonly _outputChannel: vscode.OutputChannel;
  private readonly _panel: vscode.WebviewPanel;
  private readonly _webview: vscode.Webview;
  private readonly _apiClient: ApiClient;
  private readonly _projectStructureProvider: ProjectStructureProvider;

  private constructor(
    extensionUri: vscode.Uri,
    outputChannel: vscode.OutputChannel,
    panel: vscode.WebviewPanel,
    apiClient: ApiClient,
    projectStructureProvider: ProjectStructureProvider
  ) {
    this._extensionUri = extensionUri;
    this._outputChannel = outputChannel;
    this._panel = panel;
    this._webview = panel.webview;
    this._apiClient = apiClient;
    this._projectStructureProvider = projectStructureProvider;

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
            await this._loadAgentSkills();
            await this._loadClaudeCodeSkills();
            await this._loadBuiltinSkills();
            await this._loadMarketplaceSkills();
            break;

          // Agent Skills
          case 'listAgentSkills':
            await this._loadAgentSkills();
            break;
          case 'enableAgentSkill':
            await this._enableAgentSkill(data.payload.name);
            break;
          case 'disableAgentSkill':
            await this._disableAgentSkill(data.payload.name);
            break;
          case 'reloadAgentSkill':
            await this._reloadAgentSkill(data.payload.name);
            break;
          case 'removeAgentSkill':
            await this._archiveAgentSkill(data.payload.name);
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
              data.payload.isBuiltin
            );
            break;
          case 'openLocalSkillMarkdown':
            this._openLocalSkillMarkdown(data.payload.skillDir);
            break;
          case 'openSkillFolder':
            this._openSkillFolder(data.payload.path);
            break;
          case 'fetchAgentSkillDetail':
            await this._fetchAgentSkillDetail(data.payload.name);
            break;
          case 'fetchLocalSkillMarkdown':
            await this._fetchLocalSkillMarkdown(data.payload.skillDir);
            break;
          case 'openExternal':
            vscode.env.openExternal(vscode.Uri.parse(data.payload.url));
            break;
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
            break;
          }
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
    outputChannel: vscode.OutputChannel,
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
      'Skill Management',
      column,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [context.extensionUri]
      }
    );

    context.subscriptions.push(panel);
    SkillMarketplacePanel.current = new SkillMarketplacePanel(
      context.extensionUri,
      outputChannel,
      panel,
      apiClient,
      projectStructureProvider
    );
  }




  // ============ Agent Skills ============

  private async _loadAgentSkills(): Promise<void> {
    try {
      const response = await this._apiClient.listAgentSkills();
      if (response.success) {
        const skills: AgentSkill[] = response.skills.map(s => ({
          name: s.name,
          description: s.description,
          source: s.source,
          enabled: s.enabled,
          path: s.path,
          has_skill_md: s.has_skill_md,
          script: s.script,
          requires: s.requires
        }));
        await this._postMessage({ type: 'agentSkillsLoaded', payload: skills });
      }
    } catch (error: any) {
      this._outputChannel.appendLine(`[SkillManagement] Failed to load agent skills: ${error.message}`);
      await this._postMessage({ type: 'agentSkillsLoaded', payload: [] });
    }
  }

  private async _enableAgentSkill(name: string): Promise<void> {
    try {
      const response = await this._apiClient.enableAgentSkill(name);
      await this._postMessage({ type: 'agentSkillEnabled', payload: { message: response.message } });
      await this._loadAgentSkills();
    } catch (error: any) {
      await this._postMessage({ type: 'error', payload: `Failed to enable skill: ${error.message}` });
    }
  }

  private async _disableAgentSkill(name: string): Promise<void> {
    try {
      const response = await this._apiClient.disableAgentSkill(name);
      await this._postMessage({ type: 'agentSkillDisabled', payload: { message: response.message } });
      await this._loadAgentSkills();
    } catch (error: any) {
      await this._postMessage({ type: 'error', payload: `Failed to disable skill: ${error.message}` });
    }
  }

  private async _reloadAgentSkill(name: string): Promise<void> {
    try {
      const response = await this._apiClient.reloadAgentSkill(name);
      await this._postMessage({ type: 'agentSkillReloaded', payload: { message: response.message } });
      await this._loadAgentSkills();
    } catch (error: any) {
      await this._postMessage({ type: 'error', payload: `Failed to reload skill: ${error.message}` });
    }
  }

  private async _archiveAgentSkill(name: string): Promise<void> {
    try {
      const response = await this._apiClient.archiveAgentSkill(name);
      vscode.window.showInformationMessage(response.message);
      await this._postMessage({ type: 'agentSkillRemoved', payload: { message: response.message } });
      await this._loadAgentSkills();
    } catch (error: any) {
      await this._postMessage({ type: 'error', payload: error.message || String(error) });
    }
  }

  private async _scanAgentSkills(): Promise<void> {
    try {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      const response = await this._apiClient.scanAgentSkills(workspaceFolder?.uri.fsPath);
      if (response.success) {
        vscode.window.showInformationMessage(response.message);
      }
      await this._loadAgentSkills();
    } catch (error: any) {
      this._outputChannel.appendLine(`[SkillManagement] Scan failed: ${error.message}`);
      await this._postMessage({ type: 'error', payload: error.message || String(error) });
    }
  }

  private async _loadBuiltinSkills(): Promise<void> {
    const skills: BuiltinSkill[] = [];
    const skillsDir = path.join(this._extensionUri.fsPath, 'skills');
    if (fs.existsSync(skillsDir)) {
      try {
        const names = fs.readdirSync(skillsDir).filter((name) => {
          const skillPath = path.join(skillsDir, name);
          return fs.statSync(skillPath).isDirectory() && skillMdPathInDir(skillPath) !== null;
        });
        for (const name of names) {
          const skillPath = path.join(skillsDir, name);
          const mdPath = skillMdPathInDir(skillPath)!;
          const content = fs.readFileSync(mdPath, 'utf-8');
          const frontmatter = parseFrontmatter(content);
          skills.push({
            name,
            path: skillPath,
            hasSkillMd: true,
            description: typeof frontmatter.description === 'string' ? frontmatter.description : undefined
          });
        }
      } catch (error: any) {
        this._outputChannel.appendLine(`[SkillManagement] Failed to load extension skills: ${error.message}`);
      }
    }
    await this._postMessage({ type: 'builtinSkillsLoaded', payload: skills });
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

  private _scanClaudeCodeSkills(dirPath: string, skills: ClaudeCodeSkill[], origin: 'workspace' | 'global'): void {
    if (!fs.existsSync(dirPath)) {
      return;
    }

    try {
      const entries = fs.readdirSync(dirPath, { withFileTypes: true });
      for (const entry of entries) {
        if (!entry.isDirectory() || entry.name.startsWith('.')) {
          continue;
        }
        const skillPath = path.join(dirPath, entry.name);
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
      this._outputChannel.appendLine(`[SkillManagement] Failed to scan ${dirPath}: ${error.message}`);
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
        if (!entry.isDirectory() || entry.name.startsWith('.')) {
          continue;
        }
        const skillPath = path.join(vault, entry.name);
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
      this._outputChannel.appendLine(`[SkillManagement] Failed to scan vault ${vault}: ${error.message}`);
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
            this._outputChannel.appendLine(`[SkillManagement] Purged Claude skill: ${p}`);
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

  private _isUnderDir(resolvedPath: string, resolvedDir: string): boolean {
    return resolvedPath === resolvedDir || resolvedPath.startsWith(resolvedDir + path.sep);
  }

  /**
   * 安全地解析路径，处理符号链接
   * 返回路径的真实绝对路径，如果路径不存在或无法访问则返回 null
   */
  private _safeResolvePath(inputPath: string): string | null {
    try {
      // 首先解析为绝对路径
      const absolutePath = path.resolve(inputPath);

      // 检查路径是否存在
      if (!fs.existsSync(absolutePath)) {
        return absolutePath; // 不存在的路径，返回解析后的路径用于后续检查
      }

      // 使用 realpath 获取真实路径（解析符号链接）
      const realPath = fs.realpathSync(absolutePath);
      return realPath;
    } catch {
      return null;
    }
  }

  /**
   * 检查路径是否在允许的目录内（安全版本，处理符号链接）
   */
  private _isPathSafe(inputPath: string, allowedDir: string): boolean {
    const resolvedInput = this._safeResolvePath(inputPath);
    const resolvedAllowed = this._safeResolvePath(allowedDir);

    if (!resolvedInput || !resolvedAllowed) {
      return false;
    }

    return this._isUnderDir(resolvedInput, resolvedAllowed);
  }


  private async _fetchAgentSkillDetail(name: string): Promise<void> {
    try {
      const r = await this._apiClient.getAgentSkillInfo(name);
      if (r.success) {
        await this._postMessage({ type: 'agentSkillDetailLoaded', payload: r });
      } else {
        await this._postMessage({
          type: 'skillDetailError',
          payload: { key: `agent:${name}`, error: 'Skill not found or no detail' }
        });
      }
    } catch (error: any) {
      await this._postMessage({
        type: 'skillDetailError',
        payload: { key: `agent:${name}`, error: error.message || String(error) }
      });
    }
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
        try {
          const skills = await this._fetchSkillsFromSource(source, installTarget);
          remote.push(...skills);
        } catch (error: any) {
          const msg = error?.message || String(error);
          this._outputChannel.appendLine(`[SkillManagement] Marketplace source ${label}: ${msg}`);
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

    this._outputChannel.appendLine(
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
      this._outputChannel.appendLine(`[SkillManagement] Skip ${skillName}: ${error.message}`);
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
    try {
      await this._postMessage({ type: 'installProgress', payload: { skillId: skill.id, status: 'downloading' } });

      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      const targetDir = installTarget === 'agent'
        ? path.join(workspaceFolder?.uri.fsPath || '', 'custom', 'skills', skill.id)
        : path.join(workspaceFolder?.uri.fsPath || '', '.claude', 'skills', skill.id);

      // 安全校验：分支名
      const branch = skill.branch || 'main';
      if (!isValidGitBranch(branch)) {
        throw new Error(`Invalid branch name: ${branch}`);
      }

      // 安全校验：仓库 URL
      if (!isValidGitRepoUrl(skill.repo)) {
        throw new Error(`Invalid or disallowed repository URL: ${skill.repo}`);
      }

      // 清理已存在的目标目录
      if (fs.existsSync(targetDir)) {
        fs.rmSync(targetDir, { recursive: true, force: true });
      }
      fs.mkdirSync(path.dirname(targetDir), { recursive: true });

      await this._postMessage({ type: 'installProgress', payload: { skillId: skill.id, status: 'installing' } });

      // 克隆仓库到临时目录
      const tempDir = path.join(process.env.TMP || '/tmp', `skill-${skill.id}-${Date.now()}`);
      spawnSync('git', ['clone', '--depth', '1', '--branch', branch, skill.repo, tempDir], {
        encoding: 'utf-8',
        timeout: 120000
      });

      // 复制技能目录
      const sourcePath = path.join(tempDir, skill.path);
      if (fs.existsSync(sourcePath)) {
        fs.cpSync(sourcePath, targetDir, { recursive: true });
      } else if (skill.path === '.' || skill.path === '' || skill.path === skill.id) {
        fs.cpSync(tempDir, targetDir, { recursive: true });
      } else {
        throw new Error(`Skill path not found: ${sourcePath}`);
      }

      // 清理临时目录
      fs.rmSync(tempDir, { recursive: true, force: true });

      await this._postMessage({
        type: 'installComplete',
        payload: { skillId: skill.id, name: skill.name, skillType: installTarget }
      });
      this._outputChannel.appendLine(`[SkillManagement] Successfully installed ${skillTypeLabel}: ${skill.name}`);
    } catch (error: any) {
      const message = error?.message || String(error);
      this._outputChannel.appendLine(`[SkillManagement] Failed to install ${skill.name}: ${message}`);
      await this._postMessage({ type: 'installFailed', payload: { skillId: skill.id, error: message } });
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
        await this._loadAgentSkills();
      }
    } catch (error: any) {
      this._outputChannel.appendLine(`[SkillManagement] Failed to import skill: ${error.message}`);
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
      this._outputChannel.appendLine(`[SkillManagement] Claude import failed: ${error.message}`);
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
          item.skillsPath = s.skillsPath.trim().replace(/^\/+|\/+$/g, '');
        }
        if (s.platform && s.platform !== 'github') {
          item.platform = s.platform;
        }
        if (s.baseUrl?.trim()) {
          item.baseUrl = s.baseUrl.trim();
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
      this._outputChannel.appendLine(`[SkillManagement] Save sources failed: ${error.message}`);
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
      this._outputChannel.appendLine(`[SkillManagement] Save GitHub token failed: ${error.message}`);
    }
  }

  private _parseGitNoIndexDiff(
    diffText: string,
    localRoot: string,
    remoteRoot: string,
    skill: MarketplaceSkill
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
      if (f.status === 'added') filesAdded.push(f.path);
      else if (f.status === 'deleted') filesDeleted.push(f.path);
      else filesModified.push(f.path);
    }

    return { filesAdded, filesDeleted, filesModified, fileDiffs };
  }

  private async _getSkillUpdateDiff(skill: MarketplaceSkill): Promise<void> {
    try {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        throw new Error('No workspace folder opened');
      }

      const localRoot =
        skill.installTarget === 'agent'
          ? path.join(workspaceFolder.uri.fsPath, 'custom', 'skills', skill.id)
          : path.join(workspaceFolder.uri.fsPath, '.claude', 'skills', skill.id);

      if (!fs.existsSync(localRoot)) {
        throw new Error(`Local skill not found: ${localRoot}`);
      }

      const branch = skill.branch || 'main';
      if (!isValidGitBranch(branch)) {
        throw new Error(`Invalid branch name: ${branch}`);
      }
      if (!isValidGitRepoUrl(skill.repo)) {
        throw new Error(`Invalid or disallowed repository URL: ${skill.repo}`);
      }

      const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), `skill-diff-${skill.id}-`));
      spawnSync('git', ['clone', '--depth', '1', '--branch', branch, skill.repo, tempDir], {
        encoding: 'utf-8',
        timeout: 120000,
      });

      const remoteRoot = path.join(tempDir, skill.path);
      if (!fs.existsSync(remoteRoot)) {
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

  private async _postMessage(message: { type: string; payload?: any }): Promise<void> {
    await this._webview.postMessage(message);
  }

  private _getHtmlForWebview(webview: vscode.Webview): string {
    const scriptPath = path.join(this._extensionUri.fsPath, 'out', 'webview', 'skillMarketplace.js');
    const scriptUri = webview.asWebviewUri(vscode.Uri.file(scriptPath));

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Skill Marketplace</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { height: 100vh; overflow: auto; }
    #root { min-height: 100vh; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script src="${scriptUri}"></script>
</body>
</html>`;
  }
}
