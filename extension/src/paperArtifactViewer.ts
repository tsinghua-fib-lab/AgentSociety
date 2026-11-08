/**
 * Paper Artifact Viewer — 论文产物专用查看器
 *
 * 根据文件名自动识别文件类型，使用对应的专用展示模式：
 * - paper.json        → 论文工作区状态（章节、图表、编译、审阅）
 * - research_pack.json → 研究包总览（假设、实验、图表、文献）
 * - claims.json       → 分析主张列表（批准/待批准、证据）
 * - synthesis_brief.json → 综合摘要
 * - evidence_index.json / evidence_graph.json → 证据图谱
 * - review_*.json     → 审阅结果（评分、维度、阻塞项）
 * - run.json          → 编译记录
 * - 其他 JSON         → 通用 JSON 树形查看
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'js-yaml';
import { isExtensionZh } from './i18n';

const MAX_FILE_BYTES = 8 * 1024 * 1024;

export class PaperArtifactViewer {
  private static currentPanel: vscode.WebviewPanel | undefined;

  public static async show(filePath: string): Promise<void> {
    const isZh = isExtensionZh();
    let data: any = null;
    let error: string | null = null;

    const fileName = path.basename(filePath);
    const parentDir = path.basename(path.dirname(filePath));
    const lower = filePath.toLowerCase();

    try {
      const stat = fs.statSync(filePath);
      if (stat.size > MAX_FILE_BYTES) {
        error = isZh
          ? `文件过大（>${Math.floor(MAX_FILE_BYTES / 1024 / 1024)}MB），请用编辑器打开`
          : `File too large (>${Math.floor(MAX_FILE_BYTES / 1024 / 1024)}MB); open in editor`;
      } else {
        const raw = fs.readFileSync(filePath, 'utf-8');
        data = lower.endsWith('.yaml') || lower.endsWith('.yml')
          ? yaml.load(raw)
          : JSON.parse(raw);
      }
    } catch (e: any) {
      error = e.message;
    }

    const panelTitle = this.getTitle(fileName, parentDir, isZh);

    if (this.currentPanel) {
      this.currentPanel.title = panelTitle;
      this.currentPanel.reveal(vscode.ViewColumn.One);
      this.currentPanel.webview.html = this.buildHtml(data, error, fileName, parentDir, filePath, isZh);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      'paperArtifactViewer',
      panelTitle,
      vscode.ViewColumn.One,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    this.currentPanel = panel;
    panel.onDidDispose(() => { this.currentPanel = undefined; });
    panel.webview.html = this.buildHtml(data, error, fileName, parentDir, filePath, isZh);
  }

  /** 全量 HTML 转义(2026-11-06 二轮审计:本 viewer 此前多处只转 & 或
   * 完全裸插值,LLM 生成的论文产物含 <img onerror> 即注入;统一走此)。 */
  private static esc(value: unknown): string {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  private static getTitle(fileName: string, _parentDir: string, isZh: boolean): string {
    const titles: Record<string, string> = {
      'paper.json': isZh ? '论文工作区状态' : 'Paper workspace state',
      'research_pack.json': isZh ? '研究包' : 'Research pack',
      'claims.json': isZh ? '分析主张' : 'Claims',
      'synthesis_brief.json': isZh ? '综合摘要' : 'Synthesis brief',
      'evidence_index.json': isZh ? '证据索引' : 'Evidence index',
      'evidence_graph.json': isZh ? '证据图谱' : 'Evidence graph',
      'run.json': isZh ? '编译记录' : 'Compile run',
    };
    if (titles[fileName]) {return titles[fileName];}
    if (fileName.startsWith('review_') && fileName.endsWith('.json')) {
      return isZh ? '审阅结果' : 'Review';
    }
    return fileName;
  }

  private static buildHtml(
    data: any,
    error: string | null,
    fileName: string,
    _parentDir: string,
    filePath: string,
    isZh: boolean
  ): string {
    if (error || !data) {
      return this.errorHtml(error || 'No data', filePath, isZh);
    }

    if (fileName === 'paper_meta.yaml' || fileName === 'paper_state.yaml') {return this.renderPaperState(data, filePath, isZh);}
    if (fileName === 'research_pack.json') {return this.renderResearchPack(data, filePath, isZh);}
    if (fileName === 'claim_ledger.json' || fileName === 'claims.json') {return this.renderClaims(data, filePath, isZh);}
    if (fileName === 'synthesis_brief.json') {return this.renderSynthesisBrief(data, filePath, isZh);}
    if (fileName === 'evidence_index.json' || fileName === 'evidence_graph.json' || fileName === 'evidence_backlog.json') {return this.renderEvidenceGraph(data, filePath, isZh);}
    if (fileName === 'figure_argument_map.json') {return this.renderFigureArgMap(data, filePath, isZh);}
    if (fileName === 'storyline_map.json') {return this.renderStoryline(data, filePath, isZh);}
    if (fileName.startsWith('review_') && (fileName.endsWith('.json') || fileName.endsWith('.yaml'))) {return this.renderReview(data, filePath, isZh);}
    if (fileName === 'run.json') {return this.renderCompileRun(data, filePath, isZh);}
    if (fileName === 'human_gates.yaml') {return this.renderHumanGates(data, filePath, isZh);}

    // Fallback: generic JSON tree
    return this.renderGenericJson(data, filePath, isZh);
  }

  private static baseLayout(title: string, filePath: string, isZh: boolean, body: string): string {
    const safePath = filePath.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const pathLiteral = JSON.stringify(filePath);
    const labels = {
      copyPath: isZh ? '复制路径' : 'Copy Path',
      openEditor: isZh ? '在编辑器中打开' : 'Open in editor',
      openRaw: isZh ? '打开原始 JSON' : 'Open raw JSON',
    };
    return `<!DOCTYPE html>
<html lang="${isZh ? 'zh-CN' : 'en'}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${this.esc(title)}</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: var(--vscode-font-family); background: var(--vscode-editor-background); color: var(--vscode-editor-foreground); padding: 20px; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--vscode-panel-border); flex-wrap: wrap; gap: 8px; }
    .header h1 { font-size: 18px; }
    .header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .btn { padding: 6px 12px; background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
    .btn:hover { background: var(--vscode-button-secondaryHoverBackground); }
    .path { font-size: 11px; color: var(--vscode-descriptionForeground); margin-bottom: 16px; word-break: break-all; }
    .card { background: var(--vscode-editorWidget-background); border: 1px solid var(--vscode-panel-border); border-radius: 8px; padding: 14px; margin-bottom: 12px; }
    .card h2 { font-size: 14px; margin-bottom: 8px; color: var(--vscode-editor-foreground); }
    .card h3 { font-size: 12px; margin-bottom: 6px; color: var(--vscode-descriptionForeground); }
    .kv { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--vscode-panel-border); font-size: 12px; }
    .kv:last-child { border-bottom: none; }
    .kv-key { color: var(--vscode-descriptionForeground); }
    .kv-value { color: var(--vscode-editor-foreground); font-weight: 500; }
    .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin: 2px 4px 2px 0; }
    .tag-green { background: rgba(82, 196, 26, 0.15); color: #52c41a; }
    .tag-red { background: rgba(255, 77, 79, 0.15); color: #ff4d4f; }
    .tag-blue { background: rgba(22, 119, 255, 0.15); color: #1677ff; }
    .tag-orange { background: rgba(250, 140, 22, 0.15); color: #fa8c16; }
    .tag-purple { background: rgba(114, 46, 209, 0.15); color: #722ed1; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
    .stat { text-align: center; padding: 12px; }
    .stat-value { font-size: 24px; font-weight: 700; }
    .stat-label { font-size: 11px; color: var(--vscode-descriptionForeground); margin-top: 4px; }
    .list-item { padding: 8px 10px; border: 1px solid var(--vscode-panel-border); border-radius: 6px; margin-bottom: 6px; font-size: 12px; }
    .list-item:hover { background: var(--vscode-list-hoverBackground); }
    .dimension-bar { height: 6px; border-radius: 3px; margin: 4px 0 8px; background: var(--vscode-panel-border); }
    .dimension-fill { height: 100%; border-radius: 3px; }
    .section { margin-bottom: 20px; }
    .error-box { padding: 16px; background: rgba(255, 77, 79, 0.1); border: 1px solid #ff4d4f; border-radius: 6px; color: #ff4d4f; }
    .text-secondary { font-size: 11px; color: var(--vscode-descriptionForeground); }
    .mono { font-family: var(--vscode-editor-font-family); font-size: 12px; }
    pre { background: var(--vscode-editor-background); border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: 12px; overflow: auto; max-height: 400px; }
  </style>
</head>
<body>
  <div class="header">
    <h1>📄 ${this.esc(title)}</h1>
    <div class="header-actions">
      <button class="btn" id="copyPathBtn">📋 ${labels.copyPath}</button>
      <button class="btn" id="openEditorBtn">${labels.openEditor}</button>
      <button class="btn" id="openRawBtn">${labels.openRaw}</button>
    </div>
  </div>
  <div class="path">${safePath}</div>
  ${body}
  <script>
    const vscode = acquireVsCodeApi();
    const filePath = ${pathLiteral};
    document.getElementById('copyPathBtn').addEventListener('click', function() {
      navigator.clipboard.writeText(filePath).then(function() {
        this.textContent = '${isZh ? '已复制' : 'Copied'}';
        setTimeout(function() { this.textContent = '${labels.copyPath}'; }.bind(this), 2000);
      }.bind(this));
    });
    document.getElementById('openEditorBtn').addEventListener('click', function() {
      vscode.postMessage({ command: 'openInEditor', filePath: filePath });
    });
    document.getElementById('openRawBtn').addEventListener('click', function() {
      vscode.postMessage({ command: 'openRaw', filePath: filePath });
    });
  </script>
</body>
</html>`;
  }

  // ── Renderers ──────────────────────────────────────────────

  private static renderPaperState(data: any, filePath: string, isZh: boolean): string {
    const sections = data.sections ?? [];
    const figures = data.figures ?? [];
    const tables = data.tables ?? [];
    const compileRuns = data.compile_runs ?? [];
    const reviews = data.reviews ?? [];
    const gates = data.human_gates ?? {};

    const body = `
    <div class="grid">
      <div class="card stat"><div class="stat-value" style="color:#1677ff">${Array.isArray(sections) ? sections.length : 0}</div><div class="stat-label">${isZh ? '章节' : 'Sections'}</div></div>
      <div class="card stat"><div class="stat-value" style="color:#52c41a">${Array.isArray(figures) ? figures.length : 0}</div><div class="stat-label">${isZh ? '图表' : 'Figures'}</div></div>
      <div class="card stat"><div class="stat-value" style="color:#fa8c16">${Array.isArray(tables) ? tables.length : 0}</div><div class="stat-label">${isZh ? '表格' : 'Tables'}</div></div>
      <div class="card stat"><div class="stat-value" style="color:#722ed1">${Array.isArray(compileRuns) ? compileRuns.length : 0}</div><div class="stat-label">${isZh ? '编译' : 'Compiles'}</div></div>
    </div>
    ${gates && Object.keys(gates).length > 0 ? `
    <div class="card"><h2>${isZh ? '人工确认门' : 'Human Gates'}</h2>
      ${Object.entries(gates).map(([k, v]: [string, any]) => `<div class="kv"><span class="kv-key">${this.esc(k)}</span><span class="kv-value">${this.esc(v?.note || v?.status || String(v))}</span></div>`).join('')}
    </div>` : ''}
    ${Array.isArray(reviews) && reviews.length > 0 ? `
    <div class="card"><h2>${isZh ? '审阅记录' : 'Reviews'} (${reviews.length})</h2>
      ${reviews.map((r: any) => `<div class="list-item"><span class="tag tag-blue">${this.esc(r.id || '')}</span> ${this.esc(r.verdict || '')}</div>`).join('')}
    </div>` : ''}`;
    return this.baseLayout(isZh ? '论文工作区状态' : 'Paper workspace state', filePath, isZh, body);
  }

  private static renderResearchPack(data: any, filePath: string, isZh: boolean): string {
    const hypotheses = data.hypotheses ?? [];
    const experiments = data.experiments ?? [];
    const figures = data.figures ?? [];
    const references = data.references ?? [];
    const body = `
    <div class="grid">
      <div class="card stat"><div class="stat-value" style="color:#1677ff">${Array.isArray(hypotheses) ? hypotheses.length : 0}</div><div class="stat-label">${isZh ? '假设' : 'Hypotheses'}</div></div>
      <div class="card stat"><div class="stat-value" style="color:#52c41a">${Array.isArray(experiments) ? experiments.length : 0}</div><div class="stat-label">${isZh ? '实验' : 'Experiments'}</div></div>
      <div class="card stat"><div class="stat-value" style="color:#fa8c16">${Array.isArray(figures) ? figures.length : 0}</div><div class="stat-label">${isZh ? '图表' : 'Figures'}</div></div>
      <div class="card stat"><div class="stat-value" style="color:#722ed1">${Array.isArray(references) ? references.length : 0}</div><div class="stat-label">${isZh ? '文献' : 'References'}</div></div>
    </div>`;
    return this.baseLayout(isZh ? '研究包' : 'Research pack', filePath, isZh, body);
  }

  private static renderClaims(data: any, filePath: string, isZh: boolean): string {
    const claims = Array.isArray(data) ? data : (data.claims ?? []);
    const approved = claims.filter((c: any) => c.approved !== false).length;
    const body = `
    <div class="card"><h2>${isZh ? '主张' : 'Claims'} (${approved}/${claims.length} ${isZh ? '已批准' : 'approved'})</h2></div>
    ${claims.map((c: any) => `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span class="tag ${c.approved !== false ? 'tag-green' : 'tag-red'}">${c.approved !== false ? (isZh ? '已批准' : 'Approved') : (isZh ? '待批准' : 'Pending')}</span>
          ${c.needs_chart ? `<span class="tag tag-orange">${isZh ? '需配图' : 'Needs chart'}</span>` : ''}
        </div>
        <div style="font-size:13px;margin-bottom:4px">${this.esc(c.statement || c.claim || '')}</div>
        ${c.evidence ? `<div class="text-secondary">${isZh ? '证据' : 'Evidence'}: ${this.esc(c.evidence)}</div>` : ''}
      </div>`).join('')}`;
    return this.baseLayout(isZh ? '分析主张' : 'Claims', filePath, isZh, body);
  }

  private static renderSynthesisBrief(data: any, filePath: string, isZh: boolean): string {
    const body = `
    <div class="card"><h2>${this.esc(data.question || (isZh ? '综合问题' : 'Synthesis question'))}</h2></div>
    ${data.comparison_mode ? `<div class="card"><h3>${isZh ? '比较模式' : 'Comparison mode'}</h3><p>${this.esc(data.comparison_mode)}</p></div>` : ''}
    ${data.findings ? `<div class="card"><h3>${isZh ? '发现' : 'Findings'}</h3><p>${this.esc(data.findings).replace(/\n/g,'<br>')}</p></div>` : ''}`;
    return this.baseLayout(isZh ? '综合摘要' : 'Synthesis brief', filePath, isZh, body);
  }

  private static renderEvidenceGraph(data: any, filePath: string, isZh: boolean): string {
    const nodes = data.nodes ?? [];
    const sources = data.sources ?? data.evidence_sources ?? [];
    const body = `
    <div class="grid">
      <div class="card stat"><div class="stat-value" style="color:#1677ff">${Array.isArray(nodes) ? nodes.length : 0}</div><div class="stat-label">${isZh ? '节点' : 'Nodes'}</div></div>
      <div class="card stat"><div class="stat-value" style="color:#52c41a">${Array.isArray(sources) ? sources.length : 0}</div><div class="stat-label">${isZh ? '证据来源' : 'Sources'}</div></div>
    </div>
    ${Array.isArray(sources) && sources.length > 0 ? `
    <div class="card"><h2>${isZh ? '证据来源' : 'Evidence sources'}</h2>
      ${sources.map((s: any) => `<div class="kv"><span class="kv-key">${this.esc(s.name || s.id || '')}</span><span class="kv-value">${this.esc(s.type || '')}</span></div>`).join('')}
    </div>` : ''}`;
    return this.baseLayout(isZh ? '证据图谱' : 'Evidence graph', filePath, isZh, body);
  }

  private static renderReview(data: any, filePath: string, isZh: boolean): string {
    const score = data.score ?? data.total_score ?? 0;
    const verdict = data.verdict ?? '';
    const dimensions = data.dimensions ?? {};
    const blocking = data.blocking_issues ?? [];
    const summary = data.summary ?? data.comment ?? '';
    const body = `
    <div class="grid">
      <div class="card stat"><div class="stat-value" style="color:${score >= 70 ? '#52c41a' : score >= 50 ? '#fa8c16' : '#ff4d4f'}">${this.esc(score)}</div><div class="stat-label">${isZh ? '评分' : 'Score'}</div></div>
      ${verdict ? `<div class="card stat"><div class="stat-value" style="color:#1677ff">${this.esc(verdict)}</div><div class="stat-label">${isZh ? '审阅结论' : 'Verdict'}</div></div>` : ''}
    </div>
    ${Object.keys(dimensions).length > 0 ? `
    <div class="card"><h2>${isZh ? '分项评分' : 'Dimension scores'}</h2>
      ${Object.entries(dimensions).map(([k, v]: [string, any]) => `
        <div style="margin-bottom:8px">
          <div class="kv"><span class="kv-key">${this.esc(k)}</span><span class="kv-value">${this.esc(v)}</span></div>
          <div class="dimension-bar"><div class="dimension-fill" style="width:${Math.min(100, Number(v) || 0)}%;background:${Number(v) >= 70 ? '#52c41a' : Number(v) >= 50 ? '#fa8c16' : '#ff4d4f'}"></div></div>
        </div>`).join('')}
    </div>` : ''}
    ${Array.isArray(blocking) && blocking.length > 0 ? `
    <div class="card"><h2 style="color:#ff4d4f">${isZh ? '阻塞问题' : 'Blocking issues'}</h2>
      ${blocking.map((b: any) => `<div class="list-item"><span class="tag tag-red">${isZh ? '阻塞' : 'Blocking'}</span> ${this.esc(b)}</div>`).join('')}
    </div>` : ''}
    ${summary ? `<div class="card"><h2>${isZh ? '总结' : 'Summary'}</h2><p>${this.esc(summary).replace(/\n/g,'<br>')}</p></div>` : ''}`;
    return this.baseLayout(isZh ? '审阅结果' : 'Review', filePath, isZh, body);
  }

  private static renderCompileRun(data: any, filePath: string, isZh: boolean): string {
    const success = data.success === true;
    const body = `
    <div class="card">
      <div class="grid">
        <div class="card stat"><div class="stat-value" style="color:${success ? '#52c41a' : '#ff4d4f'}">${success ? (isZh ? '✓ 成功' : '✓ Success') : (isZh ? '✗ 失败' : '✗ Failed')}</div><div class="stat-label">${isZh ? '状态' : 'Status'}</div></div>
        ${data.pdf_exists ? `<div class="card stat"><div class="stat-value" style="color:#1677ff">${isZh ? '有 PDF' : 'Has PDF'}</div><div class="stat-label">PDF</div></div>` : ''}
      </div>
    </div>`;
    return this.baseLayout(isZh ? '编译记录' : 'Compile run', filePath, isZh, body);
  }

  private static renderFigureArgMap(data: any, filePath: string, isZh: boolean): string {
    const entries = Array.isArray(data) ? data : Object.entries(data);
    const body = `
    <div class="card"><h2>${isZh ? '图表-主张映射' : 'Figure-claim map'} (${Array.isArray(entries) ? entries.length : Object.keys(data).length})</h2></div>
    ${(Array.isArray(entries) ? entries : Object.entries(data)).map(([k, v]: [string, any]) => `
      <div class="card">
        <div style="font-size:13px;font-weight:500;margin-bottom:4px">${this.esc(v?.figure_id || k)}</div>
        ${v?.roles ? `<div class="text-secondary">${this.esc(Array.isArray(v.roles) ? v.roles.join(', ') : String(v.roles))}</div>` : ''}
        ${v?.claim_ids ? `<div class="text-secondary">${isZh ? '关联主张' : 'Claims'}: ${this.esc(Array.isArray(v.claim_ids) ? v.claim_ids.join(', ') : String(v.claim_ids))}</div>` : ''}
      </div>`).join('')}`;
    return this.baseLayout(isZh ? '图表-主张映射' : 'Figure-claim map', filePath, isZh, body);
  }

  private static renderStoryline(data: any, filePath: string, isZh: boolean): string {
    const sections = data.section_logic ?? data.sections ?? [];
    const body = `
    <div class="card"><h2>${isZh ? '叙事线' : 'Storyline'} (${Array.isArray(sections) ? sections.length : 0} ${isZh ? '章节' : 'sections'})</h2></div>
    ${(Array.isArray(sections) ? sections : []).map((s: any) => `
      <div class="card">
        <div style="font-size:13px;font-weight:500;margin-bottom:4px">${this.esc(s.section || s.id || '')}</div>
        <div class="text-secondary">${this.esc(s.logic || s.description || '')}</div>
      </div>`).join('')}`;
    return this.baseLayout(isZh ? '叙事线' : 'Storyline', filePath, isZh, body);
  }

  private static renderHumanGates(data: any, filePath: string, isZh: boolean): string {
    const gates = Array.isArray(data) ? data : Object.entries(data).map(([k, v]) => ({ id: k, ...(v as any) }));
    const body = `
    <div class="card"><h2>${isZh ? '人工确认门' : 'Human gates'} (${gates.length})</h2></div>
    ${gates.map((g: any) => `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span class="tag ${g.status === 'resolved' || g.resolved ? 'tag-green' : 'tag-red'}">${this.esc(g.status || g.id || '')}</span>
          ${g.severity ? `<span class="tag tag-orange">${this.esc(g.severity)}</span>` : ''}
        </div>
        ${g.note ? `<div class="text-secondary">${this.esc(g.note)}</div>` : ''}
      </div>`).join('')}`;
    return this.baseLayout(isZh ? '人工确认门' : 'Human gates', filePath, isZh, body);
  }

  private static renderGenericJson(data: any, filePath: string, isZh: boolean): string {
    const pretty = JSON.stringify(data, null, 2);
    const body = `<pre class="mono"><code>${pretty.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</code></pre>`;
    return this.baseLayout(isZh ? 'JSON 查看' : 'JSON view', filePath, isZh, body);
  }

  private static errorHtml(error: string, filePath: string, isZh: boolean): string {
    return this.baseLayout(
      isZh ? '解析错误' : 'Parse Error',
      filePath,
      isZh,
      `<div class="error-box"><strong>${this.esc(error)}</strong></div>`
    );
  }
}
