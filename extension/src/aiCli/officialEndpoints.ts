export const OFFICIAL_ANTHROPIC_BASE_URL = 'https://api.anthropic.com';
export const OFFICIAL_OPENAI_BASE_URL = 'https://api.openai.com/v1';

export type AiCliApiKind = 'anthropic' | 'openai';

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '');
}

const OPENAI_COMPATIBLE_DOMAINS = [
  'llmapi.fiblab.net',
  'xiaomimimo.com',
  'longcat.chat',
  'siliconflow.cn',
  'dashscope.aliyuncs.com',
  'groq.com',
  'stepfun.com',
  'teapotrouter.com',
];

function parseBaseUrl(baseUrl: string): URL | null {
  try {
    return new URL(baseUrl.trim());
  } catch {
    return null;
  }
}

function isDomainOrSubdomain(hostname: string, domain: string): boolean {
  return hostname === domain || hostname.endsWith(`.${domain}`);
}

export function inferApiKindFromBaseUrl(baseUrl: string): AiCliApiKind {
  const parsed = parseBaseUrl(baseUrl);
  if (!parsed) {
    return 'anthropic';
  }
  const hostname = parsed.hostname.toLowerCase();
  const pathname = parsed.pathname.toLowerCase();
  if (/\/anthropic(\/|$)/.test(pathname)) {
    return 'anthropic';
  }
  if (
    /\/openai(\/|$)/.test(pathname) ||
    /\/compatible-mode(\/|$)/.test(pathname) ||
    /\/coding\/v1(\/|$)/.test(pathname) ||
    /\/coding\/paas(\/|$)/.test(pathname) ||
    OPENAI_COMPATIBLE_DOMAINS.some((domain) =>
      isDomainOrSubdomain(hostname, domain)
    )
  ) {
    return 'openai';
  }
  if (
    hostname === 'api.openai.com' ||
    hostname.endsWith('.api.openai.com') ||
    hostname === 'openai.com' ||
    hostname.endsWith('.openai.com')
  ) {
    return 'openai';
  }
  return 'anthropic';
}

export function isOfficialAnthropicBaseUrl(baseUrl: string): boolean {
  const normalized = normalizeBaseUrl(baseUrl);
  if (!normalized) {
    return true;
  }
  return (
    normalized === OFFICIAL_ANTHROPIC_BASE_URL ||
    normalized === `${OFFICIAL_ANTHROPIC_BASE_URL}/v1`
  );
}

export function isOfficialOpenAiBaseUrl(baseUrl: string): boolean {
  return parseBaseUrl(baseUrl)?.hostname.toLowerCase() === 'api.openai.com';
}

export function resolveProviderBaseUrl(baseUrl: string, apiKind: AiCliApiKind): string {
  const trimmed = baseUrl.trim();
  if (trimmed) {
    return normalizeBaseUrl(trimmed);
  }
  return apiKind === 'openai' ? OFFICIAL_OPENAI_BASE_URL : OFFICIAL_ANTHROPIC_BASE_URL;
}

export function providerUpstream(provider: {
  baseUrl: string;
  apiKey: string;
  apiKind?: AiCliApiKind;
}): {
  baseUrl: string;
  apiKey: string;
  apiKind: AiCliApiKind;
} {
  const apiKind = provider.apiKind ?? inferApiKindFromBaseUrl(provider.baseUrl);
  return {
    apiKind,
    baseUrl: resolveProviderBaseUrl(provider.baseUrl, apiKind),
    apiKey: provider.apiKey.trim(),
  };
}

export function claudeSettingsBaseUrl(resolvedAnthropicBaseUrl: string): string {
  if (isOfficialAnthropicBaseUrl(resolvedAnthropicBaseUrl)) {
    return '';
  }
  // Claude Code appends /v1/messages to this base, so a base that already ends
  // with /v1 (e.g. an OpenAI-style https://host/v1) would hit /v1/v1/messages
  // and 404 as "model not found". Strip the suffix before writing settings.json.
  return resolvedAnthropicBaseUrl.trim().replace(/\/v1\/?$/, '');
}
