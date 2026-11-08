import * as React from 'react';
import { Divider, Space, Switch, Tooltip, Typography, Button, Tag, Input, Collapse, Tabs } from 'antd';
import { CheckCircleOutlined, LinkOutlined, QuestionCircleOutlined, ReloadOutlined, SyncOutlined, CheckOutlined } from '@ant-design/icons';
import { ClaudeCodeConfigSection, type ProviderSectionCommonProps } from './ClaudeCodeConfigSection';
import { GatewayUsagePanel } from './GatewayUsagePanel';
import { tabBodyStyle } from './configPageStyles';
import type { TokenUsageRecord } from './gatewayUsageTypes';
import { countApiUpstreamsForRole, providerEligibleForRoleUpstream } from './providerAuth';
import type { ModelPricingMap } from './modelPricing';
import { CodexDeviceLoginPanel, useCodexDeviceLogin } from './CodexDeviceLoginPanel';

const { Text } = Typography;

export interface AiCliConfigSectionProps extends ProviderSectionCommonProps {
  onResetClaude: () => void;
  failoverEnabled: boolean;
  onFailoverToggle: (enabled: boolean) => void;
  onToggleFailoverProvider: (id: string, role: 'claude' | 'codex') => void;
  onShowGatewayLog: () => void;
  onRestartClaude?: () => void;
  onRestartCodex?: () => void;
  onSyncClaudeConfig?: () => void;
  onSyncCodexConfig?: () => void;
  onSaveOutboundProxy?: (url: string, username?: string, password?: string) => void;
  onRectifierChange?: (settings: Record<string, boolean>) => void;
  onOptimizerChange?: (settings: Record<string, boolean>) => void;
  usageRecords: TokenUsageRecord[];
  usageLoading: boolean;
  onRefreshUsage: () => void;
  onClearUsage: () => void;
  customPricing: ModelPricingMap;
  onGetPricing: () => void;
  onRefreshPricing: () => void;
  onSavePricing: (pricing: ModelPricingMap) => void;
  onClearPricing: () => void;
}

