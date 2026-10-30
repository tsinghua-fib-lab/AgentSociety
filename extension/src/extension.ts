/**
 * VSCode插件主入口文件
 *
 * 负责插件的激活/停用、命令注册、各个组件的初始化。
 *
 * 关联文件：
 * - @extension/src/services/backendManager.ts - 后端服务进程管理
 * - @extension/src/configPageViewProvider.ts - 配置页面Webview
 * - @extension/src/prefillParamsViewProvider.ts - 预填充参数查看器
 * - @extension/src/replayWebviewProvider.ts - 回放可视化Webview
 * - @extension/src/projectStructureProvider.ts - 项目结构树视图
 * - @extension/src/simSettingsEditorProvider.ts - SIM_SETTINGS自定义编辑器
 * - @extension/src/apiClient.ts - 后端API通信客户端
 * - @extension/src/envManager.ts - 环境变量(.env)管理
 * - @extension/src/services/llmValidator.ts - LLM配置验证
 *
 * 后端API：
 * - @packages/agentsociety2/agentsociety2/backend/app.py - FastAPI应用主入口
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { ProjectStructureProvider } from './projectStructureProvider';
import { SimSettingsEditorProvider } from './simSettingsEditorProvider';
import { InitConfigEditorProvider } from './initConfigEditorProvider';
import { PrefillParamsViewProvider } from './prefillParamsViewProvider';
import { ReplayWebviewProvider } from './replayWebviewProvider';
import { ConfigPageViewProvider } from './configPageViewProvider';
import { ONBOARDING_KEYS } from './onboardingState';
import { HelpPageViewProvider } from './helpPageViewProvider';
import { ApiClient } from './apiClient';
import { ProjectDragAndDropController } from './dragAndDropController';
import { localize, isExtensionZh } from './i18n';
import { BackendManager } from './services/backendManager';
import { AiCliGatewayManager } from './services/aiCliGatewayManager';
import { ConfigHealthStatusBar } from './services/configHealthStatus';
import { LanguageStatusBar } from './services/languageStatusBar';
import { formatDurationMs } from './shared/formatDuration';
import { WorkspaceExportManager } from './services/workspaceExportManager';
import { WorkspaceImportManager } from './services/workspaceImportManager';
import { filePathToAtReference } from './atReference';
import { AIChatInvoker } from './aiChatInvoker';
import { openClaudeCodeConfig } from './claudeCodeConfigProvider';
import { registerLiteratureLibraryCommands } from './literatureLibraryCommands';
import { openPdfPreview } from './openWorkspaceFile';
import { StepsViewer } from './stepsViewer';

import { PidStatusViewer } from './pidStatusViewer';
import { JsonViewer } from './jsonViewer';
import { YamlViewer } from './yamlViewer';
import { AnalysisHarnessStatusViewer } from './analysisHarnessStatusViewer';
import { CsvViewer } from './csvViewer';
import { hasConfiguredLlmApiKey, migrateLegacySettingsToEnv } from './runtimeConfig';
import { SkillMarketplacePanel } from './skillMarketplaceProvider';

interface BackendStatusMenuPick extends vscode.QuickPickItem {
  commandId: string;
}

// 全局后端服务管理器实例（管理 FastAPI 后端进程的启动、停止、重启）
let backendManager: BackendManager | null = null;
let aiCliGatewayManager: AiCliGatewayManager | null = null;

export function activate(context: vscode.ExtensionContext) {
  try {
    activateExtension(context);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error('AI Social Scientist activation failed:', error);
    void vscode.window.showErrorMessage(
      `AI Social Scientist failed to activate: ${message}. Check Output → Log (Extension Host).`
    );
    throw error;
  }
}

function activateExtension(context: vscode.ExtensionContext) {
  console.log(localize('extension.activate'));

  const migratedLegacyKeys = migrateLegacySettingsToEnv();
  if (migratedLegacyKeys.length > 0) {
    console.log(`Migrated legacy AI Social Scientist settings to .env: ${migratedLegacyKeys.join(', ')}`);
  }

  // ========== 初始化后端服务管理器 ==========
  // BackendManager 负责 FastAPI 后端进程的生命周期管理
  backendManager = new BackendManager(context);
  aiCliGatewayManager = new AiCliGatewayManager(context);
  const configHealthStatusBar = new ConfigHealthStatusBar(context);
  ConfigPageViewProvider.attachGatewayManager(aiCliGatewayManager);
  ConfigPageViewProvider.attachConfigHealthStatus(configHealthStatusBar);
  const workspaceExportManager = new WorkspaceExportManager();
  const workspaceImportManager = new WorkspaceImportManager();
  context.subscriptions.push({
    dispose: () => {
      if (backendManager) {
        backendManager.dispose();
        backendManager = null;
      }
      if (aiCliGatewayManager) {
        aiCliGatewayManager.dispose();
        aiCliGatewayManager = null;
      }
    }
  });
  void restoreAiCliGatewayIfEnabled();
  context.subscriptions.push(workspaceExportManager);
  context.subscriptions.push(workspaceImportManager);

  // 首次引导：开文件夹 → 配 API Key → 初始化工作区 → 启动后端
  const config = vscode.workspace.getConfiguration('aiSocialScientist');
  const autoStart = config.get<boolean>('backend.autoStart', false);
  const hasCompletedInitialSetup = context.globalState.get<boolean>(ONBOARDING_KEYS.hasCompletedInitialSetup);
  const hasLlmApiKey = hasConfiguredLlmApiKey();
  const needsFirstSetup = !hasCompletedInitialSetup || !hasLlmApiKey;
  const hasWorkspace = (vscode.workspace.workspaceFolders?.length ?? 0) > 0;
  const firstSetupGuideKey = ONBOARDING_KEYS.firstSetupGuideShown;

  if (!hasWorkspace) {
    if (!context.globalState.get<boolean>(firstSetupGuideKey)) {
      void vscode.window
        .showInformationMessage(
          localize('extension.onboarding.openFolderFirst'),
          localize('extension.onboarding.openFolder'),
          localize('extension.onboarding.walkthrough'),
          localize('extension.onboarding.dismiss')
        )
        .then((choice) => {
          if (choice === undefined) {
            return;
          }
          void context.globalState.update(firstSetupGuideKey, true);
          if (choice === localize('extension.onboarding.openFolder')) {
            void vscode.commands.executeCommand('workbench.action.files.openFolder');
          } else if (choice === localize('extension.onboarding.walkthrough')) {
            void vscode.commands.executeCommand('aiSocialScientist.openWalkthrough');
          }
        });
    }
  } else if (needsFirstSetup) {
    setTimeout(() => {
      ConfigPageViewProvider.createOrShow(context, vscode.ViewColumn.One);
    }, 500);
    if (!context.globalState.get<boolean>(firstSetupGuideKey)) {
      void vscode.window
        .showInformationMessage(
          localize('extension.onboarding.setupSteps'),
          localize('extension.onboarding.dismiss')
        )
        .then((choice) => {
          if (choice !== undefined) {
            void context.globalState.update(firstSetupGuideKey, true);
          }
        });
    }
  } else if (autoStart) {
    backendManager.start({ silent: true }).catch((error) => {
      console.error('Failed to auto-start backend:', error);
    });
  }

  // Initialize API client
  const apiClient = new ApiClient(context);

  // Initialize AI Chat invoker
  const aiChatInvoker = new AIChatInvoker();
  context.subscriptions.push(aiChatInvoker);

  // ========== 初始化项目结构树视图（支持拖拽） ==========
  // ProjectStructureProvider 提供左侧树视图，展示工作区文件结构
  const projectStructureProvider = new ProjectStructureProvider(context, apiClient);
  // 拖拽控制器：支持将文件拖入 papers/ 目录
  const dragAndDropController = new ProjectDragAndDropController(projectStructureProvider);

  // Use createTreeView instead of registerTreeDataProvider to support drag and drop
  const treeView = vscode.window.createTreeView('projectStructureView', {
    treeDataProvider: projectStructureProvider,
    dragAndDropController: dragAndDropController,
    showCollapseAll: true
  });
  projectStructureProvider.attachTreeView(treeView);

  // Register provider disposal on deactivation
  context.subscriptions.push({
    dispose: () => {
      projectStructureProvider.dispose();
      dragAndDropController.dispose();
    }
  });

  // Register tree view disposal
  context.subscriptions.push(treeView);

  const configEntryTitleBarHintKey = ONBOARDING_KEYS.configEntryTitleBarHintShown;
  // 已完成密钥配置后的轻量提示；首次未完成配置时改用上面的分步引导，避免重复弹窗
  if (
    hasWorkspace &&
    !needsFirstSetup &&
    !context.globalState.get<boolean>(configEntryTitleBarHintKey)
  ) {
    void vscode.window
      .showInformationMessage(
        localize('extension.configEntryTitleBarHint'),
        localize('extension.configEntryTitleBarHint.open'),
        localize('extension.configEntryTitleBarHint.walkthrough'),
        localize('extension.configEntryTitleBarHint.dismiss')
      )
      .then((choice) => {
        if (choice === undefined) {
          return;
        }
        void context.globalState.update(configEntryTitleBarHintKey, true);
        if (choice === localize('extension.configEntryTitleBarHint.open')) {
          void vscode.commands.executeCommand('aiSocialScientist.openConfigPage');
        } else if (choice === localize('extension.configEntryTitleBarHint.walkthrough')) {
          void vscode.commands.executeCommand('aiSocialScientist.openWalkthrough');
        }
      });
  }

  // Register commands
  const initProjectCommand = vscode.commands.registerCommand(
    'aiSocialScientist.initProject',
    async () => {
      const topic = await vscode.window.showInputBox({
        prompt: localize('extension.initProject.prompt'),
        placeHolder: localize('extension.initProject.placeholder')
      });
      if (topic) {
        await projectStructureProvider.initProject(topic);
      }
    }
  );

  // Configure environment command - open config page for .env setup
  const configureEnvCommand = vscode.commands.registerCommand(
    'aiSocialScientist.configureEnv',
    async () => {
      ConfigPageViewProvider.createOrShow(context, vscode.ViewColumn.One);
    }
  );

  // Fix workspace directory command
  const fixWorkspaceCommand = vscode.commands.registerCommand(
    'aiSocialScientist.fixWorkspace',
    async () => {
      await projectStructureProvider.fixWorkspace();
    }
  );

  const exportWorkspaceZipCommand = vscode.commands.registerCommand(
    'aiSocialScientist.exportWorkspaceZip',
    async () => {
      await workspaceExportManager.exportWorkspaceZip();
    }
  );

  const importWorkspaceZipCommand = vscode.commands.registerCommand(
    'aiSocialScientist.importWorkspaceZip',
    async () => {
      await workspaceImportManager.importWorkspaceZip();
    }
  );

  // 删除文献命令 (使用本地文件操作)
  const deleteLiteratureCommand = vscode.commands.registerCommand(
    'aiSocialScientist.deleteLiterature',
    async (item: any) => {
      if (!item || !item.filePath) {
        vscode.window.showErrorMessage(localize('extension.deleteLiterature.noFile'));
        return;
      }

      const filePath = item.filePath;
      const fileName = item.label || filePath.split(/[/\\]/).pop();

      // 检查是否是目录
      const isDirectory = fs.existsSync(filePath) && fs.statSync(filePath).isDirectory();

      // 对于目录，不应该使用此命令删除（目录删除需要特殊处理）
      if (isDirectory) {
        vscode.window.showWarningMessage(
          localize('extension.isDirectory', fileName)
        );
        return;
      }

      const confirm = await vscode.window.showWarningMessage(
        localize('extension.deleteLiterature.confirm', fileName),
        { modal: true },
        localize('extension.deleteLiterature.confirmButton'),
        localize('extension.deleteLiterature.cancelButton')
      );

      if (confirm !== localize('extension.deleteLiterature.confirmButton')) {
        return;
      }

      try {
        // Delete the file
        fs.unlinkSync(filePath);
        vscode.window.showInformationMessage(localize('extension.deleteLiterature.success', fileName));

        // Update literature_index.json if it exists
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (workspaceFolder) {
          const indexPath = path.join(workspaceFolder.uri.fsPath, 'papers', 'literature_index.json');
          if (fs.existsSync(indexPath)) {
            try {
              const indexData = JSON.parse(fs.readFileSync(indexPath, 'utf-8'));
              const relativePath = path.relative(workspaceFolder.uri.fsPath, filePath).replace(/\\/g, '/');
              indexData.entries = (indexData.entries || []).filter((e: any) => e.file_path !== relativePath);
              indexData.updated_at = new Date().toISOString();
              fs.writeFileSync(indexPath, JSON.stringify(indexData, null, 2), 'utf-8');
            } catch (error) {
              console.error('Failed to update literature index:', error);
            }
          }
        }

        projectStructureProvider.refresh();
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.deleteLiterature.failed', error.message || error));
      }
    }
  );

  // 重命名文献命令 (使用本地文件操作)
  const renameLiteratureCommand = vscode.commands.registerCommand(
    'aiSocialScientist.renameLiterature',
    async (item: any) => {
      if (!item || !item.filePath) {
        vscode.window.showErrorMessage(localize('extension.renameLiterature.noFile'));
        return;
      }

      const currentName = item.label || item.filePath.split(/[/\\]/).pop();
      const newName = await vscode.window.showInputBox({
        prompt: localize('extension.renameLiterature.prompt'),
        value: currentName,
        validateInput: (value) => {
          if (!value || value.trim().length === 0) {
            return localize('extension.renameLiterature.emptyName');
          }
          if (value.includes('/') || value.includes('\\')) {
            return localize('extension.renameLiterature.invalidChars');
          }
          return null;
        },
      });

      if (!newName || newName === currentName) {
        return;
      }

      try {
        const dirPath = path.dirname(item.filePath);
        const newPath = path.join(dirPath, newName);

        // Rename the file
        fs.renameSync(item.filePath, newPath);
        vscode.window.showInformationMessage(localize('extension.renameLiterature.success', newName));

        // Update literature_index.json if it exists
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (workspaceFolder) {
          const indexPath = path.join(workspaceFolder.uri.fsPath, 'papers', 'literature_index.json');
          if (fs.existsSync(indexPath)) {
            try {
              const indexData = JSON.parse(fs.readFileSync(indexPath, 'utf-8'));
              const oldRelativePath = path.relative(workspaceFolder.uri.fsPath, item.filePath).replace(/\\/g, '/');
              const newRelativePath = path.join(path.dirname(oldRelativePath), newName).replace(/\\/g, '/');

              const entry = (indexData.entries || []).find((e: any) => e.file_path === oldRelativePath);
              if (entry) {
                entry.file_path = newRelativePath;
                entry.title = newName.replace(/\.(md|json)$/, '');
                indexData.updated_at = new Date().toISOString();
                fs.writeFileSync(indexPath, JSON.stringify(indexData, null, 2), 'utf-8');
              }
            } catch (error) {
              console.error('Failed to update literature index:', error);
            }
          }
        }

        projectStructureProvider.refresh();
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.renameLiterature.failed', error.message || error));
      }
    }
  );

  // 在编辑器中打开 Markdown 文件命令
  const openMarkdownInEditorCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openMarkdownInEditor',
    async (item: any) => {
      if (!item || !item.filePath) {
        vscode.window.showErrorMessage(localize('extension.openMarkdown.noFile'));
        return;
      }

      const filePath = item.filePath;
      // 检查是否为 markdown 文件
      const isMarkdown = filePath.toLowerCase().endsWith('.md');
      if (!isMarkdown) {
        vscode.window.showWarningMessage(localize('extension.openMarkdown.warning'));
        return;
      }

      try {
        // 使用 vscode.open 命令在编辑器中打开文件
        const fileUri = vscode.Uri.file(filePath);
        await vscode.window.showTextDocument(fileUri);
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.openMarkdown.failed'));
      }
    }
  );

  const openHtmlReportCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openHtmlReport',
    async (uriOrItem?: vscode.Uri | { filePath?: string }) => {
      let uri: vscode.Uri | undefined;
      if (uriOrItem instanceof vscode.Uri) {
        uri = uriOrItem;
      } else if (uriOrItem && typeof uriOrItem === 'object' && uriOrItem.filePath) {
        uri = vscode.Uri.file(uriOrItem.filePath);
      }
      if (!uri) {
        return;
      }
      try {
        await vscode.commands.executeCommand(
          'livePreview.start.preview.atFile',
          uri
        );
      } catch {
        await vscode.commands.executeCommand('vscode.open', uri);
      }
    }
  );

  const openTreeFileInEditorCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openTreeFileInEditor',
    async (item: any) => {
      const filePath = item?.filePath;
      if (!filePath) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }
      if (!fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(localize('extension.openTreeFile.missing'));
        return;
      }
      if (!fs.statSync(filePath).isFile()) {
        vscode.window.showWarningMessage(localize('extension.openTreeFile.isDirectory'));
        return;
      }
      await vscode.window.showTextDocument(vscode.Uri.file(filePath));
    }
  );

  // Open AI Chat command
  const openChatCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openChat',
    async () => {
      await aiChatInvoker.invokeChat();
    }
  );

  // Select AI Chat provider command
  const selectAiChatCommand = vscode.commands.registerCommand(
    'aiSocialScientist.selectAiChat',
    async () => {
      await aiChatInvoker.pickProvider();
    }
  );

  // Register custom editor for SIM_SETTINGS.json
  context.subscriptions.push(
    vscode.window.registerCustomEditorProvider(
      'aiSocialScientist.simSettings',
      new SimSettingsEditorProvider(context),
      {
        webviewOptions: {
          retainContextWhenHidden: true
        },
        supportsMultipleEditorsPerDocument: false
      }
    )
  );

  // Register custom editor for init_config.json
  context.subscriptions.push(
    vscode.window.registerCustomEditorProvider(
      'aiSocialScientist.initConfig',
      new InitConfigEditorProvider(context),
      {
        webviewOptions: {
          retainContextWhenHidden: true
        },
        supportsMultipleEditorsPerDocument: false
      }
    )
  );

  // Register prefill parameters command
  const viewPrefillParamsCommand = vscode.commands.registerCommand(
    'agentsociety.viewPrefillParams',
    (kind?: 'env_module' | 'agent') => {
      PrefillParamsViewProvider.createOrShow(context, apiClient, kind);
    }
  );
  context.subscriptions.push(viewPrefillParamsCommand);

  // Register open replay command
  const openReplayCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openReplay',
    async (item?: any) => {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        vscode.window.showErrorMessage(localize('extension.replay.noWorkspace'));
        return;
      }

      // Extract hypothesis_id and experiment_id from the item or prompt user
      let hypothesisId: string | undefined;
      let experimentId: string | undefined;

      if (item && item.hypothesisId && item.experimentId) {
        // Called from tree view with context
        hypothesisId = item.hypothesisId;
        experimentId = item.experimentId;
      } else if (item && item.filePath) {
        // Try to parse from file path (e.g., hypothesis_xxx/experiment_yyy/...)
        const relativePath = path.relative(workspaceFolder.uri.fsPath, item.filePath);
        const match = relativePath.match(/hypothesis_([^/\\]+)[/\\]experiment_([^/\\]+)/);
        if (match) {
          hypothesisId = match[1];
          experimentId = match[2];
        }
      }

      if (!hypothesisId || !experimentId) {
        // Prompt user to enter hypothesis_id and experiment_id manually
        hypothesisId = await vscode.window.showInputBox({
          prompt: localize('extension.replay.inputHypothesis'),
          placeHolder: localize('extension.replay.inputHypothesisPlaceholder')
        });
        if (!hypothesisId) {
          return;
        }

        experimentId = await vscode.window.showInputBox({
          prompt: localize('extension.replay.inputExperiment'),
          placeHolder: localize('extension.replay.inputExperimentPlaceholder')
        });
        if (!experimentId) {
          return;
        }
      }

      // Create replay webview
      ReplayWebviewProvider.create(
        context,
        workspaceFolder.uri.fsPath,
        hypothesisId,
        experimentId
      );
    }
  );
  context.subscriptions.push(openReplayCommand);

  // Register backend management commands
  const startBackendCommand = vscode.commands.registerCommand(
    'aiSocialScientist.startBackend',
    async (options?: { silent?: boolean }) => {
      if (backendManager) {
        const silent = options?.silent ?? false;
        const started = await backendManager.start({ silent });
        if (!silent) {
          if (started) {
            vscode.window.showInformationMessage(localize('extension.backend.started'));
          } else {
            vscode.window.showErrorMessage(localize('extension.backend.startFailed'));
          }
        }
        return started;
      }
      return false;
    }
  );

  const stopBackendCommand = vscode.commands.registerCommand(
    'aiSocialScientist.stopBackend',
    async () => {
      if (backendManager) {
        const stopped = await backendManager.stop();
        if (stopped) {
          vscode.window.showInformationMessage(localize('extension.backend.stopped'));
        }
      }
    }
  );

  const restartBackendCommand = vscode.commands.registerCommand(
    'aiSocialScientist.restartBackend',
    async (options?: { silent?: boolean }) => {
      if (backendManager) {
        const silent = options?.silent ?? false;
        const restarted = await backendManager.restart({ silent });
        if (!silent) {
          if (restarted) {
            vscode.window.showInformationMessage(localize('extension.backend.restarted'));
          } else {
            vscode.window.showErrorMessage(localize('extension.backend.restartFailed'));
          }
        }
        return restarted;
      }
      return false;
    }
  );

  const showBackendLogsCommand = vscode.commands.registerCommand(
    'aiSocialScientist.showBackendLogs',
    () => {
      if (backendManager) {
        backendManager.showLogs();
      }
    }
  );

  // 复制后端 URL 命令
  const copyBackendUrlCommand = vscode.commands.registerCommand(
    'aiSocialScientist.copyBackendUrl',
    async () => {
      if (backendManager) {
        await backendManager.copyBackendUrl();
      }
    }
  );

  // 在浏览器中打开后端 URL 命令
  const openBackendInBrowserCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openBackendInBrowser',
    async () => {
      if (backendManager) {
        await backendManager.openInBrowser();
      }
    }
  );

  // 在浏览器中打开 API 文档命令
  const openApiDocsCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openApiDocs',
    async () => {
      if (backendManager) {
        await backendManager.openApiDocs();
      }
    }
  );

  const backendStatusMenuCommand = vscode.commands.registerCommand(
    'aiSocialScientist.backendStatusMenu',
    async () => {
      const currentStatus = backendManager?.getCurrentStatus() ?? 'stopped';
      const items: BackendStatusMenuPick[] = [];

      // 根据运行状态动态构建菜单
      if (currentStatus === 'running') {
        // 运行中：显示复制URL、打开浏览器等选项
        const url = backendManager?.getBackendUrl() ?? '';
        items.push(
          { label: `$(link) ${localize('backendManager.statusBar.copyUrl')}`, description: url, commandId: 'aiSocialScientist.copyBackendUrl' },
          { label: `$(browser) ${localize('backendManager.statusBar.openInBrowser')}`, description: url, commandId: 'aiSocialScientist.openBackendInBrowser' },
          { label: `$(book) ${localize('backendManager.statusBar.openApiDocs')}`, description: `${url}/docs`, commandId: 'aiSocialScientist.openApiDocs' },
          { label: `$(refresh) ${localize('backendManager.statusBar.restart')}`, commandId: 'aiSocialScientist.restartBackend' },
          { label: `$(stop) ${localize('backendManager.statusBar.stop')}`, commandId: 'aiSocialScientist.stopBackend' }
        );
      } else if (currentStatus === 'starting') {
        // 启动中：只显示日志和状态
        items.push(
          { label: `$(output) ${localize('backendManager.statusBar.logs')}`, commandId: 'aiSocialScientist.showBackendLogs' },
          { label: `$(settings) ${localize('backendManager.statusBar.config')}`, commandId: 'aiSocialScientist.openConfigPage' },
          { label: `$(stop) ${localize('backendManager.statusBar.stop')}`, commandId: 'aiSocialScientist.stopBackend' }
        );
      } else if (currentStatus === 'error') {
        // 错误状态：显示重启、日志、配置
        items.push(
          { label: `$(refresh) ${localize('backendManager.statusBar.restart')}`, commandId: 'aiSocialScientist.restartBackend' },
          { label: `$(output) ${localize('backendManager.statusBar.logs')}`, commandId: 'aiSocialScientist.showBackendLogs' },
          { label: `$(settings) ${localize('backendManager.statusBar.config')}`, commandId: 'aiSocialScientist.openConfigPage' }
        );
      } else {
        // 已停止：显示启动、配置选项
        items.push(
          { label: `$(play) ${localize('backendManager.statusBar.start')}`, commandId: 'aiSocialScientist.startBackend' },
          { label: `$(settings) ${localize('backendManager.statusBar.config')}`, commandId: 'aiSocialScientist.openConfigPage' }
        );
      }

      // 所有状态都显示日志和配置（除了上面已经添加的情况）
      if (currentStatus === 'running') {
        items.push(
          { label: `$(output) ${localize('backendManager.statusBar.logs')}`, commandId: 'aiSocialScientist.showBackendLogs' },
          { label: `$(settings) ${localize('backendManager.statusBar.config')}`, commandId: 'aiSocialScientist.openConfigPage' }
        );
      }

      const selected = await vscode.window.showQuickPick(items, {
        placeHolder: localize('backendManager.statusBar.placeholder'),
        matchOnDescription: true
      });
      if (selected?.commandId) {
        await vscode.commands.executeCommand(selected.commandId);
      }
    }
  );

  const getBackendStatusCommand = vscode.commands.registerCommand(
    'aiSocialScientist.getBackendStatus',
    async () => {
      if (!backendManager) {
        return { isRunning: false };
      }
      return await backendManager.getStatus();
    }
  );

  const openConfigPageCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openConfigPage',
    () => {
      ConfigPageViewProvider.createOrShow(context, vscode.ViewColumn.Beside);
    }
  );

  const openClaudeCodeConfigCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openClaudeCodeConfig',
    () => {
      openClaudeCodeConfig(context, vscode.ViewColumn.Beside);
    }
  );

  const showGatewayLogCommand = vscode.commands.registerCommand(
    'aiSocialScientist.showGatewayLog',
    () => {
      if (aiCliGatewayManager) {
        aiCliGatewayManager.showLogChannel();
      }
    }
  );

  const gatewayStatusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    99
  );
  gatewayStatusBar.command = 'aiSocialScientist.openClaudeCodeConfig';
  context.subscriptions.push(gatewayStatusBar);
  context.subscriptions.push(showGatewayLogCommand);

  const updateGatewayStatusBar = () => {
    if (!aiCliGatewayManager) {
      gatewayStatusBar.hide();
      return;
    }
    const s = aiCliGatewayManager.getPublicStatus();
    if (s.enabled && s.running) {
      const port = s.port ?? '';
      const uptime =
        s.stats?.uptimeMs !== undefined ? formatDurationMs(s.stats.uptimeMs) : '';
      gatewayStatusBar.text = port ? `$(radio-tower) :${port}` : '$(radio-tower)';
      gatewayStatusBar.tooltip = localize(
        'aiCliGateway.statusBarTooltipShort',
        s.baseUrl ?? '',
        uptime || '—',
        String(s.stats?.totalRequests ?? 0),
        String(s.stats?.successRate !== undefined ? Math.round(s.stats.successRate) : '—')
      );
      gatewayStatusBar.backgroundColor = undefined;
      gatewayStatusBar.show();
    } else if (s.enabled) {
      gatewayStatusBar.text = '$(warning) GW';
      gatewayStatusBar.tooltip = localize('aiCliGateway.statusBarStopped');
      gatewayStatusBar.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
      gatewayStatusBar.show();
    } else {
      gatewayStatusBar.backgroundColor = undefined;
      gatewayStatusBar.hide();
    }
  };
  updateGatewayStatusBar();
  const gatewayStatusBarInterval = setInterval(updateGatewayStatusBar, 10_000);
  context.subscriptions.push({ dispose: () => clearInterval(gatewayStatusBarInterval) });

  const applyLanguageChange = () => {
    projectStructureProvider.refreshNow();
    configHealthStatusBar.refresh();
    updateGatewayStatusBar();
    languageStatusBar.refresh();
    ConfigPageViewProvider.reloadLanguageIfOpen();
    SkillMarketplacePanel.reloadLanguageIfOpen();
    HelpPageViewProvider.reloadLanguageIfOpen();
    void import('./paperReviewViewer').then(({ PaperReviewViewer }) => {
      PaperReviewViewer.reloadLanguageIfOpen();
    });
  };
  const languageStatusBar = new LanguageStatusBar(context, () => {
    applyLanguageChange();
  });
  const toggleLanguageCommand = vscode.commands.registerCommand(
    'aiSocialScientist.toggleLanguage',
    async () => {
      await languageStatusBar.toggle();
    }
  );

  // ========== Help Page ==========
  const openHelpPageCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openHelpPage',
    () => {
      HelpPageViewProvider.createOrShow(context, vscode.ViewColumn.One);
    }
  );

  const openWalkthroughCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openWalkthrough',
    async () => {
      await vscode.commands.executeCommand(
        'workbench.action.openWalkthrough',
        `${context.extension.id}#aiSocialScientist.gettingStarted`,
        false
      );
    }
  );

  // ========== Skill Marketplace（编辑器区域面板，避免侧边栏过窄） ==========
  const openSkillMarketplaceCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openSkillMarketplace',
    () => {
      SkillMarketplacePanel.createOrShow(
        context,
        apiClient,
        projectStructureProvider,
        vscode.ViewColumn.One
      );
    }
  );

  const openSkillSourcesSettingsCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openSkillSourcesSettings',
    async () => {
      await vscode.commands.executeCommand('workbench.action.openSettings', 'agentSkills.skillSources');
    }
  );

  const openClaudeSkillSourcesSettingsCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openClaudeSkillSourcesSettings',
    async () => {
      await vscode.commands.executeCommand('workbench.action.openSettings', 'agentSkills.claudeSkillSources');
    }
  );

  // ========== Custom Module Commands ==========

  const refreshProjectViewCommand = vscode.commands.registerCommand(
    'aiSocialScientist.refreshProjectView',
    () => {
      projectStructureProvider.refresh();
      vscode.window.showInformationMessage(localize('projectView.refreshed'));
    }
  );

  const openAgentSkillDocCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openAgentSkillDoc',
    async (skillName: string, skillPath: string, isBuiltin: boolean, skillId?: string) => {
      await projectStructureProvider.openAgentSkillDoc(skillName, skillPath, isBuiltin, skillId);
    }
  );

  const updateExtensionSkillsCommand = vscode.commands.registerCommand(
    'aiSocialScientist.updateExtensionSkills',
    async () => {
      await projectStructureProvider.updateExtensionSkills();
    }
  );

  const switchSkillVersionCommand = vscode.commands.registerCommand(
    'aiSocialScientist.switchSkillVersion',
    async () => {
      const wf = vscode.workspace.workspaceFolders?.[0];
      if (!wf) {
        vscode.window.showErrorMessage('请先打开工作区文件夹');
        return;
      }
      const versionManager = projectStructureProvider.getSkillVersionManager();
      const file = versionManager.ensureDefaultPresetExists(wf.uri.fsPath);
      const items = Object.keys(file.presets)
        .sort()
        .map((name) => ({
          label: file.active === name ? `$(check) ${name}` : name,
          description: file.active === name ? '当前激活' : undefined,
          name,
        }));
      const picked = await vscode.window.showQuickPick(items, {
        placeHolder: 'Switch Skill Version: 选择 preset',
      });
      if (!picked) {
        return;
      }
      const result = versionManager.applyPreset(wf.uri.fsPath, picked.name);
      const summary =
        `已切换到 preset「${result.preset}」：` +
        `应用 ${result.applied.length} 个，` +
        `回退 ${result.fallbacks.length} 个，` +
        `错误 ${result.errors.length} 个`;
      if (result.errors.length === 0) {
        vscode.window.showInformationMessage(summary);
      } else {
        vscode.window.showWarningMessage(summary);
      }
    }
  );

  const snapshotCurrentSkillCommand = vscode.commands.registerCommand(
    'aiSocialScientist.snapshotCurrentSkill',
    async (presetSkillName?: string) => {
      const wf = vscode.workspace.workspaceFolders?.[0];
      if (!wf) {
        vscode.window.showErrorMessage('请先打开工作区文件夹');
        return;
      }
      const versionManager = projectStructureProvider.getSkillVersionManager();
      const skillNames = versionManager.listManagedSkills();
      if (skillNames.length === 0) {
        vscode.window.showWarningMessage('未发现可快照的 agentsociety-* skill');
        return;
      }
      const skill =
        presetSkillName && skillNames.includes(presetSkillName)
          ? presetSkillName
          : await vscode.window.showQuickPick(skillNames, {
            placeHolder: 'Snapshot Current Skill: 选择要快照的 skill',
          });
      if (!skill) {
        return;
      }
      const tag = await vscode.window.showInputBox({
        prompt: `输入快照 tag（仅字母/数字/. _ -）`,
        placeHolder: `如 stable-${new Date().toISOString().slice(0, 10)}`,
        validateInput: (v) => (/^[A-Za-z0-9._-]+$/.test(v.trim()) ? null : '非法字符'),
      });
      if (!tag) {
        return;
      }
      const result = versionManager.createSnapshot(wf.uri.fsPath, skill, tag);
      if (result.success) {
        vscode.window.showInformationMessage(result.message);
      } else {
        vscode.window.showErrorMessage(result.message);
      }
    }
  );

  const editSkillPresetsCommand = vscode.commands.registerCommand(
    'aiSocialScientist.editSkillPresets',
    async () => {
      const wf = vscode.workspace.workspaceFolders?.[0];
      if (!wf) {
        vscode.window.showErrorMessage('请先打开工作区文件夹');
        return;
      }
      const versionManager = projectStructureProvider.getSkillVersionManager();
      versionManager.ensureDefaultPresetExists(wf.uri.fsPath);
      const file = vscode.Uri.file(
        path.join(wf.uri.fsPath, '.agentsociety', 'skill-presets.json')
      );
      await vscode.window.showTextDocument(file);
    }
  );

  // 格式化查看 JSON 文件命令
  const formatJsonCommand = vscode.commands.registerCommand(
    'aiSocialScientist.formatJsonFile',
    async (item: any) => {
      if (!item || !item.filePath) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }

      const filePath = item.filePath;

      // 检查是否为 JSON 文件
      if (!filePath.toLowerCase().endsWith('.json')) {
        vscode.window.showWarningMessage(localize('extension.formatJson.wrongType'));
        return;
      }

      try {
        // 打开文件
        const document = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
        await vscode.window.showTextDocument(document);

        // 格式化文档
        await vscode.commands.executeCommand('editor.action.formatDocument');

        // 可选：切换到更友好的视图（如果安装了 JSON tools 等扩展）
        vscode.window.showInformationMessage(localize('extension.formatJson.done'));
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.formatJson.failed'));
      }
    }
  );

  // 文献库：打开索引 / 同步完善 / Bib 导入导出（插件侧，不经 MCP）
  const literatureLibraryCommands = registerLiteratureLibraryCommands(context);

  const openPdfPreviewCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openPdfPreview',
    async (filePathOrItem?: string | { filePath?: string }) => {
      const filePath =
        typeof filePathOrItem === 'string'
          ? filePathOrItem
          : filePathOrItem?.filePath;
      if (!filePath || !fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(
          isExtensionZh() ? '找不到 PDF 文件。' : 'PDF file not found.'
        );
        return;
      }
      try {
        await openPdfPreview(filePath);
      } catch (error: any) {
        vscode.window.showErrorMessage(
          isExtensionZh()
            ? `无法预览 PDF: ${error.message || error}`
            : `Could not preview PDF: ${error.message || error}`
        );
      }
    }
  );

  // Steps YAML 预览命令
  const viewStepsYamlCommand = vscode.commands.registerCommand(
    'aiSocialScientist.viewStepsYaml',
    async (item: any) => {
      let filePath: string | undefined;

      if (item && item.filePath) {
        filePath = item.filePath;
      } else {
        // 如果没有传入文件路径，让用户选择
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (!workspaceFolder) {
          vscode.window.showErrorMessage(localize('extension.steps.noWorkspace'));
          return;
        }

        const files = await vscode.workspace.findFiles('**/init/steps.yaml');
        if (files.length === 0) {
          vscode.window.showErrorMessage(localize('extension.steps.notFound'));
          return;
        }

        if (files.length === 1) {
          filePath = files[0].fsPath;
        } else {
          const picks = files.map(f => ({
            label: vscode.workspace.asRelativePath(f),
            path: f.fsPath
          }));
          const selected = await vscode.window.showQuickPick(picks, {
            placeHolder: localize('extension.steps.pickPlaceholder')
          });
          if (!selected) {
            return;
          }
          filePath = selected.path;
        }
      }

      // 检查文件是否存在
      if (!filePath || !fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(localize('extension.steps.missing'));
        return;
      }

      try {
        await StepsViewer.show(context, filePath);
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.steps.openFailed'));
      }
    }
  );

  // PID状态可视化命令
  const viewPidStatusCommand = vscode.commands.registerCommand(
    'aiSocialScientist.viewPidStatus',
    async (item: any) => {
      const filePath = item?.filePath;
      if (!filePath || !fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(localize('extension.pid.missing'));
        return;
      }

      try {
        await PidStatusViewer.createOrShow(filePath);
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.pid.openFailed'));
      }
    }
  );

  // 复制文件路径命令
  const copyFilePathCommand = vscode.commands.registerCommand(
    'aiSocialScientist.copyFilePath',
    async (item: any) => {
      const filePath = item?.filePath;
      if (!filePath) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }

      try {
        await vscode.env.clipboard.writeText(filePath);
        vscode.window.showInformationMessage(localize('extension.clipboard.pathCopied'));
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.clipboard.pathFailed'));
      }
    }
  );

  // 复制 @引用 格式命令
  const copyAtReferenceCommand = vscode.commands.registerCommand(
    'aiSocialScientist.copyAtReference',
    async (item: any) => {
      const filePath = item?.filePath;
      if (!filePath) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }

      try {
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (!workspaceFolder) {
          vscode.window.showErrorMessage(localize('customModules.noWorkspace'));
          return;
        }

        const atReference = filePathToAtReference(workspaceFolder.uri.fsPath, filePath);
        await vscode.env.clipboard.writeText(atReference);
        vscode.window.showInformationMessage(localize('extension.clipboard.refCopied', atReference));
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.clipboard.refFailed'));
      }
    }
  );

  // JSON 文件可视化命令
  const viewJsonFileCommand = vscode.commands.registerCommand(
    'aiSocialScientist.viewJsonFile',
    async (filePathOrItem: string | any) => {
      const filePath = typeof filePathOrItem === 'string' ? filePathOrItem : filePathOrItem?.filePath;
      if (!filePath || !fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }
      if (!filePath.toLowerCase().endsWith('.json')) {
        return;
      }
      // Route paper/analysis artifacts to dedicated viewer
      const fileName = path.basename(filePath);
      const parentDir = path.basename(path.dirname(filePath));
      const isPaperArtifact =
        parentDir === 'paper' || parentDir === 'reviews' || parentDir === 'state' ||
        parentDir.startsWith('experiment_') || parentDir.startsWith('hypothesis_') ||
        parentDir === 'analysis' || parentDir === 'synthesis' ||
        fileName === 'paper_meta.yaml' || fileName === 'paper_state.yaml' ||
        fileName === 'claim_ledger.json' || fileName === 'claims.json' ||
        fileName === 'synthesis_brief.json' || fileName === 'evidence_backlog.json' ||
        fileName === 'evidence_graph.json' || fileName === 'evidence_index.json' ||
        fileName === 'research_pack.json' || fileName === 'figure_argument_map.json' ||
        fileName === 'storyline_map.json' || fileName === 'human_gates.yaml' ||
        fileName === 'run.json' || fileName.startsWith('review_');
      if (isPaperArtifact) {
        const { PaperArtifactViewer } = await import('./paperArtifactViewer');
        await PaperArtifactViewer.show(filePath);
      } else {
        await JsonViewer.show(filePath);
      }
    }
  );

  // YAML 文件可视化命令
  const viewYamlFileCommand = vscode.commands.registerCommand(
    'aiSocialScientist.viewYamlFile',
    async (filePathOrItem: string | any) => {
      const filePath = typeof filePathOrItem === 'string' ? filePathOrItem : filePathOrItem?.filePath;
      if (!filePath || !fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }
      const lower = filePath.toLowerCase();
      if (!lower.endsWith('.yaml') && !lower.endsWith('.yml')) {
        return;
      }
      const fileName = path.basename(filePath);
      const parentDir = path.basename(path.dirname(filePath));
      const isPaperArtifactYaml =
        fileName === 'paper_meta.yaml' ||
        fileName === 'paper_state.yaml' ||
        fileName === 'human_gates.yaml' ||
        (fileName.startsWith('review_') && (lower.endsWith('.yaml') || lower.endsWith('.yml'))) ||
        parentDir === 'paper' ||
        parentDir === 'state' ||
        parentDir === 'reviews';
      if (isPaperArtifactYaml) {
        const { PaperArtifactViewer } = await import('./paperArtifactViewer');
        await PaperArtifactViewer.show(filePath);
        return;
      }
      await YamlViewer.show(filePath);
    }
  );

  const viewAnalysisHarnessStatusCommand = vscode.commands.registerCommand(
    'aiSocialScientist.viewAnalysisHarnessStatus',
    async (args: { statePath?: string; scope?: 'hypothesis' | 'synthesis'; focusPhase?: string }) => {
      if (!args?.statePath) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }
      await AnalysisHarnessStatusViewer.show({
        statePath: args.statePath,
        scope: args.scope || 'hypothesis',
        focusPhase: args.focusPhase,
      });
    }
  );

  const viewCsvFileCommand = vscode.commands.registerCommand(
    'aiSocialScientist.viewCsvFile',
    async (filePathOrItem: string | any) => {
      const filePath = typeof filePathOrItem === 'string' ? filePathOrItem : filePathOrItem?.filePath;
      if (!filePath || !fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }
      const lower = filePath.toLowerCase();
      if (!lower.endsWith('.csv') && !lower.endsWith('.tsv')) {
        return;
      }
      await CsvViewer.show(filePath);
    }
  );

  const viewPaperReviewCommand = vscode.commands.registerCommand(
    'aiSocialScientist.viewPaperReview',
    async (filePathOrItem: string | any) => {
      const filePath = typeof filePathOrItem === 'string' ? filePathOrItem : filePathOrItem?.filePath;
      if (!filePath || !fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }
      const { PaperReviewViewer } = await import('./paperReviewViewer');
      const stat = fs.statSync(filePath);
      if (stat.isDirectory()) {
        await PaperReviewViewer.showRound(filePath);
      } else {
        await PaperReviewViewer.showReviewer(filePath);
      }
    }
  );

  // 在文件管理器中打开命令
  const openInExplorerCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openInExplorer',
    async (item: any) => {
      const filePath = item?.filePath;
      if (!filePath) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }

      // 如果是文件，打开其所在目录
      const targetPath = fs.existsSync(filePath) && fs.statSync(filePath).isFile()
        ? path.dirname(filePath)
        : filePath;

      await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(targetPath));
    }
  );

  // Register all commands
  context.subscriptions.push(
    initProjectCommand,
    configureEnvCommand,
    fixWorkspaceCommand,
    exportWorkspaceZipCommand,
    importWorkspaceZipCommand,
    deleteLiteratureCommand,
    renameLiteratureCommand,
    ...literatureLibraryCommands,
    openPdfPreviewCommand,
    openMarkdownInEditorCommand,
    openHtmlReportCommand,
    openTreeFileInEditorCommand,
    openChatCommand,
    selectAiChatCommand,
    startBackendCommand,
    stopBackendCommand,
    restartBackendCommand,
    showBackendLogsCommand,
    getBackendStatusCommand,
    backendStatusMenuCommand,
    copyBackendUrlCommand,
    openBackendInBrowserCommand,
    openApiDocsCommand,
    openConfigPageCommand,
    openClaudeCodeConfigCommand,
    showGatewayLogCommand,
    openHelpPageCommand,
    openWalkthroughCommand,
    openSkillMarketplaceCommand,
    openSkillSourcesSettingsCommand,
    openClaudeSkillSourcesSettingsCommand,
    refreshProjectViewCommand,
    toggleLanguageCommand,
    openAgentSkillDocCommand,
    updateExtensionSkillsCommand,
    switchSkillVersionCommand,
    snapshotCurrentSkillCommand,
    editSkillPresetsCommand,
    formatJsonCommand,
    viewStepsYamlCommand,
    viewPidStatusCommand,
    viewJsonFileCommand,
    viewYamlFileCommand,
    viewAnalysisHarnessStatusCommand,
    viewCsvFileCommand,
    viewPaperReviewCommand,
    openInExplorerCommand,
    copyFilePathCommand,
    copyAtReferenceCommand
  );
}

async function restoreAiCliGatewayIfEnabled(): Promise<void> {
  if (!aiCliGatewayManager) {
    return;
  }
  try {
    await aiCliGatewayManager.restoreIfEnabled();
  } catch (error) {
    console.error('Failed to restore AI CLI gateway:', error);
  }
}

export function deactivate() {
  if (backendManager) {
    void backendManager.stop();
  }
}
