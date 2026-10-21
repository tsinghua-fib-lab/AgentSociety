/**
 * SIM Settings 编辑器提供者 (SIM Settings Editor Provider)
 *
 * 这个类负责创建和管理VSCode中的SIM_SETTINGS.json文件的自定义编辑器。
 *
 * VSCode插件开发核心概念：
 * 1. CustomTextEditorProvider: VSCode提供的接口，用于为特定文件类型创建自定义编辑器
 * 2. Webview: VSCode中用于显示自定义HTML内容的容器，类似于一个内嵌的浏览器
 * 3. WebviewPanel: Webview的容器面板，可以显示在编辑器的不同位置
 * 4. 消息传递: Webview和扩展主进程之间通过postMessage/onDidReceiveMessage进行双向通信
 * 5. Disposable: VSCode的资源管理机制，所有需要清理的资源都应该实现Disposable接口
 *
 * 工作流程：
 * 1. 用户打开SIM_SETTINGS.json文件 → resolveCustomTextEditor() 创建自定义编辑器
 * 2. 页面加载 → React组件挂载并发送requestData命令请求数据
 * 3. 扩展处理请求 → 调用后端API获取agent classes和env modules
 * 4. 返回数据 → 扩展通过postMessage发送initialData到Webview
 * 5. 用户修改设置 → Webview通过postMessage发送save命令
 * 6. 保存文件 → 扩展更新文档内容
 * 7. 文件变化 → 扩展监听文档变化并更新Webview
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，注册CustomEditorProvider
 * - @extension/src/apiClient.ts - 调用后端API获取可用的类和参数
 * - @extension/src/webview/simSettings/ - 前端React组件 (编译后为simSettings.js)
 *
 * 后端API：
 * - @packages/agentsociety2/agentsociety2/backend/routers/prefill_params.py - /api/v1/prefill-params
 * - @packages/agentsociety2/agentsociety2/backend/routers/modules.py - /api/v1/modules
 */

import * as vscode from 'vscode';
import * as path from 'path';
import { ApiClient } from './apiClient';

/**
 * SIM Settings 编辑器提供者类
 * 
 * 实现了VSCode的CustomTextEditorProvider接口，为SIM_SETTINGS.json文件提供自定义编辑器。
 * 这个编辑器使用React构建，提供了友好的UI来配置Agent类和Environment模块。
 * 
 * 重要概念：CustomTextEditorProvider
 * - 这是VSCode提供的接口，允许为特定文件类型创建自定义编辑器
 * - 必须实现resolveCustomTextEditor方法，在用户打开文件时调用
 * - 编辑器可以完全自定义UI，不限于纯文本编辑
 * - 需要处理文档的读取、写入和更新
 */
export class SimSettingsEditorProvider implements vscode.CustomTextEditorProvider {
  /**
   * API客户端实例
   * 
   * 用于与FastAPI后端服务通信的客户端。
   * 负责获取agent classes和env modules列表。
   */
  private readonly _apiClient: ApiClient;

  /**
   * 扩展上下文
   * 
   * 包含扩展的配置、状态等信息，用于获取扩展路径等。
   */
  private readonly _context: vscode.ExtensionContext;

  /**
   * 构造函数
   * 
   * 初始化SIM Settings编辑器提供者。
   * 
   * @param context - VSCode扩展上下文，包含扩展的配置、状态等信息
   */
  constructor(context: vscode.ExtensionContext) {
    this._context = context;
    this._apiClient = new ApiClient(context);
  }

