/**
 * YAML 文件可视化查看器
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as yaml from 'js-yaml';

const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_DUMP_RENDER_BYTES = 2 * 1024 * 1024;

export class YamlViewer {
  private static currentPanel: vscode.WebviewPanel | undefined;

  private static escapeHtmlText(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  public static async show(filePath: string, title?: string): Promise<void> {
    let data: any = {};
    let error: string | null = null;
    let yamlDumped = '';
    const isZh = vscode.env.language.startsWith('zh');

    try {
      const stat = fs.statSync(filePath);
      if (stat.size > MAX_FILE_BYTES) {
        error = isZh
          ? `文件过大（>${Math.floor(MAX_FILE_BYTES / 1024 / 1024)}MB），请用编辑器打开`
          : `File too large (>${Math.floor(MAX_FILE_BYTES / 1024 / 1024)}MB); open it in the editor instead`;
      } else {
        const content = fs.readFileSync(filePath, 'utf-8');
        data = yaml.load(content) ?? {};
        yamlDumped = yaml.dump(data, { indent: 2, lineWidth: -1 });
        if (Buffer.byteLength(yamlDumped, 'utf8') > MAX_DUMP_RENDER_BYTES) {
          error = isZh
            ? `格式化后体积过大（>${Math.floor(MAX_DUMP_RENDER_BYTES / 1024 / 1024)}MB），无法在预览中安全渲染，请用编辑器打开`
            : `Formatted YAML too large (>${Math.floor(MAX_DUMP_RENDER_BYTES / 1024 / 1024)}MB); open it in the editor`;
          data = {};
          yamlDumped = '';
        }
      }
    } catch (e: any) {
      error = e.message;
    }

    const fileName = filePath.split(/[/\\]/).pop() || 'YAML';
    const panelTitle = title || fileName;

    if (this.currentPanel) {
      this.currentPanel.title = panelTitle;
      this.currentPanel.reveal(vscode.ViewColumn.One);
      this.updateWebview(this.currentPanel, data, error, filePath, yamlDumped);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      'yamlViewer',
      panelTitle,
      vscode.ViewColumn.One,
      { enableScripts: true, retainContextWhenHidden: true }
    );

    this.currentPanel = panel;
    panel.onDidDispose(() => { this.currentPanel = undefined; });
    this.updateWebview(panel, data, error, filePath, yamlDumped);
  }

  private static updateWebview(
    panel: vscode.WebviewPanel,
    data: any,
    error: string | null,
    filePath: string,
    yamlDumped: string
  ): void {
    const isChinese = vscode.env.language.startsWith('zh');
    panel.webview.html = this.getHtml(data, error, filePath, isChinese, yamlDumped);
  }

  private static getHtml(
    data: any,
    error: string | null,
    filePath: string,
    isChinese: boolean,
    yamlDumped: string
  ): string {
    const safePathDisplay = this.escapeHtmlText(filePath);
    const labels = {
      title: isChinese ? 'YAML 查看器' : 'YAML Viewer',
      error: isChinese ? '解析错误' : 'Parse Error',
      copy: isChinese ? '复制 YAML' : 'Copy YAML',
      copyJson: isChinese ? '复制为 JSON' : 'Copy as JSON',
      path: isChinese ? '文件路径' : 'File Path',
    };

    const yamlStr = error ? '' : yamlDumped;

    return `<!DOCTYPE html>
<html lang="${isChinese ? 'zh-CN' : 'en'}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${labels.title}</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: var(--vscode-font-family);
      background-color: var(--vscode-editor-background);
      color: var(--vscode-editor-foreground);
      padding: 16px;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--vscode-panel-border);
    }
    .header h1 { font-size: 18px; }
    .header-actions { display: flex; gap: 8px; }
    .btn {
      padding: 6px 12px;
      background: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }
    .btn:hover { background: var(--vscode-button-secondaryHoverBackground); }
    .btn.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
    .meta {
      margin-bottom: 12px;
      font-size: 12px;
      color: var(--vscode-descriptionForeground);
    }
    .yaml-container {
      background: var(--vscode-editor-background);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 6px;
      overflow: auto;
      max-height: calc(100vh - 160px);
    }
    .yaml-content {
      padding: 12px;
      font-family: var(--vscode-editor-font-family);
      font-size: 13px;
      white-space: pre;
    }
    .yaml-key { color: #9cdcfe; }
    .yaml-value { color: #ce9178; }
    .yaml-number { color: #b5cea8; }
    .yaml-bool { color: #569cd6; }
    .yaml-comment { color: #6a9955; }
    .error-box {
      padding: 16px;
      background: rgba(255, 77, 79, 0.1);
      border: 1px solid #ff4d4f;
      border-radius: 6px;
      color: #ff4d4f;
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>📄 ${labels.title}</h1>
    <div class="header-actions">
      <button class="btn" id="copyJsonBtn">${labels.copyJson}</button>
      <button class="btn primary" id="copyBtn">${labels.copy}</button>
    </div>
  </div>
  
  <div class="meta">${labels.path}: ${safePathDisplay}</div>
  
  ${error ? `
    <div class="error-box">
      <strong>${labels.error}:</strong> ${error}
    </div>
  ` : `
    <div class="yaml-container">
      <pre class="yaml-content" id="yamlContent"></pre>
    </div>
  `}

  <script>
    const yamlData = ${error ? 'null' : JSON.stringify(data)};
    const yamlStr = ${error ? '""' : JSON.stringify(yamlStr)};
    const isChinese = ${isChinese ? 'true' : 'false'};
    
    function highlightYaml(str) {
      return str
        .replace(/^(\\s*)([a-zA-Z_][a-zA-Z0-9_]*)(:)/gm, '$1<span class="yaml-key">$2</span>$3')
        .replace(/:\\s*"([^"]*)"/g, ': <span class="yaml-value">"$1"</span>')
        .replace(/:\\s*(\\d+)/g, ': <span class="yaml-number">$1</span>')
        .replace(/:\\s*(true|false)/g, ': <span class="yaml-bool">$1</span>')
        .replace(/(#.*)$/gm, '<span class="yaml-comment">$1</span>');
    }
    
    if (yamlStr) {
      document.getElementById('yamlContent').innerHTML = highlightYaml(yamlStr);
    }
    
    document.getElementById('copyBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(yamlStr).then(() => {
        this.textContent = isChinese ? '已复制' : 'Copied';
        setTimeout(() => { this.textContent = '${labels.copy}'; }, 2000);
      });
    });
    
    document.getElementById('copyJsonBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(JSON.stringify(yamlData, null, 2)).then(() => {
        this.textContent = isChinese ? '已复制' : 'Copied';
        setTimeout(() => { this.textContent = '${labels.copyJson}'; }, 2000);
      });
    });
  </script>
</body>
</html>`;
  }
}
