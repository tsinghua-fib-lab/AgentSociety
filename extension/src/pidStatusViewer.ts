/**
 * PID状态可视化查看器
 * 
 * 用于显示实验进程状态信息的Webview面板
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import {localize, isExtensionZh} from './i18n';

export class PidStatusViewer {
  public static currentPanel: PidStatusViewer | undefined;
  private readonly panel: vscode.WebviewPanel;
  private disposables: vscode.Disposable[] = [];

  private constructor(panel: vscode.WebviewPanel) {
    this.panel = panel;
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
  }

  public static async createOrShow(filePath: string): Promise<void> {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    if (PidStatusViewer.currentPanel) {
      PidStatusViewer.currentPanel.panel.reveal(column);
      PidStatusViewer.currentPanel.update(filePath);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      'pidStatusViewer',
      localize('projectStructure.experimentStatus'),
      column || vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      }
    );

    PidStatusViewer.currentPanel = new PidStatusViewer(panel);
    PidStatusViewer.currentPanel.update(filePath);
  }

  private update(filePath: string): void {
    let data: any = {};
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      data = JSON.parse(content);
    } catch (e) {
      // 读取失败
    }

    const isChinese = isExtensionZh();

    this.panel.webview.html = this.getWebviewContent(data, isChinese);
  }

  private getWebviewContent(data: any, isChinese: boolean): string {
    const esc = (value: unknown): string => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const status = String(data.status || 'unknown');
    const statusEmoji = status === 'completed' ? '✅' : status === 'running' ? '🔄' : status === 'failed' ? '❌' : '⏸️';
    const statusColor = status === 'completed' ? '#28a745' : status === 'running' ? '#007bff' : status === 'failed' ? '#dc3545' : '#6c757d';

    const labels = {
      title: isChinese ? '实验状态' : 'Experiment Status',
      pid: isChinese ? '进程ID' : 'Process ID',
      status: isChinese ? '状态' : 'Status',
      experimentId: isChinese ? '实验ID' : 'Experiment ID',
      startTime: isChinese ? '开始时间' : 'Start Time',
      endTime: isChinese ? '结束时间' : 'End Time',
      simulationTime: isChinese ? '模拟时间' : 'Simulation Time',
      stepCount: isChinese ? '步数' : 'Step Count',
      duration: isChinese ? '运行时长' : 'Duration',
      notAvailable: isChinese ? '不可用' : 'N/A',
    };

    // 计算运行时长
    let duration = labels.notAvailable;
    if (data.start_time) {
      const start = new Date(data.start_time);
      const end = data.end_time ? new Date(data.end_time) : new Date();
      const diffMs = end.getTime() - start.getTime();
      const hours = Math.floor(diffMs / 3600000);
      const minutes = Math.floor((diffMs % 3600000) / 60000);
      const seconds = Math.floor((diffMs % 60000) / 1000);
      duration = `${hours}h ${minutes}m ${seconds}s`;
    }

    return `<!DOCTYPE html>
<html lang="${isChinese ? 'zh-CN' : 'en'}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${labels.title}</title>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }
    body {
      font-family: var(--vscode-font-family);
      background-color: var(--vscode-editor-background);
      color: var(--vscode-editor-foreground);
      padding: 20px;
    }
    .container {
      max-width: 600px;
      margin: 0 auto;
    }
    .header {
      text-align: center;
      margin-bottom: 30px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--vscode-panel-border);
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 15px 30px;
      border-radius: 12px;
      font-size: 1.5em;
      font-weight: bold;
      color: white;
      background: ${statusColor};
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    .status-emoji {
      font-size: 1.2em;
    }
    .info-grid {
      display: grid;
      gap: 15px;
    }
    .info-item {
      display: grid;
      grid-template-columns: 150px 1fr;
      padding: 15px;
      background: var(--vscode-editor-inactiveSelectionBackground);
      border-radius: 8px;
      border-left: 4px solid var(--vscode-button-background);
    }
    .info-label {
      font-weight: 600;
      color: var(--vscode-descriptionForeground);
    }
    .info-value {
      font-family: var(--vscode-editor-font-family);
      word-break: break-all;
    }
    .running-animation {
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.7; }
    }
    .progress-section {
      margin-top: 30px;
      padding: 20px;
      background: var(--vscode-editor-inactiveSelectionBackground);
      border-radius: 12px;
    }
    .progress-title {
      font-size: 1.1em;
      font-weight: 600;
      margin-bottom: 15px;
    }
    .progress-bar {
      height: 20px;
      background: var(--vscode-progressBar-background);
      border-radius: 10px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--vscode-button-background), var(--vscode-button-hoverBackground));
      border-radius: 10px;
      transition: width 0.3s ease;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="status-badge ${status === 'running' ? 'running-animation' : ''}">
        <span class="status-emoji">${statusEmoji}</span>
        <span>${esc(status.toUpperCase())}</span>
      </div>
    </div>
    
    <div class="info-grid">
      ${data.pid ? `
      <div class="info-item">
        <span class="info-label">${labels.pid}</span>
        <span class="info-value">${esc(data.pid)}</span>
      </div>
      ` : ''}
      
      <div class="info-item">
        <span class="info-label">${labels.experimentId}</span>
        <span class="info-value">${esc(data.experiment_id || labels.notAvailable)}</span>
      </div>
      
      <div class="info-item">
        <span class="info-label">${labels.startTime}</span>
        <span class="info-value">${esc(data.start_time || labels.notAvailable)}</span>
      </div>
      
      ${data.end_time ? `
      <div class="info-item">
        <span class="info-label">${labels.endTime}</span>
        <span class="info-value">${esc(data.end_time)}</span>
      </div>
      ` : ''}
      
      <div class="info-item">
        <span class="info-label">${labels.duration}</span>
        <span class="info-value">${duration}</span>
      </div>
      
      ${data.simulation_time ? `
      <div class="info-item">
        <span class="info-label">${labels.simulationTime}</span>
        <span class="info-value">${esc(data.simulation_time)}</span>
      </div>
      ` : ''}
      
      ${data.step_count !== undefined ? `
      <div class="info-item">
        <span class="info-label">${labels.stepCount}</span>
        <span class="info-value">${esc(data.step_count)}</span>
      </div>
      ` : ''}
    </div>
  </div>
  
  <script>
    // 自动刷新（运行中的实验）。JSON.stringify 转义引号/反斜杠,
    // < 防 </script> 提前闭合(2026-11-06 二轮审计:此前裸拼可注入)。
    if (${JSON.stringify(String(status ?? '')).replace(/</g, '\\u003c')} === 'running') {
      setTimeout(() => location.reload(), 5000);
    }
  </script>
</body>
</html>`;
  }

  private dispose(): void {
    PidStatusViewer.currentPanel = undefined;
    this.panel.dispose();
    this.disposables.forEach(d => d.dispose());
  }
}
