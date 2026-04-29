/**
 * HelpPageViewProvider - Help Page Webview Provider
 *
 * Provides a webview for displaying plugin usage guide and help information.
 * Reads content from HELP.md or HELP.en-US.md based on VSCode locale.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

export class HelpPageViewProvider {
  private readonly panel: vscode.WebviewPanel;
  private readonly extensionUri: vscode.Uri;
  private readonly extensionPath: string;
  private disposables: vscode.Disposable[] = [];

  /**
   * Create and show a new help page webview panel
   */
  public static createOrShow(context: vscode.ExtensionContext, viewColumn: vscode.ViewColumn = vscode.ViewColumn.One): HelpPageViewProvider {
    const locale = vscode.env.language;
    const title = locale.startsWith('zh') ? '使用指南 - AI Social Scientist' : 'User Guide - AI Social Scientist';

    const panel = vscode.window.createWebviewPanel(
      'aiSocialScientistHelp',
      title,
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
    this.extensionPath = context.extensionPath;

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
   * Read help content from appropriate HELP.md file based on locale
   */
  private readHelpContent(): string {
    const locale = vscode.env.language;

    // Try locale-specific file first (e.g., HELP.en-US.md for English)
    const localeSpecificPath = path.join(this.extensionPath, `HELP.${locale}.md`);
    if (fs.existsSync(localeSpecificPath)) {
      try {
        return fs.readFileSync(localeSpecificPath, 'utf-8');
      } catch (error) {
        console.error(`Failed to read HELP.${locale}.md:`, error);
      }
    }

    // Try base locale (e.g., HELP.en.md for en-GB, en-AU, etc.)
    const baseLocale = locale.split('-')[0];
    if (baseLocale !== locale) {
      const baseLocalePath = path.join(this.extensionPath, `HELP.${baseLocale}.md`);
      if (fs.existsSync(baseLocalePath)) {
        try {
          return fs.readFileSync(baseLocalePath, 'utf-8');
        } catch (error) {
          console.error(`Failed to read HELP.${baseLocale}.md:`, error);
        }
      }
    }

    // Fall back to default Chinese HELP.md
    const defaultPath = path.join(this.extensionPath, 'HELP.md');
    try {
      if (fs.existsSync(defaultPath)) {
        return fs.readFileSync(defaultPath, 'utf-8');
      }
    } catch (error) {
      console.error('Failed to read HELP.md:', error);
    }

    // Fallback content
    const isZh = locale.startsWith('zh');
    if (isZh) {
      return `# AI Social Scientist 使用指南

帮助文档加载失败，请查看 [README.md](https://github.com/tsinghua-fib-lab/agentsociety) 获取更多信息。

## 快速入口

- [打开配置页面](command:aiSocialScientist.openConfigPage)
- [打开技能市场](command:aiSocialScientist.openSkillMarketplace)
- [后端状态菜单](command:aiSocialScientist.backendStatusMenu)
`;
    }
    return `# AI Social Scientist User Guide

Failed to load help documentation. Please visit [README.md](https://github.com/tsinghua-fib-lab/agentsociety) for more information.

## Quick Links

- [Open Configuration Page](command:aiSocialScientist.openConfigPage)
- [Open Skill Marketplace](command:aiSocialScientist.openSkillMarketplace)
- [Backend Status Menu](command:aiSocialScientist.backendStatusMenu)
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

    const nonce = Math.random().toString(36).slice(2);
    const csp = [
      "default-src 'none'",
      `style-src ${this.panel.webview.cspSource} 'unsafe-inline'`,
      `script-src ${this.panel.webview.cspSource} 'nonce-${nonce}'`,
      `font-src ${this.panel.webview.cspSource}`,
    ].join('; ');

    // Determine language for HTML
    const locale = vscode.env.language;
    const htmlLang = locale.startsWith('zh') ? 'zh-CN' : 'en-US';
    const title = locale.startsWith('zh') ? '使用指南 - AI Social Scientist' : 'User Guide - AI Social Scientist';

    // Escape the help content for embedding in JavaScript
    const escapedContent = helpContent
      .replace(/\\/g, '\\\\')
      .replace(/`/g, '\\`')
      .replace(/\$/g, '\\$');

    return `<!DOCTYPE html>
<html lang="${htmlLang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="${csp}">
    <title>${title}</title>
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
    <script nonce="${nonce}">window.HELP_CONTENT = \`${escapedContent}\`;</script>
    <script nonce="${nonce}" src="${scriptUri}"></script>
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
