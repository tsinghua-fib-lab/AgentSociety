import * as http from 'http';
import type { ClientRequest, IncomingMessage, ServerResponse } from 'http';
import * as https from 'https';
import { URL } from 'url';
import { findAvailablePortFrom } from '../portUtils';
import {
  inferOpenAiApiFormat,
  isCodexResponsesPath,
  resolveChatCompletionsTargetUrl,
} from './codexApiFormat';
import { resolveCodexChatModel } from './codexModelMapping';
import {
  CodexChatStreamTranslator,
  formatResponsesSseEvent,
  translateChatCompletionToResponses,
  translateResponsesRequestToChat,
} from './codexResponsesBridge';
import { readCodexModelCatalogDocument } from './codexModelCatalog';
import {
  buildLocalGatewayBaseUrl,
  resolveUpstreamTargetUrl,
  upstreamTargetsLocalGateway,
  type AiCliGatewayUpstream,
} from './aiCliGatewayUpstream';
import { applyUpstreamAuthHeaders } from '../aiCli/upstreamAuthHeaders';
import { applyAnthropicModelMapping } from './anthropicModelMapping';
import { buildAnthropicGatewayModelsResponse } from './anthropicGatewayModels';
import {
  OpenAiChatToAnthropicStreamTranslator,
  translateAnthropicMessagesToOpenAiChat,
  translateOpenAiChatToAnthropicMessage,
} from './anthropicOpenAiBridge';
import {
  AnthropicMessagesToResponsesStreamTranslator,
  formatResponsesSseEvent as formatAnthropicResponsesSseEvent,
  translateAnthropicMessageToResponses,
  translateResponsesRequestToAnthropicMessages,
} from './responsesAnthropicBridge';
import {
  buildFailoverUpstreamOrder,
  FAILOVER_MAX_ATTEMPTS,
  isCircuitOpen,
  recordUpstreamFailure,
  recordUpstreamSuccess,
  shouldFailoverHttpStatus,
  upstreamHealth,
  type CircuitBreakerHealth,
  type CircuitBreakerState,
} from './gatewayFailover';
import {
  applyPreflightRectifiers,
  applyRectifierRetryFix,
  classifyRectifierRetry,
  DEFAULT_GATEWAY_RECTIFIER_SETTINGS,
  rectifierFixChanged,
  type GatewayRectifierSettings,
  type RectifierRetryKind,
} from './gatewayRequestRectifier';
import {
  applyBedrockRequestOptimizer,
  DEFAULT_GATEWAY_OPTIMIZER_SETTINGS,
  type GatewayOptimizerSettings,
} from './bedrockRequestOptimizer';
import { createOutboundProxyAgent, type OutboundProxyConfig } from './gatewayOutboundProxy';
import { GatewayRuntimeStatsTracker, type GatewayRuntimeStats } from './gatewayRuntimeStats';
import {
  extractTokenUsage,
  extractModelFromRequest,
  extractRequestId,
  parseSseMessages,
  tokenUsageFromAnthropicUsageObject,
  type TokenUsageRecord,
  type UsageListener,
  type UsageRecordContext,
} from './gatewayUsageTracker';

const DEFAULT_GATEWAY_PORT_START = 15721;
const DEFAULT_GATEWAY_PORT_END = 15820;
const MAX_BODY_BYTES = 64 * 1024 * 1024;
const DEFAULT_UPSTREAM_IDLE_TIMEOUT_MS = 5 * 60 * 1000;

export type AiCliGatewayStatus = {
  running: boolean;
  port?: number;
  baseUrl?: string;
  upstreamBaseUrl?: string;
  error?: string;
  stats?: GatewayRuntimeStats;
  failoverHealth?: Record<string, CircuitBreakerHealth>;
};

export type GatewayLogEntry = {
  ts: string;
  method: string;
  path: string;
  upstream: string;
  status: number;
  ms: number;
  model?: string;
  inputTokens?: number;
  outputTokens?: number;
  failoverFrom?: string;
};

export type AiCliGatewayLogListener = (entry: GatewayLogEntry) => void;
export type AiCliGatewayFailoverRole = 'claude' | 'codex';

export type AiCliGatewayFailoverListener = (
  upstream: AiCliGatewayUpstream,
  role: AiCliGatewayFailoverRole
) => void;

export type AiCliGatewayFailoverConfig = {
  anthropicUpstreams: AiCliGatewayUpstream[];
  openaiUpstreams: AiCliGatewayUpstream[];
  enabled: boolean;
};

type ProxyAttemptResult = {
  ok: boolean;
  status: number;
  canRetry: boolean;
  detail?: string;
};

function summarizeUpstreamErrorBody(body: Buffer, status: number): string {
  if (body.length === 0) {
    return `upstream HTTP ${status}`;
  }
  const text = body.toString('utf-8').trim();
  if (text.length > 500) {
    return `${text.slice(0, 500)}…`;
  }
  return text;
}

function normalizeGatewayErrorPayload(status: number, payload: unknown): Record<string, unknown> {
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    const obj = payload as Record<string, unknown>;
    if (obj.error && typeof obj.error === 'object' && !Array.isArray(obj.error)) {
      const nested = obj.error as Record<string, unknown>;
      if (typeof nested.message === 'string' && nested.message.trim()) {
        const out: Record<string, unknown> = {
          error: {
            message: nested.message,
            type:
              typeof nested.type === 'string' && nested.type.trim()
                ? nested.type
                : 'agentsociety_gateway_error',
            code:
              typeof nested.code === 'string' && nested.code.trim()
                ? nested.code
                : typeof obj.error === 'string'
                  ? obj.error
                  : 'gateway_error',
          },
        };
        if (typeof nested.hint === 'string' && nested.hint.trim()) {
          (out.error as Record<string, unknown>).hint = nested.hint;
        } else if (typeof obj.hint === 'string' && obj.hint.trim()) {
          (out.error as Record<string, unknown>).hint = obj.hint;
        }
        return out;
      }
    }
    const code = typeof obj.error === 'string' ? obj.error : 'gateway_error';
    const message =
      typeof obj.message === 'string' && obj.message.trim()
        ? obj.message
        : typeof obj.error === 'string'
          ? obj.error
          : `HTTP ${status}`;
    const out: Record<string, unknown> = {
      error: {
        message,
        type: 'agentsociety_gateway_error',
        code,
      },
    };
    if (typeof obj.hint === 'string' && obj.hint.trim()) {
      (out.error as Record<string, unknown>).hint = obj.hint;
    }
    return out;
  }
  return {
    error: {
      message: typeof payload === 'string' && payload.trim() ? payload : `HTTP ${status}`,
      type: 'agentsociety_gateway_error',
      code: 'gateway_error',
    },
  };
}

function inferUsageApp(urlPath: string, model: string): 'claude' | 'codex' {
  if (urlPath.includes('/responses') || urlPath.includes('/chat/completions')) {
    return 'codex';
  }
  if (urlPath.includes('/messages') || model.toLowerCase().includes('claude')) {
    return 'claude';
  }
  return 'codex';
}

export function shouldRecordGatewayRequest(method: string, urlPath: string): boolean {
  const path = urlPath.split('?')[0];
  if (path.includes('/health') || path === '/v1/usage' || path === '/usage') {
    return false;
  }
  if (method === 'GET' && path.includes('/models')) {
    return false;
  }
  if (
    method === 'POST' &&
    (path.includes('/messages') ||
      path.includes('/responses') ||
      path.includes('/chat/completions'))
  ) {
    return true;
  }
  return false;
}

export function normalizeGatewayRequestPath(urlPath: string): string {
  const anthropicPrefix = '/api/anthropic';
  if (urlPath === anthropicPrefix) {
    return '/';
  }
  if (urlPath.startsWith(`${anthropicPrefix}/`)) {
    return urlPath.slice(anthropicPrefix.length);
  }
  return urlPath;
}

