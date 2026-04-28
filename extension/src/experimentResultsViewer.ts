/**
 * 实验结果可视化预览器 - 动态探测字段，通用可视化
 */

import * as vscode from 'vscode';
import * as fs from 'fs';

interface ExperimentResults {
  [key: string]: any;
}

export class ExperimentResultsViewer {
  private static currentPanel: vscode.WebviewPanel | undefined;

  private static getNonce(): string {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let nonce = '';
    for (let i = 0; i < 32; i++) {
      nonce += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return nonce;
  }

  public static async show(context: vscode.ExtensionContext, filePath: string): Promise<void> {
    let data: ExperimentResults;
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      data = JSON.parse(content);
    } catch (error: any) {
      vscode.window.showErrorMessage(`无法读取实验结果: ${error.message}`);
      return;
    }

    // 从文件路径提取实验信息
    const pathParts = filePath.split(/[/\\]/);
    const experimentIndex = pathParts.findIndex(p => p.startsWith('experiment_'));
    const hypothesisIndex = pathParts.findIndex(p => p.startsWith('hypothesis_'));

    let title = vscode.env.language.startsWith('zh') ? '实验结果可视化' : 'Experiment Results';
    if (experimentIndex !== -1) {
      const expMatch = pathParts[experimentIndex].match(/experiment_(\d+)/);
      const hypMatch = hypothesisIndex !== -1 ? pathParts[hypothesisIndex].match(/hypothesis_(\d+)/) : null;
      if (hypMatch && expMatch) {
        title = vscode.env.language.startsWith('zh')
          ? `H${hypMatch[1]}-E${expMatch[1]} 实验结果`
          : `H${hypMatch[1]}-E${expMatch[1]} Results`;
      }
    }

    if (this.currentPanel) {
      this.currentPanel.title = title;
      this.currentPanel.reveal(vscode.ViewColumn.One);
      this.updateWebview(this.currentPanel, data, filePath);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      'experimentResultsViewer',
      title,
      vscode.ViewColumn.One,
      { enableScripts: true, retainContextWhenHidden: true }
    );

    this.currentPanel = panel;
    panel.onDidDispose(() => { this.currentPanel = undefined; });
    this.updateWebview(panel, data, filePath);
  }

  private static updateWebview(
    panel: vscode.WebviewPanel,
    data: ExperimentResults,
    filePath: string
  ): void {
    const isChinese = vscode.env.language.startsWith('zh');

    panel.webview.html = this.getHtml(data, isChinese, panel.webview.cspSource);
  }

