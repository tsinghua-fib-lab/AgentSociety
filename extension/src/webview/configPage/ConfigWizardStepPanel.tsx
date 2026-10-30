import * as React from 'react';
import { Alert, Card, Checkbox, Descriptions, Form, Input, Space, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, SyncOutlined } from '@ant-design/icons';
import type { FormInstance } from 'antd';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type { BackendStatus, ConfigValues, ValidationState, EasyPaperConfigValues } from './types';
import type { WizardStepKey } from './ConfigSetupWizard';
import { DefaultLlmConfigCard } from './DefaultLlmConfigCard';
import { EasyPaperConfigSection } from './EasyPaperConfigSection';
import { LiteratureConfigSection } from './LiteratureConfigSection';
import { AiCliConfigSection } from './AiCliConfigSection';
import type { PythonEnvironmentOption } from './PythonEnvironmentPicker';
import { PythonEnvironmentPicker } from './PythonEnvironmentPicker';
import { ValidationAction } from './ValidationAction';
import { advancedPanelInnerStyle } from './configPageStyles';
import type { ClaudeModelOption } from './claudeCodeTypes';
import type {
  AiCliGatewayStatus,
  ClaudeCodeCliStatus,
  ProviderAvailabilityResult,
} from './claudeCodeTypes';
import type { TokenUsageRecord } from './gatewayUsageTypes';
import type { ModelPricingMap } from './modelPricing';
import type { AiCliProviderRecord } from './aiCliProviderTypes';
import { ENV_LLM_SLOT } from './envLlmSlots';

const { Text } = Typography;

type WizardBackendPanelProps = {
  t: TFunction;
  palette: VscodeThemePalette;
  form: FormInstance<ConfigValues>;
  backendStatus: BackendStatus;
  backendStarting: boolean;
  validationState: ValidationState;
  pythonValidateDisabledReason: string | null;
  onValidatePython: () => void;
  pythonEnvironmentOptions: PythonEnvironmentOption[];
  pythonEnvironmentScanning: boolean;
  onScanPythonEnvironments: () => void;
};

function WizardBackendPanel({
  t,
  palette,
  form,
  backendStatus,
  backendStarting,
  validationState,
  pythonValidateDisabledReason,
  onValidatePython,
  pythonEnvironmentOptions,
  pythonEnvironmentScanning,
  onScanPythonEnvironments,
}: WizardBackendPanelProps) {
  const running = backendStatus.isRunning;
  const port = backendStatus.port;

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type={running ? 'success' : 'info'}
        showIcon
        icon={
          running ? (
            <CheckCircleOutlined />
          ) : backendStarting ? (
            <SyncOutlined spin />
          ) : (
            <CloseCircleOutlined />
          )
        }
        message={
          running
            ? t('configPage.overview.backendRunning', { port: String(port ?? '?') })
            : t('configPage.overview.backendStopped')
        }
        description={running ? undefined : t('configPage.overview.backendStoppedHint')}
      />
      <Card size="small" title={t('configPage.python.title')} style={{ borderRadius: 10 }}>
        <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 12 }}>
          {t('configPage.python.hint')}
        </Text>
        <PythonEnvironmentPicker
          t={t}
          form={form}
          options={pythonEnvironmentOptions}
          scanning={pythonEnvironmentScanning}
          onScan={onScanPythonEnvironments}
        />
        <div style={{ marginTop: 12 }}>
          <ValidationAction
            t={t}
            palette={palette}
            state={validationState}
            disabledReason={pythonValidateDisabledReason}
            onValidate={onValidatePython}
            label={t('configPage.validate')}
            size="small"
            primary={false}
          />
        </div>
      </Card>
      <Card size="small" title={t('configPage.backend.autoStartTitle')} style={{ borderRadius: 10 }}>
        <Form.Item name="backendAutoStart" valuePropName="checked" noStyle>
          <Checkbox>{t('configPage.backend.autoStartLabel')}</Checkbox>
        </Form.Item>
        <Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 8 }}>
          {t('configPage.backend.autoStartHint')}
        </Text>
      </Card>
    </Space>
  );
}

type WizardSaveReviewProps = {
  t: TFunction;
  palette: VscodeThemePalette;
  isDark: boolean;
  apiBase: string;
  model: string;
  hasKey: boolean;
  validationState: ValidationState;
};

