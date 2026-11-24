/**
 * ReplayWebviewProvider - Simulation Replay Webview Provider
 *
 * Provides a webview for replaying and visualizing simulation data.
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，注册命令 'aiSocialScientist.openReplay'
 * - @extension/src/webview/replay/ - 前端React组件 (编译后为replay.js)
 *
 * 后端API：
 * - @packages/agentsociety2/agentsociety2/backend/routers/replay.py - /api/v1/replay/*
 */

import * as vscode from 'vscode';
import * as path from 'path';
import { getCurrentLanguageCode, localize, syncWebviewLanguage } from './i18n';
import { BackendAccessError, type BackendService } from './services/backendService';
import type {
  AgentProfile,
  ExperimentInfo,
  ExtensionMessage,
  InitData,
  ReplayDatasetRows,
  ReplayPanelSchema,
  ReplayStepBundle,
  TimelinePoint,
  WebviewMessage,
} from './webview/replay/types';

export class ReplayWebviewProvider {
  private readonly panel: vscode.WebviewPanel;
  private readonly extensionUri: vscode.Uri;
  private readonly workspacePath: string;
  private readonly hypothesisId: string;
  private readonly experimentId: string;
  private disposables: vscode.Disposable[] = [];
  private readonly requestControllers = new Map<string, AbortController>();
  private readonly requestVersions = new Map<string, number>();

  /**
   * Create and show a new replay webview panel
   */
  public static create(
    context: vscode.ExtensionContext,
    backend: BackendService,
    workspacePath: string,
    hypothesisId: string,
    experimentId: string
  ): ReplayWebviewProvider {
    const panel = vscode.window.createWebviewPanel(
      'aiSocialScientistReplay',
      localize('replay.panelTitle', experimentId),
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [context.extensionUri],
      }
    );

