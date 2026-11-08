/**
 * 拖拽上传控制器 (Drag and Drop Controller)
 *
 * 实现 TreeDragAndDropController 接口，处理文件拖拽到树视图节点的事件。
 * 支持将本地文件或目录拖拽到"文献库"和"用户数据"节点进行上传。
 *
 * 功能特性：
 * - 递归目录复制（保留目录结构）
 * - 大文件警告（100MB阈值）
 * - 进度显示
 * - 覆盖策略确认（含取消选项）
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，将DragAndDropController注册到TreeView
 * - @extension/src/projectStructureProvider.ts - 树视图数据提供者
 */

import * as vscode from 'vscode';
import * as path from 'path';
import { getMainOutputChannel } from './shared/outputChannels';
import { ProjectItem, ProjectStructureProvider } from './projectStructureProvider';
import {localize, isExtensionZh} from './i18n';

/**
 * 文件处理信息
 */
interface FileToProcess {
  uri: vscode.Uri;
  fileName: string;
  targetUri: vscode.Uri;
  exists: boolean;
  size: number;
  relativePath?: string;  // 用于目录结构保留
}

/**
 * 覆盖策略类型
 */
type OverwriteStrategy = 'overwriteAll' | 'skipAll' | 'askEach' | 'cancel';

/**
 * 大文件阈值 (100 MB)
 */
const LARGE_FILE_THRESHOLD = 100 * 1024 * 1024;

/**
 * TreeDragAndDropController 实现
 *
 * 处理拖拽事件：
 * - dragMimeTypes: 定义可以拖拽的数据类型（文件URI）
 * - dropMimeTypes: 定义可以接收的数据类型
 * - handleDrop: 处理拖拽放置事件，将文件复制到目标目录
 */
export class ProjectDragAndDropController implements vscode.TreeDragAndDropController<ProjectItem> {
  /**
   * 构造函数
   * @param provider - 项目结构提供者，用于刷新视图
   */
  constructor(
    private provider: ProjectStructureProvider
  ) {
    // 创建输出通道用于调试日志
    this.outputChannel = getMainOutputChannel();
  }

  private outputChannel: vscode.OutputChannel;

  /**
   * 日志记录方法
   */
  private log(message: string, ...args: any[]): void {
    const timestamp = new Date().toISOString();
    const logMessage = `[${timestamp}] [DragAndDrop] ${message}`;
    console.log(logMessage, ...args);
    this.outputChannel.appendLine(logMessage + (args.length > 0 ? ` ${JSON.stringify(args)}` : ''));
  }

  /**
   * 支持的拖拽 MIME 类型
   * 'application/vnd.code.tree.projectStructureView' 是树视图内部拖拽
   * 'text/uri-list' 是文件系统文件拖拽（本地文件）
   */
  readonly dragMimeTypes = ['application/vnd.code.tree.projectStructureView', 'text/uri-list'];

  /**
   * 支持的接收 MIME 类型
   * 'text/uri-list' 表示可以接收文件URI列表
   */
  readonly dropMimeTypes = ['text/uri-list'];

  /**
   * 推断目标节点应该上传到的类型
   * 支持拖拽到：
   * - 'papers' 或 'userdata' 节点（父节点）
   * - 'paper' 节点（文献库内的文件）→ 上传到 papers
   * - 'file' 节点（用户数据内的文件）→ 根据 filePath 判断
   *
   * @returns 目标类型 ('papers' | 'userdata') 或 null（如果无法推断）
   */
  private inferTargetType(target: ProjectItem): 'papers' | 'userdata' | null {
    // 直接目标是父节点
    if (target.type === 'papers') {
      return 'papers';
    }
    if (target.type === 'userdata') {
      return 'userdata';
    }

    // 目标是文献库内的文件（paper 类型）
    if (target.type === 'paper') {
      return 'papers';
    }

    // 目标是 file 类型，需要根据其 filePath 判断
    if (target.type === 'file' && target.filePath) {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return null;
      }

      const workspacePath = workspaceFolder.uri.fsPath;
      const papersDir = path.join(workspacePath, 'papers');
      const userDataDir = path.join(workspacePath, 'user_data');

      const filePath = target.filePath;

      // 检查文件是否在 papers 目录下
      if (filePath.startsWith(papersDir)) {
        return 'papers';
      }
      // 检查文件是否在 user_data 目录下
      if (filePath.startsWith(userDataDir)) {
        return 'userdata';
      }
    }

