import type { ConfigValues, ValidationState } from './types';

export const ADVANCED_VALIDATION_KEYS = [
  'coder',
  'embedding',
  'python',
  'literature',
] as const;

export type AdvancedValidationKey = (typeof ADVANCED_VALIDATION_KEYS)[number];

export type AdvancedItemVisualStatus = 'idle' | 'validating' | 'ok' | 'error' | 'blocked';

export function getAdvancedItemVisualStatus(
  state: ValidationState | undefined,
  blockedReason: string | null
): AdvancedItemVisualStatus {
  if (state?.validating) {
    return 'validating';
  }
  if (state?.valid === true) {
    return 'ok';
  }
  if (state?.valid === false) {
    return 'error';
  }
  if (blockedReason) {
    return 'blocked';
  }
  return 'idle';
}

export function getAdvancedKeyFingerprint(
  key: AdvancedValidationKey,
  env: Partial<ConfigValues>
): string {
  const inherit = { llmApiKey: env.llmApiKey, llmApiBase: env.llmApiBase };
  switch (key) {
    case 'coder':
      return JSON.stringify({
        inherit,
        coderLlmApiKey: env.coderLlmApiKey,
        coderLlmApiBase: env.coderLlmApiBase,
        coderLlmModel: env.coderLlmModel,
        apiType: env.coderLlmApiType || env.llmApiType || 'openai',
        thinking: env.coderLlmThinking || env.llmThinking || '',
        thinkingFormat: env.coderLlmThinkingFormat || env.llmThinkingFormat || '',
      });
    case 'embedding':
      return JSON.stringify({
        inherit,
        embeddingApiKey: env.embeddingApiKey,
        embeddingApiBase: env.embeddingApiBase,
        embeddingModel: env.embeddingModel,
        embeddingDims: env.embeddingDims,
      });
    case 'python':
      return JSON.stringify({ pythonPath: env.pythonPath });
    case 'literature':
      return JSON.stringify({
        literatureSearchMcpUrl: env.literatureSearchMcpUrl,
        literatureSearchApiKey: env.literatureSearchApiKey,
      });
  }
}

export function getAdvancedValidationLabel(
  key: AdvancedValidationKey,
  t: (key: string) => string
): string {
  switch (key) {
    case 'coder':
      return t('configPage.coder.shortTitle');
    case 'embedding':
      return t('configPage.advanced.embedding.shortTitle');
    case 'python':
      return t('configPage.python.title');
    case 'literature':
      return t('configPage.literature.title');
  }
}

export function getClaudeConfigVisualStatus(
  blockedReason: string | null
): AdvancedItemVisualStatus {
  return blockedReason ? 'idle' : 'ok';
}

export function statusColor(
  status: AdvancedItemVisualStatus,
  palette: {
    successForeground: string;
    errorForeground: string;
    warningForeground: string;
    descriptionForeground: string;
    linkForeground: string;
  }
): string {
  switch (status) {
    case 'ok':
      return palette.successForeground;
    case 'error':
      return palette.errorForeground;
    case 'blocked':
      return palette.warningForeground;
    case 'validating':
      return palette.linkForeground;
    default:
      return palette.descriptionForeground;
  }
}
