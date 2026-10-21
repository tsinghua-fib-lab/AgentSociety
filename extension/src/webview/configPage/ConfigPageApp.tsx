import * as React from 'react';
import {
  ConfigProvider,
  Layout,
  Form,
  Input,
  Button,
  Typography,
  Alert,
  Space,
  notification,
  Tabs,
  Tooltip,
  Collapse,
  Dropdown,
} from 'antd';
import { SaveOutlined, RocketOutlined, ReloadOutlined, SettingOutlined, MoreOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type {
  AiCliGatewayStatus,
  ClaudeCodeCliStatus,
  ClaudeCodeConfigValues,
  ClaudeModelOption,
  ProviderAvailabilityResult,
} from './claudeCodeTypes';
import type { TokenUsageRecord } from './gatewayUsageTypes';
import type { ModelPricingMap } from './modelPricing';
import type { VSCodeAPI, ConfigValues, WorkspaceInfo, BackendStatus, ValidationState, ImportedModelOptions, EasyPaperConfigValues } from './types';
import { AdvancedConfigSection, type AdvancedTopTab } from './AdvancedConfigSection';
import type { PythonEnvironmentOption } from './PythonEnvironmentPicker';
import { DefaultLlmConfigCard } from './DefaultLlmConfigCard';
import { LiteratureConfigSection } from './LiteratureConfigSection';
import { AiCliConfigSection } from './AiCliConfigSection';
import {
  WebConfigImportPanel,
  type DeviceAuthState,
  type PendingWebImport,
} from './WebConfigImportPanel';
import {
  ConfigSetupWizard,
  WIZARD_STEPS,
  wizardStepIndex,
} from './ConfigSetupWizard';
import { ConfigReadinessOverview } from './ConfigReadinessOverview';
import { ConfigStatusDashboard } from './ConfigStatusDashboard';
import { ConfigWizardStepPanel } from './ConfigWizardStepPanel';
import { ENV_LLM_SLOT } from './envLlmSlots';
import { supportsProviderUsageQuery } from './providerUsageSupport';
import { normalizeProviderBaseUrl } from './providerBaseUrl';
import { autoMapClaudeRoleModels } from './aiCliProviderTypes';
import { advancedPanelInnerStyle } from './configPageStyles';
import {
  ADVANCED_VALIDATION_KEYS,
  type AdvancedValidationKey,
  getAdvancedKeyFingerprint,
} from './advancedValidation';
import { useVscodeTheme } from '../theme';
import 'antd/dist/reset.css';

const { Content } = Layout;
const { Title, Text } = Typography;

const DEFAULT_VALUES: ConfigValues = {
  llmApiKey: '',
  backendHost: '127.0.0.1',
  backendPort: 8001,
  pythonPath: '/usr/local/bin/python3',
  llmApiBase: 'https://api.openai.com/v1',
  llmModel: 'gpt-5.5',
  llmThinking: '',
  backendLogLevel: 'info',
  coderLlmApiKey: '',
  coderLlmApiBase: 'https://api.openai.com/v1',
  coderLlmModel: '',
  coderLlmThinking: '',
  embeddingApiKey: '',
  embeddingApiBase: 'https://api.openai.com/v1',
  embeddingModel: 'text-embedding-3-large',
  embeddingDims: 1024,
  literatureSearchMcpUrl: 'https://llmapi.fiblab.net/mcp/',
  literatureSearchApiKey: '',
};

const DEFAULT_CLAUDE_VALUES: ClaudeCodeConfigValues = {
  apiKey: '',
  baseUrl: '',
  model: '',
  sonnetModel: '',
  opusModel: '',
  fableModel: '',
  haikuModel: '',
  permissionMode: 'bypassPermissions',
};

const DEFAULT_EASYPAPER_VALUES: EasyPaperConfigValues = {
  llmModelName: '',
  llmApiKey: '',
  llmBaseUrl: '',
  vlmEnabled: false,
  vlmModel: '',
  vlmApiKey: '',
  vlmBaseUrl: '',
};

type ConfigPageTab = 'simulation' | 'specialized' | 'literature' | 'cli';

interface ConfigPageAppProps {
  vscode: VSCodeAPI;
}

export const ConfigPageApp: React.FC<ConfigPageAppProps> = ({ vscode }) => {
  const { t } = useTranslation();
  const { isDark, palette, themeConfig } = useVscodeTheme();
  const [form] = Form.useForm<ConfigValues>();
  const [claudeForm] = Form.useForm<ClaudeCodeConfigValues>();
  const [easyPaperForm] = Form.useForm<EasyPaperConfigValues>();
  const watchedValues = Form.useWatch([], form) as Partial<ConfigValues> | undefined;
  const watchedClaudeValues = Form.useWatch([], claudeForm) as Partial<ClaudeCodeConfigValues> | undefined;
  const currentValues = watchedValues || {};
  const claudeValues = watchedClaudeValues || {};
  const [savedEnvConfig, setSavedEnvConfig] = React.useState<Partial<ConfigValues>>({});
  const [savedClaudeConfig, setSavedClaudeConfig] = React.useState<Partial<ClaudeCodeConfigValues>>({});
  const [envDraftOverrides, setEnvDraftOverrides] = React.useState<Partial<ConfigValues>>({});
  const [claudeDraftOverrides, setClaudeDraftOverrides] = React.useState<Partial<ClaudeCodeConfigValues>>({});
  const hasText = (value?: string) => Boolean(value && value.trim());

  const effectiveConfigValues = React.useMemo(
    (): ConfigValues =>
      ({
        ...DEFAULT_VALUES,
        ...savedEnvConfig,
        ...envDraftOverrides,
        ...form.getFieldsValue(true),
        ...currentValues,
      }) as ConfigValues,
    [currentValues, envDraftOverrides, form, savedEnvConfig]
  );

  const effectiveClaudeValues = React.useMemo(
    (): ClaudeCodeConfigValues =>
      ({
        ...DEFAULT_CLAUDE_VALUES,
        ...savedClaudeConfig,
        ...claudeDraftOverrides,
        ...claudeForm.getFieldsValue(true),
        ...claudeValues,
      }) as ClaudeCodeConfigValues,
    [claudeDraftOverrides, claudeForm, claudeValues, savedClaudeConfig]
  );
  const effectiveConfigRef = React.useRef(effectiveConfigValues);
  effectiveConfigRef.current = effectiveConfigValues;

  const getConfigValuesForValidation = React.useCallback((): ConfigValues => effectiveConfigValues, [effectiveConfigValues]);

  const getClaudeValuesForValidation = React.useCallback(
    (): ClaudeCodeConfigValues => effectiveClaudeValues,
    [effectiveClaudeValues]
  );
  const defaultLlmModel = (effectiveConfigValues.llmModel || DEFAULT_VALUES.llmModel || '').trim();
  const defaultLlmApiBase = (effectiveConfigValues.llmApiBase || DEFAULT_VALUES.llmApiBase || '').trim();
  const hasDefaultLlmKey = hasText(effectiveConfigValues.llmApiKey);

  const getEffectiveApiKey = (values: Partial<ConfigValues>, llmType: string): string => {
    switch (llmType) {
      case 'coder':
        return (values.coderLlmApiKey || values.llmApiKey || '').trim();
      case 'embedding':
        return (values.embeddingApiKey || values.llmApiKey || '').trim();
      default:
        return (values.llmApiKey || '').trim();
    }
  };

  const getEffectiveApiBase = (values: Partial<ConfigValues>, llmType: string): string => {
    switch (llmType) {
      case 'coder':
        return (values.coderLlmApiBase || values.llmApiBase || '').trim();
      case 'embedding':
        return (values.embeddingApiBase || values.llmApiBase || '').trim();
      default:
        return (values.llmApiBase || '').trim();
    }
  };

  const getValidationDisabledReason = (llmType: string, values: Partial<ConfigValues>): string | null => {
    if (llmType === 'default') {
      if (!hasText(values.llmApiKey)) {
        return t('configPage.notifications.apiKeyMissing');
      }
      if (!hasText(values.llmApiBase)) {
        return t('configPage.notifications.apiBaseMissing');
      }
      return null;
    }

    if (llmType === 'literature') {
      return hasText(values.literatureSearchMcpUrl) ? null : t('configPage.validation.literatureUrlRequired');
    }

    const apiKey = getEffectiveApiKey(values, llmType);
    if (!hasText(apiKey)) {
      return t('configPage.validation.needsApiKey');
    }

    const apiBase = getEffectiveApiBase(values, llmType);
    if (!hasText(apiBase)) {
      return t('configPage.validation.needsApiBase');
    }

    return null;
  };

  const defaultValidateDisabledReason = getValidationDisabledReason('default', effectiveConfigValues);
  const coderValidateDisabledReason = getValidationDisabledReason('coder', effectiveConfigValues);
  const embeddingValidateDisabledReason = getValidationDisabledReason('embedding', effectiveConfigValues);
  const pythonValidateDisabledReason = null;
  const literatureValidateDisabledReason = getValidationDisabledReason('literature', effectiveConfigValues);
  const [loading, setLoading] = React.useState(false);
  const [savingEasyPaper, setSavingEasyPaper] = React.useState(false);
  const [startingBackend, setStartingBackend] = React.useState(false);
  const [workspaceInfo, setWorkspaceInfo] = React.useState<WorkspaceInfo>({ hasWorkspace: false });

  // Validation status for each LLM type
  const [validationState, setValidationState] = React.useState<Record<string, ValidationState>>({
    default: { validating: false, valid: null, error: null },
    coder: { validating: false, valid: null, error: null },
    embedding: { validating: false, valid: null, error: null },
    python: { validating: false, valid: null, error: null },
    literature: { validating: false, valid: null, error: null },
  });

  const [backendStatus, setBackendStatus] = React.useState<BackendStatus>({ isRunning: false });
  const [claudeCliStatus, setClaudeCliStatus] = React.useState<ClaudeCodeCliStatus>({ installed: false });
  const [claudeSettingsPath, setClaudeSettingsPath] = React.useState('~/.claude/settings.json');
  const [claudeAvailableModels, setClaudeAvailableModels] = React.useState<ClaudeModelOption[]>([]);
  const claudeModelsFetchFingerprintRef = React.useRef<string | null>(null);
  const [aiCliGatewayStatus, setAiCliGatewayStatus] = React.useState<AiCliGatewayStatus>({
    enabled: false,
    running: false,
    routeClaude: false,
    routeCodex: false,
  });
  const [gatewayToggling, setGatewayToggling] = React.useState(false);
  const [claudeProviders, setClaudeProviders] = React.useState<import('./aiCliProviderTypes').AiCliProviderRecord[]>([]);
  const [modelsByProvider, setModelsByProvider] = React.useState<Record<string, ClaudeModelOption[]>>({});
  const [modelsLoadingByProvider, setModelsLoadingByProvider] = React.useState<Record<string, boolean>>({});
  const [modelsErrorByProvider, setModelsErrorByProvider] = React.useState<Record<string, string | null>>({});
  const [providerAvailabilityResults, setProviderAvailabilityResults] = React.useState<
    Record<string, ProviderAvailabilityResult>
  >({});
  const [claudeProvidersLoading, setClaudeProvidersLoading] = React.useState(false);
  const [gatewayUsageRecords, setGatewayUsageRecords] = React.useState<TokenUsageRecord[]>([]);
  const [gatewayUsageLoading, setGatewayUsageLoading] = React.useState(false);
  const [codexRouting, setCodexRouting] = React.useState<{ configPath: string; routed: boolean; directUrl?: string } | null>(null);
  const [failoverEnabled, setFailoverEnabled] = React.useState(false);
  const [providerUsage, setProviderUsage] = React.useState<
    Record<string, import('./claudeCodeTypes').ProviderUsageQueryResult & { loading?: boolean }>
  >({});
  const [providerCheckingUrls, setProviderCheckingUrls] = React.useState<Set<string>>(() => new Set());
  const [customPricing, setCustomPricing] = React.useState<ModelPricingMap>({});
  const [advancedTopTab, setAdvancedTopTab] = React.useState<AdvancedTopTab>('models');
  const [pageTab, setPageTab] = React.useState<ConfigPageTab>('cli');
  const [pythonEnvironmentOptions, setPythonEnvironmentOptions] = React.useState<PythonEnvironmentOption[]>([]);
  const [pythonEnvironmentScanning, setPythonEnvironmentScanning] = React.useState(false);
  const [configCollapseKeys, setConfigCollapseKeys] = React.useState<string[]>([]);
  const [wizardMode, setWizardMode] = React.useState(false);
  const [wizardStep, setWizardStep] = React.useState(0);
  const [wizardFlowCompleted, setWizardFlowCompleted] = React.useState(false);
  /** Host-persisted: first setup already done — prefer dashboard over forced wizard. */
  const [setupCompleted, setSetupCompleted] = React.useState(false);
  /** Session-only: user left wizard via「全部设置」without finishing. */
  const [wizardDismissed, setWizardDismissed] = React.useState(false);
  /** Session-only: user explicitly chose「重新运行配置向导」— overrides completed setup. */
  const [wizardRequested, setWizardRequested] = React.useState(false);
  const wizardRequestedRef = React.useRef(false);
  wizardRequestedRef.current = wizardRequested;
  const [deviceAuth, setDeviceAuth] = React.useState<DeviceAuthState>({ status: 'idle' });
  const [pendingWebImport, setPendingWebImport] = React.useState<PendingWebImport | null>(null);
  const [webImportApplying, setWebImportApplying] = React.useState(false);
  const webImportApplyTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const WEB_IMPORT_APPLY_TIMEOUT_MS = 30_000;
  const pageSectionRef = React.useRef<HTMLDivElement>(null);
  const pythonSectionRef = React.useRef<HTMLDivElement>(null);
  const literatureSectionRef = React.useRef<HTMLDivElement>(null);
  const claudeSectionRef = React.useRef<HTMLDivElement>(null);
  const literatureValidateManualRef = React.useRef(false);
  const pendingStartBackendRef = React.useRef(false);
  const advancedKeyPrevFingerprintRef = React.useRef<Partial<Record<AdvancedValidationKey, string>>>({});
  const advancedKeyValidFingerprintRef = React.useRef<Partial<Record<AdvancedValidationKey, string>>>({});
  const defaultValidFingerprintRef = React.useRef<string | null>(null);
  const advancedKeyValidateTimersRef = React.useRef<
    Partial<Record<AdvancedValidationKey, ReturnType<typeof setTimeout>>>
  >({});
  const ADVANCED_CHANGE_VALIDATE_DELAY_MS = 1500;

  const getDefaultLlmFingerprint = React.useCallback(
    () =>
      JSON.stringify({
        llmApiKey: effectiveConfigValues.llmApiKey,
        llmApiBase: effectiveConfigValues.llmApiBase,
        llmModel: effectiveConfigValues.llmModel,
      }),
    [effectiveConfigValues.llmApiBase, effectiveConfigValues.llmApiKey, effectiveConfigValues.llmModel]
  );

  const markValidFingerprint = React.useCallback(
    (kind: string) => {
      if (kind === 'default') {
        defaultValidFingerprintRef.current = getDefaultLlmFingerprint();
        return;
      }
      if ((ADVANCED_VALIDATION_KEYS as readonly string[]).includes(kind)) {
        const key = kind as AdvancedValidationKey;
        advancedKeyValidFingerprintRef.current[key] = getAdvancedKeyFingerprint(
          key,
          effectiveConfigValues
        );
      }
    },
    [effectiveConfigValues, getDefaultLlmFingerprint]
  );

  const isStillValid = React.useCallback(
    (kind: string): boolean => {
      const state = validationState[kind];
      if (state?.valid !== true) {
        return false;
      }
      if (kind === 'default') {
        return defaultValidFingerprintRef.current === getDefaultLlmFingerprint();
      }
      if ((ADVANCED_VALIDATION_KEYS as readonly string[]).includes(kind)) {
        const key = kind as AdvancedValidationKey;
        return (
          advancedKeyValidFingerprintRef.current[key] ===
          getAdvancedKeyFingerprint(key, effectiveConfigValues)
        );
      }
      return false;
    },
    [effectiveConfigValues, getDefaultLlmFingerprint, validationState]
  );

  const scrollToRef = (ref: React.RefObject<HTMLDivElement | null>) => {
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const jumpToPage = (tab: ConfigPageTab, subTab?: AdvancedTopTab) => {
    setPageTab(tab);
    if (tab === 'specialized') {
      handleScanPythonEnvironments();
    }
    if (tab === 'specialized' && subTab) {
      setAdvancedTopTab(subTab);
    }
    const scrollTarget =
      tab === 'specialized' && subTab === 'python'
        ? pythonSectionRef
        : tab === 'literature'
          ? literatureSectionRef
          : tab === 'cli'
            ? claudeSectionRef
            : pageSectionRef;
    window.setTimeout(() => scrollToRef(scrollTarget), 200);
  };

  const jumpToAdvanced = (tab: AdvancedTopTab | 'literature' | 'claude' = 'models') => {
    if (tab === 'literature') {
      jumpToPage('literature');
      return;
    }
    if (tab === 'claude') {
      jumpToPage('cli');
      return;
    }
    jumpToPage('specialized', tab);
  };

  const openConfigEditor = (tab: ConfigPageTab = 'cli') => {
    jumpToPage(tab);
    setConfigCollapseKeys(['config']);
  };

  const saveDisabledReason = React.useMemo((): string | null => {
    if (!workspaceInfo.hasWorkspace) {
      return t('configPage.noWorkspaceHint');
    }
    if (!hasText(effectiveConfigValues.llmApiKey)) {
      return t('configPage.notifications.apiKeyMissing');
    }
    if (!hasText(effectiveConfigValues.llmApiBase)) {
      return t('configPage.notifications.apiBaseMissing');
    }
    return null;
  }, [effectiveConfigValues.llmApiBase, effectiveConfigValues.llmApiKey, t, workspaceInfo.hasWorkspace]);

  const canSave = !saveDisabledReason;
  const canSaveAndStart = canSave && !startingBackend;

  const hasPersistedLlmConfig =
    hasDefaultLlmKey && hasText(effectiveConfigValues.llmApiBase);

  const isReadyForDashboard = React.useMemo(
    () => workspaceInfo.hasWorkspace && hasPersistedLlmConfig,
    [hasPersistedLlmConfig, workspaceInfo.hasWorkspace]
  );

  const isDashboardMode = React.useMemo(
    () => !wizardMode && isReadyForDashboard,
    [isReadyForDashboard, wizardMode]
  );

  const isConfigCollapsed = !configCollapseKeys.includes('config');
  const showUsageChart =
    wizardFlowCompleted &&
    isDashboardMode &&
    isConfigCollapsed &&
    aiCliGatewayStatus.enabled;

  const handleWizardStepChange = React.useCallback((nextStep: number) => {
    const bounded = Math.max(0, Math.min(nextStep, WIZARD_STEPS.length - 1));
    setWizardStep(bounded);
  }, []);

  const handleCompleteWizard = React.useCallback(
    (options?: { dismissPermanently?: boolean }) => {
      const dismissPermanently = options?.dismissPermanently !== false;
      setWizardRequested(false);
      setWizardMode(false);
      setPageTab('cli');
      if (dismissPermanently) {
        setWizardFlowCompleted(true);
        setSetupCompleted(true);
        setWizardDismissed(false);
        setConfigCollapseKeys([]);
        vscode.postMessage({ command: 'markInitialSetupCompleted' });
        return;
      }
      // Session-only exit: keep auto-wizard for next open.
      setWizardDismissed(true);
    },
    [vscode]
  );

  const handleExitWizard = React.useCallback(() => {
    setWizardRequested(false);
    setWizardDismissed(true);
    setWizardMode(false);
  }, []);

  const handleRerunWizard = React.useCallback(() => {
    setWizardRequested(true);
    setWizardFlowCompleted(false);
    setWizardDismissed(false);
    setWizardMode(true);
    handleWizardStepChange(0);
  }, [handleWizardStepChange]);

  React.useEffect(() => {
    if (!workspaceInfo.hasWorkspace) {
      return;
    }
    // Explicit re-run must win over persisted "setup completed".
    if (wizardRequested) {
      setWizardMode(true);
      return;
    }
    if (setupCompleted || wizardFlowCompleted || wizardDismissed) {
      setWizardMode(false);
      if (setupCompleted || wizardFlowCompleted) {
        setConfigCollapseKeys([]);
      }
      return;
    }
    setWizardMode(true);
    handleWizardStepChange(0);
  }, [
    handleWizardStepChange,
    setupCompleted,
    wizardDismissed,
    wizardFlowCompleted,
    wizardRequested,
    workspaceInfo.hasWorkspace,
  ]);

  const requestBackendStatus = React.useCallback(() => {
    vscode.postMessage({ command: 'requestBackendStatus' });
  }, [vscode]);

  React.useEffect(() => {
    requestBackendStatus();
    const intervalMs = startingBackend ? 1000 : 3000;
    const intervalId = window.setInterval(requestBackendStatus, intervalMs);
    return () => window.clearInterval(intervalId);
  }, [requestBackendStatus, startingBackend]);

  React.useEffect(() => {
    if (!wizardMode || WIZARD_STEPS[wizardStep]?.key !== 'backend') {
      return;
    }
    requestBackendStatus();
  }, [requestBackendStatus, wizardMode, wizardStep]);

  const handleScanPythonEnvironments = React.useCallback(() => {
    setPythonEnvironmentScanning(true);
    vscode.postMessage({ command: 'discoverPythonEnvironments' });
  }, [vscode]);

  // Lazy: only scan when the backend wizard step (or specialized/python UI) needs it.
  React.useEffect(() => {
    if (wizardMode && WIZARD_STEPS[wizardStep]?.key === 'backend') {
      handleScanPythonEnvironments();
    }
  }, [handleScanPythonEnvironments, wizardMode, wizardStep]);

  const resetWorkspaceValidationState = () => {
    for (const key of ADVANCED_VALIDATION_KEYS) {
      const timer = advancedKeyValidateTimersRef.current[key];
      if (timer) {
        clearTimeout(timer);
      }
    }
    advancedKeyValidateTimersRef.current = {};
    advancedKeyPrevFingerprintRef.current = {};
    advancedKeyValidFingerprintRef.current = {};
    defaultValidFingerprintRef.current = null;
    setValidationState({
      default: { validating: false, valid: null, error: null },
      coder: { validating: false, valid: null, error: null },
      embedding: { validating: false, valid: null, error: null },
      python: { validating: false, valid: null, error: null },
      literature: { validating: false, valid: null, error: null },
    });
    vscode.postMessage({ command: 'clearDefaultLlmValidation' });
  };

  const handleResetWorkspaceDefaults = () => {
    resetWorkspaceValidationState();
    setSavedEnvConfig({});
    setEnvDraftOverrides({});
    form.setFieldsValue(DEFAULT_VALUES);
    notification.info({
      message: t('configPage.resetWorkspaceDefaults'),
      placement: 'top',
    });
  };

  const handleResetClaudeDefaults = () => {
    setSavedClaudeConfig({});
    setClaudeDraftOverrides({});
    claudeForm.setFieldsValue(DEFAULT_CLAUDE_VALUES);
    setClaudeAvailableModels([]);
    claudeModelsFetchFingerprintRef.current = null;
    notification.info({
      message: t('configPage.resetClaudeDefaults'),
      placement: 'top',
    });
  };

  const toModelOptions = React.useCallback(
    (names: string[]): ClaudeModelOption[] => names.map((id) => ({ id, name: id })),
    []
  );

  const clearWebImportApplyTimer = React.useCallback(() => {
    if (webImportApplyTimerRef.current) {
      clearTimeout(webImportApplyTimerRef.current);
      webImportApplyTimerRef.current = null;
    }
  }, []);

  const applyImportedWebConfig = React.useCallback(
    (imported: PendingWebImport, options?: { overwriteCodexClaude?: boolean }) => {
      const overwrite = options?.overwriteCodexClaude !== false;
      const importedConfig = imported.config ?? {};
      const importedClaude = imported.claudeConfig ?? {};
      const importedEasyPaper = imported.easyPaperConfig ?? {};
      const mergedEnvConfig = {
        ...form.getFieldsValue(true),
        ...importedConfig,
      } as ConfigValues;

      if (imported.modelOptions) {
        setModelsByProvider((prev) => ({
          ...prev,
          [ENV_LLM_SLOT.default]: toModelOptions(imported.modelOptions!.openaiCompatible),
        }));
        setClaudeAvailableModels(toModelOptions(imported.modelOptions.claudeCode));
      }
      setEnvDraftOverrides((prev) => ({ ...prev, ...importedConfig }));
      form.setFieldsValue(mergedEnvConfig);
      // When the user declines to overwrite their Codex/Claude Code live config,
      // also skip pre-filling the Claude Code form (keep their own values intact).
      if (overwrite && Object.keys(importedClaude).length > 0) {
        setClaudeDraftOverrides((prev) => ({ ...prev, ...importedClaude }));
        claudeForm.setFieldsValue({
          ...claudeForm.getFieldsValue(true),
          ...importedClaude,
        });
      }
      easyPaperForm.setFieldsValue({
        ...easyPaperForm.getFieldsValue(true),
        ...importedEasyPaper,
      });
      if (overwrite && imported.gatewayProvider) {
        setWebImportApplying(true);
        clearWebImportApplyTimer();
        webImportApplyTimerRef.current = setTimeout(() => {
          webImportApplyTimerRef.current = null;
          setWebImportApplying(false);
          notification.error({
            message: t('configPage.webImport.failed'),
            description: t('configPage.webImport.applyTimeout'),
            placement: 'top',
            duration: 8,
          });
        }, WEB_IMPORT_APPLY_TIMEOUT_MS);
        vscode.postMessage({ command: 'gatewayUpsertWebImportProvider' });
        return;
      }
      resetWorkspaceValidationState();
      setPendingWebImport(null);
      setDeviceAuth({ status: 'idle', authPath: imported.authPath });
      if (wizardMode && WIZARD_STEPS[wizardStep]?.key === 'import') {
        handleWizardStepChange(wizardStepIndex('simulation'));
      }
      notification.success({
        message: t('configPage.webImport.success'),
        description: imported.authPath
          ? t('configPage.webImport.successWithAuthPath', { path: imported.authPath })
          : t('configPage.webImport.successDesc'),
        placement: 'top',
        duration: 6,
      });
    },
    [
      claudeForm,
      clearWebImportApplyTimer,
      easyPaperForm,
      form,
      handleWizardStepChange,
      t,
      toModelOptions,
      vscode,
      wizardMode,
      wizardStep,
    ]
  );

  const saveEasyPaperConfig = React.useCallback(() => {
    setSavingEasyPaper(true);
    easyPaperForm
      .validateFields()
      .then((values) => {
        vscode.postMessage({ command: 'saveEasyPaperConfig', config: values });
      })
      .catch(() => {
        setSavingEasyPaper(false);
        notification.warning({
          message: t('easyPaperConfig.validationFailed'),
          placement: 'top',
        });
      });
  }, [easyPaperForm, t, vscode]);

  const handleStartWebConfigImport = React.useCallback(() => {
    setDeviceAuth({ status: 'starting' });
    vscode.postMessage({ command: 'startCasdoorDeviceAuth' });
  }, [vscode]);

  const handleCancelWebConfigImport = React.useCallback(() => {
    vscode.postMessage({ command: 'cancelCasdoorDeviceAuth' });
    setDeviceAuth({ status: 'idle' });
  }, [vscode]);

  const webImportPanel = React.useCallback(
    (variant: 'wizard' | 'header') => (
      <WebConfigImportPanel
        t={t}
        palette={palette}
        vscode={vscode}
        deviceAuth={deviceAuth}
        pendingImport={pendingWebImport}
        applying={webImportApplying}
        onStart={handleStartWebConfigImport}
        onCancel={handleCancelWebConfigImport}
        onConfirm={applyImportedWebConfig}
        prominent={variant === 'wizard'}
        compact={variant === 'header'}
        onDismissConfirm={() => {
          const authPath = pendingWebImport?.authPath;
          vscode.postMessage({ command: 'dismissWebConfigImport' });
          clearWebImportApplyTimer();
          setWebImportApplying(false);
          setPendingWebImport(null);
          setDeviceAuth({ status: 'idle', authPath });
        }}
        notify={(type, message, description) => {
          if (type === 'success') {
            notification.success({ message, description, placement: 'top', duration: 2 });
          } else {
            notification.error({ message, description, placement: 'top', duration: 8 });
          }
        }}
      />
    ),
    [
      applyImportedWebConfig,
      clearWebImportApplyTimer,
      deviceAuth,
      handleCancelWebConfigImport,
      handleStartWebConfigImport,
      palette,
      pendingWebImport,
      t,
      vscode,
      webImportApplying,
    ]
  );

  const resolveClaudeModelsFetchError = React.useCallback(
    (code: string) => {
      const key = `claudeCodeConfig.modelsFetchErrors.${code}`;
      const translated = t(key);
      return translated === key ? t('claudeCodeConfig.modelsFetchErrors.unknown') : translated;
    },
    [t]
  );

  const _fetchClaudeModels = React.useCallback(
    (options?: { force?: boolean }) => {
      const claude = getClaudeValuesForValidation();
      const baseUrl = (claude.baseUrl ?? '').trim();
      const apiKey = (claude.apiKey ?? '').trim();
      if (!baseUrl || !apiKey) {
        setClaudeModelsError(t('claudeCodeConfig.modelsFetchErrors.missing_credentials'));
        return;
      }
      const fingerprint = `${baseUrl}::${apiKey.length}::${apiKey.slice(-4)}`;
      if (!options?.force && claudeModelsFetchFingerprintRef.current === fingerprint) {
        return;
      }
      if (options?.force) {
        claudeModelsFetchFingerprintRef.current = null;
      }
      claudeModelsFetchFingerprintRef.current = fingerprint;
      setClaudeModelsLoading(true);
      setClaudeModelsError(null);
      vscode.postMessage({ command: 'fetchClaudeModels', baseUrl, apiKey });
    },
    [getClaudeValuesForValidation, t, vscode]
  );

  const handleGatewayRouteToggle = React.useCallback(
    (target: 'claude' | 'codex', enabled: boolean) => {
      setGatewayToggling(true);
      vscode.postMessage({ command: 'gatewaySetRoute', routeTarget: target, enabled });
    },
    [vscode]
  );

  const handleQueryProviderUsage = React.useCallback(
    (providerId: string) => {
      setProviderUsage((prev) => ({
        ...prev,
        [providerId]: { ...(prev[providerId] ?? { ok: false }), loading: true },
      }));
      vscode.postMessage({ command: 'gatewayQueryProviderUsage', providerId });
    },
    [vscode]
  );

  const handleSaveClaudeProvider = React.useCallback(
    (provider: import('./aiCliProviderTypes').AiCliProviderRecord) => {
      setClaudeProvidersLoading(true);
      vscode.postMessage({ command: 'gatewayUpdateProvider', provider });
      if (provider.id) {
        handleQueryProviderUsage(provider.id);
      }
    },
    [vscode, handleQueryProviderUsage]
  );

  const handleAddClaudeProvider = React.useCallback(
    (draft: Omit<import('./aiCliProviderTypes').AiCliProviderRecord, 'id'>) => {
      setClaudeProvidersLoading(true);
      vscode.postMessage({ command: 'gatewaySaveProvider', provider: draft });
    },
    [vscode]
  );

  const handleRemoveClaudeProvider = React.useCallback(
    (id: string) => {
      vscode.postMessage({ command: 'gatewayRemoveProvider', providerId: id });
    },
    [vscode]
  );

  const handleActivateClaudeProvider = React.useCallback(
    (id: string, role: 'claude' | 'codex') => {
      setClaudeProvidersLoading(true);
      setGatewayToggling(true);
      vscode.postMessage({ command: 'gatewayActivateProvider', providerId: id, role });
    },
    [vscode]
  );

  const handleToggleFailoverProvider = React.useCallback(
    (id: string, role: 'claude' | 'codex') => {
      vscode.postMessage({ command: 'gatewayToggleFailover', providerId: id, role });
    },
    [vscode]
  );

  const handleFetchProviderModels = React.useCallback(
    (providerId: string, baseUrl: string, apiKey: string, apiKind?: 'anthropic' | 'openai') => {
      if (!apiKey.trim() || !baseUrl.trim()) {
        return;
      }
      setModelsLoadingByProvider((prev) => ({ ...prev, [providerId]: true }));
      setModelsErrorByProvider((prev) => ({ ...prev, [providerId]: null }));
      vscode.postMessage({ command: 'fetchClaudeModels', baseUrl, apiKey, providerId, apiKind });
    },
    [vscode]
  );

  const handleFetchEnvModels = React.useCallback(
    (slotId: string, baseUrl: string, apiKey: string) => {
      handleFetchProviderModels(slotId, baseUrl, apiKey, 'openai');
    },
    [handleFetchProviderModels]
  );

  const handleFetchDefaultLlmModels = React.useCallback(() => {
    handleFetchEnvModels(
      ENV_LLM_SLOT.default,
      effectiveConfigValues.llmApiBase,
      effectiveConfigValues.llmApiKey
    );
  }, [effectiveConfigValues.llmApiBase, effectiveConfigValues.llmApiKey, handleFetchEnvModels]);

  const providerModelsFetchedRef = React.useRef(new Set<string>());

  React.useEffect(() => {
    for (const provider of claudeProviders) {
      if (!provider.apiKey?.trim() || !provider.baseUrl?.trim()) {
        continue;
      }
      if (provider.authMode === 'subscription') {
        continue;
      }
      const fingerprint = `${provider.id}::${provider.baseUrl.trim()}::${provider.apiKey.slice(-4)}`;
      if (providerModelsFetchedRef.current.has(fingerprint)) {
        continue;
      }
      providerModelsFetchedRef.current.add(fingerprint);
      handleFetchProviderModels(provider.id, provider.baseUrl, provider.apiKey, provider.apiKind);
    }
  }, [claudeProviders, handleFetchProviderModels]);

  const handleCheckClaudeProvider = React.useCallback(
    (baseUrl: string, apiKey: string, apiKind?: 'anthropic' | 'openai') => {
      const key = normalizeProviderBaseUrl(baseUrl);
      setProviderCheckingUrls((prev) => new Set(prev).add(key));
      vscode.postMessage({ command: 'gatewayCheckProvider', baseUrl, apiKey, apiKind });
    },
    [vscode]
  );

  const isProviderChecking = React.useCallback(
    (baseUrl: string) => providerCheckingUrls.has(normalizeProviderBaseUrl(baseUrl)),
    [providerCheckingUrls]
  );

  const handleShowClaudeGatewayLog = React.useCallback(() => {
    vscode.postMessage({ command: 'gatewayShowLog' });
  }, [vscode]);

  const handleRefreshUsage = React.useCallback(() => {
    setGatewayUsageLoading(true);
    vscode.postMessage({ command: 'gatewayGetUsage' });
  }, [vscode]);

  React.useEffect(() => {
    handleRefreshUsage();
    const timer = window.setInterval(() => {
      handleRefreshUsage();
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [handleRefreshUsage]);

  const handleClearUsage = React.useCallback(() => {
    vscode.postMessage({ command: 'gatewayClearUsage' });
  }, [vscode]);

  const handleFailoverToggle = React.useCallback((enabled: boolean) => {
    vscode.postMessage({ command: 'gatewaySetFailover', enabled });
    setFailoverEnabled(enabled);
  }, [vscode]);

  const _handleQueryAllProviderUsage = React.useCallback(() => {
    for (const p of claudeProviders) {
      if (supportsProviderUsageQuery(p.baseUrl)) {
        handleQueryProviderUsage(p.id);
      }
    }
  }, [claudeProviders, handleQueryProviderUsage]);

  const handleGetPricing = React.useCallback(() => {
    vscode.postMessage({ command: 'gatewayGetPricing' });
  }, [vscode]);

  const handleRefreshPricing = React.useCallback(() => {
    vscode.postMessage({ command: 'gatewayRefreshPricing' });
  }, [vscode]);

  const handleSavePricing = React.useCallback((pricing: ModelPricingMap) => {
    vscode.postMessage({ command: 'gatewaySavePricing', pricing });
  }, [vscode]);

  const handleClearPricing = React.useCallback(() => {
    vscode.postMessage({ command: 'gatewayClearPricing' });
  }, [vscode]);

  const handleRestartCodex = React.useCallback(() => {
    vscode.postMessage({ command: 'restartCodexCli' });
  }, [vscode]);

  const handleRestartClaude = React.useCallback(() => {
    vscode.postMessage({ command: 'restartClaudeCli' });
  }, [vscode]);

  const handleSyncClaudeConfig = React.useCallback(() => {
    vscode.postMessage({ command: 'syncClaudeConfigFiles' });
  }, [vscode]);

  const handleSyncCodexConfig = React.useCallback(() => {
    vscode.postMessage({ command: 'syncCodexConfigFiles' });
  }, [vscode]);

  const handleSaveOutboundProxy = React.useCallback((url: string) => {
    vscode.postMessage({ command: 'gatewaySetOutboundProxy', url });
  }, [vscode]);

  const handleRectifierChange = React.useCallback((settings: Record<string, boolean>) => {
    vscode.postMessage({ command: 'gatewaySetRectifier', settings });
  }, [vscode]);

  const handleOptimizerChange = React.useCallback((settings: Record<string, boolean>) => {
    vscode.postMessage({ command: 'gatewaySetOptimizer', settings });
  }, [vscode]);

  const handleRefreshCodexOfficialLogin = React.useCallback(() => {
    vscode.postMessage({ command: 'refreshCodexOfficialLogin' });
  }, [vscode]);

  const _handleAutoMapClaudeModels = React.useCallback(() => {
    if (claudeAvailableModels.length === 0) {
      return;
    }
    const current = claudeForm.getFieldsValue();
    claudeForm.setFieldsValue(autoMapClaudeRoleModels(claudeAvailableModels, current));
    notification.success({
      message: t('claudeCodeConfig.autoMapDone'),
      placement: 'top',
    });
  }, [claudeAvailableModels, claudeForm, t]);

  const submitValidation = React.useCallback(
    (llmType: string, values: ConfigValues, options?: { silent?: boolean }) => {
      const silent = options?.silent ?? false;
      const failLocal = (error: string) => {
        setValidationState((prev) => ({
          ...prev,
          [llmType]: { validating: false, valid: false, error },
        }));
        if (!silent) {
          notification.warning({
            message: t('configPage.validationFailed'),
            description: error,
            placement: 'top',
          });
        }
      };

      if (llmType === 'python') {
        setValidationState((prev) => ({
          ...prev,
          python: { validating: true, valid: null, error: null },
        }));
        vscode.postMessage({ command: 'validatePython', config: values });
        return;
      }

      if (['coder', 'embedding'].includes(llmType)) {
        const effectiveApiKey = getEffectiveApiKey(values, llmType);
        if (!effectiveApiKey) {
          failLocal(t('configPage.validation.needsApiKey'));
          return;
        }
        const effectiveApiBase = getEffectiveApiBase(values, llmType);
        if (!effectiveApiBase) {
          failLocal(t('configPage.validation.needsApiBase'));
          return;
        }
        setValidationState((prev) => ({
          ...prev,
          [llmType]: { validating: true, valid: null, error: null },
        }));
        vscode.postMessage({ command: 'validateConfig', config: values, llmType });
        return;
      }

      if (llmType === 'default') {
        const missingField = !values.llmApiKey
          ? t('configPage.notifications.apiKeyMissing')
          : !values.llmApiBase
            ? t('configPage.notifications.apiBaseMissing')
            : '';
        if (missingField) {
          failLocal(missingField);
          return;
        }
        setValidationState((prev) => ({
          ...prev,
          default: { validating: true, valid: null, error: null },
        }));
        vscode.postMessage({ command: 'validateConfig', config: values, llmType });
        return;
      }

      if (llmType === 'literature') {
        if (!hasText(values.literatureSearchMcpUrl)) {
          failLocal(t('configPage.validation.literatureUrlRequired'));
          return;
        }
        setValidationState((prev) => ({
          ...prev,
          literature: { validating: true, valid: null, error: null },
        }));
        vscode.postMessage({ command: 'validateLiteratureSearch', config: values });
      }
    },
    [t, vscode]
  );

  const validateAdvancedItem = React.useCallback(
    (key: AdvancedValidationKey, options?: { silent?: boolean; manual?: boolean }) => {
      const silent = options?.silent ?? !options?.manual;
      const manual = options?.manual ?? false;
      if (!manual && isStillValid(key)) {
        return;
      }
      const configValues = getConfigValuesForValidation();
      if (key === 'literature' && manual) {
        literatureValidateManualRef.current = true;
      }
      submitValidation(key, configValues, { silent });
    },
    [getConfigValuesForValidation, isStillValid, submitValidation]
  );

  const handleValidate = (llmType: string) => {
    const configValues = getConfigValuesForValidation();
    if (llmType === 'literature') {
      literatureValidateManualRef.current = true;
    }
    if (ADVANCED_VALIDATION_KEYS.includes(llmType as AdvancedValidationKey)) {
      validateAdvancedItem(llmType as AdvancedValidationKey, { silent: false, manual: true });
      return;
    }
    submitValidation(llmType, configValues, { silent: false });
  };

  const handleValidateDefault = React.useCallback(() => {
    submitValidation('default', getConfigValuesForValidation(), { silent: false });
  }, [getConfigValuesForValidation, submitValidation]);

  const maybeAdvanceWizardAfterDefaultValidation = React.useCallback(() => {
    if (!wizardMode || WIZARD_STEPS[wizardStep]?.key !== 'simulation') {
      return;
    }
    handleWizardStepChange(wizardStepIndex('save'));
  }, [handleWizardStepChange, wizardMode, wizardStep]);

  React.useEffect(() => {
    if (!workspaceInfo.hasWorkspace) {
      return;
    }

    const envValues = getConfigValuesForValidation();

    for (const key of ADVANCED_VALIDATION_KEYS) {
      const fingerprint = getAdvancedKeyFingerprint(key, envValues);
      const prev = advancedKeyPrevFingerprintRef.current[key];
      const validFingerprint = advancedKeyValidFingerprintRef.current[key];

      if (prev === undefined) {
        advancedKeyPrevFingerprintRef.current[key] = fingerprint;
        continue;
      }
      if (prev === fingerprint) {
        continue;
      }

      advancedKeyPrevFingerprintRef.current[key] = fingerprint;

      if (fingerprint === validFingerprint) {
        setValidationState((prevState) => {
          const cur = prevState[key];
          if (cur?.valid === true && !cur.validating && !cur.error) {
            return prevState;
          }
          return {
            ...prevState,
            [key]: { validating: false, valid: true, error: null },
          };
        });
        continue;
      }

      setValidationState((prevState) => {
        const cur = prevState[key];
        if (cur?.valid === null && cur?.validating === false && !cur?.error) {
          return prevState;
        }
        return {
          ...prevState,
          [key]: { validating: false, valid: null, error: null },
        };
      });

      const existingTimer = advancedKeyValidateTimersRef.current[key];
      if (existingTimer) {
        clearTimeout(existingTimer);
      }
      advancedKeyValidateTimersRef.current[key] = setTimeout(() => {
        validateAdvancedItem(key, { silent: true });
      }, ADVANCED_CHANGE_VALIDATE_DELAY_MS);
    }
  }, [
    getConfigValuesForValidation,
    validateAdvancedItem,
    workspaceInfo.hasWorkspace,
  ]);

  React.useEffect(() => {
    return () => {
      for (const key of ADVANCED_VALIDATION_KEYS) {
        const timer = advancedKeyValidateTimersRef.current[key];
        if (timer) {
          clearTimeout(timer);
        }
      }
    };
  }, []);

  React.useEffect(() => {
    vscode.postMessage({ command: 'requestConfig' });
  }, [vscode]);

  React.useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const message = event.data as { command: string;[key: string]: any };

      if (message.command === 'initialConfig') {
        const config = message.config || {};
        setSavedEnvConfig(config);
        setEnvDraftOverrides({});
        form.setFieldsValue({
          ...DEFAULT_VALUES,
          ...config,
        });
        const cache = message.defaultLlmValidation as { fingerprint?: string } | null | undefined;
        const fingerprint = JSON.stringify({
          llmApiKey: config.llmApiKey ?? DEFAULT_VALUES.llmApiKey ?? '',
          llmApiBase: config.llmApiBase ?? DEFAULT_VALUES.llmApiBase ?? '',
          llmModel: config.llmModel ?? DEFAULT_VALUES.llmModel ?? '',
        });
        if (cache?.fingerprint && cache.fingerprint === fingerprint) {
          defaultValidFingerprintRef.current = fingerprint;
          setValidationState((prev) => ({
            ...prev,
            default: { validating: false, valid: true, error: null },
          }));
        } else {
          defaultValidFingerprintRef.current = null;
          setValidationState((prev) => ({
            ...prev,
            default: { validating: false, valid: null, error: null },
          }));
        }
      } else if (message.command === 'initialClaudeConfig') {
        const msg = message as {
          config?: Partial<ClaudeCodeConfigValues>;
          settingsPath?: string;
          cliStatus?: ClaudeCodeCliStatus;
          gatewayStatus?: AiCliGatewayStatus;
          codexRouting?: { configPath: string; routed: boolean; directUrl?: string };
          failoverEnabled?: boolean;
        };
        setSavedClaudeConfig(msg.config || {});
        setClaudeDraftOverrides({});
        claudeForm.setFieldsValue({
          ...DEFAULT_CLAUDE_VALUES,
          ...msg.config,
        });
        if (msg.settingsPath) {
          setClaudeSettingsPath(msg.settingsPath);
        }
        if (msg.cliStatus) {
          setClaudeCliStatus(msg.cliStatus);
        }
        const gatewayMsg = message as { gatewayStatus?: AiCliGatewayStatus };
        if (gatewayMsg.gatewayStatus) {
          setAiCliGatewayStatus(gatewayMsg.gatewayStatus);
        }
        if (msg.codexRouting) {
          setCodexRouting(msg.codexRouting);
        }
        if (typeof msg.failoverEnabled === 'boolean') {
          setFailoverEnabled(msg.failoverEnabled);
        }
        vscode.postMessage({ command: 'gatewayListProviders' });
        vscode.postMessage({ command: 'gatewayGetUsage' });
      } else if (message.command === 'activeProviderConfig') {
        const apMsg = message as { config?: Partial<ClaudeCodeConfigValues> };
        if (apMsg.config) {
          setSavedClaudeConfig(apMsg.config);
          claudeForm.setFieldsValue({ ...DEFAULT_CLAUDE_VALUES, ...apMsg.config });
        }
      } else if (message.command === 'aiCliGatewayStatus') {
        setGatewayToggling(false);
        const statusMsg = message as { status?: AiCliGatewayStatus };
        if (statusMsg.status) {
          setAiCliGatewayStatus(statusMsg.status);
        }
        vscode.postMessage({ command: 'gatewayListProviders' });
        vscode.postMessage({ command: 'gatewayGetUsage' });
      } else if (message.command === 'codexRoutingStatus') {
        const routeMsg = message as { codexRouting?: { configPath: string; routed: boolean; directUrl?: string } };
        if (routeMsg.codexRouting) {
          setCodexRouting(routeMsg.codexRouting);
        }
      } else if (message.command === 'gatewayProvidersList') {
        const provMsg = message as { providers?: import('./aiCliProviderTypes').AiCliProviderRecord[] };
        setClaudeProviders(provMsg.providers ?? []);
        setClaudeProvidersLoading(false);
      } else if (
        message.command === 'gatewayCheckProviderResult' ||
        message.command === 'gatewaySpeedtestResult'
      ) {
        const stMsg = message as { baseUrl: string; result: ProviderAvailabilityResult };
        const key = normalizeProviderBaseUrl(stMsg.baseUrl);
        setProviderCheckingUrls((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
        setProviderAvailabilityResults((prev) => ({ ...prev, [key]: stMsg.result }));
        if (stMsg.result.ok) {
          notification.success({
            message: t('claudeCodeConfig.providerCheckSuccess'),
            description: t('claudeCodeConfig.providerAvailableWithProtocol', {
              count: stMsg.result.models,
              protocol:
                stMsg.result.apiKind === 'openai'
                  ? t('claudeCodeConfig.providerProtocolOpenAiDetected')
                  : t('claudeCodeConfig.providerProtocolAnthropicDetected'),
            }),
            placement: 'top',
            duration: 3,
          });
        } else {
          const errorKey = stMsg.result.error
            ? `claudeCodeConfig.modelsFetchErrors.${stMsg.result.error}`
            : '';
          const errorText =
            errorKey && t(errorKey) !== errorKey
              ? t(errorKey)
              : stMsg.result.error ?? t('claudeCodeConfig.providerUnavailable');
          notification.error({
            message: t('claudeCodeConfig.providerCheckFailed'),
            description: stMsg.result.detail
              ? `${errorText}: ${stMsg.result.detail}`
              : errorText,
            placement: 'top',
          });
        }
      } else if (message.command === 'casdoorDeviceAuthStarted') {
        const authMsg = message as {
          userCode?: string;
          verificationUri?: string;
          verificationUriComplete?: string;
          expiresIn?: number;
        };
        setDeviceAuth({
          status: 'waiting',
          userCode: authMsg.userCode,
          verificationUri: authMsg.verificationUri,
          verificationUriComplete: authMsg.verificationUriComplete,
          expiresIn: authMsg.expiresIn,
        });
      } else if (message.command === 'casdoorDeviceAuthPolling') {
        setDeviceAuth((prev) => ({ ...prev, status: 'polling' }));
      } else if (message.command === 'casdoorDeviceAuthFailed') {
        const msg = message as { error?: string };
        setDeviceAuth({ status: 'idle' });
        notification.error({
          message: t('configPage.webImport.failed'),
          description: msg.error,
          placement: 'top',
          duration: 8,
        });
      } else if (message.command === 'webConfigAuthCached') {
        const msg = message as { authPath?: string };
        if (msg.authPath) {
          setDeviceAuth((prev) => ({ ...prev, status: 'idle', authPath: msg.authPath }));
        }
      } else if (message.command === 'webConfigImported') {
        const msg = message as {
          config?: Partial<ConfigValues>;
          claudeConfig?: Partial<ClaudeCodeConfigValues>;
          easyPaperConfig?: Partial<EasyPaperConfigValues>;
          gatewayProvider?: PendingWebImport['gatewayProvider'];
          gatewayProviderHasApiKey?: boolean;
          modelOptions?: ImportedModelOptions;
          authPath?: string;
          codexConfiguredByUser?: boolean;
          claudeConfiguredByUser?: boolean;
        };
        setPendingWebImport({
          config: msg.config,
          claudeConfig: msg.claudeConfig,
          easyPaperConfig: msg.easyPaperConfig,
          gatewayProvider: msg.gatewayProvider,
          gatewayProviderHasApiKey: msg.gatewayProviderHasApiKey,
          modelOptions: msg.modelOptions,
          authPath: msg.authPath,
          codexConfiguredByUser: msg.codexConfiguredByUser,
          claudeConfiguredByUser: msg.claudeConfiguredByUser,
        });
        setDeviceAuth({ status: 'idle', authPath: msg.authPath });
      } else if (message.command === 'webConfigApplyResult') {
        const msg = message as {
          success?: boolean;
          error?: string;
          provider?: {
            name?: string;
            hasApiKey?: boolean;
            model?: string;
            sonnetModel?: string;
            opusModel?: string;
            haikuModel?: string;
            activeClaude?: boolean;
            activeCodex?: boolean;
          };
        };
        clearWebImportApplyTimer();
        setWebImportApplying(false);
        if (msg.success) {
          const authPath = pendingWebImport?.authPath;
          resetWorkspaceValidationState();
          setPendingWebImport(null);
          setDeviceAuth({ status: 'idle', authPath });
          if (wizardMode && WIZARD_STEPS[wizardStep]?.key === 'import') {
            handleWizardStepChange(wizardStepIndex('simulation'));
          }
          notification.success({
            message: t('configPage.webImport.success'),
            description: t('configPage.webImport.successWithGateway', {
              name: msg.provider?.name ?? 'Fiblab',
            }),
            placement: 'top',
            duration: 6,
          });
        } else {
          notification.error({
            message: t('configPage.webImport.failed'),
            description:
              msg.error ??
              t('configPage.webImport.gatewayApplyInvalid'),
            placement: 'top',
            duration: 8,
          });
        }
      } else if (message.command === 'initialEasyPaperConfig') {
        const msg = message as { config?: EasyPaperConfigValues };
        easyPaperForm.setFieldsValue({
          ...DEFAULT_EASYPAPER_VALUES,
          ...msg.config,
        });
      } else if (message.command === 'easyPaperSaveResult') {
        const msg = message as { success?: boolean; error?: string };
        setSavingEasyPaper(false);
        if (msg.success) {
          if (wizardMode && WIZARD_STEPS[wizardStep]?.key === 'easypaper') {
            handleWizardStepChange(wizardStep + 1);
          } else {
            notification.success({
              message: t('easyPaperConfig.saveSuccess'),
              placement: 'top',
            });
          }
        } else {
          notification.error({
            message: t('easyPaperConfig.saveFailed'),
            description: msg.error,
            placement: 'top',
          });
        }
      } else if (message.command === 'gatewayUsageData') {
        setGatewayUsageLoading(false);
        const usageMsg = message as {
          records?: TokenUsageRecord[];
          gatewayStatus?: AiCliGatewayStatus;
        };
        setGatewayUsageRecords(usageMsg.records ?? []);
        if (usageMsg.gatewayStatus) {
          setAiCliGatewayStatus(usageMsg.gatewayStatus);
        }
        vscode.postMessage({ command: 'gatewayGetPricing' });
      } else if (message.command === 'gatewayPricingData') {
        const priceMsg = message as { custom?: ModelPricingMap };
        setCustomPricing(priceMsg.custom ?? {});
      } else if (message.command === 'gatewayFailoverStatus') {
        const foMsg = message as { enabled?: boolean };
        setFailoverEnabled(foMsg.enabled ?? false);
      } else if (message.command === 'gatewayProviderUsageResult') {
        const uMsg = message as {
          providerId?: string;
          result?: import('./claudeCodeTypes').ProviderUsageQueryResult;
        };
        if (uMsg.providerId && uMsg.result) {
          setProviderUsage((prev) => ({
            ...prev,
            [uMsg.providerId!]: { ...uMsg.result!, loading: false },
          }));
        }
      } else if (message.command === 'navigateAdvanced') {
        const tab = (message as { tab?: AdvancedTopTab }).tab ?? 'models';
        jumpToAdvanced(tab);
      } else if (message.command === 'workspaceInfo') {
        const info = (message.workspaceInfo || { hasWorkspace: false }) as WorkspaceInfo;
        setWorkspaceInfo(info);
        if (info.hasCompletedInitialSetup) {
          setSetupCompleted(true);
          // Leave wizardMode to the effect so a user-requested re-run is not force-closed.
          if (!wizardRequestedRef.current) {
            setWizardFlowCompleted(true);
            setPageTab('cli');
            setConfigCollapseKeys([]);
          }
        }
      } else if (message.command === 'backendStatus') {
        setBackendStatus(message.backendStatus || { isRunning: false });
      } else if (message.command === 'claudeSaveResult') {
        const msg = message as { success?: boolean; error?: string };
        if (!msg.success && msg.error) {
          notification.error({
            message: t('claudeCodeConfig.saveFailed'),
            description: msg.error,
            placement: 'top',
          });
        }
      } else if (message.command === 'claudeModelsResult') {
        const msg = message as {
          success?: boolean;
          models?: ClaudeModelOption[];
          error?: string;
          detail?: string;
          providerId?: string;
          apiKind?: 'anthropic' | 'openai';
          baseUrl?: string;
        };
        const pid = msg.providerId;
        if (!pid) {
          return;
        }
        setModelsLoadingByProvider((prev) => ({ ...prev, [pid]: false }));
        if (msg.success && msg.models) {
          setModelsByProvider((prev) => ({ ...prev, [pid]: msg.models! }));
          setModelsErrorByProvider((prev) => ({ ...prev, [pid]: null }));
          if (msg.baseUrl && msg.apiKind) {
            const normalizedBaseUrl = String(msg.baseUrl).trim().replace(/\/+$/, '');
            setProviderAvailabilityResults((prev) => ({
              ...prev,
              [normalizedBaseUrl]: { ok: true, models: msg.models?.length ?? 0, apiKind: msg.apiKind },
            }));
          }
        } else {
          const errorText = resolveClaudeModelsFetchError(String(msg.error ?? 'unknown'));
          setModelsErrorByProvider((prev) => ({
            ...prev,
            [pid]: msg.detail ? `${errorText}: ${msg.detail}` : errorText,
          }));
        }
      } else if (message.command === 'pythonEnvironmentsResult') {
        const envMsg = message as { environments?: PythonEnvironmentOption[]; error?: string };
        setPythonEnvironmentScanning(false);
        setPythonEnvironmentOptions(envMsg.environments ?? []);
        if (envMsg.error) {
          notification.warning({
            message: t('configPage.python.scanFailed'),
            description: envMsg.error,
            placement: 'top',
          });
        }
      } else if (message.command === 'saveResult') {
        const msg = message as { success?: boolean; error?: string; needsInit?: boolean };
        setLoading(false);
        if (msg.success) {
          setSavedEnvConfig({ ...effectiveConfigRef.current });
          setEnvDraftOverrides({});
          if (
            wizardMode &&
            (WIZARD_STEPS[wizardStep]?.key === 'save' ||
              WIZARD_STEPS[wizardStep]?.key === 'literature' ||
              WIZARD_STEPS[wizardStep]?.key === 'backend')
          ) {
            handleWizardStepChange(wizardStep + 1);
          }
          if (!wizardMode && isReadyForDashboard) {
            setConfigCollapseKeys([]);
            handleRefreshUsage();
          }
          if (pendingStartBackendRef.current) {
            pendingStartBackendRef.current = false;
            vscode.postMessage({
              command: 'startBackend',
              config: getConfigValuesForValidation(),
            });
          } else {
            notification.success({
              message: t('configPage.notifications.saveSuccess'),
              description: msg.needsInit
                ? t('configPage.notifications.saveSuccessNextInit')
                : t('configPage.notifications.saveSuccessDesc'),
              placement: 'top',
            });
          }
        } else {
          pendingStartBackendRef.current = false;
          setStartingBackend(false);
          if (msg.error) {
            notification.error({
              message: t('configPage.notifications.saveFailed'),
              description: msg.error,
              placement: 'top',
            });
          }
        }
      } else if (message.command === 'startBackendResult') {
        const msg = message as { success?: boolean; error?: string };
        setStartingBackend(false);
        if (msg.success) {
          requestBackendStatus();
          const onBackendStep = wizardMode && WIZARD_STEPS[wizardStep]?.key === 'backend';
          if (onBackendStep) {
            handleWizardStepChange(wizardStepIndex('literature'));
          } else {
            notification.success({
              message: t('configPage.notifications.backendStarted', { defaultValue: 'Backend started successfully' }),
              placement: 'top',
            });
          }
        } else if (msg.error) {
          notification.error({
            message: t('configPage.notifications.backendStartFailed', { defaultValue: 'Failed to start backend' }),
            description: msg.error,
            placement: 'top',
            duration: 6,
          });
        }
      } else if (message.command === 'validationResult') {
        const msg = message as unknown as { llmType: string; success?: boolean; error?: string };
        setValidationState(prev => ({
          ...prev,
          [msg.llmType]: { validating: false, valid: msg.success ?? false, error: msg.error || null },
        }));
        if (msg.success) {
          markValidFingerprint(msg.llmType);
          if (msg.llmType === 'default') {
            maybeAdvanceWizardAfterDefaultValidation();
            vscode.postMessage({
              command: 'persistDefaultLlmValidation',
              fingerprint: getDefaultLlmFingerprint(),
            });
          }
        } else if (msg.llmType === 'default') {
          vscode.postMessage({ command: 'clearDefaultLlmValidation' });
        }
      } else if (message.command === 'literatureValidationResult') {
        const msg = message as { success?: boolean; error?: string; sources?: Record<string, unknown> };
        setValidationState(prev => ({
          ...prev,
          literature: { validating: false, valid: msg.success ?? false, error: msg.error || null },
        }));
        if (msg.success) {
          markValidFingerprint('literature');
        }
        if (msg.success && msg.sources && literatureValidateManualRef.current) {
          notification.success({
            message: t('configPage.validation.literatureValidateSuccess'),
            description: t('configPage.validation.literatureValidateSuccessDesc', {
              sources: Object.keys(msg.sources).join(', '),
            }),
            placement: 'top',
          });
        }
        literatureValidateManualRef.current = false;
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [claudeForm, clearWebImportApplyTimer, form, getDefaultLlmFingerprint, handleWizardStepChange, jumpToAdvanced, markValidFingerprint, maybeAdvanceWizardAfterDefaultValidation, pendingWebImport, requestBackendStatus, t, vscode, claudeProviders, handleFetchProviderModels, resolveClaudeModelsFetchError, wizardMode, wizardStep]);

  const handleSave = async () => {
    if (!workspaceInfo.hasWorkspace) {
      notification.warning({
        message: t('configPage.noWorkspace'),
        description: t('configPage.noWorkspaceHint'),
      });
      return;
    }

    const values = getConfigValuesForValidation();

    // Require LLM API key/base to save
    if (!hasText(values.llmApiKey)) {
      notification.warning({
        message: t('configPage.notifications.llmKeyRequired'),
        description: t('configPage.notifications.llmKeyRequiredDesc'),
      });
      return;
    }
    if (!hasText(values.llmApiBase)) {
      notification.warning({
        message: t('configPage.validationFailed'),
        description: t('configPage.notifications.apiBaseMissing'),
        placement: 'top',
      });
      return;
    }

    setLoading(true);
    vscode.postMessage({
      command: 'saveConfig',
      config: values,
    });
  };

  const handleStartBackend = React.useCallback(() => {
    if (!workspaceInfo.hasWorkspace) {
      notification.warning({
        message: t('configPage.noWorkspace'),
        description: t('configPage.noWorkspaceHint'),
      });
      return;
    }

    const values = getConfigValuesForValidation();
    if (!hasText(values.llmApiKey)) {
      notification.warning({
        message: t('configPage.notifications.llmKeyRequired'),
        description: t('configPage.notifications.llmKeyRequiredDesc'),
      });
      openConfigEditor('simulation');
      return;
    }
    if (!hasText(values.llmApiBase)) {
      notification.warning({
        message: t('configPage.validationFailed'),
        description: t('configPage.notifications.apiBaseMissing'),
        placement: 'top',
      });
      openConfigEditor('simulation');
      return;
    }

    setStartingBackend(true);
    vscode.postMessage({
      command: 'startBackend',
      config: values,
    });
  }, [getConfigValuesForValidation, openConfigEditor, t, vscode, workspaceInfo.hasWorkspace]);

  const handleSaveAndStart = async () => {
    if (!workspaceInfo.hasWorkspace) {
      notification.warning({
        message: t('configPage.noWorkspace'),
        description: t('configPage.noWorkspaceHint'),
      });
      return;
    }

    const values = getConfigValuesForValidation();

    // Require LLM API key
    if (!hasText(values.llmApiKey)) {
      notification.warning({
        message: t('configPage.notifications.llmKeyRequired'),
        description: t('configPage.notifications.llmKeyRequiredDesc'),
      });
      return;
    }
    if (!hasText(values.llmApiBase)) {
      notification.warning({
        message: t('configPage.validationFailed'),
        description: t('configPage.notifications.apiBaseMissing'),
        placement: 'top',
      });
      return;
    }

    pendingStartBackendRef.current = true;
    setLoading(true);
    setStartingBackend(true);
    vscode.postMessage({
      command: 'saveConfig',
      config: values,
    });
  };

  return (
    <ConfigProvider theme={themeConfig}>
      <Layout style={{ minHeight: '100vh', background: palette.editorBackground }}>
        <Content
          style={{
            padding: '20px 24px',
            maxWidth: 1000,
            margin: '0 auto',
            width: '100%',
            color: palette.editorForeground,
          }}
        >
          {/* 头部区域 - 玻璃态 */}
          <div
            style={{
              marginBottom: 20,
              padding: '20px 24px',
              borderRadius: 16,
              border: `1px solid ${palette.panelBorder}`,
              background: isDark
                ? 'rgba(37, 37, 38, 0.7)'
                : 'rgba(255, 255, 255, 0.65)',
              backdropFilter: 'blur(24px)',
              WebkitBackdropFilter: 'blur(24px)',
              boxShadow: isDark
                ? '0 4px 16px rgba(0,0,0,0.2)'
                : '0 4px 16px rgba(0,0,0,0.08)',
            }}
          >
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 40,
                    height: 40,
                    borderRadius: 12,
                    background: `linear-gradient(135deg, ${palette.linkForeground}20 0%, ${palette.linkForeground}10 100%)`,
                    color: palette.linkForeground,
                  }}
                >
                  <SettingOutlined style={{ fontSize: 18 }} />
                </span>
                <div>
                  <Title level={4} style={{ margin: 0 }}>
                    {wizardMode ? t('configPage.setupGuide.wizardTitle') : t('configPage.title')}
                  </Title>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                    {wizardMode
                      ? t('configPage.setupGuide.wizardSubtitle')
                      : workspaceInfo.envFilePath
                        ? t('configPage.envFileLoaded', { path: workspaceInfo.envFilePath })
                        : t('configPage.subtitle')}
                  </Text>
                </div>
              </div>
              {!wizardMode ? (
                <Space wrap={false} align="center" size={8}>
                  {webImportPanel('header')}
                  <Tooltip title={saveDisabledReason || ''}>
                    <Button
                      type="primary"
                      icon={<RocketOutlined />}
                      onClick={() => void handleSaveAndStart()}
                      disabled={!canSaveAndStart}
                      loading={loading || startingBackend}
                    >
                      {startingBackend ? t('configPage.starting') : t('configPage.saveAndStart')}
                    </Button>
                  </Tooltip>
                  <Dropdown
                    menu={{
                      items: [
                        {
                          key: 'save',
                          label: t('configPage.save'),
                          icon: <SaveOutlined />,
                          disabled: !canSave || loading,
                          onClick: () => void handleSave(),
                        },
                        {
                          key: 'rerunWizard',
                          label: t('configPage.setupGuide.rerunWizard'),
                          icon: <ReloadOutlined />,
                          onClick: handleRerunWizard,
                        },
                        {
                          key: 'reset',
                          label: t('configPage.resetWorkspaceDefaults'),
                          icon: <ReloadOutlined />,
                          onClick: handleResetWorkspaceDefaults,
                        },
                      ],
                    }}
                  >
                    <Button icon={<MoreOutlined />} />
                  </Dropdown>
                </Space>
              ) : null}
            </div>

            {!wizardMode ? (
              isDashboardMode ? (
                <ConfigStatusDashboard
                  t={t}
                  palette={palette}
                  isDark={isDark}
                  hasWorkspace={workspaceInfo.hasWorkspace}
                  hasLlmKey={hasDefaultLlmKey}
                  llmModel={defaultLlmModel}
                  defaultValidation={validationState.default}
                  backendStatus={backendStatus}
                  gatewayStatus={aiCliGatewayStatus}
                  gatewayUsageRecords={gatewayUsageRecords}
                  showUsageChart={showUsageChart}
                  usageLoading={gatewayUsageLoading}
                  onOpenSimulation={() => openConfigEditor('simulation')}
                  onOpenBackendUrl={(url) => vscode.postMessage({ command: 'openUrl', url })}
                  onStartBackend={handleStartBackend}
                  backendStarting={startingBackend}
                  onOpenCli={() => openConfigEditor('cli')}
                />
              ) : (
                <ConfigReadinessOverview
                  t={t}
                  palette={palette}
                  isDark={isDark}
                  hasWorkspace={workspaceInfo.hasWorkspace}
                  hasLlmKey={hasDefaultLlmKey}
                  llmModel={defaultLlmModel}
                  defaultValidation={validationState.default}
                  backendStatus={backendStatus}
                  gatewayStatus={aiCliGatewayStatus}
                  gatewayUsageRecords={gatewayUsageRecords}
                  onOpenSimulation={() => jumpToPage('simulation')}
                  onOpenBackendUrl={(url) => vscode.postMessage({ command: 'openUrl', url })}
                  onStartBackend={handleStartBackend}
                  backendStarting={startingBackend}
                  onOpenCli={() => jumpToPage('cli')}
                />
              )
            ) : null}
          </div>

          {!workspaceInfo.hasWorkspace && (
            <Alert
              message={t('configPage.noWorkspace')}
              description={t('configPage.noWorkspaceHint')}
              type="warning"
              showIcon
              style={{ marginBottom: 16, borderRadius: 10 }}
              action={
                <Button
                  type="primary"
                  size="small"
                  onClick={() => vscode.postMessage({ command: 'openFolder' })}
                >
                  {t('configPage.openWorkspace')}
                </Button>
              }
            />
          )}

          {wizardMode ? (
            <Form form={form} style={{ marginBottom: 20 }}>
              <ConfigSetupWizard
                t={t}
                palette={palette}
                step={wizardStep}
                hasWorkspace={workspaceInfo.hasWorkspace}
                hasLlmKey={hasDefaultLlmKey}
                defaultValidation={validationState.default}
                backendStatus={backendStatus}
                canSave={canSave}
                canSaveAndStart={canSaveAndStart}
                saving={loading}
                savingEasyPaper={savingEasyPaper}
                startingBackend={startingBackend}
                onStepChange={handleWizardStepChange}
                onExitWizard={handleExitWizard}
                onCompleteWizard={handleCompleteWizard}
                onSave={() => void handleSave()}
                onSaveAndStart={() => void handleSaveAndStart()}
                onSaveEasyPaper={saveEasyPaperConfig}
                onValidateDefault={handleValidateDefault}
              >
                <div ref={pageSectionRef}>
                  <ConfigWizardStepPanel
                    stepKey={WIZARD_STEPS[wizardStep]?.key ?? 'simulation'}
                    t={t}
                    palette={palette}
                    isDark={isDark}
                    form={form}
                    effectiveConfigValues={effectiveConfigValues}
                    hasDefaultLlmKey={hasDefaultLlmKey}
                    backendStatus={backendStatus}
                    backendStarting={startingBackend}
                    validationState={validationState}
                    defaultValidateDisabledReason={defaultValidateDisabledReason}
                    literatureValidateDisabledReason={literatureValidateDisabledReason}
                    pythonValidateDisabledReason={pythonValidateDisabledReason}
                    onValidate={handleValidate}
                    onFetchDefaultLlmModels={handleFetchDefaultLlmModels}
                    modelsByProvider={modelsByProvider}
                    modelsLoadingByProvider={modelsLoadingByProvider}
                    modelsErrorByProvider={modelsErrorByProvider}
                    webImportPanel={webImportPanel('wizard')}
                    pythonEnvironmentOptions={pythonEnvironmentOptions}
                    pythonEnvironmentScanning={pythonEnvironmentScanning}
                    onScanPythonEnvironments={handleScanPythonEnvironments}
                    literatureSectionRef={literatureSectionRef}
                    claudeSectionRef={claudeSectionRef}
                    claudeCliStatus={claudeCliStatus}
                    claudeSettingsPath={claudeSettingsPath}
                    onResetClaude={handleResetClaudeDefaults}
                    gatewayStatus={aiCliGatewayStatus}
                    gatewayToggling={gatewayToggling}
                    onRouteClaudeToggle={(enabled) => handleGatewayRouteToggle('claude', enabled)}
                    onRouteCodexToggle={(enabled) => handleGatewayRouteToggle('codex', enabled)}
                    claudeProviders={claudeProviders}
                    claudeProvidersLoading={claudeProvidersLoading}
                    providerAvailabilityResults={providerAvailabilityResults}
                    onSaveProvider={handleSaveClaudeProvider}
                    onAddProvider={handleAddClaudeProvider}
                    onRemoveProvider={handleRemoveClaudeProvider}
                    onActivateProvider={handleActivateClaudeProvider}
                    onToggleFailoverProvider={handleToggleFailoverProvider}
                    onSpeedtestProvider={handleCheckClaudeProvider}
                    isProviderChecking={isProviderChecking}
                    onShowGatewayLog={handleShowClaudeGatewayLog}
                    onFetchProviderModels={handleFetchProviderModels}
                    gatewayUsageRecords={gatewayUsageRecords}
                    gatewayUsageLoading={gatewayUsageLoading}
                    onRefreshUsage={handleRefreshUsage}
                    onClearUsage={handleClearUsage}
                    codexRouting={codexRouting}
                    failoverEnabled={failoverEnabled}
                    onFailoverToggle={handleFailoverToggle}
                    customPricing={customPricing}
                    onGetPricing={handleGetPricing}
                    onRefreshPricing={handleRefreshPricing}
                    onSavePricing={handleSavePricing}
                    onClearPricing={handleClearPricing}
                    providerUsage={providerUsage}
                    onQueryProviderUsage={handleQueryProviderUsage}
                    onRestartCodex={handleRestartCodex}
                    onRestartClaude={handleRestartClaude}
                    onSyncClaudeConfig={handleSyncClaudeConfig}
                    onSyncCodexConfig={handleSyncCodexConfig}
                    onSaveOutboundProxy={handleSaveOutboundProxy}
                    onRectifierChange={handleRectifierChange}
                    onOptimizerChange={handleOptimizerChange}
                    onRefreshCodexOfficialLogin={handleRefreshCodexOfficialLogin}
                    easyPaperForm={easyPaperForm}
                    onSaveEasyPaper={saveEasyPaperConfig}
                  />
                </div>
              </ConfigSetupWizard>
            </Form>
          ) : (
          <Form form={form} style={{ marginBottom: 20 }}>
            <div ref={pageSectionRef}>
              {isDashboardMode ? (
                <Collapse
                  bordered={false}
                  activeKey={configCollapseKeys}
                  onChange={(keys) => setConfigCollapseKeys(Array.isArray(keys) ? keys : [keys])}
                  style={{ background: 'transparent' }}
                  items={[
                    {
                      key: 'config',
                      label: (
                        <Space direction="vertical" size={0}>
                          <Text strong>{t('configPage.dashboard.editConfig')}</Text>
                          <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                            {t('configPage.dashboard.editConfigHint')}
                          </Text>
                        </Space>
                      ),
                      children: (
                        <Tabs
                          activeKey={pageTab}
                          onChange={(key) => setPageTab(key as ConfigPageTab)}
                          size="middle"
                          destroyInactiveTabPane={false}
                          style={{ marginBottom: 8 }}
                          items={[
                            {
                              key: 'cli',
                              label: t('configPage.pageTabs.cli'),
                              children: (
                                <div ref={claudeSectionRef} style={advancedPanelInnerStyle(isDark, palette)}>
                                  <AiCliConfigSection
                                    t={t}
                                    palette={palette}
                                    cliStatus={claudeCliStatus}
                                    settingsPath={claudeSettingsPath}
                                    onResetClaude={handleResetClaudeDefaults}
                                    gatewayStatus={aiCliGatewayStatus}
                                    gatewayToggling={gatewayToggling}
                                    onRouteClaudeToggle={(enabled) => handleGatewayRouteToggle('claude', enabled)}
                                    onRouteCodexToggle={(enabled) => handleGatewayRouteToggle('codex', enabled)}
                                    providers={claudeProviders}
                                    providersLoading={claudeProvidersLoading}
                                    speedtestResults={providerAvailabilityResults}
                                    onSaveProvider={handleSaveClaudeProvider}
                                    onAddProvider={handleAddClaudeProvider}
                                    onRemoveProvider={handleRemoveClaudeProvider}
                                    onActivateProvider={handleActivateClaudeProvider}
                                    onToggleFailoverProvider={handleToggleFailoverProvider}
                                    onSpeedtestProvider={handleCheckClaudeProvider}
                                    isProviderChecking={isProviderChecking}
                                    onShowGatewayLog={handleShowClaudeGatewayLog}
                                    modelsByProvider={modelsByProvider}
                                    modelsLoadingByProvider={modelsLoadingByProvider}
                                    modelsErrorByProvider={modelsErrorByProvider}
                                    onFetchProviderModels={handleFetchProviderModels}
                                    usageRecords={gatewayUsageRecords}
                                    usageLoading={gatewayUsageLoading}
                                    onRefreshUsage={handleRefreshUsage}
                                    onClearUsage={handleClearUsage}
                                    codexRouting={codexRouting}
                                    failoverEnabled={failoverEnabled}
                                    onFailoverToggle={handleFailoverToggle}
                                    customPricing={customPricing}
                                    onGetPricing={handleGetPricing}
                                    onRefreshPricing={handleRefreshPricing}
                                    onSavePricing={handleSavePricing}
                                    onClearPricing={handleClearPricing}
                                    providerUsage={providerUsage}
                                    onQueryProviderUsage={handleQueryProviderUsage}
                                    onRestartCodex={handleRestartCodex}
                                    onRestartClaude={handleRestartClaude}
                                    onSyncClaudeConfig={handleSyncClaudeConfig}
                                    onSyncCodexConfig={handleSyncCodexConfig}
                                    onSaveOutboundProxy={handleSaveOutboundProxy}
                                    onRectifierChange={handleRectifierChange}
                                    onOptimizerChange={handleOptimizerChange}
                                    onRefreshCodexOfficialLogin={handleRefreshCodexOfficialLogin}
                                  />
                                </div>
                              ),
                            },
                            {
                              key: 'simulation',
                              label: t('configPage.pageTabs.simulation'),
                              children: (
                                <DefaultLlmConfigCard
                                  t={t}
                                  palette={palette}
                                  isDark={isDark}
                                  form={form}
                                  baseUrl={effectiveConfigValues.llmApiBase ?? ''}
                                  apiKey={effectiveConfigValues.llmApiKey ?? ''}
                                  models={modelsByProvider[ENV_LLM_SLOT.default] ?? []}
                                  modelsLoading={modelsLoadingByProvider[ENV_LLM_SLOT.default] ?? false}
                                  modelsError={modelsErrorByProvider[ENV_LLM_SLOT.default] ?? null}
                                  onFetchModels={handleFetchDefaultLlmModels}
                                  validationState={validationState.default}
                                  validateDisabledReason={defaultValidateDisabledReason}
                                  onValidate={() => handleValidate('default')}
                                  showIntro={false}
                                />
                              ),
                            },
                            {
                              key: 'specialized',
                              label: t('configPage.pageTabs.specialized'),
                              children: (
                                <div style={advancedPanelInnerStyle(isDark, palette)}>
                                  <AdvancedConfigSection
                                    t={t}
                                    palette={palette}
                                    hasDefaultLlmKey={hasDefaultLlmKey}
                                    defaultLlmApiBase={defaultLlmApiBase}
                                    defaultLlmModel={defaultLlmModel}
                                    activeTopTab={advancedTopTab}
                                    onActiveTopTabChange={setAdvancedTopTab}
                                    validationState={validationState}
                                    validateDisabledByKind={{
                                      coder: coderValidateDisabledReason,
                                      embedding: embeddingValidateDisabledReason,
                                    }}
                                    pythonValidateDisabledReason={pythonValidateDisabledReason}
                                    onValidate={handleValidate}
                                    pythonSectionRef={pythonSectionRef}
                                    form={form}
                                    modelsBySlot={modelsByProvider}
                                    modelsLoadingBySlot={modelsLoadingByProvider}
                                    modelsErrorBySlot={modelsErrorByProvider}
                                    onFetchSlotModels={handleFetchEnvModels}
                                    effectiveValues={effectiveConfigValues}
                                    pythonEnvironmentOptions={pythonEnvironmentOptions}
                                    pythonEnvironmentScanning={pythonEnvironmentScanning}
                                    onScanPythonEnvironments={handleScanPythonEnvironments}
                                    easyPaperForm={easyPaperForm}
                                    onSaveEasyPaper={saveEasyPaperConfig}
                                  />
                                </div>
                              ),
                            },
                            {
                              key: 'literature',
                              label: t('configPage.pageTabs.literature'),
                              children: (
                                <div style={advancedPanelInnerStyle(isDark, palette)}>
                                  <LiteratureConfigSection
                                    t={t}
                                    palette={palette}
                                    validationState={validationState.literature}
                                    disabledReason={literatureValidateDisabledReason}
                                    onValidate={() => handleValidate('literature')}
                                    sectionRef={literatureSectionRef}
                                    showIntro={false}
                                  >
                                    <Form.Item name="literatureSearchMcpUrl" label={t('configPage.advanced.literature.apiUrl')}>
                                      <Input placeholder={t('configPage.advanced.literature.apiUrlPlaceholder')} />
                                    </Form.Item>
                                    <Form.Item name="literatureSearchApiKey" label={t('configPage.advanced.literature.apiKey')}>
                                      <Input.Password placeholder={t('configPage.advanced.literature.apiKeyPlaceholder')} autoComplete="off" />
                                    </Form.Item>
                                  </LiteratureConfigSection>
                                </div>
                              ),
                            },
                          ]}
                        />
                      ),
                    },
                  ]}
                />
              ) : (
                <Tabs
                  activeKey={pageTab}
                  onChange={(key) => setPageTab(key as ConfigPageTab)}
                  size="middle"
                  destroyInactiveTabPane={false}
                  style={{ marginBottom: 8 }}
                  items={[
                    {
                      key: 'simulation',
                      label: t('configPage.pageTabs.simulation'),
                      children: (
                        <DefaultLlmConfigCard
                          t={t}
                          palette={palette}
                          isDark={isDark}
                          form={form}
                          baseUrl={effectiveConfigValues.llmApiBase ?? ''}
                          apiKey={effectiveConfigValues.llmApiKey ?? ''}
                          models={modelsByProvider[ENV_LLM_SLOT.default] ?? []}
                          modelsLoading={modelsLoadingByProvider[ENV_LLM_SLOT.default] ?? false}
                          modelsError={modelsErrorByProvider[ENV_LLM_SLOT.default] ?? null}
                          onFetchModels={handleFetchDefaultLlmModels}
                          validationState={validationState.default}
                          validateDisabledReason={defaultValidateDisabledReason}
                          onValidate={() => handleValidate('default')}
                          showIntro={!wizardMode}
                        />
                      ),
                    },
                    {
                      key: 'specialized',
                      label: t('configPage.pageTabs.specialized'),
                      children: (
                        <div style={advancedPanelInnerStyle(isDark, palette)}>
                          <AdvancedConfigSection
                            t={t}
                            palette={palette}
                            hasDefaultLlmKey={hasDefaultLlmKey}
                            defaultLlmApiBase={defaultLlmApiBase}
                            defaultLlmModel={defaultLlmModel}
                            activeTopTab={advancedTopTab}
                            onActiveTopTabChange={setAdvancedTopTab}
                            validationState={validationState}
                            validateDisabledByKind={{
                              coder: coderValidateDisabledReason,
                              embedding: embeddingValidateDisabledReason,
                            }}
                            pythonValidateDisabledReason={pythonValidateDisabledReason}
                            onValidate={handleValidate}
                            pythonSectionRef={pythonSectionRef}
                            form={form}
                            modelsBySlot={modelsByProvider}
                            modelsLoadingBySlot={modelsLoadingByProvider}
                            modelsErrorBySlot={modelsErrorByProvider}
                            onFetchSlotModels={handleFetchEnvModels}
                            effectiveValues={effectiveConfigValues}
                            pythonEnvironmentOptions={pythonEnvironmentOptions}
                            pythonEnvironmentScanning={pythonEnvironmentScanning}
                            onScanPythonEnvironments={handleScanPythonEnvironments}
                            easyPaperForm={easyPaperForm}
                            onSaveEasyPaper={saveEasyPaperConfig}
                          />
                        </div>
                      ),
                    },
                    {
                      key: 'literature',
                      label: t('configPage.pageTabs.literature'),
                      children: (
                        <div style={advancedPanelInnerStyle(isDark, palette)}>
                          <LiteratureConfigSection
                            t={t}
                            palette={palette}
                            validationState={validationState.literature}
                            disabledReason={literatureValidateDisabledReason}
                            onValidate={() => handleValidate('literature')}
                            sectionRef={literatureSectionRef}
                            showIntro={!wizardMode}
                          >
                            <Form.Item name="literatureSearchMcpUrl" label={t('configPage.advanced.literature.apiUrl')}>
                              <Input placeholder={t('configPage.advanced.literature.apiUrlPlaceholder')} />
                            </Form.Item>
                            <Form.Item name="literatureSearchApiKey" label={t('configPage.advanced.literature.apiKey')}>
                              <Input.Password placeholder={t('configPage.advanced.literature.apiKeyPlaceholder')} autoComplete="off" />
                            </Form.Item>
                          </LiteratureConfigSection>
                        </div>
                      ),
                    },
                    {
                      key: 'cli',
                      label: t('configPage.pageTabs.cli'),
                      children: (
                        <div ref={claudeSectionRef} style={advancedPanelInnerStyle(isDark, palette)}>
                          <AiCliConfigSection
                            t={t}
                            palette={palette}
                            cliStatus={claudeCliStatus}
                            settingsPath={claudeSettingsPath}
                            onResetClaude={handleResetClaudeDefaults}
                            gatewayStatus={aiCliGatewayStatus}
                            gatewayToggling={gatewayToggling}
                            onRouteClaudeToggle={(enabled) => handleGatewayRouteToggle('claude', enabled)}
                            onRouteCodexToggle={(enabled) => handleGatewayRouteToggle('codex', enabled)}
                            providers={claudeProviders}
                            providersLoading={claudeProvidersLoading}
                            speedtestResults={providerAvailabilityResults}
                            onSaveProvider={handleSaveClaudeProvider}
                            onAddProvider={handleAddClaudeProvider}
                            onRemoveProvider={handleRemoveClaudeProvider}
                            onActivateProvider={handleActivateClaudeProvider}
                            onToggleFailoverProvider={handleToggleFailoverProvider}
                            onSpeedtestProvider={handleCheckClaudeProvider}
                            isProviderChecking={isProviderChecking}
                            onShowGatewayLog={handleShowClaudeGatewayLog}
                            modelsByProvider={modelsByProvider}
                            modelsLoadingByProvider={modelsLoadingByProvider}
                            modelsErrorByProvider={modelsErrorByProvider}
                            onFetchProviderModels={handleFetchProviderModels}
                            usageRecords={gatewayUsageRecords}
                            usageLoading={gatewayUsageLoading}
                            onRefreshUsage={handleRefreshUsage}
                            onClearUsage={handleClearUsage}
                            codexRouting={codexRouting}
                            failoverEnabled={failoverEnabled}
                            onFailoverToggle={handleFailoverToggle}
                            customPricing={customPricing}
                            onGetPricing={handleGetPricing}
                            onRefreshPricing={handleRefreshPricing}
                            onSavePricing={handleSavePricing}
                            onClearPricing={handleClearPricing}
                            providerUsage={providerUsage}
                            onQueryProviderUsage={handleQueryProviderUsage}
                            onRestartCodex={handleRestartCodex}
                            onRestartClaude={handleRestartClaude}
                            onSyncClaudeConfig={handleSyncClaudeConfig}
                            onSyncCodexConfig={handleSyncCodexConfig}
                            onSaveOutboundProxy={handleSaveOutboundProxy}
                            onRectifierChange={handleRectifierChange}
                            onOptimizerChange={handleOptimizerChange}
                            onRefreshCodexOfficialLogin={handleRefreshCodexOfficialLogin}
                          />
                        </div>
                      ),
                    },
                  ]}
                />
              )}
            </div>
          </Form>
          )}
        </Content>
      </Layout>
    </ConfigProvider>
  );
};
