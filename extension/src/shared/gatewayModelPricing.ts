export type ModelPrice = {
  inputPerMillion: number;
  outputPerMillion: number;
  cacheReadPerMillion?: number;
  /** Standard/30-minute cache-write price when the provider exposes cache writes. */
  cacheCreationPerMillion?: number;
  /** Extended 1-hour/12-hour cache-write price. */
  cacheCreationLongPerMillion?: number;
};

export type ModelPricingMap = Record<string, ModelPrice>;

const BUILTIN_PRICING: ModelPricingMap = {
  'claude-sonnet-5.5': { inputPerMillion: 2, outputPerMillion: 10, cacheReadPerMillion: 0.1, cacheCreationPerMillion: 2.5, cacheCreationLongPerMillion: 4 },
  'claude-sonnet-5': { inputPerMillion: 2, outputPerMillion: 10, cacheReadPerMillion: 0.2, cacheCreationPerMillion: 2.5, cacheCreationLongPerMillion: 4 },
  'claude-opus-5.5': { inputPerMillion: 4, outputPerMillion: 20, cacheReadPerMillion: 0.2, cacheCreationPerMillion: 5, cacheCreationLongPerMillion: 8 },
  'claude-opus-5': { inputPerMillion: 5, outputPerMillion: 25, cacheReadPerMillion: 0.5, cacheCreationPerMillion: 6.25, cacheCreationLongPerMillion: 10 },
  'claude-opus-4.8': { inputPerMillion: 5, outputPerMillion: 25, cacheReadPerMillion: 0.5, cacheCreationPerMillion: 6.25 },
  'claude-opus-4.7': { inputPerMillion: 5, outputPerMillion: 25, cacheReadPerMillion: 0.5, cacheCreationPerMillion: 6.25 },
  'claude-opus-4-6': { inputPerMillion: 5, outputPerMillion: 25, cacheReadPerMillion: 0.5, cacheCreationPerMillion: 6.25, cacheCreationLongPerMillion: 10 },
  'claude-sonnet-4-6': { inputPerMillion: 3, outputPerMillion: 15, cacheReadPerMillion: 0.3, cacheCreationPerMillion: 3.75, cacheCreationLongPerMillion: 6 },
  'claude-sonnet-4-5': { inputPerMillion: 3, outputPerMillion: 15, cacheReadPerMillion: 0.3, cacheCreationPerMillion: 3.75 },
  'claude-sonnet-4': { inputPerMillion: 3, outputPerMillion: 15, cacheReadPerMillion: 0.3, cacheCreationPerMillion: 3.75 },
  'claude-haiku-4-5': { inputPerMillion: 1, outputPerMillion: 5, cacheReadPerMillion: 0.1, cacheCreationPerMillion: 1.25 },
  'claude-opus-4-5': { inputPerMillion: 5, outputPerMillion: 25, cacheReadPerMillion: 0.5, cacheCreationPerMillion: 6.25 },
  'claude-opus-4': { inputPerMillion: 15, outputPerMillion: 75, cacheReadPerMillion: 1.5, cacheCreationPerMillion: 18.75 },
  'claude-3-7-sonnet': { inputPerMillion: 3, outputPerMillion: 15, cacheReadPerMillion: 0.3, cacheCreationPerMillion: 3.75 },
  'claude-3-5-sonnet': { inputPerMillion: 3, outputPerMillion: 15, cacheReadPerMillion: 0.3, cacheCreationPerMillion: 3.75 },
  'claude-3-5-haiku': { inputPerMillion: 0.8, outputPerMillion: 4, cacheReadPerMillion: 0.08, cacheCreationPerMillion: 1 },
  'claude-3-opus': { inputPerMillion: 15, outputPerMillion: 75, cacheReadPerMillion: 1.5, cacheCreationPerMillion: 18.75 },
  'claude-3-haiku': { inputPerMillion: 0.25, outputPerMillion: 1.25, cacheReadPerMillion: 0.03, cacheCreationPerMillion: 0.3 },
  'gpt-6-astra': { inputPerMillion: 10, outputPerMillion: 50, cacheReadPerMillion: 1, cacheCreationPerMillion: 12.5, cacheCreationLongPerMillion: 25 },
  'gpt-6.1-sol': { inputPerMillion: 2, outputPerMillion: 10, cacheReadPerMillion: 0.1, cacheCreationPerMillion: 2.5, cacheCreationLongPerMillion: 5 },
  'gpt-6.1-terra': { inputPerMillion: 1, outputPerMillion: 5, cacheReadPerMillion: 0.05, cacheCreationPerMillion: 1.25, cacheCreationLongPerMillion: 2.5 },
  'gpt-6-sol': { inputPerMillion: 2, outputPerMillion: 10, cacheReadPerMillion: 0.2, cacheCreationPerMillion: 2.5 },
  'gpt-6-luna': { inputPerMillion: 0.1, outputPerMillion: 0.5, cacheReadPerMillion: 0.01, cacheCreationPerMillion: 0.125, cacheCreationLongPerMillion: 0.25 },
  'gpt-5.6': { inputPerMillion: 4, outputPerMillion: 20, cacheReadPerMillion: 0.4, cacheCreationPerMillion: 5, cacheCreationLongPerMillion: 10 },
  'gpt-5.6-sol': { inputPerMillion: 4, outputPerMillion: 20, cacheReadPerMillion: 0.4, cacheCreationPerMillion: 5, cacheCreationLongPerMillion: 10 },
  'gpt-5.6-cyber': { inputPerMillion: 12.5, outputPerMillion: 75, cacheReadPerMillion: 1.25, cacheCreationPerMillion: 15.625, cacheCreationLongPerMillion: 31.25 },
  'gpt-5.5': { inputPerMillion: 5, outputPerMillion: 30, cacheReadPerMillion: 0.5 },
  'gpt-5.5-pro': { inputPerMillion: 30, outputPerMillion: 180 },
  'gpt-5.5-codex': { inputPerMillion: 3.5, outputPerMillion: 28, cacheReadPerMillion: 0.35 },
  'gpt-5.4': { inputPerMillion: 2.5, outputPerMillion: 15, cacheReadPerMillion: 0.25 },
  'gpt-5.4-pro': { inputPerMillion: 30, outputPerMillion: 180 },
  'gpt-5.3-codex': { inputPerMillion: 1.75, outputPerMillion: 14, cacheReadPerMillion: 0.175 },
  'gpt-5-codex': { inputPerMillion: 1.25, outputPerMillion: 10, cacheReadPerMillion: 0.125 },
  'gpt-5': { inputPerMillion: 1.25, outputPerMillion: 10, cacheReadPerMillion: 0.125 },
  'gpt-4o': { inputPerMillion: 2.5, outputPerMillion: 10, cacheReadPerMillion: 1.25 },
  'gpt-4o-mini': { inputPerMillion: 0.15, outputPerMillion: 0.6, cacheReadPerMillion: 0.075 },
  'gpt-4.1': { inputPerMillion: 2, outputPerMillion: 8, cacheReadPerMillion: 0.5 },
  'gpt-4.1-mini': { inputPerMillion: 0.4, outputPerMillion: 1.6, cacheReadPerMillion: 0.1 },
  'gpt-4.1-nano': { inputPerMillion: 0.1, outputPerMillion: 0.4, cacheReadPerMillion: 0.025 },
  'o3': { inputPerMillion: 2, outputPerMillion: 8, cacheReadPerMillion: 0.5 },
  'o3-mini': { inputPerMillion: 1.1, outputPerMillion: 4.4, cacheReadPerMillion: 0.55 },
  'o4-mini': { inputPerMillion: 1.1, outputPerMillion: 4.4, cacheReadPerMillion: 0.275 },
  'deepseek-chat': { inputPerMillion: 0.28, outputPerMillion: 0.42, cacheReadPerMillion: 0.028 },
  'deepseek-v4-pro': { inputPerMillion: 0.55, outputPerMillion: 2.19, cacheReadPerMillion: 0.14 },
  'deepseek-r2': { inputPerMillion: 0.55, outputPerMillion: 2.19, cacheReadPerMillion: 0.14 },
  'deepseek-reasoner': { inputPerMillion: 0.55, outputPerMillion: 2.19, cacheReadPerMillion: 0.14 },
  'gemini-2.5-pro': { inputPerMillion: 1.25, outputPerMillion: 10, cacheReadPerMillion: 0.125 },
  'gemini-2.5-flash': { inputPerMillion: 0.15, outputPerMillion: 0.6, cacheReadPerMillion: 0.04 },
  'gemini-2.0-flash': { inputPerMillion: 0.1, outputPerMillion: 0.4, cacheReadPerMillion: 0.025 },
  'glm-5.2': { inputPerMillion: 0.14, outputPerMillion: 0.56 },
  'glm-5.1': { inputPerMillion: 0.14, outputPerMillion: 0.56 },
  'qwen-plus': { inputPerMillion: 0.57, outputPerMillion: 2.28 },
  'qwen-turbo': { inputPerMillion: 0.11, outputPerMillion: 0.44 },
  'MiniMax-M3': { inputPerMillion: 0.30, outputPerMillion: 1.20 },
  'kimi-k2.7-code': { inputPerMillion: 0.55, outputPerMillion: 2.19 },
  'kimi-for-coding': { inputPerMillion: 0.55, outputPerMillion: 2.19 },
  'step-3.7-flash': { inputPerMillion: 0.57, outputPerMillion: 2.28 },
  'Pro/deepseek-ai/DeepSeek-V4': { inputPerMillion: 0.28, outputPerMillion: 0.42 },
};