export function AiCliConfigSection(props: AiCliConfigSectionProps) {
  const {
    onResetClaude,
    gatewayStatus,
    gatewayToggling,
    onRouteClaudeToggle,
    onRouteCodexToggle,
    failoverEnabled,
    onFailoverToggle,
    onToggleFailoverProvider,
    usageRecords,
    usageLoading,
    onRefreshUsage,
    onClearUsage,
    customPricing,
    onGetPricing,
    onRefreshPricing,
    onSavePricing,
    onClearPricing,
    onShowGatewayLog,
    onRestartClaude,
    onRestartCodex,
    onSyncClaudeConfig,
    onSyncCodexConfig,
    onSaveOutboundProxy,
    onRectifierChange,
    onOptimizerChange,
    ...providerSectionCommon
  } = props;
  const { t, palette, providers } = providerSectionCommon;
  const { toolTab, selectToolTab, networkRequested, completeNetworkRequest } = useCodexDeviceLogin();

  const routeClaude = gatewayStatus.routeClaude ?? false;
  const routeCodex = gatewayStatus.routeCodex ?? false;
  const gatewayRunning = gatewayStatus.running;
  const gatewayBaseUrl = gatewayRunning ? gatewayStatus.baseUrl : undefined;
  const claudeProxyAvailable = gatewayStatus.claudeProxyAvailable ?? false;
  const codexProxyAvailable = gatewayStatus.codexProxyAvailable ?? false;
  const rectifier = gatewayStatus.rectifier ?? {
    enabled: true,
    thinkingSignature: true,
    thinkingBudget: true,
    unsupportedImageDowngrade: true,
    heuristicTextOnlyModels: true,
  };
  const optimizer = gatewayStatus.optimizer ?? {
    enabled: false,
    thinkingOptimizer: true,
    cacheInjection: true,
  };
  const [advancedKeys, setAdvancedKeys] = React.useState<string[]>([]);
  const networkInput = React.useRef<import('antd').InputRef>(null);
  React.useEffect(() => {
    if (!networkRequested) { return; }
    setAdvancedKeys(['advanced']);
    const timer = window.setTimeout(() => {
      networkInput.current?.focus();
      networkInput.current?.input?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      completeNetworkRequest();
    }, 200);
    return () => window.clearTimeout(timer);
  }, [networkRequested, completeNetworkRequest]);
  const [proxyDraft, setProxyDraft] = React.useState(gatewayStatus.outboundProxyUrl ?? '');
  React.useEffect(() => {
    setProxyDraft(gatewayStatus.outboundProxyUrl ?? '');
  }, [gatewayStatus.outboundProxyUrl]);
  const failoverHealth = gatewayStatus.failoverHealth ?? {};
  const claudeUpstreamCount = countApiUpstreamsForRole(providers, 'claude');
  const codexUpstreamCount = countApiUpstreamsForRole(providers, 'codex');
  const showFailoverToggle =
    (routeClaude && claudeUpstreamCount >= 2) || (routeCodex && codexUpstreamCount >= 2);
  const anyRouteEnabled = routeClaude || routeCodex;
  const usageEnabledApps = [
    ...(routeClaude ? (['claude'] as const) : []),
    ...(routeCodex ? (['codex'] as const) : []),
  ];
  const activeClaudeProvider = providers.find((p) => p.activeClaude);
  const activeCodexProvider = providers.find((p) => p.activeCodex);

  const summaryItems = [
    {
      key: 'gateway',
      label: t('claudeCodeConfig.gatewaySummaryService'),
      value: gatewayRunning
        ? t('claudeCodeConfig.gatewaySummaryRunning')
        : anyRouteEnabled
          ? t('claudeCodeConfig.gatewaySummaryStopped')
          : t('claudeCodeConfig.gatewaySummaryDirect'),
      tone: gatewayRunning
        ? '#52c41a'
        : anyRouteEnabled
          ? '#faad14'
          : palette.descriptionForeground,
      detail: gatewayBaseUrl ?? t('claudeCodeConfig.gatewaySummaryNoLocal'),
    },
    {
      key: 'claude',
      label: t('claudeCodeConfig.gatewayClaudeBlockTitle'),
      value: routeClaude ? t('claudeCodeConfig.gatewayRouteProxy') : t('claudeCodeConfig.gatewayRouteDirect'),
      tone: routeClaude ? '#1677ff' : palette.descriptionForeground,
      detail: activeClaudeProvider?.name || activeClaudeProvider?.baseUrl || t('claudeCodeConfig.providerNoneActive'),
    },
    {
      key: 'codex',
      label: t('claudeCodeConfig.gatewayCodexBlockTitle'),
      value: routeCodex ? t('claudeCodeConfig.gatewayRouteProxy') : t('claudeCodeConfig.gatewayRouteDirect'),
      tone: routeCodex ? '#1677ff' : palette.descriptionForeground,
      detail: activeCodexProvider?.name || activeCodexProvider?.baseUrl || t('claudeCodeConfig.providerNoneActive'),
    },
  ];

  return (
    <div style={tabBodyStyle}>
      <div style={{ marginBottom: 12 }}>
        <Space size={6} wrap style={{ marginBottom: 8 }}>
          <LinkOutlined />
          <Text strong style={{ fontSize: 13 }}>{t('claudeCodeConfig.gatewayTopologyTitle')}</Text>
          <Tooltip title={t('claudeCodeConfig.gatewayTopologyHint')}>
            <QuestionCircleOutlined style={{ opacity: 0.65, cursor: 'help' }} />
          </Tooltip>
        </Space>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
            gap: 8,
          }}
        >
          {summaryItems.map((item) => (
            <div
              key={item.key}
              style={{
                border: `1px solid ${palette.panelBorder}`,
                borderRadius: 8,
                padding: '9px 10px',
                background: palette.codeBlockBackground,
                minWidth: 0,
              }}
            >
              <Space size={6} style={{ marginBottom: 4 }}>
                <CheckCircleOutlined style={{ color: item.tone }} />
                <Text type="secondary" style={{ fontSize: 11 }}>{item.label}</Text>
              </Space>
              <Text strong style={{ display: 'block', fontSize: 13, color: item.tone }}>
                {item.value}
              </Text>
              <Text type="secondary" ellipsis={{ tooltip: item.detail }} style={{ display: 'block', fontSize: 11 }}>
                {item.detail}
              </Text>
            </div>
          ))}
        </div>
      </div>

      {gatewayRunning && gatewayStatus.stats ? (
        <div
          style={{
            marginBottom: 12,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
            gap: 8,
          }}
        >
          {[
            {
              key: 'requests',
              label: t('claudeCodeConfig.gatewayStatsRequests'),
              value: String(gatewayStatus.stats.totalRequests),
            },
            {
              key: 'success',
              label: t('claudeCodeConfig.gatewayStatsSuccessRate'),
              value: `${gatewayStatus.stats.successRate}%`,
            },
            {
              key: 'active',
              label: t('claudeCodeConfig.gatewayStatsActive'),
              value: String(gatewayStatus.stats.activeConnections),
            },
            {
              key: 'uptime',
              label: t('claudeCodeConfig.gatewayStatsUptime'),
              value: `${Math.floor(gatewayStatus.stats.uptimeMs / 1000)}s`,
            },
          ].map((item) => (
            <div
              key={item.key}
              style={{
                border: `1px solid ${palette.panelBorder}`,
                borderRadius: 8,
                padding: '8px 10px',
                background: palette.codeBlockBackground,
              }}
            >
              <Text type="secondary" style={{ fontSize: 10, display: 'block' }}>{item.label}</Text>
              <Text strong style={{ fontSize: 14 }}>{item.value}</Text>
            </div>
          ))}
        </div>
      ) : null}

      <div
        style={{
          marginBottom: 16,
          padding: '12px 14px',
          border: `1px solid ${palette.panelBorder}`,
          borderRadius: 10,
          background: palette.codeBlockBackground,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <Space size={6}>
            <Text strong style={{ fontSize: 13 }}>{t('claudeCodeConfig.cliSettingsTitle')}</Text>
            <Tooltip title={t('claudeCodeConfig.gatewayHint')}>
              <QuestionCircleOutlined style={{ opacity: 0.65, cursor: 'help' }} />
            </Tooltip>
          </Space>
          <Button size="small" icon={<ReloadOutlined />} onClick={onShowGatewayLog}>
            {t('claudeCodeConfig.showGatewayLog')}
          </Button>
        </div>

        <Tabs size="small" activeKey={toolTab} onChange={(key) => selectToolTab(key as 'claude' | 'codex')} destroyOnHidden items={[
          { key: 'claude', label: 'Claude Code', children: (
            <div style={routeRowStyle(routeClaude, gatewayRunning)}>
              <Space size={6} wrap style={{ minWidth: 0 }}>
                <span style={dotStyle(routeClaude, gatewayRunning, palette.descriptionForeground)} />
                <Text style={{ fontSize: 12, fontWeight: 500 }}>Claude Code</Text>
                <Tag color={routeStatusColor(routeClaude, gatewayRunning)} style={{ margin: 0, fontSize: 10 }}>
                  {routeClaude
                    ? gatewayRunning ? t('claudeCodeConfig.gatewayRouteProxy') : t('claudeCodeConfig.gatewayRouteNotDetected')
                    : t('claudeCodeConfig.gatewayRouteDirect')}
                </Tag>
                <Tooltip title={t('claudeCodeConfig.modelHotSwitchClaudeHint')}>
                  <QuestionCircleOutlined style={{ opacity: 0.5, cursor: 'help', fontSize: 11 }} />
                </Tooltip>
              </Space>
              <div style={routeActionsStyle}>
                {onSyncClaudeConfig ? (
                  <Tooltip title={t('claudeCodeConfig.syncClaudeConfigHint')}>
                    <Button type="text" size="small" icon={<SyncOutlined />} onClick={onSyncClaudeConfig} aria-label={t('claudeCodeConfig.syncClaudeConfig')} />
                  </Tooltip>
                ) : null}
                {onRestartClaude ? (
                  <Tooltip title={t('claudeCodeConfig.restartClaudeHint')}>
                    <Button type="text" size="small" icon={<ReloadOutlined />} onClick={onRestartClaude} aria-label={t('claudeCodeConfig.restartClaude')} />
                  </Tooltip>
                ) : null}
                <Tooltip title={t('claudeCodeConfig.gatewayClaudeProxyEnable')}>
                  <Switch
                    size="small"
                    checked={routeClaude}
                    loading={gatewayToggling}
                    disabled={!claudeProxyAvailable && !routeClaude}
                    onChange={onRouteClaudeToggle}
                  />
                </Tooltip>
              </div>
            </div>
          ) },
          { key: 'codex', label: 'Codex', children: (
            <section aria-label={t('claudeCodeConfig.codexSettingsTitle')}>
              <div style={routeRowStyle(routeCodex, gatewayRunning)}>
                <Space size={6} wrap style={{ minWidth: 0 }}>
                  <span style={dotStyle(routeCodex, gatewayRunning, palette.descriptionForeground)} />
                  <Text style={{ fontSize: 12, fontWeight: 500 }}>Codex</Text>
                  <Tag color={routeStatusColor(routeCodex, gatewayRunning)} style={{ margin: 0, fontSize: 10 }}>
                    {routeCodex
                      ? gatewayRunning ? t('claudeCodeConfig.gatewayRouteProxy') : t('claudeCodeConfig.gatewayRouteNotDetected')
                      : t('claudeCodeConfig.gatewayRouteDirect')}
                  </Tag>
                  <Tooltip title={t('claudeCodeConfig.modelHotSwitchCodexHint')}>
                    <QuestionCircleOutlined style={{ opacity: 0.5, cursor: 'help', fontSize: 11 }} />
                  </Tooltip>
                </Space>
                <div style={routeActionsStyle}>
                  {onSyncCodexConfig ? (
                    <Tooltip title={t('claudeCodeConfig.syncCodexConfigHint')}>
                      <Button type="text" size="small" icon={<SyncOutlined />} onClick={onSyncCodexConfig} aria-label={t('claudeCodeConfig.syncCodexConfig')} />
                    </Tooltip>
                  ) : null}
                  {onRestartCodex ? (
                    <Tooltip title={t('claudeCodeConfig.restartCodexHint')}>
                      <Button type="text" size="small" icon={<ReloadOutlined />} onClick={onRestartCodex} aria-label={t('claudeCodeConfig.restartCodex')} />
                    </Tooltip>
                  ) : null}
                  <Tooltip title={t('claudeCodeConfig.gatewayCodexProxyEnable')}>
                    <Switch
                      size="small"
                      checked={routeCodex}
                      loading={gatewayToggling}
                      disabled={!codexProxyAvailable && !routeCodex}
                      onChange={onRouteCodexToggle}
                    />
                  </Tooltip>
                </div>
              </div>
              <CodexDeviceLoginPanel t={t} />
            </section>
          ) },
        ]} />

        {(routeClaude || routeCodex) ? (
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${palette.panelBorder}` }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              <Space size={6} wrap>
                <Switch
                  size="small"
                  checked={failoverEnabled && showFailoverToggle}
                  disabled={!showFailoverToggle}
                  onChange={onFailoverToggle}
                />
                <Text style={{ fontSize: 12 }}>{t('claudeCodeConfig.failoverEnable')}</Text>
                <Tag color={failoverEnabled && showFailoverToggle ? 'blue' : 'default'} style={{ margin: 0, fontSize: 10 }}>
                  {t(showFailoverToggle ? (failoverEnabled ? 'claudeCodeConfig.failoverReady' : 'claudeCodeConfig.failoverNeedBackup') : 'claudeCodeConfig.failoverNeedBackup')}
                </Tag>
                {Object.entries(failoverHealth).map(([baseUrl, health]) => (
                  <Tag
                    key={baseUrl}
                    color={health === 'healthy' ? 'green' : health === 'degraded' ? 'gold' : 'red'}
                    style={{ margin: 0, fontSize: 10 }}
                  >
                    {t(`claudeCodeConfig.failoverHealth.${health}`)}
                  </Tag>
                ))}
                <Tooltip title={t('claudeCodeConfig.failoverHint')}>
                  <QuestionCircleOutlined style={{ opacity: 0.65, cursor: 'help' }} />
                </Tooltip>
              </Space>
            </div>
            {failoverEnabled && showFailoverToggle ? (
              <div style={{ marginTop: 10, padding: '10px 12px', border: `1px solid ${palette.panelBorder}`, borderRadius: 8, background: palette.codeBlockBackground }}>
                <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 8 }}>
                  {t('claudeCodeConfig.failoverSelectBackups')}
                </Text>
                {routeClaude ? (
                  <div style={{ marginBottom: 8 }}>
                    <Text strong style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                      {t('claudeCodeConfig.failoverBackupsFor', { role: 'Claude' })}
                    </Text>
                    {providers.filter((p) => !p.activeClaude && providerEligibleForRoleUpstream(p, 'claude')).map((p) => (
                      <div
                        key={p.id}
                        onClick={() => onToggleFailoverProvider(p.id, 'claude')}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '3px 10px',
                          margin: '2px 4px 2px 0',
                          borderRadius: 4,
                          cursor: 'pointer',
                          border: `1px solid ${p.failoverClaude ? '#fa8c16' : palette.panelBorder}`,
                          background: p.failoverClaude ? 'rgba(250, 140, 22, 0.08)' : 'transparent',
                          fontSize: 11,
                          color: p.failoverClaude ? '#fa8c16' : palette.descriptionForeground,
                        }}
                      >
                        {p.failoverClaude ? <CheckOutlined style={{ fontSize: 10 }} /> : null}
                        {p.name || p.baseUrl || t('claudeCodeConfig.providerUnnamed')}
                      </div>
                    ))}
                    {providers.filter((p) => !p.activeClaude && providerEligibleForRoleUpstream(p, 'claude')).length === 0 ? (
                      <Text type="secondary" style={{ fontSize: 10 }}>{t('claudeCodeConfig.failoverNoBackups')}</Text>
                    ) : null}
                  </div>
                ) : null}
                {routeCodex ? (
                  <div>
                    <Text strong style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                      {t('claudeCodeConfig.failoverBackupsFor', { role: 'Codex' })}
                    </Text>
                    {providers.filter((p) => !p.activeCodex && providerEligibleForRoleUpstream(p, 'codex')).map((p) => (
                      <div
                        key={p.id}
                        onClick={() => onToggleFailoverProvider(p.id, 'codex')}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '3px 10px',
                          margin: '2px 4px 2px 0',
                          borderRadius: 4,
                          cursor: 'pointer',
                          border: `1px solid ${p.failoverCodex ? '#fa8c16' : palette.panelBorder}`,
                          background: p.failoverCodex ? 'rgba(250, 140, 22, 0.08)' : 'transparent',
                          fontSize: 11,
                          color: p.failoverCodex ? '#fa8c16' : palette.descriptionForeground,
                        }}
                      >
                        {p.failoverCodex ? <CheckOutlined style={{ fontSize: 10 }} /> : null}
                        {p.name || p.baseUrl || t('claudeCodeConfig.providerUnnamed')}
                      </div>
                    ))}
                    {providers.filter((p) => !p.activeCodex && providerEligibleForRoleUpstream(p, 'codex')).length === 0 ? (
                      <Text type="secondary" style={{ fontSize: 10 }}>{t('claudeCodeConfig.failoverNoBackups')}</Text>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <ClaudeCodeConfigSection {...providerSectionCommon} mode="unified" onReset={onResetClaude} />
      {anyRouteEnabled ? (
        <>
          <Divider orientation="left" plain style={{ margin: '20px 0 12px', fontSize: 12 }}>
            {t('claudeCodeConfig.usageDivider')}
          </Divider>
          <GatewayUsagePanel
            t={t}
            palette={palette}
            gatewayStatus={gatewayStatus}
            records={usageRecords}
            loading={usageLoading}
            onRefresh={onRefreshUsage}
            onClear={onClearUsage}
            customPricing={customPricing}
            onGetPricing={onGetPricing}
            onRefreshPricing={onRefreshPricing}
            onSavePricing={onSavePricing}
            onClearPricing={onClearPricing}
            enabledApps={usageEnabledApps}
          />
        </>
      ) : (
        <Text type="secondary" style={{ display: 'block', marginTop: 16, fontSize: 12 }}>
          {t('claudeCodeConfig.usageEnableRouteHint')}
        </Text>
      )}

      <div
        style={{
          marginTop: 16,
          padding: '0 4px',
          borderRadius: 8,
          border: `1px solid ${palette.panelBorder}`,
          background: palette.codeBlockBackground,
        }}
      >
        <Collapse
          ghost
          size="small"
          activeKey={advancedKeys}
          onChange={(keys) => setAdvancedKeys(Array.isArray(keys) ? keys : [keys])}
          items={[
            {
              key: 'advanced',
              label: (
                <Text strong style={{ fontSize: 12 }}>{t('claudeCodeConfig.advancedSettingsTitle')}</Text>
              ),
              children: (
                <div style={{ paddingBottom: 8 }}>
                  <AdvancedSectionHeader
                    title={t('claudeCodeConfig.advancedSectionNetwork')}
                    hint={t('claudeCodeConfig.advancedSectionNetworkHint')}
                  />
                  <Space.Compact style={{ width: '100%', marginBottom: 14 }}>
                    <Input
                      ref={networkInput}
                      aria-label={t('claudeCodeConfig.outboundProxyLabel')}
                      size="small"
                      placeholder={t('claudeCodeConfig.outboundProxyPlaceholder')}
                      value={proxyDraft}
                      onChange={(e) => setProxyDraft(e.target.value)}
                    />
                    <Button
                      size="small"
                      type="primary"
                      disabled={!onSaveOutboundProxy}
                      onClick={() => onSaveOutboundProxy?.(proxyDraft.trim())}
                    >
                      {t('claudeCodeConfig.outboundProxySave')}
                    </Button>
                  </Space.Compact>

                  <AdvancedSectionHeader
                    title={t('claudeCodeConfig.rectifierTitle')}
                    hint={t('claudeCodeConfig.rectifierHint')}
                    switchChecked={rectifier.enabled}
                    switchDisabled={!onRectifierChange}
                    onSwitchChange={(checked) => onRectifierChange?.({ enabled: checked })}
                  />
                  {(
                    [
                      ['thinkingSignature', 'rectifierThinkingSignature', 'rectifierThinkingSignatureHint'],
                      ['thinkingBudget', 'rectifierThinkingBudget', 'rectifierThinkingBudgetHint'],
                      ['unsupportedImageDowngrade', 'rectifierImageDowngrade', 'rectifierImageDowngradeHint'],
                      ['heuristicTextOnlyModels', 'rectifierHeuristicTextOnly', 'rectifierHeuristicTextOnlyHint'],
                    ] as const
                  ).map(([key, labelKey, hintKey]) => (
                    <SettingRow
                      key={key}
                      label={t(`claudeCodeConfig.${labelKey}`)}
                      hint={t(`claudeCodeConfig.${hintKey}`)}
                      checked={Boolean(rectifier[key]) && rectifier.enabled}
                      disabled={!rectifier.enabled || !onRectifierChange}
                      onChange={(checked) => onRectifierChange?.({ [key]: checked })}
                    />
                  ))}

                  <AdvancedSectionHeader
                    title={t('claudeCodeConfig.optimizerTitle')}
                    hint={t('claudeCodeConfig.optimizerHint')}
                    style={{ marginTop: 14 }}
                    switchChecked={optimizer.enabled}
                    switchDisabled={!onOptimizerChange}
                    onSwitchChange={(checked) => onOptimizerChange?.({ enabled: checked })}
                  />
                  {(
                    [
                      ['thinkingOptimizer', 'optimizerThinking', 'optimizerThinkingHint'],
                      ['cacheInjection', 'optimizerCache', 'optimizerCacheHint'],
                    ] as const
                  ).map(([key, labelKey, hintKey]) => (
                    <SettingRow
                      key={key}
                      label={t(`claudeCodeConfig.${labelKey}`)}
                      hint={t(`claudeCodeConfig.${hintKey}`)}
                      checked={Boolean(optimizer[key]) && optimizer.enabled}
                      disabled={!optimizer.enabled || !onOptimizerChange}
                      onChange={(checked) => onOptimizerChange?.({ [key]: checked })}
                    />
                  ))}
                </div>
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}

function routeRowStyle(active: boolean, running: boolean): React.CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    padding: '8px 10px',
    borderRadius: 6,
    background: active ? 'rgba(22, 119, 255, 0.04)' : 'transparent',
    border: active ? '1px solid rgba(22, 119, 255, 0.15)' : '1px solid transparent',
  };
}

const routeActionsStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 4,
  flexShrink: 0,
};

function AdvancedSectionHeader(props: {
  title: string;
  hint: string;
  style?: React.CSSProperties;
  switchChecked?: boolean;
  switchDisabled?: boolean;
  onSwitchChange?: (checked: boolean) => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        marginBottom: 8,
        ...props.style,
      }}
    >
      <Space size={6} wrap>
        <Text style={{ fontSize: 12, fontWeight: 600 }}>{props.title}</Text>
        <Tooltip title={props.hint}>
          <QuestionCircleOutlined style={{ opacity: 0.65, cursor: 'help' }} />
        </Tooltip>
      </Space>
      {props.onSwitchChange ? (
        <Switch
          size="small"
          checked={Boolean(props.switchChecked)}
          disabled={props.switchDisabled}
          onChange={props.onSwitchChange}
        />
      ) : null}
    </div>
  );
}

function SettingRow(props: {
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        marginTop: 8,
        paddingLeft: 4,
      }}
    >
      <Space size={4}>
        <Text style={{ fontSize: 11 }}>{props.label}</Text>
        <Tooltip title={props.hint}>
          <QuestionCircleOutlined style={{ opacity: 0.55, cursor: 'help', fontSize: 10 }} />
        </Tooltip>
      </Space>
      <Switch size="small" checked={props.checked} disabled={props.disabled} onChange={props.onChange} />
    </div>
  );
}

function dotStyle(active: boolean, running: boolean, fallback: string): React.CSSProperties {
  return {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: active ? (running ? '#52c41a' : '#1677ff') : fallback,
    flexShrink: 0,
  };
}

function routeStatusColor(active: boolean, running: boolean): 'success' | 'processing' | 'default' {
  if (!active) return 'default';
  return running ? 'success' : 'processing';
}
