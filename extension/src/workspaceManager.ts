/**
 * Workspace Manager - Local file operations
 *
 * Handles workspace file operations locally instead of using backend APIs.
 *
 * 关联文件：
 * - @extension/src/projectStructureProvider.ts - 树视图调用WorkspaceManager初始化工作区
 * - @extension/src/extension.ts - 主入口，创建WorkspaceManager实例
 * - @extension/skills/ - AgentSociety 内置 skills（插件侧只读展示，同时同步到 workspace/.claude/skills）
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

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

  constructor(context: vscode.ExtensionContext) {
    this.outputChannel = vscode.window.createOutputChannel('Workspace Manager');
    this.skillsSourcePath = path.join(context.extensionPath, 'skills');
  }

  private log(message: string): void {
    const timestamp = new Date().toISOString();
    this.outputChannel.appendLine(`[${timestamp}] ${message}`);
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

      // Create .agentsociety directory for internal state (prefill_params.json)
      const agentsocietyDir = path.join(workspacePath, '.agentsociety');
      if (!fs.existsSync(agentsocietyDir)) {
        fs.mkdirSync(agentsocietyDir, { recursive: true });
        filesCreated.push('.agentsociety/');
        this.log(`Created: ${agentsocietyDir}`);
      }

      // Create prefill_params.json file
      const prefillParamsPath = path.join(agentsocietyDir, 'prefill_params.json');
      if (!fs.existsSync(prefillParamsPath)) {
        const prefillParams = {
          version: '1.0',
          env_modules: {},
          agents: {}
        };
        fs.writeFileSync(prefillParamsPath, JSON.stringify(prefillParams, null, 2), 'utf-8');
        filesCreated.push('.agentsociety/prefill_params.json');
        this.log(`Created: ${prefillParamsPath}`);
      }

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
      }

      reportProgress('正在完成初始化...');

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
   * the workspace-local `.claude/skills/` directory.
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
   * Copy official Anthropic office skills (pdf, docx, xlsx, pptx)
   * from extension bundle to .claude/skills/
   *
   * This replaces MinerU with official Claude Code skills for document processing.
   * Skills are bundled with the extension for offline installation.
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
   * Recursively copy a directory tree.
   */
  private copyDirectoryRecursive(source: string, target: string): void {
    // Create target directory (recursive mkdir is idempotent)
    fs.mkdirSync(target, { recursive: true });

    for (const item of fs.readdirSync(source)) {
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
    const { exec } = require('child_process');
    const util = require('util');
    const execPromise = util.promisify(exec);

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
      const command = `"${pythonCmd}" -m agentsociety2.society.workspace init-custom --target-dir "${workspacePath}" --json`;

      this.log(`Executing: ${command}`);

      reportProgress('正在执行自定义模块初始化命令...');

      const { stdout, stderr } = await execPromise(
        command,
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
      '.claude/',
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
      const existingEntries = new Set(
        lines
          .map(l => l.trim())
          .filter(l => l && !l.startsWith('#'))
      );

      let modified = false;
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

  /**
   * Get CLAUDE.md content - AI Social Scientist workspace guide
   */
  private getClaudeMdContent(): string {
    return `# CLAUDE.md

This file provides guidance to Claude Code when working in this AI Social Scientist workspace.

**Research Context**: See \`TOPIC.md\` for research topics, goals, and current work.

---

## Python Environment

**CRITICAL**: All skills require \`agentsociety2\` to be installed in the Python environment.

### Finding the Correct Python

The workspace \`.env\` file contains \`PYTHON_PATH\` pointing to the Python environment with agentsociety2 installed:

\`\`\`bash
# Read PYTHON_PATH from .env (with fallback to python3)
PYTHON_PATH=$(grep "^PYTHON_PATH=" .env | cut -d'=' -f2)
PYTHON_PATH=\${PYTHON_PATH:-python3}
\`\`\`

### Why PYTHON_PATH Matters

- Dependencies are managed via \`uv\`, not system Python
- Skills auto-load \`.env\` but use the calling Python interpreter
- Always use \`$PYTHON_PATH\` to ensure agentsociety2 is available

---

## Research Workflow (Execution Order)

Follow this sequence for social science research:

\`\`\`
1. Define Research Topic (TOPIC.md)
   └─> Define research question and objectives

2. Literature Review
   └─> agentsociety-literature-search
   └─> agentsociety-web-research

3. Dataset Exploration (optional but recommended)
   └─> agentsociety-use-dataset (list → search → readme → download)

4. Generate Hypothesis
   └─> agentsociety-hypothesis add

5. Initialize Experiment
   └─> agentsociety-experiment-config (validate → prepare → info → run → check, supports questionnaire steps)

6. Run Experiment
   └─> agentsociety-run-experiment start

7. Analyze Results
   └─> agentsociety-analysis

8. Generate Report
   └─> agentsociety-synthesize

9. Share Dataset (optional)
   └─> agentsociety-create-dataset (init → validate → pack → upload)

10. Refine Hypothesis/Experiment
   └─> Repeat from step 3 with new insights
\`\`\`

---

## Workspace Structure

\`\`\`
.
├── TOPIC.md              # Research topic and goals
├── CLAUDE.md             # This file - technical guidance
├── AGENTS.md             # Symlink to CLAUDE.md
├── .claude/              # Claude Code workspace resources
│   └── skills/           # Synced AgentSociety skills for Claude Code
├── .env                  # Environment configuration (API keys, PYTHON_PATH, etc)
├── papers/               # Literature storage
│   ├── literature_index.json  # Literature catalog
│   └── literature/            # Individual article summaries
├── user_data/            # User data storage for custom datasets
├── datasets/             # Downloaded datasets from the platform
│   └── {dataset_id}/     # Each dataset has its own directory
│       ├── metadata.json # Dataset metadata (name, version, category, etc.)
│       ├── README.md     # Dataset description and usage guide
│       └── data/         # Actual data files
├── custom/               # Custom Agent and Environment modules
│   ├── agents/               # Custom agent definitions
│   │   └── examples/         # Example agents (reference only)
│   ├── envs/                 # Custom environment modules
│   │   └── examples/         # Example environments (reference only)
│   └── README.md             # Custom module development guide
├── .agentsociety/        # Internal workspace state
│   └── prefill_params.json  # Pre-filled parameters for modules
├── hypothesis_{id}/      # Hypothesis directories
│   ├── HYPOTHESIS.md         # Hypothesis description and groups
│   ├── SIM_SETTINGS.json     # Agent and env module selection
│   └── experiment_{id}/
│       ├── EXPERIMENT.md     # Experiment description
│       ├── init/             # Configuration files (simplified)
│       │   ├── config_params.py  # Parameter generation script
│       │   ├── init_config.json  # Experiment configuration
│       │   └── steps.yaml        # Execution steps
│       ├── run/              # Simulation outputs
│       │   ├── sqlite.db         # Simulation database
│       │   ├── stdout.log        # Standard output
│       │   ├── stderr.log        # Error messages
│       │   └── pid.json          # Process ID file (when running)
│       └── data/             # Analysis results
│           ├── analysis_summary.json
│           ├── report.md
│           └── figures/
├── presentation/         # Experiment analysis reports
│   └── hypothesis_{id}/
│       └── experiment_{id}/
│           ├── synthesis_report_zh.md
│           └── synthesis_report_en.md
└── synthesis/            # Comprehensive synthesis reports
    ├── synthesis_report_YYYYMMDD_zh.md
    ├── synthesis_report_YYYYMMDD_en.md
    ├── synthesis_report_YYYYMMDD_zh.html
    └── synthesis_report_YYYYMMDD_en.html
\`\`\`

### Directory Notes

- **custom/** - Create your custom Agent and Environment modules here. See \`custom/README.md\` for development guide.
- **user_data/** - Store your custom datasets and data files here for experiment configuration.
- **datasets/** - Downloaded datasets from the AgentSociety platform. Managed by \`agentsociety-use-dataset\`.
- **.agentsociety/** - Internal workspace state, managed by the system.
- **Claude Code conversations** - Stored outside the workspace at \`~/.claude/projects/<workspace-path-encoded>/\`. The workspace exporter includes the matching directory when it exists.

---

## User Dialogue Style

When interacting with users:

### 1. Academic Tone
- Use academic terminology and maintain professionalism
- Be precise with terminology
- Acknowledge uncertainty and limitations

### 2. Language Matching
- Match the user's language (Chinese or English)
- Maintain consistency throughout the conversation

### 3. Guidance Flow
- Proactively guide users to the next step
- After completing a step, suggest the next action
- Explain the current step's position in the overall research workflow
- Provide optional research paths

### 4. Ask Questions
- Frequently ask questions to clarify user requirements:
- "Which specific research direction are you interested in?"
- "What is the theoretical basis for this hypothesis?"
- "What results do you expect to observe?"
- "How many agents should participate in the experiment?"

---

## Quick Skill Reference

| Skill | Purpose | Example |
|-------|---------|---------|
| \`agentsociety-scan-modules\` | List available agents/envs | \`list --short\` |
| \`agentsociety-hypothesis\` | Manage hypotheses | \`add\`, \`list\`, \`get\` |
| \`agentsociety-experiment-config\` | Generate experiment config, including questionnaire steps | \`validate\`, \`prepare\`, \`run\` |
| \`agentsociety-run-experiment\` | Execute simulations | \`start\`, \`status\`, \`stop\` |
| \`agentsociety-analysis\` | Analyze results | \`--hypothesis-id 1 --experiment-id 1\` |
| \`agentsociety-synthesize\` | Create reports | Bilingual synthesis |
| \`agentsociety-use-dataset\` | Browse & download datasets | \`list\`, \`search\`, \`download\` |
| \`agentsociety-create-dataset\` | Create & share datasets | \`init\`, \`validate\`, \`upload\` |

---

## Skills Notes

- Use the VSCode extension tree view to browse:
  - **Agent Skills** (backend-managed, supports import/reload)
  - **AgentSociety Skills** (extension bundled, read-only)
- Claude Code loads the synced workspace-local skill bundle from \`.claude/skills/\`
`;
  }

  /**
   * Dispose
   */
  dispose(): void {
    this.outputChannel.dispose();
  }
}