function WizardSaveReview({
  t,
  palette,
  isDark,
  apiBase,
  model,
  hasKey,
  validationState,
}: WizardSaveReviewProps) {
  const validated = validationState.valid === true;

  return (
    <Card
      size="small"
      style={{
        borderRadius: 12,
        border: `1px solid ${palette.panelBorder}`,
        background: isDark ? palette.surfaceMuted : '#fafafa',
      }}
    >
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label={t('configPage.llm.apiBase')}>{apiBase || '—'}</Descriptions.Item>
        <Descriptions.Item label={t('configPage.llm.modelName')}>{model || '—'}</Descriptions.Item>
        <Descriptions.Item label={t('configPage.llm.apiKey')}>
          {hasKey ? (
            <Tag color="success">{t('configPage.linkedPlaceholders.configured')}</Tag>
          ) : (
            <Tag>{t('configPage.linkedPlaceholders.notConfigured')}</Tag>
          )}
        </Descriptions.Item>
        <Descriptions.Item label={t('configPage.validate')}>
          {validated ? (
            <Tag color="success">{t('configPage.advancedValidation.statusOk')}</Tag>
          ) : (
            <Tag>{t('configPage.advancedValidation.statusIdleShort')}</Tag>
          )}
        </Descriptions.Item>
      </Descriptions>
      <Text type="secondary" style={{ display: 'block', marginTop: 12, fontSize: 12 }}>
        {t('configPage.setupGuide.saveReviewHint')}
      </Text>
    </Card>
  );
}

export type ConfigWizardStepPanelProps = {
  stepKey: WizardStepKey;
  t: TFunction;
  palette: VscodeThemePalette;
  isDark: boolean;
  form: FormInstance<ConfigValues>;
  effectiveConfigValues: ConfigValues;
  hasDefaultLlmKey: boolean;
  backendStatus: BackendStatus;
  backendStarting: boolean;
  validationState: Record<string, ValidationState>;
  defaultValidateDisabledReason: string | null;
  literatureValidateDisabledReason: string | null;
  pythonValidateDisabledReason: string | null;
  onValidate: (kind: string) => void;
  onFetchDefaultLlmModels: () => void;
  modelsByProvider: Record<string, ClaudeModelOption[]>;
  modelsLoadingByProvider: Record<string, boolean>;
  modelsErrorByProvider: Record<string, string | null>;
  webImportPanel?: React.ReactNode;
  pythonEnvironmentOptions: PythonEnvironmentOption[];
  pythonEnvironmentScanning: boolean;
  onScanPythonEnvironments: () => void;
  literatureSectionRef: React.RefObject<HTMLDivElement | null>;
  claudeSectionRef: React.RefObject<HTMLDivElement | null>;
  claudeCliStatus: ClaudeCodeCliStatus;
  claudeSettingsPath: string;
  onResetClaude: () => void;
  gatewayStatus: AiCliGatewayStatus;
  gatewayToggling: boolean;
  onRouteClaudeToggle: (enabled: boolean) => void;
  onRouteCodexToggle: (enabled: boolean) => void;
  claudeProviders: AiCliProviderRecord[];
  claudeProvidersLoading: boolean;
  providerAvailabilityResults: Record<string, ProviderAvailabilityResult>;
  onSaveProvider: (provider: AiCliProviderRecord) => void;
  onAddProvider: (draft: Omit<AiCliProviderRecord, 'id'>) => void;
  onRemoveProvider: (id: string) => void;
  onActivateProvider: (id: string, role: 'claude' | 'codex') => void;
  onToggleFailoverProvider: (id: string, role: 'claude' | 'codex') => void;
  onSpeedtestProvider: (baseUrl: string, apiKey: string, apiKind?: 'anthropic' | 'openai') => void;
  isProviderChecking: (baseUrl: string) => boolean;
  onShowGatewayLog: () => void;
  onFetchProviderModels: (
    providerId: string,
    baseUrl: string,
    apiKey: string,
    apiKind?: 'anthropic' | 'openai'
  ) => void;
  gatewayUsageRecords: TokenUsageRecord[];
  gatewayUsageLoading: boolean;
  onRefreshUsage: () => void;
  onClearUsage: () => void;
  codexRouting: { configPath: string; routed: boolean; directUrl?: string } | null;
  failoverEnabled: boolean;
  onFailoverToggle: (enabled: boolean) => void;
  customPricing: ModelPricingMap;
  onGetPricing: () => void;
  onRefreshPricing: () => void;
  onSavePricing: (pricing: ModelPricingMap) => void;
  onClearPricing: () => void;
  providerUsage: Record<string, import('./claudeCodeTypes').ProviderUsageQueryResult & { loading?: boolean }>;
  onQueryProviderUsage: (providerId: string) => void;
  onRestartCodex: () => void;
  onRestartClaude: () => void;
  onSyncClaudeConfig: () => void;
  onSyncCodexConfig: () => void;
  onSaveOutboundProxy: (url: string) => void;
  onRectifierChange: (settings: Record<string, boolean>) => void;
  onOptimizerChange: (settings: Record<string, boolean>) => void;
  onRefreshCodexOfficialLogin: () => void;
  easyPaperForm: FormInstance<EasyPaperConfigValues>;
  onSaveEasyPaper: () => void;
};

