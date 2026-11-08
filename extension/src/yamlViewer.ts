/**
 * YAML 文件可视化查看器
 * 支持语法高亮、折叠、搜索、导出 JSON
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as yaml from 'js-yaml';
import { isExtensionZh } from './i18n';

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
    const isZh = isExtensionZh();

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
    const isChinese = isExtensionZh();
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
    const pathLiteral = JSON.stringify(filePath);
    const fileSize = error ? 0 : Buffer.byteLength(yamlDumped, 'utf8');
    const fileSizeStr = fileSize > 1024 ? `${(fileSize / 1024).toFixed(1)} KB` : `${fileSize} B`;
    const labels = {
      title: isChinese ? 'YAML 查看器' : 'YAML Viewer',
      error: isChinese ? '解析错误' : 'Parse Error',
      copy: isChinese ? '复制 YAML' : 'Copy YAML',
      copyJson: isChinese ? '复制为 JSON' : 'Copy as JSON',
      copyPath: isChinese ? '复制路径' : 'Copy Path',
      collapse: isChinese ? '全部折叠' : 'Collapse All',
      expand: isChinese ? '全部展开' : 'Expand All',
      search: isChinese ? '搜索...' : 'Search...',
      path: isChinese ? '文件路径' : 'File Path',
      size: isChinese ? '大小' : 'Size',
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
    .header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
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
    .btn.primary:hover { background: var(--vscode-button-hoverBackground); }
    .meta {
      display: flex;
      gap: 24px;
      margin-bottom: 12px;
      font-size: 12px;
      color: var(--vscode-descriptionForeground);
    }
    .search-box {
      margin-bottom: 12px;
    }
    .search-box input {
      width: 100%;
      padding: 8px 12px;
      background: var(--vscode-input-background);
      border: 1px solid var(--vscode-input-border);
      border-radius: 4px;
      color: var(--vscode-input-foreground);
      font-size: 13px;
    }
    .search-box input:focus { outline: 1px solid var(--vscode-focusBorder); }
    .yaml-container {
      background: var(--vscode-editor-background);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 6px;
      overflow: auto;
      max-height: calc(100vh - 220px);
    }
    .yaml-content {
      padding: 12px;
      font-family: var(--vscode-editor-font-family);
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .yaml-line { display: block; }
    .yaml-line:hover { background: var(--vscode-list-hoverBackground); }
    .yaml-key { color: #9cdcfe; }
    .yaml-value { color: #ce9178; }
    .yaml-number { color: #b5cea8; }
    .yaml-bool { color: #569cd6; }
    .yaml-comment { color: #6a9955; }
    .yaml-highlight { background: rgba(255, 215, 0, 0.3); }
    .error-box {
      padding: 16px;
      background: rgba(255, 77, 79, 0.1);
      border: 1px solid #ff4d4f;
      border-radius: 6px;
      color: #ff4d4f;
    }
    .collapsible { cursor: pointer; user-select: none; }
    .collapsible::before {
      content: '▼'; display: inline-block; margin-right: 4px;
      font-size: 10px; transition: transform 0.2s;
    }
    .collapsible.collapsed::before { transform: rotate(-90deg); }
    .collapsible-content { margin-left: 20px; }
    .collapsible-content.hidden { display: none; }
  </style>
</head>
<body>
  <div class="header">
    <h1>📄 ${labels.title}</h1>
    <div class="header-actions">
      <button class="btn" id="copyPathBtn">📋 ${labels.copyPath}</button>
      <button class="btn" id="collapseBtn">${labels.collapse}</button>
      <button class="btn" id="expandBtn">${labels.expand}</button>
      <button class="btn" id="copyJsonBtn">${labels.copyJson}</button>
      <button class="btn primary" id="copyBtn">${labels.copy}</button>
    </div>
  </div>

  <div class="meta">
    <span>${labels.path}: ${safePathDisplay}</span>
    <span>${labels.size}: ${fileSizeStr}</span>
  </div>

  <div class="search-box">
    <input type="text" id="searchInput" placeholder="${labels.search}" />
  </div>

  ${error ? `
    <div class="error-box">
      <strong>${labels.error}:</strong> ${YamlViewer.escapeHtmlText(String(error))}
    </div>
  ` : `
    <div class="yaml-container">
      <div class="yaml-content" id="yamlContent"></div>
    </div>
  `}

  <script>
    const yamlData = ${error ? 'null' : JSON.stringify(data).replace(/</g, '\\u003c')};
    const yamlStr = ${error ? '""' : JSON.stringify(yamlStr).replace(/</g, '\\u003c')};
    const isChinese = ${isChinese ? 'true' : 'false'};

    function renderYamlTree(obj, indent) {
      if (obj === null || obj === undefined) return '<span class="yaml-bool">null</span>';
      if (typeof obj === 'boolean') return '<span class="yaml-bool">' + obj + '</span>';
      if (typeof obj === 'number') return '<span class="yaml-number">' + obj + '</span>';
      if (typeof obj === 'string') {
        if (obj.includes('\\n') || obj.length > 80) return '<span class="yaml-value">' + esc(obj) + '</span>';
        return '<span class="yaml-value">' + esc(obj) + '</span>';
      }
      if (Array.isArray(obj)) {
        if (obj.length === 0) return '<span class="yaml-bool">[]</span>';
        const id = 'arr_' + Math.random().toString(36).substr(2, 9);
        let h = '<span class="collapsible" onclick="toggle(\\'' + id + '\\')">[<span class="yaml-number">' + obj.length + ' items</span>]</span>';
        h += '<div class="collapsible-content" id="' + id + '">';
        obj.forEach((item, i) => {
          h += '<div class="yaml-line">' + '  '.repeat(indent + 1) + '- ' + renderYamlTree(item, indent + 1) + '</div>';
        });
        h += '</div>';
        return h;
      }
      if (typeof obj === 'object') {
        const keys = Object.keys(obj);
        if (keys.length === 0) return '<span class="yaml-bool">{}</span>';
        const id = 'obj_' + Math.random().toString(36).substr(2, 9);
        let h = '<span class="collapsible" onclick="toggle(\\'' + id + '\\')">{<span class="yaml-number">' + keys.length + ' keys</span>}</span>';
        h += '<div class="collapsible-content" id="' + id + '">';
        keys.forEach((key) => {
          h += '<div class="yaml-line">' + '  '.repeat(indent + 1) + '<span class="yaml-key">' + esc(key) + '</span>: ' + renderYamlTree(obj[key], indent + 1) + '</div>';
        });
        h += '</div>';
        return h;
      }
      return String(obj);
    }

    function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
    function toggle(id) { var e=document.getElementById(id); var t=e.previousElementSibling; e.classList.toggle('hidden'); t.classList.toggle('collapsed'); }

    if (yamlData) {
      document.getElementById('yamlContent').innerHTML = renderYamlTree(yamlData, 0);
    }

    document.getElementById('copyBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(yamlStr).then(function() {
        this.textContent = isChinese ? '已复制' : 'Copied';
        setTimeout(() => { this.textContent = '${labels.copy}'; }, 2000);
      }.bind(this));
    });
    document.getElementById('copyJsonBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(JSON.stringify(yamlData, null, 2)).then(function() {
        this.textContent = isChinese ? '已复制' : 'Copied';
        setTimeout(() => { this.textContent = '${labels.copyJson}'; }, 2000);
      }.bind(this));
    });
    document.getElementById('copyPathBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(${pathLiteral}).then(function() {
        this.textContent = isChinese ? '已复制' : 'Copied';
        setTimeout(() => { this.textContent = isChinese ? '复制路径' : 'Copy Path'; }, 2000);
      }.bind(this));
    });
    document.getElementById('collapseBtn').addEventListener('click', function() {
      document.querySelectorAll('.collapsible-content').forEach(function(e) { e.classList.add('hidden'); });
      document.querySelectorAll('.collapsible').forEach(function(e) { e.classList.add('collapsed'); });
    });
    document.getElementById('expandBtn').addEventListener('click', function() {
      document.querySelectorAll('.collapsible-content').forEach(function(e) { e.classList.remove('hidden'); });
      document.querySelectorAll('.collapsible').forEach(function(e) { e.classList.remove('collapsed'); });
    });
    document.getElementById('searchInput').addEventListener('input', function() {
      var q = this.value.toLowerCase();
      document.querySelectorAll('.yaml-line').forEach(function(line) {
        if (q && line.textContent.toLowerCase().indexOf(q) >= 0) {
          line.classList.add('yaml-highlight');
        } else {
          line.classList.remove('yaml-highlight');
        }
      });
    });
  </script>
</body>
</html>`;
  }
}