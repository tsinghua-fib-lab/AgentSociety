/**
 * CSV / TSV 表格预览（轻量，不做编辑）
 * 支持搜索、列排序、复制 CSV
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import { isExtensionZh } from './i18n';

const MAX_FILE_BYTES = 6 * 1024 * 1024;
const MAX_ROWS = 5000;

function splitRow(line: string, delimiter: string): string[] {
  const out: string[] = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i]!;
    if (inQuotes) {
      if (c === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cur += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === delimiter) {
      out.push(cur);
      cur = '';
    } else {
      cur += c;
    }
  }
  out.push(cur);
  return out;
}

function parseDelimited(text: string, delimiter: string): string[][] {
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').filter((l) => l.length > 0);
  return lines.map((line) => splitRow(line, delimiter));
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export class CsvViewer {
  private static currentPanel: vscode.WebviewPanel | undefined;

  public static async show(filePath: string): Promise<void> {
    const isZh = isExtensionZh();
    const lower = filePath.toLowerCase();
    const delim = lower.endsWith('.tsv') ? '\t' : ',';

    let rows: string[][] = [];
    let error: string | null = null;
    let truncated = false;

    try {
      const stat = fs.statSync(filePath);
      if (stat.size > MAX_FILE_BYTES) {
        error = isZh
          ? `文件过大（>${Math.floor(MAX_FILE_BYTES / 1024 / 1024)}MB），请用编辑器或外部工具打开`
          : `File too large (>${Math.floor(MAX_FILE_BYTES / 1024 / 1024)}MB); open in an external tool`;
      } else {
        const text = fs.readFileSync(filePath, 'utf-8');
        rows = parseDelimited(text, delim);
        if (rows.length > MAX_ROWS) {
          rows = rows.slice(0, MAX_ROWS);
          truncated = true;
        }
      }
    } catch (e: any) {
      error = e.message || String(e);
    }

    const fileName = filePath.split(/[/\\]/).pop() || 'data';

    if (this.currentPanel) {
      this.currentPanel.title = fileName;
      this.currentPanel.reveal(vscode.ViewColumn.One);
      this.currentPanel.webview.html = this.buildHtml(rows, error, truncated, filePath, isZh);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      'csvViewer',
      fileName,
      vscode.ViewColumn.One,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    this.currentPanel = panel;
    panel.onDidDispose(() => {
      this.currentPanel = undefined;
    });
    panel.webview.html = this.buildHtml(rows, error, truncated, filePath, isZh);
  }

  private static buildHtml(
    rows: string[][],
    error: string | null,
    truncated: boolean,
    filePath: string,
    isZh: boolean
  ): string {
    const title = isZh ? '表格预览' : 'Table Preview';
    const pathLabel = isZh ? '路径' : 'Path';
    const searchLabel = isZh ? '搜索...' : 'Search...';
    const copyLabel = isZh ? '复制 CSV' : 'Copy CSV';
    const copyPathLabel = isZh ? '复制路径' : 'Copy Path';
    const rowCount = rows.length > 0 ? rows.length - 1 : 0;
    const colCount = rows.length > 0 ? (rows[0]?.length ?? 0) : 0;
    const sizeLabel = isZh ? '大小' : 'Size';
    const fileSize = error ? 0 : Buffer.byteLength(JSON.stringify(rows), 'utf8');
    const fileSizeStr = fileSize > 1024 ? `${(fileSize / 1024).toFixed(1)} KB` : `${fileSize} B`;

    if (error) {
      return `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>${title}</title>
      <style>body{font-family:var(--vscode-font-family);padding:16px;color:var(--vscode-errorForeground);}</style></head>
      <body><p>${escapeHtml(error)}</p><p style="color:var(--vscode-descriptionForeground);font-size:12px;">${escapeHtml(filePath)}</p></body></html>`;
    }

    const head = rows[0] || [];
    const body = rows.slice(1);
    const th = head.map((c, i) =>
      `<th data-col="${i}" onclick="sortTable(${i})" title="${isZh ? '点击排序' : 'Click to sort'}">${escapeHtml(c)} <span class="sort-arrow" id="sortArrow${i}"></span></th>`
    ).join('');
    const trs = body
      .map((r, rowIdx) => {
        const cells = head.map((_, i) => `<td>${escapeHtml(r[i] ?? '')}</td>`).join('');
        return `<tr data-row="${rowIdx}">${cells}</tr>`;
      })
      .join('');

    const note = truncated
      ? (isZh ? `<p class="note">仅显示前 ${MAX_ROWS} 行。</p>` : `<p class="note">Showing first ${MAX_ROWS} rows only.</p>`)
      : '';

    const pathLiteral = JSON.stringify(filePath);

    return `<!DOCTYPE html>
<html lang="${isZh ? 'zh-CN' : 'en'}">
<head>
  <meta charset="UTF-8">
  <title>${title}</title>
  <style>
    body { font-family: var(--vscode-font-family); background: var(--vscode-editor-background); color: var(--vscode-editor-foreground); margin: 0; padding: 12px 16px 24px; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px; }
    .header h1 { font-size: 16px; margin: 0; }
    .header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .btn { padding: 6px 12px; background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
    .btn:hover { background: var(--vscode-button-secondaryHoverBackground); }
    .btn.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
    .meta { display: flex; gap: 16px; font-size: 11px; color: var(--vscode-descriptionForeground); margin-bottom: 8px; flex-wrap: wrap; }
    .search-box { margin-bottom: 8px; }
    .search-box input { width: 100%; padding: 8px 12px; background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border); border-radius: 4px; color: var(--vscode-input-foreground); font-size: 13px; }
    .search-box input:focus { outline: 1px solid var(--vscode-focusBorder); }
    .note { font-size: 12px; color: var(--vscode-editorWarning-foreground); margin: 8px 0; }
    .wrap { overflow: auto; max-height: calc(100vh - 180px); border: 1px solid var(--vscode-panel-border); border-radius: 6px; }
    table { border-collapse: collapse; min-width: 100%; font-size: 12px; }
    th { position: sticky; top: 0; background: var(--vscode-editorWidget-background); color: var(--vscode-editor-foreground); text-align: left; padding: 8px 10px; border-bottom: 2px solid var(--vscode-panel-border); white-space: nowrap; z-index: 1; cursor: pointer; user-select: none; }
    th:hover { background: var(--vscode-list-hoverBackground); }
    .sort-arrow { font-size: 10px; margin-left: 4px; }
    td { padding: 6px 10px; border-bottom: 1px solid var(--vscode-panel-border); vertical-align: top; max-width: 420px; }
    tr:nth-child(even) td { background: var(--vscode-editor-inactiveSelectionBackground, rgba(127,127,127,.08)); }
    tr.hidden { display: none; }
    .highlight { background: rgba(255, 215, 0, 0.25) !important; }
  </style>
</head>
<body>
  <div class="header">
    <h1>📊 ${title}</h1>
    <div class="header-actions">
      <button class="btn" id="copyPathBtn">📋 ${copyPathLabel}</button>
      <button class="btn primary" id="copyBtn">${copyLabel}</button>
    </div>
  </div>
  <div class="meta">
    <span>${pathLabel}: ${escapeHtml(filePath)}</span>
    <span>${rowCount} ${isZh ? '行' : 'rows'} × ${colCount} ${isZh ? '列' : 'cols'}</span>
    <span>${sizeLabel}: ${fileSizeStr}</span>
  </div>
  ${note}
  <div class="search-box">
    <input type="text" id="searchInput" placeholder="${searchLabel}" />
  </div>
  <div class="wrap"><table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table></div>

  <script>
    const isChinese = ${isZh ? 'true' : 'false'};
    const rows = ${JSON.stringify(rows).replace(/</g, '\\u003c')};
    let sortCol = -1;
    let sortAsc = true;

    function sortTable(col) {
      if (sortCol === col) { sortAsc = !sortAsc; } else { sortCol = col; sortAsc = true; }
      const tbody = document.querySelector('tbody');
      const trs = Array.from(tbody.querySelectorAll('tr'));
      trs.sort(function(a, b) {
        const va = (rows[parseInt(a.dataset.row) + 1] || [])[col] || '';
        const vb = (rows[parseInt(b.dataset.row) + 1] || [])[col] || '';
        const na = parseFloat(va), nb = parseFloat(vb);
        if (!isNaN(na) && !isNaN(nb)) return sortAsc ? na - nb : nb - na;
        return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
      });
      trs.forEach(function(tr) { tbody.appendChild(tr); });
      document.querySelectorAll('.sort-arrow').forEach(function(s) { s.textContent = ''; });
      const arrow = document.getElementById('sortArrow' + col);
      if (arrow) arrow.textContent = sortAsc ? '▲' : '▼';
    }

    document.getElementById('searchInput').addEventListener('input', function() {
      const q = this.value.toLowerCase();
      document.querySelectorAll('tbody tr').forEach(function(tr) {
        if (!q || tr.textContent.toLowerCase().indexOf(q) >= 0) {
          tr.classList.remove('hidden');
          tr.querySelectorAll('td').forEach(function(td) { td.classList.remove('highlight'); });
        } else {
          tr.classList.add('hidden');
        }
      });
      if (q) {
        document.querySelectorAll('tbody tr:not(.hidden) td').forEach(function(td) {
          if (td.textContent.toLowerCase().indexOf(q) >= 0) td.classList.add('highlight');
        });
      }
    });

    document.getElementById('copyBtn').addEventListener('click', function() {
      const csv = rows.map(function(r) { return r.map(function(c) { return c.includes(',') || c.includes('"') ? '"' + c.replace(/"/g, '""') + '"' : c; }).join(','); }).join('\\n');
      navigator.clipboard.writeText(csv).then(function() {
        this.textContent = isChinese ? '已复制' : 'Copied';
        setTimeout(() => { this.textContent = '${copyLabel}'; }, 2000);
      }.bind(this));
    });

    document.getElementById('copyPathBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(${pathLiteral}).then(function() {
        this.textContent = isChinese ? '已复制' : 'Copied';
        setTimeout(() => { this.textContent = isChinese ? '复制路径' : 'Copy Path'; }, 2000);
      }.bind(this));
    });
  </script>
</body>
</html>`;
  }
}