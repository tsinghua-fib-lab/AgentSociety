import * as React from 'react';
import {
  Alert, Button, Checkbox, Collapse, Dropdown, Empty, Input, Modal, Popconfirm, Select, Space, Switch, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  CloudServerOutlined, EditOutlined, ImportOutlined, LoginOutlined, PlusOutlined, QuestionCircleOutlined, ReloadOutlined, SyncOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { VSCodeAPI, McpServerRecord, McpProbeResult, McpPresetCatalogItem, McpTransport } from '../types';
import type { VscodeThemePalette } from '../../theme';
import { PageSection } from './PageSection';
import { ListCard } from './ListCard';
import { TabToolbar } from './TabToolbar';
import { parseMcpArgs, parseMcpStringMap } from '../../../shared/mcpServerDraft';
import { normalizeMcpHttpEndpoint } from '../../../services/mcpClient';
import { McpRegistryBrowser } from './McpRegistryBrowser';
import { McpImportDialog } from './McpImportDialog';
import type { McpImportSource } from '../../../services/mcpImport';
import { SKILL_UI } from '../uiTokens';

const { Text } = Typography;

type Props = {
  vscode: VSCodeAPI;
  palette: VscodeThemePalette;
  servers: McpServerRecord[];
  presets: McpPresetCatalogItem[];
  loading: boolean;
  probeById: Record<string, McpProbeResult | undefined>;
  probingIds: ReadonlySet<string>;
  onRefresh?: () => void;
  onProbeStart?: (id: string) => void;
};

const EMPTY_DRAFT = {
  name: '',
  transport: 'http' as McpTransport,
  url: '',
  command: '',
  args: '[]',
  envText: '{}',
  headersText: '{}',
  bearerTokenEnvVar: '',
  enabledClaude: true,
  enabledCodex: false,
};

export function McpIntegrationsPanel({
  vscode,
  palette,
  servers,
  presets,
  loading,
  probeById,
  probingIds,
  onRefresh,
  onProbeStart,
}: Props) {
  const { t } = useTranslation();
  const [registryOpen, setRegistryOpen] = React.useState(false);
  const [importSource, setImportSource] = React.useState<McpImportSource | null>(null);
  const [editorOpen, setEditorOpen] = React.useState(false);
  const [draft, setDraft] = React.useState(EMPTY_DRAFT);
  const [editing, setEditing] = React.useState<McpServerRecord>();
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState('');
  const saveRequest = React.useRef<string | undefined>(undefined);
  const saveCounter = React.useRef(0);
  const [query, setQuery] = React.useState('');
  const [target, setTarget] = React.useState('all');
  const [authPending, setAuthPending] = React.useState<Record<string, string>>({});
  const [authErrors, setAuthErrors] = React.useState<Record<string, string>>({});
  const authRequests = React.useRef<Record<string, string>>({});
  const authSequence = React.useRef(0);

  React.useEffect(() => {
    const listener = (event: MessageEvent) => {
      const { type, payload } = event.data ?? {};
      if (type !== 'mcpAuthenticationResult' || !payload || authRequests.current[payload.id] !== payload.requestId) { return; }
      delete authRequests.current[payload.id];
      setAuthPending((previous) => { const next = { ...previous }; delete next[payload.id]; return next; });
      if (payload.success) { message.info(t('skillManagement.mcpAuthOpened')); }
      else { setAuthErrors((previous) => ({ ...previous, [payload.id]: t(`skillManagement.mcpAuthErrors.${payload.error}`, { defaultValue: t('skillManagement.mcpAuthErrors.mcp_auth_start_failed') }) })); }
    };
    window.addEventListener('message', listener);
    return () => window.removeEventListener('message', listener);
  }, [t]);

  const authenticate = (row: McpServerRecord, app: 'claude' | 'codex') => {
    const requestId = `mcp-auth-${Date.now()}-${++authSequence.current}`;
    authRequests.current[row.id] = requestId;
    setAuthPending((previous) => ({ ...previous, [row.id]: requestId }));
    setAuthErrors((previous) => { const next = { ...previous }; delete next[row.id]; return next; });
    vscode.postMessage({ type: 'authenticateMcpServer', payload: { id: row.id, app, requestId } });
  };

  React.useEffect(() => {
    const listener = (event: MessageEvent) => {
      const data = event.data;
      if (!saveRequest.current || data?.payload?.requestId !== saveRequest.current) { return; }
      if (data.type === 'mcpServerSaved') { setEditorOpen(false); setSaving(false); saveRequest.current = undefined; }
      if (data.type === 'mcpError') { setSaveError(t(`skillManagement.mcpImport.errors.${data.payload.error}`, { defaultValue: data.payload.error })); setSaving(false); saveRequest.current = undefined; }
    };
    window.addEventListener('message', listener);
    return () => window.removeEventListener('message', listener);
  }, [t]);

  const filtered = servers.filter((row) => {
    const text = [row.name, row.url, row.command, ...(probeById[row.id]?.tools ?? [])].join(' ').toLowerCase();
    return text.includes(query.trim().toLowerCase()) && (target === 'all' ||
      (target === 'claude' && row.enabledClaude) || (target === 'codex' && row.enabledCodex) ||
      (target === 'disabled' && !row.enabledClaude && !row.enabledCodex));
  });
  const clearFilters = () => { setQuery(''); setTarget('all'); };

  const builtinServers = filtered.filter((row) => row.builtin === 'literature');
  const customServers = filtered.filter((row) => row.builtin !== 'literature');

  const openCreate = () => {
    setDraft(EMPTY_DRAFT);
    setEditing(undefined);
    setSaveError('');
    setEditorOpen(true);
  };

  const saveDraft = () => {
    if (!draft.name.trim()) {
      message.warning(t('skillManagement.mcpNameRequired'));
      return;
    }
    if (draft.transport !== 'stdio' && !normalizeMcpHttpEndpoint(draft.url)) {
      message.warning(t('skillManagement.mcpUrlRequired'));
      return;
    }
    if (draft.transport === 'stdio' && !draft.command.trim()) {
      message.warning(t('skillManagement.mcpCommandRequired'));
      return;
    }
    try {
      const args = parseMcpArgs(draft.args);
      const env = parseMcpStringMap(draft.envText);
      const httpHeaders = parseMcpStringMap(draft.headersText);
      const requestId = `mcp-save-${Date.now()}-${++saveCounter.current}`;
      saveRequest.current = requestId;
      setSaving(true); setSaveError('');
      vscode.postMessage({ type: 'saveMcpServer', requestId, payload: {
        ...editing, name: draft.name.trim(), transport: draft.transport,
        url: draft.transport === 'stdio' ? undefined : draft.url.trim(),
        command: draft.transport === 'stdio' ? draft.command.trim() : undefined,
        args: draft.transport === 'stdio' ? args : undefined,
        env: draft.transport === 'stdio' ? env : undefined,
        httpHeaders: draft.transport === 'stdio' ? undefined : httpHeaders,
        bearerTokenEnvVar: draft.transport === 'stdio' ? undefined : draft.bearerTokenEnvVar.trim() || undefined,
        enabledClaude: draft.enabledClaude, enabledCodex: draft.transport === 'sse' ? false : draft.enabledCodex,
      } });
      onRefresh?.();
    } catch { setSaveError(t('skillManagement.mcpJsonInvalid')); }

  };

  const renderStatus = (row: McpServerRecord) => {
    if (row.transport === 'sse') {
      return <Tag>{t('skillManagement.mcpSseClaudeOnly')}</Tag>;
    }
    if (row.transport !== 'http') { return null; }
    const probe = probeById[row.id];
    if (probingIds.has(row.id)) {
      return <Tag color="processing">{t('skillManagement.mcpProbing')}</Tag>;
    }
    if (!probe) {
      return <Tag>{t('skillManagement.mcpNotProbed')}</Tag>;
    }
    if (probe.authRequired) {
      return <Tooltip title={t('skillManagement.mcpProbeAuthHint')}><Tag color="warning">{t('skillManagement.mcpAuthRequired')}</Tag></Tooltip>;
    }
    return probe.ok ? (
      <Tag color="success">{t('skillManagement.mcpTools', { count: probe.tools.length })}</Tag>
    ) : (
      <Tooltip title={t(`skillManagement.mcpErrors.${probe.error}`, { defaultValue: probe.error || t('skillManagement.mcpProbeFailed') })}><Tag color="error">{t('skillManagement.mcpProbeFailed')}{probe.status ? ` · HTTP ${probe.status}` : ''}</Tag></Tooltip>
    );
  };

  const renderServerCard = (row: McpServerRecord) => (
    <ListCard
      key={row.id}
      palette={palette}
      accent={row.builtin === 'literature' ? palette.linkForeground : undefined}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <Text strong title={row.name} style={{ fontSize: 13, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name}</Text>
          {row.builtin === 'literature' ? (
            <Text type="secondary" style={{ display: 'block', fontSize: 11, lineHeight: 1.45, marginTop: 4 }}>
              {t('skillManagement.mcpBuiltinLiteratureDesc')}
            </Text>
          ) : null}
        </div>
        <Space size={4} wrap>
          <Tag>{row.transport}</Tag>
          {row.builtin === 'literature' ? <Tag color="blue">{t('skillManagement.mcpBuiltinLiterature')}</Tag> : null}
          {renderStatus(row)}
        </Space>
      </div>

      {row.transport === 'stdio' ? <Text type="secondary" style={{ display: 'block', fontSize: 12, overflowWrap: 'anywhere', marginBottom: 8 }}>{row.command}</Text> : row.url ? (
        <Text type="secondary" style={{ display: 'block', fontSize: 12, overflowWrap: 'anywhere', marginBottom: 8 }}>{(() => { try { const url = new URL(row.url!); return url.origin + url.pathname; } catch { return ''; } })()}</Text>
      ) : null}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 8,
          marginBottom: 12,
          padding: '8px 10px',
          borderRadius: SKILL_UI.radius.sm,
          background: palette.surfaceBackground,
          border: `1px solid ${palette.panelBorder}`,
        }}
      >
        <div>
          <Text type="secondary" style={{ fontSize: 10, display: 'block', marginBottom: 4 }}>
            Claude Code
          </Text>
          <Switch
            aria-label={`${row.name} · Claude Code`}
            size="small"
            checked={row.enabledClaude}
            disabled={loading || row.builtin === 'literature'}
            onChange={(checked) => {
              onRefresh?.();
              vscode.postMessage({
                type: 'toggleMcpServerApp',
                payload: { id: row.id, app: 'claude', enabled: checked },
              });
            }}
          />
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 10, display: 'block', marginBottom: 4 }}>
            Codex
          </Text>
          <Switch
            aria-label={`${row.name} · Codex`}
            size="small"
            checked={row.enabledCodex}
            disabled={loading || row.builtin === 'literature' || row.transport === 'sse'}
            onChange={(checked) => {
              onRefresh?.();
              vscode.postMessage({
                type: 'toggleMcpServerApp',
                payload: { id: row.id, app: 'codex', enabled: checked },
              });
            }}
          />
        </div>
      </div>

      <Space size={6} wrap>
        {row.transport === 'http' ? (
          <Tooltip title={t('skillManagement.mcpProbeHint')}><Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={probingIds.has(row.id)}
            onClick={() => {
              onProbeStart?.(row.id);
              vscode.postMessage({ type: 'probeMcpServer', payload: { id: row.id } });
            }}
          >
            {t('skillManagement.mcpProbe')}
          </Button></Tooltip>
        ) : null}
        {row.transport === 'http' && !row.builtin ? <Tooltip title={t('skillManagement.mcpAuthHint')}>
          <Dropdown menu={{ items: [
            { key: 'claude', label: t('skillManagement.mcpAuthClaude'), disabled: !row.enabledClaude, onClick: () => authenticate(row, 'claude') },
            { key: 'codex', label: t('skillManagement.mcpAuthCodex'), disabled: !row.enabledCodex, onClick: () => authenticate(row, 'codex') },
          ] }} trigger={['click']}>
            <Button size="small" icon={<LoginOutlined />} loading={Boolean(authPending[row.id])} disabled={loading || Boolean(authPending[row.id]) || (!row.enabledClaude && !row.enabledCodex)}>{t('skillManagement.mcpAuthenticate')}</Button>
          </Dropdown>
        </Tooltip> : null}
        {row.builtin === 'literature' ? (
          <Button
            size="small"
            type="primary"
            onClick={() => vscode.postMessage({ type: 'openLiteratureMcpConfig' })}
          >
            {t('skillManagement.mcpEditInConfig')}
          </Button>
        ) : (
          <Space size={6} wrap>
            <Button size="small" icon={<EditOutlined />} disabled={loading} onClick={() => {
              setEditing(row); setSaveError('');
              setDraft({ ...EMPTY_DRAFT, ...row, name: row.name, url: row.url ?? '', command: row.command ?? '',
                args: JSON.stringify(row.args ?? [], null, 2), envText: JSON.stringify(row.env ?? {}, null, 2),
                headersText: JSON.stringify(row.httpHeaders ?? {}, null, 2), bearerTokenEnvVar: row.bearerTokenEnvVar ?? '',
              });
              setEditorOpen(true);
            }}>{t('skillManagement.mcpEdit')}</Button>
            <Popconfirm title={t('skillManagement.mcpRemoveConfirm', { name: row.name })} okText={t('skillManagement.mcpRemove')} cancelText={t('skillManagement.cancel')}
              onConfirm={() => { onRefresh?.(); vscode.postMessage({ type: 'removeMcpServer', payload: { id: row.id } }); }}>
              <Button size="small" danger disabled={loading}>{t('skillManagement.mcpRemove')}</Button>
            </Popconfirm>
          </Space>
        )}
      </Space>
      {authErrors[row.id] ? <Alert type="error" showIcon title={authErrors[row.id]} style={{ marginTop: 10 }} closable onClose={() => setAuthErrors((previous) => { const next = { ...previous }; delete next[row.id]; return next; })} /> : null}
      {probeById[row.id]?.ok ? <Collapse size="small" style={{ marginTop: 10 }} items={[{
        key: 'tools', label: t('skillManagement.mcpTools', { count: probeById[row.id]!.tools.length }),
        children: <Space wrap>{probeById[row.id]!.tools.map((name) => <Tag key={name} style={{ maxWidth: '100%', whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{name}</Tag>)}</Space>,
      }]} /> : null}
    </ListCard>
  );

  return (
    <div>
      <TabToolbar
        left={(
          <div>
            <Space size={8}>
              <Text strong style={{ fontSize: 14 }}>{t('skillManagement.mcpIntroTitle')}</Text>
              <Tooltip title={t('skillManagement.mcpIntroBody')}><QuestionCircleOutlined tabIndex={0} aria-label={t('skillManagement.sectionDetails')} /></Tooltip>
            </Space>
          </div>
        )}
        right={(
          <>
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t('skillManagement.mcpAdd')}
            </Button>
            <Button size="small" icon={<CloudServerOutlined />} onClick={() => setRegistryOpen(true)}>{t('skillManagement.registry.browse')}</Button>
            <Dropdown menu={{ items: (['claude', 'codex', 'file', 'paste'] as const).map((source) => ({ key: source, label: t(`skillManagement.mcpImport.source_${source}`), onClick: () => setImportSource(source) })) }}>
              <Button size="small" icon={<ImportOutlined />}>{t('skillManagement.mcpImport.title')}</Button>
            </Dropdown>
            <Button
              size="small"
              icon={<SyncOutlined />}
              onClick={() => {
                onRefresh?.();
                vscode.postMessage({ type: 'syncMcpServers' });
              }}
            >
              {t('skillManagement.mcpSync')}
            </Button>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => {
                onRefresh?.();
                vscode.postMessage({ type: 'listMcpServers' });
              }}
            >
              {t('skillManagement.refresh')}
            </Button>
          </>
        )}
      />

      {presets.length > 0 ? (
        <PageSection
          palette={palette}
          icon={<CloudServerOutlined />}
          title={t('skillManagement.mcpRecommended')}
        >
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 260px), 1fr))', gap: SKILL_UI.space.md }}>
            {presets.map((preset) => (
              <ListCard
                key={preset.presetId}
                palette={palette}
                hoverable
                style={{ marginBottom: 0 }}
                onClick={() => {
                  onRefresh?.();
                  vscode.postMessage({ type: 'addMcpPreset', payload: { presetId: preset.presetId } });
                }}
              >
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Space size={8}>
                    <CloudServerOutlined style={{ color: palette.linkForeground }} />
                    <Text strong style={{ fontSize: 13 }}>{preset.name}</Text>
                    <Tag style={{ margin: 0 }}>{preset.transport}</Tag>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 11, lineHeight: 1.45 }}>
                    {t(preset.descriptionKey)}
                  </Text>
                </Space>
              </ListCard>
            ))}
          </div>
        </PageSection>
      ) : null}

      <Space wrap style={{ marginBottom: 16, width: '100%' }}>
        <Input.Search allowClear aria-label={t('skillManagement.mcpSearch')} placeholder={t('skillManagement.mcpSearch')} value={query} onChange={(event) => setQuery(event.target.value)} style={{ maxWidth: '100%', width: 300 }} />
        <Select aria-label={t('skillManagement.mcpTarget')} value={target} onChange={setTarget} style={{ minWidth: 150 }}
          options={['all', 'claude', 'codex', 'disabled'].map((value) => ({ value, label: t(`skillManagement.mcpFilter_${value}`) }))} />
      </Space>
      <PageSection
        palette={palette}
        title={t('skillManagement.mcpBuiltinSection')}
        help={t('skillManagement.mcpBuiltinSectionHint')}
      >
        {builtinServers.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t(servers.some((row) => row.builtin === 'literature') ? 'skillManagement.noSearchResults' : 'skillManagement.mcpBuiltinEmpty')}
            style={{ padding: '12px 0' }}
          >
            <Button size="small" onClick={() => vscode.postMessage({ type: 'openLiteratureMcpConfig' })}>
              {t('skillManagement.mcpEditInConfig')}
            </Button>
          </Empty>
        ) : (
          builtinServers.map(renderServerCard)
        )}
      </PageSection>

      <PageSection
        palette={palette}
        title={t('skillManagement.mcpCustomSection')}
        help={t('skillManagement.mcpCustomSectionHint')}
      >
        {loading && customServers.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center' }}>
            <Text type="secondary">{t('skillManagement.loading')}</Text>
          </div>
        ) : customServers.length === 0 ? (
          <Empty description={t(query || target !== 'all' ? 'skillManagement.noSearchResults' : 'skillManagement.mcpEmpty')} style={{ padding: '24px 0' }}>
            {query || target !== 'all' ? <Button onClick={clearFilters}>{t('skillManagement.clearFilters')}</Button> : null}
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t('skillManagement.mcpAdd')}
            </Button>
          </Empty>
        ) : (
          customServers.map(renderServerCard)
        )}
      </PageSection>

      <McpRegistryBrowser open={registryOpen} vscode={vscode} onCancel={() => setRegistryOpen(false)} onSelect={(record) => {
        setRegistryOpen(false); setEditing(undefined); setSaveError('');
        setDraft({ ...EMPTY_DRAFT, ...record, url: record.url ?? '', command: record.command ?? '', args: JSON.stringify(record.args ?? [], null, 2),
          envText: JSON.stringify(record.env ?? {}, null, 2), headersText: JSON.stringify(record.httpHeaders ?? {}, null, 2), bearerTokenEnvVar: record.bearerTokenEnvVar ?? '',
        });
        setEditorOpen(true);
      }} />
      <McpImportDialog source={importSource} vscode={vscode} onClose={() => setImportSource(null)} />
      <Modal
        title={t(editing ? 'skillManagement.mcpEdit' : 'skillManagement.mcpAdd')}
        open={editorOpen}
        onCancel={() => { if (!saving) { setEditorOpen(false); } }}
        onOk={saveDraft}
        okText={t('skillManagement.mcpSave')}
        cancelText={t('skillManagement.cancel')}
        confirmLoading={saving}
        cancelButtonProps={{ disabled: saving }}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {saveError ? <Alert type="error" showIcon title={saveError} /> : null}
          <div>
            <Text style={{ fontSize: 12 }}>{t('skillManagement.mcpName')}</Text>
            <Input aria-label={t('skillManagement.mcpName')} value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
          </div>
          <div>
            <Text style={{ fontSize: 12 }}>{t('skillManagement.mcpTransport')}</Text>
            <Select
              aria-label={t('skillManagement.mcpTransport')}
              style={{ width: '100%' }}
              value={draft.transport}
              onChange={(v) => setDraft((d) => ({ ...d, transport: v, enabledCodex: v === 'sse' ? false : d.enabledCodex }))}
              options={[
                { value: 'http', label: 'HTTP' },
                { value: 'stdio', label: 'stdio' },
                { value: 'sse', label: 'SSE (Claude Code)' },
              ]}
            />
          </div>
          {draft.transport !== 'stdio' ? (
            <div>
              <Text style={{ fontSize: 12 }}>URL</Text>
              <Input
                aria-label="URL" value={draft.url}
                placeholder={t('skillManagement.mcpUrlPlaceholder')}
                onChange={(e) => setDraft((d) => ({ ...d, url: e.target.value }))}
              />
            </div>
          ) : (
            <>
              <div>
                <Text style={{ fontSize: 12 }}>{t('skillManagement.mcpCommand')}</Text>
                <Input
                  aria-label={t('skillManagement.mcpCommand')}
                  value={draft.command}
                  placeholder={t('skillManagement.mcpCommandPlaceholder')}
                  onChange={(e) => setDraft((d) => ({ ...d, command: e.target.value }))}
                />
              </div>
              <div>
                <Text style={{ fontSize: 12 }}>{t('skillManagement.mcpArgs')}</Text>
                <Input.TextArea
                  aria-label={t('skillManagement.mcpArgs')} autoSize={{ minRows: 2, maxRows: 6 }} value={draft.args}
                  placeholder={t('skillManagement.mcpArgsPlaceholder')}
                  onChange={(e) => setDraft((d) => ({ ...d, args: e.target.value }))}
                />
              </div>
            </>
          )}
          <Collapse size="small" items={[{ key: 'advanced', label: t('skillManagement.mcpAdvanced'), children: <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {draft.transport === 'stdio' ? <><Text>{t('skillManagement.mcpEnv')}</Text><Input.TextArea aria-label={t('skillManagement.mcpEnv')} value={draft.envText} onChange={(event) => setDraft((d) => ({ ...d, envText: event.target.value }))} autoSize={{ minRows: 2, maxRows: 8 }} /></>
              : <><Text>{t('skillManagement.mcpHeaders')}</Text><Input.TextArea aria-label={t('skillManagement.mcpHeaders')} value={draft.headersText} onChange={(event) => setDraft((d) => ({ ...d, headersText: event.target.value }))} autoSize={{ minRows: 2, maxRows: 8 }} />
                <Text>{t('skillManagement.mcpBearerEnv')}</Text><Input aria-label={t('skillManagement.mcpBearerEnv')} value={draft.bearerTokenEnvVar} onChange={(event) => setDraft((d) => ({ ...d, bearerTokenEnvVar: event.target.value }))} /></>}
          </Space> }]} />
          <Space>
            <Checkbox
              checked={draft.enabledClaude}
              onChange={(e) => setDraft((d) => ({ ...d, enabledClaude: e.target.checked }))}
            >
              Claude Code
            </Checkbox>
            <Checkbox
              checked={draft.enabledCodex}
              disabled={draft.transport === 'sse'}
              onChange={(e) => setDraft((d) => ({ ...d, enabledCodex: e.target.checked }))}
            >
              Codex
            </Checkbox>
          </Space>
        </Space>
      </Modal>
    </div>
  );
}
