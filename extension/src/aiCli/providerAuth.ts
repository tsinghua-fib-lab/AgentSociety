import {
  inferApiKindFromBaseUrl,
  isOfficialAnthropicBaseUrl,
  isOfficialOpenAiBaseUrl,
  type AiCliApiKind,
} from './officialEndpoints';

export type AiCliAuthMode = 'subscription' | 'api';

export type AiCliProviderAuthFields = {
  baseUrl: string;
  apiKey: string;
  apiKind?: AiCliApiKind;
  authMode?: AiCliAuthMode;
};

export function inferProviderAuthMode(provider: AiCliProviderAuthFields): AiCliAuthMode {
  if (provider.authMode === 'subscription' || provider.authMode === 'api') {
    return provider.authMode;
  }
  if (provider.apiKey.trim()) {
    return 'api';
  }
  const kind = provider.apiKind ?? inferApiKindFromBaseUrl(provider.baseUrl);
  if (kind === 'openai' && isOfficialOpenAiBaseUrl(provider.baseUrl)) {
    return 'subscription';
  }
  if (kind !== 'openai' && isOfficialAnthropicBaseUrl(provider.baseUrl)) {
    return 'subscription';
  }
  return 'api';
}

export function isOfficialSubscriptionProvider(provider: AiCliProviderAuthFields): boolean {
  return inferProviderAuthMode(provider) === 'subscription';
}

export function providerHasConfiguredCredentials(provider: AiCliProviderAuthFields): boolean {
  if (isOfficialSubscriptionProvider(provider)) {
    return true;
  }
  return Boolean(provider.apiKey.trim());
}

export function providerHasApiUpstream(provider: AiCliProviderAuthFields): boolean {
  return inferProviderAuthMode(provider) === 'api' && Boolean(provider.apiKey.trim());
}

/** Protocol and subscription compatibility, independent of whether secrets have hydrated. */
export function providerSupportsRole(provider: AiCliProviderAuthFields, role: 'claude' | 'codex'): boolean {
  const kind = provider.apiKind ?? inferApiKindFromBaseUrl(provider.baseUrl);
  if (inferProviderAuthMode(provider) === 'subscription') {
    return role === 'codex'
      ? kind === 'openai' && isOfficialOpenAiBaseUrl(provider.baseUrl)
      : kind === 'anthropic' && isOfficialAnthropicBaseUrl(provider.baseUrl);
  }
  return role === 'claude' || kind === 'openai';
}

/**
 * Whether a provider can serve as an API upstream for a CLI role.
 *
 * Claude can use Anthropic upstreams and OpenAI-compatible ones (gateway translates).
 * Codex only uses OpenAI-compatible API upstreams.
 */
export function providerEligibleForRoleUpstream(
  provider: AiCliProviderAuthFields,
  role: 'claude' | 'codex'
): boolean {
  if (!providerHasApiUpstream(provider)) {
    return false;
  }
  if (role === 'claude') {
    return true;
  }
  const kind = provider.apiKind ?? inferApiKindFromBaseUrl(provider.baseUrl);
  return kind === 'openai';
}

export function countApiUpstreamsForRole(
  providers: readonly AiCliProviderAuthFields[],
  role: 'claude' | 'codex'
): number {
  return providers.filter((provider) => providerEligibleForRoleUpstream(provider, role)).length;
}

export type AiCliProviderRoleFlags = {
  activeClaude?: boolean;
  activeCodex?: boolean;
  failoverClaude?: boolean;
  failoverCodex?: boolean;
};

/**
 * Drop role flags incompatible with the protocol or subscription.
 * Does not inspect apiKey so metadata remains stable before secrets hydrate.
 */
export function clampProviderRoleFlags<T extends AiCliProviderAuthFields & AiCliProviderRoleFlags>(
  provider: T
): T {
  const apiKind = provider.apiKind ?? inferApiKindFromBaseUrl(provider.baseUrl);
  return {
    ...provider,
    apiKind,
    activeClaude: Boolean(provider.activeClaude) && providerSupportsRole(provider, 'claude'),
    activeCodex: Boolean(provider.activeCodex) && providerSupportsRole(provider, 'codex'),
    failoverClaude: Boolean(provider.failoverClaude) && inferProviderAuthMode(provider) === 'api',
    failoverCodex: Boolean(provider.failoverCodex) && inferProviderAuthMode(provider) === 'api' && apiKind === 'openai',
  };
}
