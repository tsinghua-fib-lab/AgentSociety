import * as React from 'react';
import {
  ConfigProvider, Layout, Input, Button, Typography, Tag, Space, Spin, Empty,
  message, Modal, Tooltip, Tabs, Switch, Collapse, Alert, Pagination, Dropdown, Segmented,
} from 'antd';
import type { MenuProps } from 'antd';
import {
  SearchOutlined, DownloadOutlined, DeleteOutlined, FolderOpenOutlined,
  ReloadOutlined, AppstoreOutlined, BookOutlined,
  ToolOutlined, RobotOutlined, ThunderboltOutlined, ShopOutlined,
  SyncOutlined, ImportOutlined, InboxOutlined, CloudSyncOutlined, SettingOutlined,
  QuestionCircleOutlined, ApiOutlined, MoreOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type {
  VSCodeAPI, MarketplaceSkill, AgentSkill, ClaudeCodeSkill, BuiltinSkill, BundledPlugin,
  AgentSkillDetailPayload,
  MarketplaceLoadError, MarketplaceChannelsPayload, SkillSourceConfig,
  McpServerRecord, McpProbeResult, McpPresetCatalogItem,
} from './types';
import { DEFAULT_CLAUDE_SOURCES, DEFAULT_AGENT_SOURCES } from './types';
import {
  isBuiltinAgentSkill,
  partitionAgentSkillsBySource,
  type AgentSkillSourceKind,
} from '../../agentSkillSource';
import { useVscodeTheme } from '../theme';
import 'antd/dist/reset.css';
import {
  SkillDetailCollapse,
  McpIntegrationsPanel,
  AgentSkillCard,
  PageSection,
  SkillEntryCard,
  SkillMarkdownPreview,
  TabToolbar,
  versionTag,
  SourcesConfigPanel,
} from './components';
import { SKILL_UI, heroShellStyle, iconBadgeStyle, skillGridStyle } from './uiTokens';

const { Content } = Layout;
const { Title, Text } = Typography;
const { Search } = Input;

const MARKETPLACE_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 200;

interface SkillManagementAppProps { vscode: VSCodeAPI; }
type SkillTab = 'agent' | 'claudeCode' | 'marketplace' | 'integrations';
type MarketplaceTarget = 'agent' | 'claudeCode';

export const SkillMarketplaceApp: React.FC<SkillManagementAppProps> = ({ vscode }) => {
  const { t, i18n } = useTranslation();
  const { palette, themeConfig, isDark } = useVscodeTheme();
  const [activeTab, setActiveTab] = React.useState<SkillTab>('agent');
  const [marketplaceTarget, setMarketplaceTarget] = React.useState<MarketplaceTarget>('agent');
  const [agentSkills, setAgentSkills] = React.useState<AgentSkill[]>([]);
  const [agentSkillsLoading, setAgentSkillsLoading] = React.useState(false);
  const [claudeCodeSkills, setClaudeCodeSkills] = React.useState<ClaudeCodeSkill[]>([]);
  const [claudeCodeSkillsLoading, setClaudeCodeSkillsLoading] = React.useState(false);
  const [builtinSkills, setBuiltinSkills] = React.useState<BuiltinSkill[]>([]);
  const [builtinSkillsLoading, setBuiltinSkillsLoading] = React.useState(false);
  const [bundledPlugins, setBundledPlugins] = React.useState<BundledPlugin[]>([]);
  const [bundledPluginsLoading, setBundledPluginsLoading] = React.useState(false);
  const [agentMarketplaceSkills, setAgentMarketplaceSkills] = React.useState<MarketplaceSkill[]>([]);
  const [claudeMarketplaceSkills, setClaudeMarketplaceSkills] = React.useState<MarketplaceSkill[]>([]);
  const [marketplaceLoading, setMarketplaceLoading] = React.useState(false);
  const [agentMarketplaceLoadErrors, setAgentMarketplaceLoadErrors] = React.useState<MarketplaceLoadError[]>([]);
  const [claudeMarketplaceLoadErrors, setClaudeMarketplaceLoadErrors] = React.useState<MarketplaceLoadError[]>([]);
  const [agentMarketPage, setAgentMarketPage] = React.useState(1);
  const [claudeMarketPage, setClaudeMarketPage] = React.useState(1);
  const [searchInput, setSearchInput] = React.useState('');
  const [searchQuery, setSearchQuery] = React.useState('');
  const [installingSkills, setInstallingSkills] = React.useState<Set<string>>(new Set());
  const [agentSkillDetails, setAgentSkillDetails] = React.useState<Record<string, AgentSkillDetailPayload>>({});
  const [agentDetailLoading, setAgentDetailLoading] = React.useState<Record<string, boolean>>({});
  const [localMdByPath, setLocalMdByPath] = React.useState<Record<string, string | null>>({});
  const [localMdLoading, setLocalMdLoading] = React.useState<Record<string, boolean>>({});
  const [vsixSyncLoading, setVsixSyncLoading] = React.useState<Set<string>>(new Set());
  // 市场源配置状态
  const [agentSkillSources, setAgentSkillSources] = React.useState<SkillSourceConfig[]>([]);
  const [claudeSkillSources, setClaudeSkillSources] = React.useState<SkillSourceConfig[]>([]);
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
  const [mcpServers, setMcpServers] = React.useState<McpServerRecord[]>([]);
  const [mcpPresets, setMcpPresets] = React.useState<McpPresetCatalogItem[]>([]);
  const [mcpLoading, setMcpLoading] = React.useState(false);
  const [mcpProbeById, setMcpProbeById] = React.useState<Record<string, McpProbeResult | undefined>>({});
  const [mcpProbingId, setMcpProbingId] = React.useState<string | undefined>();

  React.useEffect(() => {
    const handle = setTimeout(() => {
      setSearchQuery(searchInput);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  React.useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const msg = event.data;
      if (!msg || !msg.type) return;
      switch (msg.type) {
        case 'agentSkillsLoaded':
          setAgentSkills(msg.payload || []);
          setAgentSkillsLoading(false);
          break;
        case 'agentSkillImported':
          message.success(t('skillManagement.importSuccess'));
          vscode.postMessage({ type: 'listAgentSkills' });
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
        case 'bundledPluginsLoaded':
          setBundledPlugins(msg.payload || []);
          setBundledPluginsLoading(false);
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
            sources: SkillSourceConfig[];
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
            sources: SkillSourceConfig[];
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
        case 'mcpServersLoaded': {
          const payload = msg.payload as { servers?: McpServerRecord[]; presets?: McpPresetCatalogItem[] } | McpServerRecord[];
          if (Array.isArray(payload)) {
            setMcpServers(payload);
          } else {
            setMcpServers(payload?.servers ?? []);
            setMcpPresets(payload?.presets ?? []);
          }
          setMcpLoading(false);
          setMcpProbingId(undefined);
          break;
        }
        case 'mcpProbeResult': {
          const p = msg.payload as { id?: string; result?: McpProbeResult };
          if (p?.id && p.result) {
            setMcpProbeById((prev) => ({ ...prev, [p.id as string]: p.result }));
            setMcpProbingId(undefined);
          }
          break;
        }
        case 'mcpError':
          setMcpLoading(false);
          setMcpProbingId(undefined);
          message.error(msg.payload?.error || t('skillManagement.mcpError'));
          break;
      }
    };
    window.addEventListener('message', handleMessage);
    setMarketplaceLoading(true);
    vscode.postMessage({ type: 'ready' });
    vscode.postMessage({ type: 'listAgentSkills' });
    vscode.postMessage({ type: 'listClaudeCodeSkills' });
    vscode.postMessage({ type: 'listBuiltinSkills' });
    vscode.postMessage({ type: 'listBundledPlugins' });
    vscode.postMessage({ type: 'listMcpServers' });
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const handleImportAgentSkill = () => vscode.postMessage({ type: 'importAgentSkill' });
  const handleImportClaudeCodeSkill = () => vscode.postMessage({ type: 'importClaudeCodeSkill' });
  const handleScanAgentSkills = () => vscode.postMessage({ type: 'scanAgentSkills' });
  const handleRefreshAgentList = () => {
    setAgentSkillsLoading(true);
    vscode.postMessage({ type: 'listAgentSkills' });
  };
  const handleRefreshClaudeList = () => {
    setClaudeCodeSkillsLoading(true);
    setBundledPluginsLoading(true);
    vscode.postMessage({ type: 'listClaudeCodeSkills' });
    vscode.postMessage({ type: 'listBundledPlugins' });
  };
  const handleRefreshClaudeAll = () => {
    handleRefreshClaudeList();
    handleRefreshMarketplace();
  };
  const handleUpdateExtensionSkills = () => vscode.postMessage({ type: 'updateExtensionSkills' });
  const handleSwitchSkillVersion = () =>
    vscode.postMessage({ type: 'invokeSwitchSkillVersionCommand' });
  const handleEditSkillPresets = () =>
    vscode.postMessage({ type: 'invokeEditSkillPresetsCommand' });
  const handleSnapshotSkill = (name?: string) =>
    vscode.postMessage({ type: 'invokeSnapshotSkillCommand', payload: { skillName: name } });

  const handleSyncOneBundledClaudeSkill = (name: string) => {
    setVsixSyncLoading((prev) => new Set(prev).add(name));
    vscode.postMessage({ type: 'syncOneClaudeSkillFromVsix', payload: { name } });
  };

  const handleOpenAgentSkillDoc = (skill: AgentSkill) => {
    vscode.postMessage({
      type: 'openAgentSkillDoc',
      payload: {
        skillName: skill.name,
        skillPath: skill.path,
        isBuiltin: isBuiltinAgentSkill(skill),
        skillId: skill.skill_id,
      },
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

  const handleSaveSkillSources = (target: 'agent' | 'claudeCode', sources: SkillSourceConfig[]) => {
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

  const ensureAgentDetail = (skill: AgentSkill) => {
    if (agentSkillDetails[skill.name] || agentDetailLoading[skill.name]) {
      return;
    }
    setAgentDetailLoading((l) => ({ ...l, [skill.name]: true }));
    vscode.postMessage({ type: 'fetchAgentSkillDetail', payload: skill });
  };

  const ensureLocalSkillMd = (skillDir: string) => {
    if (localMdByPath[skillDir] !== undefined || localMdLoading[skillDir]) {
      return;
    }
    setLocalMdLoading((l) => ({ ...l, [skillDir]: true }));
    vscode.postMessage({ type: 'fetchLocalSkillMarkdown', payload: { skillDir } });
  };

  const tabToolbar = (left: React.ReactNode, right: React.ReactNode) => (
    <TabToolbar left={left} right={right} />
  );

  /** 打开技能源弹窗 */
  const openSourcesModal = (target: 'agent' | 'claudeCode') => {
    handleGetSkillSources(target);
    handleGetGithubToken();
    setSourcesModalTarget(target);
  };

  const renderSourcesModalContent = () => {
    if (!sourcesModalTarget) {
      return null;
    }
    const sources = sourcesModalTarget === 'agent' ? agentSkillSources : claudeSkillSources;
    const defaultSources = sourcesModalTarget === 'agent' ? DEFAULT_AGENT_SOURCES : DEFAULT_CLAUDE_SOURCES;
    return (
      <SourcesConfigPanel
        palette={palette}
        sources={sources}
        defaultSources={defaultSources}
        loading={skillSourcesLoading}
        githubToken={githubToken}
        onGithubTokenChange={setGithubToken}
        onSaveGithubToken={() => handleSaveGithubToken(githubToken)}
        onSaveSources={(next) => handleSaveSkillSources(sourcesModalTarget, next)}
      />
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

  const getDescription = (skill: MarketplaceSkill) => {
    const zh = i18n.language === 'zh-CN' && skill.descriptionZh?.trim();
    const text = (zh || skill.description || '').trim();
    return text || t('skillManagement.noDescription');
  };

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

  const statPill = (label: string, value: string | number, accent?: string) => (
    <div
      style={{
        flex: '1 1 110px',
        minWidth: 96,
        padding: '12px 14px',
        borderRadius: SKILL_UI.radius.md,
        border: `1px solid ${palette.panelBorder}`,
        background: `linear-gradient(160deg, ${palette.surfaceBackground} 0%, ${palette.editorBackground} 72%)`,
        boxShadow: accent ? `inset 0 0 0 1px ${accent}18` : undefined,
      }}
    >
      <div style={{ fontSize: 11, color: palette.descriptionForeground, marginBottom: 8, fontWeight: 500, letterSpacing: 0.3 }}>{label}</div>
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

  const detailLabelStyle: React.CSSProperties = {
    fontSize: 11,
    marginBottom: 2,
  };

  const detailValueStyle: React.CSSProperties = {
    fontSize: 12,
    wordBreak: 'break-all',
    color: palette.editorForeground,
  };

  const cardsGridStyle = skillGridStyle();

  const renderAgentSkillSection = (
    title: string,
    subtitle: string,
    skills: AgentSkill[],
    sourceKind: AgentSkillSourceKind,
    icon: React.ReactNode,
  ) => (
    <PageSection
      palette={palette}
      icon={icon}
      title={`${title} (${skills.length})`}
      subtitle={subtitle}
    >
      <div style={cardsGridStyle}>
        {skills.map((skill) => (
          <AgentSkillCard
            key={skill.name}
            skill={skill}
            sourceKind={sourceKind}
            palette={palette}
            isDark={isDark}
            detail={agentSkillDetails[skill.name]}
            detailLoading={!!agentDetailLoading[skill.name]}
            t={t}
            onOpenDoc={handleOpenAgentSkillDoc}
            onOpenFolder={handleOpenFolder}
            onExpandDetail={ensureAgentDetail}
          />
        ))}
      </div>
    </PageSection>
  );

  const renderClaudeCodeSkillCard = (skill: ClaudeCodeSkill) => {
    const mdKey = skill.path;
    const mdLoading = !!localMdLoading[mdKey];
    const mdText = localMdByPath[mdKey];
    const isActive = skill.active !== false;
    const isWorkspace = skill.origin === 'workspace';
    const accent = isWorkspace ? palette.linkForeground : (palette.successForeground ?? palette.linkForeground);
    return (
      <SkillEntryCard
        key={`${skill.origin}-${skill.name}`}
        palette={palette}
        accent={accent}
        icon={isWorkspace
          ? <FolderOpenOutlined style={{ fontSize: 18 }} />
          : <CloudSyncOutlined style={{ fontSize: 18 }} />}
        title={skill.name}
        tags={
          <>
            <Tag color={isWorkspace ? 'blue' : 'geekblue'} style={{ margin: 0 }}>
              {t(`skillManagement.claudeOrigin.${skill.origin}`)}
            </Tag>
            {!isActive ? <Tag color="warning" style={{ margin: 0 }}>{t('skillManagement.claudeSkillInactive')}</Tag> : null}
          </>
        }
        description={skill.description || t('skillManagement.noDescription')}
        actions={
          <>
            <Tooltip title={isActive ? t('skillManagement.disable') : t('skillManagement.enable')}>
              <Switch checked={isActive} onChange={() => handleSetClaudeSkillActive(skill.name, skill.origin, !isActive)} size="small" />
            </Tooltip>
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  ...(skill.hasSkillMd
                    ? [{
                      key: 'doc',
                      label: t('skillManagement.viewDocumentation'),
                      icon: <BookOutlined />,
                      onClick: () => handleOpenLocalSkillMarkdown(skill.path),
                    }]
                    : []),
                  {
                    key: 'folder',
                    label: t('skillManagement.openFolder'),
                    icon: <FolderOpenOutlined />,
                    onClick: () => handleOpenFolder(skill.path),
                  },
                  {
                    key: 'purge',
                    label: t('skillManagement.purgeClaudeSkill'),
                    icon: <DeleteOutlined />,
                    danger: true,
                    onClick: () => handlePurgeClaudeCodeSkill(skill.name, skill.origin),
                  },
                ],
              }}
            >
              <Button type="text" size="small" icon={<MoreOutlined />} aria-label={t('skillManagement.moreActions')} />
            </Dropdown>
          </>
        }
      >
        <SkillDetailCollapse
          panelLabel={t('skillManagement.skillDetails')}
          onPanelOpen={() => ensureLocalSkillMd(skill.path)}
          loading={mdLoading && mdText === undefined}
          borderColor={palette.panelBorder}
        >
          <SkillMarkdownPreview
            content={mdText}
            palette={palette}
            isDark={isDark}
            extraFacts={[
              { label: t('skillManagement.detailPath'), value: <span style={detailValueStyle}>{skill.path}</span> },
              { label: t('skillManagement.detailFiles'), value: <span style={{ fontSize: 12 }}>{skill.files.length ? skill.files.join(', ') : '—'}</span> },
            ]}
          />
        </SkillDetailCollapse>
      </SkillEntryCard>
    );
  };

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

    return (
      <SkillEntryCard
        key={cardKey}
        palette={palette}
        accent={palette.linkForeground}
        icon={<ShopOutlined style={{ fontSize: 18 }} />}
        title={skill.name}
        tags={
          <>
            <Tag color="blue" style={{ margin: 0 }}>{skill.author}</Tag>
            {hasUpdate ? <Tag color="orange" style={{ margin: 0 }}>{t('skillManagement.updateAvailable')}</Tag> : null}
            {alreadyInstalled ? <Tag color="success" style={{ margin: 0 }}>{t('skillManagement.installed')}</Tag> : null}
            {(skill.tags ?? []).slice(0, 4).map(tag => (
              <Tag key={tag} style={{ margin: 0, fontSize: 11 }}>{tag}</Tag>
            ))}
          </>
        }
        description={getDescription(skill)}
        actions={
          hasUpdate ? (
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
              {installing
                ? t('skillManagement.installing')
                : alreadyInstalled
                  ? t('skillManagement.installed')
                  : installTarget === 'agent'
                    ? t('skillManagement.installAgent')
                    : t('skillManagement.installClaudeCode')}
            </Button>
          )
        }
      >
        <SkillDetailCollapse
          panelLabel={t('skillManagement.skillDetails')}
          loading={false}
          borderColor={palette.panelBorder}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {hasUpdate && skill.installedVersion ? (
              <>
                <div>
                  <Text type="secondary" style={detailLabelStyle}>{t('skillManagement.detailInstalledVersion')}</Text>
                  <div style={detailValueStyle}>v{skill.installedVersion}</div>
                </div>
                {skill.version ? (
                  <div>
                    <Text type="secondary" style={detailLabelStyle}>{t('skillManagement.detailLatestVersion')}</Text>
                    <div style={detailValueStyle}>v{skill.version}</div>
                  </div>
                ) : null}
              </>
            ) : !alreadyInstalled && skill.version ? (
              <div>
                <Text type="secondary" style={detailLabelStyle}>{t('skillManagement.skillVersion')}</Text>
                <div style={detailValueStyle}>v{skill.version}</div>
              </div>
            ) : null}
            <div>
              <Text type="secondary" style={detailLabelStyle}>{t('skillManagement.detailRepo')}</Text>
              <div style={detailValueStyle}>{skill.repo}</div>
            </div>
            {(skill.compatibility ?? []).length > 0 ? (
              <div>
                <Text type="secondary" style={{ ...detailLabelStyle, display: 'block', marginBottom: 4 }}>
                  {t('skillManagement.detailCompat')}
                </Text>
                <Space wrap size={[4, 4]}>
                  {(skill.compatibility ?? []).map((c) => (
                    <Tag key={c} style={{ margin: 0 }}>{c}</Tag>
                  ))}
                </Space>
              </div>
            ) : null}
            {skill.skillMdContent ? (
              <SkillMarkdownPreview content={skill.skillMdContent} palette={palette} isDark={isDark} />
            ) : null}
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
      </SkillEntryCard>
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
    const accent = palette.linkForeground;

    return (
      <SkillEntryCard
        key={`vsix-${skill.name}`}
        palette={palette}
        accent={accent}
        icon={<InboxOutlined style={{ fontSize: 18 }} />}
        title={skill.name}
        tags={
          <>
            <Tag color="purple" style={{ margin: 0 }}>{t('skillManagement.vsixTemplateTag')}</Tag>
            {skill.isVersioned && skill.activeVersion
              ? skill.activeVersion.source === 'snapshot'
                ? (
                  <Tag color="orange" style={{ margin: 0 }}>
                    {t('skillManagement.versionSnapshotTag', { id: skill.activeVersion.id })}
                  </Tag>
                )
                : versionTag(skill.activeVersion.id)
              : null}
            {workspaceSynced ? (
              wsActive ? (
                <Tag color="success" style={{ margin: 0 }}>{t('skillManagement.vsixWorkspaceSynced')}</Tag>
              ) : (
                <Tag color="warning" style={{ margin: 0 }}>{t('skillManagement.vsixWorkspaceInactive')}</Tag>
              )
            ) : (
              <Tag style={{ margin: 0 }}>{t('skillManagement.vsixWorkspacePending')}</Tag>
            )}
          </>
        }
        description={skill.description || t('skillManagement.noDescription')}
        actions={
          <>
            <Button
              type="primary"
              size="small"
              icon={<CloudSyncOutlined />}
              loading={vsixSyncLoading.has(skill.name)}
              onClick={() => handleSyncOneBundledClaudeSkill(skill.name)}
            >
              {workspaceSynced ? t('skillManagement.resyncVsixToWorkspace') : t('skillManagement.syncVsixToWorkspace')}
            </Button>
            {workspaceSynced ? (
              <Tooltip title={wsActive ? t('skillManagement.disable') : t('skillManagement.enable')}>
                <Switch checked={wsActive} onChange={() => handleSetClaudeSkillActive(skill.name, 'workspace', !wsActive)} size="small" />
              </Tooltip>
            ) : null}
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  ...(skill.isVersioned
                    ? [
                      {
                        key: 'switch',
                        label: t('skillManagement.switchSkillVersion'),
                        icon: <SyncOutlined />,
                        onClick: () => handleSwitchSkillVersion(),
                      },
                      {
                        key: 'snapshot',
                        label: t('skillManagement.snapshotSkill'),
                        icon: <InboxOutlined />,
                        onClick: () => handleSnapshotSkill(skill.name),
                      },
                    ]
                    : []),
                  ...(skill.hasSkillMd
                    ? [{
                      key: 'doc',
                      label: t('skillManagement.viewDocumentation'),
                      icon: <BookOutlined />,
                      onClick: () => handleOpenLocalSkillMarkdown(displayPath),
                    }]
                    : []),
                  {
                    key: 'folder',
                    label: t('skillManagement.openFolder'),
                    icon: <FolderOpenOutlined />,
                    onClick: () => handleOpenFolder(displayPath),
                  },
                  ...(workspaceSynced
                    ? [{
                      key: 'purge',
                      label: t('skillManagement.purgeClaudeSkill'),
                      icon: <DeleteOutlined />,
                      danger: true,
                      onClick: () => handlePurgeClaudeCodeSkill(skill.name, 'workspace'),
                    }]
                    : []),
                ],
              }}
            >
              <Button type="text" size="small" icon={<MoreOutlined />} aria-label={t('skillManagement.moreActions')} />
            </Dropdown>
          </>
        }
      >
        <SkillDetailCollapse
          panelLabel={t('skillManagement.skillDetails')}
          onPanelOpen={() => ensureLocalSkillMd(displayPath)}
          loading={mdLoading && mdText === undefined}
          borderColor={palette.panelBorder}
        >
          <SkillMarkdownPreview
            content={mdText}
            palette={palette}
            isDark={isDark}
            extraFacts={[
              { label: t('skillManagement.detailPath'), value: <span style={detailValueStyle}>{displayPath}</span> },
              ...(workspaceSynced
                ? [{ label: t('skillManagement.detailFiles'), value: <span style={{ fontSize: 12 }}>{detailFiles.length ? detailFiles.join(', ') : '—'}</span> }]
                : []),
            ]}
          />
        </SkillDetailCollapse>
      </SkillEntryCard>
    );
  };

  const renderMarketplaceBody = (target: MarketplaceTarget) => {
    const isAgent = target === 'agent';
    const errors = isAgent ? agentMarketplaceLoadErrors : claudeMarketplaceLoadErrors;
    const skills = isAgent ? filteredAgentMarketplaceSkills : filteredClaudeMarketplaceSkills;
    const page = isAgent ? agentMarketPage : claudeMarketPage;
    const setPage = isAgent ? setAgentMarketPage : setClaudeMarketPage;
    const slice = isAgent ? agentMarketPageSlice : claudeMarketPageSlice;
    const emptyText = isAgent
      ? t('skillManagement.noMarketplaceSkillsAgent')
      : t('skillManagement.noMarketplaceSkillsClaude');
    const renderCard = isAgent ? renderAgentMarketplaceCard : renderClaudeMarketplaceCard;

    return (
      <>
        {errors.length > 0 && (
          <Alert
            type={skills.length === 0 ? 'warning' : 'info'}
            showIcon
            style={{ marginBottom: SKILL_UI.space.md, borderRadius: SKILL_UI.radius.md }}
            message={t('skillManagement.marketplaceLoadIssues')}
            description={(
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                {errors.map((e, i) => (
                  <li key={i} style={{ marginBottom: 4 }}>{formatMpError(e)}</li>
                ))}
              </ul>
            )}
          />
        )}
        {marketplaceLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : skills.length === 0 ? (
          <Empty description={emptyText} style={{ padding: 40 }}>
            <Button type="primary" icon={<SettingOutlined />} onClick={() => openSourcesModal(target)}>
              {t('skillManagement.openSkillSourcesSettings')}
            </Button>
          </Empty>
        ) : (
          <>
            <div style={cardsGridStyle}>
              {slice.map(renderCard)}
            </div>
            {skills.length > MARKETPLACE_PAGE_SIZE ? (
              <div style={{ marginTop: SKILL_UI.space.lg, display: 'flex', justifyContent: 'flex-end', flexWrap: 'wrap', gap: 8 }}>
                <Pagination
                  size="small"
                  current={page}
                  pageSize={MARKETPLACE_PAGE_SIZE}
                  total={skills.length}
                  onChange={setPage}
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
      </>
    );
  };

  const renderMarketplaceTab = () => (
    <div>
      <TabToolbar
        left={(
          <div>
            <Text strong style={{ fontSize: 14 }}>{t('skillManagement.marketplaceTabTitle')}</Text>
            <Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 4, lineHeight: 1.55 }}>
              {t('skillManagement.marketplaceTabIntro')}
            </Text>
          </div>
        )}
        right={(
          <>
            <Segmented
              size="small"
              value={marketplaceTarget}
              onChange={(value) => setMarketplaceTarget(value as MarketplaceTarget)}
              options={[
                { label: t('skillManagement.marketplaceTargetAgent'), value: 'agent' },
                { label: t('skillManagement.marketplaceTargetClaude'), value: 'claudeCode' },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={handleRefreshMarketplace} loading={marketplaceLoading} size="small">
              {t('skillManagement.refresh')}
            </Button>
          </>
        )}
      />
      <PageSection
        palette={palette}
        icon={<ShopOutlined />}
        title={
          marketplaceTarget === 'agent'
            ? t('skillManagement.marketplaceAgent')
            : t('skillManagement.marketplaceClaude')
        }
        subtitle={
          marketplaceTarget === 'agent'
            ? t('skillManagement.marketplaceAgentHint')
            : t('skillManagement.marketplaceClaudeShort')
        }
      >
        {renderMarketplaceBody(marketplaceTarget)}
      </PageSection>
    </div>
  );

  const renderAgentTab = () => {
    const { builtin: builtinAgentSkills, custom: customSkills, env: envSkills } =
      partitionAgentSkillsBySource(filteredAgentSkills);
    const agentMoreMenuItems: MenuProps['items'] = [
      {
        key: 'scan',
        label: t('skillManagement.scanAgentSkills'),
        icon: <SearchOutlined />,
        onClick: handleScanAgentSkills,
      },
      {
        key: 'import',
        label: t('skillManagement.importSkill'),
        icon: <ImportOutlined />,
        onClick: handleImportAgentSkill,
      },
    ];

    return (
      <div>
        {tabToolbar(
          <div>
            <Text strong style={{ fontSize: 14 }}>{t('skillManagement.agentTabIntroTitle')}</Text>
            <Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 4, lineHeight: 1.55 }}>
              {t('skillManagement.agentBackendRequiredNotice')}
            </Text>
          </div>,
          <>
            <Button type="primary" icon={<ImportOutlined />} onClick={handleImportAgentSkill} size="small">
              {t('skillManagement.importSkill')}
            </Button>
            <Button icon={<ReloadOutlined />} onClick={handleRefreshAgentList} size="small" loading={agentSkillsLoading}>
              {t('skillManagement.refreshList')}
            </Button>
            <Dropdown menu={{ items: agentMoreMenuItems }} trigger={['click']}>
              <Button size="small" icon={<MoreOutlined />}>
                {t('skillManagement.moreActions')}
              </Button>
            </Dropdown>
          </>
        )}
        {agentSkillsLoading ? <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div> : (
          <>
            {builtinAgentSkills.length > 0 &&
              renderAgentSkillSection(
                t('skillManagement.agentBackendSection'),
                t('skillManagement.agentBackendSectionExplain'),
                builtinAgentSkills,
                'built-in',
                <ThunderboltOutlined />
              )}
            {envSkills.length > 0 &&
              renderAgentSkillSection(
                t('skillManagement.agentEnvSection'),
                t('skillManagement.agentEnvSectionExplain'),
                envSkills,
                'env',
                <ApiOutlined />
              )}
            {customSkills.length > 0 &&
              renderAgentSkillSection(
                t('skillManagement.agentRegisteredSection'),
                t('skillManagement.agentRegisteredSectionExplain'),
                customSkills,
                'custom',
                <ToolOutlined />
              )}
            {filteredAgentSkills.length === 0 && (
              <Empty description={t('skillManagement.noAgentSkills')} style={{ padding: 40 }}>
                <Space>
                  <Button type="primary" icon={<ImportOutlined />} onClick={handleImportAgentSkill}>
                    {t('skillManagement.importSkill')}
                  </Button>
                  <Button icon={<SearchOutlined />} onClick={handleScanAgentSkills}>
                    {t('skillManagement.scanAgentSkills')}
                  </Button>
                  <Button icon={<ShopOutlined />} onClick={() => { setMarketplaceTarget('agent'); setActiveTab('marketplace'); }}>
                    {t('skillManagement.goToMarketplace')}
                  </Button>
                </Space>
              </Empty>
            )}
          </>
        )}
      </div>
    );
  };

  const renderClaudeCodeTab = () => {
    const listBlocking =
      (claudeCodeSkillsLoading || builtinSkillsLoading) && claudeUnifiedRows.length === 0;

    const bundledRows = claudeUnifiedRows.filter(r => r.kind === 'bundled');
    const workspaceRows = claudeUnifiedRows.filter(r => r.kind === 'other' && r.skill.origin === 'workspace');
    const globalRows = claudeUnifiedRows.filter(r => r.kind === 'other' && r.skill.origin === 'global');

    const claudeMoreMenuItems: MenuProps['items'] = [
      {
        key: 'sync-all',
        label: t('skillManagement.syncExtensionSkills'),
        icon: <CloudSyncOutlined />,
        onClick: () => handleUpdateExtensionSkills(),
      },
      {
        key: 'presets',
        label: t('skillManagement.editSkillPresets'),
        icon: <SettingOutlined />,
        onClick: () => handleEditSkillPresets(),
      },
    ];

    return (
      <div>
        {tabToolbar(
          <div>
            <Text strong style={{ fontSize: 14 }}>{t('skillManagement.claudeTabIntroTitle')}</Text>
            <Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 4, lineHeight: 1.55 }}>
              {t('skillManagement.claudeTabIntroBody')}
            </Text>
          </div>,
          <>
            <Button type="primary" icon={<ImportOutlined />} onClick={handleImportClaudeCodeSkill} size="small">
              {t('skillManagement.importClaudeSkill')}
            </Button>
            <Dropdown menu={{ items: claudeMoreMenuItems }} trigger={['click']}>
              <Button size="small" icon={<MoreOutlined />}>
                {t('skillManagement.moreActions')}
              </Button>
            </Dropdown>
            <Tooltip title={t('skillManagement.claudeRefreshAll')}>
              <Button
                icon={<ReloadOutlined />}
                onClick={handleRefreshClaudeAll}
                size="small"
                loading={claudeCodeSkillsLoading || bundledPluginsLoading || marketplaceLoading}
                aria-label={t('skillManagement.claudeRefreshAll')}
              />
            </Tooltip>
          </>
        )}
        {listBlocking ? <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div> : (
          <>
            {bundledRows.length > 0 && (
              <PageSection
                palette={palette}
                icon={<InboxOutlined />}
                title={`${t('skillManagement.vsixTemplateSection')} (${bundledRows.length})`}
                subtitle={t('skillManagement.vsixTemplateExplain')}
              >
                <div style={cardsGridStyle}>
                  {bundledRows.map((row) => renderClaudeUnifiedRow(row))}
                </div>
              </PageSection>
            )}
            {bundledPlugins.length > 0 && (
              <PageSection
                palette={palette}
                icon={<AppstoreOutlined />}
                title={`${t('skillManagement.pluginsSection')} (${bundledPlugins.length})`}
              >
                <div style={cardsGridStyle}>
                {bundledPlugins.map((plugin) => (
                  <SkillEntryCard
                    key={plugin.name}
                    palette={palette}
                    accent={palette.linkForeground}
                    icon={<AppstoreOutlined style={{ fontSize: 18 }} />}
                    title={plugin.name}
                    tags={
                      <>
                        {versionTag(plugin.version)}
                        {plugin.author ? <Tag color="blue" style={{ margin: 0 }}>{plugin.author}</Tag> : null}
                        {plugin.skills.length > 0 ? (
                          <Tag icon={<ToolOutlined />} style={{ fontSize: 11, margin: 0 }}>
                            {plugin.skills.length} {t('skillManagement.pluginSkills')}
                          </Tag>
                        ) : null}
                        {plugin.commands.length > 0 ? (
                          <Tag icon={<ThunderboltOutlined />} style={{ fontSize: 11, margin: 0 }}>
                            {plugin.commands.length} {t('skillManagement.pluginCommands')}
                          </Tag>
                        ) : null}
                      </>
                    }
                    description={plugin.description || undefined}
                    hoverable={false}
                  >
                    {(plugin.skills.length > 0 || plugin.commands.length > 0) && (
                      <Collapse ghost size="small">
                        {plugin.skills.length > 0 ? (
                          <Collapse.Panel header={`${t('skillManagement.pluginSkills')} (${plugin.skills.length})`} key="skills">
                            {plugin.skills.map((skill) => (
                              <div
                                key={skill.name}
                                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 12 }}
                              >
                                <ToolOutlined style={{ color: palette.linkForeground, fontSize: 12 }} />
                                <span style={{ fontWeight: 500 }}>{skill.name}</span>
                                {skill.description ? (
                                  <span style={{ color: palette.descriptionForeground }}>— {skill.description}</span>
                                ) : null}
                                {skill.hasSkillMd ? (
                                  <Button
                                    type="link"
                                    size="small"
                                    style={{ fontSize: 11, padding: 0, height: 'auto' }}
                                    onClick={() => {
                                      vscode.postMessage({ type: 'openLocalSkillMarkdown', payload: { skillDir: skill.path } });
                                    }}
                                  >
                                    {t('skillManagement.viewDoc')}
                                  </Button>
                                ) : null}
                              </div>
                            ))}
                          </Collapse.Panel>
                        ) : null}
                        {plugin.commands.length > 0 ? (
                          <Collapse.Panel header={`${t('skillManagement.pluginCommands')} (${plugin.commands.length})`} key="commands">
                            {plugin.commands.map((cmd) => (
                              <div
                                key={cmd.name}
                                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 12 }}
                              >
                                <ThunderboltOutlined style={{ color: palette.linkForeground, fontSize: 12 }} />
                                <code style={{
                                  fontSize: 11,
                                  padding: '1px 6px',
                                  borderRadius: 4,
                                  background: `${palette.linkForeground}15`,
                                  color: palette.linkForeground,
                                }}>
                                  /{cmd.name}
                                </code>
                                {cmd.description ? (
                                  <span style={{ color: palette.descriptionForeground }}>— {cmd.description}</span>
                                ) : null}
                              </div>
                            ))}
                          </Collapse.Panel>
                        ) : null}
                      </Collapse>
                    )}
                  </SkillEntryCard>
                ))}
                </div>
              </PageSection>
            )}
            {workspaceRows.length > 0 && (
              <PageSection
                palette={palette}
                icon={<FolderOpenOutlined />}
                title={`${t('skillManagement.claudeWorkspaceSection')} (${workspaceRows.length})`}
                subtitle={t('skillManagement.claudeWorkspaceExplain')}
              >
                <div style={cardsGridStyle}>
                  {workspaceRows.map((row) => renderClaudeUnifiedRow(row))}
                </div>
              </PageSection>
            )}
            {globalRows.length > 0 && (
              <PageSection
                palette={palette}
                icon={<CloudSyncOutlined />}
                title={`${t('skillManagement.claudeGlobalSection')} (${globalRows.length})`}
                subtitle={t('skillManagement.claudeGlobalExplain')}
              >
                <div style={cardsGridStyle}>
                  {globalRows.map((row) => renderClaudeUnifiedRow(row))}
                </div>
              </PageSection>
            )}
            {claudeUnifiedRows.length === 0 && (
              <Empty description={t('skillManagement.noClaudeCodeSkills')} style={{ padding: 40 }}>
                <Space>
                  <Button type="primary" icon={<ImportOutlined />} onClick={handleImportClaudeCodeSkill}>
                    {t('skillManagement.importClaudeSkill')}
                  </Button>
                  <Button icon={<ShopOutlined />} onClick={() => { setMarketplaceTarget('claudeCode'); setActiveTab('marketplace'); }}>
                    {t('skillManagement.goToMarketplace')}
                  </Button>
                </Space>
              </Empty>
            )}
          </>
        )}
      </div>
    );
  };

  const headerSubtitle = React.useMemo(() => {
    if (activeTab === 'integrations') {
      return t('skillManagement.subtitleIntegrations');
    }
    if (activeTab === 'claudeCode') {
      return t('skillManagement.subtitleClaude');
    }
    if (activeTab === 'marketplace') {
      return t('skillManagement.subtitleMarketplace');
    }
    return t('skillManagement.subtitleAgent');
  }, [activeTab, t]);

  const searchPlaceholder = React.useMemo(() => {
    if (activeTab === 'marketplace') {
      return t('skillManagement.searchMarketplacePlaceholder');
    }
    if (activeTab === 'claudeCode') {
      return t('skillManagement.searchClaudePlaceholder');
    }
    return t('skillManagement.searchAgentPlaceholder');
  }, [activeTab, t]);

  return (
    <ConfigProvider theme={themeConfig}>
      <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
        <Content className="as-page-content" style={{ padding: '20px 22px 28px' }}>
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
                <div style={{ maxHeight: 460, overflow: 'auto', border: `1px solid ${palette.panelBorder}`, borderRadius: SKILL_UI.radius.md }}>
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
                              borderRadius: SKILL_UI.radius.sm,
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
              <ul style={{ margin: '0 0 12px', paddingLeft: 20 }}>
                <li>{t('skillManagement.helpAgentEnable')}</li>
                <li>{t('skillManagement.helpAgentImport')}</li>
                <li>{t('skillManagement.helpAgentScan')}</li>
              </ul>
              <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 16 }}>
                {t('skillManagement.helpAgentZones')}
              </Text>

              <Title level={5}>{t('skillManagement.helpClaudeTabTitle')}</Title>
              <Text style={{ display: 'block', marginBottom: 8 }}>{t('skillManagement.helpClaudeTabDescFull')}</Text>
              <ul style={{ margin: '0 0 12px', paddingLeft: 20 }}>
                <li>{t('skillManagement.helpClaudeSync')}</li>
                <li>{t('skillManagement.helpClaudeToggle')}</li>
                <li>{t('skillManagement.helpClaudeDelete')}</li>
              </ul>
              <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 16 }}>
                {t('skillManagement.helpClaudeZones')}
              </Text>
              <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 16 }}>
                {t('skillManagement.helpVersionManage')}
              </Text>

              <Title level={5}>{t('skillManagement.helpMarketplaceTitle')}</Title>
              <Text style={{ display: 'block', marginBottom: 8 }}>{t('skillManagement.helpMarketplaceDesc')}</Text>
              <ul style={{ margin: '0 0 16px', paddingLeft: 20 }}>
                <li>{t('skillManagement.helpMarketplaceInstall')}</li>
                <li>{t('skillManagement.helpMarketplaceSources')}</li>
                <li>{t('skillManagement.helpMarketplaceUpdate')}</li>
              </ul>

              <Title level={5} style={{ marginTop: 16 }}>{t('skillManagement.helpMcpTitle')}</Title>
              <Text style={{ display: 'block', marginBottom: 8 }}>{t('skillManagement.helpMcpDesc')}</Text>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>{t('skillManagement.helpMcpSync')}</li>
                <li>{t('skillManagement.helpMcpLiterature')}</li>
              </ul>
            </div>
          </Modal>
          <Modal
            open={sourcesModalTarget !== null}
            title={sourcesModalTarget === 'claudeCode'
              ? t('skillManagement.skillSourcesClaudeTitle')
              : t('skillManagement.skillSourcesAgentTitle')}
            onCancel={() => setSourcesModalTarget(null)}
            footer={null}
            width={560}
          >
            {renderSourcesModalContent()}
          </Modal>
          <div style={{ maxWidth: SKILL_UI.maxWidth, margin: '0 auto' }}>
            <div className="as-page-hero" style={heroShellStyle(palette)}>
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: SKILL_UI.space.lg }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={iconBadgeStyle(palette.linkForeground)}>
                    <AppstoreOutlined style={{ fontSize: 18 }} />
                  </span>
                  <div>
                    <Title level={4} style={{ margin: 0 }}>{t('skillManagement.title')}</Title>
                    <Text type="secondary" style={{ fontSize: 12 }}>{headerSubtitle}</Text>
                  </div>
                  <Tooltip title={t('skillManagement.helpTooltip')}>
                    <Button
                      type="text"
                      size="small"
                      icon={<QuestionCircleOutlined />}
                      onClick={() => setHelpModalOpen(true)}
                      style={{ color: palette.linkForeground }}
                    />
                  </Tooltip>
                </div>
                <Space wrap size={8}>
                  <Tooltip title={t('skillManagement.skillSourcesHint')}>
                    <Button
                      size="small"
                      icon={<SettingOutlined />}
                      onClick={() => openSourcesModal(activeTab === 'claudeCode' ? 'claudeCode' : marketplaceTarget === 'claudeCode' && activeTab === 'marketplace' ? 'claudeCode' : 'agent')}
                    >
                      {t('skillManagement.pageSettings')}
                    </Button>
                  </Tooltip>
                  <Tooltip title={t('skillManagement.refreshAll')}>
                    <Button
                      size="small"
                      icon={<ReloadOutlined />}
                      onClick={() => {
                        vscode.postMessage({ type: 'listAgentSkills' });
                        vscode.postMessage({ type: 'listClaudeCodeSkills' });
                        vscode.postMessage({ type: 'listBuiltinSkills' });
                        vscode.postMessage({ type: 'listBundledPlugins' });
                        vscode.postMessage({ type: 'refreshMarketplace' });
                        vscode.postMessage({ type: 'listMcpServers' });
                      }}
                    >
                      {t('skillManagement.refresh')}
                    </Button>
                  </Tooltip>
                </Space>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: SKILL_UI.space.md, marginBottom: SKILL_UI.space.lg }}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveTab('agent')}
                  onKeyDown={(e) => { if (e.key === 'Enter') setActiveTab('agent'); }}
                  style={{ cursor: 'pointer', flex: '1 1 110px', minWidth: 96 }}
                >
                  {statPill(t('skillManagement.statEnabledAgent'), agentSkills.length, palette.successForeground)}
                </div>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveTab('claudeCode')}
                  onKeyDown={(e) => { if (e.key === 'Enter') setActiveTab('claudeCode'); }}
                  style={{ cursor: 'pointer', flex: '1 1 110px', minWidth: 96 }}
                >
                  {statPill(t('skillManagement.statClaude'), claudeUnifiedRows.length)}
                </div>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveTab('marketplace')}
                  onKeyDown={(e) => { if (e.key === 'Enter') setActiveTab('marketplace'); }}
                  style={{ cursor: 'pointer', flex: '1 1 110px', minWidth: 96 }}
                >
                  {statPill(t('skillManagement.statMarketplace'), marketplaceTotalCount, palette.linkForeground)}
                </div>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveTab('integrations')}
                  onKeyDown={(e) => { if (e.key === 'Enter') setActiveTab('integrations'); }}
                  style={{ cursor: 'pointer', flex: '1 1 110px', minWidth: 96 }}
                >
                  {statPill(t('skillManagement.statMcp'), mcpServers.length, palette.linkForeground)}
                </div>
              </div>

              {activeTab !== 'integrations' ? (
                <Search
                  placeholder={searchPlaceholder}
                  allowClear
                  enterButton
                  size="middle"
                  value={searchInput}
                  onChange={e => setSearchInput(e.target.value)}
                />
              ) : null}
            </div>
            <Tabs
              activeKey={activeTab}
              onChange={(key) => setActiveTab(key as SkillTab)}
              type="card"
              size="small"
              tabBarStyle={{ marginBottom: 14 }}
              items={[
                {
                  key: 'agent',
                  label: renderTabTitle(
                    <RobotOutlined />,
                    t('skillManagement.agentSkillsTab'),
                    String(agentSkills.length)
                  ),
                  children: renderAgentTab(),
                },
                {
                  key: 'claudeCode',
                  label: renderTabTitle(
                    <ThunderboltOutlined />,
                    t('skillManagement.claudeCodeSkillsTab'),
                    String(claudeUnifiedRows.length)
                  ),
                  children: renderClaudeCodeTab(),
                },
                {
                  key: 'marketplace',
                  label: renderTabTitle(
                    <ShopOutlined />,
                    t('skillManagement.marketplaceTab'),
                    String(marketplaceTotalCount)
                  ),
                  children: renderMarketplaceTab(),
                },
                {
                  key: 'integrations',
                  label: renderTabTitle(
                    <ApiOutlined />,
                    t('skillManagement.integrationsTab'),
                    String(mcpServers.length)
                  ),
                  children: (
                    <McpIntegrationsPanel
                      vscode={vscode}
                      palette={palette}
                      servers={mcpServers}
                      presets={mcpPresets}
                      loading={mcpLoading}
                      probeById={mcpProbeById}
                      probingId={mcpProbingId}
                      onRefresh={() => setMcpLoading(true)}
                      onProbeStart={(id) => setMcpProbingId(id)}
                    />
                  ),
                },
              ]}
            />
          </div>
        </Content>
      </Layout>
    </ConfigProvider>
  );
};
