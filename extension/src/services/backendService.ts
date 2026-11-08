/**
 * BackendService - 后端通信服务
 *
 * 负责与 FastAPI 后端的所有 HTTP/SSE 通信。
 * 从 apiClient.ts 提取核心通信逻辑，提供更清晰的接口。
 */

import * as vscode from 'vscode';
import { getBackendAccessUrl } from '../runtimeConfig';
import { fetchCompat } from '../shared/fetchCompat';
import { appendSharedOutputLine, OUTPUT_CHANNEL_BACKEND } from '../shared/outputChannels';

const fetch = fetchCompat as unknown as typeof globalThis.fetch;

export interface BackendStatus {
  connected: boolean;
  url: string;
  error?: string;
}

export class BackendService {
  private baseUrl: string;
  private disposables: vscode.Disposable[] = [];
  private abortController: AbortController | null = null;

  constructor(context: vscode.ExtensionContext) {
    this.baseUrl = getBackendAccessUrl();

    // Monitor .env file changes for port updates
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (workspaceFolder) {
      const envWatcher = vscode.workspace.createFileSystemWatcher(
        new vscode.RelativePattern(workspaceFolder, '.env')
      );
      const refreshBackendUrl = () => {
        const newUrl = this.getBackendUrl();
        if (newUrl !== this.baseUrl) {
          this.baseUrl = newUrl;
          this.log(`Backend URL updated from .env: ${this.baseUrl}`);
        }
      };
      envWatcher.onDidCreate(refreshBackendUrl);
      envWatcher.onDidChange(refreshBackendUrl);
      envWatcher.onDidDelete(refreshBackendUrl);
      this.disposables.push(envWatcher);
      context.subscriptions.push(envWatcher);
    }
  }

  /**
   * Get backend URL from .env file
   */
  private getBackendUrl(): string {
    return getBackendAccessUrl();
  }

  private log(message: string): void {
    const timestamp = new Date().toISOString();
    appendSharedOutputLine(OUTPUT_CHANNEL_BACKEND, `[${timestamp}] ${message}`);
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Check backend health status
   */
  async healthCheck(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/health`);
      return response.ok;
    } catch (error) {
      this.log(`Health check failed: ${error}`);
      return false;
    }
  }

  /**
   * Get backend status
   */
  async getStatus(): Promise<BackendStatus> {
    const connected = await this.healthCheck();
    return {
      connected,
      url: this.baseUrl,
    };
  }

  /**
   * Abort the current SSE stream
   */
  abortStream(): void {
    if (this.abortController) {
      this.log('[SSE] Aborting current stream');
      this.abortController.abort();
      this.abortController = null;
    }
  }

  dispose(): void {
    this.abortStream();
    this.disposables.forEach((d) => d.dispose());
  }
}
