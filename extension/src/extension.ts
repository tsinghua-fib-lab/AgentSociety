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
import { ApiClient } from './apiClient';
import { ProjectDragAndDropController } from './dragAndDropController';
import { localize } from './i18n';
import { BackendManager } from './services/backendManager';
import { WorkspaceExportManager } from './services/workspaceExportManager';
import { filePathToAtReference } from './atReference';
import { AIChatInvoker } from './aiChatInvoker';
import { LiteratureIndexViewer } from './literatureIndexViewer';
import { StepsViewer } from './stepsViewer';
import { ExperimentResultsViewer } from './experimentResultsViewer';
import { PidStatusViewer } from './pidStatusViewer';
import { JsonViewer } from './jsonViewer';
import { YamlViewer } from './yamlViewer';
import { hasConfiguredLlmApiKey, migrateLegacySettingsToEnv } from './runtimeConfig';
import { SkillMarketplacePanel } from './skillMarketplaceProvider';

interface BackendStatusMenuPick extends vscode.QuickPickItem {
  commandId: string;
}

// 全局后端服务管理器实例（管理 FastAPI 后端进程的启动、停止、重启）
let backendManager: BackendManager | null = null;

export function activate(context: vscode.ExtensionContext) {
  console.log(localize('extension.activate'));

  const migratedLegacyKeys = migrateLegacySettingsToEnv();
  if (migratedLegacyKeys.length > 0) {
    console.log(`Migrated legacy AI Social Scientist settings to .env: ${migratedLegacyKeys.join(', ')}`);
  }

  // ========== 初始化后端服务管理器 ==========
  // BackendManager 负责 FastAPI 后端进程的生命周期管理
  backendManager = new BackendManager(context);
  const workspaceExportManager = new WorkspaceExportManager();
  context.subscriptions.push({
    dispose: () => {
      if (backendManager) {
        backendManager.dispose();
        backendManager = null;
      }
    }
  });
  context.subscriptions.push(workspaceExportManager);

  // 首次启动或配置未完成时，打开配置页；否则按设置决定是否自动启动后端
  const config = vscode.workspace.getConfiguration('aiSocialScientist');
  const autoStart = config.get<boolean>('backend.autoStart', false);
  const hasCompletedInitialSetup = context.globalState.get<boolean>('configPage.hasCompletedInitialSetup');
  const hasLlmApiKey = hasConfiguredLlmApiKey();

  if (!hasCompletedInitialSetup || !hasLlmApiKey) {
    // 首次启动或缺少必填配置时，打开配置页
    setTimeout(() => {
      ConfigPageViewProvider.createOrShow(context, vscode.ViewColumn.One);
    }, 500);
  } else if (autoStart) {
    // 配置已完成且启用自动启动，则启动后端
    backendManager.start().catch((error) => {
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

  // Register provider disposal on deactivation
  context.subscriptions.push({
    dispose: () => {
      projectStructureProvider.dispose();
      dragAndDropController.dispose();
    }
  });

  // Register tree view disposal
  context.subscriptions.push(treeView);

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
        vscode.window.showInformationMessage(localize('extension.initProject.success', topic));
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

  // Open AI Chat command
  const openChatCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openChat',
    async () => {
      await aiChatInvoker.invokeChat();
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
    async () => {
      if (backendManager) {
        const started = await backendManager.start();
        if (started) {
          vscode.window.showInformationMessage(localize('extension.backend.started'));
        } else {
          vscode.window.showErrorMessage(localize('extension.backend.startFailed'));
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
        await backendManager.stop();
        vscode.window.showInformationMessage(localize('extension.backend.stopped'));
      }
    }
  );

  const restartBackendCommand = vscode.commands.registerCommand(
    'aiSocialScientist.restartBackend',
    async () => {
      if (backendManager) {
        const restarted = await backendManager.restart();
        if (restarted) {
          vscode.window.showInformationMessage(localize('extension.backend.restarted'));
        } else {
          vscode.window.showErrorMessage(localize('extension.backend.restartFailed'));
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
          { label: `$(book) Open API Docs`, description: `${url}/docs`, commandId: 'aiSocialScientist.openApiDocs' },
          { label: `$(refresh) ${localize('backendManager.statusBar.restart')}`, commandId: 'aiSocialScientist.restartBackend' },
          { label: `$(stop) ${localize('backendManager.statusBar.stop')}`, commandId: 'aiSocialScientist.stopBackend' }
        );
      } else if (currentStatus === 'starting') {
        // 启动中：只显示日志和状态
        items.push(
          { label: `$(output) ${localize('backendManager.statusBar.logs')}`, commandId: 'aiSocialScientist.showBackendLogs' },
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

  const showBackendStatusCommand = vscode.commands.registerCommand(
    'aiSocialScientist.showBackendStatus',
    async () => {
      if (backendManager) {
        const status = await backendManager.getStatus();
        const message = status.isRunning
          ? localize('extension.backend.statusOn', String(status.port ?? ''))
          : localize('extension.backend.statusOff');
        vscode.window.showInformationMessage(message);
      }
    }
  );

  const openConfigPageCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openConfigPage',
    () => {
      ConfigPageViewProvider.createOrShow(context, vscode.ViewColumn.Beside);
    }
  );

  // ========== Skill Marketplace（编辑器区域面板，避免侧边栏过窄） ==========
  const skillMarketplaceOutputChannel = vscode.window.createOutputChannel('Skill Marketplace');
  context.subscriptions.push(skillMarketplaceOutputChannel);

  const openSkillMarketplaceCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openSkillMarketplace',
    () => {
      SkillMarketplacePanel.createOrShow(
        context,
        skillMarketplaceOutputChannel,
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

  const scanCustomModulesCommand = vscode.commands.registerCommand(
    'aiSocialScientist.scanCustomModules',
    async () => {
      await projectStructureProvider.scanCustomModules();
    }
  );

  const testCustomModulesCommand = vscode.commands.registerCommand(
    'aiSocialScientist.testCustomModules',
    async () => {
      await projectStructureProvider.testCustomModules();
    }
  );

  const listCustomModulesCommand = vscode.commands.registerCommand(
    'aiSocialScientist.listCustomModules',
    async () => {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        vscode.window.showErrorMessage(localize('customModules.noWorkspace'));
        return;
      }

      try {
        const response = await apiClient.listCustomModules();

        if (response.success) {
          const items: string[] = [];
          if (response.total_agents > 0) {
            items.push(`Custom Agents (${response.total_agents}):`);
            response.agents.forEach(agent => {
              items.push(`  - ${agent.class_name}: ${agent.description}`);
            });
          }
          if (response.total_envs > 0) {
            items.push(`Custom Environments (${response.total_envs}):`);
            response.envs.forEach(env => {
              items.push(`  - ${env.class_name}: ${env.description}`);
            });
          }
          if (items.length === 0) {
            items.push(localize('customModules.noModules'));
          }

          const doc = await vscode.workspace.openTextDocument({
            content: items.join('\n'),
            language: 'text'
          });
          await vscode.window.showTextDocument(doc);
        } else {
          vscode.window.showErrorMessage(localize('customModules.listFailed'));
        }
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('customModules.listFailed', error.message || error));
      }
    }
  );

  const openAgentSkillDocCommand = vscode.commands.registerCommand(
    'aiSocialScientist.openAgentSkillDoc',
    async (skillName: string, skillPath: string, isBuiltin: boolean) => {
      await projectStructureProvider.openAgentSkillDoc(skillName, skillPath, isBuiltin);
    }
  );

  const updateExtensionSkillsCommand = vscode.commands.registerCommand(
    'aiSocialScientist.updateExtensionSkills',
    async () => {
      await projectStructureProvider.updateExtensionSkills();
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

  // 文献索引预览命令
  const viewLiteratureIndexCommand = vscode.commands.registerCommand(
    'aiSocialScientist.viewLiteratureIndex',
    async (item: any) => {
      if (!item || !item.filePath) {
        vscode.window.showErrorMessage(localize('extension.noLiteratureIndexPath'));
        return;
      }

      const filePath = item.filePath;

      // 检查文件是否存在
      if (!fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(localize('extension.literatureIndex.missing'));
        return;
      }

      try {
        await LiteratureIndexViewer.show(context, filePath);
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.literatureIndex.openFailed'));
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

  // 实验结果可视化命令
  const viewExperimentResultsCommand = vscode.commands.registerCommand(
    'aiSocialScientist.viewExperimentResults',
    async (item: any) => {
      let filePath: string | undefined;

      if (item && item.filePath) {
        filePath = item.filePath;
      } else {
        // 如果没有传入文件路径，让用户选择
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (!workspaceFolder) {
          vscode.window.showErrorMessage(localize('extension.experimentResults.noWorkspace'));
          return;
        }

        const files = await vscode.workspace.findFiles('**/run/experiment_results.json');
        if (files.length === 0) {
          vscode.window.showErrorMessage(localize('extension.experimentResults.notFound'));
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
            placeHolder: localize('extension.experimentResults.pickPlaceholder')
          });
          if (!selected) {
            return;
          }
          filePath = selected.path;
        }
      }

      // 检查文件是否存在
      if (!filePath || !fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(localize('extension.experimentResults.missing'));
        return;
      }

      try {
        await ExperimentResultsViewer.show(context, filePath);
      } catch (error: any) {
        vscode.window.showErrorMessage(localize('extension.experimentResults.openFailed'));
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
      await JsonViewer.show(filePath);
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
      await YamlViewer.show(filePath);
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

  // 复制文件名命令
  const copyFileNameCommand = vscode.commands.registerCommand(
    'aiSocialScientist.copyFileName',
    async (item: any) => {
      const filePath = item?.filePath;
      if (!filePath) {
        vscode.window.showErrorMessage(localize('extension.noFilePath'));
        return;
      }
      const fileName = path.basename(filePath);
      await vscode.env.clipboard.writeText(fileName);
      vscode.window.showInformationMessage(localize('extension.clipboard.fileNameCopied', fileName));
    }
  );

  // Register all commands
  context.subscriptions.push(
    initProjectCommand,
    configureEnvCommand,
    fixWorkspaceCommand,
    exportWorkspaceZipCommand,
    deleteLiteratureCommand,
    renameLiteratureCommand,
    openMarkdownInEditorCommand,
    openChatCommand,
    startBackendCommand,
    stopBackendCommand,
    restartBackendCommand,
    showBackendLogsCommand,
    showBackendStatusCommand,
    backendStatusMenuCommand,
    copyBackendUrlCommand,
    openBackendInBrowserCommand,
    openApiDocsCommand,
    openConfigPageCommand,
    openSkillMarketplaceCommand,
    openSkillSourcesSettingsCommand,
    openClaudeSkillSourcesSettingsCommand,
    refreshProjectViewCommand,
    scanCustomModulesCommand,
    testCustomModulesCommand,
    listCustomModulesCommand,
    openAgentSkillDocCommand,
    updateExtensionSkillsCommand,
    formatJsonCommand,
    viewLiteratureIndexCommand,
    viewStepsYamlCommand,
    viewExperimentResultsCommand,
    viewPidStatusCommand,
    viewJsonFileCommand,
    viewYamlFileCommand,
    openInExplorerCommand,
    copyFileNameCommand,
    copyFilePathCommand,
    copyAtReferenceCommand
  );
}

export function deactivate() {
  // 扩展停用时：停止后端服务
  if (backendManager) {
    backendManager.stop();
  }
}
