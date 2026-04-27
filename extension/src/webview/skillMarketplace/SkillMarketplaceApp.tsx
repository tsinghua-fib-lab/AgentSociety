import * as React from 'react';
import {
  ConfigProvider, Layout, Input, Button, Card, Typography, Tag, Space, Spin, Empty,
  message, Modal, Tooltip, Tabs, Switch, Collapse, Divider, Alert, Pagination,
} from 'antd';
import {
  SearchOutlined, DownloadOutlined, DeleteOutlined, FolderOpenOutlined,
  ReloadOutlined, CheckCircleOutlined, AppstoreOutlined, BookOutlined,
  ToolOutlined, RobotOutlined, ThunderboltOutlined, ShopOutlined,
  SyncOutlined, ImportOutlined, InboxOutlined, CloudSyncOutlined, SettingOutlined,
  UndoOutlined, QuestionCircleOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type {
  VSCodeAPI, MarketplaceSkill, AgentSkill, ClaudeCodeSkill, BuiltinSkill, AgentSkillDetailPayload,
  MarketplaceLoadError, MarketplaceChannelsPayload, SkillSourceConfig,
} from './types';
import { DEFAULT_CLAUDE_SOURCES, DEFAULT_AGENT_SOURCES } from './types';
import { useVscodeTheme } from '../theme';
import 'antd/dist/reset.css';
import { SkillDetailCollapse } from './components';

const { Content } = Layout;
const { Title, Text } = Typography;
const { Search } = Input;
const { Panel } = Collapse;

const MARKETPLACE_PAGE_SIZE = 10;

interface SkillManagementAppProps { vscode: VSCodeAPI; }
type SkillTab = 'agent' | 'claudeCode';

export const SkillMarketplaceApp: React.FC<SkillManagementAppProps> = ({ vscode }) => {
  const { t, i18n } = useTranslation();
  const { palette, themeConfig } = useVscodeTheme();
  const [activeTab, setActiveTab] = React.useState<SkillTab>('agent');
  const [agentSkills, setAgentSkills] = React.useState<AgentSkill[]>([]);
  const [agentSkillsLoading, setAgentSkillsLoading] = React.useState(false);
  const [claudeCodeSkills, setClaudeCodeSkills] = React.useState<ClaudeCodeSkill[]>([]);
  const [claudeCodeSkillsLoading, setClaudeCodeSkillsLoading] = React.useState(false);
  const [builtinSkills, setBuiltinSkills] = React.useState<BuiltinSkill[]>([]);
  const [builtinSkillsLoading, setBuiltinSkillsLoading] = React.useState(false);
  const [agentMarketplaceSkills, setAgentMarketplaceSkills] = React.useState<MarketplaceSkill[]>([]);
  const [claudeMarketplaceSkills, setClaudeMarketplaceSkills] = React.useState<MarketplaceSkill[]>([]);
  const [marketplaceLoading, setMarketplaceLoading] = React.useState(false);
  const [agentMarketplaceLoadErrors, setAgentMarketplaceLoadErrors] = React.useState<MarketplaceLoadError[]>([]);
  const [claudeMarketplaceLoadErrors, setClaudeMarketplaceLoadErrors] = React.useState<MarketplaceLoadError[]>([]);
  const [agentMarketPage, setAgentMarketPage] = React.useState(1);
  const [claudeMarketPage, setClaudeMarketPage] = React.useState(1);
  const [searchQuery, setSearchQuery] = React.useState('');
  const [installingSkills, setInstallingSkills] = React.useState<Set<string>>(new Set());
  const [agentSkillDetails, setAgentSkillDetails] = React.useState<Record<string, AgentSkillDetailPayload>>({});
  const [agentDetailLoading, setAgentDetailLoading] = React.useState<Record<string, boolean>>({});
  const [localMdByPath, setLocalMdByPath] = React.useState<Record<string, string | null>>({});
  const [localMdLoading, setLocalMdLoading] = React.useState<Record<string, boolean>>({});
  const [vsixSyncLoading, setVsixSyncLoading] = React.useState<Set<string>>(new Set());
  // 市场源配置状态
  const [showAdvancedSettings, setShowAdvancedSettings] = React.useState(false);
  const [agentSkillSources, setAgentSkillSources] = React.useState<Array<{
    owner: string;
    repo: string;
    branch?: string;
    skillsPath?: string;
    platform?: string;
    baseUrl?: string;
  }>>([]);
  const [claudeSkillSources, setClaudeSkillSources] = React.useState<Array<{
    owner: string;
    repo: string;
    branch?: string;
    skillsPath?: string;
    platform?: string;
    baseUrl?: string;
  }>>([]);
  const [skillSourcesLoading, setSkillSourcesLoading] = React.useState(false);
  const [updateDiffModal, setUpdateDiffModal] = React.useState<{
    open: boolean;
    skill?: MarketplaceSkill;
    diff?: {
      skillId: string;
      skillName: string;
      localVersion: string;
      remoteVersion: string;
      filesAdded: string[];
      filesDeleted: string[];
      filesModified: string[];
      fileDiffs: Array<{
        path: string;
        status: 'added' | 'deleted' | 'modified';
        hunks: Array<{
          oldStart: number;
          oldLines: number;
          newStart: number;
          newLines: number;
          lines: string[];
        }>;
      }>;
    };
  }>({ open: false });
  const [updateDiffLoadingById, setUpdateDiffLoadingById] = React.useState<Record<string, boolean>>({});
  const pendingUpdateSkillRef = React.useRef<Record<string, MarketplaceSkill>>({});
  // 帮助弹窗状态
  const [helpModalOpen, setHelpModalOpen] = React.useState(false);
  // 高级设置弹窗状态
  const [sourcesModalTarget, setSourcesModalTarget] = React.useState<'agent' | 'claudeCode' | null>(null);
  // GitHub Token 状态
  const [githubToken, setGithubToken] = React.useState('');

  React.useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const msg = event.data;
      if (!msg || !msg.type) return;
      switch (msg.type) {
        case 'agentSkillsLoaded':
          setAgentSkills(msg.payload || []);
          setAgentSkillsLoading(false);
          break;
        case 'agentSkillEnabled':
        case 'agentSkillDisabled':
        case 'agentSkillReloaded':
          message.success(msg.payload?.message || t('skillManagement.operationSuccess'));
          break;
        case 'agentSkillImported':
          message.success(t('skillManagement.importSuccess'));
          vscode.postMessage({ type: 'listAgentSkills' });
          break;
        case 'agentSkillRemoved':
          message.success(msg.payload?.message || t('skillManagement.removeAgentSuccess'));
          break;
        case 'claudeCodeSkillImported':
          message.success(t('skillManagement.importClaudeSuccess'));
          break;
        case 'claudeCodeSkillsLoaded':
          setClaudeCodeSkills(msg.payload || []);
          setClaudeCodeSkillsLoading(false);
          setVsixSyncLoading(new Set());
          break;
        case 'claudeCodeSkillDeleted':
          message.success(t('skillManagement.deleteSuccess'));
          break;
        case 'builtinSkillsLoaded':
          setBuiltinSkills(msg.payload || []);
          setBuiltinSkillsLoading(false);
          break;
        case 'agentSkillDetailLoaded': {
          const p = msg.payload as AgentSkillDetailPayload;
          setAgentDetailLoading((l) => {
            const n = { ...l };
            delete n[p.name];
            return n;
          });
          setAgentSkillDetails((d) => ({ ...d, [p.name]: p }));
          break;
        }
        case 'localSkillMarkdownLoaded': {
          const p = msg.payload as { path: string; content: string };
          setLocalMdLoading((l) => {
            const n = { ...l };
            delete n[p.path];
            return n;
          });
          setLocalMdByPath((d) => ({ ...d, [p.path]: p.content }));
          break;
        }
        case 'skillDetailError': {
          const p = msg.payload as { key: string; error: string };
          const { key } = p;
          if (key.startsWith('agent:')) {
            const name = key.slice('agent:'.length);
            setAgentDetailLoading((l) => {
              const n = { ...l };
              delete n[name];
              return n;
            });
          } else if (key.startsWith('path:')) {
            const dirPath = key.slice('path:'.length);
            setLocalMdLoading((l) => {
              const n = { ...l };
              delete n[dirPath];
              return n;
            });
          }
          message.error(p.error || t('skillManagement.detailLoadFailed'));
          break;
        }
        case 'marketplaceSkillsLoaded': {
          const p = msg.payload as MarketplaceChannelsPayload;
          setAgentMarketplaceSkills(p.agent?.skills ?? []);
          setAgentMarketplaceLoadErrors(p.agent?.errors ?? []);
          setClaudeMarketplaceSkills(p.claude?.skills ?? []);
          setClaudeMarketplaceLoadErrors(p.claude?.errors ?? []);
          setMarketplaceLoading(false);
          break;
        }
        case 'installProgress':
          if (msg.payload?.status === 'downloading' || msg.payload?.status === 'installing') {
            setInstallingSkills(prev => new Set(prev).add(msg.payload.skillId));
          }
          break;
        case 'installComplete':
          setInstallingSkills(prev => { const next = new Set(prev); next.delete(msg.payload.skillId); return next; });
          message.success(t('skillManagement.installSuccess', { name: msg.payload.name }));
          if (msg.payload.skillType === 'agent') {
            vscode.postMessage({ type: 'listAgentSkills' });
          } else {
            vscode.postMessage({ type: 'listClaudeCodeSkills' });
          }
          break;
        case 'installFailed':
          setInstallingSkills(prev => { const next = new Set(prev); next.delete(msg.payload.skillId); return next; });
          message.error(t('skillManagement.installFailed', { error: msg.payload.error }));
          break;
        case 'error':
          message.error(msg.payload || t('skillManagement.error'));
          setAgentSkillsLoading(false);
          setClaudeCodeSkillsLoading(false);
          setBuiltinSkillsLoading(false);
          setMarketplaceLoading(false);
          setVsixSyncLoading(new Set());
          break;
        case 'skillSourcesLoaded': {
          const payload = msg.payload as {
            target: 'agent' | 'claudeCode';
            sources: Array<{
              owner: string;
              repo: string;
              branch?: string;
              skillsPath?: string;
              platform?: string;
              baseUrl?: string;
            }>;
          };
          if (payload.target === 'agent') {
            setAgentSkillSources(payload.sources);
          } else {
            setClaudeSkillSources(payload.sources);
          }
          setSkillSourcesLoading(false);
          break;
        }
        case 'skillSourcesSaved': {
          const payload = msg.payload as {
            target: 'agent' | 'claudeCode';
            sources: Array<{
              owner: string;
              repo: string;
              branch?: string;
              skillsPath?: string;
              platform?: string;
              baseUrl?: string;
            }>;
          };
          if (payload.target === 'agent') {
            setAgentSkillSources(payload.sources);
          } else {
            setClaudeSkillSources(payload.sources);
          }
          setSkillSourcesLoading(false);
          message.success(t('skillManagement.sourcesSaved'));
          break;
        }
        case 'skillSourcesError': {
          const payload = msg.payload as { target: string; error: string };
          setSkillSourcesLoading(false);
          message.error(payload.error || t('skillManagement.sourcesSaveFailed'));
          break;
        }
        case 'githubTokenLoaded': {
          const payload = msg.payload as { token: string };
          setGithubToken(payload.token || '');
          break;
        }
        case 'githubTokenSaved': {
          message.success(t('skillManagement.tokenSaved'));
          break;
        }
        case 'skillUpdateDiffLoaded': {
          const p = msg.payload as any;
          const skillId = String(p?.skillId || '');
          if (skillId) {
            setUpdateDiffLoadingById((m) => {
              const n = { ...m };
              delete n[skillId];
              return n;
            });
          }
          // 用 ref 记录的 skill，避免 effect 闭包拿到旧 state
          const skill = pendingUpdateSkillRef.current[skillId];
          setUpdateDiffModal({ open: true, skill, diff: p });
          break;
        }
        case 'skillUpdateDiffError': {
          const p = msg.payload as { error: string; skillId?: string };
          const skillId = String(p?.skillId || '');
          if (skillId) {
            setUpdateDiffLoadingById((m) => {
              const n = { ...m };
              delete n[skillId];
              return n;
            });
          }
          message.error(p?.error || t('skillManagement.detailLoadFailed'));
          break;
        }
      }
    };
    window.addEventListener('message', handleMessage);
    setMarketplaceLoading(true);
    vscode.postMessage({ type: 'ready' });
    vscode.postMessage({ type: 'listAgentSkills' });
    vscode.postMessage({ type: 'listClaudeCodeSkills' });
    vscode.postMessage({ type: 'listBuiltinSkills' });
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  // Agent Skills 操作
  const handleToggleAgentSkill = (skill: AgentSkill) => {
    vscode.postMessage({ type: skill.enabled ? 'disableAgentSkill' : 'enableAgentSkill', payload: { name: skill.name } });
  };
  const handleReloadAgentSkill = (name: string) => vscode.postMessage({ type: 'reloadAgentSkill', payload: { name } });
  const handleRemoveAgentSkill = (name: string) => {
    Modal.confirm({
      title: t('skillManagement.archiveAgentConfirmTitle'),
      content: t('skillManagement.archiveAgentConfirmContent', { name }),
      okType: 'danger',
      onOk: () => vscode.postMessage({ type: 'removeAgentSkill', payload: { name } }),
    });
  };
  const handleImportAgentSkill = () => vscode.postMessage({ type: 'importAgentSkill' });
  const handleImportClaudeCodeSkill = () => vscode.postMessage({ type: 'importClaudeCodeSkill' });
  const handleScanAgentSkills = () => vscode.postMessage({ type: 'scanAgentSkills' });
  const handleRefreshAgentList = () => {
    setAgentSkillsLoading(true);
    vscode.postMessage({ type: 'listAgentSkills' });
  };
  const handleRefreshClaudeList = () => {
    setClaudeCodeSkillsLoading(true);
    vscode.postMessage({ type: 'listClaudeCodeSkills' });
  };
  const handleUpdateExtensionSkills = () => vscode.postMessage({ type: 'updateExtensionSkills' });

  const handleSyncOneBundledClaudeSkill = (name: string) => {
    setVsixSyncLoading((prev) => new Set(prev).add(name));
    vscode.postMessage({ type: 'syncOneClaudeSkillFromVsix', payload: { name } });
  };

  const handleOpenAgentSkillDoc = (skill: AgentSkill) => {
    vscode.postMessage({
      type: 'openAgentSkillDoc',
      payload: { skillName: skill.name, skillPath: skill.path, isBuiltin: skill.source === 'builtin' }
    });
  };
  const handleOpenLocalSkillMarkdown = (skillDir: string) => {
    vscode.postMessage({ type: 'openLocalSkillMarkdown', payload: { skillDir } });
  };

  const handleSetClaudeSkillActive = (name: string, origin: 'workspace' | 'global', active: boolean) => {
    vscode.postMessage({ type: 'setClaudeSkillActive', payload: { name, origin, active } });
  };

  const handlePurgeClaudeCodeSkill = (name: string, origin: 'workspace' | 'global') => {
    Modal.confirm({
      title: t('skillManagement.purgeClaudeConfirmTitle'),
      content: t('skillManagement.purgeClaudeConfirmContent', { name }),
      okType: 'danger',
      onOk: () => vscode.postMessage({ type: 'purgeClaudeCodeSkill', payload: { name, origin } }),
    });
  };

  // 市场源配置操作
  const handleGetSkillSources = (target: 'agent' | 'claudeCode') => {
    setSkillSourcesLoading(true);
    vscode.postMessage({ type: 'getSkillSources', payload: target });
  };

  const handleSaveSkillSources = (
    target: 'agent' | 'claudeCode',
    sources: Array<{
      owner: string;
      repo: string;
      branch?: string;
      skillsPath?: string;
      platform?: string;
      baseUrl?: string;
    }>
  ) => {
    setSkillSourcesLoading(true);
    vscode.postMessage({ type: 'saveSkillSources', payload: { target, sources } });
  };

  const handleGetGithubToken = () => {
    vscode.postMessage({ type: 'getGithubToken' });
  };

  const handleSaveGithubToken = (token: string) => {
    vscode.postMessage({ type: 'saveGithubToken', payload: { token } });
  };

  const handlePreviewUpdateDiff = (skill: MarketplaceSkill) => {
    pendingUpdateSkillRef.current[skill.id] = skill;
    setUpdateDiffLoadingById((m) => ({ ...m, [skill.id]: true }));
    vscode.postMessage({ type: 'getSkillUpdateDiff', payload: { skill } });
  };

  const handleConfirmUpdate = (skill: MarketplaceSkill) => {
    vscode.postMessage({ type: 'confirmSkillUpdate', payload: { skill } });
    setUpdateDiffModal({ open: false });
  };

  // Marketplace
  const isInstalling = (id: string) => installingSkills.has(id);
  const handleInstallAgentFromMarket = (skill: MarketplaceSkill) => {
    if (isInstalling(skill.id)) return;
    setInstallingSkills(prev => new Set(prev).add(skill.id));
    vscode.postMessage({ type: 'installAgentSkill', payload: { skill } });
  };
  const handleInstallClaudeFromMarket = (skill: MarketplaceSkill) => {
    if (isInstalling(skill.id)) return;
    setInstallingSkills(prev => new Set(prev).add(skill.id));
    vscode.postMessage({ type: 'installClaudeCodeSkill', payload: { skill } });
  };
  const handleOpenFolder = (path: string) => vscode.postMessage({ type: 'openSkillFolder', payload: { path } });
  const handleRefreshMarketplace = () => { setMarketplaceLoading(true); vscode.postMessage({ type: 'refreshMarketplace' }); };
  const handleOpenSkillSourcesSettings = () => {
    vscode.postMessage({ type: 'openSkillSourcesSettings' });
  };
  const handleOpenClaudeSkillSourcesSettings = () => {
    vscode.postMessage({ type: 'openClaudeSkillSourcesSettings' });
  };

  const formatMpError = (e: MarketplaceLoadError): string => {
    switch (e.code) {
      case 'NO_SKILL_SOURCES':
        return e.channel === 'agent'
          ? t('skillManagement.marketplaceErr.noSourcesAgent')
          : t('skillManagement.marketplaceErr.noSourcesClaude');
      case 'NETWORK':
        return t('skillManagement.marketplaceErr.network');
      case 'GITHUB_SOURCE_FAILED':
        return t('skillManagement.marketplaceErr.sourceFailed', { source: e.source });
      default:
        return '';
    }
  };

  const ensureAgentDetail = (name: string) => {
    if (agentSkillDetails[name] || agentDetailLoading[name]) {
      return;
    }
    setAgentDetailLoading((l) => ({ ...l, [name]: true }));
    vscode.postMessage({ type: 'fetchAgentSkillDetail', payload: { name } });
  };

  const ensureLocalSkillMd = (skillDir: string) => {
    if (localMdByPath[skillDir] !== undefined || localMdLoading[skillDir]) {
      return;
    }
    setLocalMdLoading((l) => ({ ...l, [skillDir]: true }));
    vscode.postMessage({ type: 'fetchLocalSkillMarkdown', payload: { skillDir } });
  };

  const formatLocalSkillMdPreview = (text: string | null | undefined): string => {
    if (text === undefined || text === null) return '';
    if (text === '__SKILL_MD_META_ONLY__') return t('skillManagement.skillMdMetaOnly');
    const trimmed = text.trim();
    return trimmed || t('skillManagement.detailNoMarkdownBody');
  };

  /**
   * 格式化远程 SKILL.md 内容用于预览
   * 移除 YAML frontmatter，只显示 Markdown 正文
   */
  const formatSkillMdPreview = (text: string | null | undefined): string => {
    if (!text) return t('skillManagement.detailNoMarkdownBody');
    // 移除 YAML frontmatter
    const normalized = text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
    const match = normalized.match(/^---\n[\s\S]*?\n---\s*\n?/);
    const body = match ? normalized.slice(match[0].length).trim() : normalized.trim();
    return body || t('skillManagement.skillMdMetaOnly');
  };

  const tabToolbar = (left: React.ReactNode, right: React.ReactNode) => (
    <div
      style={{
        marginBottom: 16,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 12,
      }}
    >
      <div style={{ flex: '1 1 220px', minWidth: 0 }}>{left}</div>
      <Space wrap size="small" style={{ flex: '0 0 auto', justifyContent: 'flex-end' }}>{right}</Space>
    </div>
  );

  const mdPreviewStyle = React.useMemo(
    (): React.CSSProperties => ({
      maxHeight: 260,
      overflow: 'auto',
      padding: '8px 10px',
      borderRadius: 8,
      background: palette.codeBlockBackground,
      border: `1px solid ${palette.panelBorder}`,
    }),
    [palette.codeBlockBackground, palette.panelBorder]
  );

  /** 打开高级设置弹窗 */
  const openSourcesModal = (target: 'agent' | 'claudeCode') => {
    handleGetSkillSources(target);
    handleGetGithubToken();
    setSourcesModalTarget(target);
  };

  /** 高级设置弹窗内容 */
  const renderSourcesModalContent = () => {
    if (!sourcesModalTarget) return null;
    const sources = sourcesModalTarget === 'agent' ? agentSkillSources : claudeSkillSources;
    const setSources = sourcesModalTarget === 'agent' ? setAgentSkillSources : setClaudeSkillSources;
    const defaultSources = sourcesModalTarget === 'agent' ? DEFAULT_AGENT_SOURCES : DEFAULT_CLAUDE_SOURCES;
    const hasDefaults = defaultSources.length > 0;

    const handleAddSource = () => {
      setSources([...sources, { owner: '', repo: '', branch: 'main', platform: 'github' }]);
    };

    const handleRemoveSource = (index: number) => {
      setSources(sources.filter((_, i) => i !== index));
    };

    const handleUpdateSource = (index: number, field: string, value: string) => {
      const newSources = [...sources];
      (newSources[index] as Record<string, string>)[field] = value;
      setSources(newSources);
    };

    const handleResetToDefault = () => {
      setSources([...defaultSources]);
    };

    const handleSave = () => {
      handleSaveSkillSources(sourcesModalTarget, sources.filter(s => s.owner.trim() && s.repo.trim()));
    };

    return (
      <div>
        {/* GitHub Token 配置 */}
        <div style={{ marginBottom: 20, padding: 16, background: palette.surfaceBackground, borderRadius: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <Text strong style={{ fontSize: 13 }}>{t('skillManagement.githubTokenTitle')}</Text>
            <Tag color="default">{t('skillManagement.optional')}</Tag>
          </div>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
            {t('skillManagement.githubTokenDesc')}
          </Text>
          <Input.Password
            size="small"
            value={githubToken}
            onChange={(e) => setGithubToken(e.target.value)}
            placeholder="ghp_xxxx"
            style={{ marginBottom: 8 }}
          />
          <Button
            size="small"
            type="primary"
            ghost
            onClick={() => handleSaveGithubToken(githubToken)}
          >
            {t('skillManagement.saveToken')}
          </Button>
        </div>

        <Divider style={{ margin: '16px 0' }} />

        {/* 市场源配置 */}
        <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text strong style={{ fontSize: 13 }}>{t('skillManagement.sourcesList')}</Text>
          <Space size="small">
            {hasDefaults && (
              <Tooltip title={t('skillManagement.resetToDefaultTooltip')}>
                <Button size="small" icon={<UndoOutlined />} onClick={handleResetToDefault}>
                  {t('skillManagement.resetToDefault')}
                </Button>
              </Tooltip>
            )}
            <Button size="small" icon={<span>+</span>} onClick={handleAddSource}>
              {t('skillManagement.addSource')}
            </Button>
          </Space>
        </div>

        {hasDefaults && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12, fontSize: 12 }}
            message={t('skillManagement.defaultSourcesHint')}
          />
        )}

        {sources.length === 0 ? (
          <Empty description={t('skillManagement.noSources')} style={{ padding: 20 }} />
        ) : (
          sources.map((source, index) => {
            const isDefault = defaultSources.some(
              d => d.owner === source.owner && d.repo === source.repo && d.skillsPath === source.skillsPath
            );
            return (
              <div
                key={index}
                style={{
                  display: 'flex',
                  gap: 8,
                  alignItems: 'center',
                  padding: '10px 12px',
                  marginBottom: 8,
                  borderRadius: 6,
                  border: `1px solid ${isDefault ? palette.linkForeground : palette.panelBorder}`,
                  background: palette.surfaceBackground,
                }}
              >
                <Input
                  size="small"
                  value={source.owner}
                  onChange={(e) => handleUpdateSource(index, 'owner', e.target.value)}
                  placeholder="owner"
                  style={{ width: 100 }}
                />
                <span>/</span>
                <Input
                  size="small"
                  value={source.repo}
                  onChange={(e) => handleUpdateSource(index, 'repo', e.target.value)}
                  placeholder="repo"
                  style={{ width: 100 }}
                />
                <Input
                  size="small"
                  value={source.skillsPath || ''}
                  onChange={(e) => handleUpdateSource(index, 'skillsPath', e.target.value)}
                  placeholder="path"
                  style={{ width: 80 }}
                />
                <select
                  value={source.platform || 'github'}
                  onChange={(e) => handleUpdateSource(index, 'platform', e.target.value)}
                  style={{
                    height: 24,
                    fontSize: 12,
                    borderRadius: 4,
                    border: `1px solid ${palette.panelBorder}`,
                    background: palette.editorBackground,
                    color: palette.editorForeground,
                    width: 80,
                  }}
                >
                  <option value="github">GitHub</option>
                  <option value="gitlab">GitLab</option>
                  <option value="gitee">Gitee</option>
                </select>
                {isDefault && (
                  <Tag color="blue" style={{ margin: 0 }}>{t('skillManagement.isDefaultSource')}</Tag>
                )}
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => handleRemoveSource(index)}
                />
              </div>
            );
          })
        )}

        <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button
            size="small"
            onClick={() => handleGetSkillSources(sourcesModalTarget)}
            loading={skillSourcesLoading}
          >
            {t('skillManagement.reloadFromConfig')}
          </Button>
          <Button
            type="primary"
            size="small"
            onClick={handleSave}
            loading={skillSourcesLoading}
          >
            {t('skillManagement.saveSources')}
          </Button>
        </div>
      </div>
    );
  };

  // 过滤
  const filteredAgentSkills = React.useMemo(() => {
    if (!searchQuery) return agentSkills;
    return agentSkills.filter(s => s.name.toLowerCase().includes(searchQuery.toLowerCase()) || s.description.toLowerCase().includes(searchQuery.toLowerCase()));
  }, [agentSkills, searchQuery]);

  const filteredClaudeCodeSkills = React.useMemo(() => {
    if (!searchQuery) return claudeCodeSkills;
    const q = searchQuery.toLowerCase();
    return claudeCodeSkills.filter(
      s => s.name.toLowerCase().includes(q) || (s.description ?? '').toLowerCase().includes(q)
    );
  }, [claudeCodeSkills, searchQuery]);

  const filteredAgentMarketplaceSkills = React.useMemo(() => {
    if (!searchQuery) return agentMarketplaceSkills;
    const q = searchQuery.toLowerCase();
    return agentMarketplaceSkills.filter(
      s => s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
    );
  }, [agentMarketplaceSkills, searchQuery]);

  const filteredClaudeMarketplaceSkills = React.useMemo(() => {
    if (!searchQuery) return claudeMarketplaceSkills;
    const q = searchQuery.toLowerCase();
    return claudeMarketplaceSkills.filter(
      s => s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
    );
  }, [claudeMarketplaceSkills, searchQuery]);

  React.useEffect(() => {
    setAgentMarketPage(1);
  }, [searchQuery, filteredAgentMarketplaceSkills.length]);

  React.useEffect(() => {
    setClaudeMarketPage(1);
  }, [searchQuery, filteredClaudeMarketplaceSkills.length]);

  const agentMarketPageSlice = React.useMemo(() => {
    const start = (agentMarketPage - 1) * MARKETPLACE_PAGE_SIZE;
    return filteredAgentMarketplaceSkills.slice(start, start + MARKETPLACE_PAGE_SIZE);
  }, [filteredAgentMarketplaceSkills, agentMarketPage]);

  const claudeMarketPageSlice = React.useMemo(() => {
    const start = (claudeMarketPage - 1) * MARKETPLACE_PAGE_SIZE;
    return filteredClaudeMarketplaceSkills.slice(start, start + MARKETPLACE_PAGE_SIZE);
  }, [filteredClaudeMarketplaceSkills, claudeMarketPage]);

  const marketplaceTotalCount = agentMarketplaceSkills.length + claudeMarketplaceSkills.length;

  const filteredExtensionBundledSkills = React.useMemo(() => {
    const q = searchQuery.toLowerCase();
    if (!q) return builtinSkills;
    return builtinSkills.filter(
      s => s.name.toLowerCase().includes(q) || (s.description ?? '').toLowerCase().includes(q)
    );
  }, [builtinSkills, searchQuery]);

  const claudeUnifiedRows = React.useMemo(() => {
    const bundledNames = new Set(filteredExtensionBundledSkills.map(s => s.name));
    const bundled = filteredExtensionBundledSkills.map((skill) => {
      const workspaceSkill = filteredClaudeCodeSkills.find(
        s => s.name === skill.name && s.origin === 'workspace'
      );
      return { kind: 'bundled' as const, skill, workspaceSkill };
    });
    const extras = filteredClaudeCodeSkills
      .filter(s => !bundledNames.has(s.name))
      .map(skill => ({ kind: 'other' as const, skill }));
    return [...bundled, ...extras];
  }, [filteredExtensionBundledSkills, filteredClaudeCodeSkills]);

  const agentEnabledCount = React.useMemo(() => agentSkills.filter(s => s.enabled).length, [agentSkills]);
  const agentCustomCount = React.useMemo(() => agentSkills.filter(s => s.source !== 'builtin').length, [agentSkills]);

  const getDescription = (skill: MarketplaceSkill) => {
    const zh = i18n.language === 'zh-CN' && skill.descriptionZh?.trim();
    const text = (zh || skill.description || '').trim();
    return text || t('skillManagement.noDescription');
  };

  const descStyle = React.useMemo(
    (): React.CSSProperties => ({
      margin: '8px 0 0',
      fontSize: 13,
      lineHeight: 1.55,
      whiteSpace: 'normal',
      wordBreak: 'break-word',
      overflowWrap: 'anywhere',
      color: palette.descriptionForeground,
    }),
    [palette.descriptionForeground]
  );

  const renderTabTitle = (icon: React.ReactNode, label: string, badge: string) => (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 10,
        maxWidth: '100%',
        flexWrap: 'wrap',
        lineHeight: 1.5,
      }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}>{icon}</span>
      <span style={{ flexShrink: 0 }}>{label}</span>
      <Tag style={{ margin: 0, fontSize: 11, lineHeight: '18px', borderRadius: 6 }}>{badge}</Tag>
    </span>
  );

  const cardShell = (key: string, children: React.ReactNode, hoverable?: boolean) => (
    <Card
      key={key}
      hoverable={hoverable}
      style={{
        marginBottom: 12,
        background: palette.surfaceMuted,
        border: `1px solid ${palette.panelBorder}`,
        borderRadius: 10,
        boxShadow: '0 1px 0 rgba(0,0,0,0.04)',
      }}
      styles={{ body: { padding: '14px 16px' } }}
    >
      {children}
    </Card>
  );

  const statPill = (label: string, value: string | number, accent?: string) => (
    <div
      style={{
        flex: '1 1 120px',
        minWidth: 100,
        padding: '12px 16px',
        borderRadius: 8,
        border: `1px solid ${palette.panelBorder}`,
        background: `linear-gradient(135deg, ${palette.surfaceBackground} 0%, ${palette.editorBackground} 100%)`,
        transition: 'all 0.2s ease',
      }}
    >
      <div style={{ fontSize: 11, color: palette.descriptionForeground, marginBottom: 6, fontWeight: 500, letterSpacing: 0.3 }}>{label}</div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          fontVariantNumeric: 'tabular-nums',
          color: accent ?? palette.editorForeground,
          lineHeight: 1,
        }}
      >
        {value}
      </div>
    </div>
  );

  const renderAgentSkillCard = (skill: AgentSkill, isBuiltin: boolean) => {
    const detail = agentSkillDetails[skill.name];
    const dLoading = !!agentDetailLoading[skill.name];
    const scriptText = (detail?.script ?? skill.script ?? '').trim();
    const requiresList = (detail?.requires ?? skill.requires ?? []).filter(Boolean);
    const mdBody = (detail?.skill_md ?? '').trim();
    return cardShell(
      skill.name,
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: '1 1 220px', minWidth: 0 }}>
            <Space wrap size={[4, 4]}>
              <Tag color={isBuiltin ? 'blue' : 'green'}>
                {isBuiltin ? t('skillManagement.tagAgentBackend') : t('skillManagement.tagAgentRegistered')}
              </Tag>
              <Text strong style={{ wordBreak: 'break-word' }}>{skill.name}</Text>
              {skill.enabled && <Tag color="success" icon={<CheckCircleOutlined />}>{t('skillManagement.enabled')}</Tag>}
            </Space>
            <div style={descStyle}>{skill.description || t('skillManagement.noDescription')}</div>
          </div>
          <Space wrap style={{ flex: '0 0 auto', justifyContent: 'flex-end' }}>
            <Tooltip title={skill.enabled ? t('skillManagement.disable') : t('skillManagement.enable')}>
              <Switch checked={skill.enabled} onChange={() => handleToggleAgentSkill(skill)} size="small" />
            </Tooltip>
            {!isBuiltin && (
              <Tooltip title={t('skillManagement.reload')}>
                <Button type="text" size="small" icon={<SyncOutlined />} onClick={() => handleReloadAgentSkill(skill.name)} />
              </Tooltip>
            )}
            <Tooltip title={t('skillManagement.viewDocumentation')}>
              <Button type="text" size="small" icon={<BookOutlined />} onClick={() => handleOpenAgentSkillDoc(skill)} />
            </Tooltip>
            <Tooltip title={t('skillManagement.openFolder')}>
              <Button type="text" size="small" icon={<FolderOpenOutlined />} onClick={() => handleOpenFolder(skill.path)} />
            </Tooltip>
            {!isBuiltin && (
              <Tooltip title={t('skillManagement.archiveAgentTooltip')}>
                <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={() => handleRemoveAgentSkill(skill.name)} />
              </Tooltip>
            )}
          </Space>
        </div>
        <SkillDetailCollapse
          panelLabel={t('skillManagement.skillDetails')}
          onPanelOpen={() => ensureAgentDetail(skill.name)}
          loading={dLoading && !detail}
          borderColor={palette.panelBorder}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.detailPath')}</Text>
              <div style={{ fontSize: 12, wordBreak: 'break-all', color: palette.editorForeground }}>
                {detail?.path ?? skill.path}
              </div>
            </div>
            {scriptText ? (
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.detailScript')}</Text>
                <div
                  style={{
                    fontSize: 12,
                    fontFamily: 'var(--vscode-editor-font-family, monospace)',
                    wordBreak: 'break-all',
                    color: palette.editorForeground,
                  }}
                >
                  {scriptText}
                </div>
              </div>
            ) : null}
            {requiresList.length > 0 ? (
              <div>
                <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                  {t('skillManagement.detailRequires')}
                </Text>
                <Space wrap size={[4, 4]}>
                  {requiresList.map((r) => (
                    <Tag key={r} style={{ margin: 0 }}>{r}</Tag>
                  ))}
                </Space>
              </div>
            ) : null}
            <div>
              <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                {t('skillManagement.detailMarkdown')}
              </Text>
              <div style={mdPreviewStyle}>
                <pre
                  style={{
                    margin: 0,
                    fontSize: 11,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    color: palette.editorForeground,
                  }}
                >
                  {mdBody || t('skillManagement.detailNoMarkdownBody')}
                </pre>
              </div>
            </div>
          </div>
        </SkillDetailCollapse>
      </div>
    );
  };

  const renderClaudeCodeSkillCard = (skill: ClaudeCodeSkill) => {
    const mdKey = skill.path;
    const mdLoading = !!localMdLoading[mdKey];
    const mdText = localMdByPath[mdKey];
    const isActive = skill.active !== false;
    return cardShell(
      skill.name,
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: '1 1 220px', minWidth: 0 }}>
            <Space wrap size={[4, 4]}>
              <Tag color={skill.origin === 'workspace' ? 'blue' : 'geekblue'}>
                {t(`skillManagement.claudeOrigin.${skill.origin}`)}
              </Tag>
              {!isActive ? <Tag color="warning">{t('skillManagement.claudeSkillInactive')}</Tag> : null}
              <Text strong style={{ wordBreak: 'break-word' }}>{skill.name}</Text>
            </Space>
            <div style={descStyle}>{skill.description || t('skillManagement.noDescription')}</div>
          </div>
          <Space wrap style={{ flex: '0 0 auto', justifyContent: 'flex-end' }}>
            {skill.hasSkillMd && (
              <Tooltip title={t('skillManagement.viewDocumentation')}>
                <Button type="text" size="small" icon={<BookOutlined />} onClick={() => handleOpenLocalSkillMarkdown(skill.path)} />
              </Tooltip>
            )}
            <Tooltip title={t('skillManagement.openFolder')}>
              <Button type="text" size="small" icon={<FolderOpenOutlined />} onClick={() => handleOpenFolder(skill.path)} />
            </Tooltip>
            {isActive ? (
              <Button size="small" onClick={() => handleSetClaudeSkillActive(skill.name, skill.origin, false)}>
                {t('skillManagement.claudeSkillDeactivate')}
              </Button>
            ) : (
              <Button type="primary" size="small" onClick={() => handleSetClaudeSkillActive(skill.name, skill.origin, true)}>
                {t('skillManagement.claudeSkillActivate')}
              </Button>
            )}
            <Tooltip title={t('skillManagement.purgeClaudeSkill')}>
              <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={() => handlePurgeClaudeCodeSkill(skill.name, skill.origin)} />
            </Tooltip>
          </Space>
        </div>
        <SkillDetailCollapse
          panelLabel={t('skillManagement.skillDetails')}
          onPanelOpen={() => ensureLocalSkillMd(skill.path)}
          loading={mdLoading && mdText === undefined}
          borderColor={palette.panelBorder}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.detailPath')}</Text>
              <div style={{ fontSize: 12, wordBreak: 'break-all', color: palette.editorForeground }}>{skill.path}</div>
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                {t('skillManagement.detailFiles')}
              </Text>
              <Text style={{ fontSize: 12 }}>{skill.files.length ? skill.files.join(', ') : '—'}</Text>
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                {t('skillManagement.detailMarkdown')}
              </Text>
              <div style={mdPreviewStyle}>
                <pre
                  style={{
                    margin: 0,
                    fontSize: 11,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    color: palette.editorForeground,
                  }}
                >
                  {mdText === undefined ? '' : formatLocalSkillMdPreview(mdText)}
                </pre>
              </div>
            </div>
          </div>
        </SkillDetailCollapse>
      </div>
    );
  };

  /**
   * 统一的市场技能卡片渲染函数
   */
  const renderMarketplaceCard = (
    skill: MarketplaceSkill,
    installTarget: 'agent' | 'claudeCode'
  ) => {
    const installing = isInstalling(skill.id);
    const alreadyInstalled = installTarget === 'agent'
      ? agentSkills.some(s => s.name === skill.id)
      : claudeCodeSkills.some(s => s.name === skill.id);
    const hasUpdate = skill.updateAvailable && skill.installedVersion;
    const cardKey = installTarget === 'agent' ? `agent-mp-${skill.id}` : `claude-mp-${skill.id}`;
    const handleInstall = installTarget === 'agent'
      ? handleInstallAgentFromMarket
      : handleInstallClaudeFromMarket;

    return cardShell(
      cardKey,
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: '1 1 240px', minWidth: 0 }}>
            <Space wrap size={[4, 4]}>
              <Text strong style={{ wordBreak: 'break-word' }}>{skill.name}</Text>
              {skill.version && <Tag style={{ margin: 0 }}>v{skill.version}</Tag>}
              <Tag color="blue">{skill.author}</Tag>
              {hasUpdate && <Tag color="orange">{t('skillManagement.updateAvailable')}</Tag>}
            </Space>
            <div style={descStyle}>{getDescription(skill)}</div>
            <Space size={4} wrap style={{ marginTop: 8 }}>
              {(skill.tags ?? []).slice(0, 6).map(tag => <Tag key={tag} style={{ margin: 0, fontSize: 11 }}>{tag}</Tag>)}
            </Space>
          </div>
          <Space wrap style={{ flex: '0 0 auto' }}>
            {hasUpdate ? (
              <Button
                type="primary"
                size="small"
                icon={<SyncOutlined />}
                onClick={() => handlePreviewUpdateDiff(skill)}
                disabled={installing}
                loading={installing || !!updateDiffLoadingById[skill.id]}
              >
                {t('skillManagement.updateTo', { version: skill.version })}
              </Button>
            ) : (
              <Button
                type="primary"
                size="small"
                icon={installing ? <Spin size="small" /> : <DownloadOutlined />}
                onClick={() => handleInstall(skill)}
                disabled={installing || alreadyInstalled}
                loading={installing}
              >
                {alreadyInstalled
                  ? t('skillManagement.installed')
                  : installTarget === 'agent'
                    ? t('skillManagement.installAgent')
                    : t('skillManagement.installClaudeCode')}
              </Button>
            )}
          </Space>
        </div>
        <SkillDetailCollapse
          panelLabel={t('skillManagement.skillDetails')}
          loading={false}
          borderColor={palette.panelBorder}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
            {skill.installedVersion && (
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.detailInstalledVersion')}</Text>
                <div>v{skill.installedVersion}</div>
              </div>
            )}
            <div>
              <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.detailRepo')}</Text>
              <div style={{ wordBreak: 'break-all' }}>{skill.repo}</div>
            </div>
            {(skill.compatibility ?? []).length > 0 ? (
              <div>
                <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                  {t('skillManagement.detailCompat')}
                </Text>
                <Space wrap size={[4, 4]}>
                  {(skill.compatibility ?? []).map((c) => (
                    <Tag key={c} style={{ margin: 0 }}>{c}</Tag>
                  ))}
                </Space>
              </div>
            ) : null}
            {skill.skillMdContent && (
              <div>
                <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                  {t('skillManagement.detailMarkdown')}
                </Text>
                <div style={mdPreviewStyle}>
                  <pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: palette.editorForeground }}>
                    {formatSkillMdPreview(skill.skillMdContent)}
                  </pre>
                </div>
              </div>
            )}
            {skill.homepage ? (
              <Button
                type="link"
                size="small"
                style={{ padding: 0, height: 'auto' }}
                onClick={() => vscode.postMessage({ type: 'openExternal', payload: { url: skill.homepage } })}
              >
                {t('skillManagement.viewHomepage')}
              </Button>
            ) : null}
          </div>
        </SkillDetailCollapse>
      </div>,
      true
    );
  };

  const renderAgentMarketplaceCard = (skill: MarketplaceSkill) => {
    return renderMarketplaceCard(skill, 'agent');
  };

  const renderClaudeMarketplaceCard = (skill: MarketplaceSkill) => {
    return renderMarketplaceCard(skill, 'claudeCode');
  };

  const renderClaudeUnifiedRow = (row: (typeof claudeUnifiedRows)[number]) => {
    if (row.kind === 'other') {
      return renderClaudeCodeSkillCard(row.skill);
    }

    const { skill, workspaceSkill } = row;
    const workspaceSynced = !!workspaceSkill;
    const wsActive = workspaceSkill ? workspaceSkill.active !== false : false;
    const displayPath = workspaceSkill?.path ?? skill.path;
    const detailFiles = workspaceSkill?.files ?? [];
    const mdKey = displayPath;
    const mdLoading = !!localMdLoading[mdKey];
    const mdText = localMdByPath[mdKey];

    return cardShell(
      `vsix-${skill.name}`,
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: '1 1 220px', minWidth: 0 }}>
            <Space wrap size={[4, 4]}>
              <Tag color="purple">{t('skillManagement.vsixTemplateTag')}</Tag>
              {workspaceSynced ? (
                wsActive ? (
                  <Tag color="success">{t('skillManagement.vsixWorkspaceSynced')}</Tag>
                ) : (
                  <Tag color="warning">{t('skillManagement.vsixWorkspaceInactive')}</Tag>
                )
              ) : (
                <Tag>{t('skillManagement.vsixWorkspacePending')}</Tag>
              )}
              <Text strong style={{ wordBreak: 'break-word' }}>{skill.name}</Text>
            </Space>
            <div style={descStyle}>{skill.description || t('skillManagement.noDescription')}</div>
          </div>
          <Space wrap style={{ flex: '0 0 auto', justifyContent: 'flex-end' }}>
            <Button
              type="primary"
              size="small"
              icon={<CloudSyncOutlined />}
              loading={vsixSyncLoading.has(skill.name)}
              onClick={() => handleSyncOneBundledClaudeSkill(skill.name)}
            >
              {workspaceSynced ? t('skillManagement.resyncVsixToWorkspace') : t('skillManagement.syncVsixToWorkspace')}
            </Button>
            {skill.hasSkillMd && (
              <Tooltip title={t('skillManagement.viewDocumentation')}>
                <Button type="text" size="small" icon={<BookOutlined />} onClick={() => handleOpenLocalSkillMarkdown(displayPath)} />
              </Tooltip>
            )}
            <Tooltip title={t('skillManagement.openFolder')}>
              <Button type="text" size="small" icon={<FolderOpenOutlined />} onClick={() => handleOpenFolder(displayPath)} />
            </Tooltip>
            {workspaceSynced && wsActive ? (
              <Button size="small" onClick={() => handleSetClaudeSkillActive(skill.name, 'workspace', false)}>
                {t('skillManagement.claudeSkillDeactivate')}
              </Button>
            ) : null}
            {workspaceSynced && !wsActive ? (
              <Button type="primary" size="small" onClick={() => handleSetClaudeSkillActive(skill.name, 'workspace', true)}>
                {t('skillManagement.claudeSkillActivate')}
              </Button>
            ) : null}
            {workspaceSynced ? (
              <Tooltip title={t('skillManagement.purgeClaudeSkill')}>
                <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={() => handlePurgeClaudeCodeSkill(skill.name, 'workspace')} />
              </Tooltip>
            ) : null}
          </Space>
        </div>
        <SkillDetailCollapse
          panelLabel={t('skillManagement.skillDetails')}
          onPanelOpen={() => ensureLocalSkillMd(displayPath)}
          loading={mdLoading && mdText === undefined}
          borderColor={palette.panelBorder}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.detailPath')}</Text>
              <div style={{ fontSize: 12, wordBreak: 'break-all', color: palette.editorForeground }}>{displayPath}</div>
            </div>
            {workspaceSynced ? (
              <div>
                <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                  {t('skillManagement.detailFiles')}
                </Text>
                <Text style={{ fontSize: 12 }}>{detailFiles.length ? detailFiles.join(', ') : '—'}</Text>
              </div>
            ) : null}
            <div>
              <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                {t('skillManagement.detailMarkdown')}
              </Text>
              <div style={mdPreviewStyle}>
                <pre
                  style={{
                    margin: 0,
                    fontSize: 11,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    color: palette.editorForeground,
                  }}
                >
                  {mdText === undefined ? '' : formatLocalSkillMdPreview(mdText)}
                </pre>
              </div>
            </div>
          </div>
        </SkillDetailCollapse>
      </div>
    );
  };

  const sectionPanelHeader = (icon: React.ReactNode, label: string) => (
    <Text strong style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      {icon}
      {label}
    </Text>
  );

  const renderAgentMarketplaceSection = () => (
    <Collapse ghost style={{ marginTop: 16 }}>
      <Panel header={sectionPanelHeader(<ShopOutlined />, t('skillManagement.marketplaceAgent'))} key="marketplaceAgent">
        <div style={{ marginBottom: 10 }}>
          <Space wrap align="center">
            <Button icon={<ReloadOutlined />} onClick={handleRefreshMarketplace} loading={marketplaceLoading} size="small">
              {t('skillManagement.refresh')}
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>{t('skillManagement.marketplaceAgentHint')}</Text>
          </Space>
        </div>
        {agentMarketplaceLoadErrors.length > 0 && (
          <Alert
            type={filteredAgentMarketplaceSkills.length === 0 ? 'warning' : 'info'}
            showIcon
            style={{ marginBottom: 12 }}
            message={t('skillManagement.marketplaceLoadIssues')}
            description={(
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                {agentMarketplaceLoadErrors.map((e, i) => (
                  <li key={i} style={{ marginBottom: 4 }}>{formatMpError(e)}</li>
                ))}
              </ul>
            )}
          />
        )}
        {marketplaceLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}><Spin /></div>
        ) : filteredAgentMarketplaceSkills.length === 0 ? (
          <Empty description={t('skillManagement.noMarketplaceSkillsAgent')}>
            <Text type="secondary" style={{ fontSize: 12 }}>{t('skillManagement.configureSourcesHint')}</Text>
          </Empty>
        ) : (
          <>
            {agentMarketPageSlice.map(renderAgentMarketplaceCard)}
            {filteredAgentMarketplaceSkills.length > MARKETPLACE_PAGE_SIZE ? (
              <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end', flexWrap: 'wrap', gap: 8 }}>
                <Pagination
                  size="small"
                  current={agentMarketPage}
                  pageSize={MARKETPLACE_PAGE_SIZE}
                  total={filteredAgentMarketplaceSkills.length}
                  onChange={setAgentMarketPage}
                  showSizeChanger={false}
                  showTotal={(total, range) =>
                    t('skillManagement.marketplacePaginationTotal', {
                      start: range[0],
                      end: range[1],
                      total,
                    })
                  }
                />
              </div>
            ) : null}
          </>
        )}
        {/* 高级设置：市场源配置 - 放在最下方 */}
        <Collapse
          ghost
          size="small"
          style={{ marginTop: 16 }}
          items={[
            {
              key: 'advanced',
              label: <Text style={{ fontSize: 12 }}><SettingOutlined /> {t('skillManagement.advancedSettings')}</Text>,
              children: (
                <Button
                  size="small"
                  icon={<SettingOutlined />}
                  onClick={() => openSourcesModal('agent')}
                >
                  {t('skillManagement.openAdvancedSettings')}
                </Button>
              ),
            },
          ]}
        />
      </Panel>
    </Collapse>
  );

  const renderClaudeMarketplaceSection = () => (
    <Collapse ghost style={{ marginTop: 16 }}>
      <Panel header={sectionPanelHeader(<ShopOutlined />, t('skillManagement.marketplaceClaude'))} key="marketplaceClaude">
        <div style={{ marginBottom: 10 }}>
          <Space wrap align="center">
            <Button icon={<ReloadOutlined />} onClick={handleRefreshMarketplace} loading={marketplaceLoading} size="small">
              {t('skillManagement.refresh')}
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>{t('skillManagement.marketplaceClaudeHint')}</Text>
          </Space>
        </div>
        {claudeMarketplaceLoadErrors.length > 0 && (
          <Alert
            type={filteredClaudeMarketplaceSkills.length === 0 ? 'warning' : 'info'}
            showIcon
            style={{ marginBottom: 12 }}
            message={t('skillManagement.marketplaceLoadIssues')}
            description={(
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                {claudeMarketplaceLoadErrors.map((e, i) => (
                  <li key={i} style={{ marginBottom: 4 }}>{formatMpError(e)}</li>
                ))}
              </ul>
            )}
          />
        )}
        {marketplaceLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}><Spin /></div>
        ) : filteredClaudeMarketplaceSkills.length === 0 ? (
          <Empty description={t('skillManagement.noMarketplaceSkillsClaude')}>
            <Text type="secondary" style={{ fontSize: 12 }}>{t('skillManagement.configureSourcesHint')}</Text>
          </Empty>
        ) : (
          <>
            {claudeMarketPageSlice.map(renderClaudeMarketplaceCard)}
            {filteredClaudeMarketplaceSkills.length > MARKETPLACE_PAGE_SIZE ? (
              <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end', flexWrap: 'wrap', gap: 8 }}>
                <Pagination
                  size="small"
                  current={claudeMarketPage}
                  pageSize={MARKETPLACE_PAGE_SIZE}
                  total={filteredClaudeMarketplaceSkills.length}
                  onChange={setClaudeMarketPage}
                  showSizeChanger={false}
                  showTotal={(total, range) =>
                    t('skillManagement.marketplacePaginationTotal', {
                      start: range[0],
                      end: range[1],
                      total,
                    })
                  }
                />
              </div>
            ) : null}
          </>
        )}
        {/* 高级设置：市场源配置 - 放在最下方 */}
        <Collapse
          ghost
          size="small"
          style={{ marginTop: 16 }}
          items={[
            {
              key: 'advanced',
              label: <Text style={{ fontSize: 12 }}><SettingOutlined /> {t('skillManagement.advancedSettings')}</Text>,
              children: (
                <Button
                  size="small"
                  icon={<SettingOutlined />}
                  onClick={() => openSourcesModal('claudeCode')}
                >
                  {t('skillManagement.openAdvancedSettings')}
                </Button>
              ),
            },
          ]}
        />
      </Panel>
    </Collapse>
  );

  const renderAgentTab = () => {
    const builtinAgentSkills = filteredAgentSkills.filter(s => s.source === 'builtin');
    const customSkills = filteredAgentSkills.filter(s => s.source !== 'builtin');
    return (
      <div>
        {tabToolbar(
          <Text type="secondary" style={{ fontSize: 13 }}>
            {t('skillManagement.agentSkillsCount', { count: filteredAgentSkills.length })}
          </Text>,
          <>
            <Button icon={<SearchOutlined />} onClick={handleScanAgentSkills} size="small">
              {t('skillManagement.scanAgentSkills')}
            </Button>
            <Button icon={<ReloadOutlined />} onClick={handleRefreshAgentList} size="small">
              {t('skillManagement.refreshList')}
            </Button>
            <Button type="primary" icon={<ImportOutlined />} onClick={handleImportAgentSkill} size="small">
              {t('skillManagement.importSkill')}
            </Button>
          </>
        )}
        {agentSkillsLoading ? <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div> : (
          <>
            {builtinAgentSkills.length > 0 && (
              <Collapse defaultActiveKey={['builtin']} ghost>
                <Panel
                  header={sectionPanelHeader(<InboxOutlined />, t('skillManagement.agentBackendSection'))}
                  key="builtin"
                >
                  {builtinAgentSkills.map(s => renderAgentSkillCard(s, true))}
                </Panel>
              </Collapse>
            )}
            {customSkills.length > 0 && (
              <Collapse defaultActiveKey={['custom']} ghost style={{ marginTop: builtinAgentSkills.length > 0 ? 8 : 0 }}>
                <Panel header={sectionPanelHeader(<ToolOutlined />, t('skillManagement.agentRegisteredSection'))} key="custom">
                  {customSkills.map(s => renderAgentSkillCard(s, false))}
                </Panel>
              </Collapse>
            )}
            {filteredAgentSkills.length === 0 && (
              <Empty description={t('skillManagement.noAgentSkills')} style={{ padding: 40 }} />
            )}
          </>
        )}
        {renderAgentMarketplaceSection()}
      </div>
    );
  };

  const renderClaudeCodeTab = () => {
    const listBlocking =
      (claudeCodeSkillsLoading || builtinSkillsLoading) && claudeUnifiedRows.length === 0;

    return (
      <div>
        {tabToolbar(
          <Text type="secondary" style={{ fontSize: 13 }}>
            {t('skillManagement.claudeCodeSkillsCount', { count: filteredClaudeCodeSkills.length })}
          </Text>,
          <>
            <Button icon={<ReloadOutlined />} onClick={handleRefreshClaudeList} size="small">
              {t('skillManagement.refreshList')}
            </Button>
            <Button icon={<CloudSyncOutlined />} onClick={handleUpdateExtensionSkills} size="small">
              {t('skillManagement.syncExtensionSkills')}
            </Button>
            <Button type="primary" icon={<ImportOutlined />} onClick={handleImportClaudeCodeSkill} size="small">
              {t('skillManagement.importClaudeSkill')}
            </Button>
          </>
        )}
        <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 10 }}>
          {t('skillManagement.claudeUnifiedListTitle')}
        </Text>
        {listBlocking ? <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div> : (
          <>
            {claudeUnifiedRows.length > 0 ? (
              <>{claudeUnifiedRows.map((row) => renderClaudeUnifiedRow(row))}</>
            ) : (
              <Empty description={t('skillManagement.noClaudeCodeSkills')} style={{ padding: 40 }} />
            )}
          </>
        )}
        {renderClaudeMarketplaceSection()}
      </div>
    );
  };

  const heroBorder = palette.panelBorder;
  const heroBg = palette.surfaceBackground;

  return (
    <ConfigProvider theme={themeConfig}>
      <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
        <Content style={{ padding: '20px 22px 28px' }}>
          <Modal
            open={updateDiffModal.open}
            title={t('skillManagement.updateDiffTitle', {
              name: updateDiffModal.skill?.name || updateDiffModal.diff?.skillName || '',
              from: updateDiffModal.diff?.localVersion || updateDiffModal.skill?.installedVersion || '',
              to: updateDiffModal.diff?.remoteVersion || updateDiffModal.skill?.version || '',
            })}
            width={920}
            okText={t('skillManagement.confirmUpdate')}
            cancelText={t('skillManagement.cancel')}
            onCancel={() => setUpdateDiffModal({ open: false })}
            onOk={() => {
              if (updateDiffModal.skill) {
                handleConfirmUpdate(updateDiffModal.skill);
              }
            }}
            okButtonProps={{ disabled: !updateDiffModal.skill }}
          >
            {!updateDiffModal.diff ? (
              <div style={{ padding: 16, textAlign: 'center' }}>
                <Spin />
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 12 }}>
                  <Tag color="green">{t('skillManagement.diffAdded', { count: updateDiffModal.diff.filesAdded.length })}</Tag>
                  <Tag color="red">{t('skillManagement.diffDeleted', { count: updateDiffModal.diff.filesDeleted.length })}</Tag>
                  <Tag color="blue">{t('skillManagement.diffModified', { count: updateDiffModal.diff.filesModified.length })}</Tag>
                </div>
                <div style={{ maxHeight: 460, overflow: 'auto', border: `1px solid ${palette.panelBorder}`, borderRadius: 10 }}>
                  <div style={{ padding: 12 }}>
                    {(updateDiffModal.diff.fileDiffs || []).map((f: any) => (
                      <div key={f.path} style={{ marginBottom: 14 }}>
                        <Text strong style={{ fontSize: 12 }}>{f.path}</Text>
                        <Tag style={{ marginLeft: 8 }} color={f.status === 'added' ? 'green' : f.status === 'deleted' ? 'red' : 'blue'}>
                          {f.status}
                        </Tag>
                        {(f.hunks || []).map((h: any, idx: number) => (
                          <pre
                            key={idx}
                            style={{
                              marginTop: 8,
                              marginBottom: 0,
                              padding: '10px 12px',
                              background: palette.codeBlockBackground,
                              border: `1px solid ${palette.panelBorder}`,
                              borderRadius: 8,
                              fontSize: 11,
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              color: palette.editorForeground,
                            }}
                          >
                            {h.lines?.join('\n') || ''}
                          </pre>
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </Modal>
          {/* 帮助弹窗 */}
          <Modal
            open={helpModalOpen}
            title={t('skillManagement.helpTitle')}
            onCancel={() => setHelpModalOpen(false)}
            footer={null}
            width={720}
          >
            <div style={{ fontSize: 13, lineHeight: 1.7 }}>
              <Title level={5} style={{ marginTop: 0 }}>{t('skillManagement.helpAgentTabTitle')}</Title>
              <Text style={{ display: 'block', marginBottom: 8 }}>{t('skillManagement.helpAgentTabDescFull')}</Text>
              <ul style={{ margin: '0 0 16px', paddingLeft: 20 }}>
                <li>{t('skillManagement.helpAgentEnable')}</li>
                <li>{t('skillManagement.helpAgentArchive')}</li>
                <li>{t('skillManagement.helpAgentImport')}</li>
                <li>{t('skillManagement.helpAgentScan')}</li>
              </ul>

              <Title level={5}>{t('skillManagement.helpClaudeTabTitle')}</Title>
              <Text style={{ display: 'block', marginBottom: 8 }}>{t('skillManagement.helpClaudeTabDescFull')}</Text>
              <ul style={{ margin: '0 0 16px', paddingLeft: 20 }}>
                <li>{t('skillManagement.helpClaudeSync')}</li>
                <li>{t('skillManagement.helpClaudeToggle')}</li>
                <li>{t('skillManagement.helpClaudeDelete')}</li>
              </ul>

              <Title level={5}>{t('skillManagement.helpMarketplaceTitle')}</Title>
              <Text style={{ display: 'block', marginBottom: 8 }}>{t('skillManagement.helpMarketplaceDesc')}</Text>
              <ul style={{ margin: '0 0 16px', paddingLeft: 20 }}>
                <li>{t('skillManagement.helpMarketplaceInstall')}</li>
                <li>{t('skillManagement.helpMarketplaceSources')}</li>
                <li>{t('skillManagement.helpMarketplaceUpdate')}</li>
              </ul>

              <Title level={5}>{t('skillManagement.helpSourcesTitle')}</Title>
              <Text>{t('skillManagement.helpSourcesDesc')}</Text>
            </div>
          </Modal>
          {/* 高级设置弹窗 */}
          <Modal
            open={sourcesModalTarget !== null}
            title={t('skillManagement.advancedSettingsTitle')}
            onCancel={() => setSourcesModalTarget(null)}
            footer={null}
            width={640}
          >
            {renderSourcesModalContent()}
          </Modal>
          <div style={{ maxWidth: 1180, margin: '0 auto' }}>
            {/* 头部区域 */}
            <div
              style={{
                marginBottom: 20,
                padding: '24px 28px',
                borderRadius: 16,
                border: `1px solid ${heroBorder}`,
                background: `linear-gradient(180deg, ${heroBg} 0%, ${palette.editorBackground} 100%)`,
                boxShadow: `0 2px 8px rgba(0,0,0,0.08)`,
              }}
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: 42,
                      height: 42,
                      borderRadius: 12,
                      background: `linear-gradient(135deg, ${palette.linkForeground}20 0%, ${palette.linkForeground}10 100%)`,
                      color: palette.linkForeground,
                    }}
                  >
                    <AppstoreOutlined style={{ fontSize: 20 }} />
                  </span>
                  <div>
                    <Title level={4} style={{ margin: 0 }}>{t('skillManagement.title')}</Title>
                    <Text type="secondary" style={{ fontSize: 12 }}>{t('skillManagement.subtitle')}</Text>
                  </div>
                  <Tooltip title={t('skillManagement.helpTooltip')}>
                    <Button
                      type="text"
                      size="small"
                      icon={<QuestionCircleOutlined />}
                      onClick={() => setHelpModalOpen(true)}
                      style={{ color: palette.linkForeground, marginLeft: 8 }}
                    />
                  </Tooltip>
                </div>
                <Tooltip title={t('skillManagement.refreshAll')}>
                  <Button
                    size="small"
                    icon={<ReloadOutlined />}
                    onClick={() => {
                      vscode.postMessage({ type: 'listAgentSkills' });
                      vscode.postMessage({ type: 'listClaudeCodeSkills' });
                      vscode.postMessage({ type: 'listBuiltinSkills' });
                      vscode.postMessage({ type: 'refreshMarketplace' });
                    }}
                  >
                    {t('skillManagement.refresh')}
                  </Button>
                </Tooltip>
              </div>

              {/* 统计卡片 */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 20 }}>
                {statPill(t('skillManagement.statEnabledAgent'), agentEnabledCount, palette.successForeground)}
                {statPill(t('skillManagement.statCustomAgent'), agentCustomCount)}
                {statPill(t('skillManagement.statMarketplace'), marketplaceTotalCount, palette.linkForeground)}
                {statPill(t('skillManagement.statClaude'), claudeCodeSkills.length)}
              </div>

              {/* 搜索框 */}
              <Search
                placeholder={t('skillManagement.searchPlaceholder')}
                allowClear
                enterButton
                size="middle"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>
            <Tabs
              activeKey={activeTab}
              onChange={(key) => setActiveTab(key as SkillTab)}
              tabBarStyle={{ marginBottom: 12 }}
              items={[
                {
                  key: 'agent',
                  label: renderTabTitle(
                    <RobotOutlined />,
                    t('skillManagement.agentSkillsTab'),
                    `${agentEnabledCount}/${agentSkills.length}`
                  ),
                  children: renderAgentTab(),
                },
                {
                  key: 'claudeCode',
                  label: renderTabTitle(
                    <ThunderboltOutlined />,
                    t('skillManagement.claudeCodeSkillsTab'),
                    String(claudeCodeSkills.length)
                  ),
                  children: renderClaudeCodeTab(),
                },
              ]}
            />
          </div>
        </Content>
      </Layout>
    </ConfigProvider>
  );
};