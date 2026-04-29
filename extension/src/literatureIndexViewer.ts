/**
 * 文献索引预览器 - 以友好方式显示 literature_index.json
 *
 * 关联文件：
 * - @extension/src/extension.ts - 注册命令
 * - @extension/src/projectStructureProvider.ts - 文献索引节点
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { filePathToAtReference } from './atReference';

interface LiteratureEntry {
  title?: string;
  file_path?: string;
  authors?: string[];
  year?: number;
  abstract?: string;
  keywords?: string[];
  doi?: string;
  url?: string;
  journal?: string;
  at_ref?: string;
  extra_fields?: {
    article_id?: string;
    [key: string]: any;
  };
  [key: string]: any;
}

interface LiteratureIndex {
  version?: string;
  created_at?: string;
  updated_at?: string;
  entries?: LiteratureEntry[];
}

export class LiteratureIndexViewer {
  private static currentPanel: vscode.WebviewPanel | undefined;

  public static async show(context: vscode.ExtensionContext, filePath: string): Promise<void> {
    // 读取 JSON 文件
    let data: LiteratureIndex;
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      data = JSON.parse(content);
    } catch (error: any) {
      vscode.window.showErrorMessage(`无法读取文献索引: ${error.message}`);
      return;
    }

    // 如果已有面板，复用它
    if (this.currentPanel) {
      this.currentPanel.reveal(vscode.ViewColumn.One);
      this.updateWebview(this.currentPanel, data, filePath);
      return;
    }

    // 创建新的 webview 面板
    const panel = vscode.window.createWebviewPanel(
      'literatureIndexViewer',
      '文献索引预览',
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      }
    );

    this.currentPanel = panel;

    // 处理面板关闭
    panel.onDidDispose(() => {
      this.currentPanel = undefined;
    });

    // 处理来自 webview 的消息
    panel.webview.onDidReceiveMessage(
      async (message) => {
        if (message.command === 'openFile') {
          try {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (workspaceFolder && message.filePath) {
              const workspaceRoot = workspaceFolder.uri.fsPath;
              // 仅允许打开工作区内文件：防止通过 ../ 进行路径穿越
              const requested = String(message.filePath);
              const candidatePath = path.isAbsolute(requested)
                ? path.normalize(requested)
                : path.normalize(path.join(workspaceRoot, requested));
              const relative = path.relative(workspaceRoot, candidatePath);
              const isInside = relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
              if (!isInside) {
                throw new Error('Refused to open a path outside the workspace');
              }

              const uri = vscode.Uri.file(candidatePath);
              const doc = await vscode.workspace.openTextDocument(uri);
              await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);
            }
          } catch (error: any) {
            vscode.window.showErrorMessage(`无法打开文件: ${error.message}`);
          }
        } else if (message.command === 'openUrl') {
          // 打开外部链接（DOI、URL 等）
          if (message.url) {
            const url = String(message.url);
            if (!/^https?:\/\//i.test(url)) {
              vscode.window.showWarningMessage('Blocked non-http(s) URL');
              return;
            }
            vscode.env.openExternal(vscode.Uri.parse(url));
          }
        } else if (message.command === 'copyAtReference') {
          const wf = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
          const atReference =
            typeof message.atReference === 'string' && message.atReference
              ? message.atReference
              : message.filePath
                ? filePathToAtReference(wf, message.filePath)
                : '';
          if (atReference) {
            vscode.env.clipboard.writeText(atReference);
            const isZh = vscode.env.language.startsWith('zh');
            vscode.window.showInformationMessage(isZh ? `已复制: ${atReference}` : `Copied: ${atReference}`);
          }
        }
      },
      undefined,
      context.subscriptions
    );

    // 更新内容
    this.updateWebview(panel, data, filePath);
  }

  private static updateWebview(
    panel: vscode.WebviewPanel,
    data: LiteratureIndex,
    filePath: string
  ): void {
    const rawEntries = data.entries || [];
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const workspaceRoot = workspaceFolder?.uri.fsPath;
    const entries: LiteratureEntry[] = rawEntries.map((e) => ({
      ...e,
      at_ref: e.file_path ? filePathToAtReference(workspaceRoot, e.file_path) : '',
    }));
    const total = entries.length;

    // 获取当前语言
    const isChinese = vscode.env.language.startsWith('zh');

    panel.webview.html = `
<!DOCTYPE html>
<html lang="${isChinese ? 'zh-CN' : 'en'}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${isChinese ? '文献索引预览' : 'Literature Index Viewer'}</title>
  <style>
    :root {
      --lit-entry-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
      --lit-entry-bg: var(--vscode-editor-background);
    }

    body.vscode-dark,
    body.vscode-high-contrast {
      --lit-entry-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
      --lit-entry-bg: var(--vscode-editorWidget-background, var(--vscode-editor-background));
    }

    body {
      font-family: var(--vscode-font-family);
      background-color: var(--vscode-editor-background);
      color: var(--vscode-editor-foreground);
      padding: 20px;
      max-width: 1200px;
      margin: 0 auto;
    }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      padding-bottom: 15px;
      border-bottom: 1px solid var(--vscode-panel-border);
    }

    .header h1 {
      margin: 0;
      font-size: 24px;
    }

    .stats {
      color: var(--vscode-descriptionForeground);
      font-size: 14px;
    }

    .search-box {
      margin-bottom: 20px;
    }

    .search-box input {
      width: 100%;
      padding: 10px 15px;
      font-size: 14px;
      border: 1px solid var(--vscode-input-border);
      background-color: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      border-radius: 4px;
      outline: none;
    }

    .search-box input:focus {
      border-color: var(--vscode-focusBorder);
    }

    .entry {
      background-color: var(--lit-entry-bg);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 8px;
      padding: 15px;
      margin-bottom: 15px;
      transition: box-shadow 0.2s;
    }

    .entry:hover {
      box-shadow: var(--lit-entry-shadow);
    }

    .entry-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 10px;
    }

    .entry-title {
      font-size: 16px;
      font-weight: 600;
      color: var(--vscode-textLink-foreground);
      cursor: pointer;
      flex: 1;
    }

    .entry-title:hover {
      text-decoration: underline;
    }

    .entry-year {
      background-color: var(--vscode-badge-background);
      color: var(--vscode-badge-foreground);
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 12px;
      margin-left: 10px;
    }

    .entry-authors {
      color: var(--vscode-descriptionForeground);
      font-size: 13px;
      margin-bottom: 8px;
    }

    .entry-abstract {
      font-size: 13px;
      line-height: 1.5;
      color: var(--vscode-editor-foreground);
      margin-bottom: 10px;
    }

    .entry-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      font-size: 12px;
    }

    .keyword {
      background-color: var(--vscode-input-background);
      color: var(--vscode-descriptionForeground);
      padding: 2px 8px;
      border-radius: 4px;
      border: 1px solid var(--vscode-input-border);
    }

    .file-path {
      color: var(--vscode-textLink-foreground);
      font-size: 12px;
      margin-top: 8px;
      font-family: var(--vscode-editor-font-family);
    }

    .empty-state {
      text-align: center;
      padding: 40px;
      color: var(--vscode-descriptionForeground);
    }

    .filter-group {
      display: flex;
      gap: 10px;
      margin-bottom: 15px;
    }

    .filter-btn {
      padding: 6px 12px;
      border: 1px solid var(--vscode-button-border);
      background-color: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }

    .filter-btn:hover {
      background-color: var(--vscode-button-secondaryHoverBackground);
    }

    .filter-btn.active {
      background-color: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }

    .sort-select {
      padding: 6px 12px;
      border: 1px solid var(--vscode-input-border);
      background-color: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      border-radius: 4px;
      font-size: 12px;
    }

    .entry-actions {
      display: flex;
      gap: 8px;
      margin-top: 10px;
      flex-wrap: wrap;
    }

    .action-btn {
      padding: 4px 10px;
      border: 1px solid var(--vscode-button-border);
      background-color: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      border-radius: 4px;
      cursor: pointer;
      font-size: 11px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }

    .action-btn:hover {
      background-color: var(--vscode-button-secondaryHoverBackground);
    }

    .action-btn.primary {
      background-color: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }

    .action-btn.primary:hover {
      background-color: var(--vscode-button-hoverBackground);
    }

    .entry-journal {
      color: var(--vscode-textPreformat-foreground);
      font-size: 12px;
      font-style: italic;
      margin-bottom: 6px;
    }

    .abstract-toggle {
      color: var(--vscode-textLink-foreground);
      cursor: pointer;
      font-size: 12px;
      margin-top: 4px;
      display: inline-block;
    }

    .abstract-toggle:hover {
      text-decoration: underline;
    }

    .abstract-full {
      display: none;
    }

    .abstract-full.show {
      display: block;
    }

    .abstract-preview {
      display: block;
    }

    .abstract-preview.hide {
      display: none;
    }

    .doi-link {
      color: var(--vscode-textLink-foreground);
      font-size: 11px;
      font-family: var(--vscode-editor-font-family);
    }

    .doi-link:hover {
      text-decoration: underline;
    }
    .batch-actions {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
      padding: 10px 12px;
      background-color: var(--vscode-input-background);
      border-radius: 6px;
      align-items: center;
    }
    .batch-btn {
      padding: 6px 12px;
      background-color: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      border: 1px solid var(--vscode-button-border);
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }
    .batch-btn:hover {
      background-color: var(--vscode-button-secondaryHoverBackground);
    }
    .batch-btn.primary {
      background-color: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
    }
    .batch-btn.primary:hover {
      background-color: var(--vscode-button-hoverBackground);
    }
    .select-all-checkbox {
      margin-right: 8px;
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>${isChinese ? '📚 文献索引' : '📚 Literature Index'}</h1>
    <div class="stats">
      ${isChinese ? `共 ${total} 篇文献` : `${total} articles`}
      ${data.updated_at ? `<br>${isChinese ? '更新于' : 'Updated'}: ${new Date(data.updated_at).toLocaleString()}` : ''}
    </div>
  </div>

  <div class="search-box">
    <input type="text" id="searchInput" placeholder="${isChinese ? '搜索标题、作者或关键词...' : 'Search title, authors, or keywords...'}" />
  </div>

  <div class="filter-group">
    <select id="sortSelect" class="sort-select">
      <option value="default">${isChinese ? '默认排序' : 'Default Order'}</option>
      <option value="year-desc">${isChinese ? '年份 (新→旧)' : 'Year (New→Old)'}</option>
      <option value="year-asc">${isChinese ? '年份 (旧→新)' : 'Year (Old→New)'}</option>
      <option value="title">${isChinese ? '标题 A-Z' : 'Title A-Z'}</option>
    </select>
  </div>

  <div class="batch-actions">
    <input type="checkbox" id="selectAll" class="select-all-checkbox" />
    <label for="selectAll" style="font-size: 12px; margin-right: 12px;">${isChinese ? '全选' : 'Select All'}</label>
    <button class="batch-btn primary" id="copySelectedBtn">📋 ${isChinese ? '复制选中引用' : 'Copy Selected'}</button>
    <button class="batch-btn" id="exportBtn">📥 ${isChinese ? '导出列表' : 'Export'}</button>
  </div>

  <div id="entries"></div>

  <script>
    const entries = ${JSON.stringify(entries)};
    const workspacePath = ${workspaceFolder ? `"${workspaceFolder.uri.fsPath}"` : 'null'};
    const isChinese = ${isChinese ? 'true' : 'false'};

    function renderEntries(filteredEntries) {
      const container = document.getElementById('entries');
      container.innerHTML = '';

      if (filteredEntries.length === 0) {
        container.innerHTML = '<div class="empty-state">' + (isChinese ? '没有找到匹配的文献' : 'No matching articles found') + '</div>';
        return;
      }

      filteredEntries.forEach((entry, index) => {
        const div = document.createElement('div');
        div.className = 'entry';
        div.dataset.index = index;
        div.setAttribute('data-filepath', entry.file_path || '');
        div.setAttribute('data-at-ref', entry.at_ref || '');

        const title = entry.title || (isChinese ? '未命名文献' : 'Untitled');
        const year = entry.year || '';
        const authors = entry.authors || [];
        const abstract = entry.abstract || '';
        const keywords = entry.keywords || [];
        const filePath = entry.file_path || '';
        const journal = entry.journal || '';
        const doi = entry.doi || '';
        const articleId = entry.extra_fields?.article_id || '';
        const url = entry.url || '';

        // 构建 DOI/文章链接
        let doiLink = '';
        if (doi) {
          doiLink = \`<a class="doi-link" href="#" onclick="openUrl('https://doi.org/\${doi}'); return false;">DOI: \${doi}</a>\`;
        } else if (articleId) {
          // 如果 articleId 看起来像 DOI
          if (articleId.includes('/')) {
            doiLink = \`<a class="doi-link" href="#" onclick="openUrl('https://doi.org/\${articleId}'); return false;">DOI: \${articleId}</a>\`;
          } else {
            doiLink = \`<span class="doi-link">ID: \${articleId}</span>\`;
          }
        }
        if (url) {
          doiLink += \` <a class="doi-link" href="#" onclick="openUrl('\${url}'); return false;">🔗 \${isChinese ? '链接' : 'Link'}</a>\`;
        }

        // 构建摘要显示
        let abstractHtml = '';
        if (abstract) {
          const needsTruncate = abstract.length > 300;
          abstractHtml = \`
            <div class="entry-abstract">
              <div class="abstract-preview" id="abstract-preview-\${index}">\${abstract.substring(0, 300)}\${needsTruncate ? '...' : ''}</div>
              <div class="abstract-full" id="abstract-full-\${index}">\${abstract}</div>
              \${needsTruncate ? \`<span class="abstract-toggle" onclick="toggleAbstract(\${index})">\${isChinese ? '展开全文' : 'Show more'}</span>\` : ''}
            </div>
          \`;
        }

        div.innerHTML = \`
          <div class="entry-header">
            <input type="checkbox" class="entry-checkbox" data-filepath="\${filePath}" data-at-ref="\${entry.at_ref || ''}" data-title="\${title.replace(/"/g, '&quot;')}" style="margin-right: 10px;" />
            <div class="entry-title" onclick="openFile('\${filePath}')">\${title}</div>
            \${year ? \`<span class="entry-year">\${year}</span>\` : ''}
          </div>
          \${journal ? \`<div class="entry-journal">\${journal}</div>\` : ''}
          \${authors.length > 0 ? \`<div class="entry-authors">\${authors.join(', ')}</div>\` : ''}
          \${abstractHtml}
          <div class="entry-meta">
            \${keywords.slice(0, 5).map(k => \`<span class="keyword">\${k}</span>\`).join('')}
          </div>
          \${filePath ? \`<div class="file-path">📄 \${filePath}</div>\` : ''}
          \${doiLink ? \`<div style="margin-top: 6px;">\${doiLink}</div>\` : ''}
          <div class="entry-actions">
            <button class="action-btn primary" onclick="openFile('\${filePath}')">
              📖 \${isChinese ? '打开全文' : 'Open'}
            </button>
            \${filePath ? \`<button class="action-btn" onclick="copyAtReferenceForEntry(this)">📋 \${isChinese ? '复制引用' : 'Copy Ref'}</button>\` : ''}
            \${doi || articleId ? \`<button class="action-btn" onclick="openUrl('https://doi.org/\${doi || articleId}')">🔗 DOI</button>\` : ''}
            \${url ? \`<button class="action-btn" onclick="openUrl('\${url}')">🌐 \${isChinese ? '网页' : 'Web'}</button>\` : ''}
          </div>
        \`;

        container.appendChild(div);
      });
    }

    function toggleAbstract(index) {
      const preview = document.getElementById('abstract-preview-' + index);
      const full = document.getElementById('abstract-full-' + index);
      const toggle = preview.parentElement.querySelector('.abstract-toggle');

      if (full.classList.contains('show')) {
        full.classList.remove('show');
        preview.classList.remove('hide');
        toggle.textContent = isChinese ? '展开全文' : 'Show more';
      } else {
        full.classList.add('show');
        preview.classList.add('hide');
        toggle.textContent = isChinese ? '收起' : 'Show less';
      }
    }

    function openUrl(url) {
      if (url) {
        const vscode = acquireVsCodeApi();
        vscode.postMessage({
          command: 'openUrl',
          url: url
        });
      }
    }

    function openFile(filePath) {
      if (filePath && workspacePath) {
        const vscode = acquireVsCodeApi();
        vscode.postMessage({
          command: 'openFile',
          filePath: filePath
        });
      }
    }

    function copyAtReferenceForEntry(btn) {
      const row = btn.closest('.entry');
      const atRef = row && row.getAttribute('data-at-ref');
      if (!atRef) return;
      const vscode = acquireVsCodeApi();
      vscode.postMessage({
        command: 'copyAtReference',
        atReference: atRef
      });
    }

    // 搜索功能
    document.getElementById('searchInput').addEventListener('input', (e) => {
      const query = e.target.value.toLowerCase();
      const filtered = entries.filter(entry => {
        const title = (entry.title || '').toLowerCase();
        const authors = (entry.authors || []).join(' ').toLowerCase();
        const keywords = (entry.keywords || []).join(' ').toLowerCase();
        const abstract = (entry.abstract || '').toLowerCase();
        return title.includes(query) || authors.includes(query) || keywords.includes(query) || abstract.includes(query);
      });
      applySort(filtered);
    });

    // 排序功能
    function applySort(entriesToSort) {
      const sortValue = document.getElementById('sortSelect').value;
      let sorted = [...entriesToSort];

      if (sortValue === 'year-desc') {
        sorted.sort((a, b) => (b.year || 0) - (a.year || 0));
      } else if (sortValue === 'year-asc') {
        sorted.sort((a, b) => (a.year || 0) - (b.year || 0));
      } else if (sortValue === 'title') {
        sorted.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
      }

      renderEntries(sorted);
    }

    document.getElementById('sortSelect').addEventListener('change', () => {
      const query = document.getElementById('searchInput').value.toLowerCase();
      const filtered = entries.filter(entry => {
        const title = (entry.title || '').toLowerCase();
        const authors = (entry.authors || []).join(' ').toLowerCase();
        const keywords = (entry.keywords || []).join(' ').toLowerCase();
        const abstract = (entry.abstract || '').toLowerCase();
        return title.includes(query) || authors.includes(query) || keywords.includes(query) || abstract.includes(query);
      });
      applySort(filtered);
    });

    // 初始渲染（应用当前排序设置）
    applySort(entries);

    // 全选功能
    document.getElementById('selectAll').addEventListener('change', function() {
      var checkboxes = document.querySelectorAll('.entry-checkbox');
      checkboxes.forEach(function(cb) {
        cb.checked = document.getElementById('selectAll').checked;
      });
    });

    // 复制选中引用
    document.getElementById('copySelectedBtn').addEventListener('click', function() {
      var checkboxes = document.querySelectorAll('.entry-checkbox:checked');
      if (checkboxes.length === 0) {
        alert(isChinese ? '请先选择文献' : 'Please select articles first');
        return;
      }
      var references = [];
      checkboxes.forEach(function(cb) {
        var ar = cb.getAttribute('data-at-ref');
        if (ar) {
          references.push(ar);
        }
      });
      navigator.clipboard.writeText(references.join('\\n')).then(function() {
        alert(isChinese ? '已复制 ' + references.length + ' 条引用' : 'Copied ' + references.length + ' references');
      }).catch(function() {
        alert(isChinese ? '复制失败' : 'Copy failed');
      });
    });

    // 导出列表
    document.getElementById('exportBtn').addEventListener('click', function() {
      var checkboxes = document.querySelectorAll('.entry-checkbox:checked');
      var selectedEntries = checkboxes.length > 0 ? 
        Array.from(checkboxes).map(function(cb) {
          return entries.find(function(e) { return e.file_path === cb.getAttribute('data-filepath'); });
        }).filter(Boolean) : 
        entries;
      
      var csvContent = 'Title,Authors,Year,Journal,DOI,File Path\\n';
      selectedEntries.forEach(function(e) {
        var title = (e.title || '').replace(/"/g, '""');
        var authors = (e.authors || []).join('; ').replace(/"/g, '""');
        var year = e.year || '';
        var journal = (e.journal || '').replace(/"/g, '""');
        var doi = e.doi || '';
        var fp = e.file_path || '';
        csvContent += '"' + title + '","' + authors + '","' + year + '","' + journal + '","' + doi + '","' + fp + '"\\n';
      });
      
      var blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'literature_export.csv';
      a.click();
      URL.revokeObjectURL(url);
    });

    // 键盘快捷键支持
    document.addEventListener('keydown', function(e) {
      // Ctrl/Cmd + F: 聚焦搜索框
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        document.getElementById('searchInput').focus();
      }
      // Ctrl/Cmd + A: 全选
      if ((e.ctrlKey || e.metaKey) && e.key === 'a' && document.activeElement.tagName !== 'INPUT') {
        e.preventDefault();
        document.getElementById('selectAll').checked = true;
        document.querySelectorAll('.entry-checkbox').forEach(function(cb) {
          cb.checked = true;
        });
      }
      // Escape: 清除搜索
      if (e.key === 'Escape') {
        document.getElementById('searchInput').value = '';
        applySort(entries);
      }
    });

    // 入口项双击复制引用
    document.addEventListener('dblclick', function(e) {
      var entry = e.target.closest('.entry');
      if (entry) {
        var atRef = entry.getAttribute('data-at-ref');
        if (atRef) {
          navigator.clipboard.writeText(atRef).then(function() {
            var notification = document.createElement('div');
            notification.style.cssText = 'position:fixed;top:20px;right:20px;background:#52c41a;color:#fff;padding:8px 16px;border-radius:4px;z-index:9999;animation:fadeIn 0.3s;';
            notification.textContent = isChinese ? '已复制引用' : 'Reference copied';
            document.body.appendChild(notification);
            setTimeout(function() { notification.remove(); }, 2000);
          });
        }
      }
    });
  </script>
</body>
</html>`;
  }
}
