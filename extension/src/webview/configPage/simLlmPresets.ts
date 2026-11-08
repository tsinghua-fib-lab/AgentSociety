export type SimLlmPreset = {
  id: string;
  labelKey: string;
  hintKey?: string;
  baseUrl: string;
};

export const SIM_LLM_PRESETS: SimLlmPreset[] = [
  {
    id: 'openai',
    labelKey: 'configPage.llm.presetOpenai',
    baseUrl: 'https://api.openai.com/v1',
  },
  {
    id: 'fiblab',
    labelKey: 'configPage.llm.presetFiblab',
    hintKey: 'configPage.llm.presetFiblabHint',
    baseUrl: 'https://llmapi.fiblab.net/v1',
  },
  {
    id: 'deepseek',
    labelKey: 'configPage.llm.presetDeepseek',
    baseUrl: 'https://api.deepseek.com',
  },
  {
    id: 'bailian',
    labelKey: 'configPage.llm.presetBailian',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    hintKey: 'configPage.llm.presetBailianHint',
  },
  {
    id: 'zhipu',
    labelKey: 'configPage.llm.presetZhipu',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
  },
  {
    id: 'moonshot',
    labelKey: 'configPage.llm.presetMoonshot',
    baseUrl: 'https://api.moonshot.cn/v1',
  },
  {
    id: 'minimax',
    labelKey: 'configPage.llm.presetMinimax',
    baseUrl: 'https://api.minimaxi.com/v1',
  },
  {
    id: 'siliconflow',
    labelKey: 'configPage.llm.presetSiliconflow',
    baseUrl: 'https://api.siliconflow.cn/v1',
  },
  {
    id: 'openrouter',
    labelKey: 'configPage.llm.presetOpenrouter',
    baseUrl: 'https://openrouter.ai/api/v1',
  },
  {
    id: 'custom',
    labelKey: 'configPage.llm.presetCustom',
    baseUrl: '',
  },
];

export function matchSimLlmPreset(baseUrl: string | undefined): string {
  const normalized = (baseUrl ?? '').trim().replace(/\/+$/, '');
  if (!normalized) {
    return 'custom';
  }
  const hit = SIM_LLM_PRESETS.find((p) => {
    if (p.id === 'custom') {
      return false;
    }
    const presetBase = p.baseUrl.replace(/\/+$/, '');
    return (
      presetBase === normalized ||
      presetBase === `${normalized}/v1` ||
      `${presetBase}/v1` === normalized
    );
  });
  return hit?.id ?? 'custom';
}
