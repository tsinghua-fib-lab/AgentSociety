import * as https from 'https';
import * as http from 'http';
import { URL } from 'url';
import { readCodexSubscriptionSession } from './codexSettings';
import { applyUpstreamAuthHeaders, type AiCliAuthHeaderMode } from '../aiCli/upstreamAuthHeaders';
import { createOutboundProxyAgent, type OutboundProxyConfig } from './gatewayOutboundProxy';
import { customUsageUrl, detectUsageTemplate, parseCustomUsage, type ProviderUsageOptions, type ProviderUsagePlan, type ProviderUsageResult } from '../shared/providerUsage';
export { supportsProviderUsageQuery } from '../shared/providerUsage';
export type { ProviderUsagePlan, ProviderUsageResult } from '../shared/providerUsage';

type UsageFetcher = (url: string, headers: Record<string, string>) => Promise<unknown>;

const USAGE_TIMEOUT_MS = 12_000;

function fetchJson(url: string, headers: Record<string, string>, proxy?: OutboundProxyConfig | null): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const transport = parsed.protocol === 'https:' ? https : http;
    const agent = createOutboundProxyAgent(proxy);
    const req = transport.request(parsed, { method: 'GET', headers, agent }, (res) => {
      const chunks: Buffer[] = [];
      let size = 0;
      res.on('error', reject);
      res.on('data', (chunk: Buffer) => {
        size += chunk.length;
        if (size > 1024 * 1024) { req.destroy(new Error('response_too_large')); return; }
        chunks.push(chunk);
      });
      res.on('end', () => {
        if ((res.statusCode ?? 0) < 200 || (res.statusCode ?? 0) >= 300) {
          reject(new Error(`http_${res.statusCode}`));
          return;
        }
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf-8'))); }
        catch { reject(new Error('invalid_json')); }
      });
    });
    const timer = setTimeout(() => req.destroy(new Error('timeout')), USAGE_TIMEOUT_MS);
    req.on('error', reject);
    req.on('close', () => { clearTimeout(timer); agent?.destroy(); });
    req.end();
  });
}

function authHeader(apiKey: string): Record<string, string> {
  const token = apiKey.trim();
  if (token.toLowerCase().startsWith('bearer ')) {
    return { Authorization: token };
  }
  return { Authorization: `Bearer ${token}` };
}

async function queryZhipu(apiKey: string, request: UsageFetcher): Promise<ProviderUsageResult> {
  const data = (await request('https://open.bigmodel.cn/api/monitor/usage/quota/limit', {
    ...authHeader(apiKey),
    'Content-Type': 'application/json',
  })) as {
    success?: boolean;
    msg?: string;
    data?: {
      level?: string;
      limits?: Array<{
        type?: string;
        percentage?: number;
        remaining?: number;
        usage?: number;
        currentValue?: number;
        nextResetTime?: number;
      }>;
    };
  };
  if (!data.success || !data.data?.limits) {
    return { ok: false, template: 'zhipu', error: 'query_failed' };
  }
  const limits = data.data.limits;
  const tokenLimits = limits.filter((l) => l.type === 'TOKENS_LIMIT');
  const plans: ProviderUsagePlan[] = [];
  if (tokenLimits[0]) {
    const p = tokenLimits[0].percentage;
    if (p === undefined || !Number.isFinite(p)) { return { ok: false, error: 'invalid_usage_response' }; }
    plans.push({
      name: '5小时额度',
      remaining: `${Math.max(0, 100 - p).toFixed(0)}%`,
      used: `${p.toFixed(0)}%`,
      unit: '%',
      remainingPercent: Math.max(0, Math.min(100, 100 - p)),
    });
  }
  if (tokenLimits[1]) {
    const p = tokenLimits[1].percentage;
    if (p === undefined || !Number.isFinite(p)) { return { ok: false, error: 'invalid_usage_response' }; }
    plans.push({
      name: '每周额度',
      remaining: `${Math.max(0, 100 - p).toFixed(0)}%`,
      used: `${p.toFixed(0)}%`,
      unit: '%',
      remainingPercent: Math.max(0, Math.min(100, 100 - p)),
    });
  }
  const mcp = limits.find((l) => l.type === 'TIME_LIMIT');
  if (mcp) {
    plans.push({
      name: 'MCP 每月',
      remaining: mcp.remaining === undefined ? '—' : String(mcp.remaining),
      used: mcp.currentValue === undefined ? undefined : String(mcp.currentValue),
      unit: '次',
    });
  }
  const summary = plans.map((p) => `${p.name} 余${p.remaining}`).join(' · ');
  return { ok: true, template: 'zhipu', scope: 'quota', plans, summary };
}