  private static getHtml(data: ExperimentResults, isChinese: boolean, cspSource: string): string {
    // 提取摘要字段
    const summaryFields: Array<{ key: string; value: any }> = [];
    Object.entries(data).forEach(([key, value]) => {
      const type = typeof value;
      if (type === 'number' || type === 'string' || type === 'boolean') {
        summaryFields.push({ key, value });
      }
    });

    // 查找数组类型的数据（轮次数据）
    const arrayFields: Array<{ key: string; data: any[] }> = [];
    Object.entries(data).forEach(([key, value]) => {
      if (Array.isArray(value) && value.length > 0 && typeof value[0] === 'object') {
        arrayFields.push({ key, data: value });
      }
    });

    const nonce = this.getNonce();
    const csp = [
      "default-src 'none'",
      `img-src ${cspSource} data:`,
      `style-src ${cspSource} 'unsafe-inline'`,
      `script-src ${cspSource} 'nonce-${nonce}'`,
    ].join('; ');

    return `<!DOCTYPE html>
<html lang="${isChinese ? 'zh-CN' : 'en'}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <title>${isChinese ? '实验结果可视化' : 'Experiment Results'}</title>
  <style>
    :root {
      --results-surface: var(--vscode-editor-background);
      --results-surface-muted: var(--vscode-editorWidget-background, var(--vscode-editor-background));
      --results-accent: var(--vscode-textLink-foreground, #1890ff);
      --results-accent-fill: rgba(24, 144, 255, 0.14);
      --results-grid: var(--vscode-panel-border);
      --results-chart-text: var(--vscode-editor-foreground);
      --results-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    body.vscode-dark,
    body.vscode-high-contrast {
      --results-surface: var(--vscode-editorWidget-background, var(--vscode-editor-background));
      --results-surface-muted: var(--vscode-input-background);
      --results-accent-fill: rgba(24, 144, 255, 0.24);
      --results-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
    }

    body {
      font-family: var(--vscode-font-family);
      background-color: var(--vscode-editor-background);
      color: var(--vscode-editor-foreground);
      padding: 24px;
      max-width: 1200px;
      margin: 0 auto;
    }
    .header { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--vscode-panel-border); }
    .header h1 { margin: 0; font-size: 24px; }
    .summary-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 24px; }
    .summary-card { background-color: var(--results-surface); border: 1px solid var(--vscode-panel-border); border-radius: 8px; padding: 12px; }
    .summary-card h3 { margin: 0 0 6px 0; font-size: 11px; color: var(--vscode-descriptionForeground); text-transform: uppercase; }
    .summary-card .value { font-size: 18px; font-weight: 600; }
    .section { background-color: var(--results-surface); border: 1px solid var(--vscode-panel-border); border-radius: 8px; padding: 16px; margin-bottom: 20px; }
    .section h2 { margin: 0 0 12px 0; font-size: 15px; }
    .chart-container { height: 280px; margin-bottom: 12px; }
    .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    @media (max-width: 800px) { .chart-grid { grid-template-columns: 1fr; } }
    .data-table { width: 100%; border-collapse: collapse; font-size: 11px; }
    .data-table th, .data-table td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--vscode-panel-border); }
    .data-table th { background-color: var(--vscode-input-background); font-weight: 600; position: sticky; top: 0; }
    .data-table tr:hover { background-color: var(--vscode-list-hoverBackground); }
    .table-scroll { max-height: 350px; overflow: auto; }
    .tab-container { display: flex; gap: 6px; margin-bottom: 12px; border-bottom: 1px solid var(--vscode-panel-border); padding-bottom: 6px; flex-wrap: wrap; }
    .tab-btn { padding: 5px 12px; border: none; background: transparent; color: var(--vscode-descriptionForeground); cursor: pointer; font-size: 11px; border-radius: 4px; }
    .tab-btn:hover { background-color: var(--vscode-list-hoverBackground); }
    .tab-btn.active { background-color: var(--vscode-button-background); color: var(--vscode-button-foreground); }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .json-viewer { background-color: var(--results-surface-muted); border-radius: 6px; padding: 12px; font-family: var(--vscode-editor-font-family); font-size: 11px; max-height: 400px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
    .copy-btn { padding: 8px 16px; background-color: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
    .copy-btn:hover { background-color: var(--vscode-button-hoverBackground); }
  </style>
</head>
<body>
  <div class="header" style="display: flex; justify-content: space-between; align-items: center;">
    <h1>📊 ${isChinese ? '实验结果可视化' : 'Experiment Results'}</h1>
    <button class="copy-btn" id="copyBtn">📋 ${isChinese ? '复制数据' : 'Copy Data'}</button>
  </div>
  <div class="summary-cards" id="summaryCards"></div>
  <div class="section">
    <h2>📈 ${isChinese ? '数据可视化' : 'Data Visualization'}</h2>
    <div class="tab-container" id="tabContainer"></div>
    <div id="tabContents"></div>
  </div>
  <div class="section">
    <h2>📋 ${isChinese ? '原始数据' : 'Raw Data'}</h2>
    <div class="json-viewer" id="jsonViewer"></div>
  </div>

  <script nonce="${nonce}">
    const data = ${JSON.stringify(data)};
    const summaryFields = ${JSON.stringify(summaryFields)};
    const arrayFields = ${JSON.stringify(arrayFields.map(f => ({ key: f.key, data: f.data })))};
    const isChinese = ${isChinese ? 'true' : 'false'};
    let activeTabId = arrayFields.length > 0 ? 'tab_' + arrayFields[0].key : 'tab_overview';
    const chartInstances = [];

    function getTheme() {
      const styles = getComputedStyle(document.body);
      return {
        accent: styles.getPropertyValue('--vscode-textLink-foreground').trim() || '#1890ff',
        accentFill: styles.getPropertyValue('--results-accent-fill').trim() || 'rgba(24, 144, 255, 0.14)',
        text: styles.getPropertyValue('--vscode-editor-foreground').trim() || '#1f1f1f',
        description: styles.getPropertyValue('--vscode-descriptionForeground').trim() || '#666666',
        grid: styles.getPropertyValue('--vscode-panel-border').trim() || '#d9d9d9',
        panel: styles.getPropertyValue('--results-surface').trim() || '#ffffff',
        palette: [
          styles.getPropertyValue('--vscode-textLink-foreground').trim() || '#1890ff',
          styles.getPropertyValue('--vscode-testing-iconPassed').trim() || '#52c41a',
          styles.getPropertyValue('--vscode-editorWarning-foreground').trim() || '#faad14',
          styles.getPropertyValue('--vscode-errorForeground').trim() || '#ff4d4f',
          styles.getPropertyValue('--vscode-terminal-ansiMagenta').trim() || '#722ed1',
          styles.getPropertyValue('--vscode-terminal-ansiCyan').trim() || '#13c2c2',
          styles.getPropertyValue('--vscode-terminal-ansiBlue').trim() || '#2f54eb',
          styles.getPropertyValue('--vscode-terminal-ansiGreen').trim() || '#389e0d',
          styles.getPropertyValue('--vscode-terminal-ansiYellow').trim() || '#d48806',
          styles.getPropertyValue('--vscode-terminal-ansiRed').trim() || '#cf1322'
        ]
      };
    }

    // 渲染摘要
    function renderSummary() {
      const container = document.getElementById('summaryCards');
      container.innerHTML = summaryFields.slice(0, 8).map(f =>
        '<div class="summary-card"><h3>' + f.key + '</h3><div class="value">' + formatVal(f.value) + '</div></div>'
      ).join('');
    }

    function formatVal(v) {
      if (v === null || v === undefined) return '-';
      if (typeof v === 'object') return Array.isArray(v) ? '[' + v.length + ']' : '{...}';
      return String(v);
    }

    // 渲染标签页
    function renderTabs() {
      const tabContainer = document.getElementById('tabContainer');
      const contents = document.getElementById('tabContents');
      const theme = getTheme();
      let tabHtml = '';
      let contentHtml = '';

      if (arrayFields.length > 0) {
        arrayFields.forEach(field => {
          const tabId = 'tab_' + field.key;
          const isActive = tabId === activeTabId;
          tabHtml += '<button class="tab-btn ' + (isActive ? 'active' : '') + '" onclick="showTab(\\'' + tabId + '\\')">' + field.key + '</button>';
          contentHtml += '<div id="' + tabId + '" class="tab-content ' + (isActive ? 'active' : '') + '">';
          contentHtml += generateTable(field.data);
          contentHtml += '<div class="chart-grid" id="charts_' + field.key + '"></div>';
          contentHtml += '</div>';
        });
      } else {
        activeTabId = 'tab_overview';
        tabHtml = '<button class="tab-btn active" onclick="showTab(\\'tab_overview\\')">Overview</button>';
        contentHtml = '<div id="tab_overview" class="tab-content active"><p>No array data to visualize</p></div>';
      }

      tabContainer.innerHTML = tabHtml;
      contents.innerHTML = contentHtml;

      // 渲染图表
      chartInstances.splice(0).forEach(chart => chart.destroy());
      arrayFields.forEach(field => renderCharts(field.key, field.data, theme));
    }

    function generateTable(arr) {
      if (!arr || arr.length === 0) return '<p>Empty</p>';
      const firstItem = arr[0];
      const columns = Object.keys(firstItem);

      // 检查嵌套对象
      const flatCols = [];
      const nestedCols = {};
      columns.forEach(col => {
        const val = firstItem[col];
        if (val && typeof val === 'object' && !Array.isArray(val)) {
          nestedCols[col] = Object.keys(val);
        } else {
          flatCols.push(col);
        }
      });

      let html = '<div class="table-scroll"><table class="data-table"><thead><tr><th>#</th>';
      flatCols.forEach(c => { html += '<th>' + c + '</th>'; });
      Object.keys(nestedCols).forEach(parent => {
        nestedCols[parent].forEach(sub => { html += '<th>' + parent + '.' + sub + '</th>'; });
      });
      html += '</tr></thead><tbody>';

      arr.forEach((item, i) => {
        html += '<tr><td>' + (i + 1) + '</td>';
        flatCols.forEach(c => { html += '<td>' + formatVal(item[c]) + '</td>'; });
        Object.keys(nestedCols).forEach(parent => {
          nestedCols[parent].forEach(sub => { html += '<td>' + formatVal(item[parent] && item[parent][sub]) + '</td>'; });
        });
        html += '</tr>';
      });

      html += '</tbody></table></div>';
      return html;
    }

    // Minimal inlined chart renderer (no remote CDN / external scripts)
    function renderCharts(key, arr, theme) {
      const container = document.getElementById('charts_' + key);
      if (!container || !arr || arr.length === 0) return;
      container.innerHTML = '';

      const firstItem = arr[0];
      Object.keys(firstItem).forEach(col => {
        const val = firstItem[col];
        if (typeof val === 'number') {
          container.appendChild(buildLineChartSvg(arr.map((item, i) => item[col] || 0), col, theme));
        } else if (val && typeof val === 'object' && !Array.isArray(val)) {
          const subKeys = Object.keys(val);
          for (const subKey of subKeys.slice(0, 6)) {
            const series = arr.map((item) => (item[col] && item[col][subKey]) || 0);
            container.appendChild(buildLineChartSvg(series, String(col) + '.' + String(subKey), theme));
          }
        }
      });
    }

    function buildLineChartSvg(values, title, theme) {
      const width = 560;
      const height = 180;
      const pad = 24;
      const min = Math.min(...values);
      const max = Math.max(...values);
      const range = max - min || 1;
      const n = values.length;

      const pts = values.map((v, i) => {
        const x = pad + (i / Math.max(n - 1, 1)) * (width - pad * 2);
        const y = pad + (1 - (v - min) / range) * (height - pad * 2);
        return [x, y];
      });
      const d = pts
        .map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(2) + ',' + p[1].toFixed(2))
        .join(' ');

      const wrapper = document.createElement('div');
      wrapper.style.border = '1px solid var(--vscode-panel-border)';
      wrapper.style.borderRadius = '8px';
      wrapper.style.padding = '10px 12px';
      wrapper.style.marginBottom = '12px';
      wrapper.style.background = 'var(--results-surface)';

      const header = document.createElement('div');
      header.textContent = title;
      header.style.fontSize = '12px';
      header.style.fontWeight = '600';
      header.style.marginBottom = '8px';
      wrapper.appendChild(header);

      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 ' + String(width) + ' ' + String(height));
      svg.setAttribute('width', '100%');
      svg.setAttribute('height', '180');

      const grid = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      grid.setAttribute('x1', String(pad));
      grid.setAttribute('y1', String(height - pad));
      grid.setAttribute('x2', String(width - pad));
      grid.setAttribute('y2', String(height - pad));
      grid.setAttribute('stroke', theme.grid);
      grid.setAttribute('stroke-width', '1');
      svg.appendChild(grid);

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', theme.accent);
      path.setAttribute('stroke-width', '2');
      svg.appendChild(path);

      wrapper.appendChild(svg);
      return wrapper;
    }

    function showTab(tabId) {
      activeTabId = tabId;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      document.querySelector('[onclick*="' + tabId + '"]').classList.add('active');
      document.getElementById(tabId).classList.add('active');
    }

    let lastThemeClass = document.body.className;
    const themeObserver = new MutationObserver(() => {
      const nextThemeClass = document.body.className;
      if (nextThemeClass !== lastThemeClass) {
        lastThemeClass = nextThemeClass;
        renderTabs();
      }
    });
    themeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });

    // 渲染 JSON
    document.getElementById('jsonViewer').textContent = JSON.stringify(data, null, 2);

    // 复制数据功能
    document.getElementById('copyBtn').addEventListener('click', function() {
      var jsonStr = JSON.stringify(data, null, 2);
      navigator.clipboard.writeText(jsonStr).then(function() {
        var btn = document.getElementById('copyBtn');
        var originalText = btn.textContent;
        btn.textContent = '✓ ' + (isChinese ? '已复制' : 'Copied');
        setTimeout(function() { btn.textContent = originalText; }, 2000);
      }).catch(function() {
        alert(isChinese ? '复制失败' : 'Copy failed');
      });
    });

    // 初始化
    renderSummary();
    renderTabs();
  </script>
</body>
</html>`;
  }
}