function normalizeModelId(modelId: string): string {
  let id = modelId.trim();
  const lastSlash = id.lastIndexOf('/');
  if (lastSlash >= 0) {
    id = id.slice(lastSlash + 1);
  }
  const colonIdx = id.indexOf(':');
  if (colonIdx >= 0) {
    id = id.slice(0, colonIdx);
  }
  return id
    .replace(/@/g, '-')
    .toLowerCase()
    .replace(/\[1m\]$/, '')
    .replace(/-(?:19|20)\d{2}-\d{2}-\d{2}$/, '')
    .replace(/-(?:19|20)\d{6}$/, '');
}

function isValidPrice(price: ModelPrice): boolean {
  return [price.inputPerMillion, price.outputPerMillion, price.cacheReadPerMillion, price.cacheCreationPerMillion, price.cacheCreationLongPerMillion]
    .every((value) => value === undefined || (Number.isFinite(value) && value >= 0));
}

export function getModelPrice(modelId: string, customPricing?: ModelPricingMap): ModelPrice | null {
  const normalized = normalizeModelId(modelId);
  for (const pricing of [customPricing, BUILTIN_PRICING]) {
    if (!pricing) {
      continue;
    }
    for (const [key, price] of Object.entries(pricing)) {
      if (normalizeModelId(key) === normalized && isValidPrice(price)) {
        return price;
      }
    }
  }
  return null;
}

