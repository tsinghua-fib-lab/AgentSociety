import * as fs from 'fs';
import * as vscode from 'vscode';
import type { ClaudeCodeConfigValues } from '../webview/configPage/claudeCodeTypes';
import {
  getOrCreateGatewayAuthToken,
  buildLocalGatewayBaseUrl,
  isLocalGatewayBaseUrl,
  type AiCliGatewayUpstream,
} from './aiCliGatewayUpstream';
import { AiCliGateway, type AiCliGatewayStatus, type GatewayLogEntry } from './aiCliGateway';
import {
  CLAUDE_SETTINGS_PATH,
  applyClaudeOfficialSubscription,
  readClaudeConfig,
  readClaudeSettingsFile,
  writeClaudeConfig,
} from './claudeCodeSettings';
import {
  fetchProviderModels,
} from './providerModels';
import {
  claudeSettingsBaseUrl,
  inferApiKindFromBaseUrl,
  providerUpstream,
  resolveProviderBaseUrl,
  type AiCliApiKind,
} from '../aiCli/officialEndpoints';
import { inferOpenAiApiFormat } from './codexApiFormat';
import { resolveCodexChatModel } from './codexModelMapping';
import {
  sanitizeUsageRecords,
  type TokenUsageRecord,
} from './gatewayUsageTracker';
import {
  type ModelPricingMap,
  getBuiltinPricing,
} from './gatewayModelPricing';
import {
  fetchRemoteGatewayPricing,
  selectObservedRemotePricing,
} from './gatewayRemotePricing';
import {
  queryProviderUsage,
  supportsProviderUsageQuery,
  type ProviderUsageResult,
} from './gatewayProviderUsage';
import {
  applyCodexDirectProvider,
  applyCodexGatewayConfig,
  applyCodexOfficialSubscription,
  buildCodexDirectProviderConfigText,
  detectCodexOfficialLogin,
  getCodexRoutingSnapshot,
  getCodexOfficialLoginSnapshot,
  isCodexConfiguredByUser,
  isCodexGatewayTakeoverConfig,
  readCodexConfigText,
  releaseCodexGatewayTakeover,
  shouldEnableCodexRouteByDefault,
  snapshotCodexLiveBackup,
  stripCodexGatewayConfig,
  type CodexProviderPatch,
} from './codexSettings';
import {
  DEFAULT_GATEWAY_RECTIFIER_SETTINGS,
  type GatewayRectifierSettings,
} from './gatewayRequestRectifier';
import {
  DEFAULT_GATEWAY_OPTIMIZER_SETTINGS,
  type GatewayOptimizerSettings,
} from './bedrockRequestOptimizer';
import type { OutboundProxyConfig } from './gatewayOutboundProxy';
import { buildOutboundProxyUrl } from './gatewayOutboundProxy';
import { resolveManualConfigSyncMode } from './manualConfigSync';
import {
  clampProviderRoleFlags,
  inferProviderAuthMode,
  isOfficialSubscriptionProvider,
  providerEligibleForRoleUpstream,
  providerSupportsRole,
  providerHasApiUpstream as providerHasApiKeyUpstream,
  providerHasConfiguredCredentials,
  type AiCliAuthMode,
} from '../aiCli/providerAuth';
import type { AiCliAuthHeaderMode } from '../aiCli/upstreamAuthHeaders';
import {
  appendSharedOutputLine,
  getSharedOutputChannel,
  OUTPUT_CHANNEL_GATEWAY,
} from '../shared/outputChannels';
import {
  scanClaudeSessionUsage,
  type ClaudeSessionUsageCursor,
} from './claudeSessionUsage';

const UPSTREAM_SECRET_KEY = 'aiCliGateway.upstream.secret';
const ENABLED_STATE_KEY = 'aiCliGateway.enabled';
const PROVIDERS_STATE_KEY = 'aiCliGateway.providers';
const PROVIDER_SECRET_PREFIX = 'aiCliGateway.provider.apiKey.';
const USAGE_STATE_KEY = 'aiCliGateway.usageRecords';
const CLAUDE_SESSION_CURSOR_STATE_KEY = 'aiCliGateway.claudeSessionUsageCursor';
const CUSTOM_PRICING_STATE_KEY = 'aiCliGateway.customPricing';
const REMOTE_PRICING_STATE_KEY = 'aiCliGateway.remotePricing';
const REMOTE_PRICING_FETCHED_AT_STATE_KEY = 'aiCliGateway.remotePricingFetchedAt';
const FAILOVER_ENABLED_STATE_KEY = 'aiCliGateway.failoverEnabled';
const ROUTE_CLAUDE_STATE_KEY = 'aiCliGateway.routeClaude';
// 默认开标记(maybeEnableCodexRouteByDefault 写入,区别用户显式开)。
const ROUTE_CODEX_AUTO_STATE_KEY = 'aiCliGateway.routeCodex.auto';
const ROUTE_CODEX_STATE_KEY = 'aiCliGateway.routeCodex';
/** Pre-takeover ~/.codex/config.toml snapshot (cc-switch live backup). */
const CODEX_LIVE_BACKUP_SECRET_KEY = 'aiCliGateway.codexLiveBackup.secret';
const OUTBOUND_PROXY_SECRET_KEY = 'aiCliGateway.outboundProxy.secret';
const RECTIFIER_STATE_KEY = 'aiCliGateway.rectifier';
const OPTIMIZER_STATE_KEY = 'aiCliGateway.optimizer';
const MAX_USAGE_RECORDS = 10000;
const REMOTE_PRICING_TTL_MS = 24 * 60 * 60 * 1000;

export type AiCliGatewayPublicStatus = AiCliGatewayStatus & {
  enabled: boolean;
  routeClaude: boolean;
  routeCodex: boolean;
  claudeProxyAvailable: boolean;
  codexProxyAvailable: boolean;
  codexOfficialLoginPresent: boolean;
  codexAuthPath?: string;
  outboundProxyUrl: string;
  rectifier: GatewayRectifierSettings;
  optimizer: GatewayOptimizerSettings;
};

