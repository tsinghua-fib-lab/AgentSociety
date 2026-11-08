import * as React from 'react';
import {
  Button,
  Checkbox,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  BarChartOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type { ClaudeModelOption, ProviderAvailabilityResult, ProviderUsageQueryResult } from './claudeCodeTypes';
import { getProviderPresetsForRole, findPresetByUrl } from './aiCliProviderPresets';
import {
  isOfficialAnthropicBaseUrl,
  isOfficialOpenAiBaseUrl,
  type AiCliApiKind,
} from '../../aiCli/officialEndpoints';
import { ClaudeModelSelect } from './ClaudeModelSelect';
import type { AiCliProviderRecord } from './aiCliProviderTypes';
import { autoMapClaudeRoleModels } from './aiCliProviderTypes';
import { inferProviderAuthMode, providerSupportsRole, clampProviderRoleFlags } from './providerAuth';
import { supportsProviderUsageQuery } from './providerUsageSupport';
import { normalizeProviderBaseUrl } from './providerBaseUrl';
import { shouldShowProviderModelConfiguration } from '../../services/manualConfigSync';

const { Text } = Typography;

const CUSTOM_PRESET = 'custom';

type ClaudeRoleRow = {
  role: 'sonnet' | 'opus' | 'fable' | 'haiku';
  roleLabelKey: string;
  modelKey: 'sonnetModel' | 'opusModel' | 'fableModel' | 'haikuModel';
  displayKey: 'sonnetDisplayName' | 'opusDisplayName' | 'fableDisplayName' | 'haikuDisplayName';
  declareKey?: 'declareSonnet1m' | 'declareOpus1m' | 'declareFable1m';
};

const CLAUDE_ROLE_ROWS: ClaudeRoleRow[] = [
  {
    role: 'sonnet',
    roleLabelKey: 'claudeCodeConfig.roleSonnet',
    modelKey: 'sonnetModel',
    displayKey: 'sonnetDisplayName',
    declareKey: 'declareSonnet1m',
  },
  {
    role: 'opus',
    roleLabelKey: 'claudeCodeConfig.roleOpus',
    modelKey: 'opusModel',
    displayKey: 'opusDisplayName',
    declareKey: 'declareOpus1m',
  },
  {
    role: 'fable',
    roleLabelKey: 'claudeCodeConfig.roleFable',
    modelKey: 'fableModel',
    displayKey: 'fableDisplayName',
    declareKey: 'declareFable1m',
  },
  {
    role: 'haiku',
    roleLabelKey: 'claudeCodeConfig.roleHaiku',
    modelKey: 'haikuModel',
    displayKey: 'haikuDisplayName',
  },
];

const sectionStyle = (palette: VscodeThemePalette): React.CSSProperties => ({
  borderTop: `1px solid ${palette.panelBorder}`,
  paddingTop: 10,
});

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  display: 'block',
  marginBottom: 4,
};

function connectionFingerprint(
  baseUrl: string,
  apiKey: string,
  apiKind?: AiCliApiKind
): string {
  return `${baseUrl.trim()}::${apiKey}::${apiKind ?? ''}`;
}

type ProviderEditorProps = {
  t: TFunction;
  palette: VscodeThemePalette;
  provider: AiCliProviderRecord;
  isNew?: boolean;
  models: ClaudeModelOption[];
  modelsLoading: boolean;
  modelsError: string | null;
  availability?: ProviderAvailabilityResult;
  availabilityResults?: Record<string, ProviderAvailabilityResult>;
  providerUsage?: ProviderUsageQueryResult & { loading?: boolean };
  onQueryProviderUsage?: () => void;
  onSave: (p: AiCliProviderRecord) => void;
  onActivate?: (role: 'claude' | 'codex') => void;
  onRemove?: () => void;
  onCheckAvailability: (baseUrl: string, apiKey: string, apiKind?: AiCliApiKind) => void;
  isProviderChecking?: (baseUrl: string) => boolean;
  onFetchModels: (baseUrl: string, apiKey: string, apiKind?: AiCliApiKind) => void;
};

