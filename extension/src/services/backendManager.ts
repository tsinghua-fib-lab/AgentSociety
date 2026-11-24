/**
 * BackendManager - 后端服务管理器
 *
 * 负责启动、停止和管理 FastAPI 后端服务进程。
 * 支持自动启动、健康检查、进程状态管理和日志输出。
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，创建并管理BackendManager实例
 * - @extension/src/envManager.ts - 读取.env配置（Python路径、端口等）
 * - @extension/src/portUtils.ts - 动态端口分配工具
 *
 * 后端启动：
 * - @packages/agentsociety2/agentsociety2/backend/run.py - Python启动脚本
 * - @packages/agentsociety2/agentsociety2/backend/app.py - FastAPI应用
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { spawn, type ChildProcess, execSync } from 'child_process';
import { createInterface } from 'node:readline';
import { localize } from '../i18n';
import { EnvManager } from '../envManager';
import { findAvailablePort, isPortAvailable } from '../portUtils';
import { getBackendBindHost, getBackendPort } from '../runtimeConfig';
import { BackendAccessError, BackendService, type BackendStatus } from './backendService';
import {
  appendSharedOutputLine,
  getSharedOutputChannel,
  OUTPUT_CHANNEL_BACKEND,
} from '../shared/outputChannels';
import { formatDurationMs } from '../shared/formatDuration';
import {
  resolveAgentsocietyPython,
  pythonHasAgentsociety2,
  discoverPythonEnvironments,
  venvPythonIn,
  type PythonEnvironmentCandidate,
} from './agentsocietyPythonResolver';

export type { BackendStatus } from './backendService';

export interface BackendConfig {
  pythonPath: string;
  workingDirectory: string;
  autoStart: boolean;
  env: Record<string, string>;
}

export interface BackendOperationOptions {
  silent?: boolean;
}

export class BackendManager {
  private process: ChildProcess | null = null;
  private outputChannel: vscode.OutputChannel;
  private statusBarItem: vscode.StatusBarItem;
  private config: BackendConfig;
  private context: vscode.ExtensionContext;
  private healthCheckInterval: NodeJS.Timeout | null = null;
  private isStarting = false;
  private currentStatus: 'running' | 'stopped' | 'starting' | 'error' = 'stopped';
  private externalBackend = false;
  private runningSinceMs: number | null = null;
  private operationSilent = false;

  constructor(context: vscode.ExtensionContext, private readonly backend: BackendService) {
    this.context = context;
    this.outputChannel = getSharedOutputChannel(OUTPUT_CHANNEL_BACKEND);
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      100
    );
    this.statusBarItem.command = 'aiSocialScientist.backendStatusMenu';
    this.config = this.loadConfig({ fast: true });

    // 注意：不再监听 .env 文件变化来自动重启后端
    // 这是因为写入端口到 .env 会触发变化，导致死循环重启
    // 如需重启，用户应手动执行重启命令

    // 监听工作区文件夹变化（工作区切换时重新加载配置）
    context.subscriptions.push(
      vscode.workspace.onDidChangeWorkspaceFolders(() => {
        this.config = this.loadConfig();
        this.log('Workspace folders changed, configuration reloaded');
        // 如果服务正在运行，需要重启以应用新的工作目录
        if (this.process) {
          this.log('Workspace changed, restarting backend...');
          void this.restart();
        }
      })
    );

    context.subscriptions.push(this.statusBarItem);
    this.updateStatusBar('stopped');

    // 避免在构造阶段做 IO / 网络请求，延后到激活后的空闲时段执行
    setTimeout(() => {
      void this.checkAndCleanupOrphanedProcess().catch((error) => {
        this.log(`Failed to cleanup orphaned backend process: ${String(error)}`, 'warn');
      });
    }, 2000);
  }

  private reloadConfig(reason: string): void {
    this.config = this.loadConfig();
    this.log(`Configuration reloaded: ${reason}`);
  }

  /**
   * 检查并清理孤立的后端进程
   * 如果.env中记录的PID对应的进程不存在，则清理记录
   */
  private async checkAndCleanupOrphanedProcess(): Promise<void> {
    if (this.process || this.isStarting) {
      return;
    }
    const envManager = new EnvManager();
    const workspacePath = envManager.getWorkspacePath();
    const pid = envManager.readEnv().backendPid;
    if (!pid || !Number.isInteger(pid) || pid < 1) {
      return;
    }
    try {
      process.kill(pid, 0);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ESRCH') {
        this.log(`Orphaned backend PID ${pid} found, cleaning up...`);
        this.cleanupBackendEnv(workspacePath, pid);
      }
      return;
    }

    let status = await this.backend.getStatus();
    if (!status.isRunning && !status.error) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      status = await this.backend.getStatus();
    }
    if (this.process || this.isStarting || envManager.getWorkspacePath() !== workspacePath) {
      return;
    }
    if (status.isRunning) {
      this.log(`Existing backend process found (PID: ${pid}, Port: ${status.port})`);
      this.externalBackend = true;
      this.updateStatusBar('running', status.port);
      this.startHealthCheck();
    } else if (status.error) {
      // An authorization failure is not evidence that the process has exited.
      this.log(status.error, 'warn');
      this.updateStatusBar('error', status.port, status.error);
    }
  }

  private log(message: string, level: 'info' | 'error' | 'warn' = 'info'): void {
    const timestamp = new Date().toISOString();
    const prefix = level === 'error' ? '[ERROR]' : level === 'warn' ? '[WARN]' : '[INFO]';
    appendSharedOutputLine(OUTPUT_CHANNEL_BACKEND, `[${timestamp}] ${prefix} ${message}`);
  }

  /**
   * 显示配置错误消息，并提供打开 .env 文件的选项
   */
  private async showConfigError(message: string): Promise<void> {
    if (this.operationSilent) {
      return;
    }
    const openConfigLabel = localize('backendManager.openSettings');
    const result = await vscode.window.showErrorMessage(message, openConfigLabel);
    if (result === openConfigLabel) {
      await vscode.commands.executeCommand('aiSocialScientist.openConfigPage');
    }
  }

  private notifyError(message: string): void {
    if (this.operationSilent) {
      return;
    }
    void vscode.window.showErrorMessage(message);
  }

  private notifyWarning(message: string): void {
    if (this.operationSilent) {
      return;
    }
    void vscode.window.showWarningMessage(message);
  }

  private formatPythonPickLabel(item: PythonEnvironmentCandidate): string {
    const source = localize(`pythonEnvironment.sources.${item.source}`);
    const versionBits = [
      item.pythonVersion ? `Python ${item.pythonVersion}` : null,
      item.as2Version ? `agentsociety2 ${item.as2Version}` : null,
    ].filter(Boolean);
    const detail = versionBits.length > 0 ? versionBits.join(' · ') : localize('pythonEnvironment.compatible');
    return `${source} — ${detail}`;
  }

  private async promptPythonEnvironmentSelection(): Promise<string | null> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const envManager = new EnvManager();
    const envConfig = envManager.readEnv();
    const environments = discoverPythonEnvironments({
      configuredPath: envConfig.pythonPath,
      workspacePath: workspaceFolder?.uri.fsPath,
      extensionPath: this.context.extensionPath,
    });
    const compatible = environments.filter((item) => item.compatible);
    if (compatible.length === 0) {
      await vscode.commands.executeCommand('aiSocialScientist.openConfigPage');
      const { ConfigPageViewProvider } = await import('../configPageViewProvider');
      ConfigPageViewProvider.currentPanel?.navigateToAdvancedTab('python');
      await this.showConfigError(localize('backendManager.pythonNotFound'));
      return null;
    }
    if (compatible.length === 1) {
      return compatible[0].path;
    }
    const pick = await vscode.window.showQuickPick(
      compatible.map((item) => ({
        label: this.formatPythonPickLabel(item),
        description: item.path,
        detail: localize('pythonEnvironment.compatible'),
        path: item.path,
      })),
      {
        title: localize('backendManager.pythonPickTitle'),
        placeHolder: localize('backendManager.pythonPickPlaceholder'),
        matchOnDescription: true,
        matchOnDetail: true,
      }
    );
    return pick?.path ?? null;
  }

  private async ensureCompatiblePython(): Promise<boolean> {
    if (pythonHasAgentsociety2(this.config.pythonPath)) {
      return true;
    }
    // 2026-11-06 体验审查 #16:silent 模式(autoStart 激活自启)不得弹
    // 交互——激活瞬间冒出 QuickPick 会非常突兀;记日志留给用户主动处理。
    if (this.operationSilent) {
      this.log(
        `Python at ${this.config.pythonPath} lacks agentsociety2; skipping interactive selection in silent mode`,
        'warn'
      );
      this.isStarting = false;
      this.updateStatusBar('error');
      return false;
    }
    const selected = await this.promptPythonEnvironmentSelection();
    if (!selected) {
      this.isStarting = false;
      this.updateStatusBar('error');
      return false;
    }
    this.config.pythonPath = selected;
    const envManager = new EnvManager();
    envManager.writeEnv({ pythonPath: selected });
    this.log(`Using Python environment: ${selected}`);
    return true;
  }

  /**
   * 加载配置并映射为环境变量
   *
   * 仅从 .env 文件加载配置
   */
  private loadConfig(options?: { fast?: boolean }): BackendConfig {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      // 没有工作区时返回一个默认配置，不抛出错误
      this.log('No workspace folder found, using default configuration');
      return {
        pythonPath: this.detectPythonPath(),
        workingDirectory: '',
        autoStart: false,  // 没有工作区时不自动启动
        env: {}
      };
    }
    const workingDirectory = workspaceFolder.uri.fsPath;

    // 从 .env 文件加载配置
    const envManager = new EnvManager();
    const envConfig = envManager.readEnv();

    const configuredPython = envConfig.pythonPath?.trim();
    let pythonPath: string;
    if (options?.fast) {
      pythonPath =
        configuredPython ||
        venvPythonIn(workingDirectory) ||
        this.detectPythonPath();
    } else {
      const resolvedPython = resolveAgentsocietyPython({
        configuredPath: envConfig.pythonPath,
        workspacePath: workingDirectory,
        extensionPath: this.context.extensionPath,
      });
      pythonPath = configuredPython || resolvedPython || this.detectPythonPath();
      if (configuredPython && !pythonHasAgentsociety2(configuredPython) && resolvedPython) {
        this.log(
          `Configured PYTHON_PATH is incompatible (${configuredPython}); falling back to ${resolvedPython}`,
          'warn'
        );
        pythonPath = resolvedPython;
      } else if (configuredPython && !pythonHasAgentsociety2(configuredPython)) {
        pythonPath = configuredPython;
      }
    }

    // 映射环境变量
    const env: Record<string, string> = {};

    // 后端服务配置
    env.BACKEND_HOST = getBackendBindHost(envConfig);
    env.BACKEND_PORT = String(getBackendPort(envConfig));
    env.BACKEND_LOG_LEVEL = envConfig.backendLogLevel || 'info';
    env.PYTHON_PATH = envConfig.pythonPath || '';

    // 基础配置 - 始终使用工作区相对路径
    // AGENTSOCIETY_HOME_DIR 相对于工作区根目录
    env.AGENTSOCIETY_HOME_DIR = path.join(workspaceFolder.uri.fsPath, 'agentsociety_data');
    // WORKSPACE_PATH 用于自定义模块扫描等需要工作区路径的后端接口
    env.WORKSPACE_PATH = workspaceFolder.uri.fsPath;

    // LLM 配置
    if (envConfig.llmApiKey) { env.AGENTSOCIETY_LLM_API_KEY = envConfig.llmApiKey; }
    if (envConfig.llmApiBase) { env.AGENTSOCIETY_LLM_API_BASE = envConfig.llmApiBase; }
    if (envConfig.llmModel) { env.AGENTSOCIETY_LLM_MODEL = envConfig.llmModel; }

    // 显式空值覆盖父进程同名变量，避免清空设置后仍沿用旧的推理开关。
    if (envConfig.llmApiType !== undefined) { env.AGENTSOCIETY_LLM_API_TYPE = envConfig.llmApiType; }
    if (envConfig.llmThinkingFormat !== undefined) { env.AGENTSOCIETY_LLM_THINKING_FORMAT = envConfig.llmThinkingFormat; }
    if (envConfig.llmThinking !== undefined) { env.AGENTSOCIETY_LLM_THINKING = envConfig.llmThinking; }
    if (envConfig.llmReasoningEffort !== undefined) { env.AGENTSOCIETY_LLM_REASONING_EFFORT = envConfig.llmReasoningEffort; }
    if (envConfig.llmExtraBody !== undefined) { env.AGENTSOCIETY_LLM_EXTRA_BODY = envConfig.llmExtraBody; }

    // Coder LLM 配置
    if (envConfig.coderLlmApiKey) { env.AGENTSOCIETY_CODER_LLM_API_KEY = envConfig.coderLlmApiKey; }
    if (envConfig.coderLlmApiBase) { env.AGENTSOCIETY_CODER_LLM_API_BASE = envConfig.coderLlmApiBase; }
    if (envConfig.coderLlmModel) { env.AGENTSOCIETY_CODER_LLM_MODEL = envConfig.coderLlmModel; }
    if (envConfig.coderLlmApiType !== undefined) { env.AGENTSOCIETY_CODER_LLM_API_TYPE = envConfig.coderLlmApiType; }
    if (envConfig.coderLlmThinkingFormat !== undefined) { env.AGENTSOCIETY_CODER_LLM_THINKING_FORMAT = envConfig.coderLlmThinkingFormat; }
    if (envConfig.coderLlmThinking !== undefined) { env.AGENTSOCIETY_CODER_LLM_THINKING = envConfig.coderLlmThinking; }
    if (envConfig.coderLlmReasoningEffort !== undefined) { env.AGENTSOCIETY_CODER_LLM_REASONING_EFFORT = envConfig.coderLlmReasoningEffort; }
    if (envConfig.coderLlmExtraBody !== undefined) { env.AGENTSOCIETY_CODER_LLM_EXTRA_BODY = envConfig.coderLlmExtraBody; }

    // Embedding 配置
    if (envConfig.embeddingApiKey) { env.AGENTSOCIETY_EMBEDDING_API_KEY = envConfig.embeddingApiKey; }
    if (envConfig.embeddingApiBase) { env.AGENTSOCIETY_EMBEDDING_API_BASE = envConfig.embeddingApiBase; }
    if (envConfig.embeddingModel) { env.AGENTSOCIETY_EMBEDDING_MODEL = envConfig.embeddingModel; }
    if (envConfig.embeddingDims) { env.AGENTSOCIETY_EMBEDDING_DIMS = String(envConfig.embeddingDims); }

    // Literature Search 配置
    if (envConfig.literatureSearchMcpUrl) { env.LITERATURE_SEARCH_MCP_URL = envConfig.literatureSearchMcpUrl; }
    if (envConfig.literatureSearchApiKey) { env.LITERATURE_SEARCH_API_KEY = envConfig.literatureSearchApiKey; }

    return {
      pythonPath,
      workingDirectory,
      autoStart: false,  // 默认不自动启动
      env,
    };
  }

  /**
   * 检测 Python 可执行文件路径
   */
  private detectPythonPath(): string {
    // 尝试常见的 Python 命令
    const candidates = ['python3', 'python', 'py'];
    for (const cmd of candidates) {
      try {
        // 使用 which/where 命令检测（Windows 使用 where，Unix 使用 which）
        const isWindows = process.platform === 'win32';
        const checkCommand = isWindows ? `where ${cmd}` : `which ${cmd}`;
        execSync(checkCommand, { stdio: 'ignore' });
        return cmd;
      } catch {
        // 继续尝试下一个
      }
    }
    // 如果都找不到，返回 python3 作为默认值
    return 'python3';
  }

  /**
   * 更新状态栏
   * @param status 状态类型
   * @param port 可选的端口号，运行状态时显示
   */
  private updateStatusBar(status: 'running' | 'stopped' | 'starting' | 'error', port?: number, error?: string): void {
    this.currentStatus = status;
    const effectivePort = port;

    switch (status) {
      case 'running': {
        if (this.runningSinceMs === null) {
          this.runningSinceMs = Date.now();
        }
        const uptime =
          this.runningSinceMs !== null
            ? formatDurationMs(Date.now() - this.runningSinceMs)
            : '';
        this.statusBarItem.text = `$(server) :${effectivePort ?? ''}`;
        const runningTooltip = new vscode.MarkdownString();
        runningTooltip.appendMarkdown(`${localize('backendManager.statusBar.runningShort', String(effectivePort ?? '?'))}\n\n`);
        if (uptime) {
          runningTooltip.appendMarkdown(`${localize('backendManager.statusBar.uptime', uptime)}\n`);
        }
        const backendUrl = this.getBackendUrl();
        if (backendUrl) {
          runningTooltip.appendMarkdown(`\`${backendUrl}\``);
        }
        this.statusBarItem.tooltip = runningTooltip;
        this.statusBarItem.backgroundColor = undefined;
        this.statusBarItem.show();
        break;
      }
      case 'starting':
        this.runningSinceMs = null;
        this.statusBarItem.text = '$(sync~spin)';
        this.statusBarItem.tooltip = localize('backendManager.statusBar.startingTooltip');
        this.statusBarItem.backgroundColor = undefined;
        this.statusBarItem.show();
        break;
      case 'error':
        this.runningSinceMs = null;
        this.statusBarItem.text = '$(error)';
        this.statusBarItem.tooltip = error ?? localize('backendManager.statusBar.errorTooltip');
        this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
        this.statusBarItem.show();
        break;
      case 'stopped':
        this.runningSinceMs = null;
        this.statusBarItem.text = '$(circle-slash)';
        this.statusBarItem.tooltip = localize('backendManager.statusBar.stoppedTooltip');
        this.statusBarItem.backgroundColor = undefined;
        this.statusBarItem.show();
        break;
    }

    if (status === 'running' || status === 'stopped' || error) {
      void import('../configPageViewProvider').then(({ ConfigPageViewProvider }) => {
        ConfigPageViewProvider.refreshBackendStatusIfOpen();
      });
    }
  }

  /**
   * 启动后端服务
   */
  async start(options?: BackendOperationOptions): Promise<boolean> {
    if (this.isStarting) {
      this.log('Backend is already starting...', 'warn');
      return false;
    }
    this.isStarting = true;
    this.operationSilent = options?.silent ?? false;
    let startedProcess: ChildProcess | undefined;
    let backendToken = '';
    const redactToken = (message: string): string => backendToken
      ? message.split(backendToken).join('[REDACTED]')
      : message;
    const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    try {
      const backendEnv = this.backend.readConfiguredEnv();
      const status = await this.backend.getStartupStatus(backendEnv);
      if (workspacePath !== vscode.workspace.workspaceFolders?.[0]?.uri.fsPath) {
        throw new BackendAccessError(localize('backendManager.workspaceChanged'));
      }
      this.externalBackend = !this.process && status.isRunning;
      if (status.isRunning) {
        this.log('Backend is already running', 'warn');
        this.updateStatusBar('running', status.port);
        this.startHealthCheck();
        return true;
      }
      if (status.error) {
        throw new BackendAccessError(status.error);
      }
      if (this.process) {
        throw new Error(localize('backendManager.processNotReady'));
      }
      if (backendEnv.backendUrl?.trim() || (backendEnv.backendToken?.trim() && backendEnv.backendTokenOrigin !== undefined)) {
        throw new BackendAccessError(localize('backendRequest.externalUnavailable'));
      }

      this.reloadConfig('before start');
      this.updateStatusBar('starting');

      // 验证 Python 路径
      if (!this.config.pythonPath) {
        const errorMessage = `${localize('backendManager.configInsufficient')}: ${localize('backendManager.pythonPathMissing')}`;
        this.log(errorMessage, 'error');
        this.isStarting = false;
        this.updateStatusBar('error');
        await this.showConfigError(errorMessage);
        return false;
      }

      if (!(await this.ensureCompatiblePython())) {
        return false;
      }

      // 验证工作目录
      if (!workspacePath || !fs.existsSync(workspacePath)) {
        const errorMessage = localize('backendManager.workingDirectoryMissing', this.config.workingDirectory);
        this.log(errorMessage, 'error');
        this.isStarting = false;
        this.updateStatusBar('error');
        await this.showConfigError(errorMessage);
        return false;
      }

      // 验证必需的配置
      if (!this.config.env.AGENTSOCIETY_LLM_API_KEY) {
        const errorMessage = `${localize('backendManager.configInsufficient')}: ${localize('backendManager.llmKeyRequired')}`;
        this.log(errorMessage, 'error');
        this.isStarting = false;
        this.updateStatusBar('error');
        await this.showConfigError(errorMessage);
        return false;
      }

      // 分配动态端口
      this.log('Allocating available port...');
      const port = await this.allocatePort(getBackendPort(backendEnv));
      if (workspacePath !== vscode.workspace.workspaceFolders?.[0]?.uri.fsPath) {
        throw new BackendAccessError(localize('backendManager.workspaceChanged'));
      }
      this.log(`Allocated port: ${port}`);

      // Preserve inherited values, but don't add an empty override for Python's dotenv.
      backendToken = (process.env.BACKEND_TOKEN ?? backendEnv.backendToken)?.trim() ?? '';
      const env = {
        ...process.env,
        ...this.config.env,
        BACKEND_HOST: getBackendBindHost(backendEnv),
        BACKEND_PORT: String(port),
        ...(backendToken ? { BACKEND_TOKEN: backendToken } : {}),
        LITELLM_LOCAL_MODEL_COST_MAP: 'True',
      };
      const pinBackend = this.backend.prepareManagedBackend(env, workspacePath);
      this.writePortToEnv(port);

      this.log('Starting backend service...');
      this.log(`Python path: ${this.config.pythonPath}`);
      this.log(`Working directory: ${workspacePath}`);

      const args = ['-m', 'agentsociety2.backend.run'];
      this.process = startedProcess = spawn(this.config.pythonPath, args, {
        cwd: workspacePath,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      pinBackend();

      // Redact complete lines so a credential split across stream chunks is not logged.
      if (startedProcess.stdout) {
        createInterface({ input: startedProcess.stdout }).on('line', line => this.log(`[STDOUT] ${redactToken(line)}`));
      }
      if (startedProcess.stderr) {
        createInterface({ input: startedProcess.stderr }).on('line', line => this.log(`[STDERR] ${redactToken(line)}`, 'warn'));
      }

      // 处理进程退出
      startedProcess.on('exit', (code, signal) => {
        this.cleanupBackendEnv(workspacePath, startedProcess?.pid);
        if (this.process !== startedProcess) {
          return;
        }
        this.log(`Backend process exited with code ${code}, signal ${signal}`);
        this.stopHealthCheck();
        this.process = null;
        this.backend.clearManagedBackend();

        this.updateStatusBar('stopped');

        if (code !== 0 && code !== null) {
          this.updateStatusBar('error');
          void vscode.window.showErrorMessage(localize('backendManager.exitedWithCode', String(code)));
        }
      });

      // 处理进程错误
      startedProcess.on('error', async (error) => {
        this.cleanupBackendEnv(workspacePath, startedProcess?.pid);
        if (this.process !== startedProcess) {
          return;
        }
        this.log(`Failed to start backend: ${redactToken(error.message)}`, 'error');
        this.stopHealthCheck();
        this.process = null;
        this.backend.clearManagedBackend();

        this.updateStatusBar('error');

        const errorMessage = redactToken(error.message) || 'Unknown error';
        const isConfigError =
          errorMessage.includes('ENOENT') ||
          errorMessage.includes('spawn') ||
          errorMessage.includes('Python') ||
          errorMessage.includes('python');

        if (isConfigError) {
          await this.showConfigError(localize('backendManager.startFailed', errorMessage));
        } else {
          this.notifyError(localize('backendManager.startFailed', errorMessage));
        }
      });

      if (startedProcess.pid) {
        this.writePidToEnv(startedProcess.pid, workspacePath);
      }

      // 等待服务启动（最多等待30秒）
      const maxWaitTime = 30000;
      const checkInterval = 1000;
      let elapsed = 0;

      while (elapsed < maxWaitTime) {
        await new Promise((resolve) => setTimeout(resolve, checkInterval));
        elapsed += checkInterval;

        if (workspacePath !== vscode.workspace.workspaceFolders?.[0]?.uri.fsPath) {
          throw new BackendAccessError(localize('backendManager.workspaceChanged'));
        }
        if (this.process !== startedProcess || startedProcess.killed) {
          throw new Error('Backend process exited unexpectedly');
        }
        const status = await this.backend.getManagedStatus();
        if (workspacePath !== vscode.workspace.workspaceFolders?.[0]?.uri.fsPath) {
          throw new BackendAccessError(localize('backendManager.workspaceChanged'));
        }
        if (status.error) {
          throw new BackendAccessError(status.error);
        }
        if (status.isRunning && this.process === startedProcess && !startedProcess.killed) {
          this.log('Backend service started successfully');
          this.updateStatusBar('running', status.port);
          this.startHealthCheck();
          return true;
        }
      }

      throw new Error('Backend service failed to start within 30 seconds');
    } catch (error) {
      if (startedProcess && this.process === startedProcess) {
        await this.stop();
      } else if (!this.process) {
        this.backend.clearManagedBackend();
      }

      if (error instanceof BackendAccessError) {
        this.log(error.message, 'error');
        this.updateStatusBar('error', undefined, error.message);
        if (this.operationSilent) {
          throw error;
        }
        await this.showConfigError(error.message);
        return false;
      }

      const errorMessage = error instanceof Error ? redactToken(error.message) : 'Unknown error';
      this.log(`Failed to start backend: ${errorMessage}`, 'error');
      this.updateStatusBar('error');
      this.outputChannel.show(true);
      this.notifyError(localize('backendManager.startFailed', errorMessage));
      return false;
    } finally {
      this.isStarting = false;
      this.operationSilent = false;
    }
  }

  /**
   * 停止后端服务
   */
  async stop(): Promise<boolean> {
    if (!this.process) {
      if (this.externalBackend) {
        this.notifyWarning(localize('backendManager.externalStop'));
      } else {
        // 2026-11-06 体验审查 #6:此前只写 output 日志,用户点了
        // 命令毫无反应。给出可见反馈(backendManager 层,兼容
        // silent 模式——silent 下仍只记日志)。
        if (!this.operationSilent) {
          this.notifyWarning(localize('backendManager.notRunning'));
        } else {
          this.log('Backend is not running', 'warn');
        }
      }
      return false;
    }

    this.log('Stopping backend service...');
    this.updateStatusBar('stopped');

    // 停止健康检查
    this.stopHealthCheck();

    // 终止进程
    if (this.process.pid) {
      try {
        // 尝试优雅关闭
        process.kill(this.process.pid, 'SIGTERM');

        // 等待最多5秒
        await new Promise<void>((resolve) => {
          const timeout = setTimeout(() => {
            // 强制终止
            if (this.process?.pid) {
              process.kill(this.process.pid, 'SIGKILL');
            }
            resolve();
          }, 5000);

          this.process?.on('exit', () => {
            clearTimeout(timeout);
            resolve();
          });
        });
      } catch (error: any) {
        this.log(`Error stopping backend: ${error.message}`, 'error');
        // 强制终止
        if (this.process?.pid) {
          try {
            process.kill(this.process.pid, 'SIGKILL');
          } catch {
            // 忽略错误
          }
        }
      }
    }

    this.process = null;
    this.backend.clearManagedBackend();
    this.externalBackend = false;

    this.log('Backend service stopped');
    return true;
  }

  /**
   * 重启后端服务
   */
  async restart(options?: BackendOperationOptions): Promise<boolean> {
    this.log('Restarting backend service...');
    if (!this.process && this.externalBackend) {
      this.notifyWarning(localize('backendManager.externalRestart'));
      return false;
    }
    await this.stop();
    await new Promise((resolve) => setTimeout(resolve, 1000));
    return await this.start(options);
  }

  /**
   * 启动定期健康检查
   */
  private startHealthCheck(): void {
    this.stopHealthCheck(); // 确保没有重复的检查

    const interval = setInterval(async () => {
      const status = await this.backend.getStatus();
      if (this.healthCheckInterval !== interval) {
        return;
      }
      if (status.error) {
        if (this.currentStatus !== 'error') {
          this.log(status.error, 'warn');
          this.updateStatusBar('error', status.port, status.error);
        }
      } else if (status.isRunning) {
        this.externalBackend = !this.process;
        this.updateStatusBar('running', status.port);
      } else if (this.process && !this.process.killed) {
        this.log('Health check failed, but process is still running', 'warn');
      } else {
        this.externalBackend = false;
        this.updateStatusBar('stopped');
        this.stopHealthCheck();
      }
    }, 10000);
    this.healthCheckInterval = interval;
  }

  /**
   * 停止定期健康检查
   */
  private stopHealthCheck(): void {
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval);
      this.healthCheckInterval = null;
    }
  }

  /**
   * 分配可用端口
   * 首先检查.env文件中配置的端口是否可用，如果不可用则随机分配新端口
   */
  private async allocatePort(configuredPort: number): Promise<number> {
    // 首先检查配置的端口是否可用
    if (await isPortAvailable(configuredPort)) {
      this.log(`Configured port ${configuredPort} is available`);
      return configuredPort;
    }

    // 配置的端口不可用，查找可用端口
    this.log(`Configured port ${configuredPort} is not available, finding alternative...`);
    const newPort = await findAvailablePort();
    this.log(`Found available port: ${newPort}`);
    return newPort;
  }

  /**
   * 将分配的端口写入.env文件
   */
  private writePortToEnv(port: number): void {
    const envManager = new EnvManager();
    envManager.writeEnv({ backendPort: port });
    this.log(`Wrote port ${port} to .env file`);
  }

  /**
   * 将后端进程PID写入.env文件用于生命周期追踪
   */
  private writePidToEnv(pid: number, workspacePath: string): void {
    const envPath = path.join(workspacePath, '.env');

    // 读取现有.env内容，移除末尾空行
    let content = '';
    if (fs.existsSync(envPath)) {
      content = fs.readFileSync(envPath, 'utf-8').trimEnd();
    }

    // 添加或更新BACKEND_PID
    const lines = content.split('\n');
    let pidUpdated = false;
    const newLines: string[] = [];

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('BACKEND_PID=')) {
        newLines.push(`BACKEND_PID=${pid}`);
        pidUpdated = true;
      } else {
        newLines.push(line);
      }
    }

    if (!pidUpdated) {
      newLines.push(`BACKEND_PID=${pid}`);
    }

    fs.writeFileSync(envPath, newLines.join('\n') + '\n', 'utf-8');
    this.log(`Wrote PID ${pid} to .env file`);
  }

  /** Clear only the PID we were tracking, in the workspace that owns it. */
  private cleanupBackendEnv(workspacePath: string | null, pid?: number): void {
    if (!workspacePath || !pid) {
      return;
    }

    const envPath = path.join(workspacePath, '.env');
    if (!fs.existsSync(envPath)) {
      return;
    }

    // 移除末尾空行
    const content = fs.readFileSync(envPath, 'utf-8').trimEnd();
    const lines = content.split('\n');
    const newLines: string[] = [];

    for (const line of lines) {
      const trimmed = line.trim();
      // 移除BACKEND_PID行
      if (trimmed === `BACKEND_PID=${pid}`) {
        continue;
      }
      newLines.push(line);
    }

    if (lines.length === newLines.length) {
      return;
    }
    // 只在有内容时写入，并添加末尾换行符
    if (newLines.length > 0) {
      fs.writeFileSync(envPath, newLines.join('\n') + '\n', 'utf-8');
    } else {
      fs.writeFileSync(envPath, '', 'utf-8');
    }
    this.log('Cleaned up backend fields from .env file');
  }

  /**
   * 检查.env文件中的后端进程是否仍在运行
   * 用于生命周期管理
   */
  async checkBackendProcessByEnv(): Promise<boolean> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      return false;
    }

    const envPath = path.join(workspaceFolder.uri.fsPath, '.env');
    if (!fs.existsSync(envPath)) {
      return false;
    }

    const content = fs.readFileSync(envPath, 'utf-8');
    const lines = content.split('\n');

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('BACKEND_PID=')) {
        const match = trimmed.match(/^BACKEND_PID=(\d+)/);
        if (match) {
          const pid = parseInt(match[1], 10);
          try {
            // 检查进程是否存在
            process.kill(pid, 0);
            this.log(`Backend process with PID ${pid} is still running`);
            return true;
          } catch {
            this.log(`Backend process with PID ${pid} is no longer running`);
            return false;
          }
        }
      }
    }

    return false;
  }

  /**
   * 获取后端状态
   */
  async getStatus(): Promise<BackendStatus> {
    const status = await this.backend.getStatus();
    this.externalBackend = !this.process && status.isRunning;
    if (status.isRunning && !this.isStarting) {
      this.currentStatus = 'running';
    }
    // Status reads must not notify the config page: its refresh reads this method again.
    return { ...status, pid: this.process?.pid };
  }

  /**
   * 获取后端 URL
   */
  getBackendUrl(): string | null {
    if (this.currentStatus !== 'running') {
      return null;
    }
    try {
      return this.backend.getBaseUrl();
    } catch {
      return null;
    }
  }

  /**
   * 获取当前状态
   */
  getCurrentStatus(): 'running' | 'stopped' | 'starting' | 'error' {
    return this.currentStatus;
  }

  /**
   * 复制后端 URL 到剪贴板
   */
  async copyBackendUrl(): Promise<boolean> {
    const url = this.getBackendUrl();
    if (!url) {
      vscode.window.showWarningMessage(localize('extension.backend.statusOff'));
      return false;
    }
    await vscode.env.clipboard.writeText(url);
    vscode.window.showInformationMessage(localize('backendManager.statusBar.urlCopied', url));
    return true;
  }

  /**
   * 在浏览器中打开后端 URL
   */
  async openInBrowser(): Promise<boolean> {
    return this.openBackendPage('');
  }

  /**
   * 在浏览器中打开 API 文档
   */
  async openApiDocs(): Promise<boolean> {
    return this.openBackendPage('/docs');
  }

  private async openBackendPage(pathname: '' | '/docs'): Promise<boolean> {
    let url: string | undefined;
    try {
      url = await this.backend.getBrowserUrl();
    } catch (error) {
      if (!(error instanceof BackendAccessError)) {
        throw error;
      }
      void vscode.window.showWarningMessage(error.message);
      return false;
    }
    if (!url) {
      void vscode.window.showWarningMessage(localize('extension.backend.statusOff'));
      return false;
    }
    const target = vscode.Uri.parse(`${url}${pathname}`);
    if (vscode.env.uiKind === vscode.UIKind.Web) {
      // Coder 将本地端口映射到代理根路径，需在映射后拼回 API 路径。
      const proxy = await vscode.env.asExternalUri(target.with({ path: '/' }));
      return vscode.env.openExternal(proxy.with({ path: proxy.path.replace(/\/$/, '') + (target.path || '/') }));
    }
    return vscode.env.openExternal(target);
  }

  /**
   * 显示日志输出面板
   */
  showLogs(): void {
    this.outputChannel.show();
  }

  /**
   * 清理资源
   */
  dispose(): void {
    this.stopHealthCheck();
    this.stop();
    this.statusBarItem.dispose();
  }
}
