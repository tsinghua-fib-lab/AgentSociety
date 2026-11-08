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
    _kind?: 'env_module' | 'agent'
  ) {
    // 如果已经有一个面板打开，直接显示它（单例模式）
    if (PrefillParamsViewProvider.currentPanel) {
      PrefillParamsViewProvider.currentPanel.revealAndRefresh();
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
          case 'saveClassPrefill':
            await this._handleSaveClassPrefill(message);
            break;
          case 'openCustomModuleSource':
            await this._handleOpenCustomModuleSource(message);
            break;
          case 'startBackend':
            await this._handleStartBackend();
            break;
          case 'openConfigPage':
            await vscode.commands.executeCommand('aiSocialScientist.openConfigPage');
            break;
          case 'copyText':
            if (typeof message.text === 'string' && message.text) {
              await vscode.env.clipboard.writeText(message.text);
            }
            break;
        }
      },
      null,
      this._disposables
    );

    // 初始加载数据
    this._handleRequestData();
  }

  private _prefillParamsPath(workspaceRoot: string): string {
    return path.join(workspaceRoot, '.agentsociety', 'prefill_params.json');
  }

  private _readPrefillParamsFile(workspaceRoot: string): {
    version: string;
    env_modules: Record<string, Record<string, unknown>>;
    agents: Record<string, Record<string, unknown>>;
  } {
    const prefillPath = this._prefillParamsPath(workspaceRoot);
    const empty = { version: '1.0', env_modules: {}, agents: {} };
    if (!fs.existsSync(prefillPath)) {
      return empty;
    }
    const raw = JSON.parse(fs.readFileSync(prefillPath, 'utf-8')) as Record<string, unknown>;
    return {
      version: typeof raw.version === 'string' ? raw.version : '1.0',
      env_modules:
        raw.env_modules && typeof raw.env_modules === 'object' && !Array.isArray(raw.env_modules)
          ? (raw.env_modules as Record<string, Record<string, unknown>>)
          : {},
      agents:
        raw.agents && typeof raw.agents === 'object' && !Array.isArray(raw.agents)
          ? (raw.agents as Record<string, Record<string, unknown>>)
          : {},
    };
  }

  private async _openPrefillParamsJson(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('prefillParamsViewProvider.noWorkspace'));
      return;
    }
    const agentsocietyDir = path.join(workspaceFolder.uri.fsPath, '.agentsociety');
    const prefillPath = this._prefillParamsPath(workspaceFolder.uri.fsPath);
    try {
      if (!fs.existsSync(agentsocietyDir)) {
        fs.mkdirSync(agentsocietyDir, { recursive: true });
      }
      if (!fs.existsSync(prefillPath)) {
        fs.writeFileSync(
          prefillPath,
          `${JSON.stringify({ version: '1.0', env_modules: {}, agents: {} }, null, 2)}\n`,
          'utf-8'
        );
      }
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(prefillPath));
      await vscode.window.showTextDocument(doc, { preview: false });
    } catch (e: any) {
      vscode.window.showErrorMessage(e?.message || String(e));
    }
  }

  private async _handleSaveClassPrefill(message: {
    kind?: string;
    type?: string;
    params?: Record<string, unknown>;
  }): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this._postToWebview({
        command: 'saveResult',
        success: false,
        error: localize('prefillParamsViewProvider.noWorkspace'),
      });
      return;
    }
    const kind = message.kind === 'agent' ? 'agent' : message.kind === 'env_module' ? 'env_module' : '';
    const typeName = typeof message.type === 'string' ? message.type.trim() : '';
    if (!kind || !typeName) {
      this._postToWebview({
        command: 'saveResult',
        success: false,
        error: localize('prefillParams.save.invalidTarget'),
      });
      return;
    }
    const params =
      message.params && typeof message.params === 'object' && !Array.isArray(message.params)
        ? message.params
        : {};

    try {
      const agentsocietyDir = path.join(workspaceFolder.uri.fsPath, '.agentsociety');
      if (!fs.existsSync(agentsocietyDir)) {
        fs.mkdirSync(agentsocietyDir, { recursive: true });
      }
      const data = this._readPrefillParamsFile(workspaceFolder.uri.fsPath);
      const bucket = kind === 'env_module' ? data.env_modules : data.agents;
      if (Object.keys(params).length === 0) {
        delete bucket[typeName];
      } else {
        bucket[typeName] = params;
      }
      const prefillPath = this._prefillParamsPath(workspaceFolder.uri.fsPath);
      fs.writeFileSync(prefillPath, `${JSON.stringify(data, null, 2)}\n`, 'utf-8');
      this._postToWebview({
        command: 'saveResult',
        success: true,
        kind,
        type: typeName,
        params,
      });
    } catch (e: any) {
      this._postToWebview({
        command: 'saveResult',
        success: false,
        kind,
        type: typeName,
        error: e?.message || String(e),
      });
    }
  }

  private async _handleOpenCustomModuleSource(message: {
    kind?: string;
    className?: string;
  }): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('prefillParamsViewProvider.noWorkspace'));
      return;
    }
    const className = typeof message.className === 'string' ? message.className.trim() : '';
    if (!className) {
      return;
    }
    const kindDir = message.kind === 'agent' ? 'agents' : 'envs';
    const root = path.join(workspaceFolder.uri.fsPath, 'custom', kindDir);
    const hit = this._findPythonFileDefiningClass(root, className);
    if (!hit) {
      vscode.window.showWarningMessage(
        localize('prefillParams.openSource.notFound', className)
      );
      return;
    }
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(hit));
    await vscode.window.showTextDocument(doc, { preview: false });
  }

  private _findPythonFileDefiningClass(rootDir: string, className: string): string | undefined {
    if (!fs.existsSync(rootDir)) {
      return undefined;
    }
    const stack = [rootDir];
    const classRe = new RegExp(`^class\\s+${className}\\b`, 'm');
    while (stack.length) {
      const current = stack.pop()!;
      let entries: fs.Dirent[];
      try {
        entries = fs.readdirSync(current, { withFileTypes: true });
      } catch {
        continue;
      }
      for (const entry of entries) {
        const full = path.join(current, entry.name);
        if (entry.isDirectory()) {
          if (entry.name === 'examples' || entry.name === '__pycache__') {
            continue;
          }
          stack.push(full);
          continue;
        }
        if (!entry.isFile() || !entry.name.endsWith('.py') || entry.name.startsWith('__')) {
          continue;
        }
        try {
          const text = fs.readFileSync(full, 'utf-8');
          if (classRe.test(text)) {
            return full;
          }
        } catch {
          /* skip unreadable */
        }
      }
    }
    return undefined;
  }

  public revealAndRefresh(): void {
    this._panel.reveal(vscode.ViewColumn.Beside);
    void this._handleRequestData();
  }

  private _postToWebview(message: Record<string, unknown>): void {
    if (this._panel.webview) {
      void this._panel.webview.postMessage(message);
    }
  }

  private async _handleRequestData() {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this._postToWebview({
        command: 'error',
        error: localize('prefillParamsViewProvider.noWorkspace'),
        backendOffline: false,
      });
      return;
    }

    try {
      const classesResponse = await this._apiClient.getAvailableClasses(workspaceFolder.uri.fsPath);
      const prefillResponse = await this._apiClient.getPrefillParams(workspaceFolder.uri.fsPath);

      this._postToWebview({
        command: 'initialData',
        classes: classesResponse,
        prefillParams: prefillResponse.data,
      });
    } catch (error: any) {
      const errorText = error?.message || localize('prefillParams.errorMessages.loadFailed');
      const backendOffline =
        /未连接|not connected|ECONNREFUSED|Failed to fetch|fetch failed|NetworkError|后端服务响应超时/i.test(
          String(errorText)
        );
      this._postToWebview({
        command: 'error',
        error: errorText,
        backendOffline,
      });
    }
  }

  private async _handleStartBackend(): Promise<void> {
    try {
      const started = await vscode.commands.executeCommand<boolean>(
        'aiSocialScientist.startBackend',
        { silent: true }
      );
      this._postToWebview({
        command: 'startBackendResult',
        success: started === true,
        error: started === true ? undefined : localize('extension.backend.startFailed'),
      });
      if (started === true) {
        await this._handleRequestData();
      }
    } catch (error: any) {
      this._postToWebview({
        command: 'startBackendResult',
        success: false,
        error: error?.message || localize('extension.backend.startFailed'),
      });
    }
  }

  private async _handleTestSingleModule(message: any) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this._postToWebview({
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

      this._postToWebview({
        command: 'testResult',
        moduleKey: moduleKey,
        success: moduleSuccess,
        output: moduleOutput,
        error: moduleError,
      });
    } catch (error: any) {
      this._postToWebview({
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
