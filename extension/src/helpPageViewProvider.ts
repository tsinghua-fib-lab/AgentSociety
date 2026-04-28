/**
 * HelpPageViewProvider - Help Page Webview Provider
 *
 * Provides a webview for displaying plugin usage guide and help information.
 * Reads content from HELP.md file for easy maintenance.
 *
 * 关联文件：
 * - @extension/HELP.md - 帮助文档源文件（Markdown格式）
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

export class HelpPageViewProvider {
  private readonly panel: vscode.WebviewPanel;
  private readonly extensionUri: vscode.Uri;
  private readonly helpMdPath: string;
  private disposables: vscode.Disposable[] = [];

  /**
   * Create and show a new help page webview panel
   */
  public static createOrShow(context: vscode.ExtensionContext, viewColumn: vscode.ViewColumn = vscode.ViewColumn.One): HelpPageViewProvider {
    const panel = vscode.window.createWebviewPanel(
      'aiSocialScientistHelp',
      '使用指南 - AI Social Scientist',
      viewColumn,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [context.extensionUri],
      }
    );

    return new HelpPageViewProvider(panel, context);
  }

  private constructor(panel: vscode.WebviewPanel, context: vscode.ExtensionContext) {
    this.panel = panel;
    this.extensionUri = context.extensionUri;
    this.helpMdPath = path.join(context.extensionPath, 'HELP.md');

    // Set webview content
    this.updateWebviewContent();

    // Register event listeners
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);

    this.panel.webview.onDidReceiveMessage(
      async (message: { command: string; commandId?: string; url?: string }) => {
        switch (message.command) {
          case 'openCommand':
            if (message.commandId) {
              await vscode.commands.executeCommand(message.commandId);
            }
            break;
          case 'openUrl':
            if (message.url) {
              await vscode.env.openExternal(vscode.Uri.parse(message.url));
            }
            break;
        }
      },
      null,
      this.disposables
    );
  }

  /**
   * Read help content from HELP.md file
   */
  private readHelpContent(): string {
    try {
      if (fs.existsSync(this.helpMdPath)) {
        return fs.readFileSync(this.helpMdPath, 'utf-8');
      }
    } catch (error) {
      console.error('Failed to read HELP.md:', error);
    }
    // Fallback content
    return `# AI Social Scientist 使用指南

帮助文档加载失败，请查看 [README.md](https://github.com/tsinghua-fib-lab/agentsociety) 获取更多信息。

## 快速入口

- [打开配置页面](command:aiSocialScientist.openConfigPage)
- [打开技能市场](command:aiSocialScientist.openSkillMarketplace)
- [后端状态菜单](command:aiSocialScientist.backendStatusMenu)
`;
  }

  /**
   * Update webview content
   */
  private updateWebviewContent(): void {
    const helpContent = this.readHelpContent();
    this.panel.webview.html = this.getHtmlForWebview(helpContent);
  }

  /**
   * Generate HTML for webview
   */
  private getHtmlForWebview(helpContent: string): string {
    const scriptUri = this.panel.webview.asWebviewUri(
      vscode.Uri.file(path.join(this.extensionUri.fsPath, 'out', 'webview', 'helpPage.js'))
    );

    const csp = [
      "default-src 'none'",
      `style-src ${this.panel.webview.cspSource} 'unsafe-inline'`,
      `script-src ${this.panel.webview.cspSource}`,
      `font-src ${this.panel.webview.cspSource}`,
    ].join('; ');

    // Escape the help content for embedding in JavaScript
    const escapedContent = helpContent
      .replace(/\\/g, '\\\\')
      .replace(/`/g, '\\`')
      .replace(/\$/g, '\\$');

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="${csp}">
    <title>使用指南 - AI Social Scientist</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        html,
        body {
            height: 100%;
            width: 100%;
        }

        body {
            font-family: var(--vscode-font-family);
            font-size: var(--vscode-font-size);
            background-color: var(--vscode-editor-background);
            color: var(--vscode-editor-foreground);
        }

        #root {
            height: 100%;
            width: 100%;
        }
    </style>
</head>
<body>
    <div id="root"></div>
    <script>window.HELP_CONTENT = \`${escapedContent}\`;</script>
    <script src="${scriptUri}"></script>
</body>
</html>`;
  }

  /**
   * Dispose the webview panel and resources
   */
  public dispose(): void {
    this.disposables.forEach((d) => d.dispose());
    this.disposables = [];
  }
}
