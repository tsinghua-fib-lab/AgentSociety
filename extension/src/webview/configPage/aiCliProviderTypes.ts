import type { AiCliApiKind } from '../../aiCli/officialEndpoints';
import type { AiCliAuthMode } from '../../aiCli/providerAuth';
import type { AiCliAuthHeaderMode } from '../../aiCli/upstreamAuthHeaders';
import type { ClaudeModelOption } from './claudeCodeTypes';

export type AiCliProviderRecord = {
  id: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  apiKind?: AiCliApiKind;
  authMode?: AiCliAuthMode;
  authHeaderMode?: AiCliAuthHeaderMode;
  activeClaude: boolean;
  activeCodex: boolean;
  failoverClaude: boolean;
  failoverCodex: boolean;
  model?: string;
  codexModel?: string;
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
  codexEnable1m?: boolean;
  codexContextWindow?: number;
  codexAutoCompactLimit?: number;
  permissionMode?: string;
};

export const EMPTY_PROVIDER_DRAFT: Omit<AiCliProviderRecord, 'id' | 'activeClaude' | 'activeCodex'> = {
  failoverClaude: false,
  failoverCodex: false,
  name: '',
  baseUrl: '',
  apiKey: '',
  apiKind: undefined,
  authMode: 'api',
  authHeaderMode: 'auto',
  model: '',
  codexModel: '',
  sonnetModel: '',
  opusModel: '',
  fableModel: '',
  haikuModel: '',
  sonnetDisplayName: '',
  opusDisplayName: '',
  fableDisplayName: '',
  haikuDisplayName: '',
  declareSonnet1m: false,
  declareOpus1m: false,
  declareFable1m: false,
  codexEnable1m: false,
  codexContextWindow: undefined,
  codexAutoCompactLimit: undefined,
  permissionMode: 'bypassPermissions',
};

export function isAnthropicProvider(provider: Pick<AiCliProviderRecord, 'apiKind' | 'baseUrl'>): boolean {
  return (provider.apiKind ?? 'anthropic') !== 'openai';
}

export function isProviderActiveForRole(
  provider: Pick<AiCliProviderRecord, 'activeClaude' | 'activeCodex' | 'apiKind' | 'baseUrl'>,
  role: 'claude' | 'codex'
): boolean {
  return role === 'claude' ? provider.activeClaude : provider.activeCodex;
}

const MODEL_ROLE_PATTERNS: Record<'sonnet' | 'opus' | 'fable' | 'haiku', RegExp> = {
  sonnet: /sonnet/i,
  opus: /opus/i,
  fable: /fable/i,
  haiku: /haiku/i,
};

function findModelIdByRole(
  models: ClaudeModelOption[],
  role: 'sonnet' | 'opus' | 'fable' | 'haiku'
): string | undefined {
  const pattern = MODEL_ROLE_PATTERNS[role];
  return models.find((m) => pattern.test(m.id) || (m.label ? pattern.test(m.label) : false))?.id;
}

export type ClaudeRoleModelMapping = {
  model: string;
  sonnetModel: string;
  opusModel: string;
  fableModel: string;
  haikuModel: string;
};

export function autoMapClaudeRoleModels(
  models: ClaudeModelOption[],
  current: Partial<Pick<AiCliProviderRecord, 'model' | 'sonnetModel' | 'opusModel' | 'fableModel' | 'haikuModel'>>
): ClaudeRoleModelMapping {
  const sonnet = findModelIdByRole(models, 'sonnet');
  const opus = findModelIdByRole(models, 'opus');
  const fable = findModelIdByRole(models, 'fable');
  const haiku = findModelIdByRole(models, 'haiku');
  const fallback = sonnet ?? opus ?? models[0]?.id ?? '';
  return {
    model: current.model?.trim() ? current.model : fallback,
    sonnetModel: current.sonnetModel?.trim() ? current.sonnetModel : (sonnet ?? fallback),
    opusModel: current.opusModel?.trim() ? current.opusModel : (opus ?? fallback),
    fableModel: current.fableModel?.trim()
      ? current.fableModel
      : (fable ?? opus ?? fallback),
    haikuModel: current.haikuModel?.trim() ? current.haikuModel : (haiku ?? fallback),
  };
}
