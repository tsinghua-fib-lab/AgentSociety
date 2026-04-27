/**
 * 技能管理 Webview 类型定义
 * 
 * 两种 Skill 类型：
 * 1. Agent Skills - Agent 运行时使用，安装到 {workspace}/custom/skills/
 * 2. Claude Code Skills - Claude Code IDE 使用，安装到 .claude/skills/
 */

export interface VSCodeAPI {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

// ============ Agent Skills（后端管理，Agent 运行时） ============

export interface AgentSkill {
  name: string;
  description: string;
  source: 'builtin' | 'custom' | string; // builtin | custom | env:xxx
  enabled: boolean;
  path: string;
  has_skill_md: boolean;
  script: string;
  requires: string[];
}

// ============ Claude Code Skills（IDE 使用） ============

export interface ClaudeCodeSkill {
  name: string;
  path: string;
  hasSkillMd: boolean;
  description?: string;
  files: string[];
  origin: 'workspace' | 'global';
  /** false：目录在 .agentsociety-disabled-skills 保管区，Claude 不会当技能加载 */
  active?: boolean;
}

// ============ Built-in Skills（插件自带，只读） ============

export interface BuiltinSkill {
  name: string;
  path: string;
  hasSkillMd: boolean;
  description?: string;
}

// ============ Marketplace Skills（从 GitHub 仓库获取） ============

export interface SkillCategory {
  id: string;
  name: string;
  nameZh: string;
  icon: string;
}

/** 市场源配置（支持多平台） */
export interface SkillSourceConfig {
  owner: string;
  repo: string;
  branch?: string;
  skillsPath?: string;
  /** 平台类型，默认 github */
  platform?: 'github' | 'gitlab' | 'gitee';
  /** GitLab/Gitee 自定义域名（自托管时使用） */
  baseUrl?: string;
}

export interface MarketplaceSkill {
  id: string;
  name: string;
  description: string;
  descriptionZh?: string;
  category: string;
  author: string;
  repo: string;
  branch?: string;
  path: string;
  tags: string[];
  compatibility: string[];
  version?: string;
  homepage?: string;
  installTarget: 'agent' | 'claudeCode';
  // 新增：已安装状态
  installedVersion?: string;      // 本地已安装版本
  updateAvailable?: boolean;      // 是否有更新可用
  skillMdContent?: string;        // 远程 SKILL.md 内容（用于预览）
}

export type MarketplaceLoadError =
  | { code: 'NO_SKILL_SOURCES'; channel: 'agent' | 'claude' }
  | { code: 'NETWORK'; message: string }
  | { code: 'GITHUB_SOURCE_FAILED'; source: string; message: string };

export interface MarketplaceLoadPayload {
  skills: MarketplaceSkill[];
  errors: MarketplaceLoadError[];
}

export interface MarketplaceChannelsPayload {
  agent: MarketplaceLoadPayload;
  claude: MarketplaceLoadPayload;
}

export interface SkillSource {
  name: string;
  owner: string;
  repo: string;
  branch?: string;
  path?: string;
  skillType: 'agent' | 'claudeCode';
}

// ============ 安装相关 ============

export interface InstalledSkill {
  id: string;
  name: string;
  path: string;
  installedAt: string;
  source?: 'marketplace' | 'local';
  skillType?: 'agent' | 'claudeCode';
}

export interface InstallProgress {
  skillId: string;
  status: 'pending' | 'downloading' | 'installing' | 'completed' | 'failed';
  message?: string;
  error?: string;
}

export interface AgentSkillDetailPayload {
  success: boolean;
  name: string;
  description: string;
  source: string;
  enabled: boolean;
  path: string;
  script: string;
  requires: string[];
  skill_md: string;
}

// ============ 整体状态 ============

export interface SkillManagementState {
  activeTab: 'agent' | 'agentMarketplace' | 'claudeCode' | 'builtin';
  // Agent Skills（后端管理）
  agentSkills: AgentSkill[];
  agentSkillsLoading: boolean;
  // Claude Code Skills
  claudeCodeSkills: ClaudeCodeSkill[];
  claudeCodeSkillsLoading: boolean;
  // Built-in Skills
  builtinSkills: BuiltinSkill[];
  builtinSkillsLoading: boolean;
  // Marketplace
  agentMarketplaceSkills: MarketplaceSkill[];
  claudeCodeMarketplaceSkills: MarketplaceSkill[];
  marketplaceLoading: boolean;
  marketplaceError: string | null;
  // 市场源配置
  agentSkillSources: SkillSourceConfig[];
  claudeSkillSources: SkillSourceConfig[];
  skillSourcesLoading: boolean;
  // 通用
  isLoading: boolean;
  error: string | null;
}

// ============ 消息类型 ============

export interface ExtensionMessage {
  type:
  | 'ready'
  // Agent Skills
  | 'listAgentSkills'
  | 'enableAgentSkill'
  | 'disableAgentSkill'
  | 'reloadAgentSkill'
  | 'removeAgentSkill'
  | 'fetchAgentSkillDetail'
  | 'fetchLocalSkillMarkdown'
  | 'importAgentSkill'
  | 'importClaudeCodeSkill'
  // Claude Code Skills
  | 'listClaudeCodeSkills'
  | 'openClaudeCodeSkill'
  | 'deleteClaudeCodeSkill'
  // Built-in Skills
  | 'listBuiltinSkills'
  | 'scanAgentSkills'
  | 'refreshMarketplace'
  | 'updateExtensionSkills'
  | 'openAgentSkillDoc'
  | 'openLocalSkillMarkdown'
  // Marketplace
  | 'installAgentSkill'
  | 'installClaudeCodeSkill'
  | 'openSkillFolder'
  | 'openExternal'
  | 'openSkillSourcesSettings'
  | 'openClaudeSkillSourcesSettings'
  | 'syncOneClaudeSkillFromVsix'
  | 'setClaudeSkillActive'
  | 'purgeClaudeCodeSkill'
  // 市场源配置
  | 'getSkillSources'          // 获取市场源配置
  | 'saveSkillSources'         // 保存市场源配置
  // 更新差异预览
  | 'getSkillUpdateDiff'       // 获取技能更新差异
  | 'confirmSkillUpdate';      // 确认更新技能
  payload?: unknown;
}

export interface WebviewMessage {
  type:
  // Agent Skills
  | 'agentSkillsLoaded'
  | 'agentSkillEnabled'
  | 'agentSkillDisabled'
  | 'agentSkillReloaded'
  | 'agentSkillRemoved'
  | 'agentSkillImported'
  | 'agentSkillDetailLoaded'
  | 'localSkillMarkdownLoaded'
  | 'skillDetailError'
  // Claude Code Skills
  | 'claudeCodeSkillsLoaded'
  | 'claudeCodeSkillImported'
  | 'claudeCodeSkillDeleted'
  // Built-in Skills
  | 'builtinSkillsLoaded'
  // Marketplace
  | 'marketplaceSkillsLoaded'
  | 'installProgress'
  | 'installComplete'
  | 'installFailed'
  // 更新相关
  | 'skillUpdateDiffLoaded'
  | 'skillUpdateDiffError'
  // 市场源配置
  | 'skillSourcesLoaded'       // 市场源配置加载完成
  | 'skillSourcesSaved'        // 市场源配置保存完成
  | 'skillSourcesError'        // 市场源配置操作错误
  // 通用
  | 'error';
  payload?: unknown;
}

// ============ 更新差异预览 ============

export interface SkillFileDiff {
  path: string;                   // 文件相对路径
  status: 'added' | 'deleted' | 'modified';
  hunks: DiffHunk[];              // diff 块
}

export interface DiffHunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: string[];                // diff 行 (以 +/-/空格 开头)
}

export interface SkillUpdateDiff {
  skillId: string;
  skillName: string;
  localVersion: string;
  remoteVersion: string;
  filesAdded: string[];
  filesDeleted: string[];
  filesModified: string[];
  fileDiffs: SkillFileDiff[];
  changelog?: string;             // 可选的更新日志
}

// ============ SKILL.md Frontmatter ============

export interface SkillFrontmatter {
  name?: string;
  description?: string;
  descriptionZh?: string;
  version?: string;
  author?: string;
  tags?: string[];
  priority?: number;
  requires?: string[];
  provides?: string[];
}

// ============ 原始配置类型（用于类型安全解析） ============

export interface RawSkillSourceConfig {
  owner?: unknown;
  repo?: unknown;
  branch?: unknown;
  skillsPath?: unknown;
  path?: unknown;  // 别名
  platform?: unknown;
  baseUrl?: unknown;
}
