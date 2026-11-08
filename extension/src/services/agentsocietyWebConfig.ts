import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { requestJson } from './httpClient';
import type {
  ConfigValues,
  ImportedModelOptions,
  ImportedModelDefaults,
  EasyPaperConfigValues,
} from '../webview/configPage/types';
import type { ClaudeCodeConfigValues } from '../webview/configPage/claudeCodeTypes';
import {
  buildGatewayProviderFromWebImport,
  resolveWebImportClaudeConfig,
  type WebImportGatewayProviderDraft,
} from './webConfigGatewayImport';

const DEFAULT_CASDOOR_ISSUER = 'https://login.fiblab.net';
const DEFAULT_WEB_BASE_URL = 'https://agentsociety2.fiblab.net';
const DEFAULT_CLIENT_ID = '7ffcbfe4ae0fcb2c0d63';
const AUTH_DIR = path.join(os.homedir(), '.fiblab');
const AUTH_PATH = path.join(AUTH_DIR, 'agentsociety2-auth.json');
const DEVICE_GRANT_TYPE = 'urn:ietf:params:oauth:grant-type:device_code';
const TOKEN_EXPIRY_SKEW_MS = 60_000;

interface AuthCache {
  issuer: string;
  webBaseUrl: string;
  clientId: string;
  accessToken: string;
  refreshToken?: string;
  expiresAt?: number;
  scope?: string;
  savedAt: number;
}

interface OidcMetadata {
  device_authorization_endpoint?: string;
  token_endpoint?: string;
}

interface DeviceCodeResponse {
  device_code: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete?: string;
  expires_in: number;
  interval?: number;
}

interface TokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  scope?: string;
  error?: string;
  error_description?: string;
}

interface UserResponse {
  approval_status?: 'PENDING' | 'APPROVED' | 'REJECTED';
  litellm_api_key?: string | null;
  litellm_api_base?: string | null;
  search_api_url?: string | null;
  search_api_key?: string | null;
}

interface LiteLLMStatus {
  api_base?: string | null;
  models?: string[];
}

interface ModelPricing {
  name: string;
  interface?: 'claude_code' | 'openai_compatible' | 'embedding' | string;
}

interface ModelPricingResponse {
  data?: ModelPricing[];
  defaults?: Partial<ImportedModelDefaults>;
}

export interface DeviceAuthStarted {
  userCode: string;
  verificationUri: string;
  verificationUriComplete?: string;
  expiresIn: number;
  interval: number;
}

export interface ImportedWebConfig {
  config: Partial<ConfigValues>;
  claudeConfig: Partial<ClaudeCodeConfigValues>;
  easyPaperConfig: Partial<EasyPaperConfigValues>;
  gatewayProvider?: WebImportGatewayProviderDraft;
  modelOptions: ImportedModelOptions;
  defaults: Partial<ImportedModelDefaults>;
  authPath: string;
}

export interface ImportCallbacks {
  onDeviceAuthStarted?: (info: DeviceAuthStarted) => void | Promise<void>;
  onPolling?: () => void | Promise<void>;
}

export class AgentsocietyWebConfigService {
  private readonly issuer: string;
  private readonly webBaseUrl: string;
  private readonly clientId: string;
  private readonly scope: string;
  private cancelled = false;

  constructor() {
    const cfg = vscode.workspace.getConfiguration('aiSocialScientist.webConfigImport');
    this.issuer = DEFAULT_CASDOOR_ISSUER;
    this.webBaseUrl = this.trimTrailingSlash(cfg.get<string>('webBaseUrl') || DEFAULT_WEB_BASE_URL);
    this.clientId = cfg.get<string>('clientId') || DEFAULT_CLIENT_ID;
    this.scope = cfg.get<string>('scope') || 'openid profile email offline_access';
  }

  cancel(): void {
    this.cancelled = true;
  }

  async importConfig(callbacks: ImportCallbacks = {}): Promise<ImportedWebConfig> {
    this.cancelled = false;
    const metadata = await this.getMetadata();
    const accessToken = await this.getAccessToken(metadata, callbacks);
    const user = await this.getApi<UserResponse>('/api/users/me', accessToken);

    if (user.approval_status && user.approval_status !== 'APPROVED') {
      throw new Error(`当前账号状态为 ${user.approval_status}，审批通过后才能导入 LiteLLM 配置。`);
    }
    if (!user.litellm_api_key) {
      throw new Error('当前账号尚未分配 LiteLLM API Key。');
    }

    const [litellm, pricing] = await Promise.all([
      this.getOptionalApi<LiteLLMStatus>('/api/users/me/litellm', accessToken),
      this.getOptionalApi<ModelPricingResponse>('/api/users/models/pricing', accessToken),
    ]);

    return this.buildImportedConfig(user, litellm, pricing);
  }

