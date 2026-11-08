import * as vscode from 'vscode';
import { DEFAULT_ENV_CONFIG, type EnvConfig, EnvManager } from './envManager';

const LEGACY_ENV_SETTING_MAP: Array<{
  settingKey: string;
  envKey: keyof EnvConfig;
}> = [
    { settingKey: 'env.backendHost', envKey: 'backendHost' },
    { settingKey: 'env.backendPort', envKey: 'backendPort' },
    { settingKey: 'env.backendLogLevel', envKey: 'backendLogLevel' },
    { settingKey: 'backend.pythonPath', envKey: 'pythonPath' },
    { settingKey: 'env.llmApiKey', envKey: 'llmApiKey' },
    { settingKey: 'env.llmApiBase', envKey: 'llmApiBase' },
    { settingKey: 'env.llmModel', envKey: 'llmModel' },
    { settingKey: 'env.coderLlmApiKey', envKey: 'coderLlmApiKey' },
    { settingKey: 'env.coderLlmApiBase', envKey: 'coderLlmApiBase' },
    { settingKey: 'env.coderLlmModel', envKey: 'coderLlmModel' },
    { settingKey: 'env.embeddingApiKey', envKey: 'embeddingApiKey' },
    { settingKey: 'env.embeddingApiBase', envKey: 'embeddingApiBase' },
    { settingKey: 'env.embeddingModel', envKey: 'embeddingModel' },
    { settingKey: 'env.embeddingDims', envKey: 'embeddingDims' },
    { settingKey: 'env.literatureSearchMcpUrl', envKey: 'literatureSearchMcpUrl' },
  ];

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function normalizeBackendAccessHost(host?: string): string {
  const normalized = host?.trim();
  if (!normalized || normalized === '0.0.0.0' || normalized === '::' || normalized === '[::]') {
    return '127.0.0.1';
  }
  return normalized;
}

export function readWorkspaceEnvConfig(): EnvConfig {
  return new EnvManager().readEnv();
}

export function getBackendBindHost(config?: Partial<EnvConfig>): string {
  const host = config?.backendHost;
  if (isNonEmptyString(host)) {
    return host.trim();
  }
  return String(DEFAULT_ENV_CONFIG.backendHost ?? '127.0.0.1');
}

export function getBackendPort(config?: Partial<EnvConfig>): number {
  const port = config?.backendPort;
  if (isFiniteNumber(port)) {
    return port;
  }
  return Number(DEFAULT_ENV_CONFIG.backendPort ?? 8001);
}

export function getBackendAccessUrl(config?: Partial<EnvConfig>): string {
  const resolvedConfig = config ?? readWorkspaceEnvConfig();
  const host = normalizeBackendAccessHost(getBackendBindHost(resolvedConfig));
  const port = getBackendPort(resolvedConfig);
  return `http://${host}:${port}`;
}

/** 模板占位符(envManager 写入的默认值)——不算已配置。
 * 2026-11-06 体验审查 #2:此前只判非空,新用户的 .env 模板占位符
 * 全过判定,引导跳过配置、后端可启动,直到实验 LLM 调用 401 才暴露。 */
const ENV_PLACEHOLDER_VALUES = new Set([
  'your-api-key-here',
  'your_api_key',
  'your_coder_api_key',
  'your_embedding_api_key',
  'sk-your-litellm-virtual-key',
  'your-litellm-api-key',
]);

export function isEnvPlaceholder(value: unknown): boolean {
  if (typeof value !== 'string') {
    return false;
  }
  const trimmed = value.trim();
  return trimmed.length === 0 || ENV_PLACEHOLDER_VALUES.has(trimmed);
}

export function hasConfiguredLlmApiKey(config?: Partial<EnvConfig>): boolean {
  const resolvedConfig = config ?? readWorkspaceEnvConfig();
  return isNonEmptyString(resolvedConfig.llmApiKey)
    && !isEnvPlaceholder(resolvedConfig.llmApiKey);
}

function shouldFillEnvValue(
  currentValue: EnvConfig[keyof EnvConfig],
  defaultValue: EnvConfig[keyof EnvConfig] | undefined,
  candidateValue: EnvConfig[keyof EnvConfig],
): boolean {
  if (typeof candidateValue === 'string') {
    if (!candidateValue.trim()) {
      return false;
    }
    if (typeof currentValue !== 'string' || !currentValue.trim()) {
      return true;
    }
    return typeof defaultValue === 'string' && currentValue.trim() === defaultValue.trim();
  }

  if (typeof candidateValue === 'number') {
    if (!Number.isFinite(candidateValue)) {
      return false;
    }
    if (typeof currentValue !== 'number' || !Number.isFinite(currentValue)) {
      return true;
    }
    return typeof defaultValue === 'number' && currentValue === defaultValue;
  }

  return currentValue === undefined || currentValue === null;
}

export function migrateLegacySettingsToEnv(): string[] {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) {
    return [];
  }

  const config = vscode.workspace.getConfiguration('aiSocialScientist');
  const envManager = new EnvManager();
  const currentEnv = envManager.readEnv();
  const patch: Partial<EnvConfig> = {};
  const patchRecord = patch as Record<keyof EnvConfig, EnvConfig[keyof EnvConfig] | undefined>;
  const migratedKeys: string[] = [];

  for (const { settingKey, envKey } of LEGACY_ENV_SETTING_MAP) {
    const candidateValue = config.get<EnvConfig[keyof EnvConfig] | undefined>(settingKey);
    if (candidateValue === undefined) {
      continue;
    }
    if (!shouldFillEnvValue(currentEnv[envKey], DEFAULT_ENV_CONFIG[envKey], candidateValue)) {
      continue;
    }
    patchRecord[envKey] = typeof candidateValue === 'string' ? candidateValue.trim() : candidateValue;
    migratedKeys.push(settingKey);
  }

  const legacyBackendUrl = config.get<string | undefined>('backendUrl');
  if (isNonEmptyString(legacyBackendUrl)) {
    try {
      const parsed = new URL(legacyBackendUrl.trim());
      const parsedHost = parsed.hostname;
      const parsedPort = parsed.port ? Number(parsed.port) : undefined;

      if (
        isNonEmptyString(parsedHost)
        && shouldFillEnvValue(currentEnv.backendHost, DEFAULT_ENV_CONFIG.backendHost, parsedHost)
      ) {
        patch.backendHost = parsedHost;
        migratedKeys.push('backendUrl(host)');
      }

      if (
        isFiniteNumber(parsedPort)
        && shouldFillEnvValue(currentEnv.backendPort, DEFAULT_ENV_CONFIG.backendPort, parsedPort)
      ) {
        patch.backendPort = parsedPort;
        migratedKeys.push('backendUrl(port)');
      }
    } catch {
      // Ignore malformed legacy URL values and keep .env as the source of truth.
    }
  }

  if (migratedKeys.length > 0) {
    envManager.writeEnv(patch);
  }

  return migratedKeys;
}