    return new ReplayWebviewProvider(
      panel,
      context,
      backend,
      workspacePath,
      hypothesisId,
      experimentId
    );
  }

  private constructor(
    panel: vscode.WebviewPanel,
    context: vscode.ExtensionContext,
    private readonly backend: BackendService,
    workspacePath: string,
    hypothesisId: string,
    experimentId: string
  ) {
    this.panel = panel;
    this.extensionUri = context.extensionUri;
    this.workspacePath = workspacePath;
    this.hypothesisId = hypothesisId;
    this.experimentId = experimentId;

    // Set webview content
    syncWebviewLanguage(this.panel, () => localize('replay.panelTitle', this.experimentId));
    this.panel.webview.html = this.getHtmlForWebview();

    // Register event listeners
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);

    this.panel.webview.onDidReceiveMessage(
      (message: WebviewMessage) => this.handleMessage(message),
      null,
      this.disposables
    );
  }

  /**
   * Handle messages from webview
   */
  private async handleMessage(message: WebviewMessage): Promise<void> {
    switch (message.command) {
      case 'ready':
        this.sendInitData();
        break;

      case 'fetchExperimentInfo':
        await this.fetchExperimentInfo();
        break;

      case 'fetchTimeline':
        await this.fetchTimeline();
        break;

      case 'fetchAgentProfiles':
        await this.fetchAgentProfiles();
        break;

      case 'fetchPanelSchema':
        await this.fetchPanelSchema();
        break;

      case 'fetchStepBundle':
        await this.fetchStepBundle(message.step);
        break;

      case 'fetchReplayDatasetRows':
        await this.fetchReplayDatasetRows(
          message.datasetId,
          message.requestKey,
          message.page,
          message.pageSize,
          {
            step: message.step,
            entityId: message.entityId,
            startStep: message.startStep,
            endStep: message.endStep,
            maxStep: message.maxStep,
            columns: message.columns,
            descOrder: message.descOrder,
            latestPerEntity: message.latestPerEntity,
          }
        );
        break;

      case 'error':
        vscode.window.showErrorMessage(`Replay error: ${message.message}`);
        break;
    }
  }

  /**
   * Send initialization data to webview
   */
  private sendInitData(): void {
    const initData: InitData = {
      workspacePath: this.workspacePath,
      hypothesisId: this.hypothesisId,
      experimentId: this.experimentId,
    };

    this.postMessage({ type: 'init', data: initData });
  }

  private buildReplayRoute(pathname: string, query: Record<string, string | number | boolean | undefined>): string {
    const params = new URLSearchParams({
      workspace_path: this.workspacePath,
    });
    Object.entries(query).forEach(([key, value]) => {
      if (value === undefined || value === null || value === '') {
        return;
      }
      params.set(key, String(value));
    });
    const hypothesis = encodeURIComponent(this.hypothesisId);
    const experiment = encodeURIComponent(this.experimentId);
    return `/api/v1/replay/${hypothesis}/${experiment}${pathname}?${params}`;
  }

  private startLatestRequest(group: string): { signal: AbortSignal; version: number } {
    this.requestControllers.get(group)?.abort();
    const controller = new AbortController();
    this.requestControllers.set(group, controller);
    const version = (this.requestVersions.get(group) ?? 0) + 1;
    this.requestVersions.set(group, version);
    return { signal: controller.signal, version };
  }

  private isLatestRequest(group: string, version: number): boolean {
    return this.requestVersions.get(group) === version;
  }

  private async fetchJson<T>(
    resource: string,
    route: string,
    options?: { latestGroup?: string }
  ): Promise<T | undefined> {
    const latestGroup = options?.latestGroup;
    const latestRequest = latestGroup ? this.startLatestRequest(latestGroup) : null;

    try {
      const data = await this.backend.requestJson<T>(route, { signal: latestRequest?.signal });
      if (latestGroup && latestRequest && !this.isLatestRequest(latestGroup, latestRequest.version)) {
        return undefined;
      }
      return data;
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        return undefined;
      }
      this.handleFetchError(resource, error);
      return undefined;
    }
  }

  /**
   * Fetch experiment info from backend
   */
  private async fetchExperimentInfo(): Promise<void> {
    const route = this.buildReplayRoute('/info', {});
    const data = await this.fetchJson<ExperimentInfo>('experiment info', route);
    if (data) {
      this.postMessage({ type: 'experimentInfo', data });
    }
  }

  /**
   * Fetch timeline from backend
   */
  private async fetchTimeline(): Promise<void> {
    const route = this.buildReplayRoute('/timeline', {});
    const data = await this.fetchJson<TimelinePoint[]>('timeline', route);
    if (data) {
      this.postMessage({ type: 'timeline', data });
    }
  }

  /**
   * Fetch agent profiles from backend
   */
  private async fetchAgentProfiles(): Promise<void> {
    const route = this.buildReplayRoute('/agents/profiles', {});
    const data = await this.fetchJson<AgentProfile[]>('agent profiles', route);
    if (data) {
      this.postMessage({ type: 'agentProfiles', data });
    }
  }

  private async fetchPanelSchema(): Promise<void> {
    const route = this.buildReplayRoute('/panel-schema', {});
    const data = await this.fetchJson<ReplayPanelSchema>('panel schema', route);
    if (data) {
      this.postMessage({ type: 'panelSchema', data });
    }
  }

  private async fetchStepBundle(step: number): Promise<void> {
    if (!Number.isSafeInteger(step)) {
      return;
    }
    const route = this.buildReplayRoute(`/steps/${step}/bundle`, {});
    const data = await this.fetchJson<ReplayStepBundle>('step bundle', route, { latestGroup: 'stepBundle' });
    if (data) {
      this.postMessage({ type: 'stepBundle', data });
    }
  }

  /**
   * Fetch replay dataset rows
   */
  private async fetchReplayDatasetRows(
    datasetId: string,
    requestKey?: string,
    page: number = 1,
    pageSize: number = 50,
    options?: {
      step?: number;
      entityId?: number;
      startStep?: number;
      endStep?: number;
      maxStep?: number;
      columns?: string[];
      descOrder?: boolean;
      latestPerEntity?: boolean;
    }
  ): Promise<void> {
    const route = this.buildReplayRoute(`/datasets/${encodeURIComponent(datasetId)}/rows`, {
      page,
      page_size: pageSize,
      step: options?.step,
      entity_id: options?.entityId,
      start_step: options?.startStep,
      end_step: options?.endStep,
      max_step: options?.maxStep,
      columns: options?.columns?.join(','),
      desc_order: options?.descOrder,
      latest_per_entity: options?.latestPerEntity,
    });
    const latestGroup = requestKey ? `replayDatasetRows:${requestKey}` : 'replayDatasetRows:default';
    const data = await this.fetchJson<ReplayDatasetRows>('replay dataset rows', route, { latestGroup });
    if (data) {
      this.postMessage({ type: 'replayDatasetRows', data, requestKey });
    }
  }

  /**
   * Handle fetch errors
   */
  private handleFetchError(resource: string, error: unknown): void {
    if (error instanceof BackendAccessError) {
      this.postMessage({ type: 'error', message: error.message });
      return;
    }
    const message = `Failed to fetch ${resource}: ${error instanceof Error ? error.message : 'Unknown error'}`;
    console.error(message);
    this.postMessage({ type: 'error', message });
  }

  /**
   * Post message to webview
   */
  private postMessage(message: ExtensionMessage): void {
    this.panel.webview.postMessage(message);
  }

  /**
   * Generate HTML for webview
   */
  private getHtmlForWebview(): string {
    const scriptUri = this.panel.webview.asWebviewUri(
      vscode.Uri.file(path.join(this.extensionUri.fsPath, 'out', 'webview', 'replay.js'))
    );

    const csp = [
      "default-src 'none'",
      `img-src ${this.panel.webview.cspSource} https://*.mapbox.com https://*.tiles.mapbox.com data: blob:`,
      `style-src ${this.panel.webview.cspSource} 'unsafe-inline' https://api.mapbox.com`,
      `script-src ${this.panel.webview.cspSource}`,
      `connect-src ${this.panel.webview.cspSource} https://*.mapbox.com https://*.tiles.mapbox.com data: blob:`,
      `worker-src ${this.panel.webview.cspSource} blob:`,
      `font-src ${this.panel.webview.cspSource} https://api.mapbox.com https://*.mapbox.com data:`,
    ].join('; ');

    return `<!DOCTYPE html>
<html lang="${getCurrentLanguageCode()}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="${csp}">
    <title>Simulation Replay</title>
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
            height: 100vh;
            overflow: hidden;
            --as-border: var(--vscode-panel-border);
            --as-muted-text: var(--vscode-descriptionForeground);
            --as-strong-text: var(--vscode-editor-foreground);
            --as-accent-text: var(--vscode-textLink-foreground);
            --as-selection-bg: var(--vscode-list-activeSelectionBackground);
            --as-tooltip-bg: rgba(0, 0, 0, 0.8);
            --as-tooltip-fg: #ffffff;
            --as-panel-bg: rgba(255, 255, 255, 0.72);
            --as-panel-bg-strong: rgba(255, 255, 255, 0.92);
            --as-panel-card-bg: rgba(255, 255, 255, 0.78);
            --as-panel-chip-bg: rgba(255, 255, 255, 0.82);
            --as-panel-muted-bg: rgba(0, 0, 0, 0.04);
            --as-panel-muted-bg-strong: rgba(0, 0, 0, 0.08);
            --as-accent-soft-bg: rgba(22, 119, 255, 0.12);
            --as-accent-soft-bg-strong: rgba(22, 119, 255, 0.18);
            --as-shadow: 0 4px 12px rgba(0, 0, 0, 0.16);
            --as-reflection-border: var(--vscode-terminal-ansiMagenta, #9b59b6);
        }

        body.vscode-dark,
        body.vscode-high-contrast {
            --as-tooltip-bg: rgba(18, 18, 18, 0.92);
            --as-panel-bg: rgba(37, 37, 38, 0.78);
            --as-panel-bg-strong: rgba(37, 37, 38, 0.94);
            --as-panel-card-bg: rgba(37, 37, 38, 0.84);
            --as-panel-chip-bg: rgba(37, 37, 38, 0.92);
            --as-panel-muted-bg: rgba(255, 255, 255, 0.06);
            --as-panel-muted-bg-strong: rgba(255, 255, 255, 0.12);
            --as-accent-soft-bg: rgba(22, 119, 255, 0.16);
            --as-accent-soft-bg-strong: rgba(22, 119, 255, 0.24);
            --as-shadow: 0 4px 14px rgba(0, 0, 0, 0.3);
        }

        #root {
            height: 100%;
            width: 100%;
            display: flex;
            flex-direction: column;
        }

        /* Loading state */
        .loading-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            gap: 16px;
        }

        .loading-spinner {
            width: 40px;
            height: 40px;
            border: 3px solid var(--vscode-editor-foreground);
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to {
                transform: rotate(360deg);
            }
        }

        /* Main layout */
        .replay-container {
            position: relative;
            height: 100%;
            width: 100%;
        }

        :root {
            --replay-header: 0px;
            --replay-top: 20px;
            --panel-width: clamp(260px, 21vw, 360px);
            --timeline-width: clamp(360px, 52vw, 860px);
        }

        .deck {
            position: absolute;
            top: var(--replay-header);
            left: 0;
            width: 100%;
            height: calc(100% - var(--replay-header));
            z-index: 0;
        }

        .deck > div,
        .deck canvas,
        .deck .mapboxgl-canvas,
        .deck .mapboxgl-map {
            width: 100% !important;
            height: 100% !important;
        }

        .agentsociety-left {
            position: absolute;
            top: calc(var(--replay-header) + var(--replay-top));
            left: 0;
            z-index: 1;
        }

        .agentsociety-right {
            position: absolute;
            top: calc(var(--replay-header) + var(--replay-top));
            right: 0;
            z-index: 1;
            overflow: hidden;
            width: var(--panel-width);
        }

        .left-inner {
            background: var(--as-panel-bg);
            border: 1px solid var(--as-border);
            box-shadow: var(--as-shadow);
            border-radius: 0 8px 8px 0;
            margin: 8px 0;
            padding: 12px 16px;
            width: var(--panel-width);
            height: calc(100vh - var(--replay-header) - 60px);
            overflow: auto;
            backdrop-filter: blur(40px);
            transition: transform 0.3s ease-in-out;
        }

        .left-inner.collapsed {
            transform: translateX(-100%);
        }

        .left-title {
            display: flex;
            align-items: center;
            gap: 6px;
            font-weight: 600;
            margin: 8px 0 12px;
        }

        .left-title-icon {
            font-size: 16px;
        }

        .left-section-title {
            font-weight: 600;
            margin: 12px 0 6px;
        }

        .left-info-block,
        .left-info-block-status {
            min-width: 47%;
            margin: 4px 0;
            padding: 8px;
            border-radius: 4px;
            align-items: center;
            background: var(--as-accent-soft-bg);
            display: flex;
            justify-content: space-between;
        }

        .left-info-block-status {
            line-height: 1.4;
            display: block;
        }

        .left-info-block:hover,
        .left-info-block-status:hover {
            background: var(--as-accent-soft-bg-strong);
            cursor: pointer;
            transition: background 0.3s;
        }

        .left-info-history-card {
            border-radius: 8px;
            background-color: var(--as-panel-muted-bg);
            margin: 8px 0;
            width: 100%;
        }

        .left-info-history-inner {
            padding: 8px;
        }

        .left-info-empty {
            padding: 12px 8px;
            color: var(--as-muted-text);
        }

        .left-label {
            color: var(--as-muted-text);
            margin-right: 4px;
        }

        .left-value {
            color: var(--as-strong-text);
        }

        .right-inner {
            background: var(--as-panel-bg);
            border: 1px solid var(--as-border);
            box-shadow: var(--as-shadow);
            border-radius: 8px 0 0 8px;
            margin: 8px 0;
            width: var(--panel-width);
            height: calc(100vh - var(--replay-header) - 60px);
            display: flex;
            flex-direction: column;
            backdrop-filter: blur(40px);
            transition: transform 0.3s ease-in-out;
        }

        .right-inner.collapsed {
            transform: translateX(100%);
        }

        .tabs {
            display: flex;
            gap: 6px;
            padding: 12px 8px 8px;
            flex-wrap: wrap;
        }

        .tab-item {
            border: none;
            padding: 6px 10px;
            border-radius: 16px;
            background: var(--as-panel-chip-bg);
            cursor: pointer;
            font-size: 12px;
        }

        .tab-item.active {
            background: var(--as-accent-soft-bg-strong);
            color: var(--as-accent-text);
            font-weight: 600;
        }

        .right-content {
            flex: 1;
            overflow: auto;
            padding: 0 12px 12px;
        }

        .right-section-title {
            font-weight: 600;
            margin: 12px 0 6px;
        }

        .right-card,
        .right-info-card {
            background: var(--as-panel-card-bg);
            border-radius: 8px;
            padding: 8px 10px;
            margin-bottom: 8px;
            line-height: 1.4;
        }

        .right-card-meta {
            font-size: 11px;
            color: var(--as-muted-text);
            margin-bottom: 4px;
        }

        .right-card-content {
            font-size: 13px;
        }

        .right-empty {
            color: var(--as-muted-text);
            padding: 8px 0;
        }

        .network-graph {
            width: 100%;
            margin-bottom: 8px;
        }

        .control-progress {
            position: absolute;
            background: var(--as-panel-bg-strong);
            border: 1px solid var(--as-border);
            box-shadow: var(--as-shadow);
            border-radius: 28px;
            bottom: 32px;
            left: calc(50% - (var(--timeline-width) * 0.5));
            width: var(--timeline-width);
            height: 56px;
            z-index: 10;
            display: flex;
            align-items: center;
            padding: 0 12px;
            gap: 12px;
        }

        /* Dialog list */
        .dialog-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .dialog-item {
            padding: 8px 12px;
            border-radius: 6px;
            background: var(--vscode-editor-inactiveSelectionBackground);
        }

        .dialog-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 4px;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
        }

        .dialog-content {
            font-size: 13px;
            line-height: 1.4;
        }

        /* V2 only uses 反思 (thought/reflection) */
        .dialog-type-thought {
            border-left: 3px solid var(--as-reflection-border);
        }

        /* Timeline player */
        .timeline-player {
            display: flex;
            align-items: center;
            gap: 12px;
            width: 100%;
        }

        .status {
            border-radius: 16px;
            background: var(--as-panel-muted-bg-strong);
            height: 32px;
            padding: 0 12px;
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 12px;
            white-space: nowrap;
        }

        .player {
            border-radius: 16px;
            background: var(--as-panel-muted-bg-strong);
            height: 32px;
            padding: 0 12px;
            display: flex;
            align-items: center;
            gap: 8px;
            flex: 1;
        }

        .player-controls {
            display: flex;
            align-items: center;
            gap: 8px;
            flex: 1;
        }

        .timeline-btn {
            width: 28px;
            height: 28px;
            border: none;
            border-radius: 6px;
            background: var(--as-panel-chip-bg);
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
        }

        .timeline-btn:hover {
            background: var(--as-accent-soft-bg-strong);
        }

        .timeline-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .timeline-slider {
            flex: 1;
            height: 4px;
            -webkit-appearance: none;
            background: var(--as-accent-soft-bg-strong);
            border-radius: 2px;
            outline: none;
        }

        .timeline-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: var(--as-accent-text);
            cursor: pointer;
        }

        .speed-selector {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 11px;
            white-space: nowrap;
        }

        .speed-selector select {
            background: var(--as-panel-chip-bg);
            border: 1px solid var(--as-border);
            border-radius: 16px;
            padding: 2px 8px;
            font-size: 11px;
        }

        .circle-wrap select {
            border-radius: 16px;
        }

        /* Map placeholder */
        .map-placeholder {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--vscode-descriptionForeground);
            gap: 8px;
        }

        .map-placeholder-icon {
            font-size: 48px;
            opacity: 0.5;
        }

        /* Ant Design Tabs overrides - Two row aligned layout */
        .right-inner .ant-tabs {
            width: 100% !important;
        }

        .right-inner .ant-tabs-nav {
            margin: 0 !important;
            padding: 8px 8px 4px !important;
        }

        .right-inner .ant-tabs-nav-list {
            display: grid !important;
            grid-template-columns: repeat(3, 1fr) !important;
            gap: 6px !important;
            width: 100% !important;
            flex-wrap: wrap !important;
        }

        .right-inner .ant-tabs-nav-wrap {
            overflow: visible !important;
            flex: 1 !important;
        }

        .right-inner .ant-tabs-ink-bar {
            display: none !important;
        }

        .right-inner .ant-tabs-content {
            padding: 0 8px 8px;
            overflow: auto;
            height: calc(100vh - var(--replay-header) - 140px);
        }

        .right-inner .ant-tabs-tab {
            padding: 6px 4px !important;
            margin: 0 !important;
            border-radius: 14px !important;
            background: var(--as-panel-muted-bg) !important;
            font-size: 12px !important;
            border: none !important;
            transition: all 0.2s;
            justify-content: center !important;
            text-align: center !important;
        }

        .right-inner .ant-tabs-tab:hover {
            background: var(--as-accent-soft-bg) !important;
        }

        .right-inner .ant-tabs-tab-active {
            background: var(--as-accent-soft-bg-strong) !important;
        }

        .right-inner .ant-tabs-tab-active .ant-tabs-tab-btn {
            color: var(--as-accent-text) !important;
        }

        /* Bubble list styles */
        .bubble-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
            padding: 8px;
            overflow: auto;
            height: calc(100vh - var(--replay-header) - 180px);
        }

        .bubble-item {
            display: flex;
            gap: 8px;
            align-items: flex-start;
        }

        .bubble-item.bubble-left {
            flex-direction: row;
        }

        .bubble-item.bubble-right {
            flex-direction: row-reverse;
        }

        .bubble-content {
            max-width: 80%;
            background: var(--as-panel-bg-strong);
            border-radius: 8px;
            padding: 8px 12px;
            box-shadow: var(--as-shadow);
        }

        .bubble-header {
            font-size: 11px;
            color: var(--as-muted-text);
            margin-bottom: 4px;
        }

        .bubble-text {
            font-size: 13px;
            line-height: 1.4;
            color: var(--as-strong-text);
            word-wrap: break-word;
        }
    </style>
</head>
<body>
    <div id="root"></div>
    <script src="${scriptUri}"></script>
</body>
</html>`;
  }

  /**
   * Dispose the webview panel and resources
   */
  public dispose(): void {
    this.requestControllers.forEach((controller) => controller.abort());
    this.requestControllers.clear();
    this.requestVersions.clear();
    this.disposables.forEach((d) => d.dispose());
    this.disposables = [];
  }
}