    // 无法推断
    return null;
  }

  /**
   * 获取目标工作区文件夹
   * 如果有多个工作区，使用包含目标节点的那个
   */
  private getTargetWorkspace(_target: ProjectItem): vscode.WorkspaceFolder | undefined {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders || workspaceFolders.length === 0) {
      return undefined;
    }

    // 如果只有一个工作区，直接返回
    if (workspaceFolders.length === 1) {
      return workspaceFolders[0];
    }

    // 多工作区情况：使用 provider 的 context 判断
    // 这里简化处理：使用第一个工作区
    // TODO: 可以根据 target 的上下文来判断应该使用哪个工作区
    return workspaceFolders[0];
  }

  /**
   * 确保目标目录存在
   * @throws 如果目录创建失败且不存在
   */
  private async ensureTargetDirectory(targetDirUri: vscode.Uri): Promise<void> {
    try {
      await vscode.workspace.fs.stat(targetDirUri);
      // 目录已存在
      return;
    } catch {
      // 目录不存在，尝试创建
    }

    try {
      await vscode.workspace.fs.createDirectory(targetDirUri);
      this.log('Target directory created:', targetDirUri.toString());
    } catch (error: any) {
      const errorMsg = localize('dragDrop.mkdirFailed', targetDirUri.fsPath);
      this.log('Failed to create directory:', error.message);
      throw new Error(errorMsg);
    }
  }

  /**
   * 显示大文件警告
   * @returns true 表示继续上传，false 表示取消
   */
  private async showLargeFileWarning(
    files: FileToProcess[]
  ): Promise<boolean> {
    const largeFiles = files.filter(f => f.size >= LARGE_FILE_THRESHOLD);

    if (largeFiles.length === 0) {
      return true;
    }

    const formatSize = (bytes: number): string => {
      return (bytes / (1024 * 1024)).toFixed(1);
    };

    let message: string;
    if (largeFiles.length === 1) {
      const file = largeFiles[0];
      message = localize('dragDrop.largeFileWarning', file.fileName, formatSize(file.size));
    } else {
      message = localize('dragDrop.largeFilesWarning', String(largeFiles.length));
    }

    const continueLabel = localize('dragDrop.continue');
    const cancelLabel = localize('dragDrop.cancel');

    const response = await vscode.window.showWarningMessage(
      message,
      { modal: true },
      continueLabel,
      cancelLabel
    );

    return response === continueLabel;
  }

  /**
   * 确认覆盖策略
   * @returns 覆盖策略，'cancel' 表示取消整个操作
   */
  private async confirmOverwriteStrategy(
    existingFiles: FileToProcess[],
    totalFiles: number
  ): Promise<OverwriteStrategy> {
    // 如果只有一个文件且已存在，直接询问
    if (totalFiles === 1 && existingFiles.length === 1) {
      const file = existingFiles[0];
      const overwriteLabel = localize('dragDrop.overwrite');
      const skipLabel = localize('dragDrop.skip');
      const cancelLabel = localize('dragDrop.cancel');

      const response = await vscode.window.showWarningMessage(
        localize('dragDrop.overwriteConfirm', file.fileName),
        { modal: true },
        overwriteLabel,
        skipLabel,
        cancelLabel
      );

      if (response === overwriteLabel) {return 'overwriteAll';}
      if (response === skipLabel) {return 'skipAll';}
      return 'cancel';
    }

    // 多文件情况：显示批量策略选项
    if (existingFiles.length > 0) {
      const fileNames = existingFiles.slice(0, 3).map(f => f.fileName).join('、');
      const moreFiles = existingFiles.length > 3 ? localize('dragDrop.moreFiles', existingFiles.length - 3) : '';

      const overwriteAllLabel = localize('dragDrop.overwriteAll');
      const skipAllLabel = localize('dragDrop.skipAll');
      const askEachLabel = localize('dragDrop.askEach');
      const cancelLabel = localize('dragDrop.cancel');

      const response = await vscode.window.showWarningMessage(
        localize('dragDrop.fileExists', `${fileNames}${moreFiles}`),
        { modal: true },
        overwriteAllLabel,
        skipAllLabel,
        askEachLabel,
        cancelLabel
      );

      if (response === overwriteAllLabel) {return 'overwriteAll';}
      if (response === skipAllLabel) {return 'skipAll';}
      if (response === askEachLabel) {return 'askEach';}
      return 'cancel';
    }

    return 'overwriteAll'; // 没有已存在文件，默认覆盖
  }

  /**
   * 递归收集目录中的所有文件
   * @param sourceUri 源目录 URI
   * @param targetBasePath 目标基础路径
   * @param relativePath 相对路径（用于递归）
   * @param files 收集的文件列表
   */
  private async collectDirectoryFiles(
    sourceUri: vscode.Uri,
    targetBasePath: string,
    relativePath: string,
    files: FileToProcess[],
    token: vscode.CancellationToken
  ): Promise<void> {
    if (token.isCancellationRequested) {
      return;
    }

    try {
      const entries = await vscode.workspace.fs.readDirectory(sourceUri);

      for (const [name, fileType] of entries) {
        if (token.isCancellationRequested) {
          return;
        }

        const entryUri = sourceUri.with({ path: `${sourceUri.path}/${name}` });
        const entryRelativePath = relativePath ? `${relativePath}/${name}` : name;

        if (fileType === vscode.FileType.Directory) {
          // 递归处理子目录
          await this.collectDirectoryFiles(entryUri, targetBasePath, entryRelativePath, files, token);
        } else if (fileType === vscode.FileType.File) {
          // 获取文件信息
          try {
            const stat = await vscode.workspace.fs.stat(entryUri);
            const fileName = name || '';

            if (!fileName) {
              this.log('Empty file name in directory:', entryUri.toString());
              continue;
            }

            // 构建目标路径
            const targetPath = path.join(targetBasePath, entryRelativePath);
            const targetUri = vscode.Uri.file(targetPath);

            // 检查目标文件是否存在
            let exists = false;
            try {
              await vscode.workspace.fs.stat(targetUri);
              exists = true;
            } catch {
              exists = false;
            }

            files.push({
              uri: entryUri,
              fileName,
              targetUri,
              exists,
              size: stat.size,
              relativePath: entryRelativePath
            });

            this.log('Collected file from directory:', fileName, 'relativePath:', entryRelativePath);
          } catch (error: any) {
            this.log('Error getting file stat:', entryUri.toString(), error.message);
          }
        }
      }
    } catch (error: any) {
      const errorMsg = localize('dragDrop.directoryReadFailed', sourceUri.fsPath);
      this.log('Error reading directory:', sourceUri.toString(), error.message);
      throw new Error(errorMsg);
    }
  }

  /**
   * 收集所有待处理的文件（支持单文件和目录）
   * @returns 文件列表
   */
  private async collectFilesToProcess(
    uris: vscode.Uri[],
    targetDirPath: string,
    token: vscode.CancellationToken
  ): Promise<FileToProcess[]> {
    const files: FileToProcess[] = [];

    for (const uri of uris) {
      if (token.isCancellationRequested) {
        break;
      }

      try {
        const stat = await vscode.workspace.fs.stat(uri);

        if (stat.type === vscode.FileType.Directory) {
          // 递归收集目录文件
          const dirName = path.basename(uri.fsPath) || path.basename(uri.path) || '';
          await this.collectDirectoryFiles(uri, targetDirPath, dirName, files, token);
        } else if (stat.type === vscode.FileType.File) {
          // 单个文件
          const fileName = path.basename(uri.fsPath) || path.basename(uri.path) || '';

          if (!fileName) {
            this.log('Empty file name, skipping:', uri.toString());
            continue;
          }

          const targetPath = path.join(targetDirPath, fileName);
          const targetUri = vscode.Uri.file(targetPath);

          let exists = false;
          try {
            await vscode.workspace.fs.stat(targetUri);
            exists = true;
          } catch {
            exists = false;
          }

          files.push({
            uri,
            fileName,
            targetUri,
            exists,
            size: stat.size
          });

          this.log('Collected file:', fileName, 'exists:', exists);
        }
      } catch (error: any) {
        const fileName = path.basename(uri.fsPath) || path.basename(uri.path) || uri.toString();
        const errorMsg = localize('dragDrop.fileNotAccessible', `${fileName} (${error.message})`);
        this.log('Error processing URI:', uri.toString(), error.message);
        throw new Error(errorMsg);
      }
    }

    return files;
  }

  /**
   * 显示上传结果
   */
  private showUploadResult(
    successCount: number,
    failCount: number,
    skipCount: number,
    errors: string[],
    targetType: string
  ): void {
    const targetName = targetType === 'papers' ? localize('dragDrop.literature') : localize('dragDrop.userData');

    if (successCount > 0 && failCount === 0 && skipCount === 0) {
      vscode.window.showInformationMessage(
        localize('dragDrop.success', String(successCount), targetName)
      );
    } else if (successCount > 0 || failCount > 0 || skipCount > 0) {
      const parts: string[] = [];
      if (successCount > 0) {parts.push(localize('dragDrop.successCount', String(successCount)));}
      if (skipCount > 0) {parts.push(localize('dragDrop.skipCount', String(skipCount)));}
      if (failCount > 0) {parts.push(localize('dragDrop.failCount', String(failCount)));}

      const message = localize('dragDrop.partialSuccess', parts.join('，'));
      if (failCount > 0) {
        vscode.window.showWarningMessage(message);
      } else {
        vscode.window.showInformationMessage(message);
      }

      if (errors.length > 0) {
        this.outputChannel.show(true);
      }
    } else {
      vscode.window.showInformationMessage(localize('dragDrop.noFilesProcessed'));
    }
  }

  /**
   * 处理拖拽放置事件
   *
   * @param target - 目标节点（文献库或用户数据节点）
   * @param dataTransfer - 拖拽的数据传输对象
   * @param token - 取消令牌
   */
  async handleDrop(
    target: ProjectItem | undefined,
    dataTransfer: vscode.DataTransfer,
    token: vscode.CancellationToken
  ): Promise<void> {
    this.log('handleDrop called', { target: target?.label, targetType: target?.type });

    try {
      // 1. 验证目标节点并推断目标类型
      if (!target) {
        vscode.window.showWarningMessage(localize('dragDrop.noTarget'));
        return;
      }

      // 推断目标类型（支持拖拽到父节点或子节点）
      const inferredType = this.inferTargetType(target);
      if (!inferredType) {
        vscode.window.showWarningMessage(localize('dragDrop.invalidTarget', target.label));
        return;
      }

      // 使用推断出的类型
      const targetType = inferredType;

      // 2. 解析拖拽的文件 URI
      const transferItem = dataTransfer.get('text/uri-list');
      if (!transferItem) {
        vscode.window.showWarningMessage(localize('dragDrop.noFiles'));
        return;
      }

      const uriListString = await transferItem.asString();
      const uris = uriListString
        .split('\n')
        .map(uri => uri.trim())
        .filter(uri => uri.length > 0)
        .map(uri => {
          try {
            return vscode.Uri.parse(uri);
          } catch {
            return null;
          }
        })
        .filter((uri): uri is vscode.Uri => uri !== null);

      if (uris.length === 0) {
        vscode.window.showWarningMessage(localize('dragDrop.noValidUris'));
        return;
      }

      // 3. 获取目标工作区
      const workspaceFolder = this.getTargetWorkspace(target);
      if (!workspaceFolder) {
        vscode.window.showErrorMessage(localize('dragDrop.noWorkspace'));
        return;
      }

      // 4. 确定目标目录
      const targetDirPath = targetType === 'papers'
        ? path.join(workspaceFolder.uri.fsPath, 'papers')
        : path.join(workspaceFolder.uri.fsPath, 'user_data');
      const targetDirUri = vscode.Uri.file(targetDirPath);

      // 5. 确保目标目录存在
      try {
        await this.ensureTargetDirectory(targetDirUri);
      } catch (error: any) {
        vscode.window.showErrorMessage(error.message);
        return;
      }

      // 6. 收集所有待处理文件
      let filesToProcess: FileToProcess[] = [];
      try {
        filesToProcess = await this.collectFilesToProcess(uris, targetDirPath, token);
      } catch (error: any) {
        if (error instanceof Error) {
          vscode.window.showErrorMessage(error.message);
        }
        return;
      }

      if (filesToProcess.length === 0) {
        vscode.window.showInformationMessage(localize('dragDrop.noFilesProcessed'));
        return;
      }

      if (token.isCancellationRequested) {
        return;
      }

      // 7. 大文件警告
      const shouldContinue = await this.showLargeFileWarning(filesToProcess);
      if (!shouldContinue) {
        vscode.window.showInformationMessage(localize('dragDrop.cancelled'));
        return;
      }

      // 8. 覆盖策略确认
      const existingFiles = filesToProcess.filter(f => f.exists);
      let overwriteStrategy: OverwriteStrategy = 'askEach';

      if (existingFiles.length > 0) {
        overwriteStrategy = await this.confirmOverwriteStrategy(existingFiles, filesToProcess.length);
        if (overwriteStrategy === 'cancel') {
          vscode.window.showInformationMessage(localize('dragDrop.cancelled'));
          return;
        }
      }

      // 9. 使用进度显示处理文件
      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('dragDrop.uploading'),
          cancellable: true
        },
        async (progress, progressToken) => {
          let successCount = 0;
          let failCount = 0;
          let skipCount = 0;
          const errors: string[] = [];

          for (let i = 0; i < filesToProcess.length; i++) {
            if (progressToken.isCancellationRequested) {
              this.log('Operation cancelled by user');
              break;
            }

            const fileInfo = filesToProcess[i];
            progress.report({
              message: localize('dragDrop.processing', fileInfo.fileName, String(i + 1), String(filesToProcess.length))
            });

            try {
              // 如果文件已存在，根据策略决定
              if (fileInfo.exists) {
                let shouldOverwrite = false;

                if (overwriteStrategy === 'overwriteAll') {
                  shouldOverwrite = true;
                } else if (overwriteStrategy === 'skipAll') {
                  shouldOverwrite = false;
                } else {
                  // 逐个询问
                  const overwriteLabel = localize('dragDrop.overwrite');
                  const skipLabel = localize('dragDrop.skip');
                  const cancelLabel = localize('dragDrop.cancel');

                  const response = await vscode.window.showWarningMessage(
                    localize('dragDrop.overwriteConfirm', fileInfo.fileName),
                    { modal: false },
                    overwriteLabel,
                    skipLabel,
                    cancelLabel
                  );

                  if (response === cancelLabel) {
                    break;
                  }
                  shouldOverwrite = response === overwriteLabel;
                }

                if (!shouldOverwrite) {
                  skipCount++;
                  continue;
                }
              }

              // 确保目标文件的父目录存在（用于目录结构保留）
              if (fileInfo.relativePath && fileInfo.relativePath.includes('/')) {
                const parentDirUri = vscode.Uri.file(path.dirname(fileInfo.targetUri.fsPath));
                try {
                  await vscode.workspace.fs.createDirectory(parentDirUri);
                } catch {
                  // 目录可能已存在，忽略
                }
              }

              // 复制文件
              const fileData = await vscode.workspace.fs.readFile(fileInfo.uri);
              await vscode.workspace.fs.writeFile(fileInfo.targetUri, fileData);
              successCount++;

            } catch (error: any) {
              const errorMsg = `${fileInfo.fileName}: ${error.message || error}`;
              this.log('Error copying file:', errorMsg);
              errors.push(errorMsg);
              failCount++;
            }
          }

          return { successCount, failCount, skipCount, errors };
        }
      );

      // 10. 显示结果
      this.showUploadResult(result.successCount, result.failCount, result.skipCount, result.errors, targetType);

      // 11. 自动解析上传的 PDF 文件
      if (result.successCount > 0) {
        const uploadedFiles = filesToProcess.filter((_, index) =>
          result.errors.length === 0 || !result.errors[index]
        );
        await this.parseUploadedFiles(uploadedFiles, targetType);
      }

      // 12. 如果有成功，刷新视图
      if (result.successCount > 0) {
        this.provider.refresh();
      }

    } catch (error: any) {
      const errorMsg = localize('dragDrop.error', error.message || error);
      this.log('Unexpected error:', errorMsg, error);
      vscode.window.showErrorMessage(errorMsg);
      this.outputChannel.show(true);
    }
  }

  private async parseUploadedFiles(
    files: FileToProcess[],
    targetType: 'papers' | 'userdata'
  ): Promise<void> {
    if (targetType !== 'papers' || files.length === 0) {
      return;
    }

    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      return;
    }

    const { ingestLocalFile } = await import('./services/literatureIngest');
    let added = 0;
    let duplicates = 0;
    const errors: string[] = [];
    const isZh = isExtensionZh();

    for (const file of files) {
      const ext = path.extname(file.fileName).toLowerCase();
      if (!['.pdf', '.md', '.markdown', '.txt'].includes(ext)) {
        continue;
      }
      try {
        const payload = await ingestLocalFile(
          workspaceFolder.uri.fsPath,
          file.targetUri.fsPath
        );
        if (!payload.ok) {
          errors.push(payload.error || file.fileName);
          continue;
        }
        if (payload.duplicate) {
          duplicates += 1;
        } else if (payload.added) {
          added += 1;
        }
      } catch (error: any) {
        errors.push(`${file.fileName}: ${error.message || error}`);
        this.log('Failed to index uploaded literature file', error);
      }
    }

    if (added > 0 || duplicates > 0) {
      this.provider.refresh();
    }

    if (errors.length > 0) {
      vscode.window.showWarningMessage(
        isZh
          ? `部分文件未写入文献索引（${errors.length}）：${errors[0]}`
          : `Some files were not indexed (${errors.length}): ${errors[0]}`
      );
    } else if (added > 0) {
      vscode.window.showInformationMessage(
        isZh
          ? `已写入文献索引 ${added} 篇${duplicates ? `，跳过重复 ${duplicates} 篇` : ''}`
          : `Indexed ${added} item(s)${duplicates ? `, skipped ${duplicates} duplicate(s)` : ''}`
      );
    }
  }

  /**
   * 清理资源
   */
  dispose(): void {
  }
}
