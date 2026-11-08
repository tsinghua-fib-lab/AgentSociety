import * as React from 'react';
import {
  Alert,
  Button,
  ConfigProvider,
  Empty,
  Input,
  Segmented,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  ApiOutlined,
  AppstoreOutlined,
  CheckCircleOutlined,
  ClearOutlined,
  CloseCircleOutlined,
  CodeOutlined,
  CopyOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  LoadingOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  SearchOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type {
  AvailableClasses,
  ClassItem,
  ClassKind,
  ListFilter,
  PrefillParams,
  TestStatus,
  VSCodeAPI,
} from './types';
import { MarkdownRenderer } from '../components/MarkdownRenderer';
import { useVscodeTheme } from '../theme';
import { PageSection, TabToolbar } from '../skillMarketplace/components';
import {
  SKILL_UI,
  heroShellStyle,
  iconBadgeStyle,
  sectionShellStyle,
  surfaceCardStyle,
} from '../skillMarketplace/uiTokens';
import 'antd/dist/reset.css';
import '../i18n';

const { Text, Title } = Typography;
const { TextArea } = Input;

interface PrefillParamsAppProps {
  vscode: VSCodeAPI;
}

function moduleKey(item: Pick<ClassItem, 'kind' | 'type'>): string {
  return `${item.kind}-${item.type}`;
}

function shortDescription(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  if (flat.length <= 80) {
    return flat;
  }
  return `${flat.slice(0, 80)}…`;
}

function buildInitSnippet(item: ClassItem, params: Record<string, unknown>): string {
  if (item.kind === 'env_module') {
    return JSON.stringify({ module_type: item.type, kwargs: params }, null, 2);
  }
  return JSON.stringify(
    {
      agent_id: 0,
      agent_type: item.type,
      kwargs: { id: 0, ...params },
    },
    null,
    2
  );
}

function parseParamsJson(
  raw: string
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { ok: true, value: {} };
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: 'object' };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, error: 'json' };
  }
}

function isBackendOfflineError(text: string): boolean {
  return /未连接|not connected|ECONNREFUSED|Failed to fetch|fetch failed|NetworkError|后端服务/i.test(
    text
  );
}

function statPill(
  label: string,
  value: number,
  palette: ReturnType<typeof useVscodeTheme>['palette'],
  accent?: string
): React.ReactNode {
  return (
    <div
      style={{
        ...surfaceCardStyle(palette),
        padding: '10px 12px',
        borderRadius: SKILL_UI.radius.sm,
        minWidth: 96,
      }}
    >
      <Text type="secondary" style={{ display: 'block', fontSize: 11, marginBottom: 2 }}>
        {label}
      </Text>
      <Text strong style={{ fontSize: 18, color: accent ?? palette.editorForeground, lineHeight: 1 }}>
        {value}
      </Text>
    </div>
  );
}

