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

  constructor(context: vscode.ExtensionContext) {
    this.context = context;
    this.outputChannel = vscode.window.createOutputChannel('AI Social Scientist Backend');
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      100
    );
    this.statusBarItem.command = 'aiSocialScientist.backendStatusMenu';
    this.config = this.loadConfig();

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

    // 检查并清理可能存在的遗留后端进程
    this.checkAndCleanupOrphanedProcess();
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
                // 后端仍在运行，保留PID记录
                this.log(`Existing backend process found (PID: ${pid}, Port: ${port})`);
                this.allocatedPort = port;
                this.updateStatusBar('running', port);
                this.startHealthCheck();
              } else {
                // 健康检查失败，清理记录
                this.log(`Backend process (PID: ${pid}) exists but health check failed, cleaning up...`);
                this.cleanupBackendEnv();
              }
            } catch {
              // 无法连接，清理记录
              this.log(`Cannot connect to backend (PID: ${pid}), cleaning up...`);
              this.cleanupBackendEnv();
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
    this.outputChannel.appendLine(`[${timestamp}] ${prefix} ${message}`);
  }

  /**
   * 显示配置错误消息，并提供打开 .env 文件的选项
   */
  private async showConfigError(message: string): Promise<void> {
    const openEnvLabel = 'Open .env file';
    const result = await vscode.window.showErrorMessage(message, openEnvLabel);
    if (result === openEnvLabel) {
      // 打开 .env 文件
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (workspaceFolder) {
        const envPath = vscode.Uri.file(path.join(workspaceFolder.uri.fsPath, '.env'));
        await vscode.commands.executeCommand('vscode.open', envPath);
      }
    }
  }

  /**
   * 加载配置并映射为环境变量
   *
   * 仅从 .env 文件加载配置
   */
  private loadConfig(): BackendConfig {
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

    // 检测 Python 路径
    const pythonPath = envConfig.pythonPath || this.detectPythonPath();

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

    // Coder LLM 配置
    if (envConfig.coderLlmApiKey) { env.AGENTSOCIETY_CODER_LLM_API_KEY = envConfig.coderLlmApiKey; }
    if (envConfig.coderLlmApiBase) { env.AGENTSOCIETY_CODER_LLM_API_BASE = envConfig.coderLlmApiBase; }
    if (envConfig.coderLlmModel) { env.AGENTSOCIETY_CODER_LLM_MODEL = envConfig.coderLlmModel; }

    // Nano LLM 配置
    if (envConfig.nanoLlmApiKey) { env.AGENTSOCIETY_NANO_LLM_API_KEY = envConfig.nanoLlmApiKey; }
    if (envConfig.nanoLlmApiBase) { env.AGENTSOCIETY_NANO_LLM_API_BASE = envConfig.nanoLlmApiBase; }
    if (envConfig.nanoLlmModel) { env.AGENTSOCIETY_NANO_LLM_MODEL = envConfig.nanoLlmModel; }

    // Embedding 配置
    if (envConfig.embeddingApiKey) { env.AGENTSOCIETY_EMBEDDING_API_KEY = envConfig.embeddingApiKey; }
    if (envConfig.embeddingApiBase) { env.AGENTSOCIETY_EMBEDDING_API_BASE = envConfig.embeddingApiBase; }
    if (envConfig.embeddingModel) { env.AGENTSOCIETY_EMBEDDING_MODEL = envConfig.embeddingModel; }
    if (envConfig.embeddingDims) { env.AGENTSOCIETY_EMBEDDING_DIMS = String(envConfig.embeddingDims); }

    // Web Search 配置
    if (envConfig.webSearchApiUrl) { env.WEB_SEARCH_API_URL = envConfig.webSearchApiUrl; }
    if (envConfig.webSearchApiToken) { env.WEB_SEARCH_API_TOKEN = envConfig.webSearchApiToken; }
    if (envConfig.miroflowDefaultLlm) { env.MIROFLOW_DEFAULT_LLM = envConfig.miroflowDefaultLlm; }
    if (envConfig.miroflowDefaultAgent) { env.MIROFLOW_DEFAULT_AGENT = envConfig.miroflowDefaultAgent; }

    // EasyPaper (for generate_paper tool)
    if (envConfig.easypaperApiUrl) { env.EASYPAPER_API_URL = envConfig.easypaperApiUrl; }
    if (envConfig.literatureSearchApiUrl) { env.LITERATURE_SEARCH_API_URL = envConfig.literatureSearchApiUrl; }
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
        // 运行时显示端口号，方便用户快速查看
        this.statusBarItem.text = `$(check) Backend:${effectivePort ?? ''}`;
        // 使用 Markdown 格式的 tooltip，显示更丰富的信息
        const runningTooltip = new vscode.MarkdownString();
        runningTooltip.appendMarkdown(`**${localize('extension.backend.statusOn', String(effectivePort ?? '?'))}**\n\n`);
        runningTooltip.appendMarkdown(`- URL: \`${backendUrl}\`\n`);
        runningTooltip.appendMarkdown(`- API Docs: \`${backendUrl}/docs\`\n\n`);
        runningTooltip.appendMarkdown(`*${localize('backendManager.statusBar.tooltip')}*`);
        this.statusBarItem.tooltip = runningTooltip;
        this.statusBarItem.backgroundColor = undefined;
        this.statusBarItem.show();
        break;
      }
      case 'starting':
        this.statusBarItem.text = '$(sync~spin) Backend: Starting...';
        this.statusBarItem.tooltip = localize('backendManager.statusBar.tooltip');
        this.statusBarItem.backgroundColor = undefined;
        this.statusBarItem.show();
        break;
      case 'error':
        this.statusBarItem.text = '$(error) Backend: Error';
        this.statusBarItem.tooltip = localize('backendManager.statusBar.tooltip');
        this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
        this.statusBarItem.show();
        break;
      case 'stopped':
        this.statusBarItem.text = '$(circle-slash) Backend: Stopped';
        this.statusBarItem.tooltip = localize('backendManager.statusBar.tooltip');
        this.statusBarItem.backgroundColor = undefined;
        this.statusBarItem.show();
        break;
    }
  }

  /**
   * 检查后端服务是否正在运行
   */
  async isRunning(): Promise<boolean> {
    if (!this.process || this.process.killed) {
      return false;
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
    const backendUrl = this.allocatedPort ? `http://localhost:${this.allocatedPort}` : getBackendAccessUrl(envConfig);

    try {
      const response = await fetch(`${backendUrl}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(3000), // 3秒超时
      });
      return response.ok;
    } catch (error) {
      return false;
    }
  }

  private async detectExternalBackend(): Promise<boolean> {
    const envManager = new EnvManager();
    const envConfig = envManager.readEnv();
    const configuredPort = getBackendPort(envConfig);
    const url = `http://localhost:${configuredPort}`;
    try {
      const resp = await fetch(`${url}/health`, { method: 'GET', signal: AbortSignal.timeout(1200) });
      if (!resp.ok) {
        return false;
      }
      this.allocatedPort = configuredPort;
      this.externalBackend = true;
      this.updateStatusBar('running', configuredPort);
      this.startHealthCheck();
      return true;
    } catch {
      return false;
    }
  }

  /**
   * 启动后端服务
   */
  async start(): Promise<boolean> {
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

    try {
      // 验证 Python 路径
      if (!this.config.pythonPath) {
        const errorMessage = localize('backendManager.configInsufficient') + ': Python path not found. Please set PYTHON_PATH in .env file';
        this.log(errorMessage, 'error');
        this.isStarting = false;
        this.updateStatusBar('error');
        await this.showConfigError(errorMessage);
        return false;
      }

      // 验证工作目录
      if (!fs.existsSync(this.config.workingDirectory)) {
        const errorMessage = `Working directory does not exist: ${this.config.workingDirectory}`;
        this.log(errorMessage, 'error');
        this.isStarting = false;
        this.updateStatusBar('error');
        await this.showConfigError(errorMessage);
        return false;
      }

      // 验证必需的配置
      if (!this.config.env.AGENTSOCIETY_LLM_API_KEY) {
        const errorMessage = localize('backendManager.configInsufficient') + ': LLM API key is required. Please set AGENTSOCIETY_LLM_API_KEY in .env file';
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
          vscode.window.showErrorMessage(
            `Backend service exited with code ${code}. Check the output panel for details.`
          );
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

        // 检查是否是配置相关的错误（如找不到 Python 可执行文件）
        const errorMessage = error.message || 'Unknown error';
        const isConfigError =
          errorMessage.includes('ENOENT') ||
          errorMessage.includes('spawn') ||
          errorMessage.includes('Python') ||
          errorMessage.includes('python');

        if (isConfigError) {
          await this.showConfigError(`Failed to start backend service: ${errorMessage}`);
        } else {
          vscode.window.showErrorMessage(
            `Failed to start backend service: ${errorMessage}`
          );
        }
      });

      // 等待服务启动（最多等待30秒）
      const maxWaitTime = 30000; // 30秒
      const checkInterval = 1000; // 每秒检查一次
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

        // 检查进程是否已经退出
        if (!this.process || this.process.killed) {
          throw new Error('Backend process exited unexpectedly');
        }
      }

      // 超时
      throw new Error('Backend service failed to start within 30 seconds');
    } catch (error: any) {
      this.log(`Failed to start backend: ${error.message}`, 'error');
      this.isStarting = false;
      this.allocatedPort = null;
      this.updateStatusBar('error');

      // 清理.env文件中的PID和端口信息
      this.cleanupBackendEnv();

      // 检查是否是配置相关的错误
      const errorMessage = error.message || 'Unknown error';
      const isConfigError =
        errorMessage.includes('Python path') ||
        errorMessage.includes('LLM API key') ||
        errorMessage.includes('Working directory') ||
        errorMessage.includes('.env');

      if (isConfigError) {
        await this.showConfigError(`Failed to start backend service: ${errorMessage}`);
      } else {
        vscode.window.showErrorMessage(
          `Failed to start backend service: ${errorMessage}`
        );
      }

      // 清理进程
      if (this.process) {
        this.stop();
      }

      return false;
    }
  }

  /**
   * 停止后端服务
   */
  async stop(): Promise<void> {
    if (!this.process) {
      if (this.externalBackend) {
        vscode.window.showWarningMessage('检测到后端并非由插件启动，插件无法停止该进程；请在终端中手动结束。');
      } else {
        this.log('Backend is not running', 'warn');
      }
      return;
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
  }

  /**
   * 重启后端服务
   */
  async restart(): Promise<boolean> {
    this.log('Restarting backend service...');
    if (!this.process && this.externalBackend) {
      vscode.window.showWarningMessage('检测到后端并非由插件启动，插件无法重启该进程；请在终端中手动重启，或在插件里“启动后端”启动一份新的后端实例。');
      return false;
    }
    await this.stop();
    await new Promise((resolve) => setTimeout(resolve, 1000)); // 等待1秒
    return await this.start();
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
      }
    }, 10000); // 每10秒检查一次
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
    let isRunning = await this.isRunning();
    // 使用动态分配的端口，如果未分配则读取.env中的配置
    let port = this.allocatedPort ?? await this.getPortFromEnv();

    if (!isRunning) {
      const detected = await this.detectExternalBackend();
      if (detected) {
        isRunning = true;
        port = this.allocatedPort ?? port;
      }
    }

    return {
      isRunning,
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
    this.outputChannel.dispose();
  }
}