async function queryDeepseek(apiKey: string, request: UsageFetcher): Promise<ProviderUsageResult> {
  const data = (await request('https://api.deepseek.com/user/balance', {
    ...authHeader(apiKey),
    Accept: 'application/json',
  })) as {
    is_available?: boolean;
    balance_infos?: Array<{ currency?: string; total_balance?: string; granted_balance?: string; topped_up_balance?: string }>;
  };
  const infos = data.balance_infos ?? [];
  if (!Array.isArray(infos) || infos.length === 0) {
    return { ok: false, template: 'deepseek', error: 'empty_balance' };
  }
  if (infos.some((info) => typeof info.total_balance !== 'string' || !info.total_balance.trim() || !Number.isFinite(Number(info.total_balance)))) { return { ok: false, error: 'invalid_usage_response' }; }
  const parts = infos.map((i) => `${i.total_balance ?? '?'} ${i.currency ?? ''}`.trim());
  return {
    ok: true,
    template: 'deepseek',
    scope: 'balance',
    available: data.is_available,
    summary: parts.join(' · '),
    plans: infos.map((i, idx) => ({
      name: i.currency ?? `账户${idx + 1}`,
      remaining: i.total_balance ?? '—',
      unit: i.currency,
      details: [
        ...(i.topped_up_balance === undefined ? [] : [{ label: 'toppedUp', value: i.topped_up_balance }]),
        ...(i.granted_balance === undefined ? [] : [{ label: 'granted', value: i.granted_balance }]),
      ],
    })),
  };
}

async function queryOpenRouter(apiKey: string, request: UsageFetcher): Promise<ProviderUsageResult> {
  const data = (await request('https://openrouter.ai/api/v1/key', {
    ...authHeader(apiKey),
    Accept: 'application/json',
  })) as {
    data?: {
      label?: string;
      limit?: number | null;
      usage?: number;
      limit_remaining?: number | null;
      is_free_tier?: boolean;
    };
  };
  const d = data.data;
  if (!d) {
    return { ok: false, template: 'openrouter', error: 'empty_response' };
  }
  const remaining =
    typeof d.limit_remaining === 'number'
      ? `$${d.limit_remaining.toFixed(2)}`
      : typeof d.limit === 'number' && typeof d.usage === 'number'
        ? `$${Math.max(0, d.limit - d.usage).toFixed(2)}`
        : '—';
  const summary =
    typeof d.limit === 'number'
      ? `剩余 ${remaining} / 额度 $${d.limit.toFixed(2)}`
      : typeof d.usage === 'number' ? `已用 $${d.usage.toFixed(2)}` : '—';
  return {
    ok: true,
    template: 'openrouter',
    scope: 'key',
    summary,
    plans: [{ name: d.label ?? 'API Key', remaining, used: d.usage === undefined ? undefined : `$${d.usage.toFixed(2)}`, unit: 'USD',
      total: typeof d.limit === 'number' ? d.limit.toFixed(2) : undefined,
      remainingPercent: typeof d.limit === 'number' && d.limit > 0 && typeof d.limit_remaining === 'number' ? Math.max(0, Math.min(100, d.limit_remaining / d.limit * 100)) : undefined }],
  };
}

async function querySiliconFlow(apiKey: string, request: UsageFetcher): Promise<ProviderUsageResult> {
  const data = (await request('https://api.siliconflow.cn/v1/user/info', {
    ...authHeader(apiKey),
    Accept: 'application/json',
  })) as {
    data?: { balance?: string; charge_balance?: string };
  };
  const balance = data.data?.balance ?? data.data?.charge_balance;
  if (balance === undefined || balance === null || String(balance).trim() === '' || !Number.isFinite(Number(balance))) {
    return { ok: false, template: 'siliconflow', error: 'empty_balance' };
  }
  return {
    ok: true,
    template: 'siliconflow',
    scope: 'balance',
    summary: `余额 ${balance}`,
    plans: [{ name: '账户余额', remaining: String(balance), unit: 'CNY' }],
  };
}

type RateLimitWindowPayload = {
  used_percent?: number;
  limit_window_seconds?: number;
  reset_at?: number;
};

function windowLabel(seconds: number | undefined, fallback: string): string {
  if (seconds === undefined || seconds <= 0) {
    return fallback;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes >= 24 * 60) {
    return `${Math.round(minutes / (24 * 60))} 天窗口`;
  }
  if (minutes >= 60) {
    return `${Math.round(minutes / 60)} 小时窗口`;
  }
  return `${minutes} 分钟窗口`;
}

function formatRateLimitWindow(
  window: RateLimitWindowPayload | null | undefined,
  fallbackName: string
): ProviderUsagePlan | null {
  if (!window || window.used_percent === undefined || !Number.isFinite(window.used_percent)) {
    return null;
  }
  const used = Math.max(0, Math.min(100, window.used_percent));
  const remaining = Math.max(0, 100 - used);
  const name = windowLabel(window.limit_window_seconds, fallbackName);
  return {
    name,
    remaining: `${remaining.toFixed(0)}%`,
    used: `${used.toFixed(0)}%`,
    unit: '%',
    remainingPercent: Math.min(100, remaining),
    resetsAt: window.reset_at ? new Date(window.reset_at * 1000).toISOString() : undefined,
  };
}

