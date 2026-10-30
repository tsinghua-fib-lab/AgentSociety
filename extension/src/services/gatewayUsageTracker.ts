export type TokenUsageRecord = {
  app: 'claude' | 'codex';
  source?: 'proxy' | 'session';
  model: string;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  cacheCreationLongTokens?: number;
  serverToolUseTokens: number;
  requestId: string;
  upstream: string;
  provider?: string;
  status?: number;
  durationMs?: number;
  streaming?: boolean;
  /** Authoritative per-request USD cost reported by the upstream, when available. */
  reportedCostUsd?: number;
  ts: string;
};

export type UsageApp = TokenUsageRecord['app'];

export function isUsageApp(value: unknown): value is UsageApp {
  return value === 'claude' || value === 'codex';
}

/** Keep only records that already carry an explicit Claude/Codex app tag. */
export function sanitizeUsageRecords(records: readonly unknown[]): TokenUsageRecord[] {
  const kept: TokenUsageRecord[] = [];
  for (const raw of records) {
    if (!raw || typeof raw !== 'object') {
      continue;
    }
    const record = raw as TokenUsageRecord;
    if (!isUsageApp(record.app)) {
      continue;
    }
    kept.push(record);
  }
  return kept;
}

export type UsageRecordContext = {
  status?: number;
  durationMs?: number;
  streaming?: boolean;
  providerName?: string;
  reportedCostUsd?: number;
};

export type UsageModelStats = {
  input: number;
  output: number;
  cacheRead: number;
  cacheCreation: number;
  requests: number;
};

export type UsageTimeBucket = {
  key: string;
  label: string;
  requests: number;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
};

export type UsageAggregation = {
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCacheReadTokens: number;
  totalCacheCreationTokens: number;
  totalRequests: number;
  totalTokens: number;
  cacheHitRate: number;
  byModel: Record<string, UsageModelStats>;
  byDay: Record<string, UsageModelStats>;
  byApp: Record<'claude' | 'codex', UsageModelStats>;
  timeSeries: UsageTimeBucket[];
};

export type UsageListener = (record: TokenUsageRecord) => void;

const CROSS_SOURCE_MATCH_WINDOW_MS = 10 * 60 * 1000;

function usageFingerprintMatches(
  proxy: TokenUsageRecord,
  session: TokenUsageRecord
): boolean {
  if (proxy.model !== session.model) {
    return false;
  }
  const proxyTs = Date.parse(proxy.ts);
  const sessionTs = Date.parse(session.ts);
  if (
    !Number.isFinite(proxyTs) ||
    !Number.isFinite(sessionTs) ||
    Math.abs(proxyTs - sessionTs) > CROSS_SOURCE_MATCH_WINDOW_MS
  ) {
    return false;
  }
  return (
    proxy.inputTokens === session.inputTokens &&
    proxy.outputTokens === session.outputTokens &&
    proxy.cacheReadTokens === session.cacheReadTokens &&
    proxy.cacheCreationTokens === session.cacheCreationTokens
  );
}

function usageIsEmpty(record: TokenUsageRecord): boolean {
  return (
    record.inputTokens === 0 &&
    record.outputTokens === 0 &&
    record.cacheReadTokens === 0 &&
    record.cacheCreationTokens === 0
  );
}

export function selectAccountingUsageRecords(
  records: TokenUsageRecord[]
): TokenUsageRecord[] {
  const proxyClaude = records.filter(
    (record) => record.app === 'claude' && record.source !== 'session'
  );
  const consumedProxy = new Set<TokenUsageRecord>();
  const replacedProxy = new Set<TokenUsageRecord>();
  const acceptedSession = new Set<TokenUsageRecord>();

  for (const session of records.filter(
    (record) => record.app === 'claude' && record.source === 'session'
  )) {
    const exact = proxyClaude.find(
      (proxy) =>
        !consumedProxy.has(proxy) &&
        ((Boolean(proxy.requestId) && proxy.requestId === session.requestId) ||
          usageFingerprintMatches(proxy, session))
    );
    if (exact) {
      consumedProxy.add(exact);
      continue;
    }
    const empty = proxyClaude.find(
      (proxy) =>
        !consumedProxy.has(proxy) &&
        usageIsEmpty(proxy) &&
        proxy.model === session.model &&
        Math.abs(Date.parse(proxy.ts) - Date.parse(session.ts)) <=
          CROSS_SOURCE_MATCH_WINDOW_MS
    );
    if (empty) {
      consumedProxy.add(empty);
      replacedProxy.add(empty);
    }
    acceptedSession.add(session);
  }

  return records.filter((record) => {
    if (replacedProxy.has(record)) {
      return false;
    }
    if (record.source === 'session' && record.app === 'claude') {
      return acceptedSession.has(record);
    }
    return true;
  });
}

