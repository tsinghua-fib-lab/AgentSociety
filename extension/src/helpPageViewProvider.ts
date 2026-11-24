/**
 * HelpPageViewProvider - Help Page Webview Provider
 *
 * Embeds ReadTheDocs documentation as the primary help source,
 * with a short inline offline fallback when the iframe cannot load.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import { getCurrentLanguageCode } from './i18n';

const RTD_BASE_URL = 'https://agentsociety2.readthedocs.io';

export class HelpPageViewProvider {
  private readonly panel: vscode.WebviewPanel;
  private readonly extensionUri: vscode.Uri;
  private disposables: vscode.Disposable[] = [];

  public static currentPanel: HelpPageViewProvider | undefined;

  /**
   * Create a new help page panel or reveal the existing one.
   */
  public static createOrShow(context: vscode.ExtensionContext, viewColumn: vscode.ViewColumn = vscode.ViewColumn.One): HelpPageViewProvider {
    if (HelpPageViewProvider.currentPanel) {
      HelpPageViewProvider.currentPanel.panel.reveal(viewColumn);
      return HelpPageViewProvider.currentPanel;
    }

    const isZh = getCurrentLanguageCode() === 'zh-CN';
    const title = isZh ? '使用指南 - AI Social Scientist' : 'User Guide - AI Social Scientist';

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

    HelpPageViewProvider.currentPanel = new HelpPageViewProvider(panel, context);
    return HelpPageViewProvider.currentPanel;
  }

  private constructor(panel: vscode.WebviewPanel, context: vscode.ExtensionContext) {
    this.panel = panel;
    this.extensionUri = context.extensionUri;

    this.updateWebviewContent();

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

  public reloadForLanguage(): void {
    const isZh = getCurrentLanguageCode() === 'zh-CN';
    this.panel.title = isZh ? '使用指南 - AI Social Scientist' : 'User Guide - AI Social Scientist';
    this.updateWebviewContent();
  }

  public static reloadLanguageIfOpen(): void {
    HelpPageViewProvider.currentPanel?.reloadForLanguage();
  }

  private offlineHelpContent(): string {
    const isZh = getCurrentLanguageCode() === 'zh-CN';
    const rtdUrl = this.getRtdUrl();
    if (isZh) {
      return `# AI Social Scientist 使用指南

完整文档见 [ReadTheDocs](${rtdUrl})。

## 快速入口

- [打开配置页面](command:aiSocialScientist.openConfigPage)
- [打开技能管理](command:aiSocialScientist.openSkillMarketplace)
- [导出工作区](command:aiSocialScientist.exportWorkspaceZip)
- [导入工作区](command:aiSocialScientist.importWorkspaceZip)
- [打开快速入门](command:aiSocialScientist.openWalkthrough)
`;
    }
    return `# AI Social Scientist User Guide

Read the full guide on [ReadTheDocs](${rtdUrl}).

## Quick Links

- [Open configuration](command:aiSocialScientist.openConfigPage)
- [Open skill management](command:aiSocialScientist.openSkillMarketplace)
- [Export workspace](command:aiSocialScientist.exportWorkspaceZip)
- [Import workspace](command:aiSocialScientist.importWorkspaceZip)
- [Open getting started](command:aiSocialScientist.openWalkthrough)
`;
  }

  private getRtdUrl(): string {
    const isZh = getCurrentLanguageCode() === 'zh-CN';
    return isZh ? `${RTD_BASE_URL}/zh_CN/latest/` : `${RTD_BASE_URL}/en/latest/`;
  }

  private updateWebviewContent(): void {
    const helpContent = this.offlineHelpContent();
    const rtdUrl = this.getRtdUrl();
    this.panel.webview.html = this.getHtmlForWebview(helpContent, rtdUrl);
  }

  private getHtmlForWebview(helpContent: string, rtdUrl: string): string {
    const scriptUri = this.panel.webview.asWebviewUri(
      vscode.Uri.file(path.join(this.extensionUri.fsPath, 'out', 'webview', 'helpPage.js'))
    );

    const nonce = Math.random().toString(36).slice(2);
    const csp = [
      "default-src 'none'",
      `style-src ${this.panel.webview.cspSource} 'unsafe-inline' https://assets.readthedocs.org https://cdnjs.cloudflare.com`,
      `script-src ${this.panel.webview.cspSource} 'nonce-${nonce}'`,
      `font-src ${this.panel.webview.cspSource} https://assets.readthedocs.org https://cdnjs.cloudflare.com`,
      `frame-src ${RTD_BASE_URL} https://readthedocs.org`,
      `img-src ${this.panel.webview.cspSource} https://assets.readthedocs.org https://cdnjs.cloudflare.com data:`,
      `connect-src ${RTD_BASE_URL} https://assets.readthedocs.org`,
    ].join('; ');

    const htmlLang = getCurrentLanguageCode();
    const title = htmlLang === 'zh-CN' ? '使用指南 - AI Social Scientist' : 'User Guide - AI Social Scientist';

    const jsonHelpContent = JSON.stringify(helpContent);
    const jsonRtdUrl = JSON.stringify(rtdUrl);

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
    <script nonce="${nonce}">window.__AS_LANG__ = ${JSON.stringify(htmlLang)}; window.HELP_CONTENT = ${jsonHelpContent};</script>
    <script nonce="${nonce}">window.RTD_URL = ${jsonRtdUrl};</script>
    <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }

  public dispose(): void {
    HelpPageViewProvider.currentPanel = undefined;
    while (this.disposables.length) {
      const d = this.disposables.pop();
      if (d) {
        d.dispose();
      }
    }
  }
}
