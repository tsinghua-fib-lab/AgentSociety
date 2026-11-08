import * as React from 'react';
import { Button, Card, Space, Radio, Tag, Tooltip, Typography } from 'antd';
import { EditOutlined, PlusOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type { ClaudeModelOption, ProviderUsageQueryResult, ProviderAvailabilityResult } from './claudeCodeTypes';
import type { AiCliApiKind } from '../../aiCli/officialEndpoints';
import type { AiCliProviderRecord } from './aiCliProviderTypes';
import { EMPTY_PROVIDER_DRAFT } from './aiCliProviderTypes';
import { ProviderEditor } from './AiCliProviderEditor';
import { inferProviderAuthMode, providerSupportsRole } from '../../aiCli/providerAuth';
import { supportsProviderUsageQuery } from '../../shared/providerUsage';
import { ProviderUsageCard } from './ProviderUsageCard';
import { normalizeProviderBaseUrl } from './providerBaseUrl';

const { Text } = Typography;

export type ProviderRole = 'claude' | 'codex' | 'unified';

export type AiCliProviderGroupProps = {
  t: TFunction;
  palette: VscodeThemePalette;
  role: ProviderRole;
  providers: AiCliProviderRecord[];
  loading: boolean;
  onSave: (provider: AiCliProviderRecord) => void;
  onAdd: (draft: Omit<AiCliProviderRecord, 'id'>) => void;
  onActivate: (id: string, role: 'claude' | 'codex') => void;
  onRemove: (id: string) => void;
  onCheckAvailability: (baseUrl: string, apiKey: string, apiKind?: AiCliApiKind) => void;
  isProviderChecking?: (baseUrl: string) => boolean;
  availabilityResults: Record<string, ProviderAvailabilityResult>;
  providerUsage: Record<string, ProviderUsageQueryResult & { loading?: boolean }>;
  onQueryProviderUsage: (id: string, force?: boolean) => void;
  modelsByProvider: Record<string, ClaudeModelOption[]>;
  modelsLoadingByProvider: Record<string, boolean>;
  modelsErrorByProvider: Record<string, string | null>;
  onFetchModels: (providerId: string, baseUrl: string, apiKey: string, apiKind?: AiCliApiKind) => void;
};

export function AiCliProviderGroup({
  t,
  palette,
  providers,
  loading,
  onSave,
  onAdd,
  onActivate,
  onRemove,
  onCheckAvailability,
  isProviderChecking,
  availabilityResults,
  providerUsage,
  onQueryProviderUsage,
  modelsByProvider,
  modelsLoadingByProvider,
  modelsErrorByProvider,
  onFetchModels,
}: AiCliProviderGroupProps) {
  const NEW_ID = `__new__`;
  const [showNew, setShowNew] = React.useState(false);
  const [editingIds, setEditingIds] = React.useState<Set<string>>(() => new Set());
  // A primary provider is an exclusive choice per CLI, rather than an on/off setting.
  const renderRoleChoices = (provider: AiCliProviderRecord) => {
    const authMode = inferProviderAuthMode(provider);
    const canActivate = authMode === 'subscription' || Boolean(provider.apiKey.trim());

    const roleChoice = (label: 'Claude' | 'Codex', active: boolean, isApplicable: boolean) => {
      if (!isApplicable) {
        return (
          <Text type="secondary" style={{ fontSize: 11, width: 130 }}>
            {t('claudeCodeConfig.providerRoleNotSupported', { tool: label })}
          </Text>
        );
      }
      return (
        <Tooltip title={!canActivate ? t('claudeCodeConfig.providerNeedCredentialsHint') : undefined}>
          <Space size={4}>
            <Radio
              name={`provider-primary-${label.toLowerCase()}`}
              aria-label={t(label === 'Claude' ? 'claudeCodeConfig.providerUseForClaude' : 'claudeCodeConfig.providerUseForCodex')}
              checked={active}
              disabled={!canActivate || loading}
              onChange={() => onActivate(provider.id, label === 'Claude' ? 'claude' : 'codex')}
            >
              <Text style={{ fontSize: 12, color: active ? palette.linkForeground : palette.descriptionForeground, minWidth: 40 }}>
                {label}
              </Text>
            </Radio>
            {active ? (
              <Tag color="blue" style={{ margin: 0, fontSize: 11, lineHeight: '16px' }}>
                {t('claudeCodeConfig.providerRolePrimary')}
              </Tag>
            ) : null}
          </Space>
        </Tooltip>
      );
    };

    return (
      <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
        {roleChoice('Claude', provider.activeClaude, providerSupportsRole(provider, 'claude'))}
        {roleChoice('Codex', provider.activeCodex, providerSupportsRole(provider, 'codex'))}
      </div>
    );
  };

  const newDraft: AiCliProviderRecord = {
    id: NEW_ID,
    activeClaude: false,
    activeCodex: false,
    ...EMPTY_PROVIDER_DRAFT,
    apiKind: undefined,
    authMode: 'api',
    baseUrl: '',
    name: '',
  };

  const renderProtocolTag = (provider: AiCliProviderRecord) => {
    if (!provider.apiKind) {
      return (
        <Tag style={{ margin: 0, fontSize: 11 }}>
          {t('claudeCodeConfig.providerProtocolAuto')}
        </Tag>
      );
    }
    return (
      <Tag color={provider.apiKind === 'openai' ? 'blue' : 'purple'} style={{ margin: 0, fontSize: 11 }}>
        {provider.apiKind === 'openai'
          ? t('claudeCodeConfig.providerProtocolOpenAiDetected')
          : t('claudeCodeConfig.providerProtocolAnthropicDetected')}
      </Tag>
    );
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <Space size={5} style={{ marginBottom: 8 }}>
        <Text strong style={{ fontSize: 13 }}>
          {t('claudeCodeConfig.providersDivider')}
        </Text>
        <Tooltip title={t('claudeCodeConfig.providerCenterHint')}>
          <QuestionCircleOutlined style={{ opacity: 0.65, cursor: 'help' }} />
        </Tooltip>
      </Space>
      <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 8 }}>
        {t('claudeCodeConfig.providerSelectionHint')}
      </Text>
      <Space direction="vertical" style={{ width: '100%' }} size={10}>
        {providers.map((p) => {
          const editing = editingIds.has(p.id);
          const hasAnyActive = p.activeClaude || p.activeCodex;
          const toggleEditing = () => {
            setEditingIds((current) => {
              const next = new Set(current);
              if (next.has(p.id)) {
                next.delete(p.id);
              } else {
                next.add(p.id);
              }
              return next;
            });
          };

          return (
            <Card
              key={p.id}
              size="small"
              style={{
                borderRadius: 12,
                borderColor: hasAnyActive ? palette.focusBorder : undefined,
                background: hasAnyActive ? palette.codeBlockBackground : undefined,
              }}
              title={
                <Space size={6} wrap>
                  <Text strong style={{ fontSize: 13 }}>{p.name || p.baseUrl || t('claudeCodeConfig.providerUnnamed')}</Text>
                  {renderProtocolTag(p)}
                  {hasAnyActive ? (
                    <Tag color="green" style={{ margin: 0, fontSize: 11 }}>
                      {t('claudeCodeConfig.providerSelected')}
                    </Tag>
                  ) : null}
                </Space>
              }
              extra={
                <Button size="small" icon={<EditOutlined />} onClick={toggleEditing}>
                  {t(editing ? 'claudeCodeConfig.providerCloseEditor' : 'claudeCodeConfig.providerEdit')}
                </Button>
              }
            >
              {!editing ? (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 8 }}>
                    <Text
                      type="secondary"
                      ellipsis={{ tooltip: p.baseUrl || t('claudeCodeConfig.providerSubscriptionDirect') }}
                      style={{ display: 'block', minWidth: 0, fontSize: 12 }}
                    >
                      {p.baseUrl || t('claudeCodeConfig.providerSubscriptionDirect')}
                    </Text>
                  </div>
                  {renderRoleChoices(p)}
                  {supportsProviderUsageQuery(p.baseUrl, { apiKind: p.apiKind, authMode: inferProviderAuthMode(p), usageQuery: p.usageQuery }) ? (
                    <ProviderUsageCard usage={providerUsage[p.id]} palette={palette} onRefresh={() => onQueryProviderUsage(p.id, true)} />
                  ) : null}
                </div>
              ) : (
                <ProviderEditor
                  t={t}
                  palette={palette}
                  provider={p}
                  models={modelsByProvider[p.id] ?? []}
                  modelsLoading={modelsLoadingByProvider[p.id] ?? false}
                  modelsError={modelsErrorByProvider[p.id] ?? null}
                  availability={availabilityResults[normalizeProviderBaseUrl(p.baseUrl)]}
                  availabilityResults={availabilityResults}
                  isProviderChecking={isProviderChecking}
                  onSave={(saved) => {
                    onSave(saved);
                  }}
                  onActivate={(role) => onActivate(p.id, role)}
                  onRemove={hasAnyActive ? undefined : () => onRemove(p.id)}
                  onCheckAvailability={onCheckAvailability}
                  providerUsage={providerUsage[p.id]}
                  onQueryProviderUsage={() => onQueryProviderUsage(p.id, true)}
                  onFetchModels={(baseUrl, apiKey, kind) =>
                    onFetchModels(p.id, baseUrl, apiKey, kind)
                  }
                />
              )}
            </Card>
          );
        })}
        {providers.length === 0 && !showNew ? (
          <Text type="secondary" style={{ fontSize: 12 }}>{t('claudeCodeConfig.providerEmpty')}</Text>
        ) : null}
        {showNew ? (
          <Card
            size="small"
            title={
              <Space size={6}>
                {t('claudeCodeConfig.providerAddTitle')}
                <Tooltip title={t('claudeCodeConfig.providerAddHint')}>
                  <QuestionCircleOutlined style={{ opacity: 0.65, cursor: 'help' }} />
                </Tooltip>
              </Space>
            }
            style={{ borderRadius: 12 }}
          >
            <ProviderEditor
              t={t}
              palette={palette}
              provider={newDraft}
              isNew
              models={modelsByProvider[NEW_ID] ?? []}
              modelsLoading={modelsLoadingByProvider[NEW_ID] ?? false}
              modelsError={modelsErrorByProvider[NEW_ID] ?? null}
              availabilityResults={availabilityResults}
              onSave={(d) => {
                onAdd({
                  name: d.name,
                  baseUrl: d.baseUrl,
                  apiKey: d.apiKey,
                  apiKind: d.apiKind,
                  authMode: d.authMode,
                  authHeaderMode: d.authHeaderMode,
                  activeClaude: d.activeClaude,
                  activeCodex: d.activeCodex,
                  failoverClaude: d.failoverClaude,
                  failoverCodex: d.failoverCodex,
                  model: d.model,
                  sonnetModel: d.sonnetModel,
                  opusModel: d.opusModel,
                  fableModel: d.fableModel,
                  haikuModel: d.haikuModel,
                  sonnetDisplayName: d.sonnetDisplayName,
                  opusDisplayName: d.opusDisplayName,
                  fableDisplayName: d.fableDisplayName,
                  haikuDisplayName: d.haikuDisplayName,
                  declareSonnet1m: d.declareSonnet1m,
                  declareOpus1m: d.declareOpus1m,
                  declareFable1m: d.declareFable1m,
                  codexEnable1m: d.codexEnable1m,
                  codexContextWindow: d.codexContextWindow,
                  codexAutoCompactLimit: d.codexAutoCompactLimit,
                  permissionMode: d.permissionMode,
                });
                setShowNew(false);
              }}
              onCheckAvailability={onCheckAvailability}
              isProviderChecking={isProviderChecking}
              onFetchModels={(baseUrl, apiKey, kind) =>
                onFetchModels(NEW_ID, baseUrl, apiKey, kind)
              }
            />
            <Button size="small" type="link" onClick={() => setShowNew(false)} style={{ marginTop: 4, padding: 0 }}>
              {t('claudeCodeConfig.providerCancelAdd')}
            </Button>
          </Card>
        ) : (
          <Button
            type="dashed"
            block
            icon={<PlusOutlined />}
            onClick={() => setShowNew(true)}
            style={{ marginTop: providers.length > 0 ? 4 : 0 }}
          >
            {t('claudeCodeConfig.providerAdd')}
          </Button>
        )}
      </Space>
    </div>
  );
}