  private async getAccessToken(metadata: OidcMetadata, callbacks: ImportCallbacks): Promise<string> {
    const cached = this.readCache();
    if (cached && this.cacheMatches(cached) && this.isAccessTokenUsable(cached)) {
      return cached.accessToken;
    }
    if (cached && this.cacheMatches(cached) && cached.refreshToken && metadata.token_endpoint) {
      try {
        const refreshed = await this.refreshToken(metadata.token_endpoint, cached.refreshToken);
        this.writeCache(refreshed);
        return refreshed.accessToken;
      } catch {
        // Fall through to device flow.
      }
    }
    const authenticated = await this.deviceFlow(metadata, callbacks, 1);
    this.writeCache(authenticated);
    return authenticated.accessToken;
  }

  private async getMetadata(): Promise<OidcMetadata> {
    const response = await requestJson<OidcMetadata>(`${this.issuer}/.well-known/openid-configuration`, {
      timeoutMs: 15_000,
    });
    if (!response.ok) {
      throw new Error(`读取 Casdoor OIDC 配置失败（HTTP ${response.status}）。`);
    }
    return {
      ...response.data,
      device_authorization_endpoint:
        response.data.device_authorization_endpoint || `${this.issuer}/api/login/oauth/device/code`,
    };
  }

  private async deviceFlow(metadata: OidcMetadata, callbacks: ImportCallbacks, remainingRestarts: number): Promise<AuthCache> {
    if (!metadata.device_authorization_endpoint || !metadata.token_endpoint) {
      throw new Error('Casdoor OIDC 配置缺少 Device Flow 端点。');
    }

    const device = await this.postForm<DeviceCodeResponse>(metadata.device_authorization_endpoint, {
      client_id: this.clientId,
      scope: this.scope,
    });
    const interval = Math.max(device.interval ?? 5, 1);
    const verificationUri = this.normalizeLoginUri(device.verification_uri);
    const verificationUriComplete = device.verification_uri_complete
      ? this.normalizeLoginUri(device.verification_uri_complete)
      : undefined;
    await callbacks.onDeviceAuthStarted?.({
      userCode: device.user_code,
      verificationUri,
      verificationUriComplete,
      expiresIn: device.expires_in,
      interval,
    });

    const expiresAt = Date.now() + device.expires_in * 1000;
    let pollIntervalMs = interval * 1000;
    while (Date.now() < expiresAt) {
      this.throwIfCancelled();
      await this.wait(pollIntervalMs);
      this.throwIfCancelled();
      await callbacks.onPolling?.();
      const token = await this.postFormRaw<TokenResponse>(metadata.token_endpoint, {
        grant_type: DEVICE_GRANT_TYPE,
        client_id: this.clientId,
        device_code: device.device_code,
      });
      if (token.ok && token.data.access_token) {
        return this.toCache(token.data);
      }
      const error = token.data?.error;
      if (error === 'authorization_pending') {
        continue;
      }
      if (error === 'slow_down') {
        pollIntervalMs += 5_000;
        continue;
      }
      if (error === 'expired_token') {
        return this.restartDeviceFlow(metadata, callbacks, remainingRestarts);
      }
      throw new Error(token.data?.error_description || error || `Device Flow 失败（HTTP ${token.status}）。`);
    }
    return this.restartDeviceFlow(metadata, callbacks, remainingRestarts);
  }

  private async restartDeviceFlow(
    metadata: OidcMetadata,
    callbacks: ImportCallbacks,
    remainingRestarts: number
  ): Promise<AuthCache> {
    if (remainingRestarts <= 0) {
      throw new Error('Device Code 已过期，请重新导入。');
    }
    this.throwIfCancelled();
    return this.deviceFlow(metadata, callbacks, remainingRestarts - 1);
  }

  private async refreshToken(tokenEndpoint: string, refreshToken: string): Promise<AuthCache> {
    const token = await this.postForm<TokenResponse>(tokenEndpoint, {
      grant_type: 'refresh_token',
      client_id: this.clientId,
      refresh_token: refreshToken,
    });
    if (!token.access_token) {
      throw new Error(token.error_description || token.error || '刷新登录凭据失败。');
    }
    return this.toCache(token, refreshToken);
  }

