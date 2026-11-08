export const ENV_LLM_SLOT = {
  default: '__env_default__',
  coder: '__env_coder__',
  embedding: '__env_embedding__',
  easyPaperLlm: '__easypaper_llm__',
  easyPaperVlm: '__easypaper_vlm__',
} as const;

export type EnvLlmSlot = keyof typeof ENV_LLM_SLOT;
