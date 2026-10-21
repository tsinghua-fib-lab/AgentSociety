/**
 * Workspace Manager - Local file operations
 *
 * Handles workspace file operations locally instead of using backend APIs.
 *
 * 关联文件：
 * - @extension/src/projectStructureProvider.ts - 树视图调用WorkspaceManager初始化工作区
 * - @extension/src/extension.ts - 主入口，创建WorkspaceManager实例
 * - @extension/skills/ - AgentSociety 内置 skills（插件侧只读展示，同时同步到 workspace/.claude/skills）
 *   and exposed to Codex through workspace/.codex/skills when possible.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { execFileSync } from 'child_process';
import { SkillVersionManager } from './skillVersionManager';
import { getMainOutputChannel } from './shared/outputChannels';

export interface WorkspaceInitOptions {
  topic: string;
  createStructure?: boolean;
  progress?: vscode.Progress<{ message?: string; increment?: number }>;
}

export interface WorkspaceInitResult {
  success: boolean;
  message: string;
  filesCreated?: string[];
}

export class WorkspaceManager {
  private outputChannel: vscode.OutputChannel;
  private skillsSourcePath: string;
  private pluginsSourcePath: string;
  private runtimeSourcePath: string;
  private versionManager: SkillVersionManager;

  constructor(context: vscode.ExtensionContext) {
    this.outputChannel = getMainOutputChannel();
    this.skillsSourcePath = path.join(context.extensionPath, 'skills');
    this.pluginsSourcePath = path.join(context.extensionPath, 'plugins');
    this.runtimeSourcePath = path.join(context.extensionPath, 'runtime');
    this.versionManager = new SkillVersionManager(context, this.outputChannel);
  }

  /** Expose version manager for callers (commands, webview provider). */
  public getVersionManager(): SkillVersionManager {
    return this.versionManager;
  }

  private log(message: string): void {
    const timestamp = new Date().toISOString();
    this.outputChannel.appendLine(`[${timestamp}] [Workspace] ${message}`);
  }

  /**
   * Get workspace folder path
   */
  getWorkspacePath(): string | null {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    return workspaceFolder ? workspaceFolder.uri.fsPath : null;
  }

  /**
   * Show the Workspace Manager output channel
   */
  showOutput(): void {
    this.outputChannel.show();
  }

  /**
   * Initialize workspace
   */
  async init(options: WorkspaceInitOptions): Promise<WorkspaceInitResult> {
    const workspacePath = this.getWorkspacePath();
    if (!workspacePath) {
      return {
        success: false,
        message: 'No workspace folder open',
      };
    }

    const filesCreated: string[] = [];

    const reportProgress = (message: string) => {
      if (options.progress) {
        options.progress.report({ message });
      }
      this.log(message);
    };

    try {
      reportProgress('正在创建基础文件...');

      const gitInitResult = this.ensureWorkspaceGitRepository(workspacePath);
      if (gitInitResult.initialized) {
        filesCreated.push('.git/');
        // Make an initial commit so the repo is not empty
        try {
          execFileSync('git', ['add', '-A'], { cwd: workspacePath, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] });
          execFileSync('git', ['commit', '-m', 'init: bootstrap research workspace', '--allow-empty'], { cwd: workspacePath, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] });
        } catch (error) {
          this.log(`Initial git commit failed (non-fatal): ${error}`);
        }
      }

      // Create/update .gitignore to exclude .env
      const gitignorePath = path.join(workspacePath, '.gitignore');
      this.updateGitignore(gitignorePath);

      // Create .env file from EnvManager example if it doesn't exist
      const envPath = path.join(workspacePath, '.env');
      if (!fs.existsSync(envPath)) {
        const { EnvManager } = await import('./envManager');
        const envManager = new EnvManager();
        envManager.createEnvFromExample();
        filesCreated.push('.env (from example)');
      }

      // Verify .env has required API key before proceeding with CLI calls
      const { EnvManager } = await import('./envManager');
      const envManager = new EnvManager();
      const envConfig = envManager.readEnv();
      const hasApiKey = !!(envConfig.llmApiKey?.trim());

      if (!hasApiKey) {
        this.log('Warning: .env file exists but LLM API key is not configured');
        // Still create basic structure, but skip CLI-dependent operations
        return {
          success: false,
          message: '工作区初始化失败：请在 .env 文件中配置 LLM API 密钥后重试',
          filesCreated,
        };
      }

      // Create TOPIC.md
      const topicPath = path.join(workspacePath, 'TOPIC.md');
      if (!fs.existsSync(topicPath)) {
        fs.writeFileSync(topicPath, `# ${options.topic}\n\n`, 'utf-8');
        filesCreated.push('TOPIC.md');
        this.log(`Created: ${topicPath}`);
      }

      // Create papers directory
      const papersDir = path.join(workspacePath, 'papers');
      if (!fs.existsSync(papersDir)) {
        fs.mkdirSync(papersDir, { recursive: true });
        filesCreated.push('papers/');
        this.log(`Created: ${papersDir}`);
      }

      // Create user_data directory for user data storage
      const userDataDir = path.join(workspacePath, 'user_data');
      if (!fs.existsSync(userDataDir)) {
        fs.mkdirSync(userDataDir, { recursive: true });
        filesCreated.push('user_data/');
        this.log(`Created: ${userDataDir}`);
      }

      // Create datasets directory for downloaded datasets
      const datasetsDir = path.join(workspacePath, 'datasets');
      if (!fs.existsSync(datasetsDir)) {
        fs.mkdirSync(datasetsDir, { recursive: true });
        filesCreated.push('datasets/');
        this.log(`Created: ${datasetsDir}`);
      }

      // Initialize custom modules using agentsociety2 CLI
      reportProgress('正在初始化自定义模块...');

      const customDir = path.join(workspacePath, 'custom');
      if (!fs.existsSync(customDir)) {
        const initCustomResult = await this.initCustomModules(workspacePath, options.progress);
        if (initCustomResult.success) {
          filesCreated.push(...initCustomResult.created);
          this.log(`Custom modules initialized: ${initCustomResult.created.join(', ')}`);
        } else {
          this.log(`Failed to initialize custom modules: ${initCustomResult.message}`);
          // 即使自定义模块初始化失败，也继续创建其他文件
        }
      } else {
        filesCreated.push('custom/ (already exists)');
        this.log(`Custom directory already exists: ${customDir}`);
      }

      reportProgress('正在创建文献索引...');

      // Create literature index
      const indexPath = path.join(papersDir, 'literature_index.json');
      if (!fs.existsSync(indexPath)) {
        const index = {
          version: '1.0',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          entries: [],
        };
        fs.writeFileSync(indexPath, JSON.stringify(index, null, 2), 'utf-8');
        filesCreated.push('papers/literature_index.json');
        this.log(`Created: ${indexPath}`);
      }

      reportProgress('正在创建工作区配置...');

      // Create .agentsociety directory for internal state and persisted workflow files
      const agentsocietyDir = path.join(workspacePath, '.agentsociety');
      if (!fs.existsSync(agentsocietyDir)) {
        fs.mkdirSync(agentsocietyDir, { recursive: true });
        filesCreated.push('.agentsociety/');
        this.log(`Created: ${agentsocietyDir}`);
      }

      this.ensureWorkspaceStateFiles(workspacePath, options.topic, filesCreated);

      // Create CLAUDE.md with technical project guidance
      const claudeMdPath = path.join(workspacePath, 'CLAUDE.md');
      if (!fs.existsSync(claudeMdPath)) {
        const claudeMdContent = this.getClaudeMdContent();
        fs.writeFileSync(claudeMdPath, claudeMdContent, 'utf-8');
        filesCreated.push('CLAUDE.md');
        this.log(`Created: ${claudeMdPath}`);
      }

      // Create AGENTS.md as symlink to CLAUDE.md
      const agentsMdPath = path.join(workspacePath, 'AGENTS.md');
      if (!fs.existsSync(agentsMdPath)) {
        try {
          fs.symlinkSync('CLAUDE.md', agentsMdPath);
          filesCreated.push('AGENTS.md (symlink to CLAUDE.md)');
          this.log(`Created symlink: ${agentsMdPath} -> CLAUDE.md`);
        } catch (error) {
          // Symlink creation may fail on Windows or without permissions
          // Fall back to copying the content
          fs.writeFileSync(agentsMdPath, fs.readFileSync(claudeMdPath), 'utf-8');
          filesCreated.push('AGENTS.md (copy of CLAUDE.md)');
          this.log(`Created copy: ${agentsMdPath} (symlink not supported)`);
        }
      }

      reportProgress('正在同步 Claude Code 资源...');

      const syncResult = this.syncClaudeCodeResources();
      if (!syncResult.success) {
        this.log(`Failed to sync Claude Code resources: ${syncResult.message}`);
        return {
          success: false,
          message: `初始化工作区失败：${syncResult.message}`,
          filesCreated,
        };
      }
      if (syncResult.created.length > 0) {
        filesCreated.push(...syncResult.created);
      }

      reportProgress('正在安装官方 Office 文档处理技能...');

      const officeSkillsResult = await this.copyOfficialOfficeSkills();
      if (!officeSkillsResult.success) {
        this.log(`Failed to copy official office skills: ${officeSkillsResult.message}`);
        // Don't fail initialization if office skills copy fails, just log it
      } else {
        filesCreated.push(...officeSkillsResult.downloaded.map(s => `.claude/skills/${s}/`));
        this.log(`Copied official office skills: ${officeSkillsResult.downloaded.join(', ')}`);
        this.autoCommit(workspacePath, `init: office skills (${officeSkillsResult.downloaded.join(', ')})`);
      }

      reportProgress('正在配置 paper-toolkit 插件市场...');

      const marketplaceResult = this.seedClaudePluginMarketplaces(workspacePath);
      if (!marketplaceResult.success) {
        this.log(`Failed to seed paper-toolkit marketplace: ${marketplaceResult.message}`);
      } else if (marketplaceResult.written) {
        filesCreated.push('.claude/settings.json');
        this.log(marketplaceResult.message);
        this.autoCommit(workspacePath, 'init: paper-toolkit plugin marketplace');
      }

      reportProgress('正在完成初始化...');

      this.autoCommit(workspacePath, 'init: workspace initialized');

      return {
        success: true,
        message: `Workspace initialized for topic: ${options.topic}`,
        filesCreated,
      };
    } catch (error) {
      this.log(`Failed to initialize workspace: ${error}`);
      return {
        success: false,
        message: `初始化工作区失败: ${error}`,
      };
    }
  }

  /**
   * Check if custom modules exist
   */
  getCustomModulesStatus(): {
    customDirExists: boolean;
    agentsDirExists: boolean;
    envsDirExists: boolean;
    agentFilesCount: number;
    envFilesCount: number;
  } {
    const workspacePath = this.getWorkspacePath();
    if (!workspacePath) {
      return {
        customDirExists: false,
        agentsDirExists: false,
        envsDirExists: false,
        agentFilesCount: 0,
        envFilesCount: 0,
      };
    }

    const customDir = path.join(workspacePath, 'custom');
    const agentsDir = path.join(customDir, 'agents');
    const envsDir = path.join(customDir, 'envs');

    let agentFilesCount = 0;
    let envFilesCount = 0;

    if (fs.existsSync(agentsDir)) {
      const files = fs.readdirSync(agentsDir);
      // Count .py files but exclude examples directory
      agentFilesCount = files.filter(f => f.endsWith('.py') && !f.startsWith('__')).length;
    }

    if (fs.existsSync(envsDir)) {
      const files = fs.readdirSync(envsDir);
      // Count .py files but exclude examples directory
      envFilesCount = files.filter(f => f.endsWith('.py') && !f.startsWith('__')).length;
    }

    return {
      customDirExists: fs.existsSync(customDir),
      agentsDirExists: fs.existsSync(agentsDir),
      envsDirExists: fs.existsSync(envsDir),
      agentFilesCount,
      envFilesCount,
    };
  }

  /**
   * List custom modules
   */
  listCustomModules(): { agents: string[]; envs: string[] } {
    const workspacePath = this.getWorkspacePath();
    if (!workspacePath) {
      return { agents: [], envs: [] };
    }

    const agentsDir = path.join(workspacePath, 'custom', 'agents');
    const envsDir = path.join(workspacePath, 'custom', 'envs');

    const agents: string[] = [];
    const envs: string[] = [];

    if (fs.existsSync(agentsDir)) {
      const files = fs.readdirSync(agentsDir);
      for (const file of files) {
        if (file.endsWith('.py') && !file.startsWith('__')) {
          agents.push(file);
        }
      }
    }

    if (fs.existsSync(envsDir)) {
      const files = fs.readdirSync(envsDir);
      for (const file of files) {
        if (file.endsWith('.py') && !file.startsWith('__')) {
          envs.push(file);
        }
      }
    }

    return { agents, envs };
  }

  /**
   * Sync extension-bundled Claude Code resources into the workspace.
   *
   * The extension keeps a read-only copy of AgentSociety skills under
   * `extension/skills/` for UI browsing, but Claude Code discovers them from
   * the workspace-local `.claude/skills/` directory. Runtime launcher assets
   * are synced into `.agentsociety/bin/`.
   */
  public syncClaudeCodeResources(
    workspacePath?: string
  ): { success: boolean; message: string; created: string[]; synced: string[] } {
    workspacePath = workspacePath || this.getWorkspacePath() || '';
    if (!workspacePath) {
      return {
        success: false,
        message: 'No workspace folder open',
        created: [],
        synced: [],
      };
    }

    if (!fs.existsSync(this.skillsSourcePath) || !fs.statSync(this.skillsSourcePath).isDirectory()) {
      return {
        success: false,
        message: `扩展技能目录不存在: ${this.skillsSourcePath}`,
        created: [],
        synced: [],
      };
    }

    const claudeDir = path.join(workspacePath, '.claude');
    const targetDir = path.join(claudeDir, 'skills');
    const created: string[] = [];
    const synced: string[] = [];

    const runtimeResult = this.syncWorkspaceRuntimeAssets(workspacePath);
    if (!runtimeResult.success) {
      return runtimeResult;
    }
    created.push(...runtimeResult.created);
    synced.push(...runtimeResult.synced);

    if (!fs.existsSync(claudeDir)) {
      fs.mkdirSync(claudeDir, { recursive: true });
      created.push('.claude/');
      this.log(`Created: ${claudeDir}`);
    }

    if (!fs.existsSync(targetDir)) {
      fs.mkdirSync(targetDir, { recursive: true });
      created.push('.claude/skills/');
      this.log(`Created: ${targetDir}`);
    }

    for (const item of fs.readdirSync(this.skillsSourcePath)) {
      // agentsociety-* skills are version-managed; applyPreset handles them below.
      if (SkillVersionManager.isVersioned(item)) {
        continue;
      }
      const sourcePath = path.join(this.skillsSourcePath, item);
      const targetPath = path.join(targetDir, item);

      try {
        const stat = fs.statSync(sourcePath);
        if (stat.isDirectory()) {
          if (fs.existsSync(targetPath)) {
            fs.rmSync(targetPath, { recursive: true, force: true });
          }
          this.copyDirectoryRecursive(sourcePath, targetPath);
          synced.push(item);
        } else if (stat.isFile()) {
          fs.copyFileSync(sourcePath, targetPath);
          synced.push(item);
        }
      } catch (error) {
        this.log(`Failed to copy Claude resource ${sourcePath}: ${error}`);
        return {
          success: false,
          message: `无法同步 Claude Code 资源: ${sourcePath}`,
          created,
          synced,
        };
      }
    }

    // Apply the active version preset to materialize agentsociety-* skills as symlinks.
    const applyResult = this.versionManager.applyPreset(workspacePath);
    for (const a of applyResult.applied) {
      synced.push(a.skill);
    }
    if (applyResult.errors.length > 0) {
      this.log(
        `applyPreset[${applyResult.preset}] reported ${applyResult.errors.length} error(s): ` +
        applyResult.errors.map((e) => `${e.skill}: ${e.message}`).join('; '),
      );
    }
    if (applyResult.fallbacks.length > 0) {
      this.log(
        `applyPreset[${applyResult.preset}] fell back to defaults for: ${applyResult.fallbacks.join(', ')}`,
      );
    }

    this.pruneLegacyAnalysisSkillLayouts(workspacePath);

    created.push(...this.ensureCodexSkillsLink(workspacePath, targetDir));

    // Install bundled plugins (skills → .claude/skills/, commands → .claude/commands/)
    const pluginResult = this.installBundledPlugins(workspacePath);
    created.push(...pluginResult.created);
    synced.push(...pluginResult.synced);

    this.autoCommit(workspacePath, `sync: Claude Code resources (${synced.length} items)`);

    if (synced.length === 0) {
      return {
        success: false,
        message: '扩展技能目录为空，未同步任何 Claude Code 资源',
        created,
        synced,
      };
    }

    return {
      success: true,
      message: `已同步 ${synced.length} 个 Claude Code 资源`,
      created,
      synced,
    };
  }

  private ensureCodexSkillsLink(workspacePath: string, claudeSkillsDir: string): string[] {
    const codexDir = path.join(workspacePath, '.codex');
    const codexSkillsPath = path.join(codexDir, 'skills');
    const created: string[] = [];
    const relativeTarget = path.relative(codexDir, claudeSkillsDir) || '.';

    if (!fs.existsSync(codexDir)) {
      fs.mkdirSync(codexDir, { recursive: true });
      created.push('.codex/');
      this.log(`Created: ${codexDir}`);
    }

    if (fs.existsSync(codexSkillsPath)) {
      const stat = fs.lstatSync(codexSkillsPath);
      if (stat.isSymbolicLink()) {
        const resolved = fs.realpathSync(codexSkillsPath);
        const expected = fs.realpathSync(claudeSkillsDir);
        if (resolved === expected) {
          return created;
        }
        fs.rmSync(codexSkillsPath, { recursive: true, force: true });
      } else if (stat.isDirectory() && fs.readdirSync(codexSkillsPath).length === 0) {
        fs.rmSync(codexSkillsPath, { recursive: true, force: true });
      } else {
        this.log(
          `Skipped Codex skills link because .codex/skills already exists and is not empty: ${codexSkillsPath}`,
        );
        return created;
      }
    }

    try {
      fs.symlinkSync(relativeTarget, codexSkillsPath, 'dir');
      created.push('.codex/skills (symlink to ../.claude/skills)');
      this.log(`Created symlink: ${codexSkillsPath} -> ${relativeTarget}`);
    } catch (error) {
      this.log(`Failed to create Codex skills symlink: ${error}`);
    }

    return created;
  }

  /**
   * Install bundled Claude Code plugins from extension/plugins/.
   * Each plugin's skills/ are copied to .claude/skills/ and commands/ to .claude/commands/.
   */
  private installBundledPlugins(
    workspacePath: string,
  ): { created: string[]; synced: string[] } {
    const created: string[] = [];
    const synced: string[] = [];

    if (!fs.existsSync(this.pluginsSourcePath) || !fs.statSync(this.pluginsSourcePath).isDirectory()) {
      return { created, synced };
    }

    const claudeDir = path.join(workspacePath, '.claude');
    const skillsDir = path.join(claudeDir, 'skills');
    const commandsDir = path.join(claudeDir, 'commands');

    for (const pluginName of fs.readdirSync(this.pluginsSourcePath)) {
      const pluginDir = path.join(this.pluginsSourcePath, pluginName);
      if (!fs.statSync(pluginDir).isDirectory()) {
        continue;
      }

      // Install plugin skills
      const pluginSkillsDir = path.join(pluginDir, 'skills');
      if (fs.existsSync(pluginSkillsDir) && fs.statSync(pluginSkillsDir).isDirectory()) {
        if (!fs.existsSync(skillsDir)) {
          fs.mkdirSync(skillsDir, { recursive: true });
          created.push('.claude/skills/');
        }
        for (const skillName of fs.readdirSync(pluginSkillsDir)) {
          const sourceSkillPath = path.join(pluginSkillsDir, skillName);
          if (!fs.statSync(sourceSkillPath).isDirectory()) {
            continue;
          }
          const targetSkillPath = path.join(skillsDir, skillName);
          try {
            if (fs.existsSync(targetSkillPath)) {
              fs.rmSync(targetSkillPath, { recursive: true, force: true });
            }
            this.copyDirectoryRecursive(sourceSkillPath, targetSkillPath);
            synced.push(skillName);
          } catch (error) {
            this.log(`Failed to install plugin skill ${skillName}: ${error}`);
          }
        }
      }

      // Install plugin commands
      const pluginCommandsDir = path.join(pluginDir, 'commands');
      if (fs.existsSync(pluginCommandsDir) && fs.statSync(pluginCommandsDir).isDirectory()) {
        if (!fs.existsSync(commandsDir)) {
          fs.mkdirSync(commandsDir, { recursive: true });
          created.push('.claude/commands/');
          this.log(`Created: ${commandsDir}`);
        }
        for (const cmdFile of fs.readdirSync(pluginCommandsDir)) {
          if (!cmdFile.endsWith('.md')) {
            continue;
          }
          const sourceCmdPath = path.join(pluginCommandsDir, cmdFile);
          const targetCmdPath = path.join(commandsDir, cmdFile);
          try {
            fs.copyFileSync(sourceCmdPath, targetCmdPath);
            synced.push(cmdFile);
          } catch (error) {
            this.log(`Failed to install plugin command ${cmdFile}: ${error}`);
          }
        }
      }

      this.log(`Installed plugin: ${pluginName} (skills + commands)`);
    }

    return { created, synced };
  }

  /** Expose the bundled plugins source path for the marketplace provider. */
  public getPluginsSourcePath(): string {
    return this.pluginsSourcePath;
  }

  private syncWorkspaceRuntimeAssets(
    workspacePath: string
  ): { success: boolean; message: string; created: string[]; synced: string[] } {
    const sourceBinDir = path.join(this.runtimeSourcePath, 'agentsociety', 'bin');
    if (!fs.existsSync(sourceBinDir) || !fs.statSync(sourceBinDir).isDirectory()) {
      return {
        success: false,
        message: `扩展运行时目录不存在: ${sourceBinDir}`,
        created: [],
        synced: [],
      };
    }

    const agentsocietyDir = path.join(workspacePath, '.agentsociety');
    const targetBinDir = path.join(agentsocietyDir, 'bin');
    const created: string[] = [];

    if (!fs.existsSync(agentsocietyDir)) {
      fs.mkdirSync(agentsocietyDir, { recursive: true });
      created.push('.agentsociety/');
      this.log(`Created: ${agentsocietyDir}`);
    }

    if (fs.existsSync(targetBinDir)) {
      fs.rmSync(targetBinDir, { recursive: true, force: true });
    }
    fs.mkdirSync(targetBinDir, { recursive: true });
    created.push('.agentsociety/bin/');
    this.log(`Created: ${targetBinDir}`);

    try {
      this.copyDirectoryRecursive(sourceBinDir, targetBinDir);
    } catch (error) {
      this.log(`Failed to copy runtime assets ${sourceBinDir}: ${error}`);
      return {
        success: false,
        message: `无法同步工作区运行时资源: ${sourceBinDir}`,
        created,
        synced: [],
      };
    }

    return {
      success: true,
      message: '已同步工作区运行时资源',
      created,
      synced: ['.agentsociety/bin/ags.py'],
    };
  }

  public syncSingleBundledSkill(
    skillName: string,
    workspacePath?: string
  ): { success: boolean; message: string } {
    const trimmed = skillName.trim();
    if (!trimmed) {
      return { success: false, message: '技能名称为空' };
    }

    workspacePath = workspacePath || this.getWorkspacePath() || '';
    if (!workspacePath) {
      return { success: false, message: 'No workspace folder open' };
    }

    if (!fs.existsSync(this.skillsSourcePath) || !fs.statSync(this.skillsSourcePath).isDirectory()) {
      return { success: false, message: `扩展技能目录不存在: ${this.skillsSourcePath}` };
    }

    // agentsociety-* skills go through the version manager (active preset → symlink).
    if (SkillVersionManager.isVersioned(trimmed)) {
      const result = this.versionManager.applyPreset(workspacePath);
      const applied = result.applied.find((a) => a.skill === trimmed);
      if (applied) {
        return {
          success: true,
          message: `已应用 preset「${result.preset}」中的 ${trimmed}（${applied.mode}）`,
        };
      }
      const errored = result.errors.find((e) => e.skill === trimmed);
      if (errored) {
        return { success: false, message: `同步失败 ${trimmed}: ${errored.message}` };
      }
      return { success: false, message: `未找到技能 ${trimmed}` };
    }

    // Office / legacy skills: keep flat copy.
    const sourcePath = path.join(this.skillsSourcePath, trimmed);
    if (!fs.existsSync(sourcePath)) {
      return { success: false, message: `扩展中不存在技能: ${trimmed}` };
    }

    const stat = fs.statSync(sourcePath);
    if (!stat.isDirectory()) {
      return { success: false, message: `不是技能目录: ${trimmed}` };
    }

    const claudeDir = path.join(workspacePath, '.claude');
    const targetDir = path.join(claudeDir, 'skills');
    const targetPath = path.join(targetDir, trimmed);

    try {
      if (!fs.existsSync(claudeDir)) {
        fs.mkdirSync(claudeDir, { recursive: true });
      }
      fs.mkdirSync(targetDir, { recursive: true });
      if (fs.existsSync(targetPath)) {
        fs.rmSync(targetPath, { recursive: true, force: true });
      }
      this.copyDirectoryRecursive(sourcePath, targetPath);
    } catch (error) {
      this.log(`syncSingleBundledSkill failed: ${error}`);
      return { success: false, message: `同步失败: ${trimmed}` };
    }

    return { success: true, message: `已同步到工作区 .claude/skills/${trimmed}` };
  }

  /**
   * Copy bundled Claude Office skills (pdf, docx, xlsx, pptx) to .claude/skills/
   */
  public async copyOfficialOfficeSkills(
    workspacePath?: string
  ): Promise<{ success: boolean; message: string; downloaded: string[] }> {
    workspacePath = workspacePath || this.getWorkspacePath() || '';
    if (!workspacePath) {
      return {
        success: false,
        message: 'No workspace folder open',
        downloaded: [],
      };
    }

    const officialSkills = ['pdf', 'docx', 'xlsx', 'pptx'];
    const downloaded: string[] = [];
    const targetDir = path.join(workspacePath, '.claude', 'skills');

    // Ensure target directory exists (recursive mkdir is idempotent)
    fs.mkdirSync(targetDir, { recursive: true });

    // Get extension skills directory - handle different execution contexts
    // In production: __dirname = extension/out/, skills = extension/skills/
    // In development: __dirname might vary, so we try multiple paths
    // Try common paths for skills directory, based on actual __dirname structure
    const possiblePaths = [
      path.join(__dirname, '..', 'skills'),                  // extension/out/ -> extension/skills/
      path.join(__dirname, '..', '..', 'extension', 'skills'), // workspace root -> extension/skills/
      path.join(__dirname, '..', '..', '..', 'agentsociety', 'extension', 'skills'), // higher level
      path.join(process.cwd(), 'agentsociety', 'extension', 'skills'), // from project root
      path.join(process.cwd(), 'extension', 'skills'),        // alternative
    ];

    const sourceSkillsDir = possiblePaths.find(p => fs.existsSync(p)) || '';

    // Verify extension skills directory exists
    if (!sourceSkillsDir) {
      this.log(`Extension skills directory not found. Tried paths: ${possiblePaths.join(', ')}`);
      return {
        success: false,
        message: `Extension skills directory not found. Please check extension installation.`,
        downloaded: [],
      };
    }

    // Show output channel for progress tracking
    this.outputChannel.show();
    this.log('='.repeat(60));
    this.log('Copying official office skills from extension...');
    this.log(`Extension __dirname: ${__dirname}`);
    this.log(`Resolved source path: ${sourceSkillsDir}`);
    this.log(`Target: ${targetDir}`);
    this.log('='.repeat(60));

    for (const skill of officialSkills) {
      const sourceSkillDir = path.join(sourceSkillsDir, skill);
      const targetSkillDir = path.join(targetDir, skill);

      this.log(`[${skill}] Processing...`);

      // Check if source skill exists
      if (!fs.existsSync(sourceSkillDir)) {
        this.log(`[${skill}] ✗ Not found in extension skills directory`);
        continue;
      }

      try {
        // Remove existing skill directory if present
        if (fs.existsSync(targetSkillDir)) {
          fs.rmSync(targetSkillDir, { recursive: true, force: true });
          this.log(`[${skill}] Removed existing directory`);
        }

        // Copy skill directory
        this.copyDirectoryRecursive(sourceSkillDir, targetSkillDir);
        downloaded.push(skill);
        this.log(`[${skill}] ✓ Successfully copied`);
      } catch (error: any) {
        this.log(`[${skill}] ✗ Failed: ${error.message}`);
      }
    }

    this.log('='.repeat(60));
    this.log(`Copy complete: ${downloaded.length}/${officialSkills.length} skills`);
    this.log(`Copied: ${downloaded.join(', ') || 'none'}`);
    if (downloaded.length < officialSkills.length) {
      const missing = officialSkills.filter(s => !downloaded.includes(s));
      this.log(`Missing: ${missing.join(', ') || 'none'}`);
    }
    this.log('='.repeat(60));

    if (downloaded.length === 0) {
      return {
        success: false,
        message: `Failed to copy any official office skills. Please check the extension installation.`,
        downloaded,
      };
    }

    if (downloaded.length < officialSkills.length) {
      const missing = officialSkills.filter(s => !downloaded.includes(s));
      return {
        success: true,
        message: `Copied ${downloaded.length}/${officialSkills.length} office skills. Missing: ${missing.join(', ')}`,
        downloaded,
      };
    }

    return {
      success: true,
      message: `Successfully copied all ${downloaded.length} official office skills: ${downloaded.join(', ')}`,
      downloaded,
    };
  }

  /**
   * Seed `<workspace>/.claude/settings.json` with Claude Code plugin marketplace
   * config so CC prompts the user to install the paper-toolkit plugin (which
   * delivers the `paper` skill) when they trust the workspace folder.
   *
   * Idempotent + merge-only: any existing keys outside of
   * `extraKnownMarketplaces.paper-toolkit` / `enabledPlugins["paper-toolkit@paper-toolkit"]`
   * are preserved verbatim.
   */
  public seedClaudePluginMarketplaces(
    workspacePath?: string
  ): { success: boolean; message: string; written: boolean } {
    workspacePath = workspacePath || this.getWorkspacePath() || '';
    if (!workspacePath) {
      return { success: false, message: 'No workspace folder open', written: false };
    }

    const claudeDir = path.join(workspacePath, '.claude');
    const settingsPath = path.join(claudeDir, 'settings.json');

    let settings: Record<string, any> = {};
    if (fs.existsSync(settingsPath)) {
      try {
        const raw = fs.readFileSync(settingsPath, 'utf-8');
        settings = raw.trim() ? JSON.parse(raw) : {};
      } catch (error) {
        this.log(`Failed to parse existing ${settingsPath}: ${error}`);
        return {
          success: false,
          message: `无法解析 ${settingsPath}: ${error}`,
          written: false,
        };
      }
    }

    const desiredMarketplace = {
      source: { source: 'github', repo: 'Yokumii/paper-toolkit' },
    };
    const marketplaces =
      (settings.extraKnownMarketplaces as Record<string, any>) || {};
    const enabled = (settings.enabledPlugins as Record<string, boolean>) || {};

    const marketplaceMatches =
      JSON.stringify(marketplaces['paper-toolkit']) === JSON.stringify(desiredMarketplace);
    const enabledMatches = enabled['paper-toolkit@paper-toolkit'] === true;

    if (marketplaceMatches && enabledMatches) {
      return { success: true, message: 'paper-toolkit marketplace already seeded', written: false };
    }

    marketplaces['paper-toolkit'] = desiredMarketplace;
    enabled['paper-toolkit@paper-toolkit'] = true;
    settings.extraKnownMarketplaces = marketplaces;
    settings.enabledPlugins = enabled;

    try {
      if (!fs.existsSync(claudeDir)) {
        fs.mkdirSync(claudeDir, { recursive: true });
      }
      fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + '\n', 'utf-8');
      this.log(`Seeded paper-toolkit marketplace into ${settingsPath}`);
      return { success: true, message: 'paper-toolkit marketplace seeded', written: true };
    } catch (error) {
      this.log(`Failed to write ${settingsPath}: ${error}`);
      return {
        success: false,
        message: `无法写入 ${settingsPath}: ${error}`,
        written: false,
      };
    }
  }

  /** Remove obsolete analysis-support layouts (bundles now live under agentsociety-analysis/support/). */
  private pruneLegacyAnalysisSkillLayouts(workspacePath: string): void {
    const legacyPaths = [
      path.join(workspacePath, '.agentsociety', 'analysis-support'),
      path.join(workspacePath, '.claude', 'skills', 'frontend-design'),
    ];
    for (const legacy of legacyPaths) {
      if (!fs.existsSync(legacy)) {
        continue;
      }
      fs.rmSync(legacy, { recursive: true, force: true });
      this.log(`Removed legacy analysis skill layout: ${legacy}`);
    }
  }

  /**
   * Recursively copy a directory tree.
   */
  private copyDirectoryRecursive(source: string, target: string): void {
    // Create target directory (recursive mkdir is idempotent)
    fs.mkdirSync(target, { recursive: true });

    for (const item of fs.readdirSync(source)) {
      if (item === '__pycache__' || item.endsWith('.pyc')) {
        continue;
      }
      const sourcePath = path.join(source, item);
      const targetPath = path.join(target, item);
      const stat = fs.statSync(sourcePath);

      if (stat.isDirectory()) {
        this.copyDirectoryRecursive(sourcePath, targetPath);
      } else if (stat.isFile()) {
        fs.copyFileSync(sourcePath, targetPath);
      }
    }
  }

  /**
   * Initialize custom modules using agentsociety2 CLI
   *
   * Note: This requires agentsociety2 to be installed in the Python environment
   * specified by PYTHON_PATH in .env file. The package should be importable as
   * 'agentsociety2.society.workspace'.
   */
  async initCustomModules(
    workspacePath: string,
    progress?: vscode.Progress<{ message?: string; increment?: number }>
  ): Promise<{ success: boolean; message: string; created: string[] }> {
    const { execFile } = require('child_process');
    const util = require('util');
    const execFilePromise = util.promisify(execFile);

    const reportProgress = (message: string) => {
      if (progress) {
        progress.report({ message });
      }
      this.log(message);
    };

    try {
      // Read .env to get PYTHON_PATH
      const { EnvManager } = await import('./envManager');
      const envManager = new EnvManager();
      const envConfig = envManager.readEnv();
      const configuredPythonPath = envConfig.pythonPath?.trim();

      // Determine Python command to use
      let pythonCmd = 'python'; // default fallback
      if (configuredPythonPath) {
        pythonCmd = configuredPythonPath;
        this.log(`Using configured PYTHON_PATH: ${pythonCmd}`);
      } else {
        this.log(`PYTHON_PATH not configured, using default: ${pythonCmd}`);
      }

      // Build command using determined Python path
      // Assumes agentsociety2 is installed in the Python environment
      const args = ['-m', 'agentsociety2.society.workspace', 'init-custom', '--target-dir', workspacePath, '--json'];

      this.log(`Executing: ${pythonCmd} ${JSON.stringify(args)}`);

      reportProgress('正在执行自定义模块初始化命令...');

      const { stdout, stderr } = await execFilePromise(
        pythonCmd, args,
        { cwd: workspacePath, env: process.env }
      );

      this.log(`Custom modules CLI output: ${stdout}`);
      if (stderr) {
        this.log(`Custom modules CLI stderr: ${stderr}`);
      }

      // Parse JSON output
      const result = JSON.parse(stdout);
      return {
        success: result.success || false,
        message: result.message || '',
        created: result.created || []
      };
    } catch (error: any) {
      this.log(`Failed to initialize custom modules via CLI: ${error.message}`);
      // Fallback: try to create basic directory structure
      try {
        reportProgress('使用备用方案创建目录结构...');

        const customDir = path.join(workspacePath, 'custom');
        const agentsDir = path.join(customDir, 'agents');
        const envsDir = path.join(customDir, 'envs');

        if (!fs.existsSync(agentsDir)) {
          fs.mkdirSync(agentsDir, { recursive: true });
        }
        if (!fs.existsSync(envsDir)) {
          fs.mkdirSync(envsDir, { recursive: true });
        }

        return {
          success: true,
          message: 'Custom modules directory created (CLI unavailable, used fallback)',
          created: ['custom/agents/', 'custom/envs/']
        };
      } catch (fallbackError: any) {
        return {
          success: false,
          message: `初始化自定义模块失败: ${error.message}`,
          created: []
        };
      }
    }
  }

  /**
   * Update .gitignore to exclude .env file
   */
  private updateGitignore(gitignorePath: string): void {
    const entriesToAdd = [
      '.env',
      '.claude/*',
      '.claude/skills/',
      '.claude/settings.local.json',
      '!.claude/settings.json',
      '.codex/*',
      '.codex/skills/',
      '# Python cache files in custom/',
      'custom/**/__pycache__/',
      'custom/**/*.pyc',
      'custom/**/.pytest_cache/',
    ];

    try {
      let content = '';
      if (fs.existsSync(gitignorePath)) {
        content = fs.readFileSync(gitignorePath, 'utf-8');
      }

      const lines = content.split('\n');
      const normalizedLines = lines.filter((line) => line.trim() !== '.claude/');
      let modified = normalizedLines.length !== lines.length;
      if (modified) {
        content = normalizedLines.join('\n');
        if (content.length > 0 && !content.endsWith('\n')) {
          content += '\n';
        }
        this.log('Removed legacy .claude/ ignore rule to preserve project hook files');
      }

      const existingEntries = new Set(
        normalizedLines
          .map(l => l.trim())
          .filter(l => l && !l.startsWith('#'))
      );
      for (const entry of entriesToAdd) {
        if (!existingEntries.has(entry)) {
          if (!content.endsWith('\n') && content.length > 0) {
            content += '\n';
          }
          content += `${entry}\n`;
          modified = true;
          this.log(`Added to .gitignore: ${entry}`);
        }
      }

      if (modified || !fs.existsSync(gitignorePath)) {
        fs.writeFileSync(gitignorePath, content, 'utf-8');
        this.log(`Updated .gitignore: ${gitignorePath}`);
      }
    } catch (error) {
      this.log(`Failed to update .gitignore: ${error}`);
    }
  }

  private ensureWorkspaceGitRepository(workspacePath: string): { initialized: boolean; repoRoot?: string } {
    try {
      const existingRoot = execFileSync('git', ['rev-parse', '--show-toplevel'], {
        cwd: workspacePath,
        encoding: 'utf-8',
        stdio: ['ignore', 'pipe', 'pipe'],
      }).trim();
      if (existingRoot) {
        this.log(`Workspace already attached to git repository: ${existingRoot}`);
        return { initialized: false, repoRoot: existingRoot };
      }
    } catch (error) {
      this.log(`No existing git repository detected for workspace: ${error}`);
    }

    try {
      execFileSync('git', ['init', '--initial-branch=main'], {
        cwd: workspacePath,
        encoding: 'utf-8',
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      this.log(`Initialized git repository at: ${workspacePath}`);
      return { initialized: true, repoRoot: workspacePath };
    } catch (error) {
      this.log(`git init --initial-branch=main failed, retrying without branch flag: ${error}`);
    }

    try {
      execFileSync('git', ['init'], {
        cwd: workspacePath,
        encoding: 'utf-8',
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      this.log(`Initialized git repository at: ${workspacePath}`);
      return { initialized: true, repoRoot: workspacePath };
    } catch (error) {
      this.log(`Failed to initialize git repository: ${error}`);
      return { initialized: false };
    }
  }

  /**
   * Ensure the workspace is under git and commit all pending changes.
   * If no git repo exists yet, one is created first.
   */
  private autoCommit(workspacePath: string, message: string): void {
    const git = (...args: string[]): boolean => {
      try {
        execFileSync('git', args, { cwd: workspacePath, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] });
        return true;
      } catch (error) {
        this.log(`git ${args.join(' ')} failed: ${error}`);
        return false;
      }
    };

    const repo = this.ensureWorkspaceGitRepository(workspacePath);
    if (!repo.repoRoot) {
      this.log(`autoCommit skipped: no git repo at ${workspacePath}`);
      return;
    }

    // Ensure repo-local git identity so commits don't fail on fresh workspaces
    try {
      const userName = execFileSync('git', ['config', 'user.name'], { cwd: workspacePath, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
      if (!userName) {
        throw new Error('empty user.name');
      }
    } catch {
      git('config', 'user.name', 'AgentSociety');
      git('config', 'user.email', 'agent@agentsociety.dev');
    }

    if (!git('add', '-A')) {
      return;
    }
    // Check whether there is anything staged before committing
    try {
      execFileSync('git', ['diff', '--cached', '--quiet'], {
        cwd: workspacePath,
        encoding: 'utf-8',
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      // diff --cached --quiet exits 0 when nothing staged → skip commit
      return;
    } catch {
      // Non-zero exit means there ARE staged changes → proceed to commit
    }

    if (!git('commit', '-m', message)) {
      this.log(`autoCommit commit failed for: ${message}`);
      return;
    }
    this.log(`Auto-commit: ${message}`);
  }

  /**
   * Get CLAUDE.md content - AI Social Scientist workspace guide
   */
  private getClaudeMdContent(): string {
    return `# CLAUDE.md

This file provides guidance to Claude Code when working in this AI Social Scientist workspace.

**Research Context**: See \`TOPIC.md\` for research topics, goals, and current work.

---

## Session Start

At the start of a new task or when resuming work:

1. Read \`TOPIC.md\` to understand the research goal.
2. Read \`.env\` and resolve \`PYTHON_PATH\`.
3. Run:

\`\`\`bash
PYTHON_PATH=$(grep "^PYTHON_PATH=" .env | cut -d'=' -f2)
PYTHON_PATH=\${PYTHON_PATH:-python3}
$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline where-am-i --json
\`\`\`

Treat the returned pipeline state as the default source of truth for what to do next.

---

## Python Environment

All Claude Code skills in this workspace require \`agentsociety2\` to be available in the configured Python environment.

Always prefer the interpreter from \`.env\`:

\`\`\`bash
PYTHON_PATH=$(grep "^PYTHON_PATH=" .env | cut -d'=' -f2)
PYTHON_PATH=\${PYTHON_PATH:-python3}
\`\`\`

Required environment variables:

- \`AGENTSOCIETY_LLM_API_KEY\`
- \`AGENTSOCIETY_LLM_API_BASE\`
- \`AGENTSOCIETY_LLM_MODEL\`

Optional: \`AGENTSOCIETY_LLM_THINKING\` (\`on\`/\`off\`) toggles reasoning for OpenAI-compatible
endpoints; leave it unset to send no reasoning parameters at all. \`AGENTSOCIETY_CODER_LLM_*\`
overrides the coder role. See the extension config page for details.

Why this matters:

- Dependencies are managed via \`uv\`, not system Python.
- Skill scripts use the calling interpreter.
- Using the wrong interpreter usually means \`agentsociety2\` is not importable.

---

## Primary State Files

The workspace keeps durable execution state under \`.agentsociety/\`. Claude Code should use these files as working memory for the research process.

| File | Role | How to use it |
|------|------|---------------|
| \`.agentsociety/progress.json\` | Pipeline stage tracker | Read first when deciding the next research step |
| \`.agentsociety/bin/ags.py\` | Stable workspace launcher | Prefer this entry point for bundled workflow operations |

Prefer updating pipeline state through \`.agentsociety/bin/ags.py research-pipeline ...\` instead of editing state files manually.

---

## Workspace Map

\`\`\`
.
├── TOPIC.md
├── CLAUDE.md
├── AGENTS.md
├── .env
├── .claude/
│   ├── settings.json           # Project-level Claude Code settings
│   └── skills/                 # Claude Code skill bundle for this workspace
├── .agentsociety/
│   ├── progress.json
│   └── bin/ags.py
├── papers/                     # Literature outputs
├── datasets/                   # Downloaded datasets
├── user_data/                  # User-provided data files
├── custom/
│   ├── agents/                 # Custom agent code
│   ├── envs/                   # Custom environment module code
│   └── README.md
├── hypothesis_{id}/            # Hypothesis and experiment folders
├── presentation/               # Analysis reports and assets
├── synthesis/                  # Cross-hypothesis synthesis outputs
└── paper/                      # Workspace-level paper outputs
\`\`\`

Most tasks should begin with \`TOPIC.md\`, \`.agentsociety/progress.json\`, and the relevant hypothesis or report directory.

---

## Skill Routing

Claude Code loads the workspace-local skill bundle from \`.claude/skills/\`.

Use this routing model:

- Start with \`agentsociety-research-pipeline\` when the current stage is unclear.
- Use \`agentsociety-literature-search\` for academic literature collection.
- Use \`agentsociety-scan-modules\` before hypothesis creation or experiment configuration.
- Before \`experiment-config\`, \`create-agent\`, or \`create-env-module\`, resolve the simulation scale budget: target agent count or range, step budget, runtime budget, and preferred complexity tier. If the budget is missing, ask for it first and compare 2-3 approaches with trade-offs before choosing one.
- If the work may depend on external data, search datasets first with \`agentsociety-use-dataset\`; if a local file should be shared or reused, guide the user through \`agentsociety-create-dataset\` upload instead of hand-copying data into config.
- Use \`agentsociety-hypothesis\` to create or revise hypotheses.
- Use \`agentsociety-experiment-config\` to prepare \`init_config.json\` and \`steps.yaml\`.
- Use \`agentsociety-run-experiment\` only after configuration is ready and checked.
- Use \`agentsociety-analysis\` once experiment outputs exist.
- Use the external \`paper-toolkit\` plugin after analysis artifacts and reviewed claims are ready.
- Use \`agentsociety-paper-review\` after a complete draft exists when the user requests an internal venue-calibrated review, score, or advice about which research stage to revisit. For PDF input, use the bundled \`pdf\` skill plus the paper-review PDF intake once, then give all agents the same frozen text, layout, and page renders; stop if the intake quality gate fails. For a normal result, launch three isolated reviewer subagents concurrently with the same frozen inputs, then launch a separate MetaReview subagent to verify evidence, report score dispersion, and consolidate reroute advice. It writes only the review bundle and must not revise research artifacts, run experiments, or update pipeline state.
- After review, the user or controlling coding agent may accept one stage-valued reroute. Apply it with \`research-pipeline reroute STAGE --reason "..." --source-artifact PATH\`; never treat \`human_decision\` or \`none\` as stages. A reroute marks the target and completed downstream stages \`needs_revision\` and preserves an auditable revision round.
- Use \`agentsociety-use-dataset\` or \`agentsociety-create-dataset\` only when data acquisition or publishing is part of the task.

Preferred command examples:

\`\`\`bash
$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline where-am-i --json
$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline reroute analysis --reason "MetaReview requires uncertainty estimates" --source-artifact paper/reviews/acl-arr-review-r1.md
$PYTHON_PATH .agentsociety/bin/ags.py scan-modules list --short
$PYTHON_PATH .agentsociety/bin/ags.py hypothesis list --json
$PYTHON_PATH .agentsociety/bin/ags.py experiment-config validate --hypothesis-id 1 --experiment-id 1
$PYTHON_PATH .agentsociety/bin/ags.py run-experiment status --hypothesis-id 1 --experiment-id 1
$PYTHON_PATH .agentsociety/bin/ags.py analysis load-context --workspace . --hypothesis-id 1 --experiment-id 1
\`\`\`

---

## Operating Rules

Do:

- Match the user's language.
- Explain the current pipeline stage when it matters to the next action.
- Prefer \`.agentsociety/bin/ags.py\` over ad hoc helper scripts for workflow operations.
- Update pipeline state after completing a stage or resolving a meaningful blocker.
- When an accepted review requires backward movement, use \`research-pipeline reroute\` and carry its reason and source artifact into the owning skill.
- Read relevant state files before asking the user for information that may already exist in the workspace.
- Resolve the simulation scale budget before configuration or custom module creation; if it is missing, ask clarifying questions and compare 2-3 approaches with trade-offs.
- If external data is needed, search or inspect datasets before building new assumptions; guide dataset upload when the input should be shared or reused.
- **Commit every meaningful change**: after creating, editing, or deleting files, always run \`git add -A && git commit -m "<descriptive message>"\` to keep a full audit trail. This includes config files, experiment outputs, analysis results, and any workspace state changes.

Do not:

- Guess the current stage when \`research-pipeline where-am-i --json\` can tell you.
- Use system Python by default when \`.env\` provides \`PYTHON_PATH\`.
- Edit \`.agentsociety/*.json\` or \`.jsonl\` manually unless there is a clear reason not to use the CLI.
- Move \`current_stage\` backward by editing JSON or by marking an earlier stage \`in_progress\`; use \`research-pipeline reroute\` so downstream work is invalidated consistently.
- Let reviewer or analysis subagents mutate pipeline state; the controlling agent is the single writer of \`progress.json\`.
- Start analysis before experiment outputs exist.
- Start paper generation before analysis outputs and claim review are in place.
- Skip git commits after making file changes — every modification must be tracked.
`;
  }

  private ensureWorkspaceStateFiles(
    workspacePath: string,
    topic: string,
    filesCreated: string[]
  ): void {
    const agentsocietyDir = path.join(workspacePath, '.agentsociety');

    const writeJsonIfMissing = (relativePath: string, payload: unknown) => {
      const absolutePath = path.join(workspacePath, relativePath);
      if (fs.existsSync(absolutePath)) {
        return;
      }
      fs.writeFileSync(absolutePath, JSON.stringify(payload, null, 2), 'utf-8');
      filesCreated.push(relativePath);
      this.log(`Created: ${absolutePath}`);
    };

    const writeTextIfMissing = (relativePath: string, content: string) => {
      const absolutePath = path.join(workspacePath, relativePath);
      if (fs.existsSync(absolutePath)) {
        return;
      }
      fs.writeFileSync(absolutePath, content, 'utf-8');
      filesCreated.push(relativePath);
      this.log(`Created: ${absolutePath}`);
    };

    const emptyProgressStage = () => ({
      status: 'not_started',
      started_at: null,
      completed_at: null,
      attempts: 0,
      error: null,
      metadata: {},
      verification_status: 'not_started',
      revision_round: 0,
    });

    fs.mkdirSync(path.join(agentsocietyDir, 'agent_classes'), { recursive: true });
    fs.mkdirSync(path.join(agentsocietyDir, 'env_modules'), { recursive: true });
    fs.mkdirSync(path.join(agentsocietyDir, 'data'), { recursive: true });
    fs.mkdirSync(path.join(agentsocietyDir, 'custom_env_skill', 'runs'), { recursive: true });

    writeTextIfMissing('.agentsociety/path.md', this.getWorkspacePathMemoryContent());

    writeJsonIfMissing('.agentsociety/prefill_params.json', {
      version: '1.0',
      env_modules: {},
      agents: {},
    });

    writeJsonIfMissing('.agentsociety/progress.json', {
      version: '1.3',
      workspace: {
        topic: topic || '',
        created_at: new Date().toISOString(),
        current_stage: 'literature_search',
        current_hypothesis_id: null,
        current_experiment_id: null,
        revision_round: 0,
        active_reroute: null,
      },
      stages: {
        literature_search: emptyProgressStage(),
        hypothesis: emptyProgressStage(),
        experiment_config: emptyProgressStage(),
        run_experiment: emptyProgressStage(),
        analysis: emptyProgressStage(),
        generate_paper: emptyProgressStage(),
      },
      hypotheses: {},
      transitions: [],
    });

    this.removeObsoleteWorkspaceStateFiles(workspacePath);
  }

  private removeObsoleteWorkspaceStateFiles(workspacePath: string): void {
    const agentsocietyDir = path.join(workspacePath, '.agentsociety');
    if (!fs.existsSync(agentsocietyDir)) {
      return;
    }

    const keepRootFiles = new Set(['path.md', 'prefill_params.json', 'progress.json']);
    for (const entry of fs.readdirSync(agentsocietyDir, { withFileTypes: true })) {
      if (!entry.isFile()) {
        continue;
      }
      if (keepRootFiles.has(entry.name)) {
        continue;
      }
      if (!entry.name.endsWith('.json') && !entry.name.endsWith('.jsonl')) {
        continue;
      }

      const absolutePath = path.join(agentsocietyDir, entry.name);
      try {
        fs.rmSync(absolutePath, { force: true });
        this.log(`Removed obsolete workspace state file: ${absolutePath}`);
      } catch (error) {
        this.log(`Failed to remove obsolete workspace state file ${absolutePath}: ${error}`);
      }
    }
  }

  private getWorkspacePathMemoryContent(): string {
    return `# Workspace Path Memory

This file records descriptions of high-value file paths and their meanings to help the Agent run with long-term memory.

## High-Value Files

- \`TOPIC.md\`: The core research topic and goals for the current simulation experiment. Always read this file first to understand your mission.
- \`.agentsociety/agent_classes/*.json\`: JSON files containing detailed information about all supported agent classes, including their types and capabilities.
- \`.agentsociety/env_modules/*.json\`: JSON files containing detailed information about all supported environment modules that can be used to build simulation worlds.
- \`.agentsociety/prefill_params.json\`: Pre-filled parameters for modules to avoid repetitive input.

## Ignore Files

- \`papers/\`: The directory for storing literature search results or user-uploaded literature files. You SHOULD NOT read this directory directly, but use the \`load_literature\` tool to load the literature files.

## Progressive Context Loading

Instead of using specialized discovery tools, you should:
1. Read \`.agentsociety/path.md\` to understand the workspace structure.
2. List these directories to see available components.
3. Read specific JSON files as needed to gather detailed information about agent classes or environment modules.

## Custom Modules

- \`custom/agents/\`: Custom agent classes created by the user.
- \`custom/envs/\`: Custom environment modules created by the user.
`;
  }

  /**
   * Dispose
   */
  dispose(): void {
  }
}
