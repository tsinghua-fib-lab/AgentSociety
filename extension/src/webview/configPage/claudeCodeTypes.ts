export type ClaudeModelOption = {
  id: string;
  label?: string;
};

export interface ClaudeCodeConfigValues {
  apiKey: string;
  baseUrl: string;
  model: string;
  sonnetModel: string;
  opusModel: string;
  fableModel: string;
  haikuModel: string;
  permissionMode: string;
}

export interface ClaudeCodeCliStatus {
  installed: boolean;
  version?: string;
  error?: string;
}

export interface AiCliGatewayStatus {
  enabled: boolean;
  running: boolean;
  port?: number;
  baseUrl?: string;
  upstreamBaseUrl?: string;
  error?: string;
  routeClaude?: boolean;
  routeCodex?: boolean;
  claudeProxyAvailable?: boolean;
  codexProxyAvailable?: boolean;
  /** Whether ~/.codex/auth.json currently has official login tokens. */
  codexOfficialLoginPresent?: boolean;
  /** Absolute path of the auth.json we inspect. */
  codexAuthPath?: string;
  /** Outbound HTTP/SOCKS proxy used by the local gateway (and optionally Codex CLI). */
  outboundProxyUrl?: string;
  rectifier?: {
    enabled: boolean;
    thinkingSignature: boolean;
    thinkingBudget: boolean;
    unsupportedImageDowngrade: boolean;
    heuristicTextOnlyModels: boolean;
  };
  optimizer?: {
    enabled: boolean;
    thinkingOptimizer: boolean;
    cacheInjection: boolean;
  };
  stats?: {
    startedAt: string;
    uptimeMs: number;
    totalRequests: number;
    successfulRequests: number;
    failedRequests: number;
    activeConnections: number;
    successRate: number;
  };
  failoverHealth?: Record<string, 'healthy' | 'degraded' | 'unhealthy'>;
}

export interface CodexRoutingStatus {
  configPath: string;
  authPath?: string;
  routed: boolean;
  directConfigured?: boolean;
  directUrl?: string;
}

export type ProviderUsageQueryResult = import('../../shared/providerUsage').ProviderUsageResult;

export type ProviderAvailabilityResult = {
  ok: boolean;
  models: number;
  apiKind?: 'anthropic' | 'openai';
  error?: string;
  detail?: string;
};
