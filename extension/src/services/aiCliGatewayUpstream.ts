import type { AiCliAuthHeaderMode } from '../aiCli/upstreamAuthHeaders';

export type AiCliGatewayUpstream = {
  baseUrl: string;
  apiKey: string;
  providerName?: string;
  apiKind?: 'anthropic' | 'openai';
  /** Outbound auth header strategy; omitted/`auto` keeps historical host-based behavior. */
  authHeaderMode?: AiCliAuthHeaderMode;
  model?: string;
  sonnetModel?: string;
  opusModel?: string;
  fableModel?: string;
  haikuModel?: string;
  sonnetDisplayName?: string;
  opusDisplayName?: string;
  fableDisplayName?: string;
  haikuDisplayName?: string;
  declareSonnet1m?: boolean;
  declareOpus1m?: boolean;
  declareFable1m?: boolean;
  codexApiFormat?: 'openai_responses' | 'openai_chat';
  codexModel?: string;
  codexEnable1m?: boolean;
  codexContextWindow?: number;
  codexAutoCompactLimit?: number;
};

export const AI_CLI_GATEWAY_PLACEHOLDER_TOKEN = 'agentsociety-gateway';

// 2026-11-06 二轮审计修复:网关本地令牌。原静态占位串写在 CLI 配置里,
// 等于零认证——任意本机进程/网页(经 rebinding)都可白嫖用户 LLM key。
// 每个扩展宿主进程生成令牌;应用 CLI 配置时刷新,网关逐请求校验。
import * as crypto from 'crypto';

let _gatewayAuthToken: string | null = null;

export function getOrCreateGatewayAuthToken(): string {
  if (_gatewayAuthToken === null) {
    _gatewayAuthToken = crypto.randomBytes(24).toString('hex');
  }
  return _gatewayAuthToken;
}

export function isValidGatewayAuthToken(candidate: unknown): boolean {
  if (typeof candidate !== 'string' || candidate.length === 0) {
    return false;
  }
  const expected = getOrCreateGatewayAuthToken();
  const a = Buffer.from(candidate);
  const b = Buffer.from(expected);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

export function normalizeUpstreamBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '');
}

export function isLocalGatewayBaseUrl(baseUrl: string): boolean {
  const trimmed = baseUrl.trim();
  if (!trimmed) {
    return false;
  }
  try {
    const parsed = new URL(trimmed);
    return parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost';
  } catch {
    return false;
  }
}

export function buildLocalGatewayBaseUrl(port: number): string {
  return `http://127.0.0.1:${port}`;
}

export function upstreamTargetsLocalGateway(baseUrl: string, port: number): boolean {
  try {
    const parsed = new URL(baseUrl.trim());
    const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
    const ipv4Loopback = /^127(?:\.\d{1,3}){3}$/.test(hostname);
    const isLoopback =
      hostname === 'localhost' ||
      hostname === '::1' ||
      ipv4Loopback ||
      hostname === '::ffff:7f00:1' ||
      hostname === '::ffff:127.0.0.1';
    const parsedPort = Number(parsed.port || (parsed.protocol === 'https:' ? 443 : 80));
    return isLoopback && parsedPort === port;
  } catch {
    return false;
  }
}

export function resolveUpstreamTargetUrl(upstreamBase: string, requestPath: string): string {
  const base = normalizeUpstreamBaseUrl(upstreamBase);
  const rawPath = requestPath.startsWith('/') ? requestPath : `/${requestPath}`;
  const path = rawPath.startsWith('/claude/') ? rawPath.slice('/claude'.length) : rawPath;
  if (base.endsWith('/v1') && path.startsWith('/v1/')) {
    return `${base}${path.slice(3)}`;
  }
  if (base.endsWith('/v1') && path === '/v1') {
    return base;
  }
  return `${base}${path}`;
}
