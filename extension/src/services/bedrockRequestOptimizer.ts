/**
 * Bedrock PRE-SEND optimizer (aligned with cc-switch).
 * Only applied when the upstream looks like AWS Bedrock.
 */

export type GatewayOptimizerSettings = {
  enabled: boolean;
  thinkingOptimizer: boolean;
  cacheInjection: boolean;
};

export const DEFAULT_GATEWAY_OPTIMIZER_SETTINGS: GatewayOptimizerSettings = {
  enabled: false,
  thinkingOptimizer: true,
  cacheInjection: true,
};

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function isBedrockUpstreamBaseUrl(baseUrl: string): boolean {
  const lower = baseUrl.trim().toLowerCase();
  return lower.includes('bedrock') || lower.includes('bedrock-runtime');
}

function normalizeModelName(model: string): string {
  return model.trim().toLowerCase().replace(/[._]/g, '-');
}

export function usesAdaptiveThinking(model: string): boolean {
  const normalized = normalizeModelName(model);
  return [
    'fable-5',
    'mythos-5',
    'mythos-preview',
    'sonnet-5',
    'opus-4-8',
    'opus-4-7',
    'opus-4-6',
    'sonnet-4-6',
  ].some((needle) => normalized.includes(needle));
}

function appendBeta(body: Record<string, unknown>, beta: string): void {
  const existing = body.anthropic_beta;
  if (Array.isArray(existing)) {
    if (existing.some((item) => item === beta)) {
      return;
    }
    body.anthropic_beta = [...existing, beta];
    return;
  }
  body.anthropic_beta = [beta];
}

export function optimizeBedrockThinking(
  body: Record<string, unknown>,
  settings: GatewayOptimizerSettings
): Record<string, unknown> {
  if (!settings.enabled || !settings.thinkingOptimizer) {
    return body;
  }
  if (isObject(body.thinking) && body.thinking.type === 'disabled') { return body; }
  const model = typeof body.model === 'string' ? body.model : '';
  if (!model) {
    return body;
  }
  const lower = model.toLowerCase();
  if (lower.includes('haiku')) {
    return body;
  }

  const next: Record<string, unknown> = { ...body };
  if (usesAdaptiveThinking(model)) {
    next.thinking = { type: 'adaptive' };
    next.output_config = { effort: 'max' };
    appendBeta(next, 'context-1m-2025-08-07');
    return next;
  }

  const maxTokens = typeof next.max_tokens === 'number' ? next.max_tokens : 16_384;
  const budgetTarget = Math.max(0, maxTokens - 1);
  const thinkingType = isObject(next.thinking) ? next.thinking.type : undefined;

  if (thinkingType === undefined || thinkingType === 'disabled') {
    next.thinking = { type: 'enabled', budget_tokens: budgetTarget };
    appendBeta(next, 'interleaved-thinking-2025-05-14');
    return next;
  }

  if (thinkingType === 'enabled') {
    const thinking: Record<string, unknown> = isObject(next.thinking)
      ? { ...next.thinking }
      : { type: 'enabled' };
    const currentBudget = typeof thinking.budget_tokens === 'number' ? thinking.budget_tokens : 0;
    if (currentBudget < budgetTarget) {
      thinking.budget_tokens = budgetTarget;
    }
    next.thinking = thinking;
    appendBeta(next, 'interleaved-thinking-2025-05-14');
    return next;
  }

  appendBeta(next, 'interleaved-thinking-2025-05-14');
  return next;
}

function makeCacheControl(): Record<string, unknown> {
  return { type: 'ephemeral' };
}

function countExistingBreakpoints(body: Record<string, unknown>): number {
  let count = 0;
  if (Array.isArray(body.tools)) {
    count += body.tools.filter((tool) => isObject(tool) && tool.cache_control).length;
  }
  if (Array.isArray(body.system)) {
    count += body.system.filter((block) => isObject(block) && block.cache_control).length;
  }
  if (Array.isArray(body.messages)) {
    for (const message of body.messages) {
      if (!isObject(message) || !Array.isArray(message.content)) {
        continue;
      }
      count += message.content.filter((block) => isObject(block) && block.cache_control).length;
    }
  }
  return count;
}

function injectMessageBreakpoint(message: Record<string, unknown>): boolean {
  if (!Array.isArray(message.content)) {
    return false;
  }
  for (let i = message.content.length - 1; i >= 0; i -= 1) {
    const block = message.content[i];
    if (!isObject(block)) {
      continue;
    }
    if (block.type === 'thinking' || block.type === 'redacted_thinking') {
      continue;
    }
    if (block.cache_control) {
      return false;
    }
    message.content = message.content.map((item, index) =>
      index === i ? { ...block, cache_control: makeCacheControl() } : item
    );
    return true;
  }
  return false;
}

export function injectBedrockCacheBreakpoints(
  body: Record<string, unknown>,
  settings: GatewayOptimizerSettings
): Record<string, unknown> {
  if (!settings.enabled || !settings.cacheInjection) {
    return body;
  }

  const next: Record<string, unknown> = { ...body };
  const existing = countExistingBreakpoints(next);
  let budget = Math.max(0, 4 - existing);
  if (budget === 0) {
    return next;
  }

  if (budget > 0 && Array.isArray(next.tools) && next.tools.length > 0) {
    const tools = next.tools.map((tool) => (isObject(tool) ? { ...tool } : tool));
    const lastIndex = tools.length - 1;
    const last = tools[lastIndex];
    if (isObject(last) && !last.cache_control) {
      tools[lastIndex] = { ...last, cache_control: makeCacheControl() };
      next.tools = tools;
      budget -= 1;
    }
  }

  if (budget > 0) {
    if (typeof next.system === 'string') {
      next.system = [{ type: 'text', text: next.system }];
    }
    if (Array.isArray(next.system) && next.system.length > 0) {
      const system = next.system.map((block) => (isObject(block) ? { ...block } : block));
      const lastIndex = system.length - 1;
      const last = system[lastIndex];
      if (isObject(last) && !last.cache_control) {
        system[lastIndex] = { ...last, cache_control: makeCacheControl() };
        next.system = system;
        budget -= 1;
      }
    }
  }

  if (budget > 0 && Array.isArray(next.messages)) {
    const messages = next.messages.map((message) =>
      isObject(message)
        ? {
            ...message,
            content: Array.isArray(message.content)
              ? message.content.map((block) => (isObject(block) ? { ...block } : block))
              : message.content,
          }
        : message
    );

    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const message = messages[i];
      if (!isObject(message)) {
        continue;
      }
      if (injectMessageBreakpoint(message)) {
        budget -= 1;
        break;
      }
    }

    if (budget > 0 && messages.length >= 4) {
      let userCount = 0;
      for (let i = messages.length - 1; i >= 0; i -= 1) {
        const message = messages[i];
        if (!isObject(message) || message.role !== 'user') {
          continue;
        }
        userCount += 1;
        if (userCount === 2) {
          injectMessageBreakpoint(message);
          break;
        }
      }
    }

    next.messages = messages;
  }

  return next;
}

export function applyBedrockRequestOptimizer(
  body: Record<string, unknown>,
  settings: GatewayOptimizerSettings,
  upstreamBaseUrl: string
): Record<string, unknown> {
  if (!settings.enabled || !isBedrockUpstreamBaseUrl(upstreamBaseUrl)) {
    return body;
  }
  let next = optimizeBedrockThinking(body, settings);
  next = injectBedrockCacheBreakpoints(next, settings);
  return next;
}
