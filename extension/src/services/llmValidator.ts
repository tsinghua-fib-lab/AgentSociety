/**
 * LLM Validator - LLM API 验证服务
 *
 * 在 VSCode 扩展进程中执行 LLM API 验证，避免 webview 的 CSP 限制
 *
 * 关联文件：
 * - @extension/src/configPageViewProvider.ts - 配置页面使用LLMValidator验证API配置
 * - @extension/src/envManager.ts - 从.env读取LLM配置
 *
 * 后端Python验证：
 * - 调用 @packages/agentsociety2/agentsociety2/config.py 中的LLM配置进行验证
 */

import * as vscode from 'vscode';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { requestJson } from './httpClient';

const execFileAsync = promisify(execFile);

export interface ValidationResult {
  success: boolean;
  error?: string;
}

export interface LLMConfig {
  apiKey: string;
  apiBase: string;
  model: string;
}

export enum LLMType {
  Chat = 'chat',
  Embedding = 'embedding',
}

export interface PythonConfig {
  pythonPath?: string;
}

export class LLMValidator {
  private outputChannel: vscode.OutputChannel;

  constructor() {
    this.outputChannel = vscode.window.createOutputChannel('LLM Validator');
  }

  private log(message: string): void {
    const timestamp = new Date().toISOString();
    this.outputChannel.appendLine(`[${timestamp}] ${message}`);
  }

