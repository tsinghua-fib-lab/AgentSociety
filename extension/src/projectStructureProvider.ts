/**
 * 项目结构提供者 (Project Structure Provider)
 *
 * 这个文件实现了VSCode左侧边栏的树形视图，用于显示研究项目的层次结构。
 *
 * VSCode插件开发核心概念：
 * 1. TreeDataProvider: 实现这个接口可以创建自定义的树形视图
 * 2. TreeItem: 树形视图中的每个节点都是一个TreeItem
 * 3. FileSystemWatcher: 监听文件系统变化，实现实时更新
 * 4. EventEmitter: VSCode的事件系统，用于通知视图更新
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，注册TreeView和命令
 * - @extension/src/apiClient.ts - 调用后端API（初始化工作区、模块扫描等）
 * - @extension/src/workspaceManager.ts - 工作区状态管理
 *
 * 后端API：
 * - @packages/agentsociety2/agentsociety2/backend/routers/custom.py - /api/v1/custom/*
 * - @packages/agentsociety2/agentsociety2/backend/routers/modules.py - /api/v1/modules/*
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { localize } from './i18n';
import { ApiClient } from './apiClient';
import { WorkspaceManager } from './workspaceManager';

/**
 * ProjectItem - 项目树视图中的单个节点
 * 
 * 继承自 vscode.TreeItem，这是VSCode树形视图的基础类。
 * 每个节点可以显示标签、图标，并且可以展开/折叠。
 */
export class ProjectItem extends vscode.TreeItem {
  // Additional properties for experiment context
  public hypothesisId?: string;
  public experimentId?: string;
  // Custom module properties
  public isCustom?: boolean;
  public moduleType?: string;
  public className?: string;

  /**
   * 构造函数
   * @param label - 节点显示的文本标签
   * @param collapsibleState - 节点的折叠状态：
   *   - Collapsed: 可以展开（有子节点）
   *   - Expanded: 已展开
   *   - None: 没有子节点，不能展开
   * @param type - 节点类型，用于区分不同类型的项目项（用于上下文菜单等）
   * @param filePath - 可选的文件路径，如果提供，点击节点会打开该文件
   */
  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly type: 'initWorkspace' | 'configureEnv' | 'fixWorkspace' | 'aiChat' | 'topic' | 'hypothesis' | 'experiment' | 'paper' | 'file' | 'papers' | 'userdata' | 'prefillParams' | 'prefillParamsGroup' | 'prefillParamsEnv' | 'prefillParamsAgent' | 'settings' | 'custom' | 'customScan' | 'customTest' | 'customClean' | 'customAgentItem' | 'customEnvItem' | 'customAgentsGroup' | 'customEnvsGroup' | 'customWorkspace' | 'presentation' | 'presentationHypothesis' | 'presentationExperiment' | 'synthesis' | 'reportHtml' | 'reportMd' | 'skillManagement' | 'datasets' | 'datasetItem' | 'paperPdfGroup' | 'paperMdGroup' | 'paperJsonGroup' | 'pidJson' | 'experimentInitGroup' | 'experimentRunGroup' | 'projectStats' | 'projectStatsMetric',
    public readonly filePath?: string
  ) {
    // 调用父类构造函数，初始化树节点
    super(label, collapsibleState);

    // tooltip: 鼠标悬停时显示的提示信息
    this.tooltip = filePath || label;

    // 获取文件扩展名（用于图标和命令设置；path.extname 对 a.b.md 等更可靠）
    const ext = filePath
      ? path.extname(filePath).replace(/^\./, '').toLowerCase()
      : '';

    // 检查是否为 markdown 文件（用于后续的 contextValue 和命令设置）
    const isMarkdown = ext === 'md';

    // 检查是否为 JSON 文件
    const isJson = ext === 'json';

    // 检查是否为 Python 文件
    const isPython = ext === 'py';

    // 检查是否为 YAML 文件
    const isYaml = ext === 'yaml' || ext === 'yml';

    // contextValue: 用于上下文菜单的条件判断
    // 例如：当contextValue为'hypothesis'时，可以显示特定的右键菜单项
    // 对于 markdown 文件，添加 'markdown' 标识以便在右键菜单中显示特定选项
    // 对于 JSON 文件，添加 'json' 标识
    // 对于 YAML 文件，添加 'yaml' 标识
    if (isMarkdown) {
      this.contextValue = `${type} markdown`;
    } else if (isJson) {
      this.contextValue = `${type} json`;
    } else if (isYaml) {
      this.contextValue = `${type} yaml`;
    } else {
      this.contextValue = type;
    }

    // 根据节点类型设置不同的图标
    // ThemeIcon是VSCode内置的图标系统，使用Codicons图标库
    const iconMap: { [key: string]: string } = {
      'initWorkspace': 'add',      // 加号图标，初始化工作区
      'configureEnv': 'gear',      // 齿轮图标，配置环境变量
      'fixWorkspace': 'tools',     // 工具图标，修复工作区
      'aiChat': 'comment-discussion',  // 聊天气泡图标，AI Chat
      'topic': 'book',           // 书籍图标，表示研究话题
      'hypothesis': 'lightbulb',  // 灯泡图标，表示假设
      'experiment': 'beaker',     // 烧杯图标，表示实验
      'papers': 'file-directory', // 文献库
      'userdata': 'database',     // 数据库图标，表示用户数据
      'datasets': 'database',     // 数据集根目录图标
      'datasetItem': 'folder',    // 单个数据集图标
      'prefillParams': 'settings', // 设置图标，表示预填充参数
      'prefillParamsGroup': 'server-environment', // 环境与智能体：运行环境/工作负荷
      'prefillParamsEnv': 'symbol-namespace', // 命名空间图标，表示环境模块预置参数
      'prefillParamsAgent': 'symbol-interface', // 接口图标，表示智能体类预置参数
      'settings': 'gear', // 齿轮设置图标，表示配置设置
      'custom': 'extensions', // 自定义模块根图标
      'customWorkspace': 'folder', // custom/ 目录节点图标
      'customScan': 'search', // 搜索图标，扫描
      'customTest': 'debug-start', // 播放图标，测试
      'customAgentItem': 'symbol-class', // 自定义Agent图标
      'customEnvItem': 'symbol-namespace', // 自定义环境模块图标
      'customAgentsGroup': 'folder', // Agents组图标
      'customEnvsGroup': 'folder', // Envs组图标
      'presentation': 'folder', // 分析报告根图标
      'presentationHypothesis': 'folder', // 假设文件夹
      'presentationExperiment': 'folder', // 实验文件夹
      'synthesis': 'file-text', // 综合报告图标
      'reportHtml': 'file-code', // HTML 报告图标
      'reportMd': 'file-text', // Markdown 报告图标
      'skillManagement': 'extensions', // 技能管理（打开面板）
      'paperPdfGroup': 'file-directory', // PDF 文献组
      'paperMdGroup': 'file-directory', // Markdown 笔记组
      'paperJsonGroup': 'file-directory', // JSON 文件组
      'pidJson': 'info', // 进程状态图标
      'experimentInitGroup': 'settings-gear', // 实验配置文件组
      'experimentRunGroup': 'graph-line', // 实验运行结果组
      'projectStats': 'graph', // 项目统计概览
      'projectStatsMetric': 'primitive-dot', // 拆行展示的统计子行
    };

    // 对于 paper 和 file 类型，根据文件扩展名设置图标
    let iconId: string;
    let isDirectoryPath = false;
    if (filePath) {
      try {
        isDirectoryPath = fs.existsSync(filePath) && fs.statSync(filePath).isDirectory();
      } catch {
        isDirectoryPath = false;
      }
    }

    if ((type === 'paper' || type === 'file') && isDirectoryPath) {
      // 目录节点应始终显示为文件夹，避免误显示为白色文件图标
      iconId = 'folder';
    } else if (type === 'paper' || type === 'file') {
      // 根据文件扩展名设置图标
      const fileIconMap: { [key: string]: string } = {
        'pdf': 'file-pdf',
        'md': 'markdown',
        'json': 'json',
        'py': 'python',
        'yaml': 'code',
        'yml': 'code',
        'html': 'browser',
        'csv': 'table',
        'txt': 'file-text',
        'db': 'database',
        'sqlite': 'database',
        'png': 'file-media',
        'jpg': 'file-media',
        'jpeg': 'file-media',
        'gif': 'file-media',
      };
      iconId = (ext && fileIconMap[ext]) || 'file-text';
    } else {
      iconId = iconMap[type] || 'file';
    }

    // ThemeIcon的构造函数在类型定义中是私有的，但运行时可用
    // 使用类型断言绕过TypeScript的类型检查
    this.iconPath = new (vscode.ThemeIcon as any)(iconId);

    // 关键节点使用语义化颜色，提升树视图可读性
    if (type === 'skillManagement') {
      this.iconPath = makeThemeIcon('extensions', 'charts.blue');
    } else if (type === 'experiment') {
      this.iconPath = makeThemeIcon('beaker', 'charts.blue');
    } else if (type === 'projectStats') {
      this.iconPath = makeThemeIcon('graph', 'charts.blue');
    } else if (type === 'projectStatsMetric') {
      this.iconPath = makeThemeIcon('primitive-dot', 'descriptionForeground');
    } else if (type === 'prefillParamsGroup') {
      this.iconPath = makeThemeIcon('server-environment', 'charts.blue');
    }

    // paper / file：磁盘上存在的路径交由「文件图标主题」绘制（Markdown、JSON 等与资源管理器一致）
    if (
      filePath &&
      (type === 'paper' || type === 'file') &&
      fs.existsSync(filePath)
    ) {
      this.resourceUri = vscode.Uri.file(filePath);
      this.iconPath = undefined;
    }

    // 如果提供了文件路径，设置点击命令
    // 当用户点击这个节点时，会执行相应的命令打开文件
    if (filePath) {
      if (type === 'reportHtml' || (ext === 'html' && (type === 'presentationExperiment' || type === 'synthesis'))) {
        // HTML 报告文件使用默认浏览器打开（不依赖 Live Preview 扩展）
        this.command = {
          command: 'livePreview.start.preview.atFile',
          title: '打开 HTML 报告',
          arguments: [vscode.Uri.file(filePath)]
        };
      } else if (type === 'reportMd' && isMarkdown) {
        // Markdown 报告默认以预览模式打开
        this.command = {
          command: 'markdown.showPreview',
          title: '打开预览',
          arguments: [vscode.Uri.file(filePath)]
        };
      } else if (isMarkdown) {
        // Markdown 文件默认以预览模式打开
        this.command = {
          command: 'markdown.showPreview',  // VSCode内置命令：预览 Markdown 文件
          title: '打开预览',
          arguments: [vscode.Uri.file(filePath)]  // 传递文件URI作为参数
        };
      } else if (isJson) {
        // JSON 文件：检查是否有专门的自定义编辑器
        const fileName = path.basename(filePath);
        const parentDir = path.basename(path.dirname(filePath));
        const hasCustomEditor =
          fileName === 'SIM_SETTINGS.json' ||
          (fileName === 'init_config.json' && parentDir === 'init');

        if (hasCustomEditor) {
          // 有自定义编辑器的文件：让 VSCode 自动选择
          this.command = {
            command: 'vscode.open',
            title: '打开文件',
            arguments: [vscode.Uri.file(filePath)]
          };
        } else {
          // 其他 JSON 文件：使用通用可视化查看器
          this.command = {
            command: 'aiSocialScientist.viewJsonFile',
            title: '查看 JSON',
            arguments: [filePath]
          };
        }
      } else if (isYaml) {
        // YAML 文件：使用通用可视化查看器
        this.command = {
          command: 'aiSocialScientist.viewYamlFile',
          title: '查看 YAML',
          arguments: [filePath]
        };
      } else {
        // 其他文件使用默认打开方式
        this.command = {
          command: 'vscode.open',  // VSCode内置命令：打开文件
          title: '打开文件',
          arguments: [vscode.Uri.file(filePath)]  // 传递文件URI作为参数
        };
      }
    } else if (type === 'prefillParamsGroup') {
      // 环境与智能体节点：点击时打开统一的管理界面
      this.command = {
        command: 'agentsociety.viewPrefillParams',
        title: '预填充参数',
      };
    } else if (type === 'settings') {
      // 配置设置节点：点击时打开配置页（而非 VS Code 设置）
      this.command = {
        command: 'aiSocialScientist.openConfigPage',
        title: localize('projectStructure.settings')
      };
    }
  }
}