export type SseMessage = {
  event: string;
  data: string;
};

export function parseSseMessages(input: string): SseMessage[] {
  const messages: SseMessage[] = [];
  for (const block of input.split(/\r?\n\r?\n/)) {
    if (!block.trim()) {
      continue;
    }
    let event = '';
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        const value = line.slice(5);
        data.push(value.startsWith(' ') ? value.slice(1) : value);
      }
    }
    if (data.length > 0) {
      messages.push({ event, data: data.join('\n').trim() });
    }
  }
  return messages;
}

type ParsedTokenUsage = {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  cacheCreationLongTokens?: number;
  serverToolUseTokens: number;
  reportedCostUsd?: number;
};

function validReportedCost(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value
    : undefined;
}

function tryParseAnthropicUsage(obj: unknown): ParsedTokenUsage | null {
  if (!obj || typeof obj !== 'object') {
    return null;
  }
  const o = obj as Record<string, unknown>;
  const u = (o.usage ?? o.token_usage ?? o.count_tokens) as Record<string, unknown> | undefined;
  if (!u) {
    return null;
  }
  const hasAnthropicUsage =
    typeof u.input_tokens === 'number' ||
    typeof u.output_tokens === 'number' ||
    typeof u.cache_read_input_tokens === 'number' ||
    typeof u.cache_creation_input_tokens === 'number' ||
    typeof u.cache_creation === 'object' ||
    typeof u.server_tool_use_input_tokens === 'number';
  if (!hasAnthropicUsage) {
    return null;
  }
  const cacheCreation =
    typeof u.cache_creation === 'object' && u.cache_creation !== null
      ? u.cache_creation as Record<string, unknown>
      : {};
  const cacheCreation5m =
    typeof cacheCreation.ephemeral_5m_input_tokens === 'number'
      ? cacheCreation.ephemeral_5m_input_tokens
      : 0;
  const cacheCreation1h =
    typeof cacheCreation.ephemeral_1h_input_tokens === 'number'
      ? cacheCreation.ephemeral_1h_input_tokens
      : 0;
  return {
    inputTokens: typeof u.input_tokens === 'number' ? u.input_tokens : 0,
    outputTokens: typeof u.output_tokens === 'number' ? u.output_tokens : 0,
    cacheReadTokens:
      typeof u.cache_read_input_tokens === 'number'
        ? u.cache_read_input_tokens
        : typeof u.cache_read_tokens === 'number'
          ? u.cache_read_tokens
          : 0,
    cacheCreationTokens:
      typeof u.cache_creation_input_tokens === 'number'
        ? u.cache_creation_input_tokens
        : typeof u.cache_creation_tokens === 'number'
          ? u.cache_creation_tokens
          : cacheCreation5m + cacheCreation1h,
    ...(cacheCreation1h > 0 ? { cacheCreationLongTokens: cacheCreation1h } : {}),
    serverToolUseTokens:
      typeof u.server_tool_use_input_tokens === 'number'
        ? u.server_tool_use_input_tokens
        : 0,
    ...(validReportedCost(u.cost) !== undefined
      ? { reportedCostUsd: validReportedCost(u.cost) }
      : {}),
  };
}