export type AiCliProviderConfig = {
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

export type AiCliProviderAvailabilityResult = {
  ok: boolean;
  models: number;
  apiKind?: AiCliApiKind;
  error?: string;
  detail?: string;
};

export class AiCliGatewayManager {
  private readonly gateway = new AiCliGateway();
  private outputChannel: vscode.OutputChannel;
  private sessionUsage: TokenUsageRecord[] = [];
  private usagePersistTimer: NodeJS.Timeout | undefined;
  private usageChangeListener: (() => void) | null = null;
  private usagePersistPromise: Promise<void> = Promise.resolve();
  private providersCache: AiCliProviderConfig[] = [];
  private storedUpstreamCache: AiCliGatewayUpstream | undefined;
  private codexLiveBackupCache: string | undefined;
  private outboundProxyCache: OutboundProxyConfig | null;
  private codexLoginSnapshot = getCodexOfficialLoginSnapshot();
  private codexLoginRefreshed = false;
  private readonly secretsReady: Promise<void>;

  constructor(private readonly context: vscode.ExtensionContext) {
    this.outputChannel = getSharedOutputChannel(OUTPUT_CHANNEL_GATEWAY);
    this.gateway.onLog((entry: GatewayLogEntry) => {
      const tokenInfo =
        entry.inputTokens !== undefined && entry.outputTokens !== undefined
          ? ` in:${entry.inputTokens} out:${entry.outputTokens}`
          : '';
      const failoverInfo = entry.failoverFrom ? ` failover:${entry.failoverFrom}` : '';
      appendSharedOutputLine(
        OUTPUT_CHANNEL_GATEWAY,
        `${entry.ts} [request] ${entry.method} ${entry.path} -> ${entry.status} (${entry.ms}ms)${entry.model ? ` model=${entry.model}` : ''}${tokenInfo}${failoverInfo} upstream=${entry.upstream}`
      );
    });
    this.gateway.onUsage((record: TokenUsageRecord) => {
      this.addUsageRecord(record);
    });
    this.gateway.onFailover((upstream, role) => {
      void this.applyFailoverUpstream(upstream, role);
    });
    this.providersCache = this.readStoredProviderMetadata();
    this.outboundProxyCache = null;
    this.secretsReady = this.initializeSecretStorage();
  }

  dispose(): void {
    if (this.usagePersistTimer) {
      clearTimeout(this.usagePersistTimer);
      this.usagePersistTimer = undefined;
    }
    this.restoreLiveConfigsBeforeShutdown();
    void this.persistUsage();
    void this.gateway.stop();
  }

  getPublicStatus(): AiCliGatewayPublicStatus {
    const routeClaude = this.isRouteClaudeViaGateway();
    const routeCodex = this.isRouteCodexViaGateway();
    const claudeProxyAvailable = Boolean(this.getAnthropicProviderForGateway());
    const codexProxyAvailable = Boolean(this.getOpenAiProviderForGateway());
    this.syncGatewayEnhancements();
    const fileLogin = getCodexOfficialLoginSnapshot();
    const login = fileLogin.present ? fileLogin : this.codexLoginSnapshot;
    return {
      ...this.gateway.getStatus(),
      enabled: routeClaude || routeCodex,
      routeClaude,
      routeCodex,
      claudeProxyAvailable,
      codexProxyAvailable,
      codexOfficialLoginPresent: login.present,
      codexAuthPath: login.authPath,
      outboundProxyUrl: this.getOutboundProxy()?.url ?? '',
      rectifier: this.getRectifierSettings(),
      optimizer: this.getOptimizerSettings(),
    };
  }

  getOutboundProxy(): OutboundProxyConfig | null {
    const stored = this.outboundProxyCache;
    if (!stored?.url?.trim()) {
      return null;
    }
    return {
      url: stored.url.trim(),
      username: stored.username?.trim() || undefined,
      password: stored.password?.trim() || undefined,
    };
  }

  async setOutboundProxy(proxy: OutboundProxyConfig | null): Promise<AiCliGatewayPublicStatus> {
    await this.initialize();
    if (!proxy?.url.trim()) {
      this.outboundProxyCache = null;
      await this.context.secrets.delete(OUTBOUND_PROXY_SECRET_KEY);
    } else {
      this.outboundProxyCache = {
        url: proxy.url.trim(),
        username: proxy.username?.trim() || undefined,
        password: proxy.password?.trim() || undefined,
      };
      await this.context.secrets.store(
        OUTBOUND_PROXY_SECRET_KEY,
        JSON.stringify(this.outboundProxyCache)
      );
    }
    this.syncGatewayEnhancements();
    return this.getPublicStatus();
  }

  getRectifierSettings(): GatewayRectifierSettings {
    const stored = this.context.globalState.get<Partial<GatewayRectifierSettings>>(RECTIFIER_STATE_KEY);
    return { ...DEFAULT_GATEWAY_RECTIFIER_SETTINGS, ...(stored ?? {}) };
  }

  async setRectifierSettings(
    patch: Partial<GatewayRectifierSettings>
  ): Promise<AiCliGatewayPublicStatus> {
    await this.initialize();
    const next = { ...this.getRectifierSettings(), ...patch };
    await this.context.globalState.update(RECTIFIER_STATE_KEY, next);
    this.syncGatewayEnhancements();
    return this.getPublicStatus();
  }

  getOptimizerSettings(): GatewayOptimizerSettings {
    const stored = this.context.globalState.get<Partial<GatewayOptimizerSettings>>(OPTIMIZER_STATE_KEY);
    return { ...DEFAULT_GATEWAY_OPTIMIZER_SETTINGS, ...(stored ?? {}) };
  }

  async setOptimizerSettings(
    patch: Partial<GatewayOptimizerSettings>
  ): Promise<AiCliGatewayPublicStatus> {
    await this.initialize();
    const next = { ...this.getOptimizerSettings(), ...patch };
    await this.context.globalState.update(OPTIMIZER_STATE_KEY, next);
    this.syncGatewayEnhancements();
    return this.getPublicStatus();
  }

  private syncGatewayEnhancements(): void {
    this.gateway.configureOutboundProxy(this.getOutboundProxy());
    this.gateway.configureRectifier(this.getRectifierSettings());
    this.gateway.configureOptimizer(this.getOptimizerSettings());
  }

  /** Process environment so Codex CLI itself (including login) can reach OpenAI via the proxy. */
  buildOutboundProxyEnv(): Record<string, string> | undefined {
    const proxy = this.getOutboundProxy();
    const url = proxy ? buildOutboundProxyUrl(proxy) : null;
    if (!url) {
      return undefined;
    }
    const noProxy = Array.from(
      new Set(
        [
          ...(process.env.NO_PROXY ?? '').split(','),
          ...(process.env.no_proxy ?? '').split(','),
          '127.0.0.1',
          'localhost',
          '::1',
        ]
          .map((entry) => entry.trim())
          .filter(Boolean)
      )
    ).join(',');
    return {
      HTTP_PROXY: url,
      HTTPS_PROXY: url,
      ALL_PROXY: url,
      http_proxy: url,
      https_proxy: url,
      all_proxy: url,
      NO_PROXY: noProxy,
      no_proxy: noProxy,
    };
  }

  /**
   * Apply live Codex projection to config.toml / model catalog only.
   * Never overwrite auth.json so ChatGPT OAuth (mobile remote / plugins) stays intact
   * (cc-switch: auth.json = login cache, config.toml = provider routing).
   */
  private async projectCodexProviderLive(
    provider: AiCliProviderConfig,
    gatewayPort?: number
  ): Promise<void> {
    const patch = this.providerToCodexPatch(provider);
    if (typeof gatewayPort === 'number' && gatewayPort > 0) {
      await this.updateCodexRestoreTarget(provider);
      applyCodexGatewayConfig(gatewayPort, patch);
    } else {
      applyCodexDirectProvider(patch);
    }
  }

  private async storeCodexLiveBackup(text: string): Promise<void> {
    this.codexLiveBackupCache = text;
    await this.context.secrets.store(CODEX_LIVE_BACKUP_SECRET_KEY, text);
  }

  private async clearCodexLiveBackup(): Promise<void> {
    this.codexLiveBackupCache = undefined;
    await this.context.secrets.delete(CODEX_LIVE_BACKUP_SECRET_KEY);
  }

  /**
   * Keep the restore snapshot aligned with the selected provider while takeover
   * stays active. This is the cc-switch invariant: live points at the proxy,
   * while the backup represents the direct config to restore when routing stops.
   */
  private async updateCodexRestoreTarget(provider: AiCliProviderConfig): Promise<void> {
    const live = readCodexConfigText();
    const cleanBase =
      snapshotCodexLiveBackup(live) ??
      (this.codexLiveBackupCache &&
      !isCodexGatewayTakeoverConfig(this.codexLiveBackupCache)
        ? this.codexLiveBackupCache
        : live);
    const restoreTarget = buildCodexDirectProviderConfigText(
      cleanBase,
      this.providerToCodexPatch(provider)
    );
    await this.storeCodexLiveBackup(restoreTarget);
  }

  /**
   * Release Codex proxy takeover: restore live backup if clean, else rebuild from active provider.
   * Matches cc-switch stop_with_restore / placeholder-guard behavior.
   */
  private async releaseCodexProxyTakeover(): Promise<void> {
    const mode = releaseCodexGatewayTakeover(this.codexLiveBackupCache, () => {
      this.rebuildCodexLiveFromActiveProvider();
    });
    await this.clearCodexLiveBackup();
    this.log(
      mode === 'backup'
        ? 'Codex proxy off: restored pre-takeover config.toml backup'
        : 'Codex proxy off: rebuilt config.toml from active provider'
    );
  }

  private rebuildCodexLiveFromActiveProvider(): void {
    const active = this.getActiveCodexProvider();
    if (!active || isOfficialSubscriptionProvider(active)) {
      applyCodexOfficialSubscription();
      return;
    }
    if (
      this.providerHasApiUpstream(active) &&
      (active.apiKind ?? inferApiKindFromBaseUrl(active.baseUrl)) === 'openai'
    ) {
      applyCodexDirectProvider(this.providerToCodexPatch(active));
      return;
    }
    applyCodexOfficialSubscription();
  }

  /**
   * VS Code can unload the extension while keeping Codex terminals alive.
   * Restore usable direct configs synchronously, but retain route state and the
   * encrypted restore snapshot so the next activation can re-establish takeover.
   */
  private restoreLiveConfigsBeforeShutdown(): void {
    const codexRouting = getCodexRoutingSnapshot();
    if (codexRouting.routedViaGateway || this.codexLiveBackupCache !== undefined) {
      releaseCodexGatewayTakeover(this.codexLiveBackupCache, () => {
        this.rebuildCodexLiveFromActiveProvider();
      });
    }

    if (isLocalGatewayBaseUrl(readClaudeConfig().baseUrl)) {
      const active = this.getActiveClaudeProvider();
      if (active && isOfficialSubscriptionProvider(active)) {
        applyClaudeOfficialSubscription(active.permissionMode);
      } else if (active && this.isAnthropicProvider(active) && this.providerHasApiUpstream(active)) {
        writeClaudeConfig(this.providerToClaudeConfig(active));
      } else {
        applyClaudeOfficialSubscription();
      }
    }
  }

  isRouteClaudeViaGateway(): boolean {
    return this.context.globalState.get<boolean>(ROUTE_CLAUDE_STATE_KEY, false);
  }

  isRouteCodexViaGateway(): boolean {
    return this.context.globalState.get<boolean>(ROUTE_CODEX_STATE_KEY, false);
  }

  isClaudeRoutedViaGateway(): boolean {
    if (!this.isRouteClaudeViaGateway()) {
      return false;
    }
    return isLocalGatewayBaseUrl(readClaudeConfig().baseUrl);
  }

  async setGatewayRoute(target: 'claude' | 'codex', enabled: boolean): Promise<AiCliGatewayPublicStatus> {
    await this.initialize();
    if (enabled) {
      const available =
        target === 'claude'
          ? Boolean(this.getAnthropicProviderForGateway())
          : Boolean(this.getOpenAiProviderForGateway());
      if (!available) {
        throw new Error('route_requires_api');
      }
    }
    await this.context.globalState.update(
      target === 'claude' ? ROUTE_CLAUDE_STATE_KEY : ROUTE_CODEX_STATE_KEY,
      enabled
    );
    if (target === 'codex') {
      await this.context.globalState.update(ROUTE_CODEX_AUTO_STATE_KEY, false);
    }

    if (!this.isRouteClaudeViaGateway() && !this.isRouteCodexViaGateway()) {
      const activeAnthropic = this.getActiveAnthropicProvider();
      const config = activeAnthropic
        ? this.providerToClaudeConfig(activeAnthropic)
        : readClaudeConfig();
      return this.disableAndRestoreDirect(config);
    }

    const anthropic = this.getAnthropicProviderForGateway();
    const config = anthropic
      ? this.providerToClaudeConfig(anthropic)
      : readClaudeConfig();
    if (!this.gateway.getStatus().running) {
      return this.enableWithClaudeConfig(config);
    }
    await this.applyGatewayRoutes(config);
    await this.persistEnabled(true);
    return this.getPublicStatus();
  }

  getLogChannel(): vscode.OutputChannel {
    return this.outputChannel;
  }

  getStoredUpstream(): AiCliGatewayUpstream | undefined {
    return this.storedUpstreamCache;
  }

  private async persistUpstream(upstream: AiCliGatewayUpstream): Promise<void> {
    this.storedUpstreamCache = upstream;
    await this.context.secrets.store(UPSTREAM_SECRET_KEY, JSON.stringify(upstream));
  }

  private async persistEnabled(enabled: boolean): Promise<void> {
    await this.context.globalState.update(ENABLED_STATE_KEY, enabled);
  }

  resolveUpstreamFromClaudeForm(config: ClaudeCodeConfigValues): AiCliGatewayUpstream {
    const apiKey = config.apiKey.trim();
    let baseUrl = config.baseUrl.trim();
    if (isLocalGatewayBaseUrl(baseUrl)) {
      const stored = this.getStoredUpstream();
      if (stored?.baseUrl && stored.apiKey) {
        return stored;
      }
    }
    if (!baseUrl && apiKey) {
      baseUrl = resolveProviderBaseUrl('', 'anthropic');
    }
    return { baseUrl, apiKey };
  }

  private normalizeProvider(provider: AiCliProviderConfig): AiCliProviderConfig {
    const apiKind = provider.apiKind ?? inferApiKindFromBaseUrl(provider.baseUrl);
    const authMode = inferProviderAuthMode({ ...provider, apiKind });
    const authHeaderMode = provider.authHeaderMode ?? 'auto';
    return clampProviderRoleFlags({ ...provider, apiKind, authMode, authHeaderMode });
  }

  private readStoredProviderMetadata(): AiCliProviderConfig[] {
    const raw = this.context.globalState.get<AiCliProviderConfig[]>(PROVIDERS_STATE_KEY) ?? [];
    return raw.map((provider) => this.normalizeProvider(provider));
  }

  private providerSecretKey(id: string): string {
    return `${PROVIDER_SECRET_PREFIX}${id}`;
  }

  private providerMetadata(provider: AiCliProviderConfig): AiCliProviderConfig {
    return { ...provider, apiKey: '' };
  }

  private async initializeSecretStorage(): Promise<void> {
    try {
      const storedProviders = this.readStoredProviderMetadata();
      const hydrated: AiCliProviderConfig[] = [];
      for (const provider of storedProviders) {
        const secretApiKey = await this.context.secrets.get(this.providerSecretKey(provider.id));
        hydrated.push(this.normalizeProvider({ ...provider, apiKey: secretApiKey ?? '' }));
      }
      this.providersCache = hydrated;
      await this.context.globalState.update(
        PROVIDERS_STATE_KEY,
        hydrated.map((provider) => this.providerMetadata(provider))
      );

      const secretUpstream = await this.context.secrets.get(UPSTREAM_SECRET_KEY);
      if (secretUpstream) {
        this.storedUpstreamCache = JSON.parse(secretUpstream) as AiCliGatewayUpstream;
      }

      const secretBackup = await this.context.secrets.get(CODEX_LIVE_BACKUP_SECRET_KEY);
      this.codexLiveBackupCache = secretBackup;

      const secretProxy = await this.context.secrets.get(OUTBOUND_PROXY_SECRET_KEY);
      if (secretProxy) {
        this.outboundProxyCache = JSON.parse(secretProxy) as OutboundProxyConfig;
      }
    } catch (error) {
      this.log(`Secret storage initialization failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async initialize(): Promise<void> {
    await this.secretsReady;
    if (!this.codexLoginRefreshed) {
      this.codexLoginRefreshed = true;
      this.codexLoginSnapshot = await detectCodexOfficialLogin();
      await this.yieldCodexRouteToOfficialLoginIfNeeded();
    }
  }

  /** 官方登录出现且 codex 路由是「默认开」(非用户显式)时,自动让位:
   *  关路由、恢复官方订阅配置。用户显式开过(手动 toggle)则绝不动。 */
  private async yieldCodexRouteToOfficialLoginIfNeeded(): Promise<void> {
    const autoEnabled = this.context.globalState.get<boolean>(ROUTE_CODEX_AUTO_STATE_KEY, false);
    if (!autoEnabled || !this.codexLoginSnapshot.present) {
      return;
    }
    await this.context.globalState.update(ROUTE_CODEX_STATE_KEY, undefined);
    await this.context.globalState.update(ROUTE_CODEX_AUTO_STATE_KEY, false);
    if (getCodexRoutingSnapshot().routedViaGateway || this.codexLiveBackupCache !== undefined) {
      await this.releaseCodexProxyTakeover();
    } else {
      applyCodexOfficialSubscription();
    }
    this.log('Codex official login detected; auto-enabled gateway route yielded back to subscription');
  }

  async refreshCodexOfficialLogin(options?: { preserveRoute?: boolean }): Promise<AiCliGatewayPublicStatus> {
    await this.secretsReady;
    this.codexLoginSnapshot = await detectCodexOfficialLogin();
    this.codexLoginRefreshed = true;
    if (!options?.preserveRoute) { await this.yieldCodexRouteToOfficialLoginIfNeeded(); }
    return this.getPublicStatus();
  }

  private isAnthropicProvider(provider: AiCliProviderConfig): boolean {
    return (provider.apiKind ?? 'anthropic') !== 'openai';
  }

  providerHasCredentials(provider: AiCliProviderConfig): boolean {
    return providerHasConfiguredCredentials(provider);
  }

  providerHasApiUpstream(provider: AiCliProviderConfig): boolean {
    return providerHasApiKeyUpstream(provider);
  }

  getAnthropicProviderForGateway(): AiCliProviderConfig | undefined {
    const providers = this.getProviders();
    const active = providers.find(
      (p) =>
        p.activeClaude &&
        providerEligibleForRoleUpstream(p, 'claude')
    );
    if (active) {
      return active;
    }
    return providers.find((p) => providerEligibleForRoleUpstream(p, 'claude'));
  }

  getOpenAiProviderForGateway(): AiCliProviderConfig | undefined {
    return this.getProviders().find(
      (p) =>
        p.activeCodex &&
        providerEligibleForRoleUpstream(p, 'codex') &&
        Boolean(this.resolveCodexProviderModel(p))
    );
  }

  private resolveCodexProviderModel(provider: AiCliProviderConfig): string | undefined {
    const normalized = this.normalizeProvider(provider);
    const upstream = providerUpstream(normalized);
    const codexModelPref = normalized.codexModel?.trim() || normalized.model;
    const resolved = resolveCodexChatModel(normalized.model, {
      baseUrl: upstream.baseUrl,
      codexModel: codexModelPref,
      codexApiFormat: inferOpenAiApiFormat(upstream.baseUrl),
    });
    return resolved.trim() || undefined;
  }

  private providerToGatewayUpstream(provider: AiCliProviderConfig): AiCliGatewayUpstream {
    const normalized = this.normalizeProvider(provider);
    const upstream = providerUpstream(normalized);
    const codexApiFormat =
      upstream.apiKind === 'openai' ? inferOpenAiApiFormat(upstream.baseUrl) : undefined;
    return {
      baseUrl: upstream.baseUrl,
      apiKey: upstream.apiKey,
      providerName: normalized.name.trim() || undefined,
      apiKind: upstream.apiKind,
      authHeaderMode: normalized.authHeaderMode,
      model: normalized.model,
      sonnetModel: normalized.sonnetModel,
      opusModel: normalized.opusModel,
      fableModel: normalized.fableModel,
      haikuModel: normalized.haikuModel,
      sonnetDisplayName: normalized.sonnetDisplayName,
      opusDisplayName: normalized.opusDisplayName,
      fableDisplayName: normalized.fableDisplayName,
      haikuDisplayName: normalized.haikuDisplayName,
      declareSonnet1m: normalized.declareSonnet1m,
      declareOpus1m: normalized.declareOpus1m,
      declareFable1m: normalized.declareFable1m,
      codexApiFormat,
      codexModel:
        upstream.apiKind === 'openai'
          ? this.resolveCodexProviderModel(normalized)
          : undefined,
      codexEnable1m: normalized.codexEnable1m,
      codexContextWindow: normalized.codexContextWindow,
      codexAutoCompactLimit: normalized.codexAutoCompactLimit,
    };
  }

  private providerToCodexPatch(provider: AiCliProviderConfig): CodexProviderPatch {
    const normalized = this.normalizeProvider(provider);
    const upstream = providerUpstream(normalized);
    return {
      baseUrl: upstream.baseUrl,
      apiKey: upstream.apiKey,
      model: this.resolveCodexProviderModel(normalized),
      codexEnable1m: normalized.codexEnable1m,
      codexContextWindow: normalized.codexContextWindow,
      codexAutoCompactLimit: normalized.codexAutoCompactLimit,
    };
  }

  private getActiveAnthropicProvider(): AiCliProviderConfig | undefined {
    const providers = this.getProviders();
    return (
      providers.find((p) => p.activeClaude && this.isAnthropicProvider(p)) ??
      providers.find((p) => this.isAnthropicProvider(p) && this.providerHasCredentials(p))
    );
  }

  canEnableGateway(): boolean {
    return Boolean(this.getAnthropicProviderForGateway() || this.getOpenAiProviderForGateway());
  }

  async syncGatewayRoutesWithProviders(): Promise<Array<'claude' | 'codex'>> {
    const adjusted: Array<'claude' | 'codex'> = [];
    if (this.isRouteClaudeViaGateway() && !this.getAnthropicProviderForGateway()) {
      await this.context.globalState.update(ROUTE_CLAUDE_STATE_KEY, false);
      adjusted.push('claude');
    }
    if (this.isRouteCodexViaGateway() && !this.getOpenAiProviderForGateway()) {
      // undefined = "no explicit choice" (key deleted) so the default-on probe in
      // maybeEnableCodexRouteByDefault can still fire later. A system force-off
      // must NOT be recorded as a user decision. Claude (:725) keeps writing
      // false — out of scope for the codex default-on feature.
      await this.context.globalState.update(ROUTE_CODEX_STATE_KEY, undefined);
      adjusted.push('codex');
    }
    return adjusted;
  }

  private async prepareGatewayRoutesForEnable(): Promise<Array<'claude' | 'codex'>> {
    const adjusted = await this.syncGatewayRoutesWithProviders();
    const routeClaude = this.isRouteClaudeViaGateway();
    const routeCodex = this.isRouteCodexViaGateway();
    // Never auto-enable routes HERE — the Codex default-on probe runs when a
    // Codex provider is activated (applyActiveCodexProvider), not on Claude-only
    // enable paths. Users must flip the Claude switch themselves.
    if (!routeClaude && !routeCodex) {
      throw new Error('gateway_no_route_selected');
    }
    return adjusted;
  }

  providerToClaudeConfig(provider: AiCliProviderConfig): ClaudeCodeConfigValues {
    const normalized = this.normalizeProvider(provider);
    const upstream = providerUpstream(normalized);
    return {
      apiKey: upstream.apiKey,
      baseUrl: claudeSettingsBaseUrl(upstream.baseUrl),
      model: provider.model?.trim() ?? '',
      sonnetModel: provider.sonnetModel?.trim() ?? '',
      opusModel: provider.opusModel?.trim() ?? '',
      fableModel: provider.fableModel?.trim() ?? '',
      haikuModel: provider.haikuModel?.trim() ?? '',
      permissionMode: provider.permissionMode?.trim() ?? '',
    };
  }

  getActiveClaudeProvider(): AiCliProviderConfig | undefined {
    return this.getProviders().find((p) => p.activeClaude);
  }

  getActiveCodexProvider(): AiCliProviderConfig | undefined {
    return this.getProviders().find((p) => p.activeCodex);
  }

  claudeConfigForUi(): ClaudeCodeConfigValues {
    const active = this.getActiveClaudeProvider();
    if (active) {
      return this.providerToClaudeConfig(active);
    }
    const live = readClaudeConfig();
    if (!isLocalGatewayBaseUrl(live.baseUrl)) {
      return live;
    }
    const upstream = this.getStoredUpstream();
    if (!upstream) {
      return live;
    }
    return {
      ...live,
      baseUrl: upstream.baseUrl,
      apiKey: upstream.apiKey,
    };
  }

  private buildClaudeLiveConfig(
    port: number,
    config: ClaudeCodeConfigValues
  ): ClaudeCodeConfigValues {
    return {
      ...config,
      baseUrl: buildLocalGatewayBaseUrl(port),
      apiKey: getOrCreateGatewayAuthToken(),
    };
  }

  private ensureGatewayDiscoveryEnv(): void {
    const settings = readClaudeSettingsFile();
    const env = { ...((settings.env as Record<string, string> | undefined) ?? {}) };
    env.CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = '1';
    const updated = { ...settings, env };
    const json = JSON.stringify(updated, null, 2);
    const tmpPath = CLAUDE_SETTINGS_PATH + '.tmp';
    fs.writeFileSync(tmpPath, json, 'utf-8');
    try {
      fs.chmodSync(tmpPath, 0o600);
    } catch {
      /* ignore */
    }
    fs.renameSync(tmpPath, CLAUDE_SETTINGS_PATH);
  }

  async enableWithClaudeConfig(config: ClaudeCodeConfigValues): Promise<AiCliGatewayPublicStatus> {
    await this.initialize();
    await this.prepareGatewayRoutesForEnable();
    const routeClaude = this.isRouteClaudeViaGateway();
    const routeCodex = this.isRouteCodexViaGateway();

    const anthropicProvider = this.getAnthropicProviderForGateway();
    const openaiProvider = this.getOpenAiProviderForGateway();
    if (routeClaude && !anthropicProvider) {
      throw new Error('upstream_incomplete');
    }
    if (routeCodex && !openaiProvider) {
      throw new Error('codex_upstream_incomplete');
    }

    let startUpstream: AiCliGatewayUpstream;
    if (routeClaude && anthropicProvider) {
      startUpstream = this.providerToGatewayUpstream(anthropicProvider);
    } else if (routeCodex && openaiProvider) {
      startUpstream = this.providerToGatewayUpstream(openaiProvider);
    } else {
      throw new Error('upstream_incomplete');
    }

    await this.persistUpstream(startUpstream);
    const status = await this.gateway.start(startUpstream);
    if (!status.running || !status.port) {
      throw new Error('gateway_start_failed');
    }
    if (routeCodex && openaiProvider) {
      this.gateway.setOpenaiUpstream(this.providerToGatewayUpstream(openaiProvider));
    } else {
      this.gateway.setOpenaiUpstream(null);
    }
    if (routeClaude) {
      this.syncFailoverToGateway();
    }
    await this.applyGatewayRoutes(config);
    await this.persistEnabled(true);
    this.log(`Gateway enabled on ${status.baseUrl}`);
    return this.getPublicStatus();
  }

  private async applyGatewayRoutes(config?: ClaudeCodeConfigValues): Promise<void> {
    const routeClaude = this.isRouteClaudeViaGateway();
    const routeCodex = this.isRouteCodexViaGateway();
    const gatewayStatus = this.gateway.getStatus();
    const anthropicProvider = this.getAnthropicProviderForGateway();
    const claudeConfig =
      config ??
      (anthropicProvider ? this.providerToClaudeConfig(anthropicProvider) : readClaudeConfig());

    if (routeClaude && gatewayStatus.running && gatewayStatus.port) {
      writeClaudeConfig(this.buildClaudeLiveConfig(gatewayStatus.port, claudeConfig));
      this.ensureGatewayDiscoveryEnv();
    } else if (isLocalGatewayBaseUrl(readClaudeConfig().baseUrl)) {
      // Only rewrite Claude when leaving gateway — never while only Codex is on.
      const activeAnthropic = this.getActiveAnthropicProvider();
      if (activeAnthropic && isOfficialSubscriptionProvider(activeAnthropic)) {
        applyClaudeOfficialSubscription(activeAnthropic.permissionMode);
      } else if (anthropicProvider && this.isAnthropicProvider(anthropicProvider)) {
        const direct = this.providerToClaudeConfig(anthropicProvider);
        writeClaudeConfig(direct);
        await this.persistUpstream(this.providerToGatewayUpstream(anthropicProvider));
      } else {
        applyClaudeOfficialSubscription();
      }
    }

    if (routeCodex && gatewayStatus.running && gatewayStatus.port) {
      const openaiActive = this.getOpenAiProviderForGateway();
      if (openaiActive) {
        await this.projectCodexProviderLive(openaiActive, gatewayStatus.port);
        this.log(`Codex gateway config applied on port ${gatewayStatus.port}`);
      } else {
        // undefined = "no explicit choice" — see syncGatewayRoutesWithProviders.
        await this.context.globalState.update(ROUTE_CODEX_STATE_KEY, undefined);
        await this.releaseCodexProxyTakeover();
        this.log('Codex gateway route disabled: active provider has no resolvable model');
      }
    } else if (
      getCodexRoutingSnapshot().routedViaGateway ||
      this.codexLiveBackupCache !== undefined
    ) {
      // Only release when live is still takeover or a pre-takeover backup exists.
      // Avoid repeatedly rebuilding from the active API provider on every sync.
      await this.releaseCodexProxyTakeover();
    }

    if (!gatewayStatus.running) {
      return;
    }
    this.syncFailoverToGateway();
  }

  async disableAndRestoreDirect(config: ClaudeCodeConfigValues): Promise<AiCliGatewayPublicStatus> {
    const upstream = this.resolveUpstreamFromClaudeForm(config);
    await this.gateway.stop();
    await this.releaseCodexProxyTakeover();
    if (upstream.baseUrl && upstream.apiKey) {
      writeClaudeConfig({
        ...config,
        // Keep the raw /v1 upstream in storage, but write Claude a base it can
        // actually append /v1/messages to (see claudeSettingsBaseUrl).
        baseUrl: claudeSettingsBaseUrl(upstream.baseUrl),
        apiKey: upstream.apiKey,
      });
      await this.persistUpstream(upstream);
    }
    await this.persistEnabled(false);
    this.log('Gateway disabled; Claude restored to upstream; Codex released from proxy takeover');
    return this.getPublicStatus();
  }

  async syncUpstreamFromClaudeConfig(config: ClaudeCodeConfigValues): Promise<AiCliGatewayPublicStatus> {
    const enabled = this.context.globalState.get<boolean>(ENABLED_STATE_KEY, false);
    if (!enabled) {
      return this.getPublicStatus();
    }
    return this.enableWithClaudeConfig(config);
  }

  async restoreIfEnabled(): Promise<void> {
    await this.initialize();
    const routeClaude = this.isRouteClaudeViaGateway();
    const routeCodex = this.isRouteCodexViaGateway();
    if (!routeClaude && !routeCodex) {
      if (getCodexRoutingSnapshot().routedViaGateway || this.codexLiveBackupCache !== undefined) {
        await this.releaseCodexProxyTakeover();
      }
      await this.persistEnabled(false);
      return;
    }
    const anthropic = this.getAnthropicProviderForGateway();
    const config = anthropic
      ? this.providerToClaudeConfig(anthropic)
      : readClaudeConfig();
    try {
      await this.enableWithClaudeConfig(config);
    } catch (error) {
      if (getCodexRoutingSnapshot().routedViaGateway || this.codexLiveBackupCache !== undefined) {
        await this.releaseCodexProxyTakeover();
      }
      // Start failed: never leave Claude pointed at a dead local gateway URL.
      if (isLocalGatewayBaseUrl(readClaudeConfig().baseUrl)) {
        await this.applyGatewayRoutes();
      }
      // Keep UI/state aligned with direct configs after a failed restart.
      await this.context.globalState.update(ROUTE_CLAUDE_STATE_KEY, false);
      await this.context.globalState.update(ROUTE_CODEX_STATE_KEY, undefined);
      await this.persistEnabled(false);
      throw error;
    }
  }

  async checkProviderAvailability(
    baseUrl: string,
    apiKey: string,
    apiKind?: AiCliApiKind
  ): Promise<AiCliProviderAvailabilityResult> {
    const result = await fetchProviderModels(baseUrl, apiKey, apiKind);
    if (result.ok) {
      return { ok: true, models: result.models.length, apiKind: result.apiKind };
    }
    return { ok: false, models: 0, error: result.error, detail: result.detail };
  }

  getProviders(): AiCliProviderConfig[] {
    return this.providersCache.map((provider) => ({ ...provider }));
  }

  async saveProviders(providers: AiCliProviderConfig[]): Promise<void> {
    await this.initialize();
    const normalized = providers.map((provider) => this.normalizeProvider(provider));
    const previousIds = new Set(this.providersCache.map((provider) => provider.id));
    for (const provider of normalized) {
      const apiKey = provider.apiKey.trim();
      if (apiKey) {
        await this.context.secrets.store(this.providerSecretKey(provider.id), apiKey);
      } else {
        await this.context.secrets.delete(this.providerSecretKey(provider.id));
      }
      previousIds.delete(provider.id);
    }
    for (const removedId of previousIds) {
      await this.context.secrets.delete(this.providerSecretKey(removedId));
    }
    this.providersCache = normalized;
    await this.context.globalState.update(
      PROVIDERS_STATE_KEY,
      normalized.map((provider) => this.providerMetadata(provider))
    );
    await this.syncGatewayRoutesWithProviders();
    this.syncFailoverToGateway();
  }

  async addProvider(
    provider: Omit<AiCliProviderConfig, 'id' | 'activeClaude' | 'activeCodex' | 'failoverClaude' | 'failoverCodex'> &
      Partial<Pick<AiCliProviderConfig, 'activeClaude' | 'activeCodex' | 'failoverClaude' | 'failoverCodex'>>,
    options?: { liveApply?: 'full' | 'inventory' }
  ): Promise<AiCliProviderConfig> {
    await this.initialize();
    const providers = this.getProviders();
    const id = `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    // Only activate when explicitly requested (e.g. Web import). Do not auto-pick a default vendor.
    const activeClaude = provider.activeClaude === true;
    const activeCodex = provider.activeCodex === true;
    const failoverClaude = provider.failoverClaude ?? false;
    const failoverCodex = provider.failoverCodex ?? false;
    const entry: AiCliProviderConfig = this.normalizeProvider({
      ...provider,
      id,
      activeClaude,
      activeCodex,
      failoverClaude,
      failoverCodex,
    });
    providers.push(entry);
    if (entry.activeClaude) {
      for (const p of providers) {
        p.activeClaude = p.id === entry.id;
      }
    }
    if (entry.activeCodex) {
      for (const p of providers) {
        p.activeCodex = p.id === entry.id;
      }
    }
    await this.saveProviders(providers);
    await this.applyProviderAfterSave(entry, options?.liveApply ?? 'full');
    return entry;
  }

  async removeProvider(id: string): Promise<void> {
    await this.initialize();
    let providers = this.getProviders().filter((p) => p.id !== id);
    const claudeProviders = providers.filter((p) => this.providerHasCredentials(p));
    const codexProviders = providers.filter((p) => providerEligibleForRoleUpstream(p, 'codex'));
    if (claudeProviders.length > 0 && !claudeProviders.some((p) => p.activeClaude)) {
      providers = providers.map((p) =>
        p.id === claudeProviders[0].id ? { ...p, activeClaude: true } : p
      );
    }
    if (codexProviders.length > 0 && !codexProviders.some((p) => p.activeCodex)) {
      providers = providers.map((p) =>
        p.id === codexProviders[0].id ? { ...p, activeCodex: true } : p
      );
    }
    await this.saveProviders(providers);
    const activeClaude = providers.find((p) => p.activeClaude);
    if (activeClaude) {
      await this.applyActiveClaudeProvider(activeClaude);
    } else {
      applyClaudeOfficialSubscription();
    }
    const activeCodex = providers.find((p) => p.activeCodex);
    if (activeCodex) {
      await this.applyActiveCodexProvider(activeCodex);
    } else {
      applyCodexOfficialSubscription();
    }
    if (!this.isRouteClaudeViaGateway() && !this.isRouteCodexViaGateway()) {
      await this.gateway.stop();
      await this.persistEnabled(false);
    } else if (this.gateway.getStatus().running) {
      await this.applyGatewayRoutes();
    }
  }

  async upsertImportedGatewayProvider(
    draft: {
      name: string;
      baseUrl: string;
      apiKey: string;
      apiKind?: AiCliApiKind;
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
      permissionMode?: string;
    },
    options?: { liveApply?: 'full' | 'inventory' }
  ): Promise<AiCliProviderConfig> {
    await this.initialize();
    const providers = this.getProviders();
    const apiKind = draft.apiKind ?? inferApiKindFromBaseUrl(draft.baseUrl);
    const normalizedBaseUrl = resolveProviderBaseUrl(draft.baseUrl, apiKind);
    const existing = providers.find(
      (provider) =>
        provider.name === draft.name ||
        providerUpstream(provider).baseUrl === normalizedBaseUrl
    );
    const payload = {
      name: draft.name,
      baseUrl: draft.baseUrl.trim(),
      apiKey: draft.apiKey.trim(),
      apiKind,
      model: draft.model,
      codexModel: draft.codexModel,
      sonnetModel: draft.sonnetModel,
      opusModel: draft.opusModel,
      fableModel: draft.fableModel,
      haikuModel: draft.haikuModel,
      sonnetDisplayName: draft.sonnetDisplayName,
      opusDisplayName: draft.opusDisplayName,
      fableDisplayName: draft.fableDisplayName,
      haikuDisplayName: draft.haikuDisplayName,
      declareSonnet1m: draft.declareSonnet1m,
      declareOpus1m: draft.declareOpus1m,
      declareFable1m: draft.declareFable1m,
      codexEnable1m: draft.codexEnable1m,
      permissionMode: draft.permissionMode?.trim() || 'bypassPermissions',
      activeClaude: true,
      activeCodex: true,
    };
    if (existing) {
      const apiKey = draft.apiKey.trim() || existing.apiKey.trim();
      return this.updateProvider(existing.id, { ...payload, apiKey }, options);
    }
    return this.addProvider(payload, options);
  }

  async updateProvider(
    id: string,
    patch: Partial<AiCliProviderConfig>,
    options?: { liveApply?: 'full' | 'inventory' }
  ): Promise<AiCliProviderConfig> {
    await this.initialize();
    const providers = this.getProviders();
    const index = providers.findIndex((p) => p.id === id);
    if (index < 0) {
      throw new Error('provider_not_found');
    }
    const next = this.normalizeProvider({ ...providers[index], ...patch, id });
    providers[index] = next;
    if (next.activeClaude) {
      for (const p of providers) {
        p.activeClaude = p.id === id;
      }
    }
    if (next.activeCodex) {
      for (const p of providers) {
        p.activeCodex = p.id === id;
      }
    }
    await this.saveProviders(providers);
    await this.applyProviderAfterSave(next, options?.liveApply ?? 'full');
    return next;
  }

  /**
   * Persist inventory + write CLI config files.
   * `inventory` skips starting/reconciling the local gateway (used by Web import so Confirm cannot hang).
   */
  private async applyProviderAfterSave(
    provider: AiCliProviderConfig,
    liveApply: 'full' | 'inventory'
  ): Promise<void> {
    if (liveApply === 'inventory') {
      await this.applyProviderInventoryOnly(provider);
      return;
    }
    if (provider.activeClaude) {
      await this.applyActiveClaudeProvider(provider);
    }
    if (provider.activeCodex) {
      await this.applyActiveCodexProvider(provider);
    }
  }

  private async applyProviderInventoryOnly(provider: AiCliProviderConfig): Promise<void> {
    const normalized = this.normalizeProvider(provider);
    if (provider.activeClaude) {
      writeClaudeConfig(this.providerToClaudeConfig(normalized));
      await this.persistUpstream(this.providerToGatewayUpstream(normalized));
    }
    if (provider.activeCodex) {
      await this.projectCodexProviderLive(normalized, undefined);
    }
  }

  private async applyActiveClaudeProvider(provider: AiCliProviderConfig): Promise<AiCliGatewayPublicStatus> {
    const normalized = this.normalizeProvider(provider);
    const enabled = this.context.globalState.get<boolean>(ENABLED_STATE_KEY, false);
    if (this.isAnthropicProvider(normalized) && isOfficialSubscriptionProvider(normalized)) {
      if (this.isRouteClaudeViaGateway()) {
        await this.context.globalState.update(ROUTE_CLAUDE_STATE_KEY, false);
      }
      applyClaudeOfficialSubscription(normalized.permissionMode);
      this.log('Claude official subscription: cleared proxy env; run claude and /login if needed');
      if (enabled || this.gateway.getStatus().running) {
        await this.reconcileGatewayAfterDirectSwitch();
      }
      return this.getPublicStatus();
    }
    const config = this.providerToClaudeConfig(normalized);
    // Inventory → live only: write Claude settings / gateway when user already enabled proxy,
    // or write direct upstream when proxy is off. Never auto-flip routeClaude.
    if (this.isRouteClaudeViaGateway()) {
      if (!enabled || !this.gateway.getStatus().running) {
        return this.enableWithClaudeConfig(config);
      }
      await this.applyGatewayRoutes(config);
      return this.getPublicStatus();
    }
    writeClaudeConfig(config);
    await this.persistUpstream(this.providerToGatewayUpstream(normalized));
    return this.getPublicStatus();
  }

  /**
   * One-shot default: route Codex via the local gateway when the user never made
   * an explicit choice (state key undefined) and has no own Codex setup (no
   * user-authored provider config, no official OAuth login, no API-key-only
   * auth.json). An explicit toggle or a value persisted by an older build always
   * wins. Reads are synchronous up to the final state write — do not add awaits
   * in between (e.g. detectCodexOfficialLogin).
   */
  private async maybeEnableCodexRouteByDefault(provider: AiCliProviderConfig): Promise<boolean> {
    const explicitlySet =
      this.context.globalState.get<boolean>(ROUTE_CODEX_STATE_KEY) !== undefined
      // 默认开的(我们写的)不算用户显式选择——官方登录出现时可让位。
      && !this.context.globalState.get<boolean>(ROUTE_CODEX_AUTO_STATE_KEY, false);
    const fileLogin = getCodexOfficialLoginSnapshot();
    const shouldEnable = shouldEnableCodexRouteByDefault({
      explicitlySet,
      userConfigured: isCodexConfiguredByUser(),
      officialLoginPresent:
        fileLogin.present ||
        fileLogin.storeHint === 'api_key_only' ||
        this.codexLoginSnapshot.present,
      hasEligibleProvider:
        providerEligibleForRoleUpstream(provider, 'codex') &&
        Boolean(this.resolveCodexProviderModel(provider)),
    });
    if (!shouldEnable) {
      return false;
    }
    await this.context.globalState.update(ROUTE_CODEX_STATE_KEY, true);
    // 标记为默认开(非用户显式):后续检测到 codex 官方登录出现时,
    // 自动让位并恢复官方订阅配置(2026-11-06:用户反馈场景——先装扩展
    // 后 codex login,官方登录被 gateway 接管,恢复麻烦)。
    await this.context.globalState.update(ROUTE_CODEX_AUTO_STATE_KEY, true);
    this.log('Codex proxy enabled by default (no user-owned Codex config found)');
    return true;
  }

  private async applyActiveCodexProvider(provider: AiCliProviderConfig): Promise<AiCliGatewayPublicStatus> {
    const normalized = this.normalizeProvider(provider);
    const enabled = this.context.globalState.get<boolean>(ENABLED_STATE_KEY, false);
    if (isOfficialSubscriptionProvider(normalized) && normalized.apiKind === 'openai') {
      if (this.isRouteCodexViaGateway()) {
        // undefined = "no explicit choice" — see syncGatewayRoutesWithProviders.
        await this.context.globalState.update(ROUTE_CODEX_STATE_KEY, undefined);
      }
      if (getCodexRoutingSnapshot().routedViaGateway || this.codexLiveBackupCache !== undefined) {
        await this.releaseCodexProxyTakeover();
      }
      applyCodexOfficialSubscription();
      this.log('Codex official subscription: cleared AgentSociety proxy blocks; run codex login if needed');
      if (enabled || this.gateway.getStatus().running) {
        await this.reconcileGatewayAfterDirectSwitch();
      }
      return this.getPublicStatus();
    }
    // Default-on once when the user has no own Codex setup and made no explicit
    // choice; an explicit toggle always wins. Direct projection when proxy off;
    // gateway when already on.
    const autoEnabled = await this.maybeEnableCodexRouteByDefault(normalized);
    if (this.isRouteCodexViaGateway()) {
      try {
        if (!this.gateway.getStatus().running) {
          const anthropic = this.getAnthropicProviderForGateway();
          const config = anthropic
            ? this.providerToClaudeConfig(anthropic)
            : readClaudeConfig();
          return await this.enableWithClaudeConfig(config);
        }
        await this.applyGatewayRoutes();
        return this.getPublicStatus();
      } catch (error) {
        if (!autoEnabled) {
          throw error;
        }
        // An automatic default must not fail the surrounding save/import flow:
        // revert the premature default and keep Codex on the direct projection.
        const message = error instanceof Error ? error.message : String(error);
        this.log(`Codex proxy default-on failed to start the gateway: ${message}`);
        await this.context.globalState.update(ROUTE_CODEX_STATE_KEY, undefined);
      }
    }
    if (getCodexRoutingSnapshot().routedViaGateway || this.codexLiveBackupCache !== undefined) {
      await this.releaseCodexProxyTakeover();
    }
    await this.projectCodexProviderLive(normalized, undefined);
    return this.getPublicStatus();
  }

  private async reconcileGatewayAfterDirectSwitch(): Promise<void> {
    if (!this.isRouteClaudeViaGateway() && !this.isRouteCodexViaGateway()) {
      await this.gateway.stop();
      await this.persistEnabled(false);
      return;
    }
    if (this.gateway.getStatus().running) {
      await this.applyGatewayRoutes();
    }
  }

  async toggleFailover(id: string, role: 'claude' | 'codex'): Promise<void> {
    await this.initialize();
    const providers = this.getProviders();
    const target = providers.find((p) => p.id === id);
    if (!target) {
      throw new Error('provider_not_found');
    }
    const normalized = this.normalizeProvider(target);
    if (!providerEligibleForRoleUpstream(normalized, role)) {
      throw new Error(role === 'codex' ? 'provider_not_eligible_for_codex' : 'provider_not_eligible_for_claude');
    }
    const field = role === 'claude' ? 'failoverClaude' : 'failoverCodex';
    const providersToUpdate = providers.map((p) =>
      p.id === id ? { ...p, [field]: !p[field] } : p
    );
    await this.saveProviders(providersToUpdate);
    this.syncFailoverToGateway();
  }

  async activateProvider(id: string, role: 'claude' | 'codex'): Promise<AiCliGatewayPublicStatus> {
    await this.initialize();
    const providers = this.getProviders();
    const target = providers.find((p) => p.id === id);
    if (!target) {
      throw new Error('provider_not_found');
    }
    const normalized = this.normalizeProvider(target);
    if (!providerSupportsRole(normalized, role) || !providerHasConfiguredCredentials(normalized)) {
      throw new Error(`provider_not_eligible_for_${role}`);
    }
    for (const p of providers) {
      if (role === 'claude') {
        p.activeClaude = p.id === id;
      }
      if (role === 'codex') {
        p.activeCodex = p.id === id;
      }
    }
    await this.saveProviders(providers);
    if (role === 'claude') {
      return this.applyActiveClaudeProvider(target);
    }
    return this.applyActiveCodexProvider(target);
  }

  showLogChannel(): void {
    this.outputChannel.show();
  }

  async syncClaudeConfigFiles(): Promise<AiCliGatewayPublicStatus> {
    await this.initialize();
    const routeClaude = this.isRouteClaudeViaGateway();
    const gatewayStatus = this.gateway.getStatus();
    const mode = resolveManualConfigSyncMode(
      routeClaude,
      Boolean(gatewayStatus.running && gatewayStatus.port)
    );

    if (mode === 'gateway' && gatewayStatus.port) {
      const anthropicProvider = this.getAnthropicProviderForGateway();
      if (!anthropicProvider) {
        throw new Error('no_claude_provider');
      }
      const claudeConfig = this.providerToClaudeConfig(anthropicProvider);
      writeClaudeConfig(this.buildClaudeLiveConfig(gatewayStatus.port, claudeConfig));
      this.ensureGatewayDiscoveryEnv();
    } else {
      const active = this.getActiveClaudeProvider();
      if (!active || !this.isAnthropicProvider(active)) {
        throw new Error('no_claude_provider');
      }
      if (isOfficialSubscriptionProvider(active)) {
        applyClaudeOfficialSubscription(active.permissionMode);
        return this.getPublicStatus();
      }
      writeClaudeConfig(this.providerToClaudeConfig(active));
      if (active.baseUrl.trim() && active.apiKey.trim()) {
        await this.persistUpstream(this.providerToGatewayUpstream(active));
      }
    }

    this.log('Claude config files synced');
    return this.getPublicStatus();
  }

  async syncCodexConfigFiles(): Promise<AiCliGatewayPublicStatus> {
    await this.initialize();
    const routeCodex = this.isRouteCodexViaGateway();
    const gatewayStatus = this.gateway.getStatus();
    const mode = resolveManualConfigSyncMode(
      routeCodex,
      Boolean(gatewayStatus.running && gatewayStatus.port)
    );

    if (mode === 'gateway' && gatewayStatus.port) {
      const openaiActive = this.getOpenAiProviderForGateway();
      if (!openaiActive) {
        throw new Error('no_codex_provider');
      }
      await this.projectCodexProviderLive(openaiActive, gatewayStatus.port);
    } else {
      if (getCodexRoutingSnapshot().routedViaGateway || this.codexLiveBackupCache !== undefined) {
        await this.releaseCodexProxyTakeover();
      } else {
        stripCodexGatewayConfig();
      }
      const active = this.getActiveCodexProvider();
      if (!active) {
        throw new Error('no_codex_provider');
      }
      if (isOfficialSubscriptionProvider(active) && active.apiKind === 'openai') {
        applyCodexOfficialSubscription();
      } else if ((active.apiKind ?? inferApiKindFromBaseUrl(active.baseUrl)) === 'openai') {
        await this.projectCodexProviderLive(active);
      } else {
        throw new Error('no_codex_provider');
      }
    }

    this.log('Codex config files synced');
    return this.getPublicStatus();
  }

  setUsageChangeListener(listener: (() => void) | null): void {
    this.usageChangeListener = listener;
  }

  // ============ Usage tracking ============

  private addUsageRecord(record: TokenUsageRecord): void {
    this.sessionUsage.push(record);
    if (this.sessionUsage.length > MAX_USAGE_RECORDS) {
      this.sessionUsage = this.sessionUsage.slice(-MAX_USAGE_RECORDS);
    }
    if (!this.usagePersistTimer) {
      this.usagePersistTimer = setTimeout(() => {
        this.usagePersistTimer = undefined;
        void this.persistUsage().then(() => {
          this.usageChangeListener?.();
        });
      }, 300);
    }
  }

  async syncClaudeSessionUsage(): Promise<number> {
    await this.initialize();
    await this.persistUsage();
    const stored = await this.getPersistedUsage();
    const persisted = stored.filter((record) => record.model !== 'models-list');
    if (persisted.length !== stored.length) {
      await this.context.globalState.update(USAGE_STATE_KEY, persisted);
    }
    const cursor =
      this.context.globalState.get<ClaudeSessionUsageCursor>(
        CLAUDE_SESSION_CURSOR_STATE_KEY
      ) ?? {};
    const activeProvider = this.getActiveClaudeProvider();
    const result = await scanClaudeSessionUsage(
      cursor,
      activeProvider?.name
    );
    if (result.records.length > 0) {
      const merged = [...persisted];
      for (const record of result.records) {
        const index = merged.findIndex(
          (existing) =>
            existing.source === 'session' &&
            existing.requestId === record.requestId
        );
        if (index >= 0) {
          merged[index] = record;
        } else {
          merged.push(record);
        }
      }
      await this.context.globalState.update(
        USAGE_STATE_KEY,
        merged.slice(-MAX_USAGE_RECORDS)
      );
    }
    await this.context.globalState.update(
      CLAUDE_SESSION_CURSOR_STATE_KEY,
      result.cursor
    );
    return result.records.length;
  }

  getSessionUsage(): TokenUsageRecord[] {
    return this.sessionUsage;
  }

  clearSessionUsage(): void {
    this.sessionUsage = [];
  }

  async getPersistedUsage(): Promise<TokenUsageRecord[]> {
    const raw = this.context.globalState.get<unknown[]>(USAGE_STATE_KEY) ?? [];
    const cleaned = sanitizeUsageRecords(raw);
    if (cleaned.length !== raw.length) {
      await this.context.globalState.update(USAGE_STATE_KEY, cleaned);
    }
    return cleaned;
  }

  async persistUsage(): Promise<void> {
    if (this.sessionUsage.length === 0) {
      await this.usagePersistPromise;
      return;
    }
    const pending = this.sessionUsage;
    this.sessionUsage = [];
    this.usagePersistPromise = this.usagePersistPromise
      .then(async () => {
        const existing = await this.getPersistedUsage();
        const merged = [...existing, ...pending].slice(-MAX_USAGE_RECORDS);
        await this.context.globalState.update(USAGE_STATE_KEY, merged);
      })
      .catch(() => {
        this.sessionUsage = [...pending, ...this.sessionUsage].slice(-MAX_USAGE_RECORDS);
      });
    await this.usagePersistPromise;
  }

  async clearPersistedUsage(): Promise<void> {
    if (this.usagePersistTimer) {
      clearTimeout(this.usagePersistTimer);
      this.usagePersistTimer = undefined;
    }
    this.sessionUsage = [];
    await this.usagePersistPromise;
    await this.context.globalState.update(USAGE_STATE_KEY, []);
  }

  // ============ Codex routing status ============

  getCodexRoutingStatus(): {
    configPath: string;
    authPath: string;
    routed: boolean;
    directConfigured: boolean;
    directUrl?: string;
  } {
    const snap = getCodexRoutingSnapshot();
    return {
      configPath: snap.configPath,
      authPath: snap.authPath,
      routed: snap.routedViaGateway,
      directConfigured: snap.directConfigured,
      directUrl: snap.gatewayBaseUrl,
    };
  }

  // ============ Custom pricing ============

  getCustomPricing(): ModelPricingMap {
    return this.context.globalState.get<ModelPricingMap>(CUSTOM_PRICING_STATE_KEY) ?? {};
  }

  getRemotePricing(): ModelPricingMap {
    return this.context.globalState.get<ModelPricingMap>(REMOTE_PRICING_STATE_KEY) ?? {};
  }

  private getObservedPricingModelIds(): string[] {
    const ids = new Set<string>();
    for (const provider of this.getProviders()) {
      for (const modelId of [
        provider.model,
        provider.sonnetModel,
        provider.opusModel,
        provider.haikuModel,
      ]) {
        if (modelId?.trim()) {
          ids.add(modelId.trim());
        }
      }
    }
    for (const record of this.sessionUsage) {
      if (record.model?.trim()) {
        ids.add(record.model.trim());
      }
    }
    const persisted = sanitizeUsageRecords(
      this.context.globalState.get<unknown[]>(USAGE_STATE_KEY) ?? []
    );
    for (const record of persisted) {
      if (record.model?.trim()) {
        ids.add(record.model.trim());
      }
    }
    return [...ids];
  }

  async refreshObservedRemotePricing(force = false): Promise<ModelPricingMap> {
    const fetchedAt = this.context.globalState.get<number>(REMOTE_PRICING_FETCHED_AT_STATE_KEY, 0);
    const cached = this.getRemotePricing();
    if (
      !force &&
      Object.keys(cached).length > 0 &&
      Date.now() - fetchedAt < REMOTE_PRICING_TTL_MS
    ) {
      return cached;
    }
    const observedModelIds = this.getObservedPricingModelIds();
    if (observedModelIds.length === 0) {
      return cached;
    }
    try {
      const remote = await fetchRemoteGatewayPricing();
      const selected = selectObservedRemotePricing(remote.pricing, observedModelIds);
      const next = { ...cached, ...selected };
      await this.context.globalState.update(REMOTE_PRICING_STATE_KEY, next);
      await this.context.globalState.update(REMOTE_PRICING_FETCHED_AT_STATE_KEY, Date.now());
      if (Object.keys(selected).length > 0) {
        this.log(
          `Pricing cache refreshed from ${remote.sources.join(', ') || 'remote'}: ${Object.keys(selected).length} model(s)`
        );
      }
      return next;
    } catch (error) {
      this.log(`Pricing cache refresh skipped: ${error instanceof Error ? error.message : String(error)}`);
      return cached;
    }
  }

  async saveCustomPricing(pricing: ModelPricingMap): Promise<void> {
    await this.context.globalState.update(CUSTOM_PRICING_STATE_KEY, pricing);
  }

  async clearCustomPricing(): Promise<void> {
    await this.context.globalState.update(CUSTOM_PRICING_STATE_KEY, {});
  }

  getEffectivePricing(): ModelPricingMap {
    return { ...getBuiltinPricing(), ...this.getRemotePricing(), ...this.getCustomPricing() };
  }

  // ============ Failover config ============

  isFailoverEnabled(): boolean {
    return this.context.globalState.get<boolean>(FAILOVER_ENABLED_STATE_KEY, false);
  }

  async setFailoverEnabled(enabled: boolean): Promise<void> {
    await this.context.globalState.update(FAILOVER_ENABLED_STATE_KEY, enabled);
    this.syncFailoverToGateway();
  }

  supportsProviderUsageQuery(baseUrl: string): boolean {
    return supportsProviderUsageQuery(baseUrl);
  }

  async queryProviderUsageById(providerId: string): Promise<ProviderUsageResult> {
    await this.initialize();
    const provider = this.getProviders().find((p) => p.id === providerId);
    if (!provider) {
      throw new Error('provider_not_found');
    }
    const normalized = this.normalizeProvider(provider);
    const apiKind = normalized.apiKind ?? inferApiKindFromBaseUrl(normalized.baseUrl);
    const authMode = inferProviderAuthMode({ ...normalized, apiKind });
    return queryProviderUsage(normalized.baseUrl, normalized.apiKey, { apiKind, authMode });
  }

  private buildClaudeFailoverUpstreams(): AiCliGatewayUpstream[] {
    const providers = this.getProviders().map((p) => this.normalizeProvider(p));
    const active = providers.find(
      (p) => p.activeClaude && providerEligibleForRoleUpstream(p, 'claude')
    );
    const list: AiCliGatewayUpstream[] = [];
    if (active) {
      list.push(this.providerToGatewayUpstream(active));
    }
    const failoverCandidates = providers.filter(
      (p) =>
        p.failoverClaude &&
        p.id !== active?.id &&
        providerEligibleForRoleUpstream(p, 'claude')
    );
    for (const p of failoverCandidates) {
      list.push(this.providerToGatewayUpstream(p));
    }
    const stored = this.getStoredUpstream();
    if (list.length === 0 && stored?.baseUrl && stored.apiKey) {
      return [{ baseUrl: stored.baseUrl.trim(), apiKey: stored.apiKey.trim() }];
    }
    return list;
  }

  private buildCodexFailoverUpstreams(): AiCliGatewayUpstream[] {
    const providers = this.getProviders().map((p) => this.normalizeProvider(p));
    const active = providers.find(
      (p) => p.activeCodex && providerEligibleForRoleUpstream(p, 'codex')
    );
    const list: AiCliGatewayUpstream[] = [];
    if (active) {
      list.push(this.providerToGatewayUpstream(active));
    }
    const failoverCandidates = providers.filter(
      (p) =>
        p.failoverCodex &&
        p.id !== active?.id &&
        providerEligibleForRoleUpstream(p, 'codex')
    );
    for (const p of failoverCandidates) {
      list.push(this.providerToGatewayUpstream(p));
    }
    return list;
  }

  private syncFailoverToGateway(): void {
    if (!this.gateway.getStatus().running) {
      return;
    }
    const openaiProvider = this.isRouteCodexViaGateway()
      ? this.getOpenAiProviderForGateway()
      : undefined;
    if (openaiProvider) {
      this.gateway.setOpenaiUpstream(this.providerToGatewayUpstream(openaiProvider));
    } else {
      this.gateway.setOpenaiUpstream(null);
    }
    this.gateway.configureFailover({
      anthropicUpstreams: this.isRouteClaudeViaGateway()
        ? this.buildClaudeFailoverUpstreams()
        : [],
      openaiUpstreams: this.isRouteCodexViaGateway() ? this.buildCodexFailoverUpstreams() : [],
      enabled: this.isFailoverEnabled(),
    });
  }

  private async applyFailoverUpstream(
    upstream: AiCliGatewayUpstream,
    role: 'claude' | 'codex'
  ): Promise<void> {
    await this.initialize();
    const hydrated = this.getProviders().map((p) => this.normalizeProvider(p));
    const match = hydrated.find((p) => {
      const u = providerUpstream(p);
      return (
        u.baseUrl.trim() === upstream.baseUrl.trim() && u.apiKey.trim() === upstream.apiKey.trim()
      );
    });
    if (match) {
      if (role === 'codex') {
        for (const p of hydrated) {
          p.activeCodex = p.id === match.id;
        }
        await this.saveProviders(hydrated);
        if (this.isRouteCodexViaGateway() && this.gateway.getStatus().running) {
          await this.applyGatewayRoutes();
        }
      } else if (role === 'claude' && this.isAnthropicProvider(match)) {
        for (const p of hydrated) {
          if (this.isAnthropicProvider(p)) {
            p.activeClaude = p.id === match.id;
          }
        }
        await this.saveProviders(hydrated);
      }
    }
    await this.persistUpstream(upstream);
    this.log(`Failover switched ${role} upstream → ${upstream.baseUrl}`);
  }

  private log(message: string): void {
    appendSharedOutputLine(OUTPUT_CHANNEL_GATEWAY, `${new Date().toISOString()} [gateway] ${message}`);
  }
}
