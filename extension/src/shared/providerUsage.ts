import { isOfficialOpenAiBaseUrl } from '../aiCli/officialEndpoints';

export type ProviderUsageConfig = {
  mode: 'auto' | 'off' | 'custom';
  /** A GET endpoint on the provider's own origin. */
  path?: string;
  remainingPath?: string;
  usedPath?: string;
  totalPath?: string;
  unit?: string;
  divisor?: number;
};

export type ProviderUsagePlan = {
  name: string;
  remaining: string;
  used?: string;
  total?: string;
  unit?: string;
  remainingPercent?: number;
  resetsAt?: string;
  details?: Array<{ label: string; value: string }>;
};

export type ProviderUsageResult = {
  ok: boolean;
  template?: string;
  summary?: string;
  plans?: ProviderUsagePlan[];
  scope?: 'balance' | 'quota' | 'key';
  available?: boolean;
  fetchedAt?: string;
  error?: string;
  unsupported?: boolean;
};

export type ProviderUsageOptions = {
  authMode?: 'subscription' | 'api';
  apiKind?: 'anthropic' | 'openai';
  usageQuery?: ProviderUsageConfig;
};

const PROVIDER_HOSTS: Record<string, string> = {
  'bigmodel.cn': 'zhipu',
  'open.bigmodel.cn': 'zhipu',
  'deepseek.com': 'deepseek',
  'api.deepseek.com': 'deepseek',
  'openrouter.ai': 'openrouter',
  'siliconflow.cn': 'siliconflow',
  'api.siliconflow.cn': 'siliconflow',
};

export function detectUsageTemplate(baseUrl: string, options?: ProviderUsageOptions): string | null {
  if (options?.usageQuery?.mode === 'off') { return null; }
  if (options?.usageQuery?.mode === 'custom') { return 'custom'; }
  if (options?.apiKind === 'openai' && options.authMode === 'subscription' && isOfficialOpenAiBaseUrl(baseUrl)) {
    return 'codex_subscription';
  }
  try {
    const url = new URL(baseUrl);
    if (url.protocol !== 'https:' || url.port || url.username || url.password) { return null; }
    return PROVIDER_HOSTS[url.hostname.toLowerCase()] ?? null;
  } catch { return null; }
}

export function supportsProviderUsageQuery(baseUrl: string, options?: ProviderUsageOptions): boolean {
  return detectUsageTemplate(baseUrl, options) !== null;
}

export function customUsageUrl(baseUrl: string, config: ProviderUsageConfig): string {
  const base = new URL(baseUrl);
  const path = config.path?.trim() ?? '';
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password ||
      !path.startsWith('/') || path.startsWith('//') || path.includes('\\')) {
    throw new Error('invalid_usage_config');
  }
  const url = new URL(path, base.origin);
  if (url.origin !== base.origin || url.hash) { throw new Error('invalid_usage_config'); }
  return url.href;
}

function readNumber(body: unknown, path: string): number {
  let value = body;
  for (const part of path.split('.')) {
    if (!part || !value || typeof value !== 'object' || !Object.prototype.hasOwnProperty.call(value, part)) {
      throw new Error('invalid_usage_response');
    }
    value = (value as Record<string, unknown>)[part];
  }
  if ((typeof value !== 'number' && typeof value !== 'string') || String(value).trim() === '' || !Number.isFinite(Number(value))) {
    throw new Error('invalid_usage_response');
  }
  return Number(value);
}

export function parseCustomUsage(body: unknown, config: ProviderUsageConfig): ProviderUsageResult {
  const divisor = config.divisor ?? 1;
  if (!config.remainingPath?.trim() || !Number.isFinite(divisor) || divisor <= 0) {
    throw new Error('invalid_usage_config');
  }
  const remaining = readNumber(body, config.remainingPath.trim()) / divisor;
  const used = config.usedPath?.trim() ? readNumber(body, config.usedPath.trim()) / divisor : undefined;
  const total = config.totalPath?.trim() ? readNumber(body, config.totalPath.trim()) / divisor
    : used === undefined ? undefined : remaining + used;
  if (![remaining, used, total].every((value) => value === undefined || Number.isFinite(value))) {
    throw new Error('invalid_usage_response');
  }
  return {
    ok: true, template: 'custom', scope: 'balance',
    plans: [{
      name: '', remaining: String(remaining), used: used === undefined ? undefined : String(used),
      total: total === undefined ? undefined : String(total), unit: config.unit?.trim(),
      remainingPercent: total !== undefined && total > 0 ? Math.max(0, Math.min(100, remaining / total * 100)) : undefined,
    }],
  };
}