function tryParseOpenAIUsage(obj: unknown): ParsedTokenUsage | null {
  if (!obj || typeof obj !== 'object') {
    return null;
  }
  const o = obj as Record<string, unknown>;
  const u = o.usage as Record<string, unknown> | undefined;
  if (!u) {
    return null;
  }
  const promptDetails =
    typeof u.prompt_tokens_details === 'object' && u.prompt_tokens_details !== null
      ? u.prompt_tokens_details as Record<string, unknown>
      : {};
  const inputDetails =
    typeof u.input_tokens_details === 'object' && u.input_tokens_details !== null
      ? u.input_tokens_details as Record<string, unknown>
      : {};
  const promptTokens =
    typeof u.prompt_tokens === 'number'
      ? u.prompt_tokens
      : typeof u.input_tokens === 'number'
        ? u.input_tokens
        : 0;
  const cachedTokens =
    typeof promptDetails.cached_tokens === 'number'
      ? promptDetails.cached_tokens
      : typeof inputDetails.cached_tokens === 'number'
        ? inputDetails.cached_tokens
        : 0;
  const cacheWriteTokens =
    typeof inputDetails.cache_write_tokens === 'number'
      ? inputDetails.cache_write_tokens
      : typeof promptDetails.cache_write_tokens === 'number'
        ? promptDetails.cache_write_tokens
        : 0;
  const cacheWriteDetailsRaw =
    typeof inputDetails.cache_write_tokens_details === 'object' &&
    inputDetails.cache_write_tokens_details !== null
      ? inputDetails.cache_write_tokens_details as Record<string, unknown>
      : typeof promptDetails.cache_write_tokens_details === 'object' &&
          promptDetails.cache_write_tokens_details !== null
        ? promptDetails.cache_write_tokens_details as Record<string, unknown>
        : {};
  const longCacheWriteTokens =
    typeof cacheWriteDetailsRaw.ttl_12h_tokens === 'number'
      ? cacheWriteDetailsRaw.ttl_12h_tokens
      : 0;
  return {
    // OpenAI includes cache reads and writes in the input total. Store mutually
    // exclusive buckets so pricing never bills either bucket twice.
    inputTokens: Math.max(0, promptTokens - cachedTokens - cacheWriteTokens),
    outputTokens:
      typeof u.completion_tokens === 'number'
        ? u.completion_tokens
        : typeof u.output_tokens === 'number'
          ? u.output_tokens
          : 0,
    cacheReadTokens: cachedTokens,
    cacheCreationTokens: cacheWriteTokens,
    ...(longCacheWriteTokens > 0 ? { cacheCreationLongTokens: longCacheWriteTokens } : {}),
    serverToolUseTokens: 0,
    ...(validReportedCost(u.cost) !== undefined
      ? { reportedCostUsd: validReportedCost(u.cost) }
      : {}),
  };
}

export function tokenUsageFromAnthropicUsageObject(
  usage: unknown,
  model: string
): {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  cacheCreationLongTokens?: number;
  serverToolUseTokens: number;
  reportedCostUsd?: number;
  model: string;
} | null {
  const parsed = tryParseAnthropicUsage({ usage });
  if (!parsed) {
    return null;
  }
  if (
    parsed.inputTokens === 0 &&
    parsed.outputTokens === 0 &&
    parsed.cacheReadTokens === 0 &&
    parsed.cacheCreationTokens === 0
  ) {
    return null;
  }
  return { ...parsed, model };
}

export function extractTokenUsage(body: unknown): {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  cacheCreationLongTokens?: number;
  serverToolUseTokens: number;
  reportedCostUsd?: number;
  model: string;
} | null {
  if (!body || typeof body !== 'object') {
    return null;
  }
  const o = body as Record<string, unknown>;

  const nestedResponse = o.response;
  if (nestedResponse && typeof nestedResponse === 'object') {
    const fromResponse = extractTokenUsage(nestedResponse);
    if (fromResponse) {
      return fromResponse;
    }
  }

  const model =
    typeof o.model === 'string' && o.model
      ? o.model
      : typeof nestedResponse === 'object' &&
        nestedResponse &&
        typeof (nestedResponse as Record<string, unknown>).model === 'string'
        ? String((nestedResponse as Record<string, unknown>).model)
        : '';

  const usage = o.usage && typeof o.usage === 'object'
    ? o.usage as Record<string, unknown>
    : {};
  const hasAnthropicUsage =
    typeof usage.cache_read_input_tokens === 'number' ||
    typeof usage.cache_creation_input_tokens === 'number' ||
    typeof usage.cache_creation === 'object' ||
    typeof usage.server_tool_use_input_tokens === 'number';
  const hasOpenAiUsage =
    !hasAnthropicUsage &&
    (typeof usage.prompt_tokens === 'number' ||
      typeof usage.completion_tokens === 'number' ||
      typeof usage.input_tokens === 'number' ||
      typeof usage.output_tokens === 'number' ||
      typeof usage.prompt_tokens_details === 'object' ||
      typeof usage.completion_tokens_details === 'object' ||
      typeof usage.input_tokens_details === 'object');

  let parsed = hasOpenAiUsage ? tryParseOpenAIUsage(o) : tryParseAnthropicUsage(o);
  if (!parsed) {
    parsed = hasOpenAiUsage ? tryParseAnthropicUsage(o) : tryParseOpenAIUsage(o);
  }
  if (!parsed) {
    return null;
  }
  if (
    parsed.inputTokens === 0 &&
    parsed.outputTokens === 0 &&
    parsed.cacheReadTokens === 0 &&
    parsed.cacheCreationTokens === 0
  ) {
    return null;
  }
  return { ...parsed, model };
}

