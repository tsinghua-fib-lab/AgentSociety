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
  reportedCostUsd?: number;
  ts: string;
};

export type UsageProviderStats = {
  provider: string;
  requests: number;
  successes: number;
  failures: number;
  input: number;
  output: number;
  cacheRead: number;
  cacheCreation: number;
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
