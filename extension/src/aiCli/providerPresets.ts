import type { AiCliApiKind } from './officialEndpoints';
import {
  OFFICIAL_ANTHROPIC_BASE_URL,
  OFFICIAL_OPENAI_BASE_URL,
  isOfficialOpenAiBaseUrl,
} from './officialEndpoints';

/** How Codex should talk to this OpenAI-compatible endpoint. */
export type CodexWireHint = 'openai_responses' | 'openai_chat';

export type AiCliProviderPreset = {
  id: string;
  url: string;
  apiKind: AiCliApiKind;
  official?: boolean;
  /** Coding Plan / Token Plan / Agent Plan style subscription endpoint. */
  planKind?: 'coding' | 'token' | 'agent';
  /** Codex: prefer Chat Completions bridge vs native Responses. */
  codexWire?: CodexWireHint;
  roles: Array<'claude' | 'codex'>;
};

/**
 * Built-in dropdown presets (aligned with cc-switch cn_official / official set).
 * These do not auto-create cards — they only fill Base URL and protocol when selected.
 * Fiblab still comes from Web import. Partner aggregators are intentionally omitted.
 */
export const CLAUDE_PROVIDER_PRESETS: AiCliProviderPreset[] = [
  { id: 'anthropic', url: OFFICIAL_ANTHROPIC_BASE_URL, apiKind: 'anthropic', official: true, roles: ['claude'] },
  {
    id: 'deepseek',
    url: 'https://api.deepseek.com/anthropic',
    apiKind: 'anthropic',
    roles: ['claude'],
  },
  {
    id: 'volcengine',
    url: 'https://ark.cn-beijing.volces.com/api/coding',
    apiKind: 'anthropic',
    planKind: 'agent',
    roles: ['claude'],
  },
  {
    id: 'byteplus',
    url: 'https://ark.ap-southeast.bytepluses.com/api/coding',
    apiKind: 'anthropic',
    planKind: 'agent',
    roles: ['claude'],
  },
  {
    id: 'doubaoSeed',
    url: 'https://ark.cn-beijing.volces.com/api/compatible',
    apiKind: 'anthropic',
    roles: ['claude'],
  },
  {
    id: 'mimo',
    url: 'https://api.xiaomimimo.com/anthropic',
    apiKind: 'anthropic',
    roles: ['claude'],
  },
  {
    id: 'mimoTokenPlan',
    url: 'https://token-plan-cn.xiaomimimo.com/anthropic',
    apiKind: 'anthropic',
    planKind: 'token',
    roles: ['claude'],
  },
  {
    id: 'longcat',
    url: 'https://api.longcat.chat/anthropic',
    apiKind: 'anthropic',
    roles: ['claude'],
  },
  {
    id: 'bigmodel',
    url: 'https://open.bigmodel.cn/api/anthropic',
    apiKind: 'anthropic',
    planKind: 'coding',
    roles: ['claude'],
  },
  {
    id: 'zhipuEn',
    url: 'https://api.z.ai/api/anthropic',
    apiKind: 'anthropic',
    planKind: 'coding',
    roles: ['claude'],
  },
  {
    id: 'kimi',
    url: 'https://api.kimi.com/coding/',
    apiKind: 'anthropic',
    planKind: 'coding',
    roles: ['claude'],
  },
  {
    id: 'moonshot',
    url: 'https://api.moonshot.cn/anthropic',
    apiKind: 'anthropic',
    roles: ['claude'],
  },
  {
    id: 'minimax',
    url: 'https://api.minimaxi.com/anthropic',
    apiKind: 'anthropic',
    planKind: 'coding',
    roles: ['claude'],
  },
  {
    id: 'minimaxEn',
    url: 'https://api.minimax.io/anthropic',
    apiKind: 'anthropic',
    planKind: 'coding',
    roles: ['claude'],
  },
  {
    id: 'bailian',
    url: 'https://dashscope.aliyuncs.com/apps/anthropic',
    apiKind: 'anthropic',
    roles: ['claude'],
  },
  {
    id: 'bailianCoding',
    url: 'https://coding.dashscope.aliyuncs.com/apps/anthropic',
    apiKind: 'anthropic',
    planKind: 'coding',
    roles: ['claude'],
  },
  {
    id: 'stepfunClaude',
    url: 'https://api.stepfun.com/step_plan',
    apiKind: 'anthropic',
    planKind: 'token',
    roles: ['claude'],
  },
  {
    id: 'stepfunClaudeEn',
    url: 'https://api.stepfun.ai/step_plan',
    apiKind: 'anthropic',
    planKind: 'token',
    roles: ['claude'],
  },
  {
    id: 'bailing',
    url: 'https://api.tbox.cn/api/anthropic',
    apiKind: 'anthropic',
    roles: ['claude'],
  },
  {
    id: 'qianfan',
    url: 'https://qianfan.baidubce.com/anthropic/coding',
    apiKind: 'anthropic',
    planKind: 'coding',
    roles: ['claude'],
  },
  {
    id: 'xaiClaude',
    url: 'https://api.x.ai/v1',
    apiKind: 'anthropic',
    roles: ['claude'],
  },
  {
    id: 'openrouter',
    url: 'https://openrouter.ai/api',
    apiKind: 'anthropic',
    roles: ['claude'],
  },
];