export const PrefillParamsApp: React.FC<PrefillParamsAppProps> = ({ vscode }) => {
  const { t } = useTranslation();
  const { isDark, palette, themeConfig } = useVscodeTheme();
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [backendOffline, setBackendOffline] = React.useState(false);
  const [startingBackend, setStartingBackend] = React.useState(false);
  const [classes, setClasses] = React.useState<ClassItem[]>([]);
  const [selectedKey, setSelectedKey] = React.useState<string | null>(null);
  const [searchText, setSearchText] = React.useState('');
  const [activeTab, setActiveTab] = React.useState<ClassKind>('env_module');
  const [listFilter, setListFilter] = React.useState<ListFilter>('all');
  const [testStatuses, setTestStatuses] = React.useState<Record<string, TestStatus>>({});
  const [testResults, setTestResults] = React.useState<Record<string, string>>({});
  const [editorText, setEditorText] = React.useState('{}');
  const [editorDirty, setEditorDirty] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [narrow, setNarrow] = React.useState(false);

  React.useEffect(() => {
    const mq = window.matchMedia('(max-width: 860px)');
    const apply = () => setNarrow(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  React.useEffect(() => {
    vscode.postMessage({ command: 'requestData' });
  }, [vscode]);

  React.useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const messageData = event.data as Record<string, unknown>;
      const command = messageData.command;

      if (command === 'initialData') {
        try {
          const classesData = messageData.classes as AvailableClasses;
          const prefillParams = messageData.prefillParams as PrefillParams;
          const classItems: ClassItem[] = [];

          Object.entries(classesData.env_modules || {}).forEach(([type, info]) => {
            classItems.push({
              type,
              kind: 'env_module',
              info,
              params: (prefillParams.env_modules?.[type] || {}) as Record<string, unknown>,
            });
          });
          Object.entries(classesData.agents || {}).forEach(([type, info]) => {
            classItems.push({
              type,
              kind: 'agent',
              info,
              params: (prefillParams.agents?.[type] || {}) as Record<string, unknown>,
            });
          });

          setClasses(classItems);
          setLoading(false);
          setError(null);
          setBackendOffline(false);
          setEditorDirty(false);
        } catch (err) {
          console.error(err);
          setError(t('prefillParams.errorMessages.loadFailed'));
          setBackendOffline(false);
          setLoading(false);
          setClasses([]);
          setSelectedKey(null);
        }
        return;
      }

      if (command === 'error') {
        const errText = (messageData.error as string) || t('prefillParams.errorMessages.loadFailed');
        setError(errText);
        setBackendOffline(
          Boolean(messageData.backendOffline) || isBackendOfflineError(errText)
        );
        setLoading(false);
        setClasses([]);
        setSelectedKey(null);
        return;
      }

      if (command === 'startBackendResult') {
        setStartingBackend(false);
        if (messageData.success) {
          message.success(t('prefillParams.backend.started'));
          setLoading(true);
          setError(null);
          vscode.postMessage({ command: 'refresh' });
        } else {
          message.error(
            (messageData.error as string) || t('prefillParams.backend.startFailed')
          );
        }
        return;
      }

      if (command === 'testResult') {
        const key = messageData.moduleKey as string;
        if (!key) {
          return;
        }
        setTestStatuses((prev) => ({
          ...prev,
          [key]: messageData.success ? 'success' : 'error',
        }));
        setTestResults((prev) => ({
          ...prev,
          [key]:
            (messageData.output as string) ||
            (messageData.error as string) ||
            '',
        }));
        return;
      }

      if (command === 'saveResult') {
        setSaving(false);
        if (messageData.success) {
          message.success(t('prefillParams.save.success'));
          setEditorDirty(false);
          const kind = messageData.kind as ClassKind;
          const type = messageData.type as string;
          const params = (messageData.params || {}) as Record<string, unknown>;
          setClasses((prev) =>
            prev.map((item) => {
              if (item.kind !== kind || item.type !== type) {
                return item;
              }
              return {
                ...item,
                params,
                info: {
                  ...item.info,
                  has_prefill: Object.keys(params).length > 0,
                },
              };
            })
          );
        } else {
          message.error((messageData.error as string) || t('prefillParams.save.failed'));
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [vscode, t]);

  const filteredClasses = React.useMemo(() => {
    const lower = searchText.trim().toLowerCase();
    return classes.filter((item) => {
      if (item.kind !== activeTab) {
        return false;
      }
      if (listFilter === 'prefill' && !item.info.has_prefill && Object.keys(item.params).length === 0) {
        return false;
      }
      if (listFilter === 'custom' && !item.info.is_custom) {
        return false;
      }
      if (!lower) {
        return true;
      }
      return (
        item.type.toLowerCase().includes(lower) ||
        item.info.class_name.toLowerCase().includes(lower) ||
        item.info.description.toLowerCase().includes(lower)
      );
    });
  }, [classes, activeTab, listFilter, searchText]);

  React.useEffect(() => {
    if (filteredClasses.length === 0) {
      setSelectedKey(null);
      return;
    }
    if (!selectedKey || !filteredClasses.some((item) => moduleKey(item) === selectedKey)) {
      setSelectedKey(moduleKey(filteredClasses[0]));
    }
  }, [filteredClasses, selectedKey]);

  const selectedClass = React.useMemo(
    () => filteredClasses.find((item) => moduleKey(item) === selectedKey) ?? null,
    [filteredClasses, selectedKey]
  );

  React.useEffect(() => {
    if (!selectedClass) {
      setEditorText('{}');
      setEditorDirty(false);
      return;
    }
    setEditorText(JSON.stringify(selectedClass.params ?? {}, null, 2));
    setEditorDirty(false);
  }, [selectedClass?.kind, selectedClass?.type]);

  const handleRefresh = () => {
    setLoading(true);
    setError(null);
    setBackendOffline(false);
    setClasses([]);
    setSelectedKey(null);
    vscode.postMessage({ command: 'refresh' });
  };

  const handleStartBackend = () => {
    setStartingBackend(true);
    vscode.postMessage({ command: 'startBackend' });
  };

  const handleOpenConfigPage = () => {
    vscode.postMessage({ command: 'openConfigPage' });
  };

  const handleSelect = (item: ClassItem) => {
    if (editorDirty && !window.confirm(t('prefillParams.unsavedConfirm'))) {
      return;
    }
    setSelectedKey(moduleKey(item));
  };

  const handleSave = () => {
    if (!selectedClass) {
      return;
    }
    const parsed = parseParamsJson(editorText);
    if (!parsed.ok) {
      message.error(t('prefillParams.save.invalidJson'));
      return;
    }
    setSaving(true);
    vscode.postMessage({
      command: 'saveClassPrefill',
      kind: selectedClass.kind,
      type: selectedClass.type,
      params: parsed.value,
    });
  };

  const handleClear = () => {
    if (!selectedClass) {
      return;
    }
    setEditorText('{}');
    setEditorDirty(true);
    setSaving(true);
    vscode.postMessage({
      command: 'saveClassPrefill',
      kind: selectedClass.kind,
      type: selectedClass.type,
      params: {},
    });
  };

  const handleCopySnippet = async () => {
    if (!selectedClass) {
      return;
    }
    const parsed = parseParamsJson(editorText);
    if (!parsed.ok) {
      message.error(t('prefillParams.save.invalidJson'));
      return;
    }
    const snippet = buildInitSnippet(selectedClass, parsed.value);
    try {
      await navigator.clipboard.writeText(snippet);
      message.success(t('prefillParams.copy.success'));
    } catch {
      vscode.postMessage({ command: 'copyText', text: snippet });
      message.success(t('prefillParams.copy.success'));
    }
  };

  const handleTest = () => {
    if (!selectedClass?.info.is_custom) {
      return;
    }
    const key = moduleKey(selectedClass);
    setTestStatuses((prev) => ({ ...prev, [key]: 'testing' }));
    setTestResults((prev) => ({ ...prev, [key]: '' }));
    vscode.postMessage({
      command: 'testCustomModule',
      moduleKey: key,
      moduleType: selectedClass.kind,
      moduleTypeValue: selectedClass.type,
      moduleClassName: selectedClass.info.class_name,
    });
  };

  const handleOpenSource = () => {
    if (!selectedClass?.info.is_custom) {
      return;
    }
    vscode.postMessage({
      command: 'openCustomModuleSource',
      kind: selectedClass.kind,
      className: selectedClass.info.class_name,
    });
  };

  const envCount = classes.filter((c) => c.kind === 'env_module').length;
  const agentCount = classes.filter((c) => c.kind === 'agent').length;
  const prefillCount = classes.filter(
    (c) => c.info.has_prefill || Object.keys(c.params).length > 0
  ).length;
  const customCount = classes.filter((c) => c.info.is_custom).length;
  const prefillInTab = classes.filter(
    (c) =>
      c.kind === activeTab &&
      (c.info.has_prefill || Object.keys(c.params).length > 0)
  ).length;
  const customInTab = classes.filter((c) => c.kind === activeTab && c.info.is_custom).length;

  const selectedTestKey = selectedClass ? moduleKey(selectedClass) : '';
  const selectedTestStatus = selectedTestKey ? testStatuses[selectedTestKey] || 'idle' : 'idle';
  const selectedTestResult = selectedTestKey ? testResults[selectedTestKey] || '' : '';

  const shell = (
    children: React.ReactNode,
    opts?: { mode?: 'page' | 'split' }
  ) => {
    const mode = opts?.mode ?? 'page';
    return (
      <ConfigProvider theme={themeConfig}>
        <div
          style={{
            height: '100vh',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            background: palette.editorBackground,
          }}
        >
          <div
            className="as-page-content"
            style={{
              flex: 1,
              minHeight: 0,
              overflowY: mode === 'page' ? 'auto' : 'hidden',
              overflowX: 'hidden',
              padding: `${SKILL_UI.space.lg}px ${SKILL_UI.space.md}px ${SKILL_UI.space.xl}px`,
              display: mode === 'split' ? 'flex' : undefined,
              flexDirection: mode === 'split' ? 'column' : undefined,
            }}
          >
            <div
              style={{
                maxWidth: SKILL_UI.maxWidth,
                margin: '0 auto',
                width: '100%',
                ...(mode === 'split'
                  ? {
                      flex: 1,
                      minHeight: 0,
                      display: 'flex',
                      flexDirection: 'column',
                    }
                  : null),
              }}
            >
              {children}
            </div>
          </div>
        </div>
      </ConfigProvider>
    );
  };

  if (loading) {
    return shell(
      <div style={{ ...heroShellStyle(palette), textAlign: 'center', padding: '48px 24px' }}>
        <Spin size="large" />
        <div style={{ marginTop: 12 }}>
          <Text type="secondary">{t('prefillParams.loading')}</Text>
        </div>
      </div>
    );
  }

  if (error) {
    return shell(
      <div style={heroShellStyle(palette)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: SKILL_UI.space.lg }}>
          <span style={iconBadgeStyle(backendOffline ? palette.warningForeground : palette.errorForeground)}>
            <ApiOutlined style={{ fontSize: 18 }} />
          </span>
          <div>
            <Title level={4} style={{ margin: 0 }}>
              {backendOffline
                ? t('prefillParams.backend.offlineTitle')
                : t('prefillParams.error')}
            </Title>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {backendOffline ? t('prefillParams.backend.offlineBody') : error}
            </Text>
          </div>
        </div>
        {!backendOffline ? (
          <Alert type="error" showIcon message={error} style={{ marginBottom: SKILL_UI.space.md }} />
        ) : null}
        <Space wrap>
          {backendOffline ? (
            <>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={startingBackend}
                onClick={handleStartBackend}
              >
                {t('prefillParams.backend.start')}
              </Button>
              <Button icon={<SettingOutlined />} onClick={handleOpenConfigPage}>
                {t('prefillParams.backend.openConfig')}
              </Button>
            </>
          ) : null}
          <Button icon={<ReloadOutlined />} onClick={handleRefresh} disabled={startingBackend}>
            {t('prefillParams.refresh')}
          </Button>
        </Space>
      </div>
    );
  }

  return shell(
    <>
      <div style={{ flexShrink: 0 }}>
        <div style={heroShellStyle(palette)}>
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              marginBottom: SKILL_UI.space.lg,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
              <span style={iconBadgeStyle(palette.linkForeground)}>
                <DatabaseOutlined style={{ fontSize: 18 }} />
              </span>
              <div style={{ minWidth: 0 }}>
                <Title level={4} style={{ margin: 0 }}>{t('prefillParams.groupTitle')}</Title>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('prefillParams.introHintBody')}
                </Text>
              </div>
            </div>
            <Space wrap size={8}>
              <Button
                size="small"
                icon={<FileTextOutlined />}
                onClick={() => vscode.postMessage({ command: 'openPrefillParamsJson' })}
              >
                {t('prefillParams.openConfigFile')}
              </Button>
              <Button size="small" icon={<ReloadOutlined />} onClick={handleRefresh}>
                {t('prefillParams.refresh')}
              </Button>
            </Space>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: SKILL_UI.space.md }}>
            {statPill(t('prefillParams.classInfo.envModule'), envCount, palette, palette.linkForeground)}
            {statPill(t('prefillParams.classInfo.agent'), agentCount, palette, palette.successForeground)}
            {statPill(t('prefillParams.filter.prefill'), prefillCount, palette)}
            {statPill(t('prefillParams.classInfo.custom'), customCount, palette)}
          </div>
        </div>

        <TabToolbar
          left={
            <Space wrap size={SKILL_UI.space.sm}>
              <Segmented
                value={activeTab}
                onChange={(value) => {
                  if (editorDirty && !window.confirm(t('prefillParams.unsavedConfirm'))) {
                    return;
                  }
                  setActiveTab(value as ClassKind);
                  setSelectedKey(null);
                }}
                options={[
                  {
                    value: 'env_module',
                    label: (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                        <AppstoreOutlined />
                        {t('prefillParams.classInfo.envModule')}
                      </span>
                    ),
                  },
                  {
                    value: 'agent',
                    label: (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                        <TeamOutlined />
                        {t('prefillParams.classInfo.agent')}
                      </span>
                    ),
                  },
                ]}
              />
              <Segmented
                value={listFilter}
                onChange={(value) => setListFilter(value as ListFilter)}
                options={[
                  { value: 'all', label: t('prefillParams.filter.all') },
                  { value: 'prefill', label: `${t('prefillParams.filter.prefill')} (${prefillInTab})` },
                  { value: 'custom', label: `${t('prefillParams.filter.custom')} (${customInTab})` },
                ]}
              />
            </Space>
          }
          right={
            <Input
              allowClear
              prefix={<SearchOutlined style={{ color: palette.descriptionForeground }} />}
              placeholder={t('prefillParams.searchPlaceholder')}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              style={{ width: narrow ? '100%' : 240 }}
            />
          }
        />
      </div>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: narrow ? '1fr' : 'minmax(260px, 320px) minmax(0, 1fr)',
          gridTemplateRows: narrow ? 'minmax(180px, 34%) minmax(0, 1fr)' : 'minmax(0, 1fr)',
          gap: SKILL_UI.space.lg,
          overflow: 'hidden',
        }}
      >
        <div style={{ minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <PageSection
            palette={palette}
            icon={<AppstoreOutlined />}
            title={
              activeTab === 'env_module'
                ? t('prefillParams.classInfo.envModule')
                : t('prefillParams.classInfo.agent')
            }
            subtitle={t('prefillParams.catalogHint')}
            style={{
              marginBottom: 0,
              flex: 1,
              minHeight: 0,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', paddingRight: 2 }}>
              {filteredClasses.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('prefillParams.noClasses')} />
              ) : (
                filteredClasses.map((item) => {
                  const key = moduleKey(item);
                  const selected = selectedKey === key;
                  const hasPrefill =
                    item.info.has_prefill || Object.keys(item.params).length > 0;
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => handleSelect(item)}
                      style={{
                        ...surfaceCardStyle(palette, {
                          accent: selected ? palette.linkForeground : undefined,
                        }),
                        display: 'block',
                        width: '100%',
                        textAlign: 'left',
                        cursor: 'pointer',
                        marginBottom: SKILL_UI.space.sm,
                        padding: '12px 14px',
                        background: selected
                          ? palette.activeSelectionBackground
                          : palette.surfaceMuted,
                        borderColor: selected ? palette.focusBorder : palette.panelBorder,
                        color: palette.editorForeground,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                        <Text strong style={{ fontSize: 13, flex: 1, minWidth: 0 }} ellipsis>
                          {item.type}
                        </Text>
                        {hasPrefill ? (
                          <Tag color="success" style={{ margin: 0 }}>
                            {t('prefillParams.filter.prefill')}
                          </Tag>
                        ) : null}
                        {item.info.is_custom ? (
                          <Tag color="blue" style={{ margin: 0 }}>
                            {t('prefillParams.classInfo.custom')}
                          </Tag>
                        ) : null}
                      </div>
                      <Text type="secondary" style={{ fontSize: 12, lineHeight: 1.45 }}>
                        {shortDescription(item.info.description || item.info.class_name)}
                      </Text>
                    </button>
                  );
                })
              )}
            </div>
          </PageSection>
        </div>

        <div
          style={{
            minHeight: 0,
            overflowY: 'auto',
            overflowX: 'hidden',
            paddingBottom: SKILL_UI.space.md,
          }}
        >
          {!selectedClass ? (
            <div style={{ ...sectionShellStyle(palette), marginBottom: 0 }}>
              <Empty description={t('prefillParams.selectClass')} style={{ margin: '40px 0' }} />
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: SKILL_UI.space.lg }}>
              <PageSection
                palette={palette}
                icon={<CodeOutlined />}
                title={selectedClass.type}
                subtitle={selectedClass.info.class_name}
                extra={
                  <Space wrap size="small">
                    <Tag>
                      {selectedClass.info.is_custom
                        ? t('prefillParams.classInfo.custom')
                        : t('prefillParams.classInfo.builtin')}
                    </Tag>
                    {(selectedClass.info.has_prefill ||
                      Object.keys(selectedClass.params).length > 0) && (
                      <Tag color="success">{t('prefillParams.classInfo.hasPrefill')}</Tag>
                    )}
                    {editorDirty ? <Tag color="warning">{t('prefillParams.dirty')}</Tag> : null}
                    <Tooltip title={t('prefillParams.copy.hint')}>
                      <Button size="small" icon={<CopyOutlined />} onClick={() => void handleCopySnippet()}>
                        {t('prefillParams.copy.button')}
                      </Button>
                    </Tooltip>
                    {selectedClass.info.is_custom ? (
                      <>
                        <Button size="small" icon={<FolderOpenOutlined />} onClick={handleOpenSource}>
                          {t('prefillParams.openSource')}
                        </Button>
                        <Button
                          size="small"
                          icon={
                            selectedTestStatus === 'testing' ? (
                              <LoadingOutlined />
                            ) : selectedTestStatus === 'success' ? (
                              <CheckCircleOutlined />
                            ) : selectedTestStatus === 'error' ? (
                              <CloseCircleOutlined />
                            ) : (
                              <PlayCircleOutlined />
                            )
                          }
                          loading={selectedTestStatus === 'testing'}
                          onClick={handleTest}
                        >
                          {t('prefillParams.classInfo.test')}
                        </Button>
                      </>
                    ) : null}
                  </Space>
                }
                style={{ marginBottom: 0 }}
              >
                <Text strong style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
                  {t('prefillParams.classInfo.description')}
                </Text>
                <div
                  style={{
                    ...surfaceCardStyle(palette, { muted: true }),
                    padding: 12,
                  }}
                >
                  <MarkdownRenderer
                    content={
                      selectedClass.info.init_description?.trim() ||
                      selectedClass.info.description ||
                      ''
                    }
                    isDark={isDark}
                  />
                </div>
              </PageSection>

              <PageSection
                palette={palette}
                icon={<SaveOutlined />}
                title={t('prefillParams.classInfo.prefillParams')}
                subtitle={t('prefillParams.editorHint')}
                extra={
                  <Space size="small" wrap>
                    <Button size="small" icon={<ClearOutlined />} onClick={handleClear} disabled={saving}>
                      {t('prefillParams.clear')}
                    </Button>
                    <Button
                      type="primary"
                      size="small"
                      icon={<SaveOutlined />}
                      loading={saving}
                      disabled={!editorDirty}
                      onClick={handleSave}
                    >
                      {t('prefillParams.save.button')}
                    </Button>
                  </Space>
                }
                style={{ marginBottom: 0 }}
              >
                <TextArea
                  value={editorText}
                  onChange={(e) => {
                    setEditorText(e.target.value);
                    setEditorDirty(true);
                  }}
                  autoSize={{ minRows: 8, maxRows: 20 }}
                  spellCheck={false}
                  style={{
                    fontFamily:
                      'var(--vscode-editor-font-family, ui-monospace, SFMono-Regular, Menlo, monospace)',
                    fontSize: 12,
                    lineHeight: 1.5,
                    background: palette.inputBackground,
                    color: palette.inputForeground,
                    borderColor: palette.inputBorder,
                  }}
                />
              </PageSection>

              <PageSection
                palette={palette}
                icon={<CodeOutlined />}
                title={t('prefillParams.snippet.title')}
                subtitle={t('prefillParams.snippet.hint')}
                style={{ marginBottom: 0 }}
              >
                <pre
                  style={{
                    margin: 0,
                    padding: 12,
                    borderRadius: SKILL_UI.radius.sm,
                    background: palette.codeBlockBackground,
                    border: `1px solid ${palette.panelBorder}`,
                    fontSize: 11,
                    lineHeight: 1.45,
                    overflow: 'auto',
                    maxHeight: 200,
                  }}
                >
                  {(() => {
                    const parsed = parseParamsJson(editorText);
                    return buildInitSnippet(
                      selectedClass,
                      parsed.ok ? parsed.value : selectedClass.params
                    );
                  })()}
                </pre>
              </PageSection>

              {selectedClass.info.is_custom &&
              selectedTestStatus !== 'idle' &&
              selectedTestResult ? (
                <Alert
                  type={selectedTestStatus === 'success' ? 'success' : 'error'}
                  showIcon
                  message={
                    selectedTestStatus === 'success'
                      ? t('prefillParams.test.success')
                      : t('prefillParams.test.failed')
                  }
                  description={
                    <Text style={{ fontSize: 11, whiteSpace: 'pre-wrap' }}>{selectedTestResult}</Text>
                  }
                />
              ) : null}
            </div>
          )}
        </div>
      </div>
    </>,
    { mode: 'split' }
  );

};