export function ProviderEditor({
  t,
  palette,
  provider,
  isNew,
  models,
  modelsLoading,
  modelsError,
  availability,
  availabilityResults,
  providerUsage,
  onQueryProviderUsage,
  onSave,
  onActivate,
  onRemove,
  onCheckAvailability,
  isProviderChecking,
  onFetchModels,
}: ProviderEditorProps) {
  const [draft, setDraft] = React.useState(provider);
  const providerIdRef = React.useRef(provider.id);
  const autoFetchFingerprintRef = React.useRef('');

  React.useEffect(() => {
    if (providerIdRef.current !== provider.id) {
      providerIdRef.current = provider.id;
      autoFetchFingerprintRef.current = '';
      setDraft(provider);
      return;
    }
    setDraft((prev) => {
      if (prev.apiKey.trim() || !provider.apiKey.trim()) {
        return prev;
      }
      return { ...prev, apiKey: provider.apiKey };
    });
  }, [provider]);

  React.useEffect(() => {
    setDraft((prev) => ({ ...prev, activeClaude: provider.activeClaude, activeCodex: provider.activeCodex }));
  }, [provider.activeClaude, provider.activeCodex]);

  const patch = (partial: Partial<AiCliProviderRecord>) => {
    setDraft((prev) => clampProviderRoleFlags({ ...prev, ...partial }));
  };

  const isOfficialUrl = (baseUrl: string) => {
    const trimmed = baseUrl.trim();
    return Boolean(trimmed) && (isOfficialOpenAiBaseUrl(trimmed) || isOfficialAnthropicBaseUrl(trimmed));
  };
  const officialUrl = isOfficialUrl(draft.baseUrl);
  const effectiveAvailability =
    availabilityResults?.[normalizeProviderBaseUrl(draft.baseUrl)] ?? availability;

  const layoutApiKind = draft.apiKind ?? effectiveAvailability?.apiKind;
  const isOpenAiProvider = layoutApiKind === 'openai';
  // Do not force both Claude/Codex panels open for a blank "new" draft.
  const servesClaude =
    (layoutApiKind != null && layoutApiKind !== 'openai') ||
    draft.activeClaude ||
    draft.failoverClaude;
  const servesCodex =
    isOpenAiProvider || draft.activeCodex || draft.failoverCodex;
  const authMode = inferProviderAuthMode({ ...draft, apiKind: layoutApiKind });
  const isSubscription = authMode === 'subscription';
  const canUseApi = isSubscription || Boolean(draft.apiKey.trim());
  const canProbe = Boolean(draft.baseUrl.trim()) && Boolean(draft.apiKey.trim()) && Boolean(layoutApiKind) && !isSubscription;
  const activeProtocolChanged =
    (provider.activeClaude && !providerSupportsRole(draft, 'claude')) ||
    (provider.activeCodex && !providerSupportsRole(draft, 'codex'));
  const canSave = !activeProtocolChanged && (isSubscription || (Boolean(draft.baseUrl.trim()) && Boolean(draft.apiKey.trim()) && Boolean(layoutApiKind)));
  const matchedPreset = findPresetByUrl(draft.baseUrl, layoutApiKind)?.id ?? CUSTOM_PRESET;
  const selectedForClaude = draft.activeClaude;
  const selectedForCodex = draft.activeCodex;

  const selectableModels = autoFetchFingerprintRef.current === connectionFingerprint(draft.baseUrl, draft.apiKey, layoutApiKind) ? models : [];

  const presetOptions = [
    {
      label: t('claudeCodeConfig.gatewayClaudeBlockTitle'),
      options: getProviderPresetsForRole('claude').map((p) => ({
        value: p.id,
        label: t(`claudeCodeConfig.baseUrlPresets.${p.id}`),
      })),
    },
    {
      label: t('claudeCodeConfig.gatewayCodexBlockTitle'),
      options: getProviderPresetsForRole('codex').map((p) => ({
        value: p.id,
        label: t(`claudeCodeConfig.baseUrlPresets.${p.id}`),
      })),
    },
    {
      label: t('claudeCodeConfig.baseUrlCustom'),
      options: [{ value: CUSTOM_PRESET, label: t('claudeCodeConfig.baseUrlCustom') }],
    },
  ];

  React.useEffect(() => {
    const fingerprint = connectionFingerprint(draft.baseUrl, draft.apiKey, layoutApiKind);
    if (!canProbe) {
      if (autoFetchFingerprintRef.current !== fingerprint) {
        autoFetchFingerprintRef.current = fingerprint;
        onFetchModels(draft.baseUrl, '', layoutApiKind);
      }
      return;
    }
    if (autoFetchFingerprintRef.current === fingerprint) {
      return;
    }
    const timer = window.setTimeout(() => {
      autoFetchFingerprintRef.current = fingerprint;
      onFetchModels(draft.baseUrl, draft.apiKey, layoutApiKind);
    }, 800);
    return () => window.clearTimeout(timer);
  }, [canProbe, draft.baseUrl, draft.apiKey, layoutApiKind, onFetchModels]);

  // Intentionally no auto-fill of role/default models after fetch.
  // Blank fields stay blank until the user picks models or clicks「智能填充」.

  const protocolTag = () => {
    if (!layoutApiKind) {
      return <Tag style={{ margin: 0, fontSize: 10 }}>{t('claudeCodeConfig.providerProtocolAuto')}</Tag>;
    }
    return (
      <Tag color={layoutApiKind === 'openai' ? 'blue' : 'purple'} style={{ margin: 0, fontSize: 10 }}>
        {layoutApiKind === 'openai'
          ? t('claudeCodeConfig.providerProtocolOpenAiDetected')
          : t('claudeCodeConfig.providerProtocolAnthropicDetected')}
      </Tag>
    );
  };

  const availabilityTag = () => {
    if (!effectiveAvailability) {
      return <Tag style={{ margin: 0, fontSize: 10 }}>{t('claudeCodeConfig.providerCheckNotRun')}</Tag>;
    }
    if (!effectiveAvailability.ok) {
      const errorKey = effectiveAvailability.error ? `claudeCodeConfig.modelsFetchErrors.${effectiveAvailability.error}` : '';
      const errorText =
        errorKey && t(errorKey) !== errorKey
          ? t(errorKey)
          : effectiveAvailability.error ?? t('claudeCodeConfig.providerUnavailable');
      return (
        <Tag
          color="error"
          style={{ margin: 0, fontSize: 11 }}
          title={effectiveAvailability.detail
            ? `${errorText}: ${effectiveAvailability.detail}`
            : errorText}
        >
          <CloseCircleOutlined /> {errorText}
        </Tag>
      );
    }
    return (
      <Tag color="success" style={{ margin: 0, fontSize: 11 }}>
        <CheckCircleOutlined /> {t('claudeCodeConfig.providerAvailableWithProtocol', {
          count: effectiveAvailability.models,
          protocol: effectiveAvailability.apiKind === 'openai'
            ? t('claudeCodeConfig.providerProtocolOpenAiDetected')
            : t('claudeCodeConfig.providerProtocolAnthropicDetected'),
        })}
      </Tag>
    );
  };

  const renderUsage = () => {
    if (isNew) {
      return (
        <Text type="secondary" style={{ fontSize: 11 }}>
          {t('claudeCodeConfig.providerQuotaAfterSave')}
        </Text>
      );
    }
    const supported = supportsProviderUsageQuery(draft.baseUrl, {
      apiKind: layoutApiKind,
      authMode: inferProviderAuthMode({ ...draft, apiKind: layoutApiKind }),
    });
    if (!supported) {
      return null;
    }
    const usage = providerUsage;
    const refresh = onQueryProviderUsage ? (
      <Button
        type="text"
        size="small"
        loading={usage?.loading}
        icon={<ReloadOutlined />}
        aria-label={t('claudeCodeConfig.providerQueryQuota')}
        onClick={onQueryProviderUsage}
      />
    ) : null;
    if (usage?.ok && usage.summary) {
      return (
        <Space size={4}>
          <BarChartOutlined style={{ color: palette.linkForeground }} />
          <Tooltip title={usage.plans?.map((plan) => `${plan.name}: ${plan.remaining}`).join('\n')}>
            <Text style={{ fontSize: 11 }}>{usage.summary}</Text>
          </Tooltip>
          {refresh}
        </Space>
      );
    }
    if (usage && !usage.ok && usage.error && !usage.loading) {
      const errorKey = `claudeCodeConfig.providerUsageErrors.${usage.error}`;
      const errorText = t(errorKey) !== errorKey ? t(errorKey) : usage.error;
      return (
        <Space size={4}>
          <Tag color="error" style={{ margin: 0, fontSize: 10 }}>{errorText}</Tag>
          {refresh}
        </Space>
      );
    }
    return (
      <Space size={4}>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {usage?.loading
            ? t('claudeCodeConfig.providerQuotaLoading')
            : t('claudeCodeConfig.providerQueryQuota')}
        </Text>
        {refresh}
      </Space>
    );
  };

  const handlePresetChange = (id: string) => {
    autoFetchFingerprintRef.current = '';
    if (id === CUSTOM_PRESET) {
      patch({
        name: draft.name.trim() ? draft.name : '',
        baseUrl: '',
        apiKey: '',
        apiKind: undefined,
        authMode: 'api',
      });
      return;
    }
    const preset = [...getProviderPresetsForRole('claude'), ...getProviderPresetsForRole('codex')].find((p) => p.id === id);
    if (!preset) {
      return;
    }
    patch({
      baseUrl: preset.url,
      ...(normalizeProviderBaseUrl(draft.baseUrl) !== normalizeProviderBaseUrl(preset.url) ? { apiKey: '' } : {}),
      apiKind: preset.apiKind,
      authMode: preset.official ? 'subscription' : 'api',
      name: draft.name.trim() ? draft.name : t(`claudeCodeConfig.baseUrlPresets.${preset.id}`),
      // Provider selection changes the draft; activation is a separate action.
      activeClaude: draft.activeClaude,
      activeCodex: draft.activeCodex,
    });
  };

  const handleAutoMap = () => {
    if (selectableModels.length === 0) {
      return;
    }
    const roleMapped = autoMapClaudeRoleModels(selectableModels, draft);
    patch(roleMapped);
  };

  const handleCheck = () => {
    autoFetchFingerprintRef.current = '';
    onCheckAvailability(draft.baseUrl, draft.apiKey, layoutApiKind);
  };

  const handleManualFetch = () => {
    autoFetchFingerprintRef.current = connectionFingerprint(draft.baseUrl, draft.apiKey, layoutApiKind);
    onFetchModels(draft.baseUrl, draft.apiKey, layoutApiKind);
  };

  const save = () => {
    const finalKind = layoutApiKind;
    const nextDraft = {
      ...draft,
      apiKind: finalKind,
      authMode: officialUrl
        ? authMode
        : inferProviderAuthMode({ ...draft, apiKind: finalKind, authMode: 'api' }),
    };
    if (!nextDraft.model?.trim() && nextDraft.sonnetModel?.trim()) {
      nextDraft.model = nextDraft.sonnetModel;
    }
    for (const row of CLAUDE_ROLE_ROWS) {
      const model = nextDraft[row.modelKey]?.trim();
      const display = nextDraft[row.displayKey]?.trim();
      if (model && !display) {
        nextDraft[row.displayKey] = model;
      }
    }
    onSave(nextDraft);
  };

  const checkingAvailability = isProviderChecking?.(draft.baseUrl) ?? false;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          padding: '8px 10px',
          borderRadius: 8,
          background: palette.surfaceMuted,
          border: `1px solid ${palette.panelBorder}`,
        }}
      >
        <Space size={6} wrap>
          {protocolTag()}
          {availabilityTag()}
        </Space>
        {renderUsage()}
      </div>

      <div>
        <Space size={6} style={{ marginBottom: 8 }}>
          <Text strong style={{ fontSize: 12 }}>{t('claudeCodeConfig.providerConnectionSection')}</Text>
          <Tooltip title={t('claudeCodeConfig.providerConnectionHint')}>
            <QuestionCircleOutlined style={{ opacity: 0.65, cursor: 'help' }} />
          </Tooltip>
        </Space>
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <Input
            size="small"
            placeholder={t('claudeCodeConfig.providerNamePlaceholder')}
            value={draft.name}
            onChange={(e) => patch({ name: e.target.value })}
          />
          <Space.Compact style={{ width: '100%' }}>
            <Select
              size="small"
              value={matchedPreset}
              options={presetOptions}
              style={{ width: 168, flexShrink: 0 }}
              popupMatchSelectWidth={false}
              onChange={handlePresetChange}
            />
            <Input
              size="small"
              placeholder={t('claudeCodeConfig.providerUrlPlaceholder')}
              value={draft.baseUrl}
              onChange={(e) => {
                const nextBaseUrl = e.target.value;
                autoFetchFingerprintRef.current = '';
                const matched = findPresetByUrl(nextBaseUrl);
                patch({
                  baseUrl: nextBaseUrl,
                  apiKind: matched?.apiKind ?? draft.apiKind,
                  authMode: isOfficialUrl(nextBaseUrl) && draft.authMode !== 'api' ? 'subscription' : 'api',
                });
              }}
            />
          </Space.Compact>
          <Tag color={isSubscription ? 'gold' : 'default'} style={{ margin: 0, fontSize: 10 }}>
            {isSubscription ? t('claudeCodeConfig.providerAuthSubscription') : t('claudeCodeConfig.providerAuthApiKey')}
          </Tag>
          {officialUrl ? (
            <Select
              size="small"
              value={authMode}
              style={{ width: '100%' }}
              options={[
                {
                  value: 'subscription',
                  label: t(isOfficialOpenAiBaseUrl(draft.baseUrl) ? 'claudeCodeConfig.providerAuthCodexLogin' : 'claudeCodeConfig.providerAuthClaudeLogin'),
                },
                { value: 'api', label: t('claudeCodeConfig.providerAuthApiKey') },
              ]}
              onChange={(value) => patch({ authMode: value })}
            />
          ) : null}
          {!isSubscription ? (
            <>
              <Select
                size="small"
                aria-label={t('claudeCodeConfig.providerApiProtocol')}
                placeholder={t('claudeCodeConfig.providerApiProtocol')}
                value={layoutApiKind}
                options={[{ value: 'openai', label: 'OpenAI-compatible' }, { value: 'anthropic', label: 'Anthropic' }]}
                onChange={(apiKind) => patch({ apiKind })}
              />
              <Input.Password
                size="small"
                placeholder={t('claudeCodeConfig.providerKeyPlaceholder')}
                value={draft.apiKey}
                onChange={(e) => {
                  autoFetchFingerprintRef.current = '';
                  patch({ apiKey: e.target.value, authMode: 'api' });
                }}
                autoComplete="off"
              />
              <Space size={6} wrap style={{ width: '100%' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {t('claudeCodeConfig.providerAuthHeaderMode')}
                </Text>
                <Tooltip title={t('claudeCodeConfig.providerAuthHeaderModeHint')}>
                  <QuestionCircleOutlined style={{ opacity: 0.65, cursor: 'help' }} />
                </Tooltip>
                <Select
                  size="small"
                  style={{ minWidth: 180, flex: 1 }}
                  value={draft.authHeaderMode ?? 'auto'}
                  options={[
                    { value: 'auto', label: t('claudeCodeConfig.providerAuthHeaderAuto') },
                    { value: 'bearer', label: t('claudeCodeConfig.providerAuthHeaderBearer') },
                    { value: 'x-api-key', label: t('claudeCodeConfig.providerAuthHeaderXApiKey') },
                    { value: 'both', label: t('claudeCodeConfig.providerAuthHeaderBoth') },
                  ]}
                  onChange={(value) => patch({ authHeaderMode: value })}
                />
              </Space>
            </>
          ) : (
            <Text type="secondary" style={{ display: 'block', fontSize: 11 }}>
              {isOfficialOpenAiBaseUrl(draft.baseUrl)
                ? t('claudeCodeConfig.providerCodexSubscriptionHint')
                : t('claudeCodeConfig.providerClaudeSubscriptionHint')}
            </Text>
          )}
          <Space size={8} wrap>
            <Button
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={handleCheck}
              disabled={!canProbe}
              loading={checkingAvailability}
            >
              {t('claudeCodeConfig.providerCheckAvailability')}
            </Button>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={modelsLoading}
              disabled={!canProbe}
              onClick={handleManualFetch}
            >
              {t('claudeCodeConfig.fetchModels')}
            </Button>
          </Space>
        </Space>
      </div>

      <div style={sectionStyle(palette)}>
        <Space size={6} style={{ marginBottom: 8 }}>
          <Text strong style={{ fontSize: 12 }}>{t('claudeCodeConfig.providerUsageSection')}</Text>
          <Tooltip title={t('claudeCodeConfig.providerUsageHint')}>
            <QuestionCircleOutlined style={{ opacity: 0.65, cursor: 'help' }} />
          </Tooltip>
        </Space>
        <Space direction="vertical" style={{ width: '100%' }} size={6}>
          <Checkbox
            checked={selectedForClaude}
            disabled={!canUseApi || !providerSupportsRole(draft, 'claude') || provider.activeClaude}
            onChange={(e) => patch({ activeClaude: e.target.checked })}
          >
            <Text style={{ fontSize: 12 }}>{t('claudeCodeConfig.providerUseForClaude')}</Text>
          </Checkbox>
          <Checkbox
            checked={selectedForCodex}
            disabled={!canUseApi || !providerSupportsRole(draft, 'codex') || provider.activeCodex}
            onChange={(e) => patch({ activeCodex: e.target.checked })}
          >
            <Text style={{ fontSize: 12 }}>{t('claudeCodeConfig.providerUseForCodex')}</Text>
          </Checkbox>
        </Space>
        <Text type="secondary" style={{ display: 'block', fontSize: 11, marginTop: 6 }}>
          {t(activeProtocolChanged ? 'claudeCodeConfig.providerActiveProtocolHint' : 'claudeCodeConfig.providerSelectionHint')}
        </Text>
      </div>

      {shouldShowProviderModelConfiguration(Boolean(isNew)) ? (
      <div style={sectionStyle(palette)}>
        <Text strong style={{ fontSize: 12 }}>{t('claudeCodeConfig.modelMapping')}</Text>
        <Text type="secondary" style={{ display: 'block', fontSize: 11, margin: '2px 0 8px' }}>
          {t('claudeCodeConfig.providerUnifiedModelHint')}
        </Text>
        <Space size={8} wrap style={{ marginBottom: 8 }}>
          <Button size="small" icon={<ReloadOutlined />} disabled={selectableModels.length === 0} onClick={handleAutoMap}>
            {t('claudeCodeConfig.autoMapModels')}
          </Button>
          {modelsError ? (
            <Tag color="error" style={{ margin: 0 }}>{modelsError}</Tag>
          ) : selectableModels.length > 0 ? (
            <Tag color="success" style={{ margin: 0 }}>{t('claudeCodeConfig.modelsCount', { count: selectableModels.length })}</Tag>
          ) : (
            <Tag style={{ margin: 0 }}>{t('claudeCodeConfig.modelsInputHint')}</Tag>
          )}
        </Space>
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {servesClaude ? (
            <div>
              <Text strong style={{ fontSize: 12 }}>{t('claudeCodeConfig.claudeModelMappingSection')}</Text>
              <Text type="secondary" style={{ display: 'block', fontSize: 11, margin: '4px 0 8px' }}>
                {t('claudeCodeConfig.modelHotSwitchClaudeHint')}
              </Text>
              <Table
                size="small"
                pagination={false}
                rowKey="role"
                dataSource={CLAUDE_ROLE_ROWS}
                columns={[
                  {
                    title: t('claudeCodeConfig.modelRoleColumn'),
                    dataIndex: 'role',
                    width: 88,
                    render: (_value, row) => (
                      <Text style={{ fontSize: 12 }}>{t(row.roleLabelKey)}</Text>
                    ),
                  },
                  {
                    title: t('claudeCodeConfig.modelDisplayNameColumn'),
                    dataIndex: 'displayKey',
                    render: (_value, row) => (
                      <Input
                        size="small"
                        placeholder={draft[row.modelKey]?.trim() || t('claudeCodeConfig.modelDisplayNamePlaceholder')}
                        value={draft[row.displayKey] ?? ''}
                        onChange={(e) => patch({ [row.displayKey]: e.target.value })}
                      />
                    ),
                  },
                  {
                    title: t('claudeCodeConfig.modelRequestedColumn'),
                    dataIndex: 'modelKey',
                    render: (_value, row) => (
                      <ClaudeModelSelect
                        models={selectableModels}
                        value={draft[row.modelKey] ?? ''}
                        onChange={(v) => patch({ [row.modelKey]: v })}
                        placeholder={t('claudeCodeConfig.selectOrManual')}
                        loading={modelsLoading}
                      />
                    ),
                  },
                  {
                    title: t('claudeCodeConfig.modelDeclare1mColumn'),
                    dataIndex: 'declareKey',
                    width: 72,
                    align: 'center',
                    render: (_value, row) =>
                      row.declareKey ? (
                        <Checkbox
                          checked={Boolean(draft[row.declareKey])}
                          aria-label={t('claudeCodeConfig.modelDeclare1mColumn')}
                          onChange={(e) => patch({ [row.declareKey!]: e.target.checked })}
                        />
                      ) : null,
                  },
                ]}
              />
            </div>
          ) : null}
          {servesCodex ? (
            <div>
              <Text strong style={{ fontSize: 12 }}>{t('claudeCodeConfig.codexModelSection')}</Text>
              <Text type="secondary" style={{ display: 'block', fontSize: 11, margin: '4px 0 8px' }}>
                {t('claudeCodeConfig.modelHotSwitchCodexHint')}
              </Text>
              <Text type="secondary" style={labelStyle}>{t('claudeCodeConfig.defaultModel')}</Text>
              <ClaudeModelSelect
                models={selectableModels}
                value={draft.model ?? ''}
                onChange={(v) => patch({ model: v })}
                placeholder={t('claudeCodeConfig.selectOrManual')}
                loading={modelsLoading}
              />
              <Text type="secondary" style={{ display: 'block', fontSize: 10, marginTop: 2 }}>
                {t('claudeCodeConfig.modelDefaultHint')}
              </Text>
              <div style={{ marginTop: 8 }}>
                <Checkbox
                  checked={Boolean(draft.codexEnable1m)}
                  onChange={(e) => patch({ codexEnable1m: e.target.checked })}
                >
                  <Text style={{ fontSize: 12 }}>{t('claudeCodeConfig.codexEnable1m')}</Text>
                </Checkbox>
              </div>
              {draft.codexEnable1m ? (
                <Input
                  size="small"
                  type="number"
                  style={{ marginTop: 6 }}
                  placeholder={t('claudeCodeConfig.codexAutoCompactPlaceholder')}
                  value={draft.codexAutoCompactLimit ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value.trim();
                    patch({ codexAutoCompactLimit: raw ? Number(raw) : undefined });
                  }}
                />
              ) : null}
              <Text type="secondary" style={{ display: 'block', fontSize: 10, marginTop: 4 }}>
                {t('claudeCodeConfig.codexCatalogHint')}
              </Text>
            </div>
          ) : null}
        </Space>
      </div>
      ) : null}

      {!isNew ? (
      <div style={sectionStyle(palette)}>
        <Text type="secondary" style={labelStyle}>{t('claudeCodeConfig.permissionMode')}</Text>
        <Select
          size="small"
          style={{ width: '100%' }}
          allowClear
          value={draft.permissionMode || undefined}
          placeholder={t('claudeCodeConfig.permissionModePlaceholder')}
          onChange={(v) => patch({ permissionMode: v ?? '' })}
          options={[
            { value: '', label: t('claudeCodeConfig.permissionModeDefault') },
            { value: 'bypassPermissions', label: t('claudeCodeConfig.permissionModeBypass') },
          ]}
        />
      </div>
      ) : null}

      <Space wrap>
        <Button
          size="small"
          type="primary"
          icon={<SaveOutlined />}
          disabled={!canSave}
          onClick={save}
        >
          {isNew ? t('claudeCodeConfig.providerAdd') : t('claudeCodeConfig.providerSave')}
        </Button>
        {!isNew && onActivate && !provider.activeClaude && providerSupportsRole(provider, 'claude') ? (
          <Button size="small" onClick={() => onActivate('claude')}>
            {t('claudeCodeConfig.providerSwitchClaude')}
          </Button>
        ) : null}
        {!isNew && onActivate && !provider.activeCodex && providerSupportsRole(provider, 'codex') ? (
          <Button size="small" onClick={() => onActivate('codex')}>
            {t('claudeCodeConfig.providerSwitchCodex')}
          </Button>
        ) : null}
        {!isNew && onRemove ? (
          <Popconfirm title={t('claudeCodeConfig.providerRemoveConfirm')} onConfirm={onRemove}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        ) : null}
      </Space>
    </Space>
  );
}