function safeTokenCount(value: number): number {
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

export function calculateCost(
  modelId: string,
  inputTokens: number,
  outputTokens: number,
  cacheReadTokens: number,
  cacheCreationTokens: number,
  customPricing?: ModelPricingMap,
  options?: { app?: 'claude' | 'codex'; reportedCostUsd?: number; cacheCreationLongTokens?: number }
): { total: number; input: number; output: number; cacheRead: number; cacheCreation: number } | null {
  if (
    options?.reportedCostUsd !== undefined &&
    Number.isFinite(options.reportedCostUsd) &&
    options.reportedCostUsd >= 0
  ) {
    return { total: options.reportedCostUsd, input: 0, output: 0, cacheRead: 0, cacheCreation: 0 };
  }
  const price = getModelPrice(modelId, customPricing);
  if (!price) {
    return null;
  }
  const input = (safeTokenCount(inputTokens) / 1_000_000) * price.inputPerMillion;
  const output = (safeTokenCount(outputTokens) / 1_000_000) * price.outputPerMillion;
  const cacheRead = price.cacheReadPerMillion === undefined
    ? 0
    : (safeTokenCount(cacheReadTokens) / 1_000_000) * price.cacheReadPerMillion;
  const longCreationTokens = Math.min(
    safeTokenCount(cacheCreationTokens),
    safeTokenCount(options?.cacheCreationLongTokens ?? 0)
  );
  const standardCreationTokens = safeTokenCount(cacheCreationTokens) - longCreationTokens;
  const cacheCreation = price.cacheCreationPerMillion === undefined
    ? 0
    : (standardCreationTokens / 1_000_000) * price.cacheCreationPerMillion +
      (longCreationTokens / 1_000_000) *
        (price.cacheCreationLongPerMillion ??
          (normalizeModelId(modelId).startsWith('claude-')
            ? price.inputPerMillion * 2
            : price.cacheCreationPerMillion));
  return { total: input + output + cacheRead + cacheCreation, input, output, cacheRead, cacheCreation };
}

export function formatCost(cost: number): string {
  if (cost < 0.01) {
    return '<$0.01';
  }
  return `$${cost.toFixed(2)}`;
}

export function getBuiltinPricing(): ModelPricingMap {
  return { ...BUILTIN_PRICING };
}