  private async getApi<T>(apiPath: string, accessToken: string): Promise<T> {
    const response = await requestJson<T>(`${this.webBaseUrl}${apiPath}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      timeoutMs: 30_000,
    });
    if (!response.ok) {
      throw new Error(`请求 ${apiPath} 失败（HTTP ${response.status}）。`);
    }
    return response.data;
  }

  private async getOptionalApi<T>(apiPath: string, accessToken: string): Promise<T | null> {
    const response = await requestJson<T>(`${this.webBaseUrl}${apiPath}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      timeoutMs: 30_000,
    });
    if (!response.ok) {
      return null;
    }
    return response.data;
  }

  private buildImportedConfig(
    user: UserResponse,
    litellm: LiteLLMStatus | null,
    pricing: ModelPricingResponse | null
  ): ImportedWebConfig {
    const modelOptions = this.buildModelOptions(pricing?.data ?? [], litellm?.models ?? []);
    const defaults = pricing?.defaults ?? {};
    const apiBase = this.normalizeOpenAiBase(user.litellm_api_base || litellm?.api_base || '');
    const rawBase = user.litellm_api_base || litellm?.api_base || '';
    if (!rawBase.trim()) {
      throw new Error('AgentSociety Web 未返回 LiteLLM API 地址，无法配置 Gateway 供应商。');
    }
    const searchUrl = user.search_api_url || this.normalizeMcpUrl(rawBase);
    const apiKey = user.litellm_api_key || '';
    const importedClaudeModels = resolveWebImportClaudeConfig(
      modelOptions,
      defaults
    );
    if (!importedClaudeModels.model) {
      throw new Error('AgentSociety Web 未返回可用的 Claude Code 模型，无法配置 Gateway 供应商。');
    }

    return {
      config: {
        llmApiKey: apiKey,
        llmApiBase: apiBase,
        llmModel: this.pickModel(modelOptions.openaiCompatible, defaults.simulation),
        coderLlmApiKey: '',
        coderLlmApiBase: '',
        coderLlmModel: this.pickModel(modelOptions.openaiCompatible, defaults.coder),
        embeddingApiKey: '',
        embeddingApiBase: '',
        embeddingModel: this.pickModel(modelOptions.embedding, defaults.embedding),
        embeddingDims: 1024,
        literatureSearchMcpUrl: this.ensureTrailingSlash(searchUrl),
        literatureSearchApiKey: user.search_api_key || apiKey,
      },
      claudeConfig: {
        apiKey,
        baseUrl: this.normalizeClaudeBase(rawBase),
        model: importedClaudeModels.model ?? '',
        sonnetModel: importedClaudeModels.sonnetModel ?? '',
        opusModel: importedClaudeModels.opusModel ?? '',
        fableModel: importedClaudeModels.fableModel ?? '',
        haikuModel: importedClaudeModels.haikuModel ?? '',
      },
      easyPaperConfig: {
        llmModelName: this.pickModel(modelOptions.openaiCompatible, defaults.simulation),
        llmApiKey: apiKey,
        llmBaseUrl: apiBase,
        vlmEnabled: Boolean(defaults.easyPaperVlm?.trim()),
        vlmProvider: 'openai',
        vlmModel: defaults.easyPaperVlm?.trim() || '',
        vlmApiKey: apiKey,
        vlmBaseUrl: apiBase,
      },
      gatewayProvider: buildGatewayProviderFromWebImport(apiKey, apiBase, importedClaudeModels, {
        enableCodex1m: true,
        openAiCompatibleModels: modelOptions.openaiCompatible,
        defaults,
      }),
      modelOptions,
      defaults,
      authPath: AUTH_PATH,
    };
  }

  private buildModelOptions(pricingModels: ModelPricing[], visibleModels: string[]): ImportedModelOptions {
    const visible = new Set(visibleModels);
    const namesByInterface = (iface: string) =>
      pricingModels
        .filter((model) => model.interface === iface)
        .map((model) => model.name)
        .filter((name) => !visible.size || visible.has(name));
    const hasPricing = pricingModels.length > 0;
    return {
      openaiCompatible: this.unique(hasPricing ? namesByInterface('openai_compatible') : visibleModels),
      claudeCode: this.unique(namesByInterface('claude_code')),
      embedding: this.unique(namesByInterface('embedding')),
    };
  }

  private pickModel(options: string[], preferred?: string): string {
    if (preferred && options.includes(preferred)) {
      return preferred;
    }
    return preferred || options[0] || '';
  }

  private toCache(token: TokenResponse, fallbackRefreshToken?: string): AuthCache {
    return {
      issuer: this.issuer,
      webBaseUrl: this.webBaseUrl,
      clientId: this.clientId,
      accessToken: token.access_token || '',
      refreshToken: token.refresh_token || fallbackRefreshToken,
      expiresAt: token.expires_in ? Date.now() + token.expires_in * 1000 : undefined,
      scope: token.scope || this.scope,
      savedAt: Date.now(),
    };
  }

  private readCache(): AuthCache | null {
    try {
      if (!fs.existsSync(AUTH_PATH)) {
        return null;
      }
      return JSON.parse(fs.readFileSync(AUTH_PATH, 'utf-8')) as AuthCache;
    } catch {
      return null;
    }
  }

  private writeCache(cache: AuthCache): void {
    if (!fs.existsSync(AUTH_DIR)) {
      fs.mkdirSync(AUTH_DIR, { recursive: true });
      this.chmod(AUTH_DIR, 0o700);
    }
    const tmpPath = `${AUTH_PATH}.tmp`;
    fs.writeFileSync(tmpPath, JSON.stringify(cache, null, 2), 'utf-8');
    this.chmod(tmpPath, 0o600);
    fs.renameSync(tmpPath, AUTH_PATH);
  }

  private cacheMatches(cache: AuthCache): boolean {
    return cache.issuer === this.issuer && cache.webBaseUrl === this.webBaseUrl && cache.clientId === this.clientId;
  }

  private isAccessTokenUsable(cache: AuthCache): boolean {
    return Boolean(cache.accessToken && (!cache.expiresAt || cache.expiresAt - TOKEN_EXPIRY_SKEW_MS > Date.now()));
  }

  private async postForm<T>(url: string, body: Record<string, string>): Promise<T> {
    const response = await this.postFormRaw<T>(url, body);
    if (!response.ok) {
      const data = response.data as TokenResponse;
      throw new Error(data?.error_description || data?.error || `请求失败（HTTP ${response.status}）。`);
    }
    return response.data;
  }

  private async postFormRaw<T>(url: string, body: Record<string, string>): Promise<{ ok: boolean; status: number; data: T }> {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(body).toString(),
    });
    const text = await response.text();
    let data: T;
    try {
      data = text ? JSON.parse(text) as T : ({} as T);
    } catch {
      data = { error: text } as T;
    }
    return { ok: response.ok, status: response.status, data };
  }

  private async wait(ms: number): Promise<void> {
    await new Promise<void>((resolve) => setTimeout(resolve, ms));
  }

  private throwIfCancelled(): void {
    if (this.cancelled) {
      throw new Error('已取消 AgentSociety Web 导入。');
    }
  }

  private normalizeOpenAiBase(base: string): string {
    const trimmed = this.trimTrailingSlash(base);
    if (!trimmed) {
      return '';
    }
    return trimmed.endsWith('/v1') ? trimmed : `${trimmed}/v1`;
  }

  private normalizeClaudeBase(base: string): string {
    return this.trimTrailingSlash(base);
  }

  private normalizeMcpUrl(base: string): string {
    const trimmed = this.trimTrailingSlash(base);
    if (!trimmed) {
      return 'https://llmapi.fiblab.net/mcp/';
    }
    return this.ensureTrailingSlash(`${trimmed}/mcp`);
  }

  private trimTrailingSlash(value: string): string {
    return value.trim().replace(/\/+$/, '');
  }

  private ensureTrailingSlash(value: string): string {
    const trimmed = value.trim();
    return trimmed && !trimmed.endsWith('/') ? `${trimmed}/` : trimmed;
  }

  private normalizeLoginUri(value: string): string {
    try {
      const parsed = new URL(value);
      const fixed = new URL(DEFAULT_CASDOOR_ISSUER);
      parsed.protocol = fixed.protocol;
      parsed.host = fixed.host;
      return parsed.toString();
    } catch {
      return value;
    }
  }

  private unique(values: string[]): string[] {
    return Array.from(new Set(values.filter(Boolean)));
  }

  private chmod(targetPath: string, mode: number): void {
    if (process.platform === 'win32') {
      return;
    }
    try {
      fs.chmodSync(targetPath, mode);
    } catch {
      // Best effort only.
    }
  }
}
