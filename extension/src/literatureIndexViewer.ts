/**
 * 文献索引预览器 - 以友好方式显示 literature_index.json
 *
 * 关联文件：
 * - @extension/src/extension.ts - 注册命令
 * - @extension/src/projectStructureProvider.ts - 文献索引节点
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { filePathToAtReference } from './atReference';
import { openWorkspaceFile } from './openWorkspaceFile';
import { isExtensionZh } from './i18n';
import {
  downloadLiteraturePdfs,
  exportLiteratureBibtex,
  importLiteratureBibtex,
  ingestByIdentifier,
  ingestLocalFile,
  syncLiteratureLibrary,
  type LiteratureSyncPayload,
} from './services/literatureIngest';

interface LiteratureEntry {
  title?: string;
  file_path?: string;
  authors?: string[];
  year?: number;
  abstract?: string;
  keywords?: string[];
  doi?: string;
  url?: string;
  journal?: string;
  at_ref?: string;
  extra_fields?: {
    article_id?: string;
    [key: string]: any;
  };
  [key: string]: any;
}

interface LiteratureIndex {
  version?: string;
  created_at?: string;
  updated_at?: string;
  entries?: LiteratureEntry[];
}

export class LiteratureIndexViewer {
  private static currentPanel: vscode.WebviewPanel | undefined;

  private static safeWorkspacePath(workspaceRoot: string, filePath: string): string | undefined {
    const candidatePath = path.isAbsolute(filePath)
      ? path.normalize(filePath)
      : path.normalize(path.join(workspaceRoot, filePath));
    const relative = path.relative(workspaceRoot, candidatePath);
    const isInside = relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
    return isInside ? candidatePath : undefined;
  }

  private static reloadIndex(indexPath: string): LiteratureIndex {
    const content = fs.readFileSync(indexPath, 'utf-8');
    return JSON.parse(content) as LiteratureIndex;
  }

  private static refreshPanel(panel: vscode.WebviewPanel, indexPath: string): void {
    const data = this.reloadIndex(indexPath);
    this.updateWebview(panel, data, indexPath);
    void vscode.commands.executeCommand('aiSocialScientist.refreshProjectView');
  }

  private static async handleAddByIdentifier(
    panel: vscode.WebviewPanel,
    indexPath: string,
    identifier: string
  ): Promise<void> {
    const isZh = isExtensionZh();
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const raw = identifier.trim();
    if (!workspaceFolder || !raw) {
      vscode.window.showWarningMessage(isZh ? '请输入 DOI 或 arXiv 编号。' : 'Enter a DOI or arXiv id.');
      return;
    }

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: isZh ? '正在查询文献元数据…' : 'Looking up bibliographic metadata…',
      },
      async () => {
        try {
          const payload = await ingestByIdentifier(workspaceFolder.uri.fsPath, raw);
          if (!payload.ok) {
            throw new Error(payload.error || 'Lookup failed');
          }
          this.refreshPanel(panel, indexPath);
          if (payload.duplicate) {
            vscode.window.showWarningMessage(
              isZh
                ? `已在库中：${payload.title || raw}`
                : `Already in library: ${payload.title || raw}`
            );
          } else {
            vscode.window.showInformationMessage(
              isZh ? `已添加：${payload.title || raw}` : `Added: ${payload.title || raw}`
            );
          }
        } catch (error: any) {
          vscode.window.showErrorMessage(
            isZh
              ? `添加失败: ${error.message || error}`
              : `Add failed: ${error.message || error}`
          );
        }
      }
    );
  }

  private static async handleUploadFiles(
    panel: vscode.WebviewPanel,
    indexPath: string
  ): Promise<void> {
    const isZh = isExtensionZh();
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showWarningMessage(isZh ? '请先打开工作区。' : 'Open a workspace first.');
      return;
    }

    const uris = await vscode.window.showOpenDialog({
      canSelectMany: true,
      openLabel: isZh ? '添加到文献库' : 'Add to library',
      filters: {
        Literature: ['pdf', 'md', 'markdown', 'txt'],
      },
    });
    if (!uris || uris.length === 0) {
      return;
    }

    let added = 0;
    let duplicates = 0;
    const errors: string[] = [];
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: isZh ? '正在导入文献文件…' : 'Importing literature files…',
      },
      async () => {
        for (const uri of uris) {
          try {
            const payload = await ingestLocalFile(workspaceFolder.uri.fsPath, uri.fsPath);
            if (!payload.ok) {
              errors.push(payload.error || uri.fsPath);
              continue;
            }
            if (payload.duplicate) {
              duplicates += 1;
            } else if (payload.added) {
              added += 1;
            }
          } catch (error: any) {
            errors.push(`${path.basename(uri.fsPath)}: ${error.message || error}`);
          }
        }
      }
    );

    this.refreshPanel(panel, indexPath);
    if (errors.length > 0) {
      vscode.window.showErrorMessage(
        isZh
          ? `部分文件导入失败（${errors.length}）：${errors[0]}`
          : `Some imports failed (${errors.length}): ${errors[0]}`
      );
    } else if (added > 0) {
      vscode.window.showInformationMessage(
        isZh
          ? `已添加 ${added} 篇${duplicates ? `，跳过重复 ${duplicates} 篇` : ''}`
          : `Added ${added} item(s)${duplicates ? `, skipped ${duplicates} duplicate(s)` : ''}`
      );
    } else if (duplicates > 0) {
      vscode.window.showWarningMessage(
        isZh ? `全部为重复条目（${duplicates}）` : `All ${duplicates} item(s) already in library`
      );
    }
  }

  private static parseEntryIds(raw: unknown): number[] | undefined {
    if (!Array.isArray(raw) || raw.length === 0) {
      return undefined;
    }
    const ids = raw
      .map((value) => Number(value))
      .filter((value) => Number.isInteger(value) && value >= 0);
    return ids.length > 0 ? ids : undefined;
  }

  private static formatSyncSummary(payload: LiteratureSyncPayload, isZh: boolean): string {
    const meta = payload.metadata_updated ?? 0;
    const pdf = payload.pdf_downloaded ?? 0;
    const noCand = payload.pdf_no_candidate ?? 0;
    const failed = (payload.metadata_failed ?? 0) + (payload.pdf_failed ?? 0);
    if (isZh) {
      return `同步完成：补全元数据 ${meta}，下载原文 ${pdf}`
        + (noCand ? `，无开放 PDF ${noCand}` : '')
        + (failed ? `，失败 ${failed}` : '')
        + '（公开接口，不使用文献 MCP）';
    }
    return `Sync done: metadata ${meta}, PDFs ${pdf}`
      + (noCand ? `, no OA PDF ${noCand}` : '')
      + (failed ? `, failed ${failed}` : '')
      + ' (public APIs only; literature MCP not used)';
  }

  private static async handleSyncLibrary(
    panel: vscode.WebviewPanel,
    indexPath: string,
    entryIds?: number[]
  ): Promise<void> {
    const isZh = isExtensionZh();
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showWarningMessage(isZh ? '请先打开工作区。' : 'Open a workspace first.');
      return;
    }

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: isZh
          ? '正在同步完善（公开元数据 + 开放 PDF）…'
          : 'Syncing library (public metadata + OA PDFs)…',
      },
      async () => {
        try {
          const payload = await syncLiteratureLibrary(workspaceFolder.uri.fsPath, entryIds);
          if (!payload.ok) {
            throw new Error(payload.error || 'Sync failed');
          }
          this.refreshPanel(panel, indexPath);
          vscode.window.showInformationMessage(this.formatSyncSummary(payload, isZh));
        } catch (error: any) {
          vscode.window.showErrorMessage(
            isZh
              ? `同步失败: ${error.message || error}`
              : `Sync failed: ${error.message || error}`
          );
        }
      }
    );
  }

  private static async handleDownloadPdfs(
    panel: vscode.WebviewPanel,
    indexPath: string,
    entryIds: number[]
  ): Promise<void> {
    const isZh = isExtensionZh();
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder || entryIds.length === 0) {
      vscode.window.showWarningMessage(
        isZh ? '请先选择要下载原文的文献。' : 'Select articles to download first.'
      );
      return;
    }

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: isZh ? '正在尝试下载开放原文…' : 'Trying open-access PDF download…',
      },
      async () => {
        try {
          const payload = await downloadLiteraturePdfs(
            workspaceFolder.uri.fsPath,
            entryIds,
            true
          );
          if (!payload.ok) {
            throw new Error(payload.error || 'Download failed');
          }
          this.refreshPanel(panel, indexPath);
          vscode.window.showInformationMessage(this.formatSyncSummary(payload, isZh));
        } catch (error: any) {
          vscode.window.showErrorMessage(
            isZh
              ? `下载失败: ${error.message || error}`
              : `Download failed: ${error.message || error}`
          );
        }
      }
    );
  }

  private static async handleExportBib(
    entryIds?: number[],
    mode: 'copy' | 'file' = 'copy'
  ): Promise<void> {
    const isZh = isExtensionZh();
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showWarningMessage(isZh ? '请先打开工作区。' : 'Open a workspace first.');
      return;
    }

    try {
      const payload = await exportLiteratureBibtex(
        workspaceFolder.uri.fsPath,
        entryIds,
        mode === 'copy'
      );
      if (!payload.ok) {
        throw new Error(payload.error || 'Export failed');
      }
      const bibtex = typeof payload.bibtex === 'string' ? payload.bibtex : '';
      if (!bibtex.trim()) {
        vscode.window.showWarningMessage(isZh ? '没有可导出的条目。' : 'Nothing to export.');
        return;
      }
      if (mode === 'copy') {
        await vscode.env.clipboard.writeText(bibtex);
        vscode.window.showInformationMessage(
          isZh
            ? `已复制 ${payload.count ?? 0} 条 BibTeX`
            : `Copied ${payload.count ?? 0} BibTeX entr(y/ies)`
        );
      } else {
        vscode.window.showInformationMessage(
          isZh
            ? `已写入 ${payload.path || 'papers/library.bib'}（${payload.count ?? 0} 条）`
            : `Wrote ${payload.path || 'papers/library.bib'} (${payload.count ?? 0})`
        );
        void vscode.commands.executeCommand('aiSocialScientist.refreshProjectView');
      }
    } catch (error: any) {
      vscode.window.showErrorMessage(
        isZh
          ? `导出 BibTeX 失败: ${error.message || error}`
          : `BibTeX export failed: ${error.message || error}`
      );
    }
  }

  private static async handleImportBib(
    panel: vscode.WebviewPanel,
    indexPath: string
  ): Promise<void> {
    const isZh = isExtensionZh();
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showWarningMessage(isZh ? '请先打开工作区。' : 'Open a workspace first.');
      return;
    }

    const uris = await vscode.window.showOpenDialog({
      canSelectMany: false,
      openLabel: isZh ? '导入 BibTeX' : 'Import BibTeX',
      filters: { BibTeX: ['bib'] },
    });
    if (!uris || uris.length === 0) {
      return;
    }

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: isZh ? '正在导入 BibTeX…' : 'Importing BibTeX…',
      },
      async () => {
        try {
          const payload = await importLiteratureBibtex(
            workspaceFolder.uri.fsPath,
            uris[0].fsPath
          );
          if (!payload.ok) {
            throw new Error(payload.error || 'Import failed');
          }
          this.refreshPanel(panel, indexPath);
          vscode.window.showInformationMessage(
            isZh
              ? `导入完成：新增 ${payload.added ?? 0}，重复 ${payload.duplicates ?? 0}`
              : `Import done: added ${payload.added ?? 0}, duplicates ${payload.duplicates ?? 0}`
          );
        } catch (error: any) {
          vscode.window.showErrorMessage(
            isZh
              ? `导入失败: ${error.message || error}`
              : `Import failed: ${error.message || error}`
          );
        }
      }
    );
  }

  public static async show(context: vscode.ExtensionContext, filePath: string): Promise<void> {
    // 读取 JSON 文件
    let data: LiteratureIndex;
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      data = JSON.parse(content);
    } catch (error: any) {
      const isZh = isExtensionZh();
      vscode.window.showErrorMessage(isZh ? `无法读取文献索引: ${error.message}` : `Could not read literature index: ${error.message}`);
      return;
    }

    // 如果已有面板，复用它
    if (this.currentPanel) {
      this.currentPanel.reveal(vscode.ViewColumn.One);
      this.updateWebview(this.currentPanel, data, filePath);
      return;
    }

    // 创建新的 webview 面板
    const panel = vscode.window.createWebviewPanel(
      'literatureIndexViewer',
      isExtensionZh() ? '文献索引预览' : 'Literature Index',
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      }
    );

    this.currentPanel = panel;

    // 处理面板关闭
    panel.onDidDispose(() => {
      this.currentPanel = undefined;
    });

    // 处理来自 webview 的消息
    panel.webview.onDidReceiveMessage(
      async (message) => {
        if (message.command === 'openFile') {
          try {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (workspaceFolder && message.filePath) {
              const workspaceRoot = workspaceFolder.uri.fsPath;
              // 仅允许打开工作区内文件：防止通过 ../ 进行路径穿越
              const requested = String(message.filePath);
              const candidatePath = this.safeWorkspacePath(workspaceRoot, requested);
              if (!candidatePath) {
                throw new Error('Refused to open a path outside the workspace');
              }

              await openWorkspaceFile(candidatePath);
            }
          } catch (error: any) {
            const isZh = isExtensionZh();
            vscode.window.showErrorMessage(isZh ? `无法打开文件: ${error.message}` : `Could not open file: ${error.message}`);
          }
        } else if (message.command === 'openUrl') {
          // 打开外部链接（DOI、URL 等）
          if (message.url) {
            const url = String(message.url);
            if (!/^https?:\/\//i.test(url)) {
              vscode.window.showWarningMessage('Blocked non-http(s) URL');
              return;
            }
            vscode.env.openExternal(vscode.Uri.parse(url));
          }
        } else if (message.command === 'copyAtReference') {
          const wf = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
          const atReference =
            typeof message.atReference === 'string' && message.atReference
              ? message.atReference
              : message.filePath
                ? filePathToAtReference(wf, message.filePath)
                : '';
          if (atReference) {
            vscode.env.clipboard.writeText(atReference);
            const isZh = isExtensionZh();
            vscode.window.showInformationMessage(isZh ? `已复制: ${atReference}` : `Copied: ${atReference}`);
          }
        } else if (message.command === 'copyText') {
          const text = typeof message.text === 'string' ? message.text : '';
          if (text) {
            await vscode.env.clipboard.writeText(text);
            const isZh = isExtensionZh();
            const count = typeof message.count === 'number' ? message.count : undefined;
            vscode.window.showInformationMessage(
              count
                ? (isZh ? `已复制 ${count} 条` : `Copied ${count} item(s)`)
                : (isZh ? '已复制到剪贴板' : 'Copied to clipboard')
            );
          } else {
            const isZh = isExtensionZh();
            vscode.window.showWarningMessage(
              typeof message.emptyMessage === 'string' && message.emptyMessage
                ? message.emptyMessage
                : (isZh ? '没有可复制的内容' : 'Nothing to copy')
            );
          }
        } else if (message.command === 'addByIdentifier') {
          const identifier = typeof message.identifier === 'string' ? message.identifier : '';
          await this.handleAddByIdentifier(panel, filePath, identifier);
        } else if (message.command === 'uploadFiles') {
          await this.handleUploadFiles(panel, filePath);
        } else if (message.command === 'syncLibrary') {
          await this.handleSyncLibrary(panel, filePath, this.parseEntryIds(message.entryIds));
        } else if (message.command === 'downloadPdfs') {
          const ids = this.parseEntryIds(message.entryIds) || [];
          await this.handleDownloadPdfs(panel, filePath, ids);
        } else if (message.command === 'exportBib') {
          const mode = message.mode === 'file' ? 'file' : 'copy';
          await this.handleExportBib(this.parseEntryIds(message.entryIds), mode);
        } else if (message.command === 'importBib') {
          await this.handleImportBib(panel, filePath);
        } else if (message.command === 'refresh') {
          try {
            this.refreshPanel(panel, filePath);
          } catch (error: any) {
            const isZh = isExtensionZh();
            vscode.window.showErrorMessage(
              isZh ? `刷新失败: ${error.message}` : `Refresh failed: ${error.message}`
            );
          }
        } else if (message.command === 'deleteEntry') {
          const isZh = isExtensionZh();
          const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
          const entryId = typeof message.entryId === 'string' ? message.entryId : '';
          const title = typeof message.title === 'string' && message.title ? message.title : entryId;
          if (!workspaceFolder || !entryId) {
            vscode.window.showWarningMessage(isZh ? '无法定位要删除的文献记录。' : 'Could not locate the literature entry to delete.');
            return;
          }

          const confirm = await vscode.window.showWarningMessage(
            isZh
              ? `删除「${title}」？将同时移除索引记录，并尝试删除本地 Markdown/PDF 文件。`
              : `Delete "${title}"? This removes the index entry and tries to delete local Markdown/PDF files.`,
            { modal: true },
            isZh ? '删除' : 'Delete'
          );
          if (confirm !== (isZh ? '删除' : 'Delete')) {
            return;
          }

          try {
            const workspaceRoot = workspaceFolder.uri.fsPath;
            const indexPath = filePath;
            const currentData = JSON.parse(fs.readFileSync(indexPath, 'utf-8')) as LiteratureIndex;
            const currentEntries = Array.isArray(currentData.entries) ? currentData.entries : [];
            const entryIndex = Number(entryId);
            if (!Number.isInteger(entryIndex) || entryIndex < 0 || entryIndex >= currentEntries.length) {
              throw new Error('Entry no longer exists in the literature index');
            }

            const [removed] = currentEntries.splice(entryIndex, 1);
            const filesToDelete = [
              removed?.file_path,
              removed?.filePath,
              removed?.path,
              removed?.extra_fields?.full_text?.file_path,
            ].filter((value): value is string => typeof value === 'string' && !!value);

            for (const relPath of filesToDelete) {
              const target = this.safeWorkspacePath(workspaceRoot, relPath);
              if (target && fs.existsSync(target) && fs.statSync(target).isFile()) {
                fs.unlinkSync(target);
              }
            }

            currentData.entries = currentEntries;
            currentData.updated_at = new Date().toISOString();
            fs.writeFileSync(indexPath, JSON.stringify(currentData, null, 2), 'utf-8');
            this.updateWebview(panel, currentData, indexPath);
            void vscode.commands.executeCommand('aiSocialScientist.refreshProjectView');
            vscode.window.showInformationMessage(isZh ? `已删除「${title}」` : `Deleted "${title}"`);
          } catch (error: any) {
            vscode.window.showErrorMessage(isZh ? `删除失败: ${error.message}` : `Delete failed: ${error.message}`);
          }
        }
      },
      undefined,
      context.subscriptions
    );

    // 更新内容
    this.updateWebview(panel, data, filePath);
  }

  private static updateWebview(
    panel: vscode.WebviewPanel,
    data: LiteratureIndex,
    _filePath: string
  ): void {
    const rawEntries = data.entries || [];
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const workspaceRoot = workspaceFolder?.uri.fsPath;
    const entries: LiteratureEntry[] = rawEntries.map((e, index) => {
      const filePath =
        typeof e.file_path === 'string' && e.file_path
          ? e.file_path
          : typeof e.filePath === 'string' && e.filePath
            ? e.filePath
            : typeof e.path === 'string' && e.path
              ? e.path
              : '';
      return {
        ...e,
        file_path: filePath,
        at_ref: typeof e.at_ref === 'string' && e.at_ref
          ? e.at_ref
          : filePath
            ? filePathToAtReference(workspaceRoot, filePath)
            : '',
        _entry_id: String(index),
      };
    });
    const total = entries.length;

    // 获取当前语言
    const isChinese = isExtensionZh();
    const jsonForScript = (value: unknown) =>
      JSON.stringify(value).replace(/</g, '\\u003c');

    panel.webview.html = `
<!DOCTYPE html>
<html lang="${isChinese ? 'zh-CN' : 'en'}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${isChinese ? '文献索引预览' : 'Literature Index Viewer'}</title>
  <style>
    :root {
      --lit-entry-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
      --lit-entry-bg: var(--vscode-editor-background);
    }

    body.vscode-dark,
    body.vscode-high-contrast {
      --lit-entry-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
      --lit-entry-bg: var(--vscode-editorWidget-background, var(--vscode-editor-background));
    }

    body {
      font-family: var(--vscode-font-family);
      background-color: var(--vscode-editor-background);
      color: var(--vscode-editor-foreground);
      padding: 20px;
      max-width: 1200px;
      margin: 0 auto;
    }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      padding-bottom: 15px;
      border-bottom: 1px solid var(--vscode-panel-border);
    }

    .subtitle {
      margin-top: 6px;
      color: var(--vscode-descriptionForeground);
      font-size: 13px;
    }

    .header h1 {
      margin: 0;
      font-size: 24px;
    }

    .stats {
      color: var(--vscode-descriptionForeground);
      font-size: 14px;
    }

    .toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: stretch;
      gap: 12px;
      margin-bottom: 14px;
    }

    .search-box {
      flex: 1 1 220px;
      min-width: 0;
    }

    .toolbar-tools {
      flex: 0 1 auto;
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }

    .search-box input {
      width: 100%;
      padding: 10px 15px;
      font-size: 14px;
      border: 1px solid var(--vscode-input-border);
      background-color: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      border-radius: 4px;
      outline: none;
    }

    .search-box input:focus {
      border-color: var(--vscode-focusBorder);
    }

    .result-line {
      color: var(--vscode-descriptionForeground);
      font-size: 12px;
      margin-bottom: 12px;
    }

    .entry {
      background-color: var(--lit-entry-bg);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 8px;
      padding: 15px;
      margin-bottom: 15px;
      transition: box-shadow 0.2s;
    }

    .entry:hover {
      box-shadow: var(--lit-entry-shadow);
    }

    .entry-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 10px;
    }

    .entry-title {
      font-size: 16px;
      font-weight: 600;
      color: var(--vscode-textLink-foreground);
      cursor: pointer;
      flex: 1;
    }

    .entry-title:hover {
      text-decoration: underline;
    }

    .entry-year {
      background-color: var(--vscode-badge-background);
      color: var(--vscode-badge-foreground);
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 12px;
      margin-left: 10px;
      white-space: nowrap;
    }

    .entry-authors {
      color: var(--vscode-descriptionForeground);
      font-size: 13px;
      margin-bottom: 8px;
    }

    .entry-abstract {
      font-size: 13px;
      line-height: 1.5;
      color: var(--vscode-editor-foreground);
      margin-bottom: 10px;
    }

    .entry-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      font-size: 12px;
    }

    .keyword {
      background-color: var(--vscode-input-background);
      color: var(--vscode-descriptionForeground);
      padding: 2px 8px;
      border-radius: 4px;
      border: 1px solid var(--vscode-input-border);
    }

    .file-path {
      color: var(--vscode-textLink-foreground);
      font-size: 12px;
      margin-top: 8px;
      font-family: var(--vscode-editor-font-family);
      word-break: break-all;
    }

    .empty-state {
      text-align: center;
      padding: 48px 24px;
      color: var(--vscode-descriptionForeground);
      border: 1px dashed var(--vscode-panel-border);
      border-radius: 8px;
      background-color: var(--vscode-input-background);
    }

    .empty-state h2 {
      margin: 0 0 8px;
      font-size: 18px;
      color: var(--vscode-editor-foreground);
    }

    .empty-state p {
      margin: 0 0 20px;
      font-size: 13px;
      line-height: 1.5;
    }

    .empty-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: center;
      margin-bottom: 16px;
    }

    .ingest-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 14px;
      padding: 12px;
      border: 1px solid var(--vscode-panel-border);
      border-radius: 8px;
      background-color: var(--vscode-input-background);
    }

    .ingest-bar input[type="text"] {
      flex: 1 1 240px;
      min-width: 0;
      padding: 8px 12px;
      font-size: 13px;
      border: 1px solid var(--vscode-input-border);
      background-color: var(--vscode-editor-background);
      color: var(--vscode-input-foreground);
      border-radius: 4px;
      outline: none;
    }

    .ingest-bar input[type="text"]:focus {
      border-color: var(--vscode-focusBorder);
    }

    .hidden-when-empty {
      display: block;
    }

    body.is-empty .hidden-when-empty {
      display: none;
    }

    .filter-group {
      display: flex;
      gap: 10px;
      margin-bottom: 0;
      align-items: center;
      flex-shrink: 0;
    }

    .filter-btn {
      padding: 6px 12px;
      border: 1px solid var(--vscode-button-border);
      background-color: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }

    .filter-btn:hover {
      background-color: var(--vscode-button-secondaryHoverBackground);
    }

    .filter-btn.active {
      background-color: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }

    .sort-select {
      padding: 6px 12px;
      border: 1px solid var(--vscode-input-border);
      background-color: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      border-radius: 4px;
      font-size: 12px;
      min-width: 148px;
      max-width: min(100%, 280px);
      flex: 0 0 auto;
    }

    .entry-actions {
      display: flex;
      gap: 8px;
      margin-top: 10px;
      flex-wrap: wrap;
    }

    .action-btn {
      padding: 4px 10px;
      border: 1px solid var(--vscode-button-border);
      background-color: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      border-radius: 4px;
      cursor: pointer;
      font-size: 11px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }

    .action-btn:hover {
      background-color: var(--vscode-button-secondaryHoverBackground);
    }

    .action-btn.primary {
      background-color: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }

    .action-btn.primary:hover {
      background-color: var(--vscode-button-hoverBackground);
    }

    .action-btn.danger {
      border-color: var(--vscode-errorForeground);
      color: var(--vscode-errorForeground);
    }

    .action-btn.danger:hover {
      background-color: var(--vscode-inputValidation-errorBackground);
    }

    .entry-journal {
      color: var(--vscode-textPreformat-foreground);
      font-size: 12px;
      font-style: italic;
      margin-bottom: 6px;
    }

    .abstract-toggle {
      color: var(--vscode-textLink-foreground);
      cursor: pointer;
      font-size: 12px;
      margin-top: 4px;
      display: inline-block;
    }

    .abstract-toggle:hover {
      text-decoration: underline;
    }

    .abstract-full {
      display: none;
    }

    .abstract-full.show {
      display: block;
    }

    .abstract-preview {
      display: block;
    }

    .abstract-preview.hide {
      display: none;
    }

    .doi-link {
      color: var(--vscode-textLink-foreground);
      font-size: 11px;
      font-family: var(--vscode-editor-font-family);
    }

    .doi-link:hover {
      text-decoration: underline;
    }
    .batch-actions {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
      padding: 10px 12px;
      background-color: var(--vscode-input-background);
      border-radius: 6px;
      align-items: center;
      flex-wrap: wrap;
    }
    .batch-btn {
      padding: 6px 12px;
      background-color: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      border: 1px solid var(--vscode-button-border);
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }
    .batch-btn:hover {
      background-color: var(--vscode-button-secondaryHoverBackground);
    }
    .batch-btn.primary {
      background-color: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
    }
    .batch-btn.primary:hover {
      background-color: var(--vscode-button-hoverBackground);
    }
    .select-all-checkbox {
      margin-right: 8px;
    }

    @media (max-width: 720px) {
      body {
        padding: 12px;
      }
      .header,
      .entry-header,
      .toolbar {
        display: block;
      }
      .stats,
      .entry-year {
        margin-top: 8px;
        margin-left: 0;
      }
    }
  </style>
</head>
<body class="${total === 0 ? 'is-empty' : ''}">
  <div class="header">
    <div>
      <h1>${isChinese ? '文献库' : 'Literature Library'}</h1>
      <div class="subtitle">${isChinese ? '上传 PDF、粘贴 DOI 或导入 Bib；可同步补全元数据与开放原文。主题检索请用文献技能。' : 'Upload PDFs, paste a DOI, or import BibTeX. Sync fills metadata and open-access PDFs. Use the literature skill for topic search.'}</div>
    </div>
    <div class="stats">
      ${isChinese ? `共 ${total} 篇文献` : `${total} articles`}
      ${data.updated_at ? `<br>${isChinese ? '更新于' : 'Updated'}: ${new Date(data.updated_at).toLocaleString()}` : ''}
    </div>
  </div>

  <div class="ingest-bar">
    <input type="text" id="doiInput" placeholder="${isChinese ? '粘贴 DOI 或 arXiv 编号，例如 10.1038/... 或 1706.03762' : 'Paste DOI or arXiv id, e.g. 10.1038/... or 1706.03762'}" />
    <button class="batch-btn primary" id="addDoiBtn">${isChinese ? '用 DOI 添加' : 'Add by DOI'}</button>
    <button class="batch-btn" id="uploadBtn">${isChinese ? '上传 PDF / MD' : 'Upload PDF / MD'}</button>
    <button class="batch-btn" id="importBibBtn">${isChinese ? '导入 Bib' : 'Import Bib'}</button>
    <button class="batch-btn" id="syncBtn" title="${isChinese ? '补全缺失的作者/年份/摘要等，并尝试下载开放获取 PDF' : 'Fill missing authors/year/abstract and try open-access PDF download'}">${isChinese ? '同步完善' : 'Sync & Fill'}</button>
    <button class="batch-btn" id="refreshBtn">${isChinese ? '刷新' : 'Refresh'}</button>
  </div>

  <div class="toolbar hidden-when-empty">
    <div class="search-box">
      <input type="text" id="searchInput" placeholder="${isChinese ? '搜索标题、作者、摘要或关键词...' : 'Search title, authors, abstract, or keywords...'}" />
    </div>
    <div class="toolbar-tools">
      <div class="filter-group">
        <select id="sortSelect" class="sort-select">
          <option value="default">${isChinese ? '默认排序' : 'Default Order'}</option>
          <option value="year-desc">${isChinese ? '年份 (新→旧)' : 'Year (New→Old)'}</option>
          <option value="year-asc">${isChinese ? '年份 (旧→新)' : 'Year (Old→New)'}</option>
          <option value="title">${isChinese ? '标题 A-Z' : 'Title A-Z'}</option>
        </select>
      </div>
    </div>
  </div>
  <div id="resultLine" class="result-line hidden-when-empty"></div>

  <div class="batch-actions hidden-when-empty">
    <input type="checkbox" id="selectAll" class="select-all-checkbox" />
    <label for="selectAll" style="font-size: 12px; margin-right: 12px;">${isChinese ? '全选' : 'Select All'}</label>
    <button class="batch-btn primary" id="copySelectedBtn">${isChinese ? '复制选中 @引用' : 'Copy Selected @Refs'}</button>
    <button class="batch-btn" id="downloadSelectedBtn">${isChinese ? '下载选中原文' : 'Download Selected PDFs'}</button>
    <button class="batch-btn" id="copyBibBtn">${isChinese ? '复制 BibTeX' : 'Copy BibTeX'}</button>
    <button class="batch-btn" id="writeBibBtn">${isChinese ? '写入 library.bib' : 'Write library.bib'}</button>
    <button class="batch-btn" id="exportBtn">${isChinese ? '复制列表 CSV' : 'Copy List CSV'}</button>
  </div>

  <div id="entries"></div>

  <script>
    const entries = ${jsonForScript(entries)};
    const workspacePath = ${jsonForScript(workspaceFolder?.uri.fsPath ?? null)};
    const isChinese = ${isChinese ? 'true' : 'false'};
    const vscodeApi = acquireVsCodeApi();

    function escapeHtml(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/\`/g, '&#96;')
        .replace(/\\u0024\\u007b/g, '&#36;{');
    }

    function normalizeList(value) {
      if (Array.isArray(value)) {
        return value.map(item => String(item ?? '')).filter(Boolean);
      }
      if (value === undefined || value === null || value === '') {
        return [];
      }
      return [String(value)];
    }

    function getExtraFields(entry) {
      return entry && typeof entry.extra_fields === 'object' && entry.extra_fields ? entry.extra_fields : {};
    }

    function getEntryYear(entry) {
      const extra = getExtraFields(entry);
      const value = entry.year ?? extra.year ?? '';
      const numeric = Number(value);
      return Number.isFinite(numeric) && value !== '' ? numeric : value;
    }

    function getEntryAuthors(entry) {
      const extra = getExtraFields(entry);
      return normalizeList(entry.authors ?? extra.authors);
    }

    function getEntryKeywords(entry) {
      const extra = getExtraFields(entry);
      return normalizeList(entry.keywords ?? extra.keywords);
    }

    function getEntryUrl(entry) {
      const extra = getExtraFields(entry);
      return entry.url || extra.url || '';
    }

    function getDoiUrl(value) {
      if (!value) {
        return '';
      }
      const doi = String(value).trim();
      if (/^https?:\\/\\//i.test(doi)) {
        return doi;
      }
      return 'https://doi.org/' + doi;
    }

    function getVisibleEntries() {
      const rows = Array.from(document.querySelectorAll('.entry'));
      return rows
        .map(row => entries.find(entry => String(entry._entry_id) === row.getAttribute('data-entry-id')))
        .filter(Boolean);
    }

    function getSelectedEntries() {
      const selected = Array.from(document.querySelectorAll('.entry-checkbox:checked'))
        .map(cb => entries.find(entry => String(entry._entry_id) === cb.getAttribute('data-entry-id')))
        .filter(Boolean);
      return selected.length > 0 ? selected : getVisibleEntries();
    }

    function updateSelectAllState() {
      const selectAll = document.getElementById('selectAll');
      const checkboxes = Array.from(document.querySelectorAll('.entry-checkbox'));
      const checked = checkboxes.filter(cb => cb.checked).length;
      selectAll.checked = checkboxes.length > 0 && checked === checkboxes.length;
      selectAll.indeterminate = checked > 0 && checked < checkboxes.length;
    }

    function applySelectAllToVisible() {
      const selectAll = document.getElementById('selectAll');
      const shouldCheck = selectAll.checked && !selectAll.indeterminate;
      document.querySelectorAll('.entry-checkbox').forEach(function(cb) {
        cb.checked = shouldCheck;
      });
      updateSelectAllState();
    }

    function updateResultLine(count) {
      const line = document.getElementById('resultLine');
      line.textContent = isChinese
        ? '当前显示 ' + count + ' / ' + entries.length + ' 篇文献'
        : 'Showing ' + count + ' of ' + entries.length + ' articles';
    }

    function renderEntries(filteredEntries) {
      const container = document.getElementById('entries');
      container.innerHTML = '';
      updateResultLine(filteredEntries.length);

      if (filteredEntries.length === 0) {
        if (entries.length === 0) {
          container.innerHTML =
            '<div class="empty-state">' +
            '<h2>' + (isChinese ? '还没有文献' : 'No papers yet') + '</h2>' +
            '<p>' + (isChinese
              ? '上传 PDF / Markdown，或粘贴 DOI、arXiv 编号添加。主题检索仍可用 Claude 技能 /agentsociety-literature-search。'
              : 'Upload a PDF / Markdown file, or paste a DOI or arXiv id. Topic search still uses the /agentsociety-literature-search skill.') +
            '</p>' +
            '<div class="empty-actions">' +
            '<button class="batch-btn primary" id="emptyUploadBtn">' + (isChinese ? '上传 PDF / MD' : 'Upload PDF / MD') + '</button>' +
            '<button class="batch-btn" id="emptyFocusDoiBtn">' + (isChinese ? '填写 DOI' : 'Focus DOI field') + '</button>' +
            '</div></div>';
          const emptyUpload = document.getElementById('emptyUploadBtn');
          const emptyFocus = document.getElementById('emptyFocusDoiBtn');
          if (emptyUpload) {
            emptyUpload.addEventListener('click', function() {
              vscodeApi.postMessage({ command: 'uploadFiles' });
            });
          }
          if (emptyFocus) {
            emptyFocus.addEventListener('click', function() {
              const input = document.getElementById('doiInput');
              if (input) { input.focus(); }
            });
          }
        } else {
          container.innerHTML = '<div class="empty-state">' + (isChinese ? '没有找到匹配的文献' : 'No matching articles found') + '</div>';
        }
        updateSelectAllState();
        return;
      }

      filteredEntries.forEach((entry, index) => {
        const div = document.createElement('div');
        div.className = 'entry';
        div.dataset.index = index;
        div.setAttribute('data-entry-id', String(entry._entry_id || index));
        div.setAttribute('data-filepath', entry.file_path || '');
        div.setAttribute('data-at-ref', entry.at_ref || '');

        const title = entry.title || (isChinese ? '未命名文献' : 'Untitled');
        const extraFields = getExtraFields(entry);
        const year = getEntryYear(entry);
        const authors = getEntryAuthors(entry);
        const abstract = entry.abstract || '';
        const keywords = getEntryKeywords(entry);
        const filePath = entry.file_path || '';
        const journal = entry.journal || '';
        const doi = entry.doi || '';
        const articleId = extraFields.article_id || '';
        const doiTarget = doi || (articleId && articleId.includes('/') ? articleId : '');
        const doiUrl = getDoiUrl(doiTarget);
        const url = getEntryUrl(entry);
        const fullText = extraFields.full_text || {};
        const fullTextPath = typeof fullText.file_path === 'string' ? fullText.file_path : '';
        const sourceUrl = typeof fullText.source_url === 'string' && fullText.source_url
          ? fullText.source_url
          : (url || doiUrl);
        const originalTarget = fullTextPath || sourceUrl;
        const fullTextEnriched = fullText.enriched === true;
        const fullTextStatus = typeof fullText.status === 'string' ? fullText.status : '';
        const fullTextLabel = fullTextStatus === 'downloaded'
          ? (isChinese ? '已下载原文 PDF' : 'Full-text PDF downloaded')
          : fullTextEnriched
            ? (isChinese ? '原文不可下载，笔记已人工补充' : 'PDF unavailable; note manually supplemented')
            : fullTextStatus === 'no_candidate'
              ? (isChinese ? '未找到开放 PDF' : 'No open PDF found')
              : fullTextStatus === 'failed'
                ? (isChinese ? '原文 PDF 下载失败' : 'Full-text PDF download failed')
                : sourceUrl
                  ? (isChinese ? '未下载原文 PDF，可查看来源链接' : 'PDF not downloaded; source link available')
                  : (isChinese ? '未记录原文链接' : 'No source link recorded');
        const fullTextReason = typeof fullText.reason === 'string' && fullText.reason ? fullText.reason : '';

        // 构建摘要显示
        let abstractHtml = '';
        if (abstract) {
          const needsTruncate = abstract.length > 300;
          abstractHtml = \`
            <div class="entry-abstract">
              <div class="abstract-preview" id="abstract-preview-\${index}">\${escapeHtml(abstract.substring(0, 300))}\${needsTruncate ? '...' : ''}</div>
              <div class="abstract-full" id="abstract-full-\${index}">\${escapeHtml(abstract)}</div>
              \${needsTruncate ? \`<span class="abstract-toggle" onclick="toggleAbstract(\${index})">\${isChinese ? '展开全文' : 'Show more'}</span>\` : ''}
            </div>
          \`;
        }

        div.innerHTML = \`
          <div class="entry-header">
            <input type="checkbox" class="entry-checkbox" data-entry-id="\${escapeHtml(String(entry._entry_id || index))}" data-filepath="\${escapeHtml(filePath)}" data-at-ref="\${escapeHtml(entry.at_ref || '')}" data-title="\${escapeHtml(title)}" style="margin-right: 10px;" />
            <div class="entry-title" data-original-target="\${escapeHtml(originalTarget)}" data-is-local-file="\${fullTextPath ? 'true' : 'false'}" onclick="handleTitleClick(this)">\${escapeHtml(title)}</div>
            \${year ? \`<span class="entry-year">\${escapeHtml(year)}</span>\` : ''}
          </div>
          \${journal ? \`<div class="entry-journal">\${escapeHtml(journal)}</div>\` : ''}
          \${authors.length > 0 ? \`<div class="entry-authors">\${escapeHtml(authors.join(', '))}</div>\` : ''}
          \${abstractHtml}
          <div class="entry-meta">
            \${keywords.slice(0, 5).map(k => \`<span class="keyword">\${escapeHtml(k)}</span>\`).join('')}
          </div>
          \${filePath ? \`<div class="file-path">📝 \${isChinese ? 'Markdown' : 'Markdown'}: \${escapeHtml(filePath)}</div>\` : ''}
          \${sourceUrl ? \`<div class="file-path">🔗 \${isChinese ? '原文链接' : 'Source'}: \${escapeHtml(sourceUrl)}</div>\` : ''}
          <div class="file-path">\${fullTextPath ? '📎' : 'ⓘ'} \${escapeHtml(fullTextLabel)}\${fullTextPath ? \`: \${escapeHtml(fullTextPath)}\` : ''}\${fullTextReason ? \` · \${escapeHtml(fullTextReason)}\` : ''}</div>
          <div class="entry-actions">
            \${originalTarget ? \`<button class="action-btn primary" data-original-target="\${escapeHtml(originalTarget)}" data-is-local-file="\${fullTextPath ? 'true' : 'false'}" onclick="handleOpenOriginal(this)">\${isChinese ? '查看原文' : 'View Original'}</button>\` : ''}
            \${!fullTextPath ? \`<button class="action-btn" data-entry-id="\${escapeHtml(String(entry._entry_id || index))}" onclick="handleDownloadEntry(this)">\${isChinese ? '获取原文' : 'Fetch PDF'}</button>\` : ''}
            \${filePath ? \`<button class="action-btn" data-original-target="\${escapeHtml(filePath)}" data-is-local-file="true" onclick="handleOpenOriginal(this)">\${isChinese ? '查看笔记' : 'View Note'}</button>\` : ''}
            \${filePath ? \`<button class="action-btn" onclick="copyAtReferenceForEntry(this)">\${isChinese ? '复制 @引用' : 'Copy @Ref'}</button>\` : ''}
            <button class="action-btn" data-entry-id="\${escapeHtml(String(entry._entry_id || index))}" onclick="handleCopyEntryBib(this)">\${isChinese ? '复制 BibTeX' : 'Copy BibTeX'}</button>
            \${sourceUrl ? \`<button class="action-btn" data-source-url="\${escapeHtml(sourceUrl)}" onclick="handleCopySourceUrl(this)">\${isChinese ? '复制链接' : 'Copy Link'}</button>\` : ''}
            <button class="action-btn danger" data-entry-id="\${escapeHtml(String(entry._entry_id || index))}" data-title="\${escapeHtml(title)}" onclick="handleDeleteEntry(this)">\${isChinese ? '删除' : 'Delete'}</button>
          </div>
        \`;

        container.appendChild(div);
      });
      applySelectAllToVisible();
    }

    function toggleAbstract(index) {
      const preview = document.getElementById('abstract-preview-' + index);
      const full = document.getElementById('abstract-full-' + index);
      const toggle = preview.parentElement.querySelector('.abstract-toggle');

      if (full.classList.contains('show')) {
        full.classList.remove('show');
        preview.classList.remove('hide');
        toggle.textContent = isChinese ? '展开全文' : 'Show more';
      } else {
        full.classList.add('show');
        preview.classList.add('hide');
        toggle.textContent = isChinese ? '收起' : 'Show less';
      }
    }

    function openUrl(url) {
      if (url) {
        vscodeApi.postMessage({
          command: 'openUrl',
          url: url
        });
      }
    }

    function openFile(filePath) {
      if (filePath && workspacePath) {
        vscodeApi.postMessage({
          command: 'openFile',
          filePath: filePath
        });
      } else if (!filePath) {
        vscodeApi.postMessage({
          command: 'copyText',
          text: '',
          emptyMessage: isChinese ? '该文献没有本地笔记路径，无法打开。' : 'This article has no local note path to open.'
        });
      }
    }

    function openOriginal(target, isLocalFile) {
      const shouldOpenLocalFile = isLocalFile === true || isLocalFile === 'true';
      if (shouldOpenLocalFile && target) {
        openFile(target);
      } else if (target) {
        openUrl(target);
      } else {
        vscodeApi.postMessage({
          command: 'copyText',
          text: '',
          emptyMessage: isChinese ? '这条文献没有可打开的原文或来源链接。' : 'This article has no original file or source link to open.'
        });
      }
    }

    function handleTitleClick(el) {
      const target = el.getAttribute('data-original-target');
      const isLocal = el.getAttribute('data-is-local-file');
      if (target) {
        openOriginal(target, isLocal);
      } else {
        const row = el.closest('.entry');
        const fp = row && row.getAttribute('data-filepath');
        openFile(fp || '');
      }
    }

    function handleOpenOriginal(btn) {
      const target = btn.getAttribute('data-original-target');
      const isLocal = btn.getAttribute('data-is-local-file');
      openOriginal(target, isLocal);
    }

    function handleCopySourceUrl(btn) {
      const url = btn.getAttribute('data-source-url');
      vscodeApi.postMessage({
        command: 'copyText',
        text: url || '',
        emptyMessage: isChinese ? '这条文献没有可复制的原文链接。' : 'This article has no source link to copy.'
      });
    }

    function handleDeleteEntry(btn) {
      const entryId = btn.getAttribute('data-entry-id') || '';
      const title = btn.getAttribute('data-title') || '';
      vscodeApi.postMessage({
        command: 'deleteEntry',
        entryId: entryId,
        title: title
      });
    }

    function handleDownloadEntry(btn) {
      const entryId = btn.getAttribute('data-entry-id') || '';
      vscodeApi.postMessage({
        command: 'downloadPdfs',
        entryIds: [entryId]
      });
    }

    function handleCopyEntryBib(btn) {
      const entryId = btn.getAttribute('data-entry-id') || '';
      vscodeApi.postMessage({
        command: 'exportBib',
        entryIds: [entryId],
        mode: 'copy'
      });
    }

    function getCheckedEntryIds() {
      return Array.from(document.querySelectorAll('.entry-checkbox:checked'))
        .map(function(cb) { return cb.getAttribute('data-entry-id'); })
        .filter(Boolean);
    }

    function copyAtReferenceForEntry(btn) {
      const row = btn.closest('.entry');
      const atRef = row && row.getAttribute('data-at-ref');
      if (!atRef) {
        vscodeApi.postMessage({
          command: 'copyText',
          text: '',
          emptyMessage: isChinese ? '这条文献记录没有对应的本地文件，暂时无法复制 @引用。' : 'This article record has no matching local file, so no @ reference can be copied yet.'
        });
        return;
      }
      vscodeApi.postMessage({
        command: 'copyAtReference',
        atReference: atRef
      });
    }

    // 搜索功能
    document.getElementById('searchInput').addEventListener('input', (e) => {
      const query = e.target.value.toLowerCase();
      const filtered = entries.filter(entry => {
        const title = (entry.title || '').toLowerCase();
        const authors = getEntryAuthors(entry).join(' ').toLowerCase();
        const keywords = getEntryKeywords(entry).join(' ').toLowerCase();
        const abstract = (entry.abstract || '').toLowerCase();
        const journal = (entry.journal || '').toLowerCase();
        const doi = (entry.doi || '').toLowerCase();
        return title.includes(query) || authors.includes(query) || keywords.includes(query) || abstract.includes(query) || journal.includes(query) || doi.includes(query);
      });
      applySort(filtered);
    });

    // 排序功能
    function applySort(entriesToSort) {
      const sortValue = document.getElementById('sortSelect').value;
      let sorted = [...entriesToSort];

      if (sortValue === 'year-desc') {
        sorted.sort((a, b) => (Number(getEntryYear(b)) || 0) - (Number(getEntryYear(a)) || 0));
      } else if (sortValue === 'year-asc') {
        sorted.sort((a, b) => (Number(getEntryYear(a)) || 0) - (Number(getEntryYear(b)) || 0));
      } else if (sortValue === 'title') {
        sorted.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
      }

      renderEntries(sorted);
    }

    document.getElementById('sortSelect').addEventListener('change', () => {
      const query = document.getElementById('searchInput').value.toLowerCase();
      const filtered = entries.filter(entry => {
        const title = (entry.title || '').toLowerCase();
        const authors = getEntryAuthors(entry).join(' ').toLowerCase();
        const keywords = getEntryKeywords(entry).join(' ').toLowerCase();
        const abstract = (entry.abstract || '').toLowerCase();
        const journal = (entry.journal || '').toLowerCase();
        const doi = (entry.doi || '').toLowerCase();
        return title.includes(query) || authors.includes(query) || keywords.includes(query) || abstract.includes(query) || journal.includes(query) || doi.includes(query);
      });
      applySort(filtered);
    });

    function submitDoi() {
      var input = document.getElementById('doiInput');
      var identifier = input ? String(input.value || '').trim() : '';
      if (!identifier) {
        vscodeApi.postMessage({
          command: 'copyText',
          text: '',
          emptyMessage: isChinese ? '请输入 DOI 或 arXiv 编号。' : 'Enter a DOI or arXiv id.'
        });
        return;
      }
      vscodeApi.postMessage({ command: 'addByIdentifier', identifier: identifier });
    }

    document.getElementById('addDoiBtn').addEventListener('click', submitDoi);
    document.getElementById('doiInput').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitDoi();
      }
    });
    document.getElementById('uploadBtn').addEventListener('click', function() {
      vscodeApi.postMessage({ command: 'uploadFiles' });
    });
    document.getElementById('importBibBtn').addEventListener('click', function() {
      vscodeApi.postMessage({ command: 'importBib' });
    });
    document.getElementById('syncBtn').addEventListener('click', function() {
      var ids = getCheckedEntryIds();
      vscodeApi.postMessage({
        command: 'syncLibrary',
        entryIds: ids.length > 0 ? ids : undefined
      });
    });
    document.getElementById('refreshBtn').addEventListener('click', function() {
      vscodeApi.postMessage({ command: 'refresh' });
    });
    document.getElementById('downloadSelectedBtn').addEventListener('click', function() {
      var ids = getCheckedEntryIds();
      if (ids.length === 0) {
        vscodeApi.postMessage({
          command: 'copyText',
          text: '',
          emptyMessage: isChinese ? '请先勾选要下载原文的文献。' : 'Select articles before downloading PDFs.'
        });
        return;
      }
      vscodeApi.postMessage({ command: 'downloadPdfs', entryIds: ids });
    });
    document.getElementById('copyBibBtn').addEventListener('click', function() {
      var ids = getCheckedEntryIds();
      vscodeApi.postMessage({
        command: 'exportBib',
        entryIds: ids.length > 0 ? ids : undefined,
        mode: 'copy'
      });
    });
    document.getElementById('writeBibBtn').addEventListener('click', function() {
      var ids = getCheckedEntryIds();
      vscodeApi.postMessage({
        command: 'exportBib',
        entryIds: ids.length > 0 ? ids : undefined,
        mode: 'file'
      });
    });

    // 初始渲染（应用当前排序设置）
    applySort(entries);

    // 全选功能
    document.getElementById('selectAll').addEventListener('change', function() {
      this.indeterminate = false;
      applySelectAllToVisible();
    });

    document.getElementById('entries').addEventListener('change', function(e) {
      if (e.target && e.target.classList && e.target.classList.contains('entry-checkbox')) {
        updateSelectAllState();
      }
    });

    // 复制选中引用
    document.getElementById('copySelectedBtn').addEventListener('click', function() {
      var checkboxes = document.querySelectorAll('.entry-checkbox:checked');
      if (checkboxes.length === 0) {
        vscodeApi.postMessage({
          command: 'copyText',
          text: '',
          emptyMessage: isChinese ? '请先勾选要复制的文献。' : 'Select articles before copying @references.'
        });
        return;
      }
      var references = [];
      checkboxes.forEach(function(cb) {
        var ar = cb.getAttribute('data-at-ref');
        if (ar) {
          references.push(ar);
        }
      });
      if (references.length === 0) {
        vscodeApi.postMessage({
          command: 'copyText',
          text: '',
          emptyMessage: isChinese ? '选中的文献记录没有对应的本地文件，暂时无法复制 @引用。' : 'The selected article records have no matching local files, so no @ references can be copied yet.'
        });
        return;
      }
      vscodeApi.postMessage({
        command: 'copyText',
        text: references.join('\\n'),
        count: references.length
      });
    });

    // 复制 CSV 列表
    document.getElementById('exportBtn').addEventListener('click', function() {
      var selectedEntries = getSelectedEntries();
      if (selectedEntries.length === 0) {
        vscodeApi.postMessage({
          command: 'copyText',
          text: '',
          emptyMessage: isChinese ? '当前没有可复制的文献条目。' : 'There are no article entries to copy.'
        });
        return;
      }
      
      var csvContent = 'Title,Authors,Year,Journal,DOI,File Path\\n';
      selectedEntries.forEach(function(e) {
        var title = (e.title || '').replace(/"/g, '""');
        var authors = getEntryAuthors(e).join('; ').replace(/"/g, '""');
        var year = getEntryYear(e) || '';
        var journal = (e.journal || '').replace(/"/g, '""');
        var doi = e.doi || '';
        var fp = e.file_path || '';
        csvContent += '"' + title + '","' + authors + '","' + year + '","' + journal + '","' + doi + '","' + fp + '"\\n';
      });
      
      vscodeApi.postMessage({
        command: 'copyText',
        text: csvContent,
        count: selectedEntries.length
      });
    });

    // 键盘快捷键支持
    document.addEventListener('keydown', function(e) {
      // Ctrl/Cmd + F: 聚焦搜索框
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        document.getElementById('searchInput').focus();
      }
      // Ctrl/Cmd + A: 全选
      if ((e.ctrlKey || e.metaKey) && e.key === 'a' && document.activeElement.tagName !== 'INPUT') {
        e.preventDefault();
        document.getElementById('selectAll').checked = true;
        document.getElementById('selectAll').indeterminate = false;
        applySelectAllToVisible();
      }
      // Escape: 清除搜索
      if (e.key === 'Escape') {
        document.getElementById('searchInput').value = '';
        applySort(entries);
      }
    });

  </script>
</body>
</html>`;
  }
}