  /**
   * 解析自定义文本编辑器（CustomTextEditorProvider接口要求实现的方法）
   * 
   * 当用户打开SIM_SETTINGS.json文件时，VSCode会调用这个方法。
   * 这个方法负责：
   * 1. 配置Webview选项（启用脚本、设置资源根目录等）
   * 2. 解析当前文档内容
   * 3. 设置Webview的HTML内容（加载React应用）
   * 4. 注册事件监听器（文档变化、消息接收、面板销毁）
   * 5. 初始化Webview（发送初始设置）
   * 
   * @param document - 要编辑的文档（SIM_SETTINGS.json文件）
   * @param webviewPanel - VSCode提供的WebviewPanel实例，包含Webview对象
   * @param _token - 取消令牌，用于取消操作（当前未使用）
   * 
   * 重要概念：消息传递机制
   * - Webview → 扩展：通过vscode.postMessage()发送消息
   * - 扩展 → Webview：通过webview.postMessage()发送消息
   * - 扩展接收：通过webview.onDidReceiveMessage()监听消息
   * - Webview接收：通过window.addEventListener('message')监听消息
   * 
   * 消息类型：
   * - requestData: Webview请求加载agent classes和env modules数据
   * - save: Webview保存设置到文档
   * - update: 扩展通知Webview文档已更新
   * - initialData: 扩展发送初始数据到Webview
   */
  public async resolveCustomTextEditor(
    document: vscode.TextDocument,
    webviewPanel: vscode.WebviewPanel,
    _token: vscode.CancellationToken
  ): Promise<void> {
    // 步骤1: 配置Webview选项
    // localResourceRoots指定允许加载的资源根目录（安全限制）
    // 只有在这个目录下的资源才能被Webview加载
    const webviewResourceRoot = vscode.Uri.file(
      path.join(this._context.extensionPath, 'out', 'webview')
    );
    webviewPanel.webview.options = {
      enableScripts: true,  // 启用JavaScript，允许Webview中运行React应用
      localResourceRoots: [webviewResourceRoot],  // 允许加载的资源根目录
    };

    // 步骤2: 解析当前文档内容
    // 读取SIM_SETTINGS.json文件的内容并解析为JSON对象
    // 如果文件格式错误，使用空对象作为默认值
    const content = document.getText();
    let parsedContent: any = {};
    try {
      parsedContent = JSON.parse(content);
    } catch {
      // 如果JSON解析失败（文件格式错误），使用空对象
      // 这样用户可以在编辑器中重新配置
      parsedContent = {};
    }

    // 步骤3: 获取React应用的脚本URI
    // 将本地文件路径转换为Webview可以访问的URI
    // asWebviewUri()方法会将本地路径转换为特殊的vscode-webview://协议URI
    const scriptPath = vscode.Uri.file(
      path.join(this._context.extensionPath, 'out', 'webview', 'simSettings.js')
    );
    const scriptUri = webviewPanel.webview.asWebviewUri(scriptPath);

    // 步骤4: 设置Webview的HTML内容
    // 这会加载React构建的HTML和JS文件
    webviewPanel.webview.html = this._getHtmlForWebview(
      webviewPanel.webview,
      scriptUri,
      parsedContent
    );

    // 步骤5: 定义更新Webview的函数
    // 当文档内容发生变化时，需要通知Webview更新UI
    // 这个函数会读取当前文档内容并发送update消息到Webview
    const updateWebview = () => {
      const currentContent = document.getText();

      // 发送update消息到Webview，通知文档已更新
      webviewPanel.webview.postMessage({
        command: 'update',
        text: currentContent,
      });
    };

    // 步骤6: 监听文档变化事件
    // 当用户通过其他方式（如直接编辑文件）修改文档时，需要更新Webview
    // 这确保了Webview和文档内容保持同步
    const changeDocumentSubscription = vscode.workspace.onDidChangeTextDocument(e => {
      // 只处理当前文档的变化
      if (e.document.uri.toString() === document.uri.toString()) {
        updateWebview();
      }
    });

    // 步骤7: 监听面板销毁事件
    // 当用户关闭编辑器时，需要清理资源（如事件监听器）
    // 避免内存泄漏
    webviewPanel.onDidDispose(() => {
      changeDocumentSubscription.dispose();
    });

    // 步骤8: 监听来自Webview的消息
    // 这是双向通信的关键：Webview中的React组件可以通过vscode.postMessage()发送消息到这里
    // 消息处理逻辑：
    // - save: 用户点击保存按钮，更新文档内容
    // - requestData: React组件请求加载agent classes和env modules数据
    webviewPanel.webview.onDidReceiveMessage(async (message: any) => {
      switch (message.command) {
        case 'save':
          // 用户点击了"保存设置"按钮
          // 将Webview发送的内容保存到文档中
          // 这会触发文档变化事件，进而更新Webview（通过updateWebview函数）
          await this._updateTextDocument(document, message.content);
          return;

        case 'requestData':
          // React组件在挂载时发送此命令，请求加载agent classes和env modules数据
          // 这是按需加载的方式，避免在初始化时阻塞
          await this._handleRequestData(webviewPanel, parsedContent);
          return;
      }
    });

    // 步骤9: 初始化Webview
    // 发送当前文档内容到Webview，让React组件显示初始设置
    updateWebview();
  }