function makeThemeIcon(id: string, colorId?: string): vscode.ThemeIcon {
  if (!colorId) {
    return new (vscode.ThemeIcon as any)(id);
  }
  return new (vscode.ThemeIcon as any)(id, new vscode.ThemeColor(colorId));
}

function getCustomWorkspaceDirIcon(dirName: string): vscode.ThemeIcon | undefined {
  const normalized = dirName.trim().toLowerCase();
  if (normalized === 'agents') {
    return makeThemeIcon('symbol-class', 'charts.blue');
  }
  if (normalized === 'envs') {
    return makeThemeIcon('symbol-namespace', 'charts.orange');
  }
  if (normalized === 'skills') {
    return makeThemeIcon('puzzle', 'charts.green');
  }
  return undefined;
}

/**
 * ProjectStructureProvider - 项目结构数据提供者
 * 
 * 实现 TreeDataProvider<ProjectItem> 接口，这是VSCode树形视图的核心。
 * 
 * 主要职责：
 * 1. 提供树形视图的数据（通过getChildren方法）
 * 2. 响应文件系统变化，自动刷新视图
 * 3. 管理文件监听器和资源清理
 */
export class ProjectStructureProvider implements vscode.TreeDataProvider<ProjectItem> {
  /**
   * _onDidChangeTreeData - 事件发射器
   * 
   * EventEmitter是VSCode事件系统的核心。
   * 当数据发生变化时，通过fire()方法发射事件，视图会自动刷新。
   * 
   * 类型说明：
   * - ProjectItem | undefined | null: 可以传递特定的节点来刷新，或undefined/null刷新整个树
   */
  private _onDidChangeTreeData: vscode.EventEmitter<ProjectItem | undefined | null> = new vscode.EventEmitter<ProjectItem | undefined | null>();

  /**
   * onDidChangeTreeData - 公开的事件属性
   * 
   * VSCode通过这个属性订阅数据变化事件。
   * 当_onDidChangeTreeData.fire()被调用时，VSCode会自动调用getChildren()重新获取数据。
   */
  readonly onDidChangeTreeData: vscode.Event<ProjectItem | undefined | null> = this._onDidChangeTreeData.event;

  // 文件系统监听器 - 监听工作区文件的变化
  private watcher: vscode.FileSystemWatcher | undefined;

  // 当前工作区的路径
  private workspacePath: string = '';

  // 批量操作标志 - 在批量文件操作期间暂停自动刷新
  private batchOperationInProgress: boolean = false;

  // 防抖定时器 - 用于限制刷新频率
  private refreshTimer: NodeJS.Timeout | undefined;

  // 防抖延迟时间（毫秒）- 200ms内多次刷新请求会被合并为一次
  private readonly DEBOUNCE_DELAY = 2000;  // 2秒防抖延迟，避免实验运行时频繁刷新

  // 输出通道 - 用于显示调试日志
  // 用户可以在"输出"面板中查看这些日志
  private outputChannel: vscode.OutputChannel;

  // 自定义模块缓存 - 存储扫描结果
  private customModulesCache: {
    agents: Array<{ type: string; class_name: string; description: string; file_path: string }>;
    envs: Array<{ type: string; class_name: string; description: string; file_path: string }>;
  } = { agents: [], envs: [] };

  // 树结构缓存 - 缓存节点的子项，避免重复的文件系统扫描
  private treeItemCache: Map<string, { items: ProjectItem[]; timestamp: number }> = new Map();

  // 缓存过期时间（5秒）
  private readonly CACHE_TTL = 5000;

  // Workspace Manager - 本地文件操作
  private workspaceManager: WorkspaceManager;