async function queryCodexSubscriptionUsage(request: UsageFetcher): Promise<ProviderUsageResult> {
  const session = readCodexSubscriptionSession();
  if (!session) {
    return { ok: false, template: 'codex_subscription', error: 'codex_not_logged_in' };
  }
  const headers: Record<string, string> = {
    Authorization: `Bearer ${session.accessToken}`,
    Accept: 'application/json',
    'User-Agent': 'codex-cli',
  };
  if (session.accountId) {
    headers['ChatGPT-Account-Id'] = session.accountId;
  }
  const data = (await request('https://chatgpt.com/backend-api/wham/usage', headers)) as {
    rate_limit?: {
      primary_window?: RateLimitWindowPayload | null;
      secondary_window?: RateLimitWindowPayload | null;
    } | null;
    additional_rate_limits?: Array<{
      limit_name?: string | null;
      rate_limit?: {
        primary_window?: RateLimitWindowPayload | null;
        secondary_window?: RateLimitWindowPayload | null;
      } | null;
    }> | null;
  };
  const primary = formatRateLimitWindow(data.rate_limit?.primary_window, '短期额度');
  const secondary = formatRateLimitWindow(data.rate_limit?.secondary_window, '长期额度');
  const plans = [primary, secondary].filter((p): p is ProviderUsagePlan => p !== null);
  if (plans.length === 0) {
    const codexExtra = data.additional_rate_limits?.find((item) => item.limit_name === 'codex');
    const extraPrimary = formatRateLimitWindow(
      codexExtra?.rate_limit?.primary_window,
      'Codex 短期'
    );
    const extraSecondary = formatRateLimitWindow(
      codexExtra?.rate_limit?.secondary_window,
      'Codex 长期'
    );
    if (extraPrimary) {
      plans.push(extraPrimary);
    }
    if (extraSecondary) {
      plans.push(extraSecondary);
    }
  }
  if (plans.length === 0) {
    return { ok: false, template: 'codex_subscription', error: 'empty_quota' };
  }
  const summary = plans.map((p) => `${p.name} 余 ${p.remaining}`).join(' · ');
  return { ok: true, template: 'codex_subscription', scope: 'quota', plans, summary };
}

export type ProviderUsageQueryOptions = ProviderUsageOptions & {
  authHeaderMode?: AiCliAuthHeaderMode;
  proxy?: OutboundProxyConfig | null;
};

export async function queryProviderUsage(
  baseUrl: string, apiKey: string, options?: ProviderUsageQueryOptions
): Promise<ProviderUsageResult> {
  const template = detectUsageTemplate(baseUrl, options);
  if (!template) { return { ok: false, unsupported: true, error: 'unsupported_provider' }; }
  if (template !== 'codex_subscription' && !apiKey.trim()) { return { ok: false, error: 'missing_api_key' }; }
  const request: UsageFetcher = (url, headers) => fetchJson(url, headers, options?.proxy);
  try {
    let result: ProviderUsageResult;
    switch (template) {
      case 'zhipu': result = await queryZhipu(apiKey, request); break;
      case 'deepseek': result = await queryDeepseek(apiKey, request); break;
      case 'openrouter': result = await queryOpenRouter(apiKey, request); break;
      case 'siliconflow': result = await querySiliconFlow(apiKey, request); break;
      case 'codex_subscription': result = await queryCodexSubscriptionUsage(request); break;
      case 'custom': {
        const config = options!.usageQuery!;
        const url = customUsageUrl(baseUrl, config);
        if (!config.remainingPath?.trim() || !Number.isFinite(config.divisor ?? 1) || (config.divisor ?? 1) <= 0) { throw new Error('invalid_usage_config'); }
        const headers = { Accept: 'application/json' };
        applyUpstreamAuthHeaders(headers, apiKey, { upstreamBaseUrl: baseUrl, mode: options?.authHeaderMode });
        result = parseCustomUsage(await request(url, headers), config);
        break;
      }
      default: return { ok: false, unsupported: true, error: 'unsupported_provider' };
    }
    return { ...result, fetchedAt: result.ok ? new Date().toISOString() : undefined };
  } catch (err) {
    const message = err instanceof Error ? err.message : '';
    const error = /^(http_\d{3}|timeout|invalid_json|response_too_large|invalid_usage_config|invalid_usage_response)$/.test(message) ? message : 'network_error';
    return { ok: false, template, error };
  }
}

/** One request per provider at a time; cache entries expire after one minute. */
export class ProviderUsageCache {
  private readonly entries = new Map<string, { at: number; result: ProviderUsageResult }>();
  private readonly pending = new Map<string, Promise<ProviderUsageResult>>();

  query(key: string, load: () => Promise<ProviderUsageResult>, force = false): Promise<ProviderUsageResult> {
    const pending = this.pending.get(key);
    if (pending) { return pending; }
    const cached = this.entries.get(key);
    if (!force && cached && Date.now() - cached.at < 60_000) { return Promise.resolve(cached.result); }
    const task = load().then((result) => {
      this.entries.delete(key);
      if (this.entries.size >= 128) { this.entries.delete(this.entries.keys().next().value!); }
      this.entries.set(key, { at: Date.now(), result });
      return result;
    }).finally(() => this.pending.delete(key));
    this.pending.set(key, task);
    return task;
  }
}