  /**
   * 处理Webview的数据请求
   * 
   * 当React组件挂载时，会发送requestData命令请求加载agent classes和env modules数据。
   * 这个方法会：
   * 1. 调用后端API获取agent classes列表
   * 2. 调用后端API获取env modules列表
   * 3. 将数据发送回Webview
   * 
   * @param webviewPanel - Webview面板实例，用于发送消息
   * @param currentSettings - 当前文档的设置内容
   * 
   * 错误处理：
   * - 如果API调用失败，会记录错误但不会中断流程
   * - 失败的API会返回空对象，Webview会显示空列表
   */
  private async _handleRequestData(
    webviewPanel: vscode.WebviewPanel,
    currentSettings: any
  ): Promise<void> {
    // 初始化数据对象
    let agentClasses: Record<string, any> = {};
    let envModules: Record<string, any> = {};

    // 步骤1: 获取agent classes列表
    // 调用后端API获取所有可用的agent类
    try {
      const agentsResponse = await this._apiClient.getAgentClasses();
      if (agentsResponse.success) {
        agentClasses = agentsResponse.agents;
      }
    } catch (error) {
      // 如果API调用失败，记录错误但继续执行
      // Webview会显示空列表，用户可以重试
      console.error('Failed to load agent classes:', error);
    }

    // 步骤2: 获取env modules列表
    // 调用后端API获取所有可用的environment模块类
    try {
      const envModulesResponse = await this._apiClient.getEnvModules();
      if (envModulesResponse.success) {
        envModules = envModulesResponse.modules;
      }
    } catch (error) {
      // 如果API调用失败，记录错误但继续执行
      console.error('Failed to load env modules:', error);
    }

    // 步骤3: 发送初始数据到Webview
    // 包含当前设置、agent classes和env modules
    // React组件会接收这个消息并更新UI
    webviewPanel.webview.postMessage({
      command: 'initialData',
      settings: currentSettings,      // 当前文档的设置
      agentClasses: agentClasses,     // agent类列表
      envModules: envModules,          // environment模块列表
    });
  }

  /**
   * 生成Webview的HTML内容
   * 
   * 使用 React 构建的 webview，加载构建后的 HTML 和 JS 文件。
   * 
   * 重要概念：Webview中的JavaScript
   * - Webview中的JavaScript运行在一个隔离的环境中
   * - 不能直接访问Node.js API或VSCode API
   * - 只能通过vscode.postMessage()与扩展通信
   * - 通过acquireVsCodeApi()获取vscode对象
   * 
   * 消息通信流程：
   * 1. Webview JS → vscode.postMessage() → 扩展的onDidReceiveMessage
   * 2. 扩展 → webview.postMessage() → Webview的window.addEventListener('message')
   * 
   * @param webview - Webview实例，用于获取资源URI
   * @param scriptUri - React应用的JavaScript文件URI
   * @param initialSettings - 初始设置数据，通过全局变量传递给React应用
   * @returns HTML字符串
   */
  private _getHtmlForWebview(
    webview: vscode.Webview,
    scriptUri: vscode.Uri,
    initialSettings: any
  ): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SIM Settings Editor</title>
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
      overflow: auto;
    }

    #root {
      min-height: 100vh;
    }
  </style>
</head>
<body>
  <div id="root"></div>
  <script>
    // 通过全局变量传递初始设置到React应用
    // React应用会在index.tsx中读取这个变量
    window.initialSettings = ${JSON.stringify(initialSettings)};
  </script>
  <script src="${scriptUri}"></script>
</body>
</html>`;
  }

  /**
   * 更新文档内容
   * 
   * 当用户在Webview中点击"保存设置"按钮时，会调用这个方法。
   * 这个方法会将Webview发送的内容写入到SIM_SETTINGS.json文件中。
   * 
   * 重要概念：WorkspaceEdit
   * - VSCode使用WorkspaceEdit来批量编辑文档
   * - 可以同时编辑多个文档
   * - 编辑操作是原子的（要么全部成功，要么全部失败）
   * 
   * @param document - 要更新的文档（SIM_SETTINGS.json文件）
   * @param content - 新的文档内容（JSON字符串）
   * 
   * 工作流程：
   * 1. 创建WorkspaceEdit对象
   * 2. 添加替换操作（替换整个文档内容）
   * 3. 应用编辑操作
   * 4. 这会触发文档变化事件，进而更新Webview
   */
  private async _updateTextDocument(
    document: vscode.TextDocument,
    content: string
  ): Promise<void> {
    // 创建WorkspaceEdit对象，用于批量编辑文档
    const edit = new vscode.WorkspaceEdit();

    // 添加替换操作：替换整个文档内容
    // Range(0, 0, document.lineCount, 0)表示从文档开始到结束的范围
    edit.replace(
      document.uri,
      new vscode.Range(0, 0, document.lineCount, 0),
      content
    );

    // 应用编辑操作
    // 这会实际写入文件，并触发文档变化事件
    await vscode.workspace.applyEdit(edit);
  }
}