  /**
   * 构造函数
   * @param context - ExtensionContext，VSCode扩展的上下文对象
   * @param apiClient - ApiClient，与后端通信的客户端
   * 
   * ExtensionContext包含：
   * - subscriptions: 用于注册需要清理的资源（监听器、命令等）
   * - extensionPath: 扩展的安装路径
   * - workspaceState/globalState: 存储扩展的状态数据
   */
  constructor(private context: vscode.ExtensionContext, private apiClient: ApiClient) {
    // 创建输出通道，用于显示调试日志
    // 用户可以在VSCode的"输出"面板中选择"AI Social Scientist"查看日志
    this.outputChannel = vscode.window.createOutputChannel('AI Social Scientist');
    this.workspaceManager = new WorkspaceManager(context);
    this.log('ProjectStructureProvider initialized');

    // 设置文件系统监听器
    this.setupFileWatchers();

    // 监听工作区文件夹的变化
    // 当用户添加/删除工作区文件夹时，需要重新设置监听器
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      this.log('Workspace folders changed, reinitializing watchers');
      this.disposeWatcher();  // 清理旧的监听器
      this.setupFileWatchers();  // 重新设置监听器
      this.refresh();  // 刷新视图
    });
  }

  /**
   * 日志记录方法
   * 
   * 将日志同时输出到：
   * 1. 控制台（console.log）- 开发时在调试控制台查看
   * 2. 输出通道（OutputChannel）- 用户可以在VSCode的输出面板查看
   * 
   * @param message - 日志消息
   * @param args - 额外的参数（会被JSON序列化）
   */
  private log(message: string, ...args: any[]): void {
    const timestamp = new Date().toISOString();
    const logMessage = `[${timestamp}] [ProjectStructureProvider] ${message}`;

    // 输出到控制台（开发调试用）
    console.log(logMessage, ...args);

    // 输出到VSCode的输出面板（用户可见）
    this.outputChannel.appendLine(logMessage + (args.length > 0 ? ` ${JSON.stringify(args)}` : ''));
  }

  /**
   * 设置文件系统监听器
   * 
   * FileSystemWatcher可以监听文件系统的变化：
   * - onDidChange: 文件被修改
   * - onDidCreate: 文件被创建
   * - onDidDelete: 文件被删除
   * 
   * 使用RelativePattern可以指定监听的范围
   * 监听模式使用双星号加斜杠加星号表示递归匹配所有文件
   */
  private setupFileWatchers(): void {
    // 获取当前打开的第一个工作区文件夹
    // workspaceFolders是一个数组，支持多根工作区
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this.log('No workspace folder found, skipping file watcher setup');
      return;
    }

    // 保存工作区路径，后续会用到
    this.workspacePath = workspaceFolder.uri.fsPath;
    this.log(`Setting up file watcher for workspace: ${this.workspacePath}`);

    // 创建文件系统监听器
    // RelativePattern用于指定相对于工作区的文件模式
    // **/* 表示匹配所有文件和文件夹（递归）
    this.watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(workspaceFolder, '**/*')
    );

    // 创建辅助函数：检查路径是否应该被忽略
    // 优化：使用更高效的路径匹配，提前检查常见情况
    const shouldIgnorePath = (filePath: string): boolean => {
      // 快速路径：检查路径中是否包含常见忽略目录
      const quickIgnorePatterns = ['node_modules', '.git', '__pycache__', '.venv', 'venv', 'virtualenv', '.pytest_cache', '.mypy_cache', '.ipynb_checkpoints'];
      for (const pattern of quickIgnorePatterns) {
        if (filePath.includes(`/${pattern}/`) || filePath.includes(`\\${pattern}\\`)) {
          return true;
        }
      }

      // 文件扩展名快速检查
      const ext = filePath.toLowerCase();
      const ignoredExts = ['.pyc', '.pyo', '.log', '.ds_store', '.swp', '.swo', '.coverage'];
      for (const ignoredExt of ignoredExts) {
        if (ext.endsWith(ignoredExt)) {
          return true;
        }
      }

      // 更复杂的模式匹配（仅在快速检查失败时执行）
      const complexIgnorePatterns = [
        /\/out\//,         // 编译输出
        /\/dist\//,        // 分发目录
        /\/\.claude\/virtualenv\//,  // 项目虚拟环境
        /\/\.claude\/\.venv\//,     // 项目虚拟环境
        /coverage/,        // 覆盖率报告
        /\.egg-info/,      // Python egg 信息
        /\/\.Python\//,    // Python build 目录
        /\/build\//,       // Python build 目录
        /\/\.ipynb\//,     // Jupyter notebook 数据
      ];
      return complexIgnorePatterns.some(pattern => pattern.test(filePath));
    };

    // 监听文件修改事件
    this.watcher.onDidChange((uri) => {
      if (shouldIgnorePath(uri.fsPath)) {
        return;  // 忽略匹配的路径
      }
      this.log(`File changed: ${uri.fsPath}`);
      this.refresh();
    });

    // 监听文件创建事件
    this.watcher.onDidCreate((uri) => {
      if (shouldIgnorePath(uri.fsPath)) {
        return;  // 忽略匹配的路径
      }
      this.log(`File created: ${uri.fsPath}`);
      this.refresh();
    });

    // 监听文件删除事件
    this.watcher.onDidDelete((uri) => {
      if (shouldIgnorePath(uri.fsPath)) {
        return;  // 忽略匹配的路径
      }
      this.log(`File deleted: ${uri.fsPath}`);
      this.refresh();
    });

    // 将监听器添加到context.subscriptions
    // 这样当扩展停用时，VSCode会自动调用dispose()清理资源
    // 这是VSCode插件开发的最佳实践，避免内存泄漏
    this.context.subscriptions.push(this.watcher);
    this.log('File watcher setup completed');
  }

  /**
   * 清理文件监听器
   * 
   * 当工作区变化或扩展停用时调用，释放资源
   */
  private disposeWatcher(): void {
    if (this.watcher) {
      this.log('Disposing file watcher');
      this.watcher.dispose();  // 停止监听
      this.watcher = undefined;
    }
  }

  /**
   * 生成缓存键
   * @param element - 树节点元素
   * @returns 缓存键字符串
   */
  private getCacheKey(element?: ProjectItem): string {
    if (!element) {
      return 'root';
    }
    return `${element.type}:${element.filePath || element.label || 'unknown'}`;
  }

  /**
   * 从缓存获取节点子项
   * @param element - 树节点元素
   * @returns 缓存的子项或 undefined
   */
  private getCachedChildren(element?: ProjectItem): ProjectItem[] | undefined {
    const key = this.getCacheKey(element);
    const cached = this.treeItemCache.get(key);
    if (cached && Date.now() - cached.timestamp < this.CACHE_TTL) {
      this.log(`Cache hit for key: ${key}`);
      return cached.items;
    }
    return undefined;
  }

  /**
   * 缓存节点子项
   * @param element - 树节点元素
   * @param items - 要缓存的子项
   */
  private setCachedChildren(element: ProjectItem | undefined, items: ProjectItem[]): void {
    const key = this.getCacheKey(element);
    this.treeItemCache.set(key, {
      items,
      timestamp: Date.now()
    });
    // 限制缓存大小，避免内存泄漏
    if (this.treeItemCache.size > 100) {
      const oldestKey = Array.from(this.treeItemCache.keys())[0];
      this.treeItemCache.delete(oldestKey);
    }
  }

  /**
   * 清除缓存
   * @param pattern - 可选的清除模式，如果提供则只清除匹配的缓存
   */
  private clearCache(pattern?: string): void {
    if (pattern) {
      for (const key of this.treeItemCache.keys()) {
        if (key.includes(pattern)) {
          this.treeItemCache.delete(key);
          this.log(`Cleared cache matching pattern: ${pattern}`);
        }
      }
    } else {
      this.treeItemCache.clear();
      this.log('Cleared all cache');
    }
  }

  /**
   * 刷新树形视图
   *
   * 使用防抖（debounce）机制：
   * - 如果200ms内多次调用refresh()，只会在最后一次调用后200ms执行刷新
   * - 这样可以避免频繁刷新，提升性能
   *
   * 工作原理：
   * 1. 第一次调用：启动200ms定时器
   * 2. 200ms内再次调用：清除旧定时器，启动新定时器
   * 3. 200ms内没有新调用：执行刷新（调用fire()）
   */
  refresh(): void {
    // 如果正在进行批量操作，跳过自动刷新
    if (this.batchOperationInProgress) {
      return;
    }

    // 清除缓存以强制重新读取
    this.clearCache();

    // 如果已有待执行的定时器，先清除它
    if (this.refreshTimer) {
      this.log('Debouncing: clearing existing refresh timer');
      clearTimeout(this.refreshTimer);
    }

    // 设置新的定时器
    // setTimeout返回一个定时器ID，用于后续清除
    this.refreshTimer = setTimeout(() => {
      this.log('Executing debounced refresh');

      // fire()方法会触发onDidChangeTreeData事件
      // VSCode监听到这个事件后，会调用getChildren()重新获取数据
      // 传递undefined表示刷新整个树
      this._onDidChangeTreeData.fire(undefined);

      // 清除定时器引用
      this.refreshTimer = undefined;
    }, this.DEBOUNCE_DELAY);
  }

  /**
   * 清理资源
   * 
   * 当扩展停用时，VSCode会调用这个方法。
   * 需要清理所有资源，避免内存泄漏。
   */
  dispose(): void {
    this.log('Disposing ProjectStructureProvider');

    // 清除待执行的刷新定时器
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = undefined;
    }

    // 清理文件监听器
    this.disposeWatcher();

    // 清理输出通道
    this.outputChannel.dispose();

    // 清理 Workspace Manager
    this.workspaceManager.dispose();
  }

  /**
   * 获取树节点的显示信息
   * 
   * VSCode会为每个节点调用这个方法。
   * 由于ProjectItem本身就是TreeItem，直接返回即可。
   * 
   * @param element - 要显示的节点
   * @returns TreeItem对象，包含节点的显示信息
   */
  getTreeItem(element: ProjectItem): vscode.TreeItem {
    return element;
  }

  /**
   * 获取节点的子节点
   * 
   * 这是TreeDataProvider的核心方法。
   * VSCode会调用这个方法获取树形视图的数据：
   * - 当展开节点时，获取该节点的子节点
   * - 当首次加载视图时，element为undefined，返回根节点
   * 
   * 这个方法实现了递归的树形结构：
   * - 根节点（element为undefined）→ 显示"Research Topic"
   * - Topic节点 → 显示假设和论文
   * - Hypothesis节点 → 显示实验和SIM设置
   * - Experiment节点 → 显示初始化结果和运行结果
   * 
   * @param element - 当前节点，undefined表示根节点
   * @returns 子节点数组
   */
  async getChildren(element?: ProjectItem): Promise<ProjectItem[]> {
    // 获取工作区文件夹
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      return [];  // 没有工作区，返回空数组
    }

    const workspacePath = workspaceFolder.uri.fsPath;
    const isChinese = vscode.env.language === 'zh-CN' || vscode.env.language.startsWith('zh');

    // 检查工作区状态
    const topicFile = path.join(workspacePath, 'TOPIC.md');
    const envFile = path.join(workspacePath, '.env');
    const hasEnv = fs.existsSync(envFile);
    const hasTopic = fs.existsSync(topicFile);

    // 检查.env是否已配置（有API key）
    const { EnvManager } = await import('./envManager');
    const envManager = new EnvManager();
    const envConfig = envManager.readEnv();
    const hasApiKey = !!(envConfig.llmApiKey?.trim());

    // 检查工作区目录结构是否完整
    const workspaceHealth = this.checkWorkspaceHealth(workspacePath);
    const needsFix = !workspaceHealth.isHealthy;

    // 根节点：显示研究话题
    // element为undefined表示这是根节点
    if (!element) {
      const items: ProjectItem[] = [];

      // 阶段1: 没有.env文件 -> 提示配置环境变量
      if (!hasEnv) {
        const settingsItem = new ProjectItem(
          localize('projectStructure.settings'),
          vscode.TreeItemCollapsibleState.None,
          'settings',
          undefined
        );
        settingsItem.tooltip = localize('projectStructure.settings.tooltip');
        items.push(settingsItem);
        return items;
      }

      // 阶段2: 有.env但没有配置API key -> 提示配置环境变量
      if (hasEnv && !hasApiKey) {
        const settingsItem = new ProjectItem(
          localize('projectStructure.settings'),
          vscode.TreeItemCollapsibleState.None,
          'settings',
          undefined
        );
        settingsItem.tooltip = localize('projectStructure.settings.tooltip');
        items.push(settingsItem);

        // 显示说明信息
        const infoItem = new ProjectItem(
          localize('projectStructure.apiKeyRequired.label'),
          vscode.TreeItemCollapsibleState.None,
          'initWorkspace',
          undefined
        );
        infoItem.tooltip = localize('projectStructure.apiKeyRequired.tooltip');
        items.push(infoItem);
        return items;
      }

      // 阶段3: 有.env且配置了API key，但没有TOPIC.md -> 提示初始化工作区
      if (hasEnv && hasApiKey && !hasTopic) {
        // 配置设置按钮始终在最上面
        const settingsItem = new ProjectItem(
          localize('projectStructure.settings'),
          vscode.TreeItemCollapsibleState.None,
          'settings',
          undefined
        );
        settingsItem.tooltip = localize('projectStructure.settings.tooltip');
        items.push(settingsItem);

        const initItem = new ProjectItem(
          localize('extension.initProject.button'),
          vscode.TreeItemCollapsibleState.None,
          'initWorkspace',
          undefined
        );
        initItem.command = {
          command: 'aiSocialScientist.initProject',
          title: localize('extension.initProject.commandTitle'),
        };
        initItem.tooltip = localize('extension.initProject.tooltip');
        items.push(initItem);

        return items;
      }

      // 已初始化：配置设置按钮始终在最上面
      const settingsItem = new ProjectItem(
        localize('projectStructure.settings'),
        vscode.TreeItemCollapsibleState.None,
        'settings',
        undefined
      );
      settingsItem.tooltip = localize('projectStructure.settings.tooltip');
      items.push(settingsItem);

      // 添加 AI Chat 入口
      const aiChatItem = new ProjectItem(
        localize('extension.aiChat.label'),
        vscode.TreeItemCollapsibleState.None,
        'aiChat',
        undefined
      );
      aiChatItem.command = {
        command: 'aiSocialScientist.openChat',
        title: localize('extension.aiChat.commandTitle'),
      };
      aiChatItem.tooltip = localize('extension.aiChat.tooltip');
      items.push(aiChatItem);

      // 如果工作区目录结构不完整，显示修复按钮
      if (needsFix) {
        const fixItem = new ProjectItem(
          localize('extension.fixWorkspace.button'),
          vscode.TreeItemCollapsibleState.None,
          'fixWorkspace',
          undefined
        );
        fixItem.command = {
          command: 'aiSocialScientist.fixWorkspace',
          title: localize('extension.fixWorkspace.commandTitle'),
        };
        fixItem.tooltip = localize('extension.fixWorkspace.tooltip');
        items.push(fixItem);
      }

      // 添加项目状态概览（统计信息）
      const statsOverview = this.getProjectStats(workspacePath);
      if (statsOverview) {
        const statsItem = new ProjectItem(
          statsOverview.label,
          vscode.TreeItemCollapsibleState.Collapsed,
          'projectStats',
          undefined
        );
        statsItem.description = statsOverview.description;
        statsItem.tooltip = statsOverview.tooltip;
        if (statsOverview.failedExperiments > 0) {
          statsItem.iconPath = makeThemeIcon('warning', 'charts.red');
        } else if (statsOverview.runningExperiments > 0) {
          statsItem.iconPath = makeThemeIcon('sync', 'charts.yellow');
        } else {
          statsItem.iconPath = makeThemeIcon('graph', 'charts.green');
        }
        items.push(statsItem);
      }

      const skillMgmt = new ProjectItem(
        localize('projectStructure.skillManagement.label'),
        vscode.TreeItemCollapsibleState.None,
        'skillManagement',
        undefined
      );
      skillMgmt.command = {
        command: 'aiSocialScientist.openSkillMarketplace',
        title: localize('projectStructure.skillManagement.commandTitle'),
      };
      skillMgmt.description = localize('projectStructure.skillManagement.description');
      skillMgmt.tooltip = localize('projectStructure.skillManagement.tooltip');
      items.push(skillMgmt);

      const prefillItem = new ProjectItem(
        localize('prefillParams.groupTitle'),
        vscode.TreeItemCollapsibleState.None,
        'prefillParamsGroup',
        undefined
      );
      prefillItem.description = localize('projectStructure.prefillParams.description');
      prefillItem.tooltip = localize('projectStructure.prefillParams.tooltip');
      items.push(prefillItem);

      const topicItem = new ProjectItem(
        localize('projectStructure.researchTopic'),
        vscode.TreeItemCollapsibleState.Expanded,
        'topic',
        topicFile
      );
      topicItem.tooltip = localize('projectStructure.researchTopic.tooltip');
      items.push(topicItem);

      return items;
    }

    if (element.type === 'skillManagement') {
      return [];
    }

    if (element.type === 'projectStats') {
      return this.buildProjectStatsMetricItems(workspacePath);
    }

    // 环境与智能体节点的子节点：已移空（测试功能移至webview内）
    if (element.type === 'prefillParamsGroup') {
      return [];
    }

    // 自定义模块节点的子节点：显示扫描结果（已废弃，保留兼容性）
    if (element.type === 'custom') {
      const items: ProjectItem[] = [];

      // 如果有扫描结果,显示分组
      if (this.customModulesCache.agents.length > 0) {
        items.push(new ProjectItem(
          `${localize('projectStructure.customAgents')} (${this.customModulesCache.agents.length})`,
          vscode.TreeItemCollapsibleState.Collapsed,
          'customAgentsGroup',
          undefined
        ));
      }

      if (this.customModulesCache.envs.length > 0) {
        items.push(new ProjectItem(
          `${localize('projectStructure.customEnvs')} (${this.customModulesCache.envs.length})`,
          vscode.TreeItemCollapsibleState.Collapsed,
          'customEnvsGroup',
          undefined
        ));
      }

      return items;
    }

    // 自定义Agents分组节点：显示所有Agent
    if (element.type === 'customAgentsGroup') {
      return this.customModulesCache.agents.map(agent => {
        const item = new ProjectItem(
          agent.class_name,
          vscode.TreeItemCollapsibleState.None,
          'customAgentItem',
          agent.file_path
        );
        item.tooltip = agent.description;
        item.isCustom = true;
        item.moduleType = 'agent';
        item.className = agent.class_name;
        return item;
      });
    }

    // 自定义Envs分组节点：显示所有环境模块
    if (element.type === 'customEnvsGroup') {
      return this.customModulesCache.envs.map(env => {
        const item = new ProjectItem(
          env.class_name,
          vscode.TreeItemCollapsibleState.None,
          'customEnvItem',
          env.file_path
        );
        item.tooltip = env.description;
        item.isCustom = true;
        item.moduleType = 'env';
        item.className = env.class_name;
        return item;
      });
    }

    // Topic节点的子节点：显示假设和论文
    if (element.type === 'topic') {
      const items: ProjectItem[] = [];

      // 查找所有假设目录（hypothesis_12345格式）
      // findDirectories方法会匹配符合正则表达式的目录名
      const hypothesisDirs = this.findDirectories(workspacePath, /^hypothesis_\d+$/);
      if (hypothesisDirs.length > 0) {
        for (const dir of hypothesisDirs) {
          const hypothesisFile = path.join(dir, 'HYPOTHESIS.md');
          const dirName = path.basename(dir);  // 如hypothesis_12345
          // 提取数字部分，转换为友好的显示名称（如"假设 12345"）
          const match = dirName.match(/^hypothesis_(\d+)$/);

          // 统计实验数量和完成数量
          const experimentDirs = this.findDirectories(dir, /^experiment_\d+$/);
          const totalExperiments = experimentDirs.length;
          let completedExperiments = 0;
          let runningExperiments = 0;
          let failedExperiments = 0;

          for (const expDir of experimentDirs) {
            const pidFile = path.join(expDir, 'run', 'pid.json');
            if (fs.existsSync(pidFile)) {
              try {
                const pidContent = fs.readFileSync(pidFile, 'utf-8');
                const pidData = JSON.parse(pidContent);
                const st = this.normalizeExperimentStatus(pidData.status);
                if (st === 'completed') {
                  completedExperiments++;
                } else if (st === 'running') {
                  runningExperiments++;
                } else if (st === 'failed') {
                  failedExperiments++;
                }
              } catch { void 0; }
            }
          }

          let statusDesc = '';
          if (totalExperiments > 0) {
            const bits: string[] = [`${completedExperiments}/${totalExperiments}`];
            if (runningExperiments > 0) {
              bits.push(`▶${runningExperiments}`);
            }
            if (failedExperiments > 0) {
              bits.push(`✗${failedExperiments}`);
            }
            statusDesc = ` (${bits.join(' ')})`;
          }

          const displayName = match
            ? `${localize('projectStructure.hypothesis')} ${match[1]}${statusDesc}`
            : dirName;  // 如果格式不匹配，使用原目录名

          const item = new ProjectItem(
            displayName,  // 显示为"假设 12345"或"Hypothesis 12345"
            vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
            'hypothesis',
            fs.existsSync(hypothesisFile) ? hypothesisFile : undefined  // 如果存在HYPOTHESIS.md，点击可打开
          );

          // 设置 tooltip 显示详细状态
          if (totalExperiments > 0) {
            item.tooltip = `${localize('projectStructure.experiments')}: ${totalExperiments}\n${localize('projectStructure.completed')}: ${completedExperiments}`;
            if (runningExperiments > 0) {
              item.tooltip += `\n${localize('projectStructure.running')}: ${runningExperiments}`;
            }
            if (failedExperiments > 0) {
              item.tooltip += `\n${localize('projectStructure.statusFailed')}: ${failedExperiments}`;
            }
          }

          items.push(item);
        }
      }

      // 查找papers目录，如果有论文文件，创建一个"文献库"节点
      const papersDir = path.join(workspacePath, 'papers');
      if (fs.existsSync(papersDir)) {
        // 创建一个"文献库"节点，可展开显示所有论文
        items.push(new ProjectItem(
          localize('projectStructure.literature'),  // 显示为"文献库"
          vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
          'papers',  // 节点类型为papers
          undefined  // 文献库节点本身不关联文件
        ));
      }

      // 查找user_data目录，如果存在，创建一个"用户数据"节点
      const userDataDir = path.join(workspacePath, 'user_data');
      if (fs.existsSync(userDataDir)) {
        // 创建一个"用户数据"节点，可展开显示所有文件
        items.push(new ProjectItem(
          localize('projectStructure.userData'),  // 显示为"用户数据"
          vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
          'userdata',  // 节点类型为userdata
          undefined  // 用户数据节点本身不关联文件
        ));
      }

      // 查找datasets目录，如果存在，创建一个"数据集"节点
      const datasetsDir = path.join(workspacePath, 'datasets');
      if (fs.existsSync(datasetsDir)) {
        // 统计本地数据集数量（每个含 metadata.json 的子目录视为一个数据集）
        const datasetCount = fs.readdirSync(datasetsDir)
          .filter(name => {
            const subDir = path.join(datasetsDir, name);
            return fs.statSync(subDir).isDirectory() &&
              fs.existsSync(path.join(subDir, 'metadata.json'));
          }).length;

        const label = datasetCount > 0
          ? `${localize('projectStructure.datasets')} (${datasetCount})`
          : localize('projectStructure.datasets');
        items.push(new ProjectItem(
          label,
          vscode.TreeItemCollapsibleState.Collapsed,
          'datasets',
          undefined
        ));
      }

      // 查找custom目录，如果存在，创建一个"自定义模块"节点
      const customDir = path.join(workspacePath, 'custom');
      if (fs.existsSync(customDir)) {
        // 创建一个"自定义模块"节点，可展开显示子目录
        items.push(new ProjectItem(
          localize('projectStructure.customModules'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'customWorkspace',
          undefined
        ));
      }

      // 查找presentation目录（分析报告）
      const presentationDir = path.join(workspacePath, 'presentation');
      if (fs.existsSync(presentationDir)) {
        items.push(new ProjectItem(
          localize('projectStructure.presentation'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'presentation',
          undefined
        ));
      }

      // 查找synthesis目录（综合报告）
      const synthesisDir = path.join(workspacePath, 'synthesis');
      if (fs.existsSync(synthesisDir)) {
        items.push(new ProjectItem(
          localize('projectStructure.synthesis'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'synthesis',
          undefined
        ));
      }

      return items;
    }

    // Papers节点（文献库）的子节点：按类型分组显示
    if (element.type === 'papers') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const papersDir = path.join(workspacePath, 'papers');
      const items: ProjectItem[] = [];

      if (fs.existsSync(papersDir)) {
        const entries = fs.readdirSync(papersDir).filter(entry => entry !== 'mineru_output');

        // 按类型分类文件
        const pdfFiles: { name: string; path: string }[] = [];
        const mdFiles: { name: string; path: string }[] = [];
        const jsonFiles: { name: string; path: string }[] = [];
        const otherFiles: { name: string; path: string }[] = [];
        const directories: { name: string; path: string; count: number }[] = [];

        for (const entry of entries) {
          const fullPath = path.join(papersDir, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isFile()) {
            const ext = entry.toLowerCase().split('.').pop() || '';
            if (ext === 'pdf') {
              pdfFiles.push({ name: entry, path: fullPath });
            } else if (ext === 'md') {
              mdFiles.push({ name: entry, path: fullPath });
            } else if (ext === 'json') {
              jsonFiles.push({ name: entry, path: fullPath });
            } else {
              otherFiles.push({ name: entry, path: fullPath });
            }
          } else if (stat.isDirectory()) {
            let fileCount = 0;
            try {
              const subEntries = fs.readdirSync(fullPath).filter((sub: string) => sub !== 'mineru_output');
              fileCount = subEntries.filter((sub: string) => {
                const subPath = path.join(fullPath, sub);
                return fs.statSync(subPath).isFile();
              }).length;
            } catch { void 0; }
            directories.push({ name: entry, path: fullPath, count: fileCount });
          }
        }

        // 文献索引文件（特殊处理，置顶显示）
        const literatureIndexFile = jsonFiles.find(f => f.name === 'literature_index.json');
        if (literatureIndexFile) {
          try {
            const content = fs.readFileSync(literatureIndexFile.path, 'utf-8');
            const data = JSON.parse(content);
            const count = data.entries?.length || 0;
            const fileItem = new ProjectItem(
              localize('projectStructure.literatureIndex'),
              vscode.TreeItemCollapsibleState.None,
              'paper',
              literatureIndexFile.path
            );
            fileItem.tooltip = `${localize('projectStructure.literatureIndex')} (${count} ${localize('projectStructure.articles')})`;
            fileItem.description = `(${count} ${localize('projectStructure.articles')})`;
            fileItem.contextValue = 'paper json literatureIndex';
            fileItem.command = {
              command: 'aiSocialScientist.viewLiteratureIndex',
              title: '查看文献索引',
              arguments: [{ filePath: literatureIndexFile.path }]
            };
            items.push(fileItem);
          } catch { void 0; }
        }

        // PDF 文献组
        if (pdfFiles.length > 0) {
          const pdfGroup = new ProjectItem(
            `${localize('projectStructure.pdfFiles')} (${pdfFiles.length})`,
            vscode.TreeItemCollapsibleState.Collapsed,
            'paperPdfGroup',
            papersDir
          );
          (pdfGroup as any).fileList = pdfFiles;
          items.push(pdfGroup);
        }

        // Markdown 笔记组
        if (mdFiles.length > 0) {
          const mdGroup = new ProjectItem(
            `${localize('projectStructure.mdFiles')} (${mdFiles.length})`,
            vscode.TreeItemCollapsibleState.Collapsed,
            'paperMdGroup',
            papersDir
          );
          (mdGroup as any).fileList = mdFiles;
          items.push(mdGroup);
        }

        // 其他 JSON 文件组
        const otherJsonFiles = jsonFiles.filter(f => f.name !== 'literature_index.json');
        if (otherJsonFiles.length > 0) {
          const jsonGroup = new ProjectItem(
            `${localize('projectStructure.jsonFiles')} (${otherJsonFiles.length})`,
            vscode.TreeItemCollapsibleState.Collapsed,
            'paperJsonGroup',
            papersDir
          );
          (jsonGroup as any).fileList = otherJsonFiles;
          items.push(jsonGroup);
        }

        // 其他文件
        for (const file of otherFiles) {
          items.push(new ProjectItem(file.name, vscode.TreeItemCollapsibleState.None, 'paper', file.path));
        }

        // 子目录
        for (const dir of directories) {
          const dirItem = new ProjectItem(
            dir.count > 0 ? `${dir.name} (${dir.count})` : dir.name,
            vscode.TreeItemCollapsibleState.Collapsed,
            'paper',
            dir.path
          );
          dirItem.tooltip = `${dir.name} - ${dir.count} ${localize('projectStructure.files')}`;
          items.push(dirItem);
        }
      }

      return items;
    }

    // 处理paper类型节点：如果是目录，显示其子文件和子目录
    if (element.type === 'paper' && element.filePath) {
      const filePath = element.filePath;
      // 检查是否为目录
      if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
        const items: ProjectItem[] = [];
        // 读取目录内容，忽略mineru_output文件夹
        const entries = fs.readdirSync(filePath).filter(entry => entry !== 'mineru_output');

        for (const entry of entries) {
          const fullPath = path.join(filePath, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isFile()) {
            // 如果是文件，创建文件节点
            items.push(new ProjectItem(
              entry,  // 文件名作为标签
              vscode.TreeItemCollapsibleState.None,  // 文件没有子节点
              'paper',
              fullPath  // 完整文件路径
            ));
          } else if (stat.isDirectory()) {
            // 如果是目录，创建可展开的目录节点
            items.push(new ProjectItem(
              entry,  // 目录名作为标签
              vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
              'paper',  // 使用paper类型
              fullPath  // 存储目录路径，用于获取子节点
            ));
          }
        }

        return items;
      }
    }

    // 处理文献分组节点（PDF/MD/JSON）
    if ((element.type === 'paperPdfGroup' || element.type === 'paperMdGroup' || element.type === 'paperJsonGroup') && (element as any).fileList) {
      const fileList: { name: string; path: string }[] = (element as any).fileList;
      const items: ProjectItem[] = [];

      for (const file of fileList) {
        items.push(new ProjectItem(
          file.name,
          vscode.TreeItemCollapsibleState.None,
          'paper',
          file.path
        ));
      }

      return items;
    }

    // 处理 pid.json 可视化
    if (element.type === 'pidJson' && element.filePath) {
      return []; // pid.json 没有子节点，点击打开可视化面板
    }

    // UserData节点（用户数据）的子节点：显示所有文件
    if (element.type === 'userdata') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const userDataDir = path.join(workspacePath, 'user_data');
      const items: ProjectItem[] = [];

      if (fs.existsSync(userDataDir)) {
        // 读取目录下的所有文件和文件夹，忽略mineru_output文件夹
        const entries = fs.readdirSync(userDataDir).filter(entry => entry !== 'mineru_output');

        for (const entry of entries) {
          const fullPath = path.join(userDataDir, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isFile()) {
            // 如果是文件，创建文件节点
            items.push(new ProjectItem(
              entry,  // 文件名作为标签
              vscode.TreeItemCollapsibleState.None,  // 文件没有子节点
              'file',
              fullPath  // 完整文件路径
            ));
          } else if (stat.isDirectory()) {
            // 如果是目录，创建可展开的目录节点
            // 将目录路径存储在filePath中，用于后续获取子节点
            items.push(new ProjectItem(
              entry,  // 目录名作为标签
              vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
              'file',  // 使用file类型
              fullPath  // 存储目录路径，用于获取子节点
            ));
          }
        }
      }

      return items;
    }

    // Datasets节点（数据集）的子节点：显示每个本地数据集
    if (element.type === 'datasets') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const datasetsDir = path.join(workspaceFolder.uri.fsPath, 'datasets');
      if (!fs.existsSync(datasetsDir)) {
        return [];
      }

      const items: ProjectItem[] = [];
      const entries = fs.readdirSync(datasetsDir);

      for (const entry of entries) {
        const fullPath = path.join(datasetsDir, entry);
        if (!fs.statSync(fullPath).isDirectory()) { continue; }

        const metadataPath = path.join(fullPath, 'metadata.json');
        if (!fs.existsSync(metadataPath)) { continue; }

        // 读取 metadata.json 获取友好名称
        let displayName = entry;
        let description = '';
        try {
          const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf-8'));
          if (metadata.name) { displayName = metadata.name; }
          if (metadata.description) { description = metadata.description; }
          if (metadata.version) { displayName += ` (${metadata.version})`; }
        } catch {
          // metadata 解析失败，使用目录名
        }

        // 如果有 README.md，点击可预览
        const readmePath = path.join(fullPath, 'README.md');

        const item = new ProjectItem(
          displayName,
          vscode.TreeItemCollapsibleState.Collapsed,
          'datasetItem',
          fs.existsSync(readmePath) ? readmePath : undefined
        );
        item.tooltip = description || entry;
        (item as any).datasetDirPath = fullPath;
        items.push(item);
      }

      return items;
    }

    // DatasetItem展开时显示目录内容
    if (element.type === 'datasetItem') {
      const datasetDirPath = (element as any).datasetDirPath;
      if (!datasetDirPath || !fs.existsSync(datasetDirPath) || !fs.statSync(datasetDirPath).isDirectory()) {
        return [];
      }

      const items: ProjectItem[] = [];
      const entries = fs.readdirSync(datasetDirPath);

      for (const entry of entries) {
        const fullPath = path.join(datasetDirPath, entry);
        const stat = fs.statSync(fullPath);

        if (stat.isFile()) {
          const fileItem = new ProjectItem(
            entry,
            vscode.TreeItemCollapsibleState.None,
            'file',
            fullPath
          );
          if (entry.toLowerCase().endsWith('.md')) {
            fileItem.command = {
              command: 'markdown.showPreview',
              title: 'Open Preview',
              arguments: [vscode.Uri.file(fullPath)]
            };
          }
          items.push(fileItem);
        } else if (stat.isDirectory()) {
          items.push(new ProjectItem(
            entry,
            vscode.TreeItemCollapsibleState.Collapsed,
            'file',
            fullPath
          ));
        }
      }

      return items;
    }

    // 处理file类型节点：如果是目录，显示其子文件和子目录
    if (element.type === 'file' && element.filePath) {
      const filePath = element.filePath;
      // 检查是否为目录
      if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
        const items: ProjectItem[] = [];
        // 读取目录内容，忽略mineru_output文件夹
        const entries = fs.readdirSync(filePath).filter(entry => entry !== 'mineru_output');

        for (const entry of entries) {
          const fullPath = path.join(filePath, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isFile()) {
            // 如果是文件，创建文件节点
            items.push(new ProjectItem(
              entry,  // 文件名作为标签
              vscode.TreeItemCollapsibleState.None,  // 文件没有子节点
              'file',
              fullPath  // 完整文件路径
            ));
          } else if (stat.isDirectory()) {
            // 如果是目录，创建可展开的目录节点
            items.push(new ProjectItem(
              entry,  // 目录名作为标签
              vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
              'file',  // 使用file类型
              fullPath  // 存储目录路径，用于获取子节点
            ));
          }
        }

        return items;
      }
    }

    // Custom Workspace节点（custom/目录）的子节点：显示agents和envs
    if (element.type === 'customWorkspace') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const customDir = path.join(workspacePath, 'custom');
      const items: ProjectItem[] = [];

      if (fs.existsSync(customDir)) {
        const entries = fs.readdirSync(customDir).sort((a, b) => {
          const rank = (name: string): number => {
            const normalized = name.toLowerCase();
            if (normalized === 'agents') { return 0; }
            if (normalized === 'envs') { return 1; }
            if (normalized === 'skills') { return 2; }
            return 10;
          };
          const rankDiff = rank(a) - rank(b);
          if (rankDiff !== 0) {
            return rankDiff;
          }
          return a.localeCompare(b);
        });

        for (const entry of entries) {
          const fullPath = path.join(customDir, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isDirectory()) {
            // 创建可展开的目录节点
            const dirItem = new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.Collapsed,
              'file',  // 使用file类型来复用目录展开逻辑
              fullPath
            );
            const semanticIcon = getCustomWorkspaceDirIcon(entry);
            if (semanticIcon) {
              dirItem.iconPath = semanticIcon;
            }
            items.push(dirItem);
          } else if (stat.isFile()) {
            // 创建文件节点
            items.push(new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.None,
              'file',
              fullPath
            ));
          }
        }
      }

      return items;
    }

    // Hypothesis节点的子节点：显示实验和SIM设置
    if (element.type === 'hypothesis') {
      // 获取假设目录的路径
      // element.filePath是HYPOTHESIS.md的路径，dirname获取其所在目录
      const hypothesisDir = path.dirname(element.filePath || '');

      // 提取 hypothesis_id（从目录名 hypothesis_xxx 中提取）
      const hypothesisDirName = path.basename(hypothesisDir);
      const hypothesisMatch = hypothesisDirName.match(/^hypothesis_(\d+)$/);
      const hypothesisId = hypothesisMatch ? hypothesisMatch[1] : undefined;

      // 查找该假设下的所有实验目录（experiment_123格式）
      const experimentDirs = this.findDirectories(hypothesisDir, /^experiment_\d+$/);

      const items: ProjectItem[] = [];

      // 为每个实验目录创建节点
      for (const dir of experimentDirs) {
        const experimentFile = path.join(dir, 'EXPERIMENT.md');
        const dirName = path.basename(dir);  // 如experiment_123
        // 提取数字部分，转换为友好的显示名称（如"实验 123"）
        const match = dirName.match(/^experiment_(\d+)$/);
        const experimentId = match ? match[1] : undefined;

        // 检查实验状态（通过 pid.json），通过 icon/description 呈现而非 emoji 拼接
        let statusKey: 'completed' | 'running' | 'failed' | 'pending' | 'unknown' = 'pending';
        let statusTooltip = '';
        const pidFile = path.join(dir, 'run', 'pid.json');
        if (fs.existsSync(pidFile)) {
          try {
            const pidContent = fs.readFileSync(pidFile, 'utf-8');
            const pidData = JSON.parse(pidContent);
            const status = this.normalizeExperimentStatus(pidData.status);
            if (status === 'completed') {
              statusKey = 'completed';
              statusTooltip = localize('projectStructure.statusCompleted');
            } else if (status === 'running') {
              statusKey = 'running';
              statusTooltip = localize('projectStructure.statusRunning');
            } else if (status === 'failed') {
              statusKey = 'failed';
              statusTooltip = localize('projectStructure.statusFailed');
            } else {
              statusKey = status === 'unknown' ? 'unknown' : 'pending';
              statusTooltip = localize('projectStructure.statusPaused');
            }
          } catch {
            statusKey = 'unknown';
          }
        }

        const displayName = match
          ? `${localize('projectStructure.experiment')} ${match[1]}`
          : dirName;  // 如果格式不匹配，使用原目录名
        const item = new ProjectItem(
          displayName,  // 显示为"实验 123"或"Experiment 123"
          vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
          'experiment',
          fs.existsSync(experimentFile) ? experimentFile : undefined
        );
        if (statusTooltip) {
          item.tooltip = statusTooltip;
        }
        item.description = this.getExperimentStatusLabel(statusKey, isChinese);
        item.iconPath = this.getExperimentStatusIcon(statusKey);
        // Set hypothesis and experiment IDs for replay command
        item.hypothesisId = hypothesisId;
        item.experimentId = experimentId;
        items.push(item);
      }

      // 添加SIM_SETTINGS.json文件节点（如果存在）
      const simSettingsFile = path.join(hypothesisDir, 'SIM_SETTINGS.json');
      if (fs.existsSync(simSettingsFile)) {
        items.push(new ProjectItem(
          localize('projectStructure.simSettings'),  // 显示标签（国际化）
          vscode.TreeItemCollapsibleState.None,  // 文件没有子节点
          'file',
          simSettingsFile
        ));
      }

      return items;
    }

    // Experiment节点的子节点：显示初始化结果和运行结果
    if (element.type === 'experiment') {
      // 获取实验目录的路径
      const experimentDir = path.dirname(element.filePath || '');
      const items: ProjectItem[] = [];

      // 检查init目录（配置文件分组）
      const initDir = path.join(experimentDir, 'init');
      if (fs.existsSync(initDir)) {
        const initFiles = fs.readdirSync(initDir).filter(file => {
          const filePath = path.join(initDir, file);
          return fs.statSync(filePath).isFile();
        });

        if (initFiles.length > 0) {
          // 创建配置文件分组节点
          const configGroup = new ProjectItem(
            isChinese ? '配置文件' : 'Configuration',
            vscode.TreeItemCollapsibleState.Collapsed,
            'experimentInitGroup',
            undefined  // 不传递路径，通过 element 的其他属性获取
          );
          (configGroup as any).initDir = initDir;
          (configGroup as any).hypothesisId = element.hypothesisId;
          (configGroup as any).experimentId = element.experimentId;
          items.push(configGroup);
        }
      }

      // 检查run目录（运行结果分组）
      const runDir = path.join(experimentDir, 'run');
      if (fs.existsSync(runDir)) {
        const runFiles = fs.readdirSync(runDir);
        const hasRunContent = runFiles.some(file => {
          const filePath = path.join(runDir, file);
          return fs.statSync(filePath).isFile();
        });

        if (hasRunContent) {
          // 创建运行结果分组节点
          const runGroup = new ProjectItem(
            isChinese ? '运行结果' : 'Run Results',
            vscode.TreeItemCollapsibleState.Collapsed,
            'experimentRunGroup',
            undefined  // 不传递路径
          );
          (runGroup as any).runDir = runDir;
          (runGroup as any).hypothesisId = element.hypothesisId;
          (runGroup as any).experimentId = element.experimentId;
          items.push(runGroup);
        }
      }

      return items;
    }

    // 实验配置文件分组
    if (element.type === 'experimentInitGroup') {
      const initDir = (element as any).initDir;
      if (!initDir || !fs.existsSync(initDir)) {
        return [];
      }
      const items: ProjectItem[] = [];
      const initFiles = fs.readdirSync(initDir);

      for (const file of initFiles) {
        const filePath = path.join(initDir, file);
        const stat = fs.statSync(filePath);
        if (stat.isFile()) {
          const fileItem = new ProjectItem(
            file,
            vscode.TreeItemCollapsibleState.None,
            'file',
            filePath
          );

          if (file === 'steps.yaml') {
            fileItem.contextValue = 'yaml stepsYaml';
            fileItem.command = {
              command: 'aiSocialScientist.viewStepsYaml',
              title: '查看步骤时间线',
              arguments: [{ filePath: filePath }]
            };
          }

          items.push(fileItem);
        }
      }
      return items;
    }

    // 实验运行结果分组
    if (element.type === 'experimentRunGroup') {
      const runDir = (element as any).runDir;
      if (!runDir || !fs.existsSync(runDir)) {
        return [];
      }
      const items: ProjectItem[] = [];

      // sqlite.db
      const dbFile = path.join(runDir, 'sqlite.db');
      if (fs.existsSync(dbFile)) {
        const item = new ProjectItem(
          localize('projectStructure.resultsDatabase'),
          vscode.TreeItemCollapsibleState.None,
          'file',
          dbFile
        );

        if (element.hypothesisId && element.experimentId) {
          item.command = {
            command: 'aiSocialScientist.openReplay',
            title: localize('projectStructure.openReplay'),
            arguments: [{
              hypothesisId: element.hypothesisId,
              experimentId: element.experimentId,
              filePath: dbFile
            }]
          };
          item.contextValue = 'replayableDatabase';
        }

        items.push(item);
      }

      // experiment_results.json
      const resultsFile = path.join(runDir, 'experiment_results.json');
      if (fs.existsSync(resultsFile)) {
        const resultsItem = new ProjectItem(
          isChinese ? '实验结果' : 'Experiment Results',
          vscode.TreeItemCollapsibleState.None,
          'file',
          resultsFile
        );
        resultsItem.contextValue = 'json experimentResults';
        resultsItem.command = {
          command: 'aiSocialScientist.viewExperimentResults',
          title: '查看实验结果',
          arguments: [{ filePath: resultsFile }]
        };
        items.push(resultsItem);
      }

      // pid.json
      const pidFile = path.join(runDir, 'pid.json');
      if (fs.existsSync(pidFile)) {
        try {
          const pidContent = fs.readFileSync(pidFile, 'utf-8');
          const pidData = JSON.parse(pidContent);
          const status = this.normalizeExperimentStatus(pidData.status);

          const pidItem = new ProjectItem(
            `${localize('projectStructure.experimentStatus')}: ${status}`,
            vscode.TreeItemCollapsibleState.None,
            'pidJson',
            pidFile
          );
          pidItem.iconPath = this.getExperimentStatusIcon(status);
          pidItem.tooltip = `${localize('projectStructure.experimentStatus')}: ${status}\nPID: ${pidData.pid || 'N/A'}\n${localize('projectStructure.startTime')}: ${pidData.start_time || 'N/A'}\n${localize('projectStructure.endTime')}: ${pidData.end_time || 'N/A'}`;
          pidItem.description = pidData.experiment_id || '';
          pidItem.contextValue = 'pidJson';
          pidItem.command = {
            command: 'aiSocialScientist.viewPidStatus',
            title: '查看运行状态',
            arguments: [{ filePath: pidFile }]
          };
          items.push(pidItem);
        } catch { void 0; }
      }

      return items;
    }

    // Presentation节点（分析报告）的子节点：显示所有假设目录
    if (element.type === 'presentation') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const presentationDir = path.join(workspacePath, 'presentation');
      const items: ProjectItem[] = [];

      if (fs.existsSync(presentationDir)) {
        // 读取目录，查找所有hypothesis_*目录
        const entries = fs.readdirSync(presentationDir);
        for (const entry of entries) {
          const fullPath = path.join(presentationDir, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isDirectory() && entry.startsWith('hypothesis_')) {
            // 提取假设ID，转换为友好显示名称
            const match = entry.match(/^hypothesis_(\d+)$/);

            // 统计报告数量
            let reportCount = 0;
            const expDirs = this.findDirectories(fullPath, /^experiment_\d+$/);
            for (const expDir of expDirs) {
              const reportHtml = path.join(expDir, 'report.html');
              const reportZhHtml = path.join(expDir, 'report_zh.html');
              const reportEnHtml = path.join(expDir, 'report_en.html');
              if (fs.existsSync(reportHtml) || fs.existsSync(reportZhHtml) || fs.existsSync(reportEnHtml)) {
                reportCount++;
              }
            }

            const countSuffix = reportCount > 0 ? ` (${reportCount})` : '';
            const displayName = match
              ? `${localize('projectStructure.hypothesis')} ${match[1]}${countSuffix}`
              : entry;
            items.push(new ProjectItem(
              displayName,
              vscode.TreeItemCollapsibleState.Collapsed,
              'presentationHypothesis',
              fullPath
            ));
          }
        }
      }

      return items;
    }

    // PresentationHypothesis节点的子节点：显示所有实验目录
    if (element.type === 'presentationHypothesis' && element.filePath) {
      const items: ProjectItem[] = [];

      if (fs.existsSync(element.filePath) && fs.statSync(element.filePath).isDirectory()) {
        const entries = fs.readdirSync(element.filePath);
        for (const entry of entries) {
          const fullPath = path.join(element.filePath, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isDirectory() && entry.startsWith('experiment_')) {
            // 提取实验ID，转换为友好显示名称
            const match = entry.match(/^experiment_(\d+)$/);
            const displayName = match
              ? `${localize('projectStructure.experiment')} ${match[1]}`
              : entry;
            items.push(new ProjectItem(
              displayName,
              vscode.TreeItemCollapsibleState.Collapsed,
              'presentationExperiment',
              fullPath
            ));
          }
        }
      }

      return items;
    }

    // PresentationExperiment节点的子节点：显示报告文件和数据目录
    if (element.type === 'presentationExperiment' && element.filePath) {
      const items: ProjectItem[] = [];

      if (fs.existsSync(element.filePath) && fs.statSync(element.filePath).isDirectory()) {
        const entries = fs.readdirSync(element.filePath);

        // 按优先级查找报告文件：语言特定版本优先于通用版本
        const reportFiles: { [key: string]: string } = {};
        for (const entry of entries) {
          const fullPath = path.join(element.filePath, entry);
          const stat = fs.statSync(fullPath);
          if (stat.isFile()) {
            reportFiles[entry] = fullPath;
          }
        }

        // 添加中文 HTML 报告
        if (reportFiles['report_zh.html']) {
          const item = new ProjectItem(
            localize('projectStructure.reportHtmlZh'),
            vscode.TreeItemCollapsibleState.None,
            'reportHtml',
            reportFiles['report_zh.html']
          );
          item.command = {
            command: 'livePreview.start.preview.atFile',
            title: 'Open with Live Preview',
            arguments: [vscode.Uri.file(reportFiles['report_zh.html'])]
          };
          items.push(item);
        }

        // 添加英文 HTML 报告
        if (reportFiles['report_en.html']) {
          const item = new ProjectItem(
            localize('projectStructure.reportHtmlEn'),
            vscode.TreeItemCollapsibleState.None,
            'reportHtml',
            reportFiles['report_en.html']
          );
          item.command = {
            command: 'livePreview.start.preview.atFile',
            title: 'Open with Live Preview',
            arguments: [vscode.Uri.file(reportFiles['report_en.html'])]
          };
          items.push(item);
        }

        // 如果没有语言特定版本，添加通用 HTML 报告
        if (!reportFiles['report_zh.html'] && !reportFiles['report_en.html'] && reportFiles['report.html']) {
          const item = new ProjectItem(
            localize('projectStructure.reportHtml'),
            vscode.TreeItemCollapsibleState.None,
            'reportHtml',
            reportFiles['report.html']
          );
          item.command = {
            command: 'livePreview.start.preview.atFile',
            title: 'Open with Live Preview',
            arguments: [vscode.Uri.file(reportFiles['report.html'])]
          };
          items.push(item);
        }

        // 添加中文 Markdown 报告
        if (reportFiles['report_zh.md']) {
          const item = new ProjectItem(
            localize('projectStructure.reportMdZh'),
            vscode.TreeItemCollapsibleState.None,
            'reportMd',
            reportFiles['report_zh.md']
          );
          item.command = {
            command: 'markdown.showPreview',
            title: 'Open Preview',
            arguments: [vscode.Uri.file(reportFiles['report_zh.md'])]
          };
          items.push(item);
        }

        // 添加英文 Markdown 报告
        if (reportFiles['report_en.md']) {
          const item = new ProjectItem(
            localize('projectStructure.reportMdEn'),
            vscode.TreeItemCollapsibleState.None,
            'reportMd',
            reportFiles['report_en.md']
          );
          item.command = {
            command: 'markdown.showPreview',
            title: 'Open Preview',
            arguments: [vscode.Uri.file(reportFiles['report_en.md'])]
          };
          items.push(item);
        }

        // 如果没有语言特定版本，添加通用 Markdown 报告
        if (!reportFiles['report_zh.md'] && !reportFiles['report_en.md'] && reportFiles['report.md']) {
          const item = new ProjectItem(
            localize('projectStructure.reportMd'),
            vscode.TreeItemCollapsibleState.None,
            'reportMd',
            reportFiles['report.md']
          );
          item.command = {
            command: 'markdown.showPreview',
            title: 'Open Preview',
            arguments: [vscode.Uri.file(reportFiles['report.md'])]
          };
          items.push(item);
        }

        // 添加 data 目录（分析数据）
        const dataDir = path.join(element.filePath, 'data');
        if (fs.existsSync(dataDir)) {
          items.push(new ProjectItem(
            localize('projectStructure.analysisData'),
            vscode.TreeItemCollapsibleState.Collapsed,
            'file',
            dataDir
          ));
        }

        // 添加 charts 目录（图表）
        const chartsDir = path.join(element.filePath, 'charts');
        if (fs.existsSync(chartsDir)) {
          items.push(new ProjectItem(
            localize('projectStructure.reportCharts'),
            vscode.TreeItemCollapsibleState.Collapsed,
            'file',
            chartsDir
          ));
        }

        // 添加 assets 目录（资源）
        const assetsDir = path.join(element.filePath, 'assets');
        if (fs.existsSync(assetsDir)) {
          items.push(new ProjectItem(
            localize('projectStructure.reportAssets'),
            vscode.TreeItemCollapsibleState.Collapsed,
            'file',
            assetsDir
          ));
        }
      }

      return items;
    }


    // Synthesis节点（综合报告）的子节点：显示所有综合报告文件
    if (element.type === 'synthesis') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const synthesisDir = path.join(workspacePath, 'synthesis');
      const items: ProjectItem[] = [];

      if (fs.existsSync(synthesisDir)) {
        const entries = fs.readdirSync(synthesisDir);

        // 分组报告：按基础名称和时间戳分组，支持双语版本
        const reportGroups: { [key: string]: { [lang: string]: string } } = {};

        for (const entry of entries) {
          const fullPath = path.join(synthesisDir, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isFile() && entry.startsWith('synthesis_report_')) {
            // 匹配带语言后缀的文件: synthesis_report_YYYYMMDD_HHMMSS_(zh|en).(html|md)
            const langMatch = entry.match(/^synthesis_report_([\d_]+)_(zh|en)\.(html|md)$/);
            // 匹配通用文件: synthesis_report_YYYYMMDD_HHMMSS.(html|md)
            const genericMatch = entry.match(/^synthesis_report_([\d_]+)\.(html|md)$/);

            if (langMatch) {
              const timestamp = langMatch[1];
              const lang = langMatch[2];
              const ext = langMatch[3];
              const key = `${timestamp}.${ext}`;

              if (!reportGroups[key]) {
                reportGroups[key] = {};
              }
              reportGroups[key][lang] = fullPath;
            } else if (genericMatch) {
              const timestamp = genericMatch[1];
              const ext = genericMatch[2];
              const key = `${timestamp}.${ext}`;

              if (!reportGroups[key]) {
                reportGroups[key] = {};
              }
              reportGroups[key]['generic'] = fullPath;
            }
          }
        }

        // 生成显示项：优先显示语言特定版本，如果没有则显示通用版本
        for (const [key, paths] of Object.entries(reportGroups)) {
          const dotIndex = key.lastIndexOf('.');
          if (dotIndex < 0) {
            continue;
          }
          const timestamp = key.slice(0, dotIndex);
          const ext = key.slice(dotIndex + 1);
          const isHtml = ext === 'html';

          if (isHtml) {
            // 中文 HTML
            if (paths.zh) {
              const item = new ProjectItem(
                `${localize('projectStructure.synthesis')} ${timestamp} (${localize('projectStructure.reportHtmlZh')})`,
                vscode.TreeItemCollapsibleState.None,
                'reportHtml',
                paths.zh
              );
              item.command = {
                command: 'livePreview.start.preview.atFile',
                title: 'Open with Live Preview',
                arguments: [vscode.Uri.file(paths.zh)]
              };
              items.push(item);
            }

            // 英文 HTML
            if (paths.en) {
              const item = new ProjectItem(
                `${localize('projectStructure.synthesis')} ${timestamp} (${localize('projectStructure.reportHtmlEn')})`,
                vscode.TreeItemCollapsibleState.None,
                'reportHtml',
                paths.en
              );
              item.command = {
                command: 'livePreview.start.preview.atFile',
                title: 'Open with Live Preview',
                arguments: [vscode.Uri.file(paths.en)]
              };
              items.push(item);
            }

            // 通用 HTML（仅当没有语言特定版本时）
            if (!paths.zh && !paths.en && paths.generic) {
              const item = new ProjectItem(
                `${localize('projectStructure.synthesis')} ${timestamp}`,
                vscode.TreeItemCollapsibleState.None,
                'reportHtml',
                paths.generic
              );
              item.command = {
                command: 'livePreview.start.preview.atFile',
                title: 'Open with Live Preview',
                arguments: [vscode.Uri.file(paths.generic)]
              };
              items.push(item);
            }
          } else {
            // Markdown
            // 中文 MD
            if (paths.zh) {
              const item = new ProjectItem(
                `${localize('projectStructure.synthesis')} ${timestamp} (${localize('projectStructure.reportMdZh')})`,
                vscode.TreeItemCollapsibleState.None,
                'reportMd',
                paths.zh
              );
              item.command = {
                command: 'markdown.showPreview',
                title: 'Open Preview',
                arguments: [vscode.Uri.file(paths.zh)]
              };
              items.push(item);
            }

            // 英文 MD
            if (paths.en) {
              const item = new ProjectItem(
                `${localize('projectStructure.synthesis')} ${timestamp} (${localize('projectStructure.reportMdEn')})`,
                vscode.TreeItemCollapsibleState.None,
                'reportMd',
                paths.en
              );
              item.command = {
                command: 'markdown.showPreview',
                title: 'Open Preview',
                arguments: [vscode.Uri.file(paths.en)]
              };
              items.push(item);
            }

            // 通用 MD（仅当没有语言特定版本时）
            if (!paths.zh && !paths.en && paths.generic) {
              const item = new ProjectItem(
                `${localize('projectStructure.synthesis')} ${timestamp} (${localize('projectStructure.reportMd')})`,
                vscode.TreeItemCollapsibleState.None,
                'reportMd',
                paths.generic
              );
              item.command = {
                command: 'markdown.showPreview',
                title: 'Open Preview',
                arguments: [vscode.Uri.file(paths.generic)]
              };
              items.push(item);
            }
          }
        }
      }

      return items;
    }

    // 其他类型的节点没有子节点
    return [];
  }

  private buildProjectStatsMetricItems(workspacePath: string): ProjectItem[] {
    const overview = this.getProjectStats(workspacePath);
    if (!overview) {
      return [];
    }
    const completionRate =
      overview.totalExperiments > 0
        ? Math.round((overview.completedExperiments / overview.totalExperiments) * 100)
        : 0;
    const rows: ProjectItem[] = [];
    rows.push(
      new ProjectItem(
        localize(
          'projectStructure.experimentStats.lineDone',
          overview.completedExperiments,
          overview.totalExperiments,
          completionRate
        ),
        vscode.TreeItemCollapsibleState.None,
        'projectStatsMetric',
        undefined
      )
    );
    rows.push(
      new ProjectItem(
        localize('projectStructure.experimentStats.lineRun', overview.runningExperiments),
        vscode.TreeItemCollapsibleState.None,
        'projectStatsMetric',
        undefined
      )
    );
    rows.push(
      new ProjectItem(
        localize('projectStructure.experimentStats.lineFailed', overview.failedExperiments),
        vscode.TreeItemCollapsibleState.None,
        'projectStatsMetric',
        undefined
      )
    );
    rows.push(
      new ProjectItem(
        localize('projectStructure.experimentStats.linePending', overview.pendingExperiments),
        vscode.TreeItemCollapsibleState.None,
        'projectStatsMetric',
        undefined
      )
    );
    if (overview.unknownExperiments > 0) {
      rows.push(
        new ProjectItem(
          localize('projectStructure.experimentStats.lineUnknown', overview.unknownExperiments),
          vscode.TreeItemCollapsibleState.None,
          'projectStatsMetric',
          undefined
        )
      );
    }
    return rows;
  }

  /**
   * 获取项目统计概览
   */
  private getProjectStats(
    workspacePath: string,
  ): {
    label: string;
    description: string;
    tooltip: string;
    totalExperiments: number;
    completedExperiments: number;
    runningExperiments: number;
    failedExperiments: number;
    pendingExperiments: number;
    unknownExperiments: number;
  } | null {
    let totalExperiments = 0;
    let completedExperiments = 0;
    let runningExperiments = 0;
    let failedExperiments = 0;
    let unknownExperiments = 0;
    let trackedExperiments = 0;

    // 统计所有假设下的实验
    const hypothesisDirs = this.findDirectories(workspacePath, /^hypothesis_\d+$/);
    for (const hypDir of hypothesisDirs) {
      const experimentDirs = this.findDirectories(hypDir, /^experiment_\d+$/);
      totalExperiments += experimentDirs.length;

      for (const expDir of experimentDirs) {
        const pidFile = path.join(expDir, 'run', 'pid.json');
        if (!fs.existsSync(pidFile)) {
          continue;
        }
        trackedExperiments++;
        try {
          const pidContent = fs.readFileSync(pidFile, 'utf-8');
          const pidData = JSON.parse(pidContent);
          const status = this.normalizeExperimentStatus(pidData.status);
          if (status === 'completed') {
            completedExperiments++;
          } else if (status === 'running') {
            runningExperiments++;
          } else if (status === 'failed') {
            failedExperiments++;
          } else {
            unknownExperiments++;
          }
        } catch {
          unknownExperiments++;
        }
      }
    }

    if (totalExperiments === 0) {
      return null;
    }

    const pendingExperiments = Math.max(totalExperiments - trackedExperiments, 0);
    const completionRate = Math.round((completedExperiments / totalExperiments) * 100);

    const descriptionFull = localize(
      'projectStructure.experimentStats.compact',
      completedExperiments,
      totalExperiments,
      completionRate,
      runningExperiments,
      failedExperiments,
      pendingExperiments
    );

    const descriptionShort = localize(
      'projectStructure.experimentStats.short',
      completedExperiments,
      totalExperiments,
      completionRate
    );

    const tooltipLines: string[] = [
      localize('projectStructure.experimentStats.tooltipTitle'),
      descriptionFull,
      localize('projectStructure.experimentStats.completionRate', completionRate),
      localize('projectStructure.experimentStats.seeTopicHint'),
    ];
    if (unknownExperiments > 0) {
      tooltipLines.push(localize('projectStructure.experimentStats.unknown', unknownExperiments));
    }

    return {
      label: localize('projectStructure.experimentStats.label'),
      description: descriptionShort,
      tooltip: tooltipLines.join('\n'),
      totalExperiments,
      completedExperiments,
      runningExperiments,
      failedExperiments,
      pendingExperiments,
      unknownExperiments,
    };
  }

  private normalizeExperimentStatus(status: unknown): 'completed' | 'running' | 'failed' | 'pending' | 'unknown' {
    if (typeof status !== 'string') {
      return 'unknown';
    }
    const normalized = status.trim().toLowerCase();
    if (normalized === 'completed' || normalized === 'running' || normalized === 'failed') {
      return normalized;
    }
    if (normalized === 'pending' || normalized === 'queued' || normalized === 'created') {
      return 'pending';
    }
    return 'unknown';
  }

  private getExperimentStatusIcon(status: 'completed' | 'running' | 'failed' | 'pending' | 'unknown'): vscode.ThemeIcon {
    switch (status) {
      case 'completed':
        return makeThemeIcon('pass-filled', 'charts.green');
      case 'running':
        return makeThemeIcon('sync', 'charts.yellow');
      case 'failed':
        return makeThemeIcon('error', 'charts.red');
      case 'pending':
        return makeThemeIcon('clock', 'descriptionForeground');
      default:
        return makeThemeIcon('question', 'descriptionForeground');
    }
  }

  private getExperimentStatusLabel(
    status: 'completed' | 'running' | 'failed' | 'pending' | 'unknown',
    isChinese: boolean
  ): string {
    if (isChinese) {
      if (status === 'completed') { return '已完成'; }
      if (status === 'running') { return '运行中'; }
      if (status === 'failed') { return '失败'; }
      if (status === 'pending') { return '待运行'; }
      return '未知';
    }
    if (status === 'completed') { return 'completed'; }
    if (status === 'running') { return 'running'; }
    if (status === 'failed') { return 'failed'; }
    if (status === 'pending') { return 'pending'; }
    return 'unknown';
  }

  /**
   * 查找符合模式的目录
   * 
   * 辅助方法，用于查找符合特定命名模式的目录。
   * 例如：查找所有hypothesis_12345格式的目录。
   * 
   * @param parentDir - 父目录路径
   * @param pattern - 正则表达式，用于匹配目录名
   * @returns 匹配的目录路径数组（已排序）
   */
  private findDirectories(parentDir: string, pattern: RegExp): string[] {
    // 如果父目录不存在，返回空数组
    if (!fs.existsSync(parentDir)) {
      return [];
    }

    // 读取目录内容，忽略mineru_output文件夹
    return fs.readdirSync(parentDir)
      .filter(name => {
        // 忽略mineru_output文件夹
        if (name === 'mineru_output') {
          return false;
        }
        const fullPath = path.join(parentDir, name);
        // 检查是否为目录且名称匹配正则表达式
        return fs.statSync(fullPath).isDirectory() && pattern.test(name);
      })
      .map(name => path.join(parentDir, name))  // 转换为完整路径
      .sort();  // 排序，确保顺序一致
  }

  /**
   * 初始化研究项目
   * 
   * 创建一个新的研究项目，包括：
   * 1. 创建TOPIC.md文件
   * 2. 创建papers目录
   * 
   * 这个方法通常由命令调用（如"Initialize Research Project"命令）。
   * 
   * @param topic - 研究话题的标题
   */
  async initProject(topic: string): Promise<void> {
    // 获取工作区文件夹
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('projectStructure.noWorkspace'));
      return;
    }

    const workspacePath = workspaceFolder.uri.fsPath;

    // 检查 .agentsociety 文件夹是否存在
    const dotAgentSocietyPath = path.join(workspacePath, '.agentsociety');
    if (fs.existsSync(dotAgentSocietyPath)) {
      const confirm = await vscode.window.showWarningMessage(
        localize('projectStructure.initWorkspace.warnExists'),
        { modal: true },
        localize('projectStructure.initWorkspace.confirm'),
        localize('projectStructure.initWorkspace.cancel')
      );
      if (confirm !== localize('projectStructure.initWorkspace.confirm')) {
        return;
      }
    }

    try {
      // 使用进度提示显示初始化过程
      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('workspaceInit.initializing'),
          cancellable: false,
        },
        async (progress) => {
          // 使用本地 WorkspaceManager 初始化，传递 progress 对象
          return await this.workspaceManager.init({ topic, progress });
        }
      );

      if (result.success) {
        vscode.window.showInformationMessage(localize('workspaceInit.success', topic));
      } else {
        // 失败时显示错误消息
        vscode.window.showErrorMessage(result.message);
      }
    } catch (error: any) {
      // 异常时也显示错误消息
      vscode.window.showErrorMessage(localize('projectStructure.initWorkspace.failed', error.message || error));
    }

    // 刷新视图，显示新创建的文件和目录
    this.refresh();
  }

  /**
   * 扫描自定义模块
   */
  async scanCustomModules(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('customModules.noWorkspace'));
      return;
    }

    const workspacePath = workspaceFolder.uri.fsPath;

    try {
      vscode.window.showInformationMessage(localize('customModules.scanning'));

      const response = await this.apiClient.scanCustomModules({
        workspace_path: workspacePath
      });

      if (response.success) {
        // 获取扫描后的模块列表
        const listResponse = await this.apiClient.listCustomModules();

        if (listResponse.success) {
          // 过滤出自定义模块（is_custom 为 true）
          this.customModulesCache.agents = listResponse.agents.filter(a => a.is_custom);
          this.customModulesCache.envs = listResponse.envs.filter(e => e.is_custom);

          this.log(`Custom modules scan completed: ${this.customModulesCache.agents.length} agents, ${this.customModulesCache.envs.length} envs`);

          vscode.window.showInformationMessage(
            localize('customModules.scanSuccess') +
            ` (${this.customModulesCache.agents.length} ${localize('projectStructure.customAgents')}, ` +
            `${this.customModulesCache.envs.length} ${localize('projectStructure.customEnvs')})`
          );

          // 刷新视图
          this.refresh();
        }
      } else {
        vscode.window.showErrorMessage(localize('customModules.scanFailed', response.message || 'Unknown error'));
      }
    } catch (error: any) {
      this.log(`Scan custom modules failed: ${error}`);
      vscode.window.showErrorMessage(localize('customModules.scanFailed', error.message || error));
    }
  }

  /**
   * 测试自定义模块
   */
  async testCustomModules(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('customModules.noWorkspace'));
      return;
    }

    const workspacePath = workspaceFolder.uri.fsPath;

    try {
      vscode.window.showInformationMessage(localize('customModules.testing'));

      const response = await this.apiClient.testCustomModules({
        workspace_path: workspacePath
      });

      if (response.success) {
        vscode.window.showInformationMessage(
          localize('customModules.testSuccess')
        );

        // 如果有测试输出，显示在输出通道
        if (response.test_output) {
          this.outputChannel.show();
          this.outputChannel.appendLine('=== Custom Modules Test Output ===');
          this.outputChannel.appendLine(response.test_output);
        }
      } else {
        vscode.window.showErrorMessage(
          localize('customModules.testFailed', response.error || 'Unknown error')
        );
      }
    } catch (error: any) {
      this.log(`Test custom modules failed: ${error}`);
      vscode.window.showErrorMessage(localize('customModules.testFailed', error.message || error));
    }
  }

  /**
   * 检查工作区目录结构健康状态
   * @returns 工作区健康状态信息
   */
  checkWorkspaceHealth(workspacePath: string): {
    isHealthy: boolean;
    missingItems: string[];
    issues: string[];
  } {
    const missingItems: string[] = [];
    const issues: string[] = [];

    // 必需的目录
    const requiredDirs = [
      'papers',
      'user_data',
      'datasets',
      'custom',
      'custom/agents',
      'custom/envs',
      '.agentsociety',
      '.claude',
      '.claude/skills'
    ];

    // 必需的文件
    const requiredFiles = [
      'TOPIC.md',
      'CLAUDE.md',
      'AGENTS.md',
      '.env',
      'papers/literature_index.json',
      '.agentsociety/prefill_params.json'
    ];

    // 检查目录
    for (const dir of requiredDirs) {
      const dirPath = path.join(workspacePath, dir);
      if (!fs.existsSync(dirPath)) {
        missingItems.push(`${dir}/`);
      }
    }

    // 检查文件
    for (const file of requiredFiles) {
      const filePath = path.join(workspacePath, file);
      if (!fs.existsSync(filePath)) {
        missingItems.push(file);
      }
    }

    // 检查custom目录中是否有示例文件（仅作为警告）
    const customAgentsDir = path.join(workspacePath, 'custom', 'agents');
    const customEnvsDir = path.join(workspacePath, 'custom', 'envs');
    if (fs.existsSync(customAgentsDir)) {
      const agents = fs.readdirSync(customAgentsDir);
      if (agents.length === 0 || agents.every(f => f.startsWith('__') || f === 'examples')) {
        issues.push('custom/agents/ 目录为空或只有示例文件');
      }
    }

    return {
      isHealthy: missingItems.length === 0,
      missingItems,
      issues
    };
  }

  /**
   * 修复工作区目录结构
   */
  async fixWorkspace(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('customModules.noWorkspace'));
      return;
    }

    const workspacePath = workspaceFolder.uri.fsPath;
    const health = this.checkWorkspaceHealth(workspacePath);

    if (health.isHealthy) {
      vscode.window.showInformationMessage(localize('workspaceFix.healthy'));
      return;
    }

    // 显示问题并询问是否修复
    const missingList = health.missingItems.map(i => `  - ${i}`).join('\n');
    const message = localize('workspaceFix.confirm', health.missingItems.length, missingList);

    const confirm = await vscode.window.showWarningMessage(
      message,
      { modal: true },
      'Fix / 修复',
      'Cancel / 取消'
    );

    if (confirm !== 'Fix / 修复') {
      return;
    }

    try {
      // 使用 WorkspaceManager 来修复工作区
      const result = await this.workspaceManager.init({ topic: 'Fix Workspace' });

      if (result.success) {
        vscode.window.showInformationMessage(localize('workspaceFix.fixed', result.filesCreated?.length || 0));
        this.refresh();
      } else {
        vscode.window.showErrorMessage(localize('workspaceFix.failed', result.message));
      }
    } catch (error: any) {
      this.log(`Fix workspace failed: ${error}`);
      vscode.window.showErrorMessage(localize('workspaceFix.failed', error.message || error));
    }
  }

  /**
   * Update extension-bundled skills by re-syncing to workspace .claude/skills/
   * This includes both AgentSociety skills and official Claude Code office skills (pdf, docx, xlsx, pptx).
   */
  syncBundledClaudeSkillToWorkspace(skillName: string): { success: boolean; message: string } {
    return this.workspaceManager.syncSingleBundledSkill(skillName);
  }

  async updateExtensionSkills(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('projectStructure.noWorkspace'));
      return;
    }

    // Declare in outer scope to be accessible in both steps
    let syncResult: { success: boolean; message: string; created: string[]; synced: string[] };

    // 启动批量操作模式，暂停文件监视器的自动刷新
    this.batchOperationInProgress = true;

    try {
      // Step 1: Sync AgentSociety extension skills
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('projectStructure.updateSkills.step1'),
          cancellable: false
        },
        async (progress) => {
          // Immediately report progress to ensure notification shows up
          progress.report({ increment: 0 });

          // Yield to event loop so progress notification can render
          await new Promise(resolve => setTimeout(resolve, 10));

          // Now execute the synchronous operation
          syncResult = this.workspaceManager.syncClaudeCodeResources();

          if (!syncResult.success) {
            throw new Error(syncResult.message);
          }

          progress.report({ increment: 50 });
          this.outputChannel.appendLine(`[updateExtensionSkills] Synced ${syncResult.synced.length} AgentSociety skills`);
        }
      );

      // Step 2: Copy official Claude Code office skills from extension (pdf, docx, xlsx, pptx)
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('projectStructure.updateSkills.step2'),
          cancellable: false
        },
        async (progress) => {
          // Immediately report progress to ensure notification shows up
          progress.report({ increment: 50 });

          // Yield to event loop so progress notification can render
          await new Promise(resolve => setTimeout(resolve, 10));

          const officeSkillsResult = await this.workspaceManager.copyOfficialOfficeSkills();

          // Combine results for user message
          const agentSocietyCount = syncResult.synced.length;
          const officeSkillsCount = officeSkillsResult.downloaded.length;
          const totalSkills = agentSocietyCount + officeSkillsCount;

          let message: string;
          let buttons: string[] = [
            localize('projectStructure.updateSkills.viewDetails'),
            localize('projectStructure.updateSkills.ok')
          ];

          if (officeSkillsCount === 0) {
            // All office skills failed - critical issue
            message = localize('projectStructure.updateSkills.partialIssues');
            message += localize('projectStructure.updateSkills.agentsociety', agentSocietyCount);
            message += localize('projectStructure.updateSkills.officeFailed');
            message += `⚠️ ${officeSkillsResult.message}\n\n`;
            message += localize('projectStructure.updateSkills.checkExtension');
            buttons = [
              localize('projectStructure.updateSkills.viewDetails'),
              localize('projectStructure.updateSkills.close')
            ];
          } else if (!officeSkillsResult.success && officeSkillsResult.downloaded.length > 0) {
            // Partial success
            message = localize('projectStructure.updateSkills.partialSuccess');
            message += localize('projectStructure.updateSkills.agentsociety', agentSocietyCount);
            message += localize('projectStructure.updateSkills.partialOffice', officeSkillsCount);
            message += `⚠️ ${officeSkillsResult.message}`;
          } else {
            // Full success
            message = localize('projectStructure.updateSkills.success');
            message += localize('projectStructure.updateSkills.agentsociety', agentSocietyCount);
            message += localize('projectStructure.updateSkills.office', officeSkillsCount);
            message += localize('projectStructure.updateSkills.total', totalSkills);
          }

          progress.report({ increment: 100 });

          // Show final result with action button to view output
          const result = await vscode.window.showInformationMessage(
            message,
            ...buttons
          );

          if (result === localize('projectStructure.updateSkills.viewDetails') ||
            result === localize('projectStructure.updateSkills.viewInstructions')) {
            // Show the Workspace Manager output channel
            this.workspaceManager.showOutput();
          }

          this.refresh();
        }
      );

    } catch (error: any) {
      const errorMessage = localize('projectStructure.updateSkills.failed', error.message || error);
      this.outputChannel.appendLine(`[updateExtensionSkills] Error: ${error.stack || error}`);

      // Offer to view output for debugging
      const viewOutput = await vscode.window.showErrorMessage(
        errorMessage,
        localize('projectStructure.updateSkills.viewOutput'),
        localize('projectStructure.updateSkills.close')
      );

      if (viewOutput === localize('projectStructure.updateSkills.viewOutput')) {
        this.workspaceManager.showOutput();
      }
    } finally {
      // 结束批量操作模式，恢复文件监视器的自动刷新
      this.batchOperationInProgress = false;

      // 批量操作完成后，手动触发一次刷新以显示所有更改
      this.refresh();
    }
  }

  /**
   * 打开 Skill 文档（SKILL.md）
   *
   * 对于内置 skill，文件路径在 Python 包内，前端无法直接访问，
   * 因此需要通过 API 获取内容并创建临时文件显示。
   * 对于自定义 skill，直接打开工作区中的文件。
   *
   * @param skillName - Skill 名称
   * @param skillPath - Skill 目录路径
   * @param isBuiltin - 是否为内置 skill
   */
  async openAgentSkillDoc(skillName: string, skillPath: string, isBuiltin: boolean): Promise<void> {
    // 对于内置 skill，始终通过 API 获取内容（路径在 Python 包内，前端无法直接访问）
    if (isBuiltin) {
      await this._openBuiltinSkillDoc(skillName);
      return;
    }

    // 对于自定义 skill，尝试直接打开文件
    const skillMdPath = path.join(skillPath, 'SKILL.md');
    if (fs.existsSync(skillMdPath) && fs.statSync(skillMdPath).isFile()) {
      const uri = vscode.Uri.file(skillMdPath);
      await vscode.commands.executeCommand('markdown.showPreview', uri);
      return;
    }

    // 如果文件不存在，也尝试通过 API 获取
    await this._openBuiltinSkillDoc(skillName);
  }

  /**
   * 通过 API 获取 skill 文档内容并显示
   */
  private async _openBuiltinSkillDoc(skillName: string): Promise<void> {
    try {
      const response = await this.apiClient.getAgentSkillInfo(skillName);
      if (response.success && response.skill_md && response.skill_md.trim()) {
        // 创建临时文件显示内容
        const tempDir = path.join(this.context.globalStorageUri.fsPath, 'skill-docs');
        if (!fs.existsSync(tempDir)) {
          fs.mkdirSync(tempDir, { recursive: true });
        }

        const tempFilePath = path.join(tempDir, `${skillName}.md`);
        fs.writeFileSync(tempFilePath, response.skill_md, 'utf-8');

        const uri = vscode.Uri.file(tempFilePath);
        await vscode.commands.executeCommand('markdown.showPreview', uri);
      } else {
        vscode.window.showWarningMessage(localize('extension.skill.noDoc', skillName));
      }
    } catch (error: any) {
      vscode.window.showErrorMessage(localize('extension.skill.openDocFailed'));
    }
  }
}