  /**
   * 验证 LLM API 连通性
   */
  async validate(config: LLMConfig, type: LLMType = LLMType.Chat): Promise<ValidationResult> {
    const { apiKey, apiBase, model } = config;

    if (!apiKey) {
      return { success: false, error: 'API Key 为空' };
    }

    if (!apiBase) {
      return { success: false, error: 'API Base URL 为空' };
    }

    if (!model) {
      return { success: false, error: '模型名称为空' };
    }

    // 移除末尾斜杠
    const baseUrl = apiBase.replace(/\/$/, '');
    const endpoint = type === LLMType.Embedding ? '/embeddings' : '/chat/completions';
    const fullUrl = `${baseUrl}${endpoint}`;

    this.log(`Validating ${type} API: ${fullUrl}`);
    this.log(`Model: ${model}`);

    try {
      const requestBody = type === LLMType.Embedding
        ? {
            model: model,
            input: 'Hello',
          }
        : {
            model: model,
            messages: [{ role: 'user', content: 'Hello' }],
            max_tokens: 1,
          };

      const response = await requestJson<{ error?: { message?: string }; message?: string }>(fullUrl, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${apiKey}`,
        },
        body: requestBody,
        timeoutMs: 15000,
      });

      this.log(`Response status: ${response.status}`);

      if (response.ok) {
        this.log('Validation successful');
        return { success: true };
      }

      // 尝试获取错误详情
      let errorDetail = '';
      try {
        const errorData = response.data;
        errorDetail = errorData.error?.message || errorData.message || JSON.stringify(errorData);
      } catch {
        errorDetail = response.statusText || `HTTP ${response.status}`;
      }

      this.log(`Validation failed: ${response.status} - ${errorDetail}`);

      if (response.status === 401) {
        return { success: false, error: 'API Key 无效或已过期' };
      } else if (response.status === 404) {
        return { success: false, error: `API 地址不正确: ${fullUrl}` };
      } else if (response.status >= 500) {
        return { success: false, error: `服务器错误 (${response.status}): ${errorDetail}` };
      } else {
        return { success: false, error: `请求失败 (${response.status}): ${errorDetail}` };
      }
    } catch (error) {
      if (error instanceof Error) {
        if (error.message.includes('请求超时')) {
          const errorMsg = '请求超时（15秒），请检查网络连接或 API 地址是否正确';
          this.log(`Timeout error: ${errorMsg}`);
          return { success: false, error: errorMsg };
        }
        const errorMsg = `无法连接到 ${fullUrl}。请检查网络或 API 地址是否正确`;
        this.log(`Connection error: ${error.message}`);
        return { success: false, error: errorMsg };
      }
      return { success: false, error: '未知错误' };
    }
  }

  dispose(): void {
    this.outputChannel.dispose();
  }
}

/**
 * Python Validator - Python 环境验证服务
 *
 * 验证指定的 Python 环境中是否安装了 agentsociety2
 */
export class PythonValidator {
  private outputChannel: vscode.OutputChannel;
  private static readonly AGENTSOCIETY2_CHECK_SCRIPT = `
import importlib.util
import json
import sys

try:
    from importlib.metadata import PackageNotFoundError, version
except ImportError:
    from importlib_metadata import PackageNotFoundError, version

spec = importlib.util.find_spec("agentsociety2")
if spec is None:
    print(json.dumps({"installed": False}))
    raise SystemExit(1)

try:
    package_version = version("agentsociety2")
except PackageNotFoundError:
    package_version = None

print(json.dumps({
    "installed": True,
    "version": package_version,
    "location": spec.origin,
}))
`.trim();

  constructor() {
    this.outputChannel = vscode.window.createOutputChannel('Python Validator');
  }

  private log(message: string): void {
    const timestamp = new Date().toISOString();
    this.outputChannel.appendLine(`[${timestamp}] ${message}`);
  }

  /**
   * 验证 Python 环境
   */
  async validate(config: PythonConfig): Promise<ValidationResult> {
    const { pythonPath } = config;

    // 如果没有指定 Python 路径，尝试自动检测
    const pythonCmd = this.normalizePythonPath(pythonPath) || 'python3';
    this.log(`Validating Python: ${pythonCmd}`);

    try {
      // 首先检查 Python 是否可用
      this.log(`Checking Python executable...`);
      const versionResult = await this.execCommand(pythonCmd, '--version');

      if (!versionResult.success) {
        return {
          success: false,
          error: pythonPath
            ? `找不到 Python: ${pythonPath}`
            : '找不到 Python (python3)，请指定正确的 Python 路径'
        };
      }

      const pythonVersion = this.getCommandOutput(versionResult);
      this.log(`Python version: ${pythonVersion}`);

      // 检查 agentsociety2 是否安装
      this.log(`Checking agentsociety2 installation...`);
      const importResult = await this.execCommand(
        pythonCmd,
        '-c',
        PythonValidator.AGENTSOCIETY2_CHECK_SCRIPT
      );

      if (!importResult.success) {
        const importError = this.getCommandOutput(importResult);
        return {
          success: false,
          error: [
            'agentsociety2 未安装在此 Python 环境中。',
            `版本信息: ${pythonVersion}`,
            importError ? `检测详情: ${importError}` : null,
          ].filter(Boolean).join('\n')
        };
      }

      const packageInfo = this.parsePackageCheckResult(importResult.stdout);
      const version = packageInfo?.version || 'unknown';
      const location = packageInfo?.location || 'unknown';
      this.log(`agentsociety2 version: ${version}`);
      this.log(`agentsociety2 location: ${location}`);

      return {
        success: true,
      };
    } catch (error) {
      if (error instanceof Error) {
        this.log(`Error: ${error.message}`);
        return { success: false, error: error.message };
      }
      return { success: false, error: '未知错误' };
    }
  }

  /**
   * 执行命令并返回结果
   */
  private async execCommand(command: string, ...args: string[]): Promise<{ success: boolean; stdout: string; stderr: string }> {
    this.log(`Executing: ${command} ${args.join(' ')}`);

    try {
      const { stdout, stderr } = await execFileAsync(command, args, {
        timeout: 10000, // 10秒超时
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
        windowsHide: true,
      });

      return { success: true, stdout: stdout || '', stderr: stderr || '' };
    } catch (error: any) {
      this.log(`Command failed: ${error.message}`);
      return {
        success: false,
        stdout: error.stdout || '',
        stderr: error.stderr || error.message || ''
      };
    }
  }

  private normalizePythonPath(pythonPath?: string): string {
    const trimmed = pythonPath?.trim() || '';
    return trimmed.replace(/^["'](.+)["']$/, '$1');
  }

  private getCommandOutput(result: { stdout: string; stderr: string }): string {
    return (result.stdout || result.stderr || '').trim();
  }

  private parsePackageCheckResult(stdout: string): { installed: boolean; version?: string | null; location?: string | null } | null {
    const trimmed = stdout.trim();
    if (!trimmed) {
      return null;
    }

    try {
      return JSON.parse(trimmed) as { installed: boolean; version?: string | null; location?: string | null };
    } catch {
      this.log(`Failed to parse package check result: ${trimmed}`);
      return null;
    }
  }

  dispose(): void {
    this.outputChannel.dispose();
  }
}