export function ConfigWizardStepPanel(props: ConfigWizardStepPanelProps) {
  const {
    stepKey,
    t,
    palette,
    isDark,
    form,
    effectiveConfigValues,
    hasDefaultLlmKey,
    backendStatus,
    backendStarting,
    validationState,
    defaultValidateDisabledReason,
    onValidate,
    onFetchDefaultLlmModels,
    modelsByProvider,
    modelsLoadingByProvider,
    modelsErrorByProvider,
    webImportPanel,
  } = props;

  if (stepKey === 'import') {
    return (
      <div style={advancedPanelInnerStyle(isDark, palette)}>
        {webImportPanel}
      </div>
    );
  }

  if (stepKey === 'simulation') {
    return (
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
        onFetchModels={onFetchDefaultLlmModels}
        validationState={validationState.default}
        validateDisabledReason={defaultValidateDisabledReason}
        onValidate={() => onValidate('default')}
        showIntro={false}
      />
    );
  }

  if (stepKey === 'save') {
    return (
      <WizardSaveReview
        t={t}
        palette={palette}
        isDark={isDark}
        apiBase={effectiveConfigValues.llmApiBase ?? ''}
        model={effectiveConfigValues.llmModel ?? ''}
        hasKey={hasDefaultLlmKey}
        validationState={validationState.default}
      />
    );
  }

  if (stepKey === 'backend') {
    return (
      <WizardBackendPanel
        t={t}
        palette={palette}
        form={form}
        backendStatus={backendStatus}
        backendStarting={backendStarting}
        validationState={validationState.python}
        pythonValidateDisabledReason={props.pythonValidateDisabledReason}
        onValidatePython={() => onValidate('python')}
        pythonEnvironmentOptions={props.pythonEnvironmentOptions}
        pythonEnvironmentScanning={props.pythonEnvironmentScanning}
        onScanPythonEnvironments={props.onScanPythonEnvironments}
      />
    );
  }

  if (stepKey === 'easypaper') {
    return (
      <div style={advancedPanelInnerStyle(isDark, palette)}>
        <EasyPaperConfigSection
          t={t}
          palette={palette}
          form={props.easyPaperForm}
          defaultLlmApiKey={hasDefaultLlmKey ? (effectiveConfigValues.llmApiKey || '') : ''}
          defaultLlmApiBase={effectiveConfigValues.llmApiBase ?? ''}
          defaultLlmModel={effectiveConfigValues.llmModel ?? ''}
          onSave={props.onSaveEasyPaper}
          showInlineSave={false}
          showIntro={false}
        />
      </div>
    );
  }

  if (stepKey === 'literature') {
    return (
      <div style={advancedPanelInnerStyle(isDark, palette)}>
        <LiteratureConfigSection
          t={t}
          palette={palette}
          validationState={validationState.literature}
          disabledReason={props.literatureValidateDisabledReason}
          onValidate={() => onValidate('literature')}
          sectionRef={props.literatureSectionRef}
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
    );
  }

  return (
    <div ref={props.claudeSectionRef} style={advancedPanelInnerStyle(isDark, palette)}>
      <AiCliConfigSection
        t={t}
        palette={palette}
        cliStatus={props.claudeCliStatus}
        settingsPath={props.claudeSettingsPath}
        onResetClaude={props.onResetClaude}
        gatewayStatus={props.gatewayStatus}
        gatewayToggling={props.gatewayToggling}
        onRouteClaudeToggle={props.onRouteClaudeToggle}
        onRouteCodexToggle={props.onRouteCodexToggle}
        providers={props.claudeProviders}
        providersLoading={props.claudeProvidersLoading}
        speedtestResults={props.providerAvailabilityResults}
        onSaveProvider={props.onSaveProvider}
        onAddProvider={props.onAddProvider}
        onRemoveProvider={props.onRemoveProvider}
        onActivateProvider={props.onActivateProvider}
        onToggleFailoverProvider={props.onToggleFailoverProvider}
        onSpeedtestProvider={props.onSpeedtestProvider}
        isProviderChecking={props.isProviderChecking}
        onShowGatewayLog={props.onShowGatewayLog}
        modelsByProvider={modelsByProvider}
        modelsLoadingByProvider={modelsLoadingByProvider}
        modelsErrorByProvider={modelsErrorByProvider}
        onFetchProviderModels={props.onFetchProviderModels}
        usageRecords={props.gatewayUsageRecords}
        usageLoading={props.gatewayUsageLoading}
        onRefreshUsage={props.onRefreshUsage}
        onClearUsage={props.onClearUsage}
        codexRouting={props.codexRouting}
        failoverEnabled={props.failoverEnabled}
        onFailoverToggle={props.onFailoverToggle}
        customPricing={props.customPricing}
        onGetPricing={props.onGetPricing}
        onRefreshPricing={props.onRefreshPricing}
        onSavePricing={props.onSavePricing}
        onClearPricing={props.onClearPricing}
        providerUsage={props.providerUsage}
        onQueryProviderUsage={props.onQueryProviderUsage}
        onRestartCodex={props.onRestartCodex}
        onRestartClaude={props.onRestartClaude}
        onSyncClaudeConfig={props.onSyncClaudeConfig}
        onSyncCodexConfig={props.onSyncCodexConfig}
        onSaveOutboundProxy={props.onSaveOutboundProxy}
        onRectifierChange={props.onRectifierChange}
        onOptimizerChange={props.onOptimizerChange}
        onRefreshCodexOfficialLogin={props.onRefreshCodexOfficialLogin}
      />
    </div>
  );
}
