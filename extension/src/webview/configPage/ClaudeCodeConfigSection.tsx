import * as React from 'react';
import { Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type {
  AiCliGatewayStatus,
  ClaudeCodeCliStatus,
  ClaudeModelOption,
  CodexRoutingStatus,
  ProviderUsageQueryResult,
  ProviderAvailabilityResult,
} from './claudeCodeTypes';
import { AiCliProviderGroup } from './AiCliProviderGroup';
import type { AiCliProviderRecord } from './aiCliProviderTypes';

export type ProviderSectionCommonProps = {
  t: TFunction;
  palette: VscodeThemePalette;
  cliStatus: ClaudeCodeCliStatus;
  settingsPath: string;
  gatewayStatus: AiCliGatewayStatus;
  gatewayToggling: boolean;
  onRouteClaudeToggle: (enabled: boolean) => void;
  onRouteCodexToggle: (enabled: boolean) => void;
  codexRouting: CodexRoutingStatus | null;
  providers: AiCliProviderRecord[];
  providersLoading: boolean;
  speedtestResults: Record<string, ProviderAvailabilityResult>;
  onSaveProvider: (provider: AiCliProviderRecord) => void;
  onAddProvider: (draft: Omit<AiCliProviderRecord, 'id'>) => void;
  onActivateProvider: (id: string, role: 'claude' | 'codex') => void;
  onRemoveProvider: (id: string) => void;
  onSpeedtestProvider: (baseUrl: string, apiKey: string, apiKind?: 'anthropic' | 'openai') => void;
  isProviderChecking?: (baseUrl: string) => boolean;
  modelsByProvider: Record<string, ClaudeModelOption[]>;
  modelsLoadingByProvider: Record<string, boolean>;
  modelsErrorByProvider: Record<string, string | null>;
  onFetchProviderModels: (
    providerId: string,
    baseUrl: string,
    apiKey: string,
    apiKind?: 'anthropic' | 'openai'
  ) => void;
  providerUsage: Record<string, ProviderUsageQueryResult & { loading?: boolean }>;
  onQueryProviderUsage: (id: string, force?: boolean) => void;
};

export interface ClaudeCodeConfigSectionProps extends ProviderSectionCommonProps {
  mode: 'claude' | 'codex' | 'unified';
  onReset?: () => void;
}

export function ClaudeCodeConfigSection({
  t,
  palette,
  onReset,
  providers,
  providersLoading,
  onSaveProvider,
  onAddProvider,
  onActivateProvider,
  onRemoveProvider,
  onSpeedtestProvider,
  speedtestResults,
  modelsByProvider,
  modelsLoadingByProvider,
  modelsErrorByProvider,
  onFetchProviderModels,
  providerUsage,
  onQueryProviderUsage,
  isProviderChecking,
}: ClaudeCodeConfigSectionProps) {
  const providerGroupProps = {
    t,
    palette,
    providers,
    loading: providersLoading,
    onSave: onSaveProvider,
    onAdd: onAddProvider,
    onActivate: onActivateProvider,
    onRemove: onRemoveProvider,
    onCheckAvailability: onSpeedtestProvider,
    isProviderChecking,
    availabilityResults: speedtestResults,
    providerUsage,
    onQueryProviderUsage,
    modelsByProvider,
    modelsLoadingByProvider,
    modelsErrorByProvider,
    onFetchModels: onFetchProviderModels,
  };

  return (
    <div style={{ paddingTop: 4 }}>
      <AiCliProviderGroup
        {...providerGroupProps}
        role="unified"
      />
      {onReset ? (
        <Button icon={<ReloadOutlined />} onClick={onReset} style={{ marginTop: 12 }}>
          {t('configPage.resetClaudeDefaults')}
        </Button>
      ) : null}
    </div>
  );
}