export const CODEX_PROVIDER_PRESETS: AiCliProviderPreset[] = [
  { id: 'openai', url: OFFICIAL_OPENAI_BASE_URL, apiKind: 'openai', official: true, roles: ['codex'], codexWire: 'openai_responses' },
  {
    id: 'xaiCodex',
    url: 'https://api.x.ai/v1',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_responses',
  },
  {
    id: 'mimoCodex',
    url: 'https://api.xiaomimimo.com/v1',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_responses',
  },
  {
    id: 'mimoTokenPlanCodex',
    url: 'https://token-plan-cn.xiaomimimo.com/v1',
    apiKind: 'openai',
    planKind: 'token',
    roles: ['codex'],
    codexWire: 'openai_responses',
  },
  {
    id: 'longcatCodex',
    url: 'https://api.longcat.chat/openai/v1',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_responses',
  },
  {
    id: 'zhipuCodex',
    url: 'https://open.bigmodel.cn/api/coding/paas/v4',
    apiKind: 'openai',
    planKind: 'coding',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'zhipuCodexEn',
    url: 'https://api.z.ai/api/coding/paas/v4',
    apiKind: 'openai',
    planKind: 'coding',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'kimiCodex',
    url: 'https://api.kimi.com/coding/v1',
    apiKind: 'openai',
    planKind: 'coding',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'moonshotCodex',
    url: 'https://api.moonshot.cn/v1',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'minimaxOpenAi',
    url: 'https://api.minimaxi.com/v1',
    apiKind: 'openai',
    planKind: 'coding',
    roles: ['codex'],
    // MiniMax official /v1/responses — native Responses (cc-switch).
    codexWire: 'openai_responses',
  },
  {
    id: 'minimaxOpenAiEn',
    url: 'https://api.minimax.io/v1',
    apiKind: 'openai',
    planKind: 'coding',
    roles: ['codex'],
    codexWire: 'openai_responses',
  },
  {
    id: 'deepseekOpenAi',
    url: 'https://api.deepseek.com',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_responses',
  },
  {
    id: 'volcengineAgentplanCodex',
    url: 'https://ark.cn-beijing.volces.com/api/coding/v3',
    apiKind: 'openai',
    planKind: 'agent',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'byteplusCodex',
    url: 'https://ark.ap-southeast.bytepluses.com/api/coding/v3',
    apiKind: 'openai',
    planKind: 'agent',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'doubaoSeedCodex',
    url: 'https://ark.cn-beijing.volces.com/api/v3',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_responses',
  },
  {
    id: 'siliconflow',
    url: 'https://api.siliconflow.cn/v1',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'bailianCodex',
    url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_responses',
  },
  {
    id: 'stepfun',
    url: 'https://api.stepfun.com/step_plan/v1',
    apiKind: 'openai',
    planKind: 'token',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'stepfunEn',
    url: 'https://api.stepfun.ai/step_plan/v1',
    apiKind: 'openai',
    planKind: 'token',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'qianfanCodex',
    url: 'https://qianfan.baidubce.com/v2/coding',
    apiKind: 'openai',
    planKind: 'coding',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'bailingCodex',
    url: 'https://api.tbox.cn/api/llm/v1',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
  {
    id: 'openrouterOpenAi',
    url: 'https://openrouter.ai/api/v1',
    apiKind: 'openai',
    roles: ['codex'],
    codexWire: 'openai_chat',
  },
];

const ALL_PRESETS: AiCliProviderPreset[] = [...CLAUDE_PROVIDER_PRESETS, ...CODEX_PROVIDER_PRESETS];

export function getProviderPresetsForRole(role: 'claude' | 'codex'): AiCliProviderPreset[] {
  return role === 'claude' ? CLAUDE_PROVIDER_PRESETS : CODEX_PROVIDER_PRESETS;
}

export function findPresetByUrl(baseUrl: string, apiKind?: AiCliApiKind): AiCliProviderPreset | undefined {
  const normalized = baseUrl.trim().replace(/\/+$/, '');
  return ALL_PRESETS.find((preset) => preset.url.replace(/\/+$/, '') === normalized && (!apiKind || preset.apiKind === apiKind));
}

export function findPresetById(id: string): AiCliProviderPreset | undefined {
  return ALL_PRESETS.find((preset) => preset.id === id);
}

/** Hosts that natively speak OpenAI Responses (Codex can skip Chat bridge). */
const NATIVE_RESPONSES_HOST_MARKERS = [
  'api.openai.com',
  'api.deepseek.com',
  'api.longcat.chat',
  'api.xiaomimimo.com',
  'token-plan-cn.xiaomimimo.com',
  'token-plan.xiaomimimo.com',
  'dashscope.aliyuncs.com',
  'api.x.ai',
];

export function inferCodexWireFromBaseUrl(baseUrl: string): CodexWireHint {
  const preset = findPresetByUrl(baseUrl);
  if (preset?.codexWire) {
    return preset.codexWire;
  }
  if (isOfficialOpenAiBaseUrl(baseUrl)) {
    return 'openai_responses';
  }
  try {
    const host = new URL(baseUrl.trim()).hostname.toLowerCase();
    if (NATIVE_RESPONSES_HOST_MARKERS.some((marker) => host === marker || host.endsWith(`.${marker}`))) {
      return 'openai_responses';
    }
  } catch {
    /* fall through */
  }
  return 'openai_chat';
}
