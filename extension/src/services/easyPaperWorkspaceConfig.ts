import * as fs from 'fs';
import * as yaml from 'js-yaml';
import writeFileAtomic from 'write-file-atomic';
import type { EasyPaperConfigValues } from '../webview/configPage/types';

interface AgentConfig {
  name: string;
  model?: Record<string, unknown>;
  vlm_review_config?: Record<string, unknown>;
  [key: string]: unknown;
}

interface PaperConfig {
  agents?: AgentConfig[];
  vlm_service?: Record<string, unknown>;
  [key: string]: unknown;
}

function readDocument(configPath: string): PaperConfig {
  const data = yaml.load(fs.readFileSync(configPath, 'utf-8'));
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('EasyPaper config must be a YAML mapping.');
  }
  const document = data as PaperConfig;
  if (document.agents !== undefined && (!Array.isArray(document.agents) || document.agents.some(
    (agent) => !agent || typeof agent !== 'object' || typeof agent.name !== 'string'
  ))) {
    throw new Error('EasyPaper agents must be a list of named agent configurations.');
  }
  return document;
}

export function readEasyPaperConfig(configPath: string): EasyPaperConfigValues | undefined {
  if (!fs.existsSync(configPath)) {
    return undefined;
  }
  const data = readDocument(configPath);
  const model = data.agents?.find((agent) => !agent.vlm_review_config && agent.model)?.model;
  const vlm = data.vlm_service;
  return {
    llmModelName: String(model?.model_name ?? ''),
    llmApiKey: String(model?.api_key ?? ''),
    llmBaseUrl: String(model?.base_url ?? ''),
    vlmEnabled: vlm?.enabled !== false && Boolean(vlm?.model),
    vlmProvider: String(vlm?.provider ?? 'openai'),
    vlmModel: String(vlm?.model ?? ''),
    vlmApiKey: String(vlm?.api_key ?? ''),
    vlmBaseUrl: String(vlm?.base_url ?? ''),
  };
}

export function writeEasyPaperConfig(configPath: string, config: EasyPaperConfigValues, templatePath: string): void {
  const model = {
    model_name: config.llmModelName?.trim(),
    api_key: config.llmApiKey?.trim(),
    base_url: config.llmBaseUrl?.trim(),
  };
  if (!model.model_name || !model.api_key || !model.base_url) {
    throw new Error('EasyPaper requires an LLM model, API key and Base URL.');
  }
  if (config.vlmEnabled && (!config.vlmModel?.trim() || !config.vlmApiKey?.trim() || !config.vlmBaseUrl?.trim())) {
    throw new Error('Enabled VLM requires a vision model, API key and Base URL.');
  }
  if (!['openai', 'claude', 'qwen'].includes(config.vlmProvider)) {
    throw new Error('Unsupported EasyPaper VLM provider.');
  }
  const template = readDocument(templatePath);
  const document = fs.existsSync(configPath) ? readDocument(configPath) : template;
  const agents = document.agents ?? [];
  for (const agentTemplate of template.agents ?? []) {
    if (!agentTemplate.model) { continue; }
    let agent = agents.find((entry) => entry.name === agentTemplate.name);
    if (!agent) {
      agent = { ...agentTemplate };
      agents.push(agent);
    }
    agent.model = { ...agent.model, ...model };
  }
  let review = agents.find((agent) => agent.name === 'vlm_review');
  if (!review) {
    review = { name: 'vlm_review' };
    agents.push(review);
  }
  review.vlm_review_config = { ...review.vlm_review_config, enabled: config.vlmEnabled };
  document.agents = agents;
  document.vlm_service = {
    ...document.vlm_service,
    enabled: config.vlmEnabled,
    provider: config.vlmProvider,
    model: config.vlmModel?.trim() || '',
    api_key: config.vlmApiKey?.trim() || '',
    base_url: config.vlmBaseUrl?.trim() || '',
  };
  writeFileAtomic.sync(configPath, yaml.dump(document, { lineWidth: 120, noRefs: true }), {
    encoding: 'utf8', mode: 0o600,
  });
}