function readRequestBody(req: IncomingMessage): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    req.on('data', (chunk: Buffer) => {
      total += chunk.length;
      if (total > MAX_BODY_BYTES) {
        reject(new Error('request_body_too_large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

function isAnthropicMessagesPath(urlPath: string): boolean {
  return urlPath.includes('/messages') && !urlPath.includes('/responses');
}

function applyAnthropicRequestMapping(
  upstream: AiCliGatewayUpstream,
  urlPath: string,
  body: Buffer,
  rectifier: GatewayRectifierSettings = DEFAULT_GATEWAY_RECTIFIER_SETTINGS,
  optimizer: GatewayOptimizerSettings = DEFAULT_GATEWAY_OPTIMIZER_SETTINGS
): { body: Buffer; model: string } {
  if (!isAnthropicMessagesPath(urlPath) || body.length === 0) {
    return { body, model: '' };
  }
  try {
    const parsed = JSON.parse(body.toString('utf-8')) as Record<string, unknown>;
    const mapped = applyAnthropicModelMapping(parsed, upstream);
    const model =
      mapped.mappedModel ??
      mapped.originalModel ??
      extractModelFromRequest(parsed);
    let next = applyPreflightRectifiers(mapped.body, rectifier, model);
    next = applyBedrockRequestOptimizer(next, optimizer, upstream.baseUrl);
    if (!mapped.mappedModel && next === mapped.body) {
      return { body, model };
    }
    return { body: Buffer.from(JSON.stringify(next), 'utf-8'), model };
  } catch {
    return { body, model: '' };
  }
}

function filterForwardHeaders(
  headers: IncomingMessage['headers'],
  upstreamHost: string
): Record<string, string> {
  const out: Record<string, string> = {};
  const skip = new Set([
    'host',
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailer',
    'transfer-encoding',
    'upgrade',
  ]);
  for (const [key, value] of Object.entries(headers)) {
    if (!value || skip.has(key.toLowerCase())) {
      continue;
    }
    out[key] = Array.isArray(value) ? value.join(', ') : value;
  }
  out.host = upstreamHost;
  return out;
}

const HOP_BY_HOP_RESPONSE_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

export function filterProxyResponseHeaders(
  headers: IncomingMessage['headers']
): Record<string, string | string[]> {
  const connectionTokens = new Set(
    String(headers.connection ?? '')
      .split(',')
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean)
  );
  const out: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(headers)) {
    const normalized = key.toLowerCase();
    if (
      value === undefined ||
      HOP_BY_HOP_RESPONSE_HEADERS.has(normalized) ||
      connectionTokens.has(normalized)
    ) {
      continue;
    }
    out[key] = value;
  }
  return out;
}

function reportedCostFromHeaders(headers: IncomingMessage['headers']): number | undefined {
  const raw = headers['x-litellm-response-cost'];
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== 'string' || value.trim() === '') {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function applyUpstreamAuth(
  headers: Record<string, string>,
  apiKey: string,
  upstreamBaseUrl: string,
  authHeaderMode?: AiCliGatewayUpstream['authHeaderMode']
): void {
  applyUpstreamAuthHeaders(headers, apiKey, {
    upstreamBaseUrl,
    mode: authHeaderMode,
  });
}

/**
 * Local HTTP proxy server that intercepts Claude Code / Codex API requests
 * and forwards them to configured upstream providers with format translation.
 *
 * ## Architecture
 *
 * The gateway runs on `127.0.0.1:{port}` and handles two primary request paths:
 *
 * - **Anthropic Messages** (`/v1/messages`): May be forwarded directly
 *   (passthrough) or translated to OpenAI Chat if the upstream provider
 *   has `codexApiFormat` set.
 * - **OpenAI Responses** (`/v1/responses`): May be forwarded directly or
 *   translated to OpenAI Chat via the Codex bridge.
 *
 * ## Format Translation
 *
 * When the upstream provider's API format differs from the client's request
 * format, the gateway uses bridges:
 *
 * - `proxyAnthropicMessagesViaOpenAiChat()` — Anthropic Messages → OpenAI Chat
 * - `proxyCodexResponsesViaChat()` — OpenAI Responses → OpenAI Chat
 *
 * ## Failover
 *
 * When `failoverEnabled` is true, the gateway tries upstream providers in
 * priority order. Circuit breakers prevent hammering failed providers.
 * Successful failover updates the active provider.
 *
 * @see AiCliGatewayManager for provider lifecycle management
 * @see anthropicOpenAiBridge for Anthropic↔OpenAI format translation
 * @see codexResponsesBridge for Codex Responses↔Chat format translation
 */
export class AiCliGateway {
  private server: http.Server | null = null;
  private port: number | null = null;
  /** Active upstream for Anthropic/Claude routes. */
  private upstream: AiCliGatewayUpstream | null = null;
  /** Active upstream for OpenAI/Codex routes. */
  private openaiUpstream: AiCliGatewayUpstream | null = null;
  /** All Anthropic-format upstreams (active + failover candidates). */
  private upstreams: AiCliGatewayUpstream[] = [];
  /** All OpenAI-format upstreams (active + failover candidates). */
  private openaiUpstreams: AiCliGatewayUpstream[] = [];
  private failoverEnabled = false;
  private readonly circuit = new Map<string, CircuitBreakerState>();
  private lastError: string | undefined;
  private logListener: AiCliGatewayLogListener | null = null;
  private usageListener: UsageListener | null = null;
  private failoverListener: AiCliGatewayFailoverListener | null = null;
  private readonly statsTracker = new GatewayRuntimeStatsTracker();
  private outboundProxy: OutboundProxyConfig | null = null;
  private outboundProxyAgent: ReturnType<typeof createOutboundProxyAgent>;
  private outboundProxyKey = '';
  private directHttpAgent: http.Agent | undefined;
  private directHttpsAgent: https.Agent | undefined;
  private rectifier: GatewayRectifierSettings = { ...DEFAULT_GATEWAY_RECTIFIER_SETTINGS };
  private optimizer: GatewayOptimizerSettings = { ...DEFAULT_GATEWAY_OPTIMIZER_SETTINGS };
  private readonly rectifierRetriedKinds = new WeakMap<IncomingMessage, Set<RectifierRetryKind>>();

  constructor(
    private readonly upstreamIdleTimeoutMs = DEFAULT_UPSTREAM_IDLE_TIMEOUT_MS
  ) {}

  onLog(listener: AiCliGatewayLogListener | null): void {
    this.logListener = listener;
  }

  onUsage(listener: UsageListener | null): void {
    this.usageListener = listener;
  }

  onFailover(listener: AiCliGatewayFailoverListener | null): void {
    this.failoverListener = listener;
  }

  configureOutboundProxy(proxy: OutboundProxyConfig | null): void {
    const normalized = proxy?.url.trim()
      ? { ...proxy, url: proxy.url.trim() }
      : null;
    const key = normalized
      ? JSON.stringify([normalized.url, normalized.username ?? '', normalized.password ?? ''])
      : '';
    if (key === this.outboundProxyKey) {
      return;
    }
    this.outboundProxyAgent?.destroy();
    this.outboundProxyAgent = undefined;
    this.outboundProxy = normalized;
    this.outboundProxyKey = key;
  }

  configureRectifier(settings: Partial<GatewayRectifierSettings> | null): void {
    this.rectifier = {
      ...DEFAULT_GATEWAY_RECTIFIER_SETTINGS,
      ...(settings ?? {}),
    };
  }

  getRectifierSettings(): GatewayRectifierSettings {
    return { ...this.rectifier };
  }

  configureOptimizer(settings: Partial<GatewayOptimizerSettings> | null): void {
    this.optimizer = {
      ...DEFAULT_GATEWAY_OPTIMIZER_SETTINGS,
      ...(settings ?? {}),
    };
  }

  getOptimizerSettings(): GatewayOptimizerSettings {
    return { ...this.optimizer };
  }

  private rectifierKindsFor(req: IncomingMessage): Set<RectifierRetryKind> {
    let kinds = this.rectifierRetriedKinds.get(req);
    if (!kinds) {
      kinds = new Set();
      this.rectifierRetriedKinds.set(req, kinds);
    }
    return kinds;
  }

  private outboundAgent(protocol: string): http.Agent | undefined {
    if (this.outboundProxy) {
      this.outboundProxyAgent ??= createOutboundProxyAgent(this.outboundProxy);
      return this.outboundProxyAgent;
    }
    if (protocol === 'https:') {
      this.directHttpsAgent ??= new https.Agent({ keepAlive: true });
      return this.directHttpsAgent;
    }
    if (protocol === 'http:') {
      this.directHttpAgent ??= new http.Agent({ keepAlive: true });
      return this.directHttpAgent;
    }
    return undefined;
  }

  private bindProxyRequestLifecycle(
    proxyReq: ClientRequest,
    clientReq: IncomingMessage,
    clientRes: ServerResponse
  ): void {
    proxyReq.setTimeout(this.upstreamIdleTimeoutMs, () => {
      proxyReq.destroy(new Error('upstream_idle_timeout'));
    });
    const abortUpstream = () => {
      if (!clientRes.writableEnded && !proxyReq.destroyed) {
        proxyReq.destroy(new Error('client_disconnected'));
      }
    };
    clientReq.once('aborted', abortUpstream);
    clientRes.once('close', abortUpstream);
    proxyReq.once('close', () => {
      clientReq.off('aborted', abortUpstream);
      clientRes.off('close', abortUpstream);
    });
  }

  private proxyRequestErrorResult(
    err: Error,
    clientReq: IncomingMessage,
    clientRes: ServerResponse
  ): ProxyAttemptResult {
    if (
      err.message === 'client_disconnected' ||
      clientReq.aborted ||
      clientRes.destroyed
    ) {
      return { ok: false, status: 499, canRetry: false, detail: 'client_disconnected' };
    }
    this.lastError = err.message;
    if (err.message === 'upstream_idle_timeout') {
      return { ok: false, status: 504, canRetry: true, detail: err.message };
    }
    return clientRes.headersSent
      ? { ok: false, status: 502, canRetry: false, detail: err.message }
      : { ok: false, status: 0, canRetry: true, detail: err.message };
  }

  private normalizeCodexUpstream(upstream: AiCliGatewayUpstream): AiCliGatewayUpstream {
    const baseUrl = upstream.baseUrl.trim();
    const explicitFormat = upstream.codexApiFormat;
    return {
      ...upstream,
      baseUrl,
      apiKey: upstream.apiKey.trim(),
      codexApiFormat:
        explicitFormat ??
        (upstream.apiKind === 'openai' ? inferOpenAiApiFormat(baseUrl) : undefined),
      codexModel: upstream.codexModel?.trim(),
    };
  }

  private assertNotSelfForwarding(upstream: AiCliGatewayUpstream): void {
    if (this.port && upstreamTargetsLocalGateway(upstream.baseUrl, this.port)) {
      throw new Error('gateway_upstream_points_to_itself');
    }
  }

  setOpenaiUpstream(upstream: AiCliGatewayUpstream | null): void {
    if (upstream?.baseUrl.trim() && upstream.apiKey.trim()) {
      const normalized = this.normalizeCodexUpstream(upstream);
      this.assertNotSelfForwarding(normalized);
      this.openaiUpstream = normalized;
    } else {
      this.openaiUpstream = null;
    }
  }

  configureFailover(config: AiCliGatewayFailoverConfig): void {
    const anthropicUpstreams = config.anthropicUpstreams
      .filter((u) => u.baseUrl.trim() && u.apiKey.trim())
      .map((u) => ({
        ...u,
        baseUrl: u.baseUrl.trim(),
        apiKey: u.apiKey.trim(),
      }));
    const openaiUpstreams = config.openaiUpstreams
      .filter((u) => u.baseUrl.trim() && u.apiKey.trim())
      .map((u) => this.normalizeCodexUpstream(u));
    for (const upstream of [...anthropicUpstreams, ...openaiUpstreams]) {
      this.assertNotSelfForwarding(upstream);
    }
    this.upstreams = anthropicUpstreams;
    this.openaiUpstreams = openaiUpstreams;
    this.failoverEnabled = config.enabled;
    if (this.upstreams.length > 0) {
      this.upstream = this.upstreams[0];
    }
    this.openaiUpstream = this.openaiUpstreams[0] ?? null;
  }

  private isFailoverActiveForPath(urlPath: string): boolean {
    if (!this.failoverEnabled) {
      return false;
    }
    if (this.pathNeedsOpenAiUpstream(urlPath)) {
      return this.openaiUpstreams.length > 1;
    }
    return this.upstreams.length > 1;
  }

  private pathNeedsOpenAiUpstream(urlPath: string): boolean {
    return (
      isCodexResponsesPath(urlPath) ||
      urlPath.includes('/chat/completions') ||
      urlPath.includes('/completions')
    );
  }

  private pickUpstreamForPath(urlPath: string): AiCliGatewayUpstream | null {
    if (!this.upstream) {
      return null;
    }
    if (this.pathNeedsOpenAiUpstream(urlPath)) {
      return this.openaiUpstream;
    }
    return this.upstream;
  }

  private orderedUpstreamsForPath(urlPath: string): AiCliGatewayUpstream[] {
    const primary = this.pickUpstreamForPath(urlPath);
    if (!primary) {
      return [];
    }
    const list = this.pathNeedsOpenAiUpstream(urlPath)
      ? this.openaiUpstreams.length > 0
        ? this.openaiUpstreams
        : [primary]
      : this.upstreams.length > 0
        ? this.upstreams
        : [primary];
    return buildFailoverUpstreamOrder(list, primary.baseUrl);
  }

  private failoverRoleForPath(urlPath: string): AiCliGatewayFailoverRole {
    return this.pathNeedsOpenAiUpstream(urlPath) ? 'codex' : 'claude';
  }

  private commitFailoverUpstream(urlPath: string, upstream: AiCliGatewayUpstream): void {
    const role = this.failoverRoleForPath(urlPath);
    if (role === 'codex') {
      this.openaiUpstream = this.normalizeCodexUpstream(upstream);
      this.failoverListener?.(this.openaiUpstream, role);
    } else {
      this.upstream = { ...upstream, baseUrl: upstream.baseUrl.trim(), apiKey: upstream.apiKey.trim() };
      this.failoverListener?.(this.upstream, role);
    }
  }

  getStatus(): AiCliGatewayStatus {
    if (!this.server || !this.port) {
      return { running: false, error: this.lastError };
    }
    const failoverHealth: Record<string, CircuitBreakerHealth> = {};
    for (const [baseUrl, state] of this.circuit.entries()) {
      failoverHealth[baseUrl] = upstreamHealth(state);
    }
    return {
      running: true,
      port: this.port,
      baseUrl: buildLocalGatewayBaseUrl(this.port),
      upstreamBaseUrl: this.upstream?.baseUrl,
      error: this.lastError,
      stats: this.statsTracker.snapshot(),
      failoverHealth,
    };
  }

  async start(upstream: AiCliGatewayUpstream): Promise<AiCliGatewayStatus> {
    const baseUrl = upstream.baseUrl.trim();
    const apiKey = upstream.apiKey.trim();
    if (!baseUrl || !apiKey) {
      throw new Error('upstream_incomplete');
    }
    const normalized: AiCliGatewayUpstream = { ...upstream, baseUrl, apiKey };
    this.assertNotSelfForwarding(normalized);
    this.upstream = normalized;
    if (this.upstreams.length === 0) {
      this.upstreams = [normalized];
    }
    if (this.server) {
      return this.getStatus();
    }
    const port = await findAvailablePortFrom(DEFAULT_GATEWAY_PORT_START, DEFAULT_GATEWAY_PORT_END);
    this.lastError = undefined;

    const server = http.createServer((req, res) => {
      void this.handleRequest(req, res);
    });
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject);
      server.listen(port, '127.0.0.1', () => resolve());
    });
    this.server = server;
    this.port = port;
    this.statsTracker.reset();
    return this.getStatus();
  }

  async stop(): Promise<void> {
    this.outboundProxyAgent?.destroy();
    this.outboundProxyAgent = undefined;
    this.directHttpAgent?.destroy();
    this.directHttpAgent = undefined;
    this.directHttpsAgent?.destroy();
    this.directHttpsAgent = undefined;
    if (!this.server) {
      this.port = null;
      this.upstream = null;
      this.upstreams = [];
      return;
    }
    const closing = this.server;
    this.server = null;
    this.port = null;
    this.upstream = null;
    this.openaiUpstream = null;
    this.upstreams = [];
    this.openaiUpstreams = [];
    this.circuit.clear();
    this.statsTracker.reset();
    await new Promise<void>((resolve) => {
      closing.close(() => resolve());
    });
  }

  getUpstream(): AiCliGatewayUpstream | null {
    return this.upstream;
  }

  private emitLog(entry: GatewayLogEntry): void {
    this.logListener?.(entry);
  }

  private emitUsage(record: TokenUsageRecord): void {
    this.usageListener?.({ ...record, source: 'proxy' });
  }

  private usageProviderLabel(upstreamUrl: string, providerName?: string): string | undefined {
    const name = providerName?.trim();
    if (name) {
      return name;
    }
    try {
      return new URL(upstreamUrl).hostname;
    } catch {
      return upstreamUrl || undefined;
    }
  }

  private bridgeUsageCtx(
    upstream: AiCliGatewayUpstream,
    status: number,
    startTime: number,
    streaming: boolean,
    reportedCostUsd?: number
  ): UsageRecordContext {
    return {
      status,
      durationMs: Date.now() - startTime,
      streaming,
      providerName: upstream.providerName,
      reportedCostUsd,
    };
  }

  private emitRequestUsage(
    reqModel: string,
    upstream: string,
    urlPath: string,
    ctx?: UsageRecordContext
  ): void {
    this.emitUsage({
      app: inferUsageApp(urlPath, reqModel),
      model: reqModel || 'unknown',
      inputTokens: 0,
      outputTokens: 0,
      cacheReadTokens: 0,
      cacheCreationTokens: 0,
      serverToolUseTokens: 0,
      requestId: '',
      upstream,
      provider: this.usageProviderLabel(upstream, ctx?.providerName),
      status: ctx?.status,
      durationMs: ctx?.durationMs,
      streaming: ctx?.streaming,
      reportedCostUsd: ctx?.reportedCostUsd,
      ts: new Date().toISOString(),
    });
  }

  private recordProxiedRequestIfNeeded(
    method: string,
    urlPath: string,
    status: number,
    reqModel: string,
    upstream: string,
    usageEmitted: boolean,
    ctx?: UsageRecordContext
  ): void {
    if (usageEmitted) {
      return;
    }
    if (!shouldRecordGatewayRequest(method, urlPath)) {
      return;
    }
    this.emitRequestUsage(reqModel, upstream, urlPath, { ...ctx, status });
  }

  private async handleRequest(clientReq: IncomingMessage, clientRes: ServerResponse): Promise<void> {
    if (!this.upstream || !this.port) {
      this.writeJson(clientRes, 503, { error: 'gateway_not_ready' });
      return;
    }

    const method = clientReq.method ?? 'GET';
    const urlPath = normalizeGatewayRequestPath(clientReq.url ?? '/');
    const startTime = Date.now();

    if (method === 'OPTIONS') {
      clientRes.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': '*',
      });
      clientRes.end();
      return;
    }

    if (urlPath === '/health' || urlPath.startsWith('/health?')) {
      this.writeJson(clientRes, 200, {
        ok: true,
        service: 'agentsociety-ai-cli-gateway',
        port: this.port,
        upstream: this.upstream.baseUrl,
        failover: this.failoverEnabled,
        ...this.statsTracker.snapshot(),
      });
      return;
    }

    this.statsTracker.onRequestStart();
    let success = false;
    try {
      if (urlPath === '/v1/usage' || urlPath === '/usage') {
        this.writeJson(clientRes, 200, { hint: 'Usage stats are available via the extension UI' });
        success = true;
        return;
      }

      if (!urlPath.startsWith('/v1') && !urlPath.startsWith('/claude/')) {
        this.writeJson(clientRes, 404, { error: 'not_found', hint: 'Use /v1/messages, /v1/responses, or /v1/models' });
        return;
      }

      const isStreaming = clientReq.headers.accept?.includes('text/event-stream') ?? false;
      const needsBodyCapture =
        method === 'POST' &&
        (urlPath.includes('/messages') ||
          urlPath.includes('/responses') ||
          urlPath.includes('/chat/completions'));

      let body: Buffer;
      try {
        body = method === 'GET' || method === 'HEAD' ? Buffer.alloc(0) : await readRequestBody(clientReq);
      } catch (err) {
        this.writeJson(clientRes, 413, {
          error: 'payload_too_large',
          message: this.clientSafeErrorMessage(err),
        });
        return;
      }

      if (this.pathNeedsOpenAiUpstream(urlPath) && !this.openaiUpstream) {
        this.writeJson(clientRes, 503, {
          error: 'codex_upstream_missing',
          message:
            'Codex proxy requires an active OpenAI-format provider with an API key. Add a key or disable Codex local proxy for ChatGPT subscription.',
        });
        return;
      }

      const primaryUpstream = this.pickUpstreamForPath(urlPath);
      if (!primaryUpstream) {
        this.writeJson(clientRes, 503, { error: 'gateway_not_ready' });
        return;
      }

      const modelsPath = urlPath.split('?')[0];
      if (method === 'GET' && (modelsPath.endsWith('/models') || modelsPath.endsWith('/v1/models'))) {
        const hasAnthropicHeaders =
          Boolean(clientReq.headers['anthropic-version']) ||
          Boolean(clientReq.headers['x-api-key']);
        if (this.openaiUpstream && !hasAnthropicHeaders) {
          const catalog = readCodexModelCatalogDocument();
          this.writeJson(clientRes, 200, catalog ?? { models: [] });
          success = true;
          return;
        }
        if (!this.pathNeedsOpenAiUpstream(urlPath)) {
          const synthesized = buildAnthropicGatewayModelsResponse(primaryUpstream);
          if (synthesized) {
            this.writeJson(clientRes, 200, synthesized);
            success = true;
            return;
          }
        }
      }

      const resolvedCodexFormat =
        primaryUpstream.codexApiFormat ??
        (primaryUpstream.apiKind === 'openai'
          ? inferOpenAiApiFormat(primaryUpstream.baseUrl)
          : primaryUpstream.apiKind === 'anthropic'
            ? undefined
            : inferOpenAiApiFormat(primaryUpstream.baseUrl));
      const usesCodexChatBridge =
        method === 'POST' &&
        isCodexResponsesPath(urlPath) &&
        resolvedCodexFormat === 'openai_chat';

      const usesClaudeOpenAiChatBridge =
        method === 'POST' &&
        isAnthropicMessagesPath(urlPath) &&
        Boolean(primaryUpstream.codexApiFormat);
      const usesCodexAnthropicBridge =
        method === 'POST' &&
        isCodexResponsesPath(urlPath) &&
        !usesCodexChatBridge &&
        primaryUpstream.apiKind === 'anthropic';

      if (usesCodexChatBridge || usesClaudeOpenAiChatBridge || usesCodexAnthropicBridge) {
        const candidates = this.isFailoverActiveForPath(urlPath)
          ? this.orderedUpstreamsForPath(urlPath)
          : [primaryUpstream];
        const maxAttempts = this.isFailoverActiveForPath(urlPath)
          ? Math.min(FAILOVER_MAX_ATTEMPTS, candidates.length)
          : 1;
        let lastStatus = 502;
        let lastFailDetail: string | undefined;
        for (let attempt = 0; attempt < maxAttempts; attempt++) {
          const upstream = candidates[attempt];
          if (!upstream) {
            break;
          }
          if (isCircuitOpen(this.circuit.get(upstream.baseUrl.trim()))) {
            continue;
          }
          try {
            const result = usesClaudeOpenAiChatBridge
              ? await this.proxyAnthropicMessagesViaOpenAiChat(
                clientReq,
                clientRes,
                method,
                urlPath,
                startTime,
                body,
                upstream
              )
              : usesCodexChatBridge
                ? await this.proxyCodexResponsesViaChat(
                  clientReq,
                  clientRes,
                  method,
                  urlPath,
                  startTime,
                  body,
                  upstream
                )
                : await this.proxyCodexResponsesViaAnthropic(
                  clientReq,
                  clientRes,
                  method,
                  urlPath,
                  startTime,
                  body,
                  upstream
                );
            lastStatus = result.status > 0 ? result.status : 502;
            lastFailDetail = result.detail ?? this.lastError;
            if (result.ok) {
              recordUpstreamSuccess(this.circuit, upstream.baseUrl);
              if (attempt > 0) {
                this.commitFailoverUpstream(urlPath, upstream);
              }
              success = true;
              return;
            }
            if (result.status === 499 || clientRes.destroyed) {
              return;
            }
            if (shouldFailoverHttpStatus(result.status)) {
              recordUpstreamFailure(this.circuit, upstream.baseUrl);
            }
            if (clientRes.headersSent) {
              return;
            }
            if (this.isFailoverActiveForPath(urlPath) && result.canRetry) {
              continue;
            }
            this.writeJson(clientRes, lastStatus, {
              error: 'upstream_error',
              message: lastFailDetail ?? `Upstream request failed with HTTP ${lastStatus}`,
              hint: usesClaudeOpenAiChatBridge
                ? 'Claude Code OpenAI-compatible routes translate Anthropic Messages to Chat Completions. Set the provider model explicitly if the upstream rejects Claude model aliases.'
                : usesCodexChatBridge
                  ? `Codex /v1/responses was translated to Chat Completions at ${resolveChatCompletionsTargetUrl(upstream.baseUrl)}. Check provider key/model/quota.`
                  : 'Codex /v1/responses was translated to Anthropic Messages for this provider.',
            });
            return;
          } catch (err) {
            const message = this.clientSafeErrorMessage(err);
            this.lastError = message;
            lastFailDetail = message;
            recordUpstreamFailure(this.circuit, upstream.baseUrl);
            if (clientRes.headersSent) {
              return;
            }
            if (this.isFailoverActiveForPath(urlPath)) {
              continue;
            }
            this.writeJson(clientRes, 500, { error: 'gateway_error', message });
            return;
          }
        }
        if (!clientRes.headersSent && !clientRes.destroyed) {
          this.writeJson(clientRes, lastStatus > 0 ? lastStatus : 502, {
            error: 'failover_exhausted',
            message: lastFailDetail ?? 'All configured upstream providers failed',
            hint: usesClaudeOpenAiChatBridge
              ? 'Claude Code OpenAI-compatible routes translate Anthropic Messages to Chat Completions. Set the provider model explicitly if the upstream rejects Claude model aliases.'
              : 'Third-party Codex routes map gpt-* requests to the provider model (e.g. glm-5.2). Set the model in the provider card or pick a built-in preset.',
          });
        }
        return;
      }

      const candidates = this.isFailoverActiveForPath(urlPath)
        ? this.orderedUpstreamsForPath(urlPath)
        : [primaryUpstream];
      const maxAttempts = this.isFailoverActiveForPath(urlPath)
        ? Math.min(FAILOVER_MAX_ATTEMPTS, candidates.length)
        : 1;
      let lastStatus = 502;

      for (let attempt = 0; attempt < maxAttempts; attempt++) {
        const upstream = candidates[attempt];
        if (!upstream) {
          break;
        }
        if (isCircuitOpen(this.circuit.get(upstream.baseUrl.trim()))) {
          continue;
        }

        try {
          const targetUrl = resolveUpstreamTargetUrl(upstream.baseUrl, urlPath);
          const parsed = new URL(targetUrl);
          const result = isStreaming
            ? await this.proxyStream(
              upstream,
              clientReq,
              clientRes,
              method,
              parsed,
              targetUrl,
              urlPath,
              startTime,
              needsBodyCapture,
              body
            )
            : await this.proxyBuffered(
              upstream,
              clientReq,
              clientRes,
              method,
              parsed,
              targetUrl,
              urlPath,
              startTime,
              needsBodyCapture,
              body
            );

          lastStatus = result.status;

          if (result.ok) {
            recordUpstreamSuccess(this.circuit, upstream.baseUrl);
            if (attempt > 0) {
              this.commitFailoverUpstream(urlPath, upstream);
            }
            success = true;
            return;
          }

          if (result.status === 499 || clientRes.destroyed) {
            return;
          }

          if (shouldFailoverHttpStatus(result.status)) {
            recordUpstreamFailure(this.circuit, upstream.baseUrl);
          }
          if (clientRes.headersSent) {
            return;
          }
          if (this.isFailoverActiveForPath(urlPath) && result.canRetry) {
            continue;
          }
          this.writeJson(clientRes, result.status > 0 ? result.status : 502, {
            error: 'upstream_error',
            message: result.detail ?? this.lastError ?? `Upstream request failed with HTTP ${result.status || 502}`,
          });
          return;
        } catch (err) {
          const message = this.clientSafeErrorMessage(err);
          this.lastError = message;
          recordUpstreamFailure(this.circuit, upstream.baseUrl);
          if (clientRes.headersSent) {
            return;
          }
          if (this.isFailoverActiveForPath(urlPath)) {
            continue;
          }
          this.writeJson(clientRes, 500, { error: 'gateway_error', message });
          return;
        }
      }

      if (!clientRes.headersSent && !clientRes.destroyed) {
        this.writeJson(clientRes, lastStatus > 0 ? lastStatus : 502, {
          error: 'failover_exhausted',
          message: 'All configured upstream providers failed',
        });
      }
    } finally {
      this.statsTracker.onRequestEnd(success);
    }
  }

  private tryBuildRectifiedBody(
    clientReq: IncomingMessage,
    forwardedBody: Buffer,
    status: number,
    errBody: Buffer
  ): Buffer | null {
    if (!this.rectifier.enabled || status < 400 || status >= 500) {
      return null;
    }
    let original: Record<string, unknown>;
    try {
      original = JSON.parse(forwardedBody.toString('utf-8')) as Record<string, unknown>;
    } catch {
      return null;
    }
    const kind = classifyRectifierRetry(
      status,
      errBody.toString('utf-8'),
      this.rectifier,
      original
    );
    if (!kind) {
      return null;
    }
    const tried = this.rectifierKindsFor(clientReq);
    if (tried.has(kind)) {
      return null;
    }
    const fixed = applyRectifierRetryFix(original, kind);
    if (!rectifierFixChanged(original, fixed)) {
      return null;
    }
    tried.add(kind);
    return Buffer.from(JSON.stringify(fixed), 'utf-8');
  }

  private async proxyStream(
    upstream: AiCliGatewayUpstream,
    clientReq: IncomingMessage,
    clientRes: ServerResponse,
    method: string,
    parsed: URL,
    targetUrl: string,
    urlPath: string,
    startTime: number,
    captureUsage: boolean,
    body: Buffer
  ): Promise<ProxyAttemptResult> {
    const headers = filterForwardHeaders(clientReq.headers, parsed.host);
    headers['x-upstream-base'] = upstream.baseUrl;
    applyUpstreamAuth(headers, upstream.apiKey, upstream.baseUrl, upstream.authHeaderMode);
    const mappedRequest = applyAnthropicRequestMapping(
      upstream,
      urlPath,
      body,
      this.rectifier,
      this.optimizer
    );
    const forwardedBody = mappedRequest.body;
    if (forwardedBody.length > 0) {
      headers['content-length'] = String(forwardedBody.length);
    }

    let reqModel = mappedRequest.model;
    if (captureUsage && body.length > 0) {
      try {
        reqModel = reqModel || extractModelFromRequest(JSON.parse(body.toString('utf-8')));
      } catch {
        /* ignore */
      }
    }

    const transport = parsed.protocol === 'https:' ? https : http;
    let fullResponse = '';

    return new Promise<ProxyAttemptResult>((resolve) => {
      const proxyReq = transport.request(parsed, { method, headers, agent: this.outboundAgent(parsed.protocol) }, (proxyRes) => {
        const status = proxyRes.statusCode ?? 502;
        const reportedCostUsd = reportedCostFromHeaders(proxyRes.headers);
        const canRetry = shouldFailoverHttpStatus(status) && !clientRes.headersSent;

        if (canRetry) {
          proxyRes.resume();
          resolve({ ok: false, status, canRetry: true });
          return;
        }

        if (
          !clientRes.headersSent &&
          status >= 400 &&
          status < 500 &&
          isAnthropicMessagesPath(urlPath)
        ) {
          const errChunks: Buffer[] = [];
          proxyRes.on('data', (chunk: Buffer) => errChunks.push(chunk));
          proxyRes.on('end', () => {
            const errBody = Buffer.concat(errChunks);
            const fixed = this.tryBuildRectifiedBody(clientReq, forwardedBody, status, errBody);
            if (!fixed) {
              const respHeaders = filterProxyResponseHeaders(proxyRes.headers);
              respHeaders['content-length'] = String(errBody.length);
              clientRes.writeHead(status, respHeaders);
              clientRes.end(errBody);
              resolve({
                ok: false,
                status,
                canRetry: false,
                detail: summarizeUpstreamErrorBody(errBody, status),
              });
              return;
            }
            void this.proxyStream(
              upstream,
              clientReq,
              clientRes,
              method,
              parsed,
              targetUrl,
              urlPath,
              startTime,
              captureUsage,
              fixed
            ).then(resolve);
          });
          proxyRes.on('error', () => {
            resolve({ ok: false, status, canRetry: false });
          });
          return;
        }

        clientRes.writeHead(status, filterProxyResponseHeaders(proxyRes.headers));

        if (captureUsage) {
          proxyRes.on('data', (chunk: Buffer) => {
            if (fullResponse.length < 1_000_000) {
              fullResponse += chunk.toString('utf-8');
            }
          });
        }

        proxyRes.pipe(clientRes);
        proxyRes.on('end', () => {
          const ms = Date.now() - startTime;
          const usageCtx: UsageRecordContext = {
            status,
            durationMs: ms,
            streaming: true,
            providerName: upstream.providerName,
            reportedCostUsd,
          };
          this.emitLog({
            ts: new Date().toISOString(),
            method,
            path: urlPath,
            upstream: targetUrl,
            status,
            ms,
            model: reqModel || undefined,
          });
          if (captureUsage && fullResponse) {
            this.processUsageFromSSE(fullResponse, reqModel, targetUrl, urlPath, usageCtx);
          } else {
            this.recordProxiedRequestIfNeeded(
              method,
              urlPath,
              status,
              reqModel,
              targetUrl,
              false,
              usageCtx
            );
          }
          resolve({ ok: status > 0 && status < 500, status, canRetry: false });
        });
        proxyRes.on('error', () => {
          clientRes.end();
          resolve({ ok: false, status, canRetry: false });
        });
      });
      this.bindProxyRequestLifecycle(proxyReq, clientReq, clientRes);
      proxyReq.on('error', (err) => {
        const result = this.proxyRequestErrorResult(err, clientReq, clientRes);
        if (clientRes.headersSent && !clientRes.writableEnded) {
          clientRes.end();
        }
        resolve(result);
      });
      if (forwardedBody.length > 0) {
        proxyReq.write(forwardedBody);
      }
      proxyReq.end();
    });
  }

  private async proxyBuffered(
    upstream: AiCliGatewayUpstream,
    clientReq: IncomingMessage,
    clientRes: ServerResponse,
    method: string,
    parsed: URL,
    targetUrl: string,
    urlPath: string,
    startTime: number,
    captureUsage: boolean,
    body: Buffer
  ): Promise<ProxyAttemptResult> {
    const headers = filterForwardHeaders(clientReq.headers, parsed.host);
    headers['x-upstream-base'] = upstream.baseUrl;
    applyUpstreamAuth(headers, upstream.apiKey, upstream.baseUrl, upstream.authHeaderMode);
    const mappedRequest = applyAnthropicRequestMapping(
      upstream,
      urlPath,
      body,
      this.rectifier,
      this.optimizer
    );
    const forwardedBody = mappedRequest.body;
    if (forwardedBody.length > 0) {
      headers['content-length'] = String(forwardedBody.length);
    }

    let reqModel = mappedRequest.model;
    if (captureUsage && body.length > 0) {
      try {
        reqModel = reqModel || extractModelFromRequest(JSON.parse(body.toString('utf-8')));
      } catch {
        /* ignore */
      }
    }

    const transport = parsed.protocol === 'https:' ? https : http;

    return new Promise<ProxyAttemptResult>((resolve) => {
      const proxyReq = transport.request(parsed, { method, headers, agent: this.outboundAgent(parsed.protocol) }, (proxyRes) => {
        const status = proxyRes.statusCode ?? 502;
        const reportedCostUsd = reportedCostFromHeaders(proxyRes.headers);
        const respHeaders = filterProxyResponseHeaders(proxyRes.headers);
        const canRetry = shouldFailoverHttpStatus(status) && !clientRes.headersSent;

        if (canRetry) {
          proxyRes.resume();
          resolve({ ok: false, status, canRetry: true });
          return;
        }

        if (
          !clientRes.headersSent &&
          status >= 400 &&
          status < 500 &&
          isAnthropicMessagesPath(urlPath)
        ) {
          const errChunks: Buffer[] = [];
          proxyRes.on('data', (chunk: Buffer) => errChunks.push(chunk));
          proxyRes.on('end', () => {
            const errBody = Buffer.concat(errChunks);
            const fixed = this.tryBuildRectifiedBody(clientReq, forwardedBody, status, errBody);
            if (!fixed) {
              delete respHeaders['transfer-encoding'];
              respHeaders['content-length'] = String(errBody.length);
              clientRes.writeHead(status, respHeaders);
              clientRes.end(errBody);
              resolve({ ok: false, status, canRetry: false, detail: summarizeUpstreamErrorBody(errBody, status) });
              return;
            }
            void this.proxyBuffered(
              upstream,
              clientReq,
              clientRes,
              method,
              parsed,
              targetUrl,
              urlPath,
              startTime,
              captureUsage,
              fixed
            ).then(resolve);
          });
          proxyRes.on('error', () => {
            resolve({ ok: false, status, canRetry: false });
          });
          return;
        }

        const isChunked = proxyRes.headers['transfer-encoding']?.toString().includes('chunked');
        const isSse = respHeaders['content-type']?.toString().includes('text/event-stream');

        if (isChunked || isSse) {
          let fullResponse = '';
          if (captureUsage) {
            proxyRes.on('data', (chunk: Buffer) => {
              if (fullResponse.length < 1_000_000) {
                fullResponse += chunk.toString('utf-8');
              }
            });
          }
          clientRes.writeHead(status, respHeaders);
          proxyRes.pipe(clientRes);
          proxyRes.on('end', () => {
            const ms = Date.now() - startTime;
            const usageCtx: UsageRecordContext = {
              status,
              durationMs: ms,
              streaming: true,
              providerName: upstream.providerName,
              reportedCostUsd,
            };
            this.emitLog({
              ts: new Date().toISOString(),
              method,
              path: urlPath,
              upstream: targetUrl,
              status,
              ms,
              model: reqModel || undefined,
            });
            if (captureUsage && fullResponse) {
              this.processUsageFromSSE(fullResponse, reqModel, targetUrl, urlPath, usageCtx);
            } else {
              this.recordProxiedRequestIfNeeded(
                method,
                urlPath,
                status,
                reqModel,
                targetUrl,
                false,
                usageCtx
              );
            }
            resolve({ ok: status > 0 && status < 500, status, canRetry: false });
          });
          proxyRes.on('error', () => {
            clientRes.end();
            resolve({ ok: false, status, canRetry: false });
          });
          return;
        }

        const chunks: Buffer[] = [];
        proxyRes.on('data', (chunk: Buffer) => chunks.push(chunk));
        proxyRes.on('end', () => {
          const respBody = Buffer.concat(chunks);
          respHeaders['content-length'] = String(respBody.length);
          clientRes.writeHead(status, respHeaders);
          clientRes.end(respBody);
          const ms = Date.now() - startTime;
          const usageCtx: UsageRecordContext = {
            status,
            durationMs: ms,
            streaming: false,
            providerName: upstream.providerName,
            reportedCostUsd,
          };
          let usageInfo: { model: string; inputTokens: number; outputTokens: number } | null = null;
          let usageEmitted = false;
          if (captureUsage && respBody.length > 0) {
            try {
              const parsedBody = JSON.parse(respBody.toString('utf-8')) as Record<string, unknown>;
              usageInfo = this.emitUsageFromResponseBody(parsedBody, reqModel, targetUrl, urlPath, usageCtx);
              usageEmitted = Boolean(usageInfo);
            } catch {
              /* ignore */
            }
          }
          if (!usageEmitted) {
            this.recordProxiedRequestIfNeeded(
              method,
              urlPath,
              status,
              reqModel,
              targetUrl,
              usageEmitted,
              usageCtx
            );
          }
          this.emitLog({
            ts: new Date().toISOString(),
            method,
            path: urlPath,
            upstream: targetUrl,
            status,
            ms,
            model: usageInfo?.model || reqModel || undefined,
            inputTokens: usageInfo?.inputTokens,
            outputTokens: usageInfo?.outputTokens,
          });
          resolve({ ok: status > 0 && status < 500, status, canRetry: false });
        });
        proxyRes.on('error', () => {
          clientRes.end();
          resolve({ ok: false, status, canRetry: false });
        });
      });
      this.bindProxyRequestLifecycle(proxyReq, clientReq, clientRes);
      proxyReq.on('error', (err) => {
        const result = this.proxyRequestErrorResult(err, clientReq, clientRes);
        if (clientRes.headersSent && !clientRes.writableEnded) {
          clientRes.end();
        }
        resolve(result);
      });
      if (forwardedBody.length > 0) {
        proxyReq.write(forwardedBody);
      }
      proxyReq.end();
    });
  }

  private parseOpenAiSseDataChunk(block: string): Record<string, unknown> | null {
    const dataLine = block.split(/\r?\n/).find((line) => line.startsWith('data:'));
    if (!dataLine) {
      return null;
    }
    const payload = dataLine.slice(5).trim();
    if (!payload || payload === '[DONE]') {
      return null;
    }
    try {
      return JSON.parse(payload) as Record<string, unknown>;
    } catch {
      return null;
    }
  }

  private mergeStreamUsage(
    current: {
      model: string;
      inputTokens: number;
      outputTokens: number;
      cacheReadTokens: number;
      cacheCreationTokens: number;
      cacheCreationLongTokens?: number;
      serverToolUseTokens: number;
      reportedCostUsd?: number;
    } | null,
    chunk: Record<string, unknown>
  ): {
    model: string;
    inputTokens: number;
    outputTokens: number;
    cacheReadTokens: number;
    cacheCreationTokens: number;
    cacheCreationLongTokens?: number;
    serverToolUseTokens: number;
    reportedCostUsd?: number;
  } | null {
    return extractTokenUsage(chunk) ?? current;
  }

  private processUsageFromSSE(
    fullResponse: string,
    reqModel: string,
    upstream: string,
    urlPath: string,
    ctx?: UsageRecordContext
  ): void {
    let lastUsage: {
      model: string;
      inputTokens: number;
      outputTokens: number;
      cacheReadTokens: number;
      cacheCreationTokens: number;
      cacheCreationLongTokens?: number;
      serverToolUseTokens: number;
      reportedCostUsd?: number;
    } | null = null;
    let lastRequestId = '';
    for (const message of parseSseMessages(fullResponse)) {
      if (message.data === '[DONE]') {
        continue;
      }
      try {
        const parsed = JSON.parse(message.data);
        const usage = extractTokenUsage(parsed);
        if (usage) {
          lastUsage = usage;
        }
        const rid = extractRequestId(parsed);
        if (rid) {
          lastRequestId = rid;
        }
      } catch {
        /* ignore */
      }
    }
    if (!lastUsage) {
      for (const line of fullResponse.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) {
          continue;
        }
        const payload = trimmed.slice(5).trim();
        if (!payload || payload === '[DONE]') {
          continue;
        }
        try {
          const parsed = JSON.parse(payload);
          const usage = extractTokenUsage(parsed);
          if (usage) {
            lastUsage = usage;
          }
          const rid = extractRequestId(parsed);
          if (rid) {
            lastRequestId = rid;
          }
        } catch {
          /* ignore */
        }
      }
    }
    if (lastUsage) {
      this.emitUsage({
        app: inferUsageApp(urlPath, lastUsage.model || reqModel),
        model: lastUsage.model || reqModel || 'unknown',
        inputTokens: lastUsage.inputTokens,
        outputTokens: lastUsage.outputTokens,
        cacheReadTokens: lastUsage.cacheReadTokens,
        cacheCreationTokens: lastUsage.cacheCreationTokens,
        cacheCreationLongTokens: lastUsage.cacheCreationLongTokens,
        serverToolUseTokens: lastUsage.serverToolUseTokens,
        requestId: lastRequestId,
        upstream,
        provider: this.usageProviderLabel(upstream, ctx?.providerName),
        status: ctx?.status,
        durationMs: ctx?.durationMs,
        streaming: ctx?.streaming,
        reportedCostUsd: lastUsage.reportedCostUsd ?? ctx?.reportedCostUsd,
        ts: new Date().toISOString(),
      });
      return;
    }
    this.emitRequestUsage(reqModel, upstream, urlPath, ctx);
  }

  private emitUsageFromResponseBody(
    body: Record<string, unknown>,
    reqModel: string,
    upstream: string,
    urlPath: string,
    ctx?: UsageRecordContext
  ): { model: string; inputTokens: number; outputTokens: number } | null {
    const extracted = extractTokenUsage(body);
    if (!extracted) {
      return null;
    }
    this.emitUsage({
      app: inferUsageApp(urlPath, extracted.model || reqModel),
      model: extracted.model || reqModel || 'unknown',
      inputTokens: extracted.inputTokens,
      outputTokens: extracted.outputTokens,
      cacheReadTokens: extracted.cacheReadTokens,
      cacheCreationTokens: extracted.cacheCreationTokens,
      cacheCreationLongTokens: extracted.cacheCreationLongTokens,
      serverToolUseTokens: extracted.serverToolUseTokens,
      requestId: extractRequestId(body),
      upstream,
      provider: this.usageProviderLabel(upstream, ctx?.providerName),
      status: ctx?.status,
      durationMs: ctx?.durationMs,
      streaming: ctx?.streaming,
      reportedCostUsd: extracted.reportedCostUsd ?? ctx?.reportedCostUsd,
      ts: new Date().toISOString(),
    });
    return {
      model: extracted.model || reqModel || 'unknown',
      inputTokens: extracted.inputTokens,
      outputTokens: extracted.outputTokens,
    };
  }

  /**
   * Proxy an OpenAI Responses request through an OpenAI Chat-compatible upstream.
   *
   * Translates the Responses-format request to OpenAI Chat Completions,
   * forwards it, and translates the SSE stream back to Responses format.
   *
   * This is used when the active Codex provider has `codexApiFormat='openai_chat'`
   * (all third-party OpenAI-compatible providers).
   *
   * @see CodexChatStreamTranslator for SSE stream translation
   * @see translateResponsesRequestToChat for request translation
   */
  private async proxyCodexResponsesViaChat(
    clientReq: IncomingMessage,
    clientRes: ServerResponse,
    method: string,
    urlPath: string,
    startTime: number,
    body: Buffer,
    upstream: AiCliGatewayUpstream,
    overrideChatRequest?: Record<string, unknown>
  ): Promise<ProxyAttemptResult> {

    let responsesRequest: Record<string, unknown>;
    try {
      responsesRequest = JSON.parse(body.toString('utf-8')) as Record<string, unknown>;
    } catch {
      this.writeJson(clientRes, 400, { error: 'invalid_json' });
      return { ok: false, status: 400, canRetry: false };
    }

    const chatModel = resolveCodexChatModel(responsesRequest.model, upstream);
    let chatRequest: Record<string, unknown>;
    if (overrideChatRequest) {
      chatRequest = overrideChatRequest;
    } else {
      const preflightResponses = applyPreflightRectifiers(responsesRequest, this.rectifier, chatModel);
      chatRequest = translateResponsesRequestToChat(
        preflightResponses,
        chatModel,
        upstream.baseUrl
      );
      chatRequest = applyPreflightRectifiers(chatRequest, this.rectifier, chatModel);
    }
    const targetUrl = resolveChatCompletionsTargetUrl(upstream.baseUrl);
    const parsed = new URL(targetUrl);
    const isStreaming = chatRequest.stream !== false;
    const headers = filterForwardHeaders(clientReq.headers, parsed.host);
    applyUpstreamAuth(headers, upstream.apiKey, upstream.baseUrl, upstream.authHeaderMode);
    const chatBody = Buffer.from(JSON.stringify(chatRequest), 'utf-8');
    headers['content-type'] = 'application/json';
    headers['content-length'] = String(chatBody.length);
    if (isStreaming) {
      headers.accept = 'text/event-stream';
    }

    const transport = parsed.protocol === 'https:' ? https : http;

    return new Promise<ProxyAttemptResult>((resolve) => {
      const proxyReq = transport.request(parsed, { method, headers, agent: this.outboundAgent(parsed.protocol) }, (proxyRes) => {
        const status = proxyRes.statusCode ?? 502;
        const reportedCostUsd = reportedCostFromHeaders(proxyRes.headers);
        if (status < 200 || status >= 300) {
          const canRetry = shouldFailoverHttpStatus(status) && !clientRes.headersSent;
          const chunks: Buffer[] = [];
          proxyRes.on('data', (chunk: Buffer) => chunks.push(chunk));
          proxyRes.on('end', () => {
            const respBody = Buffer.concat(chunks);
            if (canRetry) {
              resolve({ ok: false, status, canRetry: true, detail: summarizeUpstreamErrorBody(respBody, status) });
              return;
            }
            const fixed = this.tryBuildRectifiedBody(clientReq, chatBody, status, respBody);
            if (fixed && !clientRes.headersSent) {
              void this.proxyCodexResponsesViaChat(
                clientReq,
                clientRes,
                method,
                urlPath,
                startTime,
                body,
                upstream,
                JSON.parse(fixed.toString('utf-8')) as Record<string, unknown>
              ).then(resolve);
              return;
            }
            const detail = summarizeUpstreamErrorBody(respBody, status);
            this.lastError = detail;
            clientRes.writeHead(status, {
              'content-type': proxyRes.headers['content-type'] ?? 'application/json',
              'content-length': String(respBody.length),
            });
            clientRes.end(respBody);
            this.emitLog({
              ts: new Date().toISOString(),
              method,
              path: urlPath,
              upstream: targetUrl,
              status,
              ms: Date.now() - startTime,
              model: chatModel,
            });
            resolve({ ok: false, status, canRetry: false, detail });
          });
          return;
        }

        if (isStreaming) {
          const translator = new CodexChatStreamTranslator(responsesRequest);
          clientRes.writeHead(200, {
            'content-type': 'text/event-stream',
            'cache-control': 'no-cache',
            connection: 'keep-alive',
          });
          for (const event of translator.initialEvents()) {
            clientRes.write(formatResponsesSseEvent(event));
          }
          let buffer = '';
          proxyRes.on('data', (chunk: Buffer) => {
            buffer += chunk.toString('utf-8');
            const lines = buffer.split('\n');
            buffer = lines.pop() ?? '';
            for (const line of lines) {
              for (const event of translator.consumeChatSseLine(line)) {
                clientRes.write(formatResponsesSseEvent(event));
              }
            }
          });
          proxyRes.on('end', () => {
            if (buffer) {
              for (const event of translator.consumeChatSseLine(buffer)) {
                clientRes.write(formatResponsesSseEvent(event));
              }
            }
            const completion = translator.completionEvent();
            clientRes.write(formatResponsesSseEvent(completion));
            clientRes.end();
            const responseBody =
              completion.response && typeof completion.response === 'object'
                ? completion.response as Record<string, unknown>
                : null;
            const usageCtx = this.bridgeUsageCtx(upstream, 200, startTime, true, reportedCostUsd);
            const usageInfo = responseBody
              ? this.emitUsageFromResponseBody(responseBody, chatModel, targetUrl, urlPath, usageCtx)
              : null;
            if (!usageInfo) {
              this.emitRequestUsage(chatModel, targetUrl, urlPath, usageCtx);
            }
            this.emitLog({
              ts: new Date().toISOString(),
              method,
              path: urlPath,
              upstream: targetUrl,
              status: 200,
              ms: Date.now() - startTime,
              model: usageInfo?.model || chatModel,
              inputTokens: usageInfo?.inputTokens,
              outputTokens: usageInfo?.outputTokens,
            });
            resolve({ ok: true, status: 200, canRetry: false });
          });
          proxyRes.on('error', () => {
            clientRes.end();
            resolve({ ok: false, status: 502, canRetry: false });
          });
          return;
        }

        const chunks: Buffer[] = [];
        proxyRes.on('data', (chunk: Buffer) => chunks.push(chunk));
        proxyRes.on('end', () => {
          const respBody = Buffer.concat(chunks);
          let chatJson: Record<string, unknown>;
          try {
            chatJson = JSON.parse(respBody.toString('utf-8')) as Record<string, unknown>;
          } catch {
            const detail = summarizeUpstreamErrorBody(respBody, 502);
            this.lastError = detail;
            clientRes.writeHead(502, { 'content-type': 'application/json' });
            clientRes.end(JSON.stringify({ error: 'upstream_invalid_json', message: detail }));
            resolve({ ok: false, status: 502, canRetry: false, detail });
            return;
          }
          const translated = translateChatCompletionToResponses(chatJson, responsesRequest);
          const out = JSON.stringify(translated);
          clientRes.writeHead(200, {
            'content-type': 'application/json',
            'content-length': Buffer.byteLength(out),
          });
          clientRes.end(out);
          const usageCtx = this.bridgeUsageCtx(upstream, 200, startTime, false, reportedCostUsd);
          const usageInfo = this.emitUsageFromResponseBody(translated, chatModel, targetUrl, urlPath, usageCtx);
          if (!usageInfo) {
            this.emitRequestUsage(chatModel, targetUrl, urlPath, usageCtx);
          }
          this.emitLog({
            ts: new Date().toISOString(),
            method,
            path: urlPath,
            upstream: targetUrl,
            status: 200,
            ms: Date.now() - startTime,
            model: usageInfo?.model || chatModel,
            inputTokens: usageInfo?.inputTokens,
            outputTokens: usageInfo?.outputTokens,
          });
          resolve({ ok: true, status: 200, canRetry: false });
        });
        proxyRes.on('error', () => {
          clientRes.end();
          resolve({ ok: false, status: 502, canRetry: false });
        });
      });
      this.bindProxyRequestLifecycle(proxyReq, clientReq, clientRes);
      proxyReq.on('error', (err) => {
        const result = this.proxyRequestErrorResult(err, clientReq, clientRes);
        if (clientRes.headersSent && !clientRes.writableEnded) {
          clientRes.end();
        }
        resolve(result);
      });
      proxyReq.write(chatBody);
      proxyReq.end();
    });
  }

  /**
   * Proxy an Anthropic Messages request through an OpenAI Chat-compatible upstream.
   *
   * Translates the Anthropic-format request body to OpenAI Chat Completions,
   * forwards it to the upstream, and translates the SSE stream back to
   * Anthropic Messages format.
   *
   * This is used when the active Claude provider has `apiKind='openai'`.
   *
   * @see OpenAiChatToAnthropicStreamTranslator for SSE stream translation
   * @see translateAnthropicMessagesToOpenAiChat for request translation
   */
  private async proxyAnthropicMessagesViaOpenAiChat(
    clientReq: IncomingMessage,
    clientRes: ServerResponse,
    method: string,
    urlPath: string,
    startTime: number,
    body: Buffer,
    upstream: AiCliGatewayUpstream
  ): Promise<ProxyAttemptResult> {
    let anthropicRequest: Record<string, unknown>;
    try {
      anthropicRequest = JSON.parse(body.toString('utf-8')) as Record<string, unknown>;
    } catch {
      this.writeJson(clientRes, 400, { error: 'invalid_json' });
      return { ok: false, status: 400, canRetry: false };
    }

    const mapped = applyAnthropicModelMapping(anthropicRequest, upstream);
    const chatModel = String(mapped.body.model ?? mapped.mappedModel ?? mapped.originalModel ?? upstream.model ?? 'gpt-4o');
    let anthropicBody = applyPreflightRectifiers(mapped.body, this.rectifier, chatModel);
    anthropicBody = applyBedrockRequestOptimizer(anthropicBody, this.optimizer, upstream.baseUrl);
    const chatRequest = translateAnthropicMessagesToOpenAiChat(anthropicBody, chatModel);
    const targetUrl = resolveChatCompletionsTargetUrl(upstream.baseUrl);
    const parsed = new URL(targetUrl);
    const isStreaming = chatRequest.stream !== false;
    const headers = filterForwardHeaders(clientReq.headers, parsed.host);
    applyUpstreamAuth(headers, upstream.apiKey, upstream.baseUrl, upstream.authHeaderMode);
    const chatBody = Buffer.from(JSON.stringify(chatRequest), 'utf-8');
    headers['content-type'] = 'application/json';
    headers['content-length'] = String(chatBody.length);
    if (isStreaming) {
      headers.accept = 'text/event-stream';
    }

    const transport = parsed.protocol === 'https:' ? https : http;

    return new Promise<ProxyAttemptResult>((resolve) => {
      const proxyReq = transport.request(parsed, { method, headers, agent: this.outboundAgent(parsed.protocol) }, (proxyRes) => {
        const status = proxyRes.statusCode ?? 502;
        const reportedCostUsd = reportedCostFromHeaders(proxyRes.headers);
        if (status < 200 || status >= 300) {
          const canRetry = shouldFailoverHttpStatus(status) && !clientRes.headersSent;
          const chunks: Buffer[] = [];
          proxyRes.on('data', (chunk: Buffer) => chunks.push(chunk));
          proxyRes.on('end', () => {
            if (canRetry) {
              resolve({ ok: false, status, canRetry: true });
              return;
            }
            const respBody = Buffer.concat(chunks);
            const fixed = this.tryBuildRectifiedBody(clientReq, Buffer.from(JSON.stringify(anthropicBody), 'utf-8'), status, respBody);
            if (fixed && !clientRes.headersSent) {
              void this.proxyAnthropicMessagesViaOpenAiChat(
                clientReq,
                clientRes,
                method,
                urlPath,
                startTime,
                fixed,
                upstream
              ).then(resolve);
              return;
            }
            const detail = summarizeUpstreamErrorBody(respBody, status);
            this.lastError = detail;
            this.writeJson(clientRes, status, { error: 'upstream_error', message: detail });
            resolve({ ok: false, status, canRetry: false, detail });
          });
          return;
        }

        if (isStreaming) {
          clientRes.writeHead(status, {
            'content-type': 'text/event-stream; charset=utf-8',
            'cache-control': 'no-cache',
            connection: 'keep-alive',
          });
          const translator = new OpenAiChatToAnthropicStreamTranslator(chatModel);
          let buffer = '';
          let usageInfo: {
            model: string;
            inputTokens: number;
            outputTokens: number;
            cacheReadTokens: number;
            cacheCreationTokens: number;
            cacheCreationLongTokens?: number;
            serverToolUseTokens: number;
            reportedCostUsd?: number;
          } | null = null;
          proxyRes.on('data', (chunk: Buffer) => {
            buffer += chunk.toString('utf-8');
            const blocks = buffer.split(/\n\n/);
            buffer = blocks.pop() ?? '';
            for (const block of blocks) {
              const parsedChunk = this.parseOpenAiSseDataChunk(block);
              if (!parsedChunk) {
                continue;
              }
              usageInfo = this.mergeStreamUsage(usageInfo, parsedChunk);
              for (const event of translator.acceptChunk(parsedChunk)) {
                clientRes.write(event);
              }
            }
          });
          proxyRes.on('end', () => {
            if (buffer) {
              const parsedChunk = this.parseOpenAiSseDataChunk(buffer);
              if (parsedChunk) {
                usageInfo = this.mergeStreamUsage(usageInfo, parsedChunk);
                for (const event of translator.acceptChunk(parsedChunk)) {
                  clientRes.write(event);
                }
              }
            }
            if (!usageInfo) {
              const fromTranslator = tokenUsageFromAnthropicUsageObject(
                translator.getLatestUsage(),
                chatModel
              );
              if (fromTranslator) {
                usageInfo = fromTranslator;
              }
            }
            if (!clientRes.writableEnded) {
              clientRes.end();
            }
            const usageCtx = this.bridgeUsageCtx(upstream, status, startTime, true, reportedCostUsd);
            if (usageInfo) {
              this.emitUsage({
                app: 'claude',
                model: usageInfo.model || chatModel,
                inputTokens: usageInfo.inputTokens,
                outputTokens: usageInfo.outputTokens,
                cacheReadTokens: usageInfo.cacheReadTokens,
                cacheCreationTokens: usageInfo.cacheCreationTokens,
                cacheCreationLongTokens: usageInfo.cacheCreationLongTokens,
                serverToolUseTokens: usageInfo.serverToolUseTokens,
                requestId: '',
                upstream: targetUrl,
                provider: this.usageProviderLabel(targetUrl, upstream.providerName),
                status: usageCtx.status,
                durationMs: usageCtx.durationMs,
                streaming: usageCtx.streaming,
                reportedCostUsd: usageInfo.reportedCostUsd ?? usageCtx.reportedCostUsd,
                ts: new Date().toISOString(),
              });
            } else {
              this.emitRequestUsage(chatModel, targetUrl, urlPath, usageCtx);
            }
            const ms = Date.now() - startTime;
            this.emitLog({
              ts: new Date().toISOString(),
              method,
              path: urlPath,
              upstream: targetUrl,
              status,
              ms,
              model: usageInfo?.model || chatModel,
              inputTokens: usageInfo?.inputTokens,
              outputTokens: usageInfo?.outputTokens,
            });
            resolve({ ok: true, status, canRetry: false });
          });
          proxyRes.on('error', () => {
            clientRes.end();
            resolve({ ok: false, status, canRetry: false });
          });
          return;
        }

        const chunks: Buffer[] = [];
        proxyRes.on('data', (chunk: Buffer) => chunks.push(chunk));
        proxyRes.on('end', () => {
          const rawBody = Buffer.concat(chunks);
          try {
            const parsedBody = JSON.parse(rawBody.toString('utf-8')) as Record<string, unknown>;
            const translated = translateOpenAiChatToAnthropicMessage(parsedBody, chatModel);
            const usageCtx = this.bridgeUsageCtx(upstream, status, startTime, false, reportedCostUsd);
            const usageInfo = this.emitUsageFromResponseBody(translated, chatModel, targetUrl, urlPath, usageCtx);
            if (!usageInfo) {
              this.emitRequestUsage(chatModel, targetUrl, urlPath, usageCtx);
            }
            const responseBody = Buffer.from(JSON.stringify(translated), 'utf-8');
            clientRes.writeHead(status, {
              'content-type': 'application/json',
              'content-length': String(responseBody.length),
            });
            clientRes.end(responseBody);
            const ms = Date.now() - startTime;
            this.emitLog({
              ts: new Date().toISOString(),
              method,
              path: urlPath,
              upstream: targetUrl,
              status,
              ms,
              model: usageInfo?.model || chatModel,
              inputTokens: usageInfo?.inputTokens,
              outputTokens: usageInfo?.outputTokens,
            });
            resolve({ ok: true, status, canRetry: false });
          } catch (error) {
            const message = this.clientSafeErrorMessage(error);
            this.lastError = message;
            this.writeJson(clientRes, 502, { error: 'translation_failed', message });
            resolve({ ok: false, status: 502, canRetry: false, detail: message });
          }
        });
      });
      this.bindProxyRequestLifecycle(proxyReq, clientReq, clientRes);
      proxyReq.on('error', (err) => {
        const result = this.proxyRequestErrorResult(err, clientReq, clientRes);
        if (clientRes.headersSent && !clientRes.writableEnded) {
          clientRes.end();
        }
        resolve(result);
      });
      proxyReq.write(chatBody);
      proxyReq.end();
    });
  }

  /**
   * Proxy an OpenAI Responses request through an Anthropic Messages-compatible upstream.
   *
   * This lets a Claude/Anthropic-compatible provider serve Codex through the
   * same local gateway. It mirrors the OpenAI Chat bridge: convert request
   * shape, forward upstream, then convert the response back to Responses.
   */
  private async proxyCodexResponsesViaAnthropic(
    clientReq: IncomingMessage,
    clientRes: ServerResponse,
    method: string,
    urlPath: string,
    startTime: number,
    body: Buffer,
    upstream: AiCliGatewayUpstream,
    overrideAnthropicRequest?: Record<string, unknown>
  ): Promise<ProxyAttemptResult> {
    let responsesRequest: Record<string, unknown>;
    try {
      responsesRequest = JSON.parse(body.toString('utf-8')) as Record<string, unknown>;
    } catch {
      this.writeJson(clientRes, 400, { error: 'invalid_json' });
      return { ok: false, status: 400, canRetry: false };
    }

    const requestedModel = typeof responsesRequest.model === 'string' ? responsesRequest.model : '';
    const mappedModel = applyAnthropicModelMapping(
      { model: requestedModel || upstream.model || 'claude-sonnet-4' },
      upstream
    );
    const anthropicModel = String(
      mappedModel.mappedModel ?? mappedModel.originalModel ?? upstream.model ?? requestedModel ?? 'claude-sonnet-4'
    );
    let anthropicRequest: Record<string, unknown>;
    if (overrideAnthropicRequest) {
      anthropicRequest = overrideAnthropicRequest;
    } else {
      anthropicRequest = translateResponsesRequestToAnthropicMessages(responsesRequest, anthropicModel);
      anthropicRequest = applyPreflightRectifiers(anthropicRequest, this.rectifier, anthropicModel);
      anthropicRequest = applyBedrockRequestOptimizer(anthropicRequest, this.optimizer, upstream.baseUrl);
    }
    const targetUrl = resolveUpstreamTargetUrl(upstream.baseUrl, '/v1/messages');
    const parsed = new URL(targetUrl);
    const isStreaming = anthropicRequest.stream !== false;
    const headers = filterForwardHeaders(clientReq.headers, parsed.host);
    applyUpstreamAuth(headers, upstream.apiKey, upstream.baseUrl, upstream.authHeaderMode);
    const anthropicBody = Buffer.from(JSON.stringify(anthropicRequest), 'utf-8');
    headers['content-type'] = 'application/json';
    headers['content-length'] = String(anthropicBody.length);
    headers['anthropic-version'] = headers['anthropic-version'] || '2023-06-01';
    if (isStreaming) {
      headers.accept = 'text/event-stream';
    }

    const transport = parsed.protocol === 'https:' ? https : http;

    return new Promise<ProxyAttemptResult>((resolve) => {
      const proxyReq = transport.request(parsed, { method, headers, agent: this.outboundAgent(parsed.protocol) }, (proxyRes) => {
        const status = proxyRes.statusCode ?? 502;
        const reportedCostUsd = reportedCostFromHeaders(proxyRes.headers);
        if (status < 200 || status >= 300) {
          const canRetry = shouldFailoverHttpStatus(status) && !clientRes.headersSent;
          const chunks: Buffer[] = [];
          proxyRes.on('data', (chunk: Buffer) => chunks.push(chunk));
          proxyRes.on('end', () => {
            if (canRetry) {
              resolve({ ok: false, status, canRetry: true });
              return;
            }
            const respBody = Buffer.concat(chunks);
            const fixed = this.tryBuildRectifiedBody(clientReq, anthropicBody, status, respBody);
            if (fixed && !clientRes.headersSent) {
              void this.proxyCodexResponsesViaAnthropic(
                clientReq,
                clientRes,
                method,
                urlPath,
                startTime,
                body,
                upstream,
                JSON.parse(fixed.toString('utf-8')) as Record<string, unknown>
              ).then(resolve);
              return;
            }
            const detail = summarizeUpstreamErrorBody(respBody, status);
            this.lastError = detail;
            clientRes.writeHead(status, {
              'content-type': proxyRes.headers['content-type'] ?? 'application/json',
              'content-length': String(respBody.length),
            });
            clientRes.end(respBody);
            this.emitLog({
              ts: new Date().toISOString(),
              method,
              path: urlPath,
              upstream: targetUrl,
              status,
              ms: Date.now() - startTime,
              model: anthropicModel,
            });
            resolve({ ok: false, status, canRetry: false, detail });
          });
          return;
        }

        if (isStreaming) {
          const translator = new AnthropicMessagesToResponsesStreamTranslator(responsesRequest);
          clientRes.writeHead(200, {
            'content-type': 'text/event-stream',
            'cache-control': 'no-cache',
            connection: 'keep-alive',
          });
          for (const event of translator.initialEvents()) {
            clientRes.write(formatAnthropicResponsesSseEvent(event));
          }
          let buffer = '';
          proxyRes.on('data', (chunk: Buffer) => {
            buffer += chunk.toString('utf-8');
            const blocks = buffer.split(/\r?\n\r?\n/);
            buffer = blocks.pop() ?? '';
            for (const block of blocks) {
              for (const message of parseSseMessages(block)) {
                try {
                  const parsedChunk = JSON.parse(message.data) as Record<string, unknown>;
                  for (const event of translator.consumeAnthropicEvent(message.event, parsedChunk)) {
                    clientRes.write(formatAnthropicResponsesSseEvent(event));
                  }
                } catch {
                  /* ignore malformed chunks */
                }
              }
            }
          });
          proxyRes.on('end', () => {
            if (buffer) {
              for (const message of parseSseMessages(buffer)) {
                try {
                  const parsedChunk = JSON.parse(message.data) as Record<string, unknown>;
                  for (const event of translator.consumeAnthropicEvent(message.event, parsedChunk)) {
                    clientRes.write(formatAnthropicResponsesSseEvent(event));
                  }
                } catch {
                  /* ignore malformed final chunk */
                }
              }
            }
            const completion = translator.completionEvent();
            clientRes.write(formatAnthropicResponsesSseEvent(completion));
            clientRes.end();
            const responseBody =
              completion.response && typeof completion.response === 'object'
                ? completion.response as Record<string, unknown>
                : null;
            const usageCtx = this.bridgeUsageCtx(upstream, 200, startTime, true, reportedCostUsd);
            const usageInfo = responseBody
              ? this.emitUsageFromResponseBody(responseBody, anthropicModel, targetUrl, urlPath, usageCtx)
              : null;
            if (!usageInfo) {
              this.emitRequestUsage(anthropicModel, targetUrl, urlPath, usageCtx);
            }
            this.emitLog({
              ts: new Date().toISOString(),
              method,
              path: urlPath,
              upstream: targetUrl,
              status: 200,
              ms: Date.now() - startTime,
              model: usageInfo?.model || anthropicModel,
              inputTokens: usageInfo?.inputTokens,
              outputTokens: usageInfo?.outputTokens,
            });
            resolve({ ok: true, status: 200, canRetry: false });
          });
          proxyRes.on('error', () => {
            clientRes.end();
            resolve({ ok: false, status: 502, canRetry: false });
          });
          return;
        }

        const chunks: Buffer[] = [];
        proxyRes.on('data', (chunk: Buffer) => chunks.push(chunk));
        proxyRes.on('end', () => {
          const rawBody = Buffer.concat(chunks);
          try {
            const parsedBody = JSON.parse(rawBody.toString('utf-8')) as Record<string, unknown>;
            const translated = translateAnthropicMessageToResponses(parsedBody, responsesRequest);
            const out = JSON.stringify(translated);
            clientRes.writeHead(200, {
              'content-type': 'application/json',
              'content-length': Buffer.byteLength(out),
            });
            clientRes.end(out);
            const usageCtx = this.bridgeUsageCtx(upstream, 200, startTime, false, reportedCostUsd);
            const usageInfo = this.emitUsageFromResponseBody(translated, anthropicModel, targetUrl, urlPath, usageCtx);
            if (!usageInfo) {
              this.emitRequestUsage(anthropicModel, targetUrl, urlPath, usageCtx);
            }
            this.emitLog({
              ts: new Date().toISOString(),
              method,
              path: urlPath,
              upstream: targetUrl,
              status: 200,
              ms: Date.now() - startTime,
              model: usageInfo?.model || anthropicModel,
              inputTokens: usageInfo?.inputTokens,
              outputTokens: usageInfo?.outputTokens,
            });
            resolve({ ok: true, status: 200, canRetry: false });
          } catch (error) {
            const message = this.clientSafeErrorMessage(error);
            this.lastError = message;
            this.writeJson(clientRes, 502, { error: 'translation_failed', message });
            resolve({ ok: false, status: 502, canRetry: false, detail: message });
          }
        });
        proxyRes.on('error', () => {
          clientRes.end();
          resolve({ ok: false, status: 502, canRetry: false });
        });
      });
      this.bindProxyRequestLifecycle(proxyReq, clientReq, clientRes);
      proxyReq.on('error', (err) => {
        const result = this.proxyRequestErrorResult(err, clientReq, clientRes);
        if (clientRes.headersSent && !clientRes.writableEnded) {
          clientRes.end();
        }
        resolve(result);
      });
      proxyReq.write(anthropicBody);
      proxyReq.end();
    });
  }

  private writeJson(res: ServerResponse, status: number, payload: unknown): void {
    const shaped = status >= 400 ? normalizeGatewayErrorPayload(status, payload) : payload;
    const sanitized = this.sanitizeErrorPayload(shaped);
    const body = JSON.stringify(sanitized);
    res.writeHead(status, {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body),
    });
    res.end(body);
  }

  /** First-line client-safe error text; never stringify unknown Error (can include stack). */
  private clientSafeErrorMessage(err: unknown): string {
    const raw = err instanceof Error ? err.message : 'request_failed';
    const firstLine = raw.split('\n')[0].trim() || 'request_failed';
    return firstLine.length > 280 ? `${firstLine.slice(0, 280)}…` : firstLine;
  }

  /** Recursively sanitize error payload: drop stacks and truncate messages. */
  private sanitizeErrorPayload(payload: unknown): unknown {
    if (typeof payload !== 'object' || payload === null) {
      return payload;
    }
    if (Array.isArray(payload)) {
      return payload.map((item) => this.sanitizeErrorPayload(item));
    }
    const blockedKeys = new Set([
      'stack',
      'stackTrace',
      'stacktrace',
      'traceback',
      'exception',
      'cause',
      'trace',
    ]);
    const textKeys = new Set(['message', 'error', 'detail', 'hint']);
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(payload as Record<string, unknown>)) {
      if (blockedKeys.has(key)) {
        continue;
      }
      if (textKeys.has(key) && typeof value === 'string') {
        const firstLine = value.split('\n')[0].trim();
        out[key] = firstLine.length > 280 ? `${firstLine.slice(0, 280)}…` : firstLine;
      } else if (typeof value === 'object' && value !== null) {
        out[key] = this.sanitizeErrorPayload(value);
      } else {
        out[key] = value;
      }
    }
    return out;
  }
}
