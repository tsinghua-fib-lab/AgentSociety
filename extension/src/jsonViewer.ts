/**
 * JSON 文件可视化查看器
 * 
 * 提供格式化的 JSON 数据展示，支持折叠展开
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import { isExtensionZh } from './i18n';

const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_PRETTY_RENDER_BYTES = 2 * 1024 * 1024;

export class JsonViewer {
  private static currentPanel: vscode.WebviewPanel | undefined;

  private static escapeHtmlText(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  public static async show(filePath: string, title?: string): Promise<void> {
    let data: any = {};
    let error: string | null = null;
    const isZh = isExtensionZh();

    try {
      const stat = fs.statSync(filePath);
      if (stat.size > MAX_FILE_BYTES) {
        error = isZh
          ? `文件过大（>${Math.floor(MAX_FILE_BYTES / 1024 / 1024)}MB），请用编辑器打开`
          : `File too large (>${Math.floor(MAX_FILE_BYTES / 1024 / 1024)}MB); open it in the editor instead`;
      } else {
        const content = fs.readFileSync(filePath, 'utf-8');
        data = JSON.parse(content);
        const pretty = JSON.stringify(data, null, 2);
        if (Buffer.byteLength(pretty, 'utf8') > MAX_PRETTY_RENDER_BYTES) {
          error = isZh
            ? `格式化后体积过大（>${Math.floor(MAX_PRETTY_RENDER_BYTES / 1024 / 1024)}MB），无法在预览中安全渲染，请用编辑器打开`
            : `Pretty-printed JSON too large (>${Math.floor(MAX_PRETTY_RENDER_BYTES / 1024 / 1024)}MB); open it in the editor`;
          data = {};
        }
      }
    } catch (e: any) {
      error = e.message;
    }

    const fileName = filePath.split(/[/\\]/).pop() || 'JSON';
    const panelTitle = title || fileName;

    if (this.currentPanel) {
      this.currentPanel.title = panelTitle;
      this.currentPanel.reveal(vscode.ViewColumn.One);
      this.updateWebview(this.currentPanel, data, error, filePath);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      'jsonViewer',
      panelTitle,
      vscode.ViewColumn.One,
      { enableScripts: true, retainContextWhenHidden: true }
    );

    this.currentPanel = panel;
    panel.onDidDispose(() => { this.currentPanel = undefined; });
    this.updateWebview(panel, data, error, filePath);
  }

  private static updateWebview(
    panel: vscode.WebviewPanel,
    data: any,
    error: string | null,
    filePath: string
  ): void {
    const isChinese = isExtensionZh();
    panel.webview.html = this.getHtml(data, error, filePath, isChinese);
  }

  private static getHtml(data: any, error: string | null, filePath: string, isChinese: boolean): string {
    const safePathDisplay = this.escapeHtmlText(filePath);
    const pathLiteral = JSON.stringify(filePath);
    const labels = {
      title: isChinese ? 'JSON 查看器' : 'JSON Viewer',
      error: isChinese ? '解析错误' : 'Parse Error',
      copy: isChinese ? '复制 JSON' : 'Copy JSON',
      collapse: isChinese ? '全部折叠' : 'Collapse All',
      expand: isChinese ? '全部展开' : 'Expand All',
      search: isChinese ? '搜索...' : 'Search...',
      path: isChinese ? '文件路径' : 'File Path',
      size: isChinese ? '大小' : 'Size',
    };

    const jsonStr = error ? '' : JSON.stringify(data, null, 2);
    const fileSize = error ? 0 : Buffer.byteLength(jsonStr, 'utf8');
    const fileSizeStr = fileSize > 1024 ? `${(fileSize / 1024).toFixed(1)} KB` : `${fileSize} B`;

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
    .json-container {
      background: var(--vscode-editor-background);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 6px;
      overflow: auto;
      max-height: calc(100vh - 200px);
    }
    .json-content {
      padding: 12px;
      font-family: var(--vscode-editor-font-family);
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .json-line { display: block; }
    .json-line:hover { background: var(--vscode-list-hoverBackground); }
    .json-key { color: #9cdcfe; }
    .json-string { color: #ce9178; }
    .json-number { color: #b5cea8; }
    .json-boolean { color: #569cd6; }
    .json-null { color: #569cd6; }
    .json-bracket { color: var(--vscode-editor-foreground); }
    .json-highlight { background: rgba(255, 215, 0, 0.3); }
    .error-box {
      padding: 16px;
      background: rgba(255, 77, 79, 0.1);
      border: 1px solid #ff4d4f;
      border-radius: 6px;
      color: #ff4d4f;
    }
    .collapsible {
      cursor: pointer;
      user-select: none;
    }
    .collapsible::before {
      content: '▼';
      display: inline-block;
      margin-right: 4px;
      font-size: 10px;
      transition: transform 0.2s;
    }
    .collapsible.collapsed::before {
      transform: rotate(-90deg);
    }
    .collapsible-content {
      margin-left: 16px;
    }
    .collapsible-content.hidden { display: none; }
  </style>
</head>
<body>
  <div class="header">
    <h1>📄 ${labels.title}</h1>
    <div class="header-actions">
      <button class="btn" id="copyPathBtn">📋 ${isChinese ? '复制路径' : 'Copy Path'}</button>
      <button class="btn" id="collapseBtn">${labels.collapse}</button>
      <button class="btn" id="expandBtn">${labels.expand}</button>
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
      <strong>${labels.error}:</strong> ${JsonViewer.escapeHtmlText(String(error))}
    </div>
  ` : `
    <div class="json-container">
      <div class="json-content" id="jsonContent"></div>
    </div>
  `}

  <script>
    const jsonData = ${error ? 'null' : JSON.stringify(data).replace(/</g, '\\u003c')};
    const isChinese = ${isChinese ? 'true' : 'false'};
    
    function renderJson(obj, indent = 0) {
      if (obj === null) return '<span class="json-null">null</span>';
      if (typeof obj === 'boolean') return '<span class="json-boolean">' + obj + '</span>';
      if (typeof obj === 'number') return '<span class="json-number">' + obj + '</span>';
      if (typeof obj === 'string') return '<span class="json-string">"' + escapeHtml(obj) + '"</span>';
      
      if (Array.isArray(obj)) {
        if (obj.length === 0) return '<span class="json-bracket">[]</span>';
        const id = 'arr_' + Math.random().toString(36).substr(2, 9);
        let html = '<span class="collapsible" onclick="toggleCollapse(\\'' + id + '\\')"><span class="json-bracket">[</span></span>';
        html += '<div class="collapsible-content" id="' + id + '">';
        obj.forEach((item, i) => {
          html += '<div class="json-line">' + '  '.repeat(indent + 1) + renderJson(item, indent + 1);
          if (i < obj.length - 1) html += '<span class="json-bracket">,</span>';
          html += '</div>';
        });
        html += '</div><span class="json-line">' + '  '.repeat(indent) + '<span class="json-bracket">]</span></span>';
        return html;
      }
      
      if (typeof obj === 'object') {
        const keys = Object.keys(obj);
        if (keys.length === 0) return '<span class="json-bracket">{}</span>';
        const id = 'obj_' + Math.random().toString(36).substr(2, 9);
        let html = '<span class="collapsible" onclick="toggleCollapse(\\'' + id + '\\')"><span class="json-bracket">{</span></span>';
        html += '<div class="collapsible-content" id="' + id + '">';
        keys.forEach((key, i) => {
          html += '<div class="json-line">' + '  '.repeat(indent + 1) + '<span class="json-key">"' + escapeHtml(key) + '"</span>: ' + renderJson(obj[key], indent + 1);
          if (i < keys.length - 1) html += '<span class="json-bracket">,</span>';
          html += '</div>';
        });
        html += '</div><span class="json-line">' + '  '.repeat(indent) + '<span class="json-bracket">}</span></span>';
        return html;
      }
      
      return String(obj);
    }
    
    function escapeHtml(str) {
      return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    
    function toggleCollapse(id) {
      const el = document.getElementById(id);
      const trigger = el.previousElementSibling;
      el.classList.toggle('hidden');
      trigger.classList.toggle('collapsed');
    }
    
    if (jsonData) {
      document.getElementById('jsonContent').innerHTML = renderJson(jsonData);
    }
    
    document.getElementById('copyBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(JSON.stringify(jsonData, null, 2)).then(() => {
        this.textContent = isChinese ? '已复制' : 'Copied';
        setTimeout(() => { this.textContent = '${labels.copy}'; }, 2000);
      });
    });
    
    document.getElementById('copyPathBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(${pathLiteral}).then(() => {
        this.textContent = isChinese ? '已复制' : 'Copied';
        setTimeout(() => { this.textContent = isChinese ? '复制路径' : 'Copy Path'; }, 2000);
      });
    });
    
    document.getElementById('collapseBtn').addEventListener('click', () => {
      document.querySelectorAll('.collapsible-content').forEach(el => el.classList.add('hidden'));
      document.querySelectorAll('.collapsible').forEach(el => el.classList.add('collapsed'));
    });
    
    document.getElementById('expandBtn').addEventListener('click', () => {
      document.querySelectorAll('.collapsible-content').forEach(el => el.classList.remove('hidden'));
      document.querySelectorAll('.collapsible').forEach(el => el.classList.remove('collapsed'));
    });
    
    document.getElementById('searchInput').addEventListener('input', function() {
      const query = this.value.toLowerCase();
      document.querySelectorAll('.json-line').forEach(line => {
        if (query && line.textContent.toLowerCase().includes(query)) {
          line.classList.add('json-highlight');
        } else {
          line.classList.remove('json-highlight');
        }
      });
    });
  </script>
</body>
</html>`;
  }
}
