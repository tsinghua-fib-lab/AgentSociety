import { isOfficialOpenAiBaseUrl } from '../../aiCli/officialEndpoints';
import type { AiCliAuthMode } from '../../aiCli/providerAuth';

const KNOWN_PROVIDER_HOSTS = [
  'bigmodel.cn',
  'open.bigmodel.cn',
  'deepseek.com',
  'api.deepseek.com',
  'openrouter.ai',
  'siliconflow.cn',
  'api.siliconflow.cn',
];

export function supportsProviderUsageQuery(
  baseUrl: string,
  options?: { authMode?: AiCliAuthMode; apiKind?: 'anthropic' | 'openai' }
): boolean {
  if (
    options?.apiKind === 'openai' &&
    options.authMode === 'subscription' &&
    isOfficialOpenAiBaseUrl(baseUrl)
  ) {
    return true;
  }
  let host: string;
  try {
    host = new URL(baseUrl).hostname.toLowerCase();
  } catch {
    host = baseUrl.toLowerCase();
  }
  return KNOWN_PROVIDER_HOSTS.some(
    (h) => host === h || host.endsWith('.' + h)
  );
}
