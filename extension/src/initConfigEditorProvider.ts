/**
 * Init Config 编辑器提供者 (Init Config Editor Provider)
 *
 * 为 init_config.json 文件提供图形化编辑器。
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，注册 CustomEditorProvider
 * - @extension/src/webview/initConfig/ - 前端React组件 (编译后为initConfig.js)
 */

import * as vscode from 'vscode';
import * as path from 'path';

/**
 * Init Config 编辑器提供者类
 *
 * 实现了 VSCode 的 CustomTextEditorProvider 接口，为 init_config.json 文件提供图形化编辑器。
 */
export class InitConfigEditorProvider implements vscode.CustomTextEditorProvider {
  /**
   * 扩展上下文
   */
  private readonly _context: vscode.ExtensionContext;

  /**
   * 构造函数
   */
  constructor(context: vscode.ExtensionContext) {
    this._context = context;
  }

  /**
   * 解析自定义文本编辑器
   */
  public async resolveCustomTextEditor(
    document: vscode.TextDocument,
    webviewPanel: vscode.WebviewPanel,
    _token: vscode.CancellationToken
  ): Promise<void> {
    // 配置 Webview 选项
    const webviewResourceRoot = vscode.Uri.file(
      path.join(this._context.extensionPath, 'out', 'webview')
    );
    webviewPanel.webview.options = {
      enableScripts: true,
      localResourceRoots: [webviewResourceRoot],
    };

    // 解析当前文档内容
    const content = document.getText();
    let parsedConfig: any = {};
    try {
      parsedConfig = JSON.parse(content);
    } catch {
      parsedConfig = {};
    }

    // 获取 React 应用的脚本 URI
    const scriptPath = vscode.Uri.file(
      path.join(this._context.extensionPath, 'out', 'webview', 'initConfig.js')
    );
    const scriptUri = webviewPanel.webview.asWebviewUri(scriptPath);

    // 设置 Webview 的 HTML 内容
    webviewPanel.webview.html = this._getHtmlForWebview(
      webviewPanel.webview,
      scriptUri,
      parsedConfig
    );

    // 更新 Webview 的函数
    const updateWebview = () => {
      const currentContent = document.getText();
      let currentConfig: any = {};
      try {
        currentConfig = JSON.parse(currentContent);
      } catch {
        currentConfig = {};
      }

      webviewPanel.webview.postMessage({
        command: 'update',
        config: currentConfig,
      });
    };

    // 监听文档变化事件
    const changeDocumentSubscription = vscode.workspace.onDidChangeTextDocument((e) => {
      if (e.document.uri.toString() === document.uri.toString()) {
        updateWebview();
      }
    });

    // 监听面板销毁事件
    webviewPanel.onDidDispose(() => {
      changeDocumentSubscription.dispose();
    });

    // 监听来自 Webview 的消息
    webviewPanel.webview.onDidReceiveMessage(async (message: any) => {
      switch (message.command) {
        case 'save':
          await this._updateTextDocument(document, message.content);
          return;

        case 'requestData':
          webviewPanel.webview.postMessage({
            command: 'initialData',
            config: parsedConfig,
          });
          return;
      }
    });

    // 初始化 Webview
    updateWebview();
  }

  /**
   * 生成 Webview 的 HTML 内容
   */
  private _getHtmlForWebview(
    webview: vscode.Webview,
    scriptUri: vscode.Uri,
    initialConfig: any
  ): string {
    const nonce = Array.from({ length: 32 }, () => Math.random().toString(36)[2]).join('');
    const csp = [
      "default-src 'none'",
      `img-src ${webview.cspSource} data:`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src ${webview.cspSource} 'nonce-${nonce}'`,
      `connect-src ${webview.cspSource} http://127.0.0.1:* http://localhost:*`,
    ].join('; ');

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <title>Init Config Editor</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
      background: var(--vscode-editor-background);
      color: var(--vscode-editor-foreground);
      height: 100vh;
      overflow: auto;
    }
    #root { min-height: 100vh; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}">
    window.initialConfig = ${JSON.stringify(initialConfig)};
  </script>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }

  /**
   * 更新文档内容
   */
  private async _updateTextDocument(
    document: vscode.TextDocument,
    content: string
  ): Promise<void> {
    const edit = new vscode.WorkspaceEdit();
    edit.replace(
      document.uri,
      new vscode.Range(0, 0, document.lineCount, 0),
      content
    );
    await vscode.workspace.applyEdit(edit);
  }
}
