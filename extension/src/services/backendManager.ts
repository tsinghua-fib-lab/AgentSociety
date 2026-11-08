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
import { spawn, ChildProcess, execSync } from 'child_process';
import { localize } from '../i18n';
import { EnvManager } from '../envManager';
import { findAvailablePort, isPortAvailable } from '../portUtils';
import { getBackendAccessUrl, getBackendBindHost, getBackendPort } from '../runtimeConfig';
import { fetchCompat } from '../shared/fetchCompat';
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

const fetch = fetchCompat as unknown as typeof globalThis.fetch;

export interface BackendStatus {
  isRunning: boolean;
  pid?: number;
  port?: number;
  error?: string;
}

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
  private allocatedPort: number | null = null; // Track dynamically allocated port
  private currentStatus: 'running' | 'stopped' | 'starting' | 'error' = 'stopped';
  private externalBackend = false;
  private runningSinceMs: number | null = null;
  private operationSilent = false;

  constructor(context: vscode.ExtensionContext) {
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
          this.restart();
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
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      return;
    }

    const envPath = path.join(workspaceFolder.uri.fsPath, '.env');
    if (!fs.existsSync(envPath)) {
      return;
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
            // 进程存在，尝试进行健康检查
            const envManager = new EnvManager();
            const envConfig = envManager.readEnv();
            const port = getBackendPort(envConfig);
            const backendUrl = getBackendAccessUrl(envConfig);

            try {
              const response = await fetch(`${backendUrl}/health`, {
                method: 'GET',
                signal: AbortSignal.timeout(3000),
              });
              if (response.ok) {
                this.log(`Existing backend process found (PID: ${pid}, Port: ${port})`);
                this.allocatedPort = port;
                this.externalBackend = true;
                this.currentStatus = 'running';
                this.updateStatusBar('running', port);
                this.startHealthCheck();
              } else {
                this.log(`Backend process (PID: ${pid}) exists but health check returned non-OK, cleaning up...`);
                this.cleanupBackendEnv();
              }
            } catch {
              // 健康检查失败可能是后端正在启动中，等待 2 秒重试一次
              this.log(`Backend health check failed (PID: ${pid}), retrying in 2s...`);
              await new Promise(resolve => setTimeout(resolve, 2000));
              try {
                const retryResponse = await fetch(`${backendUrl}/health`, {
                  method: 'GET',
                  signal: AbortSignal.timeout(3000),
                });
                if (retryResponse.ok) {
                  this.log(`Backend process recovered (PID: ${pid}, Port: ${port})`);
                  this.allocatedPort = port;
                  this.externalBackend = true;
                  this.currentStatus = 'running';
                  this.updateStatusBar('running', port);
                  this.startHealthCheck();
                } else {
                  this.log(`Backend process (PID: ${pid}) still unhealthy after retry, cleaning up...`);
                  this.cleanupBackendEnv();
                }
              } catch {
                this.log(`Cannot connect to backend (PID: ${pid}) after retry, cleaning up...`);
                this.cleanupBackendEnv();
              }
            }
          } catch {
            // 进程不存在，清理记录
            this.log(`Orphaned backend PID ${pid} found, cleaning up...`);
            this.cleanupBackendEnv();
          }
        }
        break;
      }
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

    // 推理（thinking）开关 - 空值即「未设置」，不注入，保持后端默认行为
    if (envConfig.llmThinking) { env.AGENTSOCIETY_LLM_THINKING = envConfig.llmThinking; }
    if (envConfig.llmReasoningEffort) { env.AGENTSOCIETY_LLM_REASONING_EFFORT = envConfig.llmReasoningEffort; }
    if (envConfig.llmExtraBody) { env.AGENTSOCIETY_LLM_EXTRA_BODY = envConfig.llmExtraBody; }

    // Coder LLM 配置
    if (envConfig.coderLlmApiKey) { env.AGENTSOCIETY_CODER_LLM_API_KEY = envConfig.coderLlmApiKey; }
    if (envConfig.coderLlmApiBase) { env.AGENTSOCIETY_CODER_LLM_API_BASE = envConfig.coderLlmApiBase; }
    if (envConfig.coderLlmModel) { env.AGENTSOCIETY_CODER_LLM_MODEL = envConfig.coderLlmModel; }
    if (envConfig.coderLlmThinking) { env.AGENTSOCIETY_CODER_LLM_THINKING = envConfig.coderLlmThinking; }
    if (envConfig.coderLlmReasoningEffort) { env.AGENTSOCIETY_CODER_LLM_REASONING_EFFORT = envConfig.coderLlmReasoningEffort; }
    if (envConfig.coderLlmExtraBody) { env.AGENTSOCIETY_CODER_LLM_EXTRA_BODY = envConfig.coderLlmExtraBody; }

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
  private updateStatusBar(status: 'running' | 'stopped' | 'starting' | 'error', port?: number): void {
    this.currentStatus = status;
    const effectivePort = port ?? this.allocatedPort;
    const backendUrl = effectivePort ? `http://localhost:${effectivePort}` : '';

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
        runningTooltip.appendMarkdown(`\`${backendUrl}\``);
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
        this.statusBarItem.tooltip = localize('backendManager.statusBar.errorTooltip');
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

    if (status === 'running' || status === 'stopped') {
      void import('../configPageViewProvider').then(({ ConfigPageViewProvider }) => {
        ConfigPageViewProvider.refreshBackendStatusIfOpen();
      });
    }
  }

  /**
   * 检查后端服务是否正在运行
   */
  async isRunning(): Promise<boolean> {
    if (!this.process || this.process.killed) {
      return (await this.getStatus()).isRunning;
    }

    // 检查进程是否还在运行
    try {
      if (this.process.pid) {
        process.kill(this.process.pid, 0); // 发送信号 0 检查进程是否存在
      }
    } catch {
      return false;
    }

    // 进行健康检查
    return await this.healthCheck();
  }

  /**
   * 健康检查
   */
  async healthCheck(): Promise<boolean> {
    const envManager = new EnvManager();
    const envConfig = envManager.readEnv();
    const port = this.allocatedPort ?? getBackendPort(envConfig);
    const backendUrl = getBackendAccessUrl({ ...envConfig, backendPort: port });

    try {
      const response = await fetch(`${backendUrl}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(3000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  /**
   * 启动后端服务
   */
  async start(options?: BackendOperationOptions): Promise<boolean> {
    this.operationSilent = options?.silent ?? false;
    try {
      if (this.isStarting) {
        this.log('Backend is already starting...', 'warn');
        return false;
      }

      this.reloadConfig('before start');

      if (await this.isRunning()) {
        this.log('Backend is already running', 'warn');
        return true;
      }

      this.isStarting = true;
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
      if (!fs.existsSync(this.config.workingDirectory)) {
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
      const port = await this.allocatePort();
      this.allocatedPort = port;
      this.log(`Allocated port: ${port}`);

      // 将端口写入.env文件
      await this.writePortToEnv(port);

      this.log('Starting backend service...');
      this.log(`Python path: ${this.config.pythonPath}`);
      this.log(`Working directory: ${this.config.workingDirectory}`);

      // 合并环境变量，使用动态分配的端口
      const env = {
        ...process.env,
        ...this.config.env,
        BACKEND_PORT: String(port),
        LITELLM_LOCAL_MODEL_COST_MAP: 'True',
      };

      // 启动后端进程
      const args = ['-m', 'agentsociety2.backend.run'];
      this.process = spawn(this.config.pythonPath, args, {
        cwd: this.config.workingDirectory,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      // 将进程PID写入.env文件用于生命周期管理
      if (this.process.pid) {
        await this.writePidToEnv(this.process.pid);
      }

      // 处理 stdout
      this.process.stdout?.on('data', (data: Buffer) => {
        const message = data.toString();
        this.outputChannel.append(message);
        this.log(`[STDOUT] ${message.trim()}`, 'info');
      });

      // 处理 stderr
      this.process.stderr?.on('data', (data: Buffer) => {
        const message = data.toString();
        this.outputChannel.append(message);
        this.log(`[STDERR] ${message.trim()}`, 'warn');
      });

      // 处理进程退出
      this.process.on('exit', (code, signal) => {
        this.log(`Backend process exited with code ${code}, signal ${signal}`);
        this.process = null;
        this.isStarting = false;
        this.allocatedPort = null;

        // 清理.env文件中的PID和端口信息
        this.cleanupBackendEnv();

        this.updateStatusBar('stopped');

        if (code !== 0 && code !== null) {
          this.updateStatusBar('error');
          void vscode.window.showErrorMessage(localize('backendManager.exitedWithCode', String(code)));
        }
      });

      // 处理进程错误
      this.process.on('error', async (error) => {
        this.log(`Failed to start backend: ${error.message}`, 'error');
        this.process = null;
        this.isStarting = false;
        this.allocatedPort = null;

        // 清理.env文件中的PID和端口信息
        this.cleanupBackendEnv();

        this.updateStatusBar('error');

        const errorMessage = error.message || 'Unknown error';
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

      // 等待服务启动（最多等待30秒）
      const maxWaitTime = 30000;
      const checkInterval = 1000;
      let elapsed = 0;

      while (elapsed < maxWaitTime) {
        await new Promise((resolve) => setTimeout(resolve, checkInterval));
        elapsed += checkInterval;

        if (await this.healthCheck()) {
          this.log('Backend service started successfully');
          this.isStarting = false;
          this.updateStatusBar('running', this.allocatedPort ?? undefined);
          this.startHealthCheck();
          return true;
        }

        if (!this.process || this.process.killed) {
          throw new Error('Backend process exited unexpectedly');
        }
      }

      throw new Error('Backend service failed to start within 30 seconds');
    } catch (error: any) {
      this.log(`Failed to start backend: ${error.message}`, 'error');
      this.isStarting = false;
      this.allocatedPort = null;
      this.updateStatusBar('error');

      this.cleanupBackendEnv();

      const errorMessage = error.message || 'Unknown error';
      const isConfigError =
        errorMessage.includes('Python path') ||
        errorMessage.includes('LLM API key') ||
        errorMessage.includes('Working directory') ||
        errorMessage.includes('.env');

      if (isConfigError) {
        await this.showConfigError(localize('backendManager.startFailed', errorMessage));
      } else {
        this.outputChannel.show(true);
        this.notifyError(localize('backendManager.startFailed', errorMessage));
      }

      if (this.process) {
        await this.stop();
      }

      return false;
    } finally {
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
    this.allocatedPort = null;
    this.externalBackend = false;

    // 清理.env文件中的后端相关字段
    this.cleanupBackendEnv();

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

    this.healthCheckInterval = setInterval(async () => {
      const isHealthy = await this.healthCheck();
      if (!isHealthy) {
        if (this.process && !this.process.killed) {
          this.log('Health check failed, but process is still running', 'warn');
        } else if (this.externalBackend) {
          this.externalBackend = false;
          this.allocatedPort = null;
          this.updateStatusBar('stopped');
          this.stopHealthCheck();
        }
      } else if (this.currentStatus === 'running') {
        this.updateStatusBar('running', this.allocatedPort ?? undefined);
      }
    }, 10000);
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
  private async allocatePort(): Promise<number> {
    const envManager = new EnvManager();
    const envConfig = envManager.readEnv();
    const configuredPort = getBackendPort(envConfig);

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
  private async writePortToEnv(port: number): Promise<void> {
    const envManager = new EnvManager();
    envManager.writeEnv({ backendPort: port });
    this.log(`Wrote port ${port} to .env file`);
  }

  /**
   * 将后端进程PID写入.env文件用于生命周期追踪
   */
  private async writePidToEnv(pid: number): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      return;
    }

    const envPath = path.join(workspaceFolder.uri.fsPath, '.env');

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

  /**
   * 清理.env文件中的后端相关字段（PID和端口）
   */
  private cleanupBackendEnv(): void {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      return;
    }

    const envPath = path.join(workspaceFolder.uri.fsPath, '.env');
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
      if (trimmed.startsWith('BACKEND_PID=')) {
        continue;
      }
      newLines.push(line);
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
    const port = this.allocatedPort ?? await this.getPortFromEnv();

    if (this.process && !this.process.killed) {
      try {
        if (this.process.pid) {
          process.kill(this.process.pid, 0);
        }
        if (await this.healthCheck()) {
          this.currentStatus = 'running';
          return {
            isRunning: true,
            pid: this.process.pid,
            port: this.allocatedPort ?? port,
          };
        }
      } catch {
        // fall through to external probe
      }
    }

    if (await this.healthCheck()) {
      if (!this.process) {
        this.externalBackend = true;
      }
      this.currentStatus = 'running';
      // Status reads must not notify the config page: its refresh reads this
      // method again. Lifecycle operations update the status bar separately.
      return {
        isRunning: true,
        pid: this.process?.pid,
        port: this.allocatedPort ?? port,
      };
    }

    return {
      isRunning: false,
      pid: this.process?.pid,
      port,
    };
  }

  /**
   * 从.env文件读取端口
   */
  private async getPortFromEnv(): Promise<number> {
    const envManager = new EnvManager();
    const envConfig = envManager.readEnv();
    return getBackendPort(envConfig);
  }

  /**
   * 获取后端 URL
   */
  getBackendUrl(): string | null {
    const port = this.allocatedPort;
    if (!port) {
      return null;
    }
    return `http://localhost:${port}`;
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
    const url = this.getBackendUrl();
    if (!url) {
      vscode.window.showWarningMessage(localize('extension.backend.statusOff'));
      return false;
    }
    await vscode.env.openExternal(vscode.Uri.parse(url));
    return true;
  }

  /**
   * 在浏览器中打开 API 文档
   */
  async openApiDocs(): Promise<boolean> {
    const url = this.getBackendUrl();
    if (!url) {
      vscode.window.showWarningMessage(localize('extension.backend.statusOff'));
      return false;
    }
    await vscode.env.openExternal(vscode.Uri.parse(`${url}/docs`));
    return true;
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