export function extractModelFromRequest(body: unknown): string {
  if (!body || typeof body !== 'object') {
    return '';
  }
  const o = body as Record<string, unknown>;
  return typeof o.model === 'string' && o.model ? o.model : '';
}

export function extractRequestId(body: unknown): string {
  if (!body || typeof body !== 'object') {
    return '';
  }
  const o = body as Record<string, unknown>;
  return typeof o.id === 'string' && o.id ? o.id : '';
}

function emptyModelStats(): UsageModelStats {
  return { input: 0, output: 0, cacheRead: 0, cacheCreation: 0, requests: 0 };
}

function addRecordToStats(stats: UsageModelStats, r: TokenUsageRecord): void {
  stats.input += r.inputTokens;
  stats.output += r.outputTokens;
  stats.cacheRead += r.cacheReadTokens;
  stats.cacheCreation += r.cacheCreationTokens;
  stats.requests += 1;
}

export function computeCacheHitRate(
  inputTokens: number,
  cacheReadTokens: number
): number {
  const cacheable = inputTokens + cacheReadTokens;
  if (cacheable <= 0) {
    return 0;
  }
  return Math.min(100, (cacheReadTokens / cacheable) * 100);
}

function bucketKey(ts: string): string {
  return ts.slice(0, 10);
}

function formatBucketLabel(key: string): string {
  return key.slice(5);
}

export function buildUsageTimeSeries(
  records: TokenUsageRecord[],
  maxPoints = 30
): UsageTimeBucket[] {
  if (records.length === 0) {
    return [];
  }
  const sorted = [...records].sort((a, b) => a.ts.localeCompare(b.ts));
  const map = new Map<string, UsageTimeBucket>();

  for (const r of sorted) {
    const key = bucketKey(r.ts);
    let b = map.get(key);
    if (!b) {
      b = {
        key,
        label: formatBucketLabel(key),
        requests: 0,
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
        cacheCreationTokens: 0,
      };
      map.set(key, b);
    }
    b.requests += 1;
    b.inputTokens += r.inputTokens;
    b.outputTokens += r.outputTokens;
    b.cacheReadTokens += r.cacheReadTokens;
    b.cacheCreationTokens += r.cacheCreationTokens;
  }

  const series = [...map.values()].sort((a, b) => a.key.localeCompare(b.key));
  if (series.length <= maxPoints) {
    return series;
  }
  return series.slice(-maxPoints);
}

export function aggregateUsage(records: TokenUsageRecord[]): UsageAggregation {
  const usable = sanitizeUsageRecords(records);
  const agg: UsageAggregation = {
    totalInputTokens: 0,
    totalOutputTokens: 0,
    totalCacheReadTokens: 0,
    totalCacheCreationTokens: 0,
    totalRequests: usable.length,
    totalTokens: 0,
    cacheHitRate: 0,
    byModel: {},
    byDay: {},
    byApp: {
      claude: emptyModelStats(),
      codex: emptyModelStats(),
    },
    timeSeries: [],
  };
  for (const r of usable) {
    agg.totalInputTokens += r.inputTokens;
    agg.totalOutputTokens += r.outputTokens;
    agg.totalCacheReadTokens += r.cacheReadTokens;
    agg.totalCacheCreationTokens += r.cacheCreationTokens;
    const modelKey = r.model || 'unknown';
    const m = agg.byModel[modelKey] ?? emptyModelStats();
    addRecordToStats(m, r);
    agg.byModel[modelKey] = m;
    const day = r.ts.slice(0, 10);
    const d = agg.byDay[day] ?? emptyModelStats();
    addRecordToStats(d, r);
    agg.byDay[day] = d;
    addRecordToStats(agg.byApp[r.app], r);
  }
  agg.totalTokens =
    agg.totalInputTokens +
    agg.totalOutputTokens +
    agg.totalCacheReadTokens +
    agg.totalCacheCreationTokens;
  agg.cacheHitRate = computeCacheHitRate(agg.totalInputTokens, agg.totalCacheReadTokens);
  agg.timeSeries = buildUsageTimeSeries(usable);
  return agg;
}
