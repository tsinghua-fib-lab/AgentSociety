/**
 * Steps YAML 预览器 - 以时间线方式显示 steps.yaml，支持编辑
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as yaml from 'js-yaml';
import { isExtensionZh } from './i18n';

interface RunStep {
  type: 'run';
  num_steps?: number;
  tick?: number;
}

interface AskStep {
  type: 'ask';
  question?: string;
}

interface InterveneStep {
  type: 'intervene';
  target?: string;
  action?: string;
  params?: Record<string, any>;
}

interface QuestionItem {
  id: string;
  prompt: string;
  response_type?: 'text' | 'integer' | 'float' | 'choice' | 'json';
  choices?: string[];
}

interface QuestionnaireStep {
  type: 'questionnaire';
  questionnaire_id: string;
  title?: string;
  description?: string;
  target_agent_ids?: number[];
  questions?: QuestionItem[];
}

type Step = RunStep | AskStep | InterveneStep | QuestionnaireStep;

interface StepsConfig {
  start_t?: string;
  steps?: Step[];
}

export class StepsViewer {
  private static currentPanel: vscode.WebviewPanel | undefined;
  private static currentFilePath: string | undefined;

  public static async show(context: vscode.ExtensionContext, filePath: string): Promise<void> {
    let data: StepsConfig;
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      data = yaml.load(content) as StepsConfig;
    } catch (error: any) {
      vscode.window.showErrorMessage(`无法读取 steps.yaml: ${error.message}`);
      return;
    }

    this.currentFilePath = filePath;

    if (this.currentPanel) {
      this.currentPanel.reveal(vscode.ViewColumn.One);
      this.updateWebview(this.currentPanel, data, filePath, context);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      'stepsViewer',
      '实验步骤预览',
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      }
    );

    this.currentPanel = panel;

    panel.webview.onDidReceiveMessage(async (message) => {
      if (message.command === 'save' && this.currentFilePath) {
        try {
          fs.writeFileSync(this.currentFilePath, message.content, 'utf-8');
          vscode.window.showInformationMessage('步骤配置已保存');
          panel.webview.postMessage({ command: 'saved' });
        } catch (e: any) {
          vscode.window.showErrorMessage(`保存失败: ${e.message}`);
        }
      }
    });

    panel.onDidDispose(() => {
      this.currentPanel = undefined;
      this.currentFilePath = undefined;
    });

    this.updateWebview(panel, data, filePath, context);
  }

  private static updateWebview(
    panel: vscode.WebviewPanel,
    data: StepsConfig,
    filePath: string,
    context: vscode.ExtensionContext
  ): void {
    const steps = data.steps || [];
    const isChinese = isExtensionZh();
    const serializedYaml = this.serializeStepsConfig(data);

    const runCount = steps.filter(s => s.type === 'run').length;
    const askCount = steps.filter(s => s.type === 'ask').length;
    const interveneCount = steps.filter(s => s.type === 'intervene').length;
    const questionnaireCount = steps.filter(s => s.type === 'questionnaire').length;

    const stepSnippets: Record<string, string> = {
      run: '\n  - type: run\n    num_steps: 10\n    tick: 60\n',
      ask: isChinese
        ? '\n  - type: ask\n    question: "在此填写问题"\n'
        : '\n  - type: ask\n    question: "Your question here"\n',
      intervene: '\n  - type: intervene\n    target: agent_0\n    action: noop\n    params: {}\n',
      questionnaire: isChinese
        ? '\n  - type: questionnaire\n    questionnaire_id: q1\n    title: 问卷标题\n    questions:\n      - id: q1_1\n        prompt: 题目内容\n        response_type: text\n'
        : '\n  - type: questionnaire\n    questionnaire_id: q1\n    title: Questionnaire title\n    questions:\n      - id: q1_1\n        prompt: Question text\n        response_type: text\n',
    };

    panel.webview.html = `
<!DOCTYPE html>
<html lang="${isChinese ? 'zh-CN' : 'en'}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${isChinese ? '实验步骤预览' : 'Steps Preview'}</title>
  <style>
    :root {
      --steps-run-color: var(--vscode-testing-iconPassed, #52c41a);
      --steps-ask-color: var(--vscode-textLink-foreground, #1890ff);
      --steps-intervene-color: var(--vscode-editorWarning-foreground, #faad14);
      --steps-questionnaire-color: var(--vscode-terminal-ansiCyan, #13c2c2);
      --steps-run-bg: rgba(82, 196, 26, 0.15);
      --steps-ask-bg: rgba(24, 144, 255, 0.15);
      --steps-intervene-bg: rgba(250, 173, 20, 0.15);
      --steps-questionnaire-bg: rgba(19, 194, 194, 0.15);
      --steps-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
      --steps-question-bg: rgba(24, 144, 255, 0.08);
      --steps-question-border: var(--steps-ask-color);
      --steps-card-bg: var(--vscode-input-background);
      --steps-card-border: var(--vscode-panel-border);
    }

    body.vscode-dark,
    body.vscode-high-contrast {
      --steps-run-bg: rgba(82, 196, 26, 0.22);
      --steps-ask-bg: rgba(24, 144, 255, 0.24);
      --steps-intervene-bg: rgba(250, 173, 20, 0.24);
      --steps-questionnaire-bg: rgba(19, 194, 194, 0.24);
      --steps-shadow: 0 4px 14px rgba(0, 0, 0, 0.3);
      --steps-question-bg: rgba(24, 144, 255, 0.18);
    }

    body {
      font-family: var(--vscode-font-family);
      background-color: var(--vscode-editor-background);
      color: var(--vscode-editor-foreground);
      padding: 24px;
      max-width: 1000px;
      margin: 0 auto;
    }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--vscode-panel-border);
    }

    .header h1 {
      margin: 0;
      font-size: 24px;
    }

    .stats {
      display: flex;
      gap: 16px;
    }

    .stat-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      border-radius: 16px;
      font-size: 13px;
    }

    .stat-badge.run {
      background-color: var(--steps-run-bg);
      color: var(--steps-run-color);
    }

    .stat-badge.ask {
      background-color: var(--steps-ask-bg);
      color: var(--steps-ask-color);
    }

    .stat-badge.intervene {
      background-color: var(--steps-intervene-bg);
      color: var(--steps-intervene-color);
    }

    .stat-badge.questionnaire {
      background-color: var(--steps-questionnaire-bg);
      color: var(--steps-questionnaire-color);
    }

    .start-time {
      background-color: var(--vscode-input-background);
      padding: 12px 16px;
      border-radius: 8px;
      margin-bottom: 24px;
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .start-time-label {
      color: var(--vscode-descriptionForeground);
      font-size: 13px;
    }

    .start-time-value {
      font-weight: 600;
      font-size: 15px;
    }

    .timeline {
      position: relative;
      padding-left: 32px;
    }

    .timeline::before {
      content: '';
      position: absolute;
      left: 12px;
      top: 0;
      bottom: 0;
      width: 2px;
      background-color: var(--vscode-panel-border);
    }

    .step {
      position: relative;
      margin-bottom: 20px;
      padding: 16px;
      background-color: var(--vscode-editor-background);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 8px;
      transition: box-shadow 0.2s;
    }

    .step:hover {
      box-shadow: var(--steps-shadow);
    }

    .step::before {
      content: '';
      position: absolute;
      left: -26px;
      top: 20px;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      border: 2px solid var(--vscode-panel-border);
      background-color: var(--vscode-editor-background);
    }

    .step.run::before {
      background-color: var(--steps-run-color);
      border-color: var(--steps-run-color);
    }

    .step.ask::before {
      background-color: var(--steps-ask-color);
      border-color: var(--steps-ask-color);
    }

    .step.intervene::before {
      background-color: var(--steps-intervene-color);
      border-color: var(--steps-intervene-color);
    }

    .step.questionnaire::before {
      background-color: var(--steps-questionnaire-color);
      border-color: var(--steps-questionnaire-color);
    }

    .step-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }

    .step-type {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .step-icon {
      font-size: 18px;
    }

    .step-label {
      font-weight: 600;
      font-size: 14px;
      text-transform: uppercase;
    }

    .step-label.run { color: var(--steps-run-color); }
    .step-label.ask { color: var(--steps-ask-color); }
    .step-label.intervene { color: var(--steps-intervene-color); }
    .step-label.questionnaire { color: var(--steps-questionnaire-color); }

    .step-number {
      background-color: var(--vscode-badge-background);
      color: var(--vscode-badge-foreground);
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 12px;
    }

    .step-content {
      font-size: 13px;
      line-height: 1.6;
    }

    .step-params {
      margin-top: 12px;
      padding: 12px;
      background-color: var(--vscode-input-background);
      border-radius: 6px;
      font-family: var(--vscode-editor-font-family);
      font-size: 12px;
    }

    .param-row {
      display: flex;
      gap: 8px;
      margin-bottom: 4px;
    }

    .param-row:last-child {
      margin-bottom: 0;
    }

    .param-key {
      color: var(--vscode-textPreformat-foreground);
      min-width: 80px;
    }

    .param-value {
      color: var(--vscode-editor-foreground);
    }

    .question-box {
      margin-top: 12px;
      padding: 12px 16px;
      background-color: var(--steps-ask-bg);
      border-left: 3px solid var(--steps-question-border);
      border-radius: 0 6px 6px 0;
      font-size: 13px;
      line-height: 1.6;
    }

    .questionnaire-block {
      margin-top: 12px;
      display: grid;
      gap: 12px;
    }

    .questionnaire-meta {
      padding: 12px 16px;
      background-color: var(--steps-questionnaire-bg);
      border-left: 3px solid var(--steps-questionnaire-color);
      border-radius: 0 6px 6px 0;
      font-size: 13px;
      line-height: 1.7;
    }

    .questionnaire-title {
      font-size: 15px;
      font-weight: 600;
      margin-bottom: 6px;
    }

    .questionnaire-description {
      color: var(--vscode-descriptionForeground);
    }

    .questionnaire-targets {
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }

    .target-pill,
    .response-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 2px 10px;
      border-radius: 999px;
      background-color: var(--steps-card-bg);
      border: 1px solid var(--steps-card-border);
      font-size: 12px;
    }

    .question-list {
      display: grid;
      gap: 12px;
    }

    .question-card {
      padding: 14px 16px;
      border: 1px solid var(--steps-card-border);
      border-radius: 8px;
      background-color: var(--steps-card-bg);
    }

    .question-card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
    }

    .question-id {
      font-size: 12px;
      color: var(--vscode-descriptionForeground);
      font-family: var(--vscode-editor-font-family);
    }

    .question-prompt {
      font-size: 13px;
      line-height: 1.6;
      white-space: pre-wrap;
    }

    .choices-wrap {
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .choice-pill {
      display: inline-flex;
      align-items: center;
      padding: 3px 10px;
      border-radius: 999px;
      background-color: var(--steps-question-bg);
      border: 1px solid var(--steps-question-border);
      font-size: 12px;
    }

    .empty-state {
      text-align: center;
      padding: 48px;
      color: var(--vscode-descriptionForeground);
    }

    .snippet-bar {
      display: none;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 12px;
      padding: 10px 12px;
      border-radius: 6px;
      border: 1px solid var(--vscode-panel-border);
      background-color: var(--vscode-sideBar-background);
    }

    .snippet-bar-label {
      font-size: 12px;
      color: var(--vscode-descriptionForeground);
      flex: 0 0 100%;
    }

    @media (min-width: 560px) {
      .snippet-bar-label {
        flex: 0 0 auto;
        margin-right: 6px;
      }
    }

    .snippet-btn {
      font-size: 12px;
      padding: 4px 10px;
      border-radius: 4px;
      border: 1px solid var(--vscode-button-border);
      background-color: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      cursor: pointer;
    }

    .snippet-btn:hover {
      background-color: var(--vscode-button-secondaryHoverBackground);
    }

    .copy-btn {
      padding: 6px 12px;
      background-color: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }
    .copy-btn:hover {
      background-color: var(--vscode-button-hoverBackground);
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>📋 ${isChinese ? '实验步骤预览' : 'Steps Preview'}</h1>
    <div style="display: flex; align-items: center; gap: 16px;">
      <button class="copy-btn" id="editBtn" style="background: var(--vscode-button-secondaryBackground);">✏️ ${isChinese ? '编辑' : 'Edit'}</button>
      <button class="copy-btn" id="copyBtn">📋 ${isChinese ? '复制配置' : 'Copy Config'}</button>
      <div class="stats">
      <span class="stat-badge run">▶ Run × ${runCount}</span>
      <span class="stat-badge ask">❓ Ask × ${askCount}</span>
      <span class="stat-badge intervene">✋ Intervene × ${interveneCount}</span>
      <span class="stat-badge questionnaire">📝 Questionnaire × ${questionnaireCount}</span>
      </div>
    </div>
  </div>

  ${data.start_t ? `
    <div class="start-time">
      <span class="start-time-label">${isChinese ? '📅 开始时间' : '📅 Start Time'}:</span>
      <span class="start-time-value">${data.start_t}</span>
    </div>
  ` : ''}

  <div class="timeline" id="timeline"></div>
  
  <div id="editor" style="display: none; margin-top: 24px;">
    <div id="snippetBar" class="snippet-bar">
      <span class="snippet-bar-label">${isChinese ? '在光标处插入：' : 'Insert at cursor:'}</span>
      <button type="button" class="snippet-btn" data-snippet="run">Run</button>
      <button type="button" class="snippet-btn" data-snippet="ask">Ask</button>
      <button type="button" class="snippet-btn" data-snippet="intervene">Intervene</button>
      <button type="button" class="snippet-btn" data-snippet="questionnaire">${isChinese ? '问卷' : 'Questionnaire'}</button>
    </div>
    <textarea id="yamlEditor" style="width: 100%; min-height: 300px; padding: 12px; background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border); border-radius: 6px; color: var(--vscode-input-foreground); font-family: var(--vscode-editor-font-family); font-size: 13px; resize: vertical;"></textarea>
    <div style="margin-top: 12px; display: flex; gap: 8px;">
      <button class="copy-btn" id="saveBtn">💾 ${isChinese ? '保存' : 'Save'}</button>
      <button class="copy-btn" id="cancelBtn" style="background: var(--vscode-button-secondaryBackground);">${isChinese ? '取消' : 'Cancel'}</button>
    </div>
  </div>

  <script>
    const steps = ${JSON.stringify(steps)};
    const startT = ${JSON.stringify(data.start_t || '')};
    const serializedYaml = ${JSON.stringify(serializedYaml)};
    const stepSnippets = ${JSON.stringify(stepSnippets)};
    const isChinese = ${isChinese ? 'true' : 'false'};
    const vscode = acquireVsCodeApi();
    
    let isEditing = false;

    function escapeHtml(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }
    
    function toggleEditor() {
      const editor = document.getElementById('editor');
      const timeline = document.getElementById('timeline');
      const bar = document.getElementById('snippetBar');
      isEditing = !isEditing;
      
      if (isEditing) {
        editor.style.display = 'block';
        timeline.style.display = 'none';
        bar.style.display = 'flex';
        document.getElementById('yamlEditor').value = serializedYaml;
        document.getElementById('editBtn').textContent = '👁️ ' + (isChinese ? '预览' : 'Preview');
      } else {
        editor.style.display = 'none';
        timeline.style.display = 'block';
        bar.style.display = 'none';
        document.getElementById('editBtn').textContent = '✏️ ' + (isChinese ? '编辑' : 'Edit');
      }
    }

    function insertSnippetAtCursor(text) {
      const ta = document.getElementById('yamlEditor');
      const start = typeof ta.selectionStart === 'number' ? ta.selectionStart : ta.value.length;
      const end = typeof ta.selectionEnd === 'number' ? ta.selectionEnd : start;
      const v = ta.value;
      ta.value = v.slice(0, start) + text + v.slice(end);
      ta.focus();
      const pos = start + text.length;
      ta.setSelectionRange(pos, pos);
    }

    function bindSnippetBar() {
      document.querySelectorAll('.snippet-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
          const key = btn.getAttribute('data-snippet');
          const text = stepSnippets[key] || '';
          if (text) {
            insertSnippetAtCursor(text);
          }
        });
      });
    }
    bindSnippetBar();
    
    document.getElementById('editBtn').addEventListener('click', toggleEditor);
    
    document.getElementById('saveBtn').addEventListener('click', function() {
      const content = document.getElementById('yamlEditor').value;
      vscode.postMessage({ command: 'save', content: content });
    });
    
    document.getElementById('cancelBtn').addEventListener('click', function() {
      toggleEditor();
    });

    function renderSteps() {
      const container = document.getElementById('timeline');

      if (steps.length === 0) {
        container.innerHTML = '<div class="empty-state">' + (isChinese ? '暂无步骤配置' : 'No steps configured') + '</div>';
        return;
      }

      const icons = {
        run: '▶️',
        ask: '❓',
        intervene: '✋',
        questionnaire: '📝'
      };

      const labels = {
        run: isChinese ? '运行模拟' : 'Run Simulation',
        ask: isChinese ? '提问观察' : 'Ask Question',
        intervene: isChinese ? '干预操作' : 'Intervene',
        questionnaire: isChinese ? '问卷收集' : 'Questionnaire'
      };

      steps.forEach((step, index) => {
        const div = document.createElement('div');
        div.className = 'step ' + step.type;

        let content = '';

        if (step.type === 'run') {
          content = \`
            <div class="step-params">
              <div class="param-row">
                <span class="param-key">num_steps:</span>
                <span class="param-value">\${escapeHtml(step.num_steps || 1)}</span>
              </div>
              <div class="param-row">
                <span class="param-key">tick:</span>
                <span class="param-value">\${escapeHtml(step.tick || 60)}s</span>
              </div>
            </div>
          \`;
        } else if (step.type === 'ask') {
          content = \`
            <div class="question-box">\${escapeHtml(step.question || (isChinese ? '(无问题)' : '(No question)'))}</div>
          \`;
        } else if (step.type === 'intervene') {
          const params = Object.entries(step.params || {}).map(([k, v]) => \`<div class="param-row"><span class="param-key">\${escapeHtml(k)}:</span><span class="param-value">\${escapeHtml(JSON.stringify(v))}</span></div>\`).join('');
          content = \`
            <div class="step-params">
              <div class="param-row">
                <span class="param-key">target:</span>
                <span class="param-value">\${escapeHtml(step.target || '-')}</span>
              </div>
              <div class="param-row">
                <span class="param-key">action:</span>
                <span class="param-value">\${escapeHtml(step.action || '-')}</span>
              </div>
              \${params}
            </div>
          \`;
        } else if (step.type === 'questionnaire') {
          const questionItems = (step.questions || []).map((question, questionIndex) => {
            const choiceHtml = Array.isArray(question.choices) && question.choices.length > 0
              ? \`<div class="choices-wrap">\${question.choices.map((choice) => \`<span class="choice-pill">\${escapeHtml(choice)}</span>\`).join('')}</div>\`
              : '';

            return \`
              <div class="question-card">
                <div class="question-card-header">
                  <span class="question-id">\${escapeHtml(question.id || 'q_' + (questionIndex + 1))}</span>
                  <span class="response-pill">\${escapeHtml(question.response_type || 'text')}</span>
                </div>
                <div class="question-prompt">\${escapeHtml(question.prompt || (isChinese ? '(无题目内容)' : '(No prompt)'))}</div>
                \${choiceHtml}
              </div>
            \`;
          }).join('');

          const targetAgents = Array.isArray(step.target_agent_ids) && step.target_agent_ids.length > 0
            ? step.target_agent_ids.map((agentId) => \`<span class="target-pill">Agent \${escapeHtml(agentId)}</span>\`).join('')
            : \`<span class="target-pill">\${isChinese ? '全部 Agent' : 'All Agents'}</span>\`;

          content = \`
            <div class="questionnaire-block">
              <div class="questionnaire-meta">
                <div class="questionnaire-title">\${escapeHtml(step.title || step.questionnaire_id || (isChinese ? '未命名问卷' : 'Untitled Questionnaire'))}</div>
                <div><strong>questionnaire_id:</strong> \${escapeHtml(step.questionnaire_id || '-')}</div>
                \${step.description ? \`<div class="questionnaire-description">\${escapeHtml(step.description)}</div>\` : ''}
                <div class="questionnaire-targets">
                  <strong>\${isChinese ? '目标对象' : 'Targets'}:</strong>
                  \${targetAgents}
                </div>
              </div>
              <div>
                <div style="margin-bottom: 8px; font-weight: 600;">\${isChinese ? '题目列表' : 'Questions'} (\${(step.questions || []).length})</div>
                <div class="question-list">
                  \${questionItems || \`<div class="empty-state" style="padding: 20px;">\${isChinese ? '暂无题目' : 'No questions configured'}</div>\`}
                </div>
              </div>
            </div>
          \`;
        }

        div.innerHTML = \`
          <div class="step-header">
            <div class="step-type">
              <span class="step-icon">\${icons[step.type]}</span>
              <span class="step-label \${step.type}">\${labels[step.type]}</span>
            </div>
            <span class="step-number">#\${index + 1}</span>
          </div>
          <div class="step-content">
            \${content}
          </div>
        \`;

        container.appendChild(div);
      });
    }

    // 复制步骤配置
    document.getElementById('copyBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(serializedYaml).then(function() {
        const btn = document.getElementById('copyBtn');
        const originalText = btn.textContent;
        btn.textContent = '✓ ' + (isChinese ? '已复制' : 'Copied');
        setTimeout(function() { btn.textContent = originalText; }, 2000);
      }).catch(function() {
        alert(isChinese ? '复制失败' : 'Copy failed');
      });
    });

    renderSteps();
  </script>
</body>
</html>`;
  }

  private static serializeStepsConfig(data: StepsConfig): string {
    return yaml.dump(
      {
        ...(data.start_t !== undefined ? { start_t: data.start_t } : {}),
        steps: data.steps || [],
      },
      {
        noRefs: true,
        lineWidth: -1,
        sortKeys: false,
      }
    );
  }
}
