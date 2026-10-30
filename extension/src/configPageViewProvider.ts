/**
 * 配置页视图提供者 (Config Page View Provider)
 *
 * 在首次启动时或用户手动打开时显示配置页，引导用户填写 LLM API 密钥等必要配置，
 * 避免让用户去 Settings 页面编写 JSON 配置。
 *
 * **重要**: 配置现在保存在工作区的 .env 文件中，而不是 VSCode 设置中。
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，注册命令 'aiSocialScientist.openConfigPage'
 * - @extension/src/envManager.ts - .env文件读写管理
 * - @extension/src/services/llmValidator.ts - LLM配置验证服务
 * - @extension/src/services/backendManager.ts - 后端服务管理（配置保存后启动）
 * - @extension/src/webview/configPage/ - 前端React组件 (编译后为configPage.js)
 *
 * 后端API：
 * - @packages/agentsociety2/agentsociety2/backend/app.py - FastAPI后端
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import {
  CLAUDE_SETTINGS_PATH,
  detectClaudeCli,
  isClaudeCodeConfiguredByUser,
  isClaudeCodeEnvCustomized,
  readClaudeConfig,
  writeClaudeConfig,
} from './services/claudeCodeSettings';
import { isCodexConfiguredByUser } from './services/codexSettings';
import { fetchProviderModels } from './services/claudeCodeModels';
import { inferApiKindFromBaseUrl } from './aiCli/officialEndpoints';
import type { AiCliGatewayManager, AiCliProviderConfig } from './services/aiCliGatewayManager';
import type { ClaudeCodeConfigValues } from './webview/configPage/claudeCodeTypes';
import type { WebImportGatewayProviderDraft } from './services/webConfigGatewayImport';
import { getCurrentLanguageCode, localize } from './i18n';
import type { ConfigValues, WorkspaceInfo, EasyPaperConfigValues } from './webview/configPage/types';
import { EnvManager } from './envManager';
import { LLMValidator, PythonValidator, LLMType } from './services/llmValidator';
import { fetchCompat, createTimeoutSignal } from './shared/fetchCompat';
import { CONFIG_PAGE_API_VALIDATE_TIMEOUT_MS } from './services/validateTimeouts';
import { AgentsocietyWebConfigService } from './services/agentsocietyWebConfig';
import type { ConfigHealthStatusBar } from './services/configHealthStatus';
import {
  discoverPythonEnvironments,
  resolveAgentsocietyPython,
} from './services/agentsocietyPythonResolver';
import { ONBOARDING_KEYS, type DefaultLlmValidationCache } from './onboardingState';
import { getBackendAccessUrl } from './runtimeConfig';
import {
  readEasyPaperConfig,
  writeEasyPaperConfig,
} from './services/easyPaperWorkspaceConfig';

const fetch = fetchCompat as unknown as typeof globalThis.fetch;

const DEFAULT_LLM_API_BASE = 'https://api.openai.com/v1';
const DEFAULT_LLM_MODEL = 'gpt-5.5';

export class ConfigPageViewProvider {
  public static currentPanel: ConfigPageViewProvider | undefined;
  private static gatewayManager: AiCliGatewayManager | null = null;
  private static configHealthStatus: ConfigHealthStatusBar | null = null;
  private static readonly viewType = 'aiSocialScientistConfigPage';

  public static attachGatewayManager(manager: AiCliGatewayManager): void {
    ConfigPageViewProvider.gatewayManager = manager;
    manager.setUsageChangeListener(() => {
      void ConfigPageViewProvider.currentPanel?._pushGatewayUsageData();
    });
  }

  public static attachConfigHealthStatus(status: ConfigHealthStatusBar): void {
    ConfigPageViewProvider.configHealthStatus = status;
  }

  private readonly _panel: vscode.WebviewPanel;
  private readonly _extensionPath: string;
  private readonly _context: vscode.ExtensionContext;
  private readonly _envManager: EnvManager;
  private _webConfigImport: AgentsocietyWebConfigService | undefined;
  private _pendingImportedGateway: WebImportGatewayProviderDraft | undefined;
  private _disposables: vscode.Disposable[] = [];

  public static createOrShow(
    context: vscode.ExtensionContext,
    viewColumn: vscode.ViewColumn = vscode.ViewColumn.One
  ): void {
    if (ConfigPageViewProvider.currentPanel) {
      ConfigPageViewProvider.currentPanel._panel.reveal(viewColumn);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      ConfigPageViewProvider.viewType,
      localize('configPage.title'),
      viewColumn,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.file(path.join(context.extensionPath, 'out', 'webview'))
        ]
      }
    );

    ConfigPageViewProvider.currentPanel = new ConfigPageViewProvider(panel, context);
  }

  private constructor(
    panel: vscode.WebviewPanel,
    context: vscode.ExtensionContext
  ) {
    this._panel = panel;
    this._context = context;
    this._extensionPath = context.extensionPath;
    this._envManager = new EnvManager();

    this._panel.webview.html = this._getHtmlForWebview(this._panel.webview);

    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
    this._panel.onDidChangeViewState(
      ({ webviewPanel }) => {
        void webviewPanel.webview.postMessage({
          command: 'configPageVisibility',
          visible: webviewPanel.visible,
        });
      },
      null,
      this._disposables
    );

    this._panel.webview.onDidReceiveMessage(
      async (message: {
        command: string;
        config?: Partial<ConfigValues> | ClaudeCodeConfigValues;
        llmType?: string;
        url?: string;
        baseUrl?: string;
        apiKey?: string;
        enabled?: boolean;
        routeTarget?: 'claude' | 'codex';
        providerId?: string;
        role?: 'claude' | 'codex';
        provider?: unknown;
        apiKind?: 'anthropic' | 'openai';
        pricing?: Record<string, unknown>;
        dismissed?: boolean;
        username?: string;
        password?: string;
        settings?: Record<string, boolean>;
        fingerprint?: string;
      }) => {
        switch (message.command) {
          case 'requestConfig':
            await this._sendInitialConfig();
            await this._panel.webview.postMessage({
              command: 'configPageVisibility',
              visible: this._panel.visible,
            });
            break;
          case 'requestBackendStatus':
            await this._postOverviewStatus();
            break;
          case 'saveConfig':
            await this._handleSaveConfig((message.config || {}) as Partial<ConfigValues>);
            break;
          case 'startBackend':
            await this._handleStartBackend((message.config || {}) as Partial<ConfigValues>);
            break;
          case 'validateConfig':
            await this._handleValidateConfig((message.config || {}) as Partial<ConfigValues>, message.llmType);
            break;
          case 'validatePython':
            await this._handleValidatePython((message.config || {}) as Partial<ConfigValues>);
            break;
          case 'discoverPythonEnvironments':
            await this._handleDiscoverPythonEnvironments();
            break;
          case 'validateLiteratureSearch':
            await this._handleValidateLiteratureSearch((message.config || {}) as Partial<ConfigValues>);
            break;
          case 'closeConfigPage':
            this._panel.dispose();
            break;
          case 'openVscodeSettings':
            await vscode.commands.executeCommand('workbench.action.openSettings', '@aiSocialScientist');
            break;
          case 'openFolder':
            await vscode.commands.executeCommand('workbench.action.files.openFolder');
            break;
          case 'saveClaudeConfig':
            await this._handleSaveClaudeConfig((message.config || {}) as ClaudeCodeConfigValues);
            break;
          case 'fetchClaudeModels':
            await this._handleFetchClaudeModels(
              String(message.baseUrl ?? ''),
              String(message.apiKey ?? ''),
              message.providerId ? String(message.providerId) : undefined,
              message.apiKind === 'openai' || message.apiKind === 'anthropic'
                ? message.apiKind
                : undefined
            );
            break;
          case 'gatewayUpdateProvider':
            await this._handleGatewayUpdateProvider(
              message.provider as AiCliProviderConfig
            );
            break;
          case 'gatewaySetRoute':
            await this._handleGatewaySetRoute(
              message.routeTarget === 'codex' ? 'codex' : 'claude',
              Boolean(message.enabled)
            );
            break;
          case 'gatewayListProviders':
            await this._handleGatewayListProviders();
            break;
          case 'gatewaySaveProvider':
            await this._handleGatewaySaveProvider(
              message.provider as Partial<AiCliProviderConfig>
            );
            break;
          case 'gatewayRemoveProvider':
            await this._handleGatewayRemoveProvider(String(message.providerId ?? ''));
            break;
          case 'gatewayActivateProvider':
            await this._handleGatewayActivateProvider(
              String(message.providerId ?? ''),
              message.role === 'codex' ? 'codex' : 'claude'
            );
            break;
          case 'gatewayToggleFailover':
            await this._handleGatewayToggleFailover(
              String(message.providerId ?? ''),
              message.role === 'codex' ? 'codex' : 'claude'
            );
            break;
          case 'gatewayCheckProvider':
          case 'gatewaySpeedtest':
            await this._handleGatewayCheckProvider(
              String(message.baseUrl ?? ''),
              String(message.apiKey ?? ''),
              message.apiKind === 'openai' || message.apiKind === 'anthropic'
                ? message.apiKind
                : undefined
            );
            break;
          case 'gatewayShowLog':
            ConfigPageViewProvider.gatewayManager?.showLogChannel();
            break;
          case 'gatewayGetUsage':
            await this._handleGatewayGetUsage();
            break;
          case 'gatewayClearUsage':
            await this._handleGatewayClearUsage();
            break;
          case 'gatewayGetPricing':
            await this._handleGatewayGetPricing();
            break;
          case 'gatewayRefreshPricing':
            await this._handleGatewayGetPricing(true);
            break;
          case 'gatewaySavePricing':
            await this._handleGatewaySavePricing(message.pricing);
            break;
          case 'gatewayClearPricing':
            await this._handleGatewayClearPricing();
            break;
          case 'gatewaySetFailover':
            await this._handleGatewaySetFailover(Boolean(message.enabled));
            break;
          case 'gatewaySetOutboundProxy':
            await this._handleGatewaySetOutboundProxy(
              typeof message.url === 'string' ? message.url : '',
              typeof message.username === 'string' ? message.username : undefined,
              typeof message.password === 'string' ? message.password : undefined
            );
            break;
          case 'gatewaySetRectifier':
            await this._handleGatewaySetRectifier(
              message.settings && typeof message.settings === 'object'
                ? (message.settings as Record<string, boolean>)
                : {}
            );
            break;
          case 'gatewaySetOptimizer':
            await this._handleGatewaySetOptimizer(
              message.settings && typeof message.settings === 'object'
                ? (message.settings as Record<string, boolean>)
                : {}
            );
            break;
          case 'refreshCodexOfficialLogin':
            await ConfigPageViewProvider.gatewayManager?.refreshCodexOfficialLogin();
            await this._postGatewayStatus();
            {
              const present =
                ConfigPageViewProvider.gatewayManager?.getPublicStatus().codexOfficialLoginPresent;
              vscode.window.showInformationMessage(
                present
                  ? localize('aiCliGateway.codexLoginDetected')
                  : localize('aiCliGateway.codexLoginNotDetected')
              );
            }
            break;
          case 'gatewayQueryProviderUsage':
            await this._handleGatewayQueryProviderUsage(String(message.providerId ?? ''));
            break;
          case 'restartCodexCli':
            await this._handleRestartCodexCli();
            break;
          case 'restartClaudeCli':
            await this._handleRestartClaudeCli();
            break;
          case 'syncClaudeConfigFiles':
            await this._handleSyncClaudeConfigFiles();
            break;
          case 'syncCodexConfigFiles':
            await this._handleSyncCodexConfigFiles();
            break;
          case 'startCasdoorDeviceAuth':
            await this._handleStartCasdoorDeviceAuth();
            break;
          case 'cancelCasdoorDeviceAuth':
            this._cancelCasdoorDeviceAuth();
            break;
          case 'gatewayUpsertWebImportProvider':
            await this._handleGatewayUpsertWebImportProvider();
            break;
          case 'dismissWebConfigImport':
            this._clearPendingImportedGateway();
            break;
          case 'markInitialSetupCompleted':
            await this._context.globalState.update(ONBOARDING_KEYS.hasCompletedInitialSetup, true);
            break;
          case 'persistDefaultLlmValidation': {
            const fingerprint =
              typeof message.fingerprint === 'string' ? message.fingerprint.trim() : '';
            if (!fingerprint) {
              break;
            }
            const cache: DefaultLlmValidationCache = {
              fingerprint,
              at: Date.now(),
            };
            await this._context.workspaceState.update(ONBOARDING_KEYS.defaultLlmValidation, cache);
            break;
          }
          case 'clearDefaultLlmValidation':
            await this._context.workspaceState.update(ONBOARDING_KEYS.defaultLlmValidation, undefined);
            break;
          case 'saveEasyPaperConfig':
            await this._handleSaveEasyPaperConfig(
              message.config as EasyPaperConfigValues | undefined
            );
            break;
          case 'openUrl':
            if (message.url) {
              await vscode.env.openExternal(vscode.Uri.parse(message.url));
            }
            break;
        }
      },
      null,
      this._disposables
    );
  }

  private async _sendInitialConfig(): Promise<void> {
    // Read from .env file instead of VSCode settings
    const envConfig = this._envManager.readEnv();
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const workspacePath = workspaceFolder?.uri.fsPath;
    const envPath = this._envManager.getEnvPath();
    let envFilePath: string | undefined;
    if (workspacePath && envPath) {
      envFilePath = path.relative(workspacePath, envPath) || path.basename(envPath);
    }

    const hasLlmKey = Boolean(envConfig.llmApiKey?.trim());
    const setupFlag = Boolean(
      this._context.globalState.get<boolean>(ONBOARDING_KEYS.hasCompletedInitialSetup)
    );
    // Completed = flag set (wizard finish / prior save) OR workspace already has a simulation LLM key.
    const hasCompletedInitialSetup = setupFlag || hasLlmKey;

    const workspaceInfo: WorkspaceInfo = {
      hasWorkspace: Boolean(workspaceFolder),
      workspacePath,
      envFilePath,
      hasCompletedInitialSetup,
    };

    const configValues: Partial<ConfigValues> = {
      llmApiKey: envConfig.llmApiKey || '',
      backendHost: envConfig.backendHost || '127.0.0.1',
      backendPort: envConfig.backendPort ?? 8001,
      pythonPath: envConfig.pythonPath || '',
      backendAutoStart: vscode.workspace
        .getConfiguration('aiSocialScientist')
        .get<boolean>('backend.autoStart', false),
      llmApiBase: envConfig.llmApiBase || DEFAULT_LLM_API_BASE,
      llmModel: envConfig.llmModel || DEFAULT_LLM_MODEL,
      backendLogLevel: envConfig.backendLogLevel || 'info',
      llmThinking: envConfig.llmThinking || '',
      coderLlmApiKey: envConfig.coderLlmApiKey || '',
      coderLlmApiBase: envConfig.coderLlmApiBase || '',
      coderLlmModel: envConfig.coderLlmModel || '',
      coderLlmThinking: envConfig.coderLlmThinking || '',
      embeddingApiKey: envConfig.embeddingApiKey || '',
      embeddingApiBase: envConfig.embeddingApiBase || '',
      embeddingModel: envConfig.embeddingModel || 'text-embedding-3-large',
      embeddingDims: envConfig.embeddingDims ?? 1024,
      literatureSearchMcpUrl:
        envConfig.literatureSearchMcpUrl || 'https://llmapi.fiblab.net/mcp/',
      literatureSearchApiKey: envConfig.literatureSearchApiKey || '',
    };

    const defaultLlmValidation = this._context.workspaceState.get<DefaultLlmValidationCache>(
      ONBOARDING_KEYS.defaultLlmValidation
    );

    this._panel.webview.postMessage({
      command: 'initialConfig',
      config: configValues,
      defaultLlmValidation: defaultLlmValidation ?? null,
    });

    this._panel.webview.postMessage({
      command: 'workspaceInfo',
      workspaceInfo: workspaceInfo
    });

    const webAuthPath = path.join(os.homedir(), '.fiblab', 'agentsociety2-auth.json');
    if (fs.existsSync(webAuthPath)) {
      this._panel.webview.postMessage({
        command: 'webConfigAuthCached',
        authPath: webAuthPath,
      });
    }

    await this._sendClaudeInitialConfig();
    await this._sendEasyPaperInitialConfig();
    await this._postOverviewStatus();
  }

  private async _handleDiscoverPythonEnvironments(): Promise<void> {
    try {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      const envConfig = this._envManager.readEnv();
      const environments = discoverPythonEnvironments({
        configuredPath: envConfig.pythonPath,
        workspacePath: workspaceFolder?.uri.fsPath,
        extensionPath: this._context.extensionPath,
      });
      this._panel.webview.postMessage({
        command: 'pythonEnvironmentsResult',
        environments,
      });
    } catch (error) {
      this._panel.webview.postMessage({
        command: 'pythonEnvironmentsResult',
        environments: [],
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  public navigateToAdvancedTab(tab: 'models' | 'python' | 'literature' | 'claude' | 'easypaper'): void {
    this._panel.webview.postMessage({ command: 'navigateAdvanced', tab });
  }

  public refreshBackendStatus(): void {
    void this._postOverviewStatus();
  }

  /** 语言切换后重建 webview，使 `__AS_LANG__` 与标题生效。 */
  public reloadForLanguage(): void {
    this._panel.title = localize('configPage.title');
    this._panel.webview.html = this._getHtmlForWebview(this._panel.webview);
  }

  public static refreshBackendStatusIfOpen(): void {
    void ConfigPageViewProvider.currentPanel?.refreshBackendStatus();
  }

  public static reloadLanguageIfOpen(): void {
    ConfigPageViewProvider.currentPanel?.reloadForLanguage();
  }

  private async _sendClaudeInitialConfig(): Promise<void> {
    const cliStatus = await detectClaudeCli();
    await ConfigPageViewProvider.gatewayManager?.initialize();
    const claudeConfig = ConfigPageViewProvider.gatewayManager?.claudeConfigForUi() ?? readClaudeConfig();
    claudeConfig.permissionMode = vscode.workspace.getConfiguration('claudeCode').get<string>('initialPermissionMode', '');
    const codexStatus = ConfigPageViewProvider.gatewayManager?.getCodexRoutingStatus();
    this._panel.webview.postMessage({
      command: 'initialClaudeConfig',
      config: claudeConfig,
      settingsPath: CLAUDE_SETTINGS_PATH,
      cliStatus,
      gatewayStatus: ConfigPageViewProvider.gatewayManager?.getPublicStatus(),
      codexRouting: codexStatus,
      failoverEnabled: ConfigPageViewProvider.gatewayManager?.isFailoverEnabled() ?? false,
    });
  }

  private async _postGatewayStatus(): Promise<void> {
    if (!ConfigPageViewProvider.gatewayManager) {
      return;
    }
    const manager = ConfigPageViewProvider.gatewayManager;
    this._panel.webview.postMessage({
      command: 'aiCliGatewayStatus',
      status: manager.getPublicStatus(),
    });
    this._panel.webview.postMessage({
      command: 'codexRoutingStatus',
      codexRouting: manager.getCodexRoutingStatus(),
    });
  }

  private async _handleGatewaySetRoute(
    target: 'claude' | 'codex',
    enabled: boolean
  ): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    try {
      await manager.setGatewayRoute(target, enabled);
      await this._postGatewayStatus();
      if (target === 'codex' && enabled) {
        await this._offerCodexRestart(localize('aiCliGateway.codexRestartNeeded'));
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      const localized =
        message === 'route_requires_api'
          ? localize(
            target === 'claude'
              ? 'aiCliGateway.routeClaudeRequiresApi'
              : 'aiCliGateway.routeCodexRequiresApi'
          )
          : message === 'gateway_no_route_selected'
            ? localize('aiCliGateway.noRouteSelected')
          : localize('aiCliGateway.toggleFailed', message);
      vscode.window.showWarningMessage(localized);
      await this._postGatewayStatus();
    }
  }

  private async _handleFetchClaudeModels(
    baseUrl: string,
    apiKey: string,
    providerId?: string,
    apiKind?: 'anthropic' | 'openai'
  ): Promise<void> {
    const result = await fetchProviderModels(baseUrl, apiKey, apiKind);
    if (result.ok) {
      const normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, '');
      if (providerId && providerId !== '__new__' && ConfigPageViewProvider.gatewayManager) {
        const provider = ConfigPageViewProvider.gatewayManager
          .getProviders()
          .find((p) => p.id === providerId);
        if (provider && provider.apiKind !== result.apiKind) {
          await ConfigPageViewProvider.gatewayManager.updateProvider(providerId, {
            ...provider,
            apiKind: result.apiKind,
          });
          await this._postProvidersAndActiveConfig();
        }
      }
      this._panel.webview.postMessage({
        command: 'claudeModelsResult',
        success: true,
        models: result.models,
        providerId,
        apiKind: result.apiKind,
        baseUrl: normalizedBaseUrl,
      });
      return;
    }
    this._panel.webview.postMessage({
      command: 'claudeModelsResult',
      success: false,
      error: result.error,
      detail: result.detail,
      status: result.status,
      providerId,
    });
  }

  private async _handleGatewayListProviders(): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    let providers: AiCliProviderConfig[] = [];
    if (manager) {
      await manager.initialize();
      providers = manager.getProviders();
      await manager.syncGatewayRoutesWithProviders();
    }
    this._panel.webview.postMessage({
      command: 'gatewayProvidersList',
      providers,
    });
    if (manager) {
      const active = manager.getActiveClaudeProvider();
      if (active) {
        this._panel.webview.postMessage({
          command: 'activeProviderConfig',
          config: manager.providerToClaudeConfig(active),
        });
      }
    }
  }

  private async _handleGatewaySaveProvider(provider: Partial<AiCliProviderConfig>): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      this._panel.webview.postMessage({ command: 'gatewayProvidersList', providers: [] });
      return;
    }
    const created = await manager.addProvider({
      name: provider.name?.trim() || provider.baseUrl?.trim() || 'Provider',
      baseUrl: provider.baseUrl?.trim() ?? '',
      apiKey: provider.apiKey?.trim() ?? '',
      apiKind: provider.apiKind ?? inferApiKindFromBaseUrl(provider.baseUrl ?? ''),
      authMode: provider.authMode,
      authHeaderMode: provider.authHeaderMode,
      activeClaude: provider.activeClaude,
      activeCodex: provider.activeCodex,
      failoverClaude: provider.failoverClaude,
      failoverCodex: provider.failoverCodex,
      model: provider.model,
      sonnetModel: provider.sonnetModel,
      opusModel: provider.opusModel,
      fableModel: provider.fableModel,
      haikuModel: provider.haikuModel,
      sonnetDisplayName: provider.sonnetDisplayName,
      opusDisplayName: provider.opusDisplayName,
      fableDisplayName: provider.fableDisplayName,
      haikuDisplayName: provider.haikuDisplayName,
      declareSonnet1m: provider.declareSonnet1m,
      declareOpus1m: provider.declareOpus1m,
      declareFable1m: provider.declareFable1m,
      codexEnable1m: provider.codexEnable1m,
      codexContextWindow: provider.codexContextWindow,
      codexAutoCompactLimit: provider.codexAutoCompactLimit,
      permissionMode: provider.permissionMode,
    });
    await this._postProvidersAndActiveConfig();
    await this._postGatewayStatus();
    if (created.activeClaude) {
      vscode.window.showInformationMessage(localize('aiCliGateway.claudeHotSwitchHint'));
    }
    if (created.activeCodex) {
      await this._offerCodexRestart(localize('aiCliGateway.codexRestartNeeded'));
    }
  }

  private async _handleGatewayUpdateProvider(provider: AiCliProviderConfig): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager || !provider.id) {
      return;
    }
    const updated = await manager.updateProvider(provider.id, provider);
    await this._postGatewayStatus();
    await this._postProvidersAndActiveConfig();
    if (updated.activeClaude) {
      vscode.window.showInformationMessage(localize('aiCliGateway.claudeHotSwitchHint'));
    }
    if (updated.activeCodex) {
      await this._offerCodexRestart(localize('aiCliGateway.codexRestartNeeded'));
    }
  }

  private async _postProvidersAndActiveConfig(): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    this._panel.webview.postMessage({
      command: 'gatewayProvidersList',
      providers: manager.getProviders(),
    });
    const active = manager.getActiveClaudeProvider();
    if (active) {
      this._panel.webview.postMessage({
        command: 'activeProviderConfig',
        config: manager.providerToClaudeConfig(active),
      });
    }
  }

  private async _handleGatewayRemoveProvider(id: string): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    await manager.removeProvider(id);
    this._panel.webview.postMessage({
      command: 'gatewayProvidersList',
      providers: manager.getProviders(),
    });
  }

  private async _handleGatewayActivateProvider(
    id: string,
    role: 'claude' | 'codex'
  ): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    try {
      await manager.activateProvider(id, role);
      await this._postGatewayStatus();
      await this._postProvidersAndActiveConfig();
      if (role === 'claude') {
        vscode.window.showInformationMessage(localize('aiCliGateway.claudeHotSwitchHint'));
      } else {
        await this._offerCodexRestart(localize('aiCliGateway.codexRestartNeeded'));
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      vscode.window.showErrorMessage(localize('aiCliGateway.toggleFailed', message));
      await this._postGatewayStatus();
    }
  }

  private async _handleGatewaySetOutboundProxy(
    url: string,
    username?: string,
    password?: string
  ): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    await manager.setOutboundProxy(
      url.trim()
        ? { url: url.trim(), username: username?.trim() || undefined, password: password?.trim() || undefined }
        : null
    );
    await this._postGatewayStatus();
    vscode.window.showInformationMessage(
      url.trim()
        ? localize('aiCliGateway.outboundProxySaved')
        : localize('aiCliGateway.outboundProxyCleared')
    );
  }

  private async _handleGatewaySetRectifier(settings: Record<string, boolean>): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    await manager.setRectifierSettings(settings);
    await this._postGatewayStatus();
  }

  private async _handleGatewaySetOptimizer(settings: Record<string, boolean>): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    await manager.setOptimizerSettings(settings);
    await this._postGatewayStatus();
  }


  private async _handleGatewayToggleFailover(
    id: string,
    role: 'claude' | 'codex'
  ): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    try {
      await manager.toggleFailover(id, role);
      await this._postGatewayStatus();
      await this._postProvidersAndActiveConfig();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      vscode.window.showErrorMessage(message);
      await this._postGatewayStatus();
    }
  }

  private async _handleGatewayCheckProvider(
    baseUrl: string,
    apiKey: string,
    apiKind?: 'anthropic' | 'openai'
  ): Promise<void> {
    const normalized = baseUrl.trim().replace(/\/+$/, '');
    const result = await fetchProviderModels(normalized, apiKey, apiKind);
    const availability = result.ok
      ? { ok: true as const, models: result.models.length, apiKind: result.apiKind }
      : { ok: false as const, models: 0, error: result.error, detail: result.detail };
    this._panel.webview.postMessage({
      command: 'gatewayCheckProviderResult',
      baseUrl: normalized,
      result: availability,
    });
  }

  private async _handleGatewayGetUsage(): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      this._panel.webview.postMessage({ command: 'gatewayUsageData', records: [] });
      return;
    }
    await manager.syncClaudeSessionUsage();
    await this._postStoredGatewayUsage(manager);
  }

  private async _postStoredGatewayUsage(manager: AiCliGatewayManager): Promise<void> {
    const persisted = await manager.getPersistedUsage();
    const session = manager.getSessionUsage();
    const records = session.length > 0 ? [...persisted, ...session] : persisted;
    this._panel.webview.postMessage({
      command: 'gatewayUsageData',
      records,
      gatewayStatus: manager.getPublicStatus(),
    });
  }

  async _pushGatewayUsageData(): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager || !this._panel.visible) {
      return;
    }
    // Gateway records are already persisted by the manager before this listener
    // fires. Avoid rescanning external CLI session files for every live request.
    await this._postStoredGatewayUsage(manager);
  }

  private async _handleGatewayClearUsage(): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    await manager.clearPersistedUsage();
    this._panel.webview.postMessage({
      command: 'gatewayUsageData',
      records: [],
    });
  }

  private async _handleGatewayGetPricing(force = false): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      this._panel.webview.postMessage({ command: 'gatewayPricingData', builtin: {}, custom: {} });
      return;
    }
    const { getBuiltinPricing } = await import('./services/gatewayModelPricing');
    await manager.refreshObservedRemotePricing(force);
    this._panel.webview.postMessage({
      command: 'gatewayPricingData',
      builtin: getBuiltinPricing(),
      custom: { ...manager.getRemotePricing(), ...manager.getCustomPricing() },
    });
  }

  private async _handleGatewaySavePricing(pricing: unknown): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager || !pricing || typeof pricing !== 'object') {
      return;
    }
    const typed = JSON.parse(JSON.stringify(pricing)) as Record<string, { inputPerMillion: number; outputPerMillion: number; cacheReadPerMillion?: number; cacheCreationPerMillion?: number; cacheCreationLongPerMillion?: number }>;
    await manager.saveCustomPricing(typed);
    await this._handleGatewayGetPricing();
  }

  private async _handleGatewayClearPricing(): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    await manager.clearCustomPricing();
    await this._handleGatewayGetPricing();
  }

  private async _handleGatewaySetFailover(enabled: boolean): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    await manager.setFailoverEnabled(enabled);
    this._panel.webview.postMessage({
      command: 'gatewayFailoverStatus',
      enabled,
    });
  }

  private async _handleGatewayQueryProviderUsage(providerId: string): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager || !providerId) {
      return;
    }
    const provider = manager.getProviders().find((p) => p.id === providerId);
    if (!provider) {
      return;
    }
    const result = await manager.queryProviderUsageById(providerId);
    this._panel.webview.postMessage({
      command: 'gatewayProviderUsageResult',
      providerId,
      baseUrl: provider.baseUrl,
      result,
    });
  }

  private async _offerCodexRestart(message: string): Promise<void> {
    const action = localize('aiCliGateway.restartCodexAction');
    const picked = await vscode.window.showInformationMessage(message, action);
    if (picked === action) {
      await this._restartCodexCli(false);
    }
  }

  /**
   * Write Claude Code permission defaults to user settings.
   * These keys are machine-scoped and cannot be stored in workspace settings.
   */
  private async _applyClaudeCodePermissionSettings(permissionMode?: string): Promise<void> {
    const mode = (permissionMode || '').trim();
    const claudeCfg = vscode.workspace.getConfiguration('claudeCode');
    const target = vscode.ConfigurationTarget.Global;
    if (mode === 'bypassPermissions') {
      await claudeCfg.update('allowDangerouslySkipPermissions', true, target);
      await claudeCfg.update('initialPermissionMode', 'bypassPermissions', target);
      return;
    }
    await claudeCfg.update('allowDangerouslySkipPermissions', undefined, target);
    await claudeCfg.update('initialPermissionMode', undefined, target);
  }

  private async _handleRestartCodexCli(): Promise<void> {
    await this._restartCodexCli(true);
  }

  private async _restartCodexCli(confirm: boolean): Promise<void> {
    const action = localize('aiCliGateway.restartCodexAction');
    if (confirm) {
      const picked = await vscode.window.showWarningMessage(
        localize('aiCliGateway.restartCodexConfirm'),
        { modal: true },
        action
      );
      if (picked !== action) {
        return;
      }
    }

    for (const terminal of vscode.window.terminals) {
      if (/\bcodex\b/i.test(terminal.name)) {
        terminal.dispose();
      }
    }

    const manager = ConfigPageViewProvider.gatewayManager;
    const terminal = vscode.window.createTerminal({
      name: 'Codex',
      env: manager?.buildOutboundProxyEnv(),
    });
    terminal.show(true);
    terminal.sendText('codex');
    vscode.window.showInformationMessage(localize('aiCliGateway.restartCodexStarted'));
  }

  private async _handleRestartClaudeCli(): Promise<void> {
    await this._restartClaudeCli(true);
  }

  private async _restartClaudeCli(confirm: boolean): Promise<void> {
    const action = localize('aiCliGateway.restartClaudeAction');
    if (confirm) {
      const picked = await vscode.window.showWarningMessage(
        localize('aiCliGateway.restartClaudeConfirm'),
        { modal: true },
        action
      );
      if (picked !== action) {
        return;
      }
    }

    for (const terminal of vscode.window.terminals) {
      if (/\bclaude\b/i.test(terminal.name)) {
        terminal.dispose();
      }
    }

    const terminal = vscode.window.createTerminal('Claude Code');
    terminal.show(true);
    terminal.sendText('claude');
    vscode.window.showInformationMessage(localize('aiCliGateway.restartClaudeStarted'));
  }

  private async _handleSyncClaudeConfigFiles(): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    try {
      await manager.syncClaudeConfigFiles();
      await this._postGatewayStatus();
      vscode.window.showInformationMessage(localize('aiCliGateway.syncClaudeConfigDone'));
    } catch (error) {
      const code = error instanceof Error ? error.message : '';
      if (code === 'no_claude_provider') {
        vscode.window.showErrorMessage(localize('aiCliGateway.syncClaudeConfigNoProvider'));
        return;
      }
      if (code === 'gateway_not_running') {
        vscode.window.showErrorMessage(localize('aiCliGateway.syncConfigGatewayStopped'));
        return;
      }
      vscode.window.showErrorMessage(localize('aiCliGateway.syncClaudeConfigFailed'));
    }
  }

  private async _handleSyncCodexConfigFiles(): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    if (!manager) {
      return;
    }
    try {
      await manager.syncCodexConfigFiles();
      await this._postGatewayStatus();
      vscode.window.showInformationMessage(localize('aiCliGateway.syncCodexConfigDone'));
    } catch (error) {
      const code = error instanceof Error ? error.message : '';
      if (code === 'no_codex_provider') {
        vscode.window.showErrorMessage(localize('aiCliGateway.syncCodexConfigNoProvider'));
        return;
      }
      if (code === 'gateway_not_running') {
        vscode.window.showErrorMessage(localize('aiCliGateway.syncConfigGatewayStopped'));
        return;
      }
      vscode.window.showErrorMessage(localize('aiCliGateway.syncCodexConfigFailed'));
    }
  }

  private async _handleSaveClaudeConfig(config: ClaudeCodeConfigValues): Promise<void> {
    try {
      const manager = ConfigPageViewProvider.gatewayManager;
      const active = manager?.getActiveClaudeProvider();
      if (active && manager) {
        await manager.updateProvider(active.id, {
          ...active,
          baseUrl: config.baseUrl,
          apiKey: config.apiKey,
          model: config.model,
          sonnetModel: config.sonnetModel,
          opusModel: config.opusModel,
          fableModel: config.fableModel,
          haikuModel: config.haikuModel,
          permissionMode: config.permissionMode,
        });
      } else if (manager?.getPublicStatus().enabled) {
        await manager.syncUpstreamFromClaudeConfig(config);
      } else {
        writeClaudeConfig(config);
      }

      await this._applyClaudeCodePermissionSettings(config.permissionMode);

      this._panel.webview.postMessage({ command: 'claudeSaveResult', success: true });
      await this._postGatewayStatus();
      await this._postOverviewStatus();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      this._panel.webview.postMessage({
        command: 'claudeSaveResult',
        success: false,
        error: message,
      });
    }
  }

  private async _handleStartCasdoorDeviceAuth(): Promise<void> {
    this._cancelCasdoorDeviceAuth();
    const service = new AgentsocietyWebConfigService();
    this._webConfigImport = service;
    try {
      const imported = await service.importConfig({
        onDeviceAuthStarted: (info) => {
          this._panel.webview.postMessage({
            command: 'casdoorDeviceAuthStarted',
            ...info,
          });
        },
        onPolling: () => {
          this._panel.webview.postMessage({ command: 'casdoorDeviceAuthPolling' });
        },
      });
      if (this._webConfigImport !== service) {
        return;
      }
      this._pendingImportedGateway = imported.gatewayProvider;
      this._panel.webview.postMessage({
        command: 'webConfigImported',
        config: imported.config,
        claudeConfig: imported.claudeConfig,
        easyPaperConfig: imported.easyPaperConfig,
        gatewayProvider: imported.gatewayProvider
          ? { ...imported.gatewayProvider, apiKey: '' }
          : undefined,
        gatewayProviderHasApiKey: Boolean(imported.gatewayProvider?.apiKey?.trim()),
        modelOptions: imported.modelOptions,
        defaults: imported.defaults,
        authPath: imported.authPath,
        codexConfiguredByUser: isCodexConfiguredByUser(),
        claudeConfiguredByUser: isClaudeCodeConfiguredByUser(),
      });
    } catch (err) {
      if (this._webConfigImport !== service) {
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      this._panel.webview.postMessage({
        command: 'casdoorDeviceAuthFailed',
        error: message,
      });
    } finally {
      if (this._webConfigImport === service) {
        this._webConfigImport = undefined;
      }
    }
  }

  private _cancelCasdoorDeviceAuth(): void {
    if (this._webConfigImport) {
      this._webConfigImport.cancel();
      this._webConfigImport = undefined;
    }
    this._clearPendingImportedGateway();
  }

  private _clearPendingImportedGateway(): void {
    this._pendingImportedGateway = undefined;
  }

  private async _handleGatewayUpsertWebImportProvider(): Promise<void> {
    const manager = ConfigPageViewProvider.gatewayManager;
    const draft = this._pendingImportedGateway;
    if (
      !manager ||
      !draft?.name?.trim() ||
      !draft.baseUrl?.trim() ||
      !draft.apiKey?.trim() ||
      !draft.model?.trim() ||
      !draft.sonnetModel?.trim() ||
      !draft.opusModel?.trim() ||
      !draft.haikuModel?.trim()
    ) {
      this._panel.webview.postMessage({
        command: 'webConfigApplyResult',
        success: false,
        error: '导入数据缺少 Gateway 供应商、API 地址、API Key 或 Claude 角色模型。',
      });
      return;
    }
    try {
      // Web import must not start/reconcile the local gateway here — that path can hang
      // Confirm import. Inventory + direct CLI config is enough; wizard CLI step starts it later.
      const provider = await manager.upsertImportedGatewayProvider(draft, {
        liveApply: 'inventory',
      });
      this._pendingImportedGateway = undefined;
      await this._applyClaudeCodePermissionSettings('bypassPermissions');
      await this._postProvidersAndActiveConfig();
      await this._postGatewayStatus();
      this._panel.webview.postMessage({
        command: 'webConfigApplyResult',
        success: true,
        provider: {
          name: provider.name,
          baseUrl: provider.baseUrl,
          hasApiKey: Boolean(provider.apiKey.trim()),
          model: provider.model,
          sonnetModel: provider.sonnetModel,
          opusModel: provider.opusModel,
          fableModel: provider.fableModel,
          haikuModel: provider.haikuModel,
          activeClaude: provider.activeClaude,
          activeCodex: provider.activeCodex,
        },
      });
    } catch (error) {
      this._panel.webview.postMessage({
        command: 'webConfigApplyResult',
        success: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  private async _sendEasyPaperInitialConfig(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this._panel.webview.postMessage({ command: 'initialEasyPaperConfig', config: undefined });
      return;
    }
    const configPath = path.join(workspaceFolder.uri.fsPath, 'easypaper_config.yaml');
    const config = readEasyPaperConfig(configPath);
    this._panel.webview.postMessage({ command: 'initialEasyPaperConfig', config });
  }

  private async _handleSaveEasyPaperConfig(config: EasyPaperConfigValues | undefined): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this._panel.webview.postMessage({
        command: 'easyPaperSaveResult',
        success: false,
        error: 'No workspace open',
      });
      return;
    }
    if (!config) {
      this._panel.webview.postMessage({
        command: 'easyPaperSaveResult',
        success: false,
        error: 'Missing EasyPaper config',
      });
      return;
    }
    try {
      const configPath = path.join(workspaceFolder.uri.fsPath, 'easypaper_config.yaml');
      writeEasyPaperConfig(configPath, config);
      this._panel.webview.postMessage({ command: 'easyPaperSaveResult', success: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this._panel.webview.postMessage({
        command: 'easyPaperSaveResult',
        success: false,
        error: message,
      });
    }
  }

  private async _postOverviewStatus(): Promise<void> {
    const backendStatus = await this._getBackendStatus();
    this._panel.webview.postMessage({
      command: 'backendStatus',
      backendStatus,
      claudeCodeCustomized: isClaudeCodeEnvCustomized(),
    });
  }

  /**
   * 获取后端状态信息
   */
  private async _getBackendStatus(): Promise<{ isRunning: boolean; port?: number; url?: string }> {
    const envConfig = this._envManager.readEnv();
    const fallbackUrl = getBackendAccessUrl(envConfig);

    try {
      const status = await vscode.commands.executeCommand<{ isRunning: boolean; port?: number }>(
        'aiSocialScientist.getBackendStatus'
      );
      if (status?.isRunning) {
        const port = status.port ?? envConfig.backendPort ?? 8001;
        return {
          isRunning: true,
          port,
          url: getBackendAccessUrl({ ...envConfig, backendPort: port }),
        };
      }
    } catch {
      // 命令不存在或执行失败，忽略
    }

    return {
      isRunning: false,
      port: envConfig.backendPort ?? 8001,
      url: fallbackUrl,
    };
  }

  private async _handleSaveConfig(config: Partial<ConfigValues>): Promise<void> {
    try {
      await this._saveConfigInternal(config);
      const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
      const hasTopic = !!(workspacePath && fs.existsSync(path.join(workspacePath, 'TOPIC.md')));
      this._panel.webview.postMessage({
        command: 'saveResult',
        success: true,
        needsInit: !hasTopic,
      });
      if (!hasTopic && (config.llmApiKey ?? '').trim()) {
        void vscode.window
          .showInformationMessage(
            localize('extension.onboarding.afterSaveInit'),
            localize('extension.onboarding.initNow'),
            localize('extension.onboarding.later')
          )
          .then((choice) => {
            if (choice === localize('extension.onboarding.initNow')) {
              void vscode.commands.executeCommand('aiSocialScientist.initProject');
            }
          });
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      this._panel.webview.postMessage({
        command: 'saveResult',
        success: false,
        error: message
      });
    }
  }


  private async _handleStartBackend(config: Partial<ConfigValues>): Promise<void> {
    try {
      await this._saveConfigInternal(config);

      const success = await vscode.commands.executeCommand<boolean>(
        'aiSocialScientist.startBackend',
        { silent: true }
      );

      await this._postOverviewStatus();

      this._panel.webview.postMessage({
        command: 'startBackendResult',
        success: success === true,
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      this._panel.webview.postMessage({
        command: 'startBackendResult',
        success: false,
        error: message
      });
    }
  }

  private async _saveConfigInternal(config: Partial<ConfigValues>): Promise<void> {
    // 检查是否有工作区
    if (!vscode.workspace.workspaceFolders || vscode.workspace.workspaceFolders.length === 0) {
      throw new Error(localize('configPage.noWorkspace'));
    }

    // Write to .env file instead of VSCode settings
    this._envManager.writeEnv({
      llmApiKey: config.llmApiKey,
      backendHost: config.backendHost,
      backendPort: config.backendPort,
      pythonPath: config.pythonPath,
      llmApiBase: config.llmApiBase,
      llmModel: (config.llmModel ?? '').trim() || DEFAULT_LLM_MODEL,
      backendLogLevel: config.backendLogLevel,
      llmThinking: config.llmThinking,
      coderLlmApiKey: config.coderLlmApiKey,
      coderLlmApiBase: config.coderLlmApiBase,
      coderLlmModel: config.coderLlmModel,
      coderLlmThinking: config.coderLlmThinking,
      embeddingApiKey: config.embeddingApiKey,
      embeddingApiBase: config.embeddingApiBase,
      embeddingModel: config.embeddingModel,
      embeddingDims: config.embeddingDims,
      literatureSearchMcpUrl: config.literatureSearchMcpUrl,
      literatureSearchApiKey: config.literatureSearchApiKey,
    });

    if (typeof config.backendAutoStart === 'boolean') {
      await vscode.workspace
        .getConfiguration('aiSocialScientist')
        .update('backend.autoStart', config.backendAutoStart, vscode.ConfigurationTarget.Global);
    }

    const llmKey = (config.llmApiKey ?? '').trim();
    if (llmKey) {
      await this._context.globalState.update(ONBOARDING_KEYS.hasCompletedInitialSetup, true);
    }
  }

  /**
   * 处理 LLM 配置验证请求
   */
  private async _handleValidateConfig(config: Partial<ConfigValues>, llmType: string = 'default'): Promise<void> {
    const validator = new LLMValidator();
    const defaultModel = (config.llmModel ?? '').trim() || DEFAULT_LLM_MODEL;

    let apiKey: string = '';
    let apiBase: string = '';
    let model: string = '';
    let validationType: LLMType = LLMType.Chat;

    switch (llmType) {
      case 'coder':
        apiKey = config.coderLlmApiKey || '';
        apiBase = config.coderLlmApiBase || '';
        model = config.coderLlmModel || defaultModel;
        break;
      case 'embedding':
        apiKey = config.embeddingApiKey || '';
        apiBase = config.embeddingApiBase || '';
        model = config.embeddingModel || 'text-embedding-3-large';
        validationType = LLMType.Embedding;
        break;
      default: // default LLM
        apiKey = config.llmApiKey || '';
        apiBase = config.llmApiBase || '';
        model = defaultModel;
        break;
    }

    // 对非默认模型：若 API Key 或 Base URL 为空，则回落到默认 LLM 配置
    if (!apiKey && llmType !== 'default') {
      apiKey = config.llmApiKey || '';
    }
    if (!apiBase) {
      apiBase = config.llmApiBase || '';
    }

    const result = await validator.validate({ apiKey, apiBase, model }, validationType);

    if (llmType === 'default') {
      ConfigPageViewProvider.configHealthStatus?.updateFromValidation(
        result.success,
        model,
        result.error
      );
    }

    this._panel.webview.postMessage({
      command: 'validationResult',
      llmType,
      success: result.success,
      error: result.error || null,
    });
  }

  /**
   * 处理 Python 环境验证请求
   */
  private async _handleValidatePython(config: Partial<ConfigValues>): Promise<void> {
    const validator = new PythonValidator();
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const resolved = resolveAgentsocietyPython({
      configuredPath: config.pythonPath,
      workspacePath: workspaceFolder?.uri.fsPath,
      extensionPath: this._context.extensionPath,
    });
    const pythonPath = config.pythonPath?.trim() || resolved || '';

    const result = await validator.validate({ pythonPath });

    this._panel.webview.postMessage({
      command: 'validationResult',
      llmType: 'python',
      success: result.success,
      error: result.error || null,
    });
  }

  /**
   * 向 MCP Streamable HTTP 端点发送 JSON-RPC 请求并解析响应。
   *
   * litellm 的 /mcp/ 返回 text/event-stream（每行 `data: {...}`），也可能直接返回 JSON，
   * 这里统一提取出 JSON-RPC payload。叠加检测超时，避免长调用挂起。
   */
  private async _mcpJsonRpc(
    endpoint: string,
    headerMap: Record<string, string> | undefined,
    payload: Record<string, unknown>
  ): Promise<{ ok: boolean; status: number; data: unknown | null }> {
    const headers = {
      ...(headerMap ?? {}),
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
    };
    const { signal, cleanup } = createTimeoutSignal(CONFIG_PAGE_API_VALIDATE_TIMEOUT_MS);
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
        signal,
      });
      const text = await res.text();
      let data: unknown = null;
      for (const line of text.split(/\r?\n/)) {
        if (line.startsWith('data: ')) {
          try {
            data = JSON.parse(line.slice('data: '.length));
          } catch {
            // 忽略无法解析的 data 行
          }
        }
      }
      if (data === null) {
        try {
          data = JSON.parse(text);
        } catch {
          data = null;
        }
      }
      return { ok: res.ok, status: res.status, data };
    } finally {
      cleanup();
    }
  }

  private _literatureAuthHeaders(apiKey: string): Record<string, string> | undefined {
    const trimmed = apiKey.trim();
    if (!trimmed) {
      return undefined;
    }
    return { Authorization: `Bearer ${trimmed}` };
  }

  private _literatureAuthError(status: number, apiKey: string): string {
    if (status === 401 || status === 403) {
      return apiKey.trim()
        ? localize('configPage.validation.literatureAuthInvalid')
        : localize('configPage.validation.literatureAuthRequired');
    }
    return localize('configPage.validation.literatureGatewayError', String(status));
  }

  private static readonly LITERATURE_MCP_TOOL_SUFFIXES = [
    'literature_search',
    'literature_status',
    'literature_ingest_text',
  ] as const;

  /** Validation only requires search + status; ingest is optional and unused by the runtime. */
  private static readonly LITERATURE_MCP_REQUIRED_SUFFIXES = [
    'literature_search',
    'literature_status',
  ] as const;

  private _isLiteratureMcpTool(name: string): boolean {
    return ConfigPageViewProvider.LITERATURE_MCP_TOOL_SUFFIXES.some(
      (suffix) => name === suffix || name.endsWith(`-${suffix}`)
    );
  }

  /** 规范化 MCP Streamable HTTP 端点：必须以 /mcp/ 结尾，返回完整 URL；非法返回 null。 */
  private _literatureMcpEndpoint(mcpUrl: string): string | null {
    try {
      const trimmed = mcpUrl.trim();
      const normalized = trimmed.endsWith('/mcp') ? `${trimmed}/` : trimmed;
      if (!normalized.endsWith('/mcp/')) {
        return null;
      }
      new URL(normalized);
      return normalized;
    } catch {
      return null;
    }
  }

  private _pickLiteratureMcpTool(
    toolNames: string[],
    suffix: (typeof ConfigPageViewProvider.LITERATURE_MCP_TOOL_SUFFIXES)[number]
  ): string | null {
    const literatureTools = toolNames.filter((name) => this._isLiteratureMcpTool(name));
    const exact = literatureTools.find((name) => name === suffix || name.endsWith(`-${suffix}`));
    return exact ?? null;
  }

  private _missingLiteratureTools(toolNames: string[]): string[] {
    return ConfigPageViewProvider.LITERATURE_MCP_REQUIRED_SUFFIXES.filter(
      (suffix) => !this._pickLiteratureMcpTool(toolNames, suffix)
    );
  }

  private async _handleValidateLiteratureSearch(config: Partial<ConfigValues>): Promise<void> {
    const mcpUrl = config.literatureSearchMcpUrl || '';
    const apiKey = config.literatureSearchApiKey || '';
    const authHeaders = this._literatureAuthHeaders(apiKey);

    if (!mcpUrl.trim()) {
      this._panel.webview.postMessage({
        command: 'literatureValidationResult',
        success: false,
        error: '请输入学术文献检索 MCP 地址',
      });
      return;
    }

    if (!apiKey.trim()) {
      this._panel.webview.postMessage({
        command: 'literatureValidationResult',
        success: false,
        error: '需要输入 API Key',
      });
      return;
    }

    if (!mcpUrl.includes('/mcp')) {
      this._panel.webview.postMessage({
        command: 'literatureValidationResult',
        success: false,
        error: 'MCP 地址应为 https://llmapi.fiblab.net/mcp/',
      });
      return;
    }

    // 直接走 MCP Streamable HTTP 端点（与运行时子进程的实际调用方式一致）。
    // 不再使用 /mcp-rest/*：litellm v1.85 的 /mcp-rest/tools/call 要求 server_id，
    // 而 /mcp-rest/tools/list 不返回 server_id，导致检测必然 400 失败。
    const endpoint = this._literatureMcpEndpoint(mcpUrl);
    if (!endpoint) {
      this._panel.webview.postMessage({
        command: 'literatureValidationResult',
        success: false,
        error: '请使用 MCP 网关地址 https://llmapi.fiblab.net/mcp/',
      });
      return;
    }

    const rpcErrorOf = (data: unknown): string | null => {
      const msg = (data as { error?: { message?: unknown } } | null)?.error?.message;
      return typeof msg === 'string' ? msg : null;
    };

    try {
      // 1) initialize 握手
      const init = await this._mcpJsonRpc(endpoint, authHeaders, {
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
          protocolVersion: '2024-11-05',
          capabilities: {},
          clientInfo: { name: 'agentsociety-ext', version: '1' },
        },
      });
      if (!init.ok) {
        this._panel.webview.postMessage({
          command: 'literatureValidationResult',
          success: false,
          error: rpcErrorOf(init.data) ?? this._literatureAuthError(init.status, apiKey),
        });
        return;
      }

      // 2) 发送 initialized 通知（无需响应）
      await this._mcpJsonRpc(endpoint, authHeaders, {
        jsonrpc: '2.0',
        method: 'notifications/initialized',
      });

      // 3) tools/list，确认提供文献检索工具
      const list = await this._mcpJsonRpc(endpoint, authHeaders, {
        jsonrpc: '2.0',
        id: 2,
        method: 'tools/list',
        params: {},
      });
      if (!list.ok) {
        this._panel.webview.postMessage({
          command: 'literatureValidationResult',
          success: false,
          error: rpcErrorOf(list.data) ?? this._literatureAuthError(list.status, apiKey),
        });
        return;
      }
      const toolNames = (
        ((list.data as { result?: { tools?: Array<{ name?: string }> } } | null)?.result?.tools) ??
        []
      )
        .map((tool) => tool.name)
        .filter((name): name is string => Boolean(name));
      const missing = this._missingLiteratureTools(toolNames);
      if (missing.length > 0) {
        this._panel.webview.postMessage({
          command: 'literatureValidationResult',
          success: false,
          error: '网关未提供学术文献检索服务，请确认 API Key 具备文献检索权限',
        });
        return;
      }

      // 4) 实际调用 literature_status 验证服务可用（用工具全名，无需 server_id）
      const statusTool = this._pickLiteratureMcpTool(toolNames, 'literature_status');
      if (!statusTool) {
        this._panel.webview.postMessage({
          command: 'literatureValidationResult',
          success: false,
          error: '无法获取学术文献检索服务状态',
        });
        return;
      }
      const call = await this._mcpJsonRpc(endpoint, authHeaders, {
        jsonrpc: '2.0',
        id: 3,
        method: 'tools/call',
        params: { name: statusTool, arguments: {} },
      });
      if (!call.ok) {
        this._panel.webview.postMessage({
          command: 'literatureValidationResult',
          success: false,
          error: rpcErrorOf(call.data) ?? this._literatureAuthError(call.status, apiKey),
        });
        return;
      }
      const content =
        (call.data as { result?: { content?: Array<{ text?: string }> } } | null)?.result?.content ??
        [];
      const textBlock = content.find((block) => block.text)?.text;
      if (!textBlock) {
        this._panel.webview.postMessage({
          command: 'literatureValidationResult',
          success: false,
          error: '学术文献检索服务未返回有效状态',
        });
        return;
      }

      const statusData = JSON.parse(textBlock) as { sources?: Record<string, unknown> };
      this._panel.webview.postMessage({
        command: 'literatureValidationResult',
        success: true,
        sources: statusData.sources,
      });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      this._panel.webview.postMessage({
        command: 'literatureValidationResult',
        success: false,
        error: `连接失败: ${errorMessage}`,
      });
    }
  }

  private _getHtmlForWebview(webview: vscode.Webview): string {
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.file(path.join(this._extensionPath, 'out', 'webview', 'configPage.js'))
    );

    const nonce = Array.from({ length: 32 }, () => Math.random().toString(36)[2]).join('');
    const lang = getCurrentLanguageCode();
    const csp = [
      "default-src 'none'",
      `img-src ${webview.cspSource} data:`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src ${webview.cspSource} 'nonce-${nonce}'`,
      `connect-src ${webview.cspSource} http://127.0.0.1:* http://localhost:*`,
    ].join('; ');

    return `<!DOCTYPE html>
<html lang="${lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <title>${localize('configPage.title')}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
      background: var(--vscode-editor-background);
      color: var(--vscode-editor-foreground);
      height: 100vh;
      overflow: auto;
    }
    #root { min-height: 100vh; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}">window.__AS_LANG__=${JSON.stringify(lang)};</script>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }

  public dispose(): void {
    ConfigPageViewProvider.currentPanel = undefined;
    this._cancelCasdoorDeviceAuth();
    this._envManager.dispose();
    while (this._disposables.length) {
      const d = this._disposables.pop();
      if (d) { d.dispose(); }
    }
  }
}
