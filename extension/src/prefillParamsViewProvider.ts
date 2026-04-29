/**
 * 预填充参数视图提供者 (Prefill Parameters View Provider)
 *
 * 这个类负责创建和管理VSCode中的预填充参数查看窗口（只读）。
 * 使用WebviewPanel模式，类似ChatWebviewProvider，作为项目结构视图中的一个入口。
 *
 * 功能：
 * 1. 显示所有可用的Agent类和Env Module类（通过Tab页切换）
 * 2. 显示每个类的预填充参数（只读）
 * 3. 支持搜索和筛选
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，注册命令 'agentsociety.viewPrefillParams'
 * - @extension/src/apiClient.ts - 调用后端API获取预填充参数
 * - @extension/src/webview/prefillParams/ - 前端React组件 (编译后为prefillParams.js)
 *
 * 后端API：
 * - @packages/agentsociety2/agentsociety2/backend/routers/prefill_params.py - /api/v1/prefill-params
 * - @packages/agentsociety2/agentsociety2/backend/routers/modules.py - /api/v1/modules (获取可用类)
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { ApiClient } from './apiClient';
import { localize } from './i18n';

export class PrefillParamsViewProvider {
  /**
   * 当前活动的预填充参数面板实例（单例模式）
   */
  public static currentPanel: PrefillParamsViewProvider | undefined;

  /**
   * Webview视图类型标识符
   */
  private static readonly viewType = 'prefillParamsView';

  /**
   * Webview面板实例
   */
  private readonly _panel: vscode.WebviewPanel;

  /**
   * 扩展的URI
   */
  private readonly _extensionUri: vscode.Uri;

  /**
   * 扩展路径
   */
  private readonly _extensionPath: string;

  /**
   * API客户端实例
   */
  private readonly _apiClient: ApiClient;

  /**
   * 可清理资源列表
   */
  private _disposables: vscode.Disposable[] = [];

  /**
   * 创建或显示预填充参数面板（静态工厂方法）
   */
  public static createOrShow(
    context: vscode.ExtensionContext,
    apiClient: ApiClient,
    kind?: 'env_module' | 'agent'
  ) {
    // 如果已经有一个面板打开，直接显示它（单例模式）
    if (PrefillParamsViewProvider.currentPanel) {
      PrefillParamsViewProvider.currentPanel._panel.reveal(vscode.ViewColumn.Beside);
      return;
    }

    // 创建新的WebviewPanel - 统一的标题
    const title = localize('prefillParams.groupTitle'); // 环境与智能体

    const panel = vscode.window.createWebviewPanel(
      PrefillParamsViewProvider.viewType,
      title,
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.file(path.join(context.extensionPath, 'out', 'webview'))
        ]
      }
    );

    // 创建PrefillParamsViewProvider实例并保存为当前面板
    PrefillParamsViewProvider.currentPanel = new PrefillParamsViewProvider(panel, context, apiClient);
  }

  /**
   * 构造函数（私有，只能通过createOrShow调用）
   */
  private constructor(
    panel: vscode.WebviewPanel,
    context: vscode.ExtensionContext,
    apiClient: ApiClient
  ) {
    this._panel = panel;
    this._extensionUri = context.extensionUri;
    this._extensionPath = context.extensionPath;
    this._apiClient = apiClient;

    // 设置Webview的HTML内容
    this._panel.webview.html = this._getHtmlForWebview(this._panel.webview);

    // 监听面板销毁事件
    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    // 处理来自Webview的消息
    this._panel.webview.onDidReceiveMessage(
      async (message) => {
        switch (message.command) {
          case 'requestData':
            await this._handleRequestData();
            break;
          case 'refresh':
            await this._handleRequestData();
            break;
          case 'testCustomModule':
            await this._handleTestSingleModule(message);
            break;
          case 'openPrefillParamsJson':
            await this._openPrefillParamsJson();
            break;
        }
      },
      null,
      this._disposables
    );

    // 初始加载数据
    this._handleRequestData();
  }

  private async _openPrefillParamsJson(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('prefillParamsViewProvider.noWorkspace'));
      return;
    }
    const agentsocietyDir = path.join(workspaceFolder.uri.fsPath, '.agentsociety');
    const prefillPath = path.join(agentsocietyDir, 'prefill_params.json');
    try {
      if (!fs.existsSync(agentsocietyDir)) {
        fs.mkdirSync(agentsocietyDir, { recursive: true });
      }
      if (!fs.existsSync(prefillPath)) {
        const template = {
          version: '1.0',
          env_modules: {},
          agents: {},
        };
        fs.writeFileSync(prefillPath, `${JSON.stringify(template, null, 2)}\n`, 'utf-8');
      }
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(prefillPath));
      await vscode.window.showTextDocument(doc, { preview: false });
    } catch (e: any) {
      vscode.window.showErrorMessage(e?.message || String(e));
    }
  }

  private async _handleRequestData() {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this._panel.webview.postMessage({
        command: 'error',
        error: localize('prefillParamsViewProvider.noWorkspace'),
      });
      return;
    }

    try {
      // 获取可用的类列表
      const classesResponse = await this._apiClient.getAvailableClasses(workspaceFolder.uri.fsPath);

      // 获取所有预填充参数
      const prefillResponse = await this._apiClient.getPrefillParams(workspaceFolder.uri.fsPath);

      this._panel.webview.postMessage({
        command: 'initialData',
        classes: classesResponse,
        prefillParams: prefillResponse.data,
      });
    } catch (error: any) {
      this._panel.webview.postMessage({
        command: 'error',
        error: error.message || localize('prefillParams.errorMessages.loadFailed'),
      });
    }
  }

  private async _handleTestSingleModule(message: any) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this._panel.webview.postMessage({
        command: 'testResult',
        moduleKey: message.moduleKey,
        success: false,
        error: localize('prefillParamsViewProvider.noWorkspace'),
      });
      return;
    }

    const moduleType = message.moduleType; // 'env_module' or 'agent'
    const moduleClassName = message.moduleClassName; // e.g., 'SimpleAgent'
    const moduleKey = message.moduleKey;

    try {
      // 发送请求，指定要测试的模块
      const response = await this._apiClient.testCustomModules({
        workspace_path: workspaceFolder.uri.fsPath,
        module_kind: moduleType,
        module_class_name: moduleClassName,
      });

      // 由于后端只测试指定的模块，结果应该只包含一个模块的测试结果
      let moduleOutput = '';
      let moduleSuccess = false;
      let moduleError: string | undefined = undefined;

      // 从 results 数组中获取测试结果
      const results = response.results || [];

      if (results.length > 0) {
        // 找到了该模块的测试结果
        const moduleResult = results[0];
        moduleSuccess = moduleResult.success;
        moduleOutput = moduleResult.output || '';
        moduleError = moduleResult.error;
      } else {
        // 没有找到结果，可能是后端没有找到该模块
        moduleOutput = response.test_output || '';
        moduleSuccess = response.success || false;
        moduleError = response.error || `未找到模块 "${moduleClassName}" 的测试结果`;
      }

      this._panel.webview.postMessage({
        command: 'testResult',
        moduleKey: moduleKey,
        success: moduleSuccess,
        output: moduleOutput,
        error: moduleError,
      });
    } catch (error: any) {
      this._panel.webview.postMessage({
        command: 'testResult',
        moduleKey: moduleKey,
        success: false,
        error: error.message || localize('customModules.testFailed', 'Unknown error'),
        output: '',
      });
    }
  }

  public dispose() {
    PrefillParamsViewProvider.currentPanel = undefined;

    // 清理资源
    while (this._disposables.length) {
      const x = this._disposables.pop();
      if (x) {
        x.dispose();
      }
    }
  }

  private _getHtmlForWebview(webview: vscode.Webview): string {
    // 获取webview资源的URI
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.file(path.join(this._extensionPath, 'out', 'webview', 'prefillParams.js'))
    );
    const nonce = Array.from({ length: 32 }, () => Math.random().toString(36)[2]).join('');
    const csp = [
      "default-src 'none'",
      `img-src ${webview.cspSource} data:`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src ${webview.cspSource} 'nonce-${nonce}'`,
      `connect-src ${webview.cspSource} http://127.0.0.1:* http://localhost:*`,
    ].join('; ');

    // 使用非空断言，因为我们知道这些文件会被webpack生成
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="${csp}">
    <title>Prefill Parameters</title>
    <style>
      * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
      }
      body {
        font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
        background: var(--vscode-editor-background);
        color: var(--vscode-editor-foreground);
        height: 100vh;
        overflow: hidden;
      }
      #root {
        height: 100vh;
      }
    </style>
</head>
<body>
    <div id="root"></div>
    <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}
