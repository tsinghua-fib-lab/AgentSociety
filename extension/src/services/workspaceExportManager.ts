/**
 * Export selected workspace content into a ZIP archive.
 *
 * Default picks follow the research workspace layout (TOPIC, papers,
 * hypothesis_*, custom, .claude, …). Secrets and non-portable paths are
 * always filtered by {@link shouldExcludeWorkspacePath}.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { localize } from '../i18n';
import { getMainOutputChannel } from '../shared/outputChannels';
import { resolveAgentsocietyPython } from './agentsocietyPythonResolver';
import {
  buildExportManifest,
  canonicalizeContentHash,
  isDefaultExportTier,
  isNonResearchOptionalRoot,
  isSafeWorkspaceName,
  RECOMMENDED_EXPORT_ROOTS,
  resolveExportTier,
  resolveSafeExportSymlink,
  shouldExcludeWorkspacePath,
  validateExportSelection,
  verifyZipMagic,
  writeExportSidecars,
  buildShareMarkdown,
  type WorkspaceExportRootRecord,
  type WorkspaceExportTier,
} from './workspaceExportManifest';
import { collectContentDigests, runPythonArchiveCommand } from './workspaceArchiveIo';

interface ExportSummary {
  exportedRoots: string[];
  copiedFiles: number;
}

interface ExportCandidate {
  label: string;
  archivePath: string;
  sourcePath: string;
  allowedRoot: string;
  tier: WorkspaceExportTier;
  source: 'workspace' | 'external';
  kind: 'file' | 'directory';
  detail?: string;
  size?: number;
  available: boolean;
}

interface ExportPickItem extends vscode.QuickPickItem {
  candidate: ExportCandidate;
}

export class WorkspaceExportManager implements vscode.Disposable {
  private readonly outputChannel: vscode.OutputChannel;
  private readonly extensionVersion: string;

  constructor() {
    this.outputChannel = getMainOutputChannel();
    this.extensionVersion =
      vscode.extensions.getExtension('tsinghua-fib-lab.ai-social-scientist')?.packageJSON
        ?.version ?? 'unknown';
  }

  async exportWorkspaceZip(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('workspaceExport.noWorkspace'));
      return;
    }

    const workspacePath = workspaceFolder.uri.fsPath;
    let previousSelection: string[] | undefined;

    while (true) {
      const selectedRoots = await this.promptForExportSelection(workspacePath, previousSelection);
      if (selectedRoots === undefined) {
        return;
      }

      if (selectedRoots.length === 0) {
        vscode.window.showWarningMessage(localize('workspaceExport.noSelection'));
        previousSelection = [];
        continue;
      }

      const selectionRecords: WorkspaceExportRootRecord[] = selectedRoots.map((candidate) => ({
        archivePath: candidate.archivePath,
        kind: candidate.kind,
        tier: candidate.tier,
        bytes: candidate.size ?? 0,
        fileCount: this.estimateExportableFileCount(candidate),
      }));
      const validation = validateExportSelection({
        selectedRoots: selectionRecords,
      });
      const errors = validation.issues.filter((issue) => issue.level === 'error');
      const warnings = validation.issues.filter((issue) => issue.level === 'warning');
      if (errors.length > 0) {
        vscode.window.showErrorMessage(
          errors.map((issue) => localize(`workspaceExport.validation.${issue.code}`)).join('\n')
        );
        return;
      }
      if (warnings.length > 0) {
        const warningText = warnings
          .map((issue) => localize(`workspaceExport.validation.${issue.code}`))
          .join('\n');
        const continueLabel = localize('workspaceExport.validation.continue');
        const choice = await vscode.window.showWarningMessage(
          `${warningText}\n\n${localize('workspaceExport.validation.summary', validation.totalFiles, this.formatSize(validation.totalBytes))}`,
          { modal: true },
          continueLabel,
          localize('workspaceExport.validation.back')
        );
        if (choice === localize('workspaceExport.validation.back')) {
          previousSelection = selectedRoots.map((item) => item.archivePath);
          continue;
        }
        if (choice !== continueLabel) {
          return;
        }
      }

      const defaultSaveUri = this.getDefaultSaveUri(workspaceFolder);
      const saveUri = await vscode.window.showSaveDialog({
        ...(defaultSaveUri ? { defaultUri: defaultSaveUri } : {}),
        filters: {
          'ZIP Archive': ['zip'],
        },
        saveLabel: localize('workspaceExport.saveLabel'),
      });

      if (!saveUri) {
        return;
      }

      try {
        const summary = await vscode.window.withProgress<ExportSummary>(
          {
            location: vscode.ProgressLocation.Notification,
            title: localize('workspaceExport.progress.title'),
            cancellable: false,
          },
          async (progress) => this.performExport(workspacePath, saveUri, selectedRoots, progress),
        );

        const message = localize(
          'workspaceExport.success',
          this.getUriDisplayName(saveUri),
          summary.copiedFiles,
          summary.exportedRoots.slice(0, 4).join(', ') + (summary.exportedRoots.length > 4 ? '…' : ''),
        );

        const isRemote = vscode.env.remoteName !== undefined;
        const actions = isRemote
          ? [localize('workspaceExport.openInEditor'), localize('workspaceExport.copyPath')]
          : [localize('workspaceExport.reveal'), localize('workspaceExport.openInEditor'), localize('workspaceExport.copyPath')];

        const action = await vscode.window.showInformationMessage(message, ...actions);

        try {
          if (action === localize('workspaceExport.reveal')) {
            await vscode.commands.executeCommand('revealFileInOS', saveUri);
          } else if (action === localize('workspaceExport.openInEditor')) {
            await vscode.commands.executeCommand('vscode.open', saveUri);
          } else if (action === localize('workspaceExport.copyPath')) {
            await vscode.env.clipboard.writeText(this.getUriClipboardText(saveUri));
          }
        } catch (error: unknown) {
          const postActionError = error instanceof Error ? error.message : String(error);
          this.log(`Post-export action failed: ${postActionError}`);
          vscode.window.showWarningMessage(localize('workspaceExport.postActionFailed', postActionError));
        }
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        this.log(`Export failed: ${message}`);
        const action = await vscode.window.showErrorMessage(
          localize('workspaceExport.failed', message),
          localize('workspaceExport.viewOutput'),
        );
        if (action === localize('workspaceExport.viewOutput')) {
          this.outputChannel.show(true);
        }
      }
      return;
    }
  }

  dispose(): void {
    return;
  }

  private async promptForExportSelection(
    workspacePath: string,
    previousSelection?: string[],
  ): Promise<ExportCandidate[] | undefined> {
    const candidates = this.collectExportCandidates(workspacePath);
    if (candidates.length === 0) {
      throw new Error(localize('workspaceExport.empty'));
    }

    const selectedSet = previousSelection ? new Set(previousSelection) : undefined;
    const items: ExportPickItem[] = candidates.map((candidate) => {
      if (!candidate.available) {
        return {
          label: `${localize('workspaceExport.pick.missing')}: ${this.formatCandidateLabel(candidate)}`,
          detail: this.buildExportPickDetail(candidate),
          kind: vscode.QuickPickItemKind.Separator,
          candidate,
        };
      }
      return {
        label: `${this.formatTierPrefix(candidate.tier)}${this.formatCandidateLabel(candidate)}`,
        description: localize(`workspaceExport.pick.tier.${candidate.tier}`),
        detail: this.buildExportPickDetail(candidate),
        picked: selectedSet
          ? selectedSet.has(candidate.archivePath)
          : isDefaultExportTier(candidate.tier),
        candidate,
      };
    });
    const tierRank: Record<WorkspaceExportTier, number> = {
      core: 0,
      agent: 1,
      optional: 2,
      external: 3,
    };
    items.sort((a, b) => {
      const availability = Number(b.candidate.available) - Number(a.candidate.available);
      if (availability !== 0) {
        return availability;
      }
      return tierRank[a.candidate.tier] - tierRank[b.candidate.tier];
    });

    const selectedItems = await vscode.window.showQuickPick<ExportPickItem>(items, {
      canPickMany: true,
      title: localize('workspaceExport.pick.title'),
      placeHolder: localize('workspaceExport.pick.placeholder'),
      ignoreFocusOut: true,
    });

    if (!selectedItems) {
      return undefined;
    }
    return selectedItems
      .map((item) => item.candidate)
      .filter((candidate) => candidate.available);
  }

  private async performExport(
    workspacePath: string,
    destinationZipUri: vscode.Uri,
    selectedRoots: ExportCandidate[],
    progress: vscode.Progress<{ message?: string; increment?: number }>,
  ): Promise<ExportSummary> {
    const exportRoots = selectedRoots;
    if (exportRoots.length === 0) {
      throw new Error(localize('workspaceExport.empty'));
    }

    const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-social-scientist-export-'));
    const stagingPath = path.join(tempRoot, 'workspace');
    fs.mkdirSync(stagingPath, { recursive: true });

    const summary: ExportSummary = {
      exportedRoots: exportRoots.map((candidate) => candidate.archivePath),
      copiedFiles: 0,
    };
    const rootRecords: WorkspaceExportRootRecord[] = [];

    try {
      progress.report({ message: localize('workspaceExport.progress.collecting'), increment: 10 });
      this.log(`Export roots: ${summary.exportedRoots.join(', ')}`);

      const perRootIncrement = exportRoots.length > 0 ? 50 / exportRoots.length : 50;
      for (const candidate of exportRoots) {
        progress.report({
          message: localize('workspaceExport.progress.copying', candidate.archivePath),
          increment: perRootIncrement,
        });
        const targetPath = path.join(stagingPath, candidate.archivePath);
        const beforeCount = summary.copiedFiles;
        this.copyEntry(
          candidate.sourcePath,
          targetPath,
          candidate.archivePath,
          candidate.allowedRoot,
          summary,
        );
        rootRecords.push({
          archivePath: candidate.archivePath,
          kind: candidate.kind,
          tier: candidate.tier,
          bytes: fs.existsSync(targetPath)
            ? (candidate.kind === 'directory'
              ? this.getDirectorySize(targetPath)
              : this.getFileSize(targetPath))
            : 0,
          fileCount: summary.copiedFiles - beforeCount,
        });
      }

      if (summary.copiedFiles === 0) {
        throw new Error(localize('workspaceExport.empty'));
      }
      const contentHash = canonicalizeContentHash(collectContentDigests(stagingPath));
      const workspaceName = path.basename(workspacePath);
      if (!isSafeWorkspaceName(workspaceName)) {
        throw new Error(localize('workspaceExport.invalidWorkspaceName'));
      }
      const manifest = buildExportManifest({
        workspaceName,
        extensionVersion: this.extensionVersion,
        roots: rootRecords,
        contentHash,
        notice: {
          title: localize('workspaceExport.share.title'),
          copyright: localize('workspaceExport.share.copyright'),
          redistribution: localize('workspaceExport.share.redistribution'),
          secrets: localize('workspaceExport.share.secrets'),
          importer: localize('workspaceExport.share.importer'),
        },
      });
      writeExportSidecars(
        stagingPath,
        manifest,
        buildShareMarkdown(manifest, {
          includedTitle: localize('workspaceExport.share.included'),
          excludedTitle: localize('workspaceExport.share.excluded'),
        }),
      );
      this.log(`Wrote export manifest with ${rootRecords.length} root(s), hash ${contentHash}`);

      progress.report({ message: localize('workspaceExport.progress.archiving'), increment: 20 });
      const temporaryZipPath = path.join(tempRoot, 'workspace-export.zip');
      await this.createZipArchive(stagingPath, temporaryZipPath, workspacePath);

      progress.report({ message: localize('workspaceExport.progress.saving'), increment: 10 });
      await this.writeArchiveToDestination(temporaryZipPath, destinationZipUri);

      const zipToVerify = destinationZipUri.scheme === 'file' ? destinationZipUri.fsPath : temporaryZipPath;
      if (!verifyZipMagic(zipToVerify)) {
        throw new Error(localize('workspaceExport.validation.archiveInvalid'));
      }

      progress.report({ message: localize('workspaceExport.progress.done'), increment: 10 });
      this.log(`Export completed: ${destinationZipUri.toString(true)} (${summary.copiedFiles} files)`);
      return summary;
    } finally {
      fs.rmSync(tempRoot, { recursive: true, force: true });
    }
  }

  private makeWorkspaceCandidate(
    workspacePath: string,
    archivePath: string,
    kind: 'file' | 'directory',
    sourcePath: string,
    available = true,
  ): ExportCandidate {
    return {
      label: archivePath,
      archivePath,
      sourcePath,
      allowedRoot: workspacePath,
      tier: resolveExportTier(archivePath, 'workspace'),
      source: 'workspace',
      kind,
      size: available
        ? (kind === 'directory'
          ? this.getDirectorySize(sourcePath, '', workspacePath)
          : this.getFileSize(sourcePath))
        : 0,
      available,
    };
  }

  private collectExportCandidates(workspacePath: string): ExportCandidate[] {
    const candidates: ExportCandidate[] = [];
    const knownRoots = new Set<string>();

    const addCandidate = (candidate: ExportCandidate) => {
      if (knownRoots.has(candidate.archivePath)) {
        return;
      }
      knownRoots.add(candidate.archivePath);
      candidates.push(candidate);
    };

    // Recommended research roots always appear so users can see/select them.
    for (const recommended of RECOMMENDED_EXPORT_ROOTS) {
      const sourcePath = path.join(workspacePath, recommended.archivePath);
      const available = this.shouldOfferTopLevelEntry(workspacePath, recommended.archivePath);
      addCandidate(
        this.makeWorkspaceCandidate(
          workspacePath,
          recommended.archivePath,
          recommended.kind,
          sourcePath,
          available,
        ),
      );
    }

    let dynamicRoots: fs.Dirent[] = [];
    try {
      dynamicRoots = fs.readdirSync(workspacePath, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && /^hypothesis_[^/\\]+$/.test(entry.name))
        .sort((a, b) => a.name.localeCompare(b.name));
    } catch {
      this.log(`Failed to scan hypothesis directories in ${workspacePath}`);
    }

    for (const entry of dynamicRoots) {
      addCandidate(
        this.makeWorkspaceCandidate(
          workspacePath,
          entry.name,
          'directory',
          path.join(workspacePath, entry.name),
        ),
      );
    }

    if (dynamicRoots.length === 0) {
      addCandidate({
        label: 'hypothesis_*',
        archivePath: 'hypothesis_*',
        sourcePath: workspacePath,
        allowedRoot: workspacePath,
        tier: 'core',
        source: 'workspace',
        kind: 'directory',
        size: 0,
        available: false,
        detail: localize('workspaceExport.pick.hint.hypothesisMissing'),
      });
    }

    const claudeConversationCandidate = this.getClaudeConversationCandidate(workspacePath);
    if (claudeConversationCandidate) {
      addCandidate(claudeConversationCandidate);
    }

    const claudeHistoryCandidate = this.getClaudeHistoryCandidate();
    if (claudeHistoryCandidate) {
      addCandidate(claudeHistoryCandidate);
    }

    const codexCandidate = this.getCodexCandidate(workspacePath);
    if (codexCandidate) {
      addCandidate(codexCandidate);
    }

    let optionalRoots: fs.Dirent[] = [];
    try {
      optionalRoots = fs.readdirSync(workspacePath, { withFileTypes: true })
        .filter((entry) => !knownRoots.has(entry.name))
        .filter((entry) => !isNonResearchOptionalRoot(entry.name))
        .filter((entry) => !this.shouldExclude(this.normalizeRelativePath(entry.name)))
        .sort((a, b) => a.name.localeCompare(b.name));
    } catch {
      this.log(`Failed to scan optional entries in ${workspacePath}`);
    }

    for (const entry of optionalRoots) {
      const archivePath = entry.name;
      addCandidate(
        this.makeWorkspaceCandidate(
          workspacePath,
          archivePath,
          entry.isDirectory() ? 'directory' : 'file',
          path.join(workspacePath, archivePath),
        ),
      );
    }

    return candidates;
  }

  private getFileSize(filePath: string): number {
    try {
      const stats = fs.statSync(filePath);
      return stats.size;
    } catch {
      return 0;
    }
  }

  private getDirectorySize(
    dirPath: string,
    relativePath = '',
    allowedRoot = dirPath,
  ): number {
    try {
      let totalSize = 0;
      const entries = fs.readdirSync(dirPath, { withFileTypes: true });
      for (const entry of entries) {
        const childRelative = this.normalizeRelativePath(relativePath ? `${relativePath}/${entry.name}` : entry.name);
        const fullPath = path.join(dirPath, entry.name);
        if (this.shouldExclude(childRelative)) {
          continue;
        }
        if (entry.isDirectory()) {
          totalSize += this.getDirectorySize(fullPath, childRelative, allowedRoot);
        } else if (entry.isFile()) {
          totalSize += this.getFileSize(fullPath);
        } else if (entry.isSymbolicLink()) {
          const resolved = resolveSafeExportSymlink(fullPath, allowedRoot);
          if (resolved && fs.statSync(resolved).isFile()) {
            totalSize += this.getFileSize(resolved);
          }
        }
      }
      return totalSize;
    } catch {
      return 0;
    }
  }

  private buildExportPickDetail(candidate: ExportCandidate): string {
    if (!candidate.available) {
      return candidate.detail
        ?? localize('workspaceExport.pick.missingDetail');
    }
    const hint = this.rootHint(candidate);
    if (candidate.detail) {
      return hint ? `${candidate.detail} · ${hint}` : candidate.detail;
    }
    const kindLabel =
      candidate.kind === 'directory'
        ? localize('workspaceExport.pick.directoryDetail')
        : localize('workspaceExport.pick.fileDetail');
    const sizeLabel = candidate.size === undefined
      ? kindLabel
      : candidate.kind === 'directory' && candidate.size === 0
        ? `${kindLabel} · ${localize('workspaceExport.pick.emptyDirectoryHint')}`
        : `${kindLabel} · ${this.formatSize(candidate.size)}`;
    return hint ? `${sizeLabel} · ${hint}` : sizeLabel;
  }

  private formatCandidateLabel(candidate: ExportCandidate): string {
    if (candidate.archivePath === 'TOPIC.md') {
      return localize('workspaceExport.pick.label.topic');
    }
    if (candidate.archivePath.startsWith('hypothesis_') || candidate.archivePath === 'hypothesis_*') {
      return localize('workspaceExport.pick.label.hypothesis', candidate.archivePath);
    }
    if (candidate.archivePath === 'papers' || candidate.archivePath === 'paper') {
      return localize('workspaceExport.pick.label.papers', candidate.archivePath);
    }
    if (candidate.archivePath === '.agentsociety') {
      return localize('workspaceExport.pick.label.agentsociety');
    }
    if (candidate.archivePath === 'custom') {
      return localize('workspaceExport.pick.label.custom');
    }
    if (candidate.archivePath === 'datasets') {
      return localize('workspaceExport.pick.label.datasets');
    }
    if (candidate.archivePath === 'user_data') {
      return localize('workspaceExport.pick.label.userData');
    }
    if (candidate.archivePath === 'presentation') {
      return localize('workspaceExport.pick.label.presentation');
    }
    if (candidate.archivePath === 'synthesis') {
      return localize('workspaceExport.pick.label.synthesis');
    }
    if (candidate.archivePath === '.claude') {
      return localize('workspaceExport.pick.label.claude');
    }
    if (candidate.archivePath === 'CLAUDE.md') {
      return localize('workspaceExport.pick.label.claudeMd');
    }
    if (candidate.archivePath === 'AGENTS.md') {
      return localize('workspaceExport.pick.label.agentsMd');
    }
    return candidate.label;
  }

  private rootHint(candidate: ExportCandidate): string | undefined {
    if (candidate.source === 'external') {
      return localize('workspaceExport.pick.hint.external');
    }
    if (candidate.archivePath === 'TOPIC.md') {
      return localize('workspaceExport.pick.hint.topic');
    }
    if (candidate.archivePath.startsWith('hypothesis_') || candidate.archivePath === 'hypothesis_*') {
      return localize('workspaceExport.pick.hint.hypothesis');
    }
    if (candidate.archivePath === 'papers' || candidate.archivePath === 'paper') {
      return localize('workspaceExport.pick.hint.papers');
    }
    if (candidate.archivePath === '.claude') {
      return localize('workspaceExport.pick.hint.claude');
    }
    if (candidate.archivePath === 'CLAUDE.md') {
      return localize('workspaceExport.pick.hint.claudeMd');
    }
    if (candidate.archivePath === 'AGENTS.md') {
      return localize('workspaceExport.pick.hint.agentsMd');
    }
    if (candidate.archivePath === '.agentsociety') {
      return localize('workspaceExport.pick.hint.agentsociety');
    }
    if (candidate.archivePath === 'custom') {
      return localize('workspaceExport.pick.hint.custom');
    }
    if (candidate.archivePath === 'datasets' || candidate.archivePath === 'user_data') {
      return localize('workspaceExport.pick.hint.datasets');
    }
    if (candidate.archivePath === 'presentation') {
      return localize('workspaceExport.pick.hint.presentation');
    }
    if (candidate.archivePath === 'synthesis') {
      return localize('workspaceExport.pick.hint.synthesis');
    }
    return undefined;
  }

  private formatSize(bytes: number): string {
    if (bytes === 0) {
      return '0 B';
    }
    const units = ['B', 'KB', 'MB', 'GB'];
    const k = 1024;
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    const size = parseFloat((bytes / Math.pow(k, i)).toFixed(1));
    return `${size} ${units[i]}`;
  }

  private copyEntry(
    sourcePath: string,
    targetPath: string,
    relativePath: string,
    workspaceRoot: string,
    summary: ExportSummary,
  ): void {
    const normalizedPath = this.normalizeRelativePath(relativePath);
    let stats: fs.Stats;
    try {
      stats = fs.lstatSync(sourcePath);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      this.log(`Skipped unreadable path: ${normalizedPath} (${message})`);
      return;
    }

    if (this.shouldExclude(normalizedPath)) {
      this.log(`Skipped excluded path: ${normalizedPath}`);
      return;
    }

    if (stats.isSymbolicLink()) {
      const resolvedPath = resolveSafeExportSymlink(sourcePath, workspaceRoot);
      if (!resolvedPath) {
        this.log(`Skipped broken or out-of-root symlink: ${normalizedPath}`);
        return;
      }

      let resolvedStats: fs.Stats;
      try {
        resolvedStats = fs.statSync(resolvedPath);
      } catch {
        this.log(`Skipped unreadable symlink target: ${normalizedPath}`);
        return;
      }
      if (resolvedStats.isDirectory()) {
        this.log(`Skipped directory symlink: ${normalizedPath}`);
      } else if (resolvedStats.isFile()) {
        this.copyFile(resolvedPath, targetPath, summary);
      } else {
        this.log(`Skipped unsupported symlink target: ${normalizedPath}`);
      }
      return;
    }

    if (stats.isDirectory()) {
      this.copyDirectory(sourcePath, targetPath, normalizedPath, workspaceRoot, summary);
      return;
    }

    if (stats.isFile()) {
      this.copyFile(sourcePath, targetPath, summary);
    } else {
      this.log(`Skipped unsupported file type: ${normalizedPath}`);
    }
  }

  private copyDirectory(
    sourceDir: string,
    targetDir: string,
    relativeDir: string,
    workspaceRoot: string,
    summary: ExportSummary,
  ): void {
    fs.mkdirSync(targetDir, { recursive: true });

    const entries = fs.readdirSync(sourceDir, { withFileTypes: true })
      .sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of entries) {
      const childRelativePath = this.normalizeRelativePath(path.posix.join(relativeDir, entry.name));
      const childSourcePath = path.join(sourceDir, entry.name);
      const childTargetPath = path.join(targetDir, entry.name);
      this.copyEntry(childSourcePath, childTargetPath, childRelativePath, workspaceRoot, summary);
    }
  }

  private copyFile(
    sourceFile: string,
    targetFile: string,
    summary: ExportSummary,
  ): void {
    fs.mkdirSync(path.dirname(targetFile), { recursive: true });
    fs.copyFileSync(sourceFile, targetFile);
    summary.copiedFiles += 1;
  }

  private shouldExclude(relativePath: string): boolean {
    return shouldExcludeWorkspacePath(relativePath);
  }

  private async createZipArchive(
    sourceDir: string,
    destinationZipPath: string,
    workspacePath: string,
  ): Promise<void> {
    fs.mkdirSync(path.dirname(destinationZipPath), { recursive: true });
    fs.rmSync(destinationZipPath, { force: true });
    const errors: string[] = [];
    for (const pythonCommand of this.getPythonCandidates(workspacePath)) {
      try {
        await runPythonArchiveCommand(pythonCommand, 'create', sourceDir, destinationZipPath);
        return;
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        errors.push(`${pythonCommand}: ${message}`);
      }
    }
    this.log(`ZIP create failed: ${errors.join('; ')}`);
    throw new Error(localize('workspaceExport.pythonUnavailable'));
  }

  private async writeArchiveToDestination(sourceZipPath: string, destinationUri: vscode.Uri): Promise<void> {
    if (destinationUri.scheme === 'file') {
      const destPath = destinationUri.fsPath;
      await fs.promises.mkdir(path.dirname(destPath), { recursive: true });
      await fs.promises.copyFile(sourceZipPath, destPath);
    } else {
      const zipContent = await fs.promises.readFile(sourceZipPath);
      await vscode.workspace.fs.writeFile(destinationUri, zipContent);
    }
  }

  private getPythonCandidates(workspacePath: string): string[] {
    const extension = vscode.extensions.getExtension('tsinghua-fib-lab.ai-social-scientist');
    const resolved = resolveAgentsocietyPython({
      configuredPath: this.readConfiguredPythonPath() ?? undefined,
      workspacePath,
      extensionPath: extension?.extensionPath,
    });
    const candidates = resolved ? [resolved] : [];
    const defaults = process.platform === 'win32'
      ? ['python', 'py']
      : ['python3', 'python'];

    for (const candidate of defaults) {
      if (!candidates.includes(candidate)) {
        candidates.push(candidate);
      }
    }

    return candidates;
  }

  private readConfiguredPythonPath(): string | null {
    const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspacePath) {
      return null;
    }

    const envPath = path.join(workspacePath, '.env');
    if (!fs.existsSync(envPath)) {
      return null;
    }

    const content = fs.readFileSync(envPath, 'utf-8');
    for (const line of content.split(/\r?\n/)) {
      const match = line.trim().match(/^PYTHON_PATH=(.*)$/);
      if (match) {
        return match[1].trim() || null;
      }
    }

    return null;
  }

  private shouldOfferTopLevelEntry(workspacePath: string, relativePath: string): boolean {
    if (this.shouldExclude(this.normalizeRelativePath(relativePath))) {
      return false;
    }

    const absolutePath = path.join(workspacePath, relativePath);
    if (!fs.existsSync(absolutePath)) {
      return false;
    }

    return !this.shouldExclude(this.normalizeRelativePath(relativePath));
  }

  private getClaudeConversationCandidate(workspacePath: string): ExportCandidate | null {
    const encodedWorkspacePath = this.encodeClaudeProjectPath(workspacePath);
    const conversationPath = path.join(os.homedir(), '.claude', 'projects', encodedWorkspacePath);
    if (!fs.existsSync(conversationPath)) {
      return null;
    }

    const stats = fs.lstatSync(conversationPath);
    if (!stats.isDirectory()) {
      return null;
    }

    return {
      label: `.claude/projects/${encodedWorkspacePath}`,
      archivePath: path.posix.join('.claude', 'projects', encodedWorkspacePath),
      sourcePath: conversationPath,
      allowedRoot: conversationPath,
      tier: 'external',
      source: 'external',
      kind: 'directory',
      detail: localize('workspaceExport.pick.claudeConversationDetail'),
      size: this.getDirectorySize(conversationPath),
      available: true,
    };
  }

  private getClaudeHistoryCandidate(): ExportCandidate | null {
    const historyPath = path.join(os.homedir(), '.claude', 'history.jsonl');
    if (!fs.existsSync(historyPath)) {
      return null;
    }

    return {
      label: '.claude/history.jsonl',
      archivePath: '.claude/history.jsonl',
      sourcePath: historyPath,
      allowedRoot: path.dirname(historyPath),
      tier: 'external',
      source: 'external',
      kind: 'file',
      detail: localize('workspaceExport.pick.claudeHistoryDetail'),
      size: this.getFileSize(historyPath),
      available: true,
    };
  }

  private getCodexCandidate(workspacePath: string): ExportCandidate | null {
    const codexRoot = path.join(os.homedir(), '.codex');
    if (!fs.existsSync(codexRoot)) {
      return null;
    }

    const stats = fs.lstatSync(codexRoot);
    if (!stats.isDirectory()) {
      return null;
    }

    const encodedWorkspacePath = this.encodeClaudeProjectPath(workspacePath);
    const workspaceScopedDir = path.join(codexRoot, 'projects', encodedWorkspacePath);
    if (!fs.existsSync(workspaceScopedDir) || !fs.lstatSync(workspaceScopedDir).isDirectory()) {
      return null;
    }

    return {
      label: `.codex/projects/${encodedWorkspacePath}`,
      archivePath: path.posix.join('.codex', 'projects', encodedWorkspacePath),
      sourcePath: workspaceScopedDir,
      allowedRoot: workspaceScopedDir,
      tier: 'external',
      source: 'external',
      kind: 'directory',
      detail: localize('workspaceExport.pick.codexDetail'),
      size: this.getDirectorySize(workspaceScopedDir),
      available: true,
    };
  }

  private encodeClaudeProjectPath(workspacePath: string): string {
    return path.resolve(workspacePath).replace(/[:\\/]+/g, '-');
  }

  private formatTierPrefix(tier: WorkspaceExportTier): string {
    if (tier === 'core' || tier === 'agent') {
      return '$(star-full) ';
    }
    if (tier === 'external') {
      return '$(warning) ';
    }
    return '$(circle-outline) ';
  }

  private estimateExportableFileCount(candidate: ExportCandidate): number {
    return this.countExportableFiles(candidate.sourcePath, candidate.archivePath, candidate.allowedRoot);
  }

  private countExportableFiles(
    sourceDir: string,
    relativeDir: string,
    workspaceRoot: string,
  ): number {
    if (!fs.existsSync(sourceDir)) {
      return 0;
    }
    let stats: fs.Stats;
    try {
      stats = fs.lstatSync(sourceDir);
    } catch {
      return 0;
    }
    if (stats.isSymbolicLink()) {
      const resolved = resolveSafeExportSymlink(sourceDir, workspaceRoot);
      if (!resolved) {
        return 0;
      }
      try {
        return fs.statSync(resolved).isFile() &&
          !this.shouldExclude(this.normalizeRelativePath(relativeDir))
          ? 1
          : 0;
      } catch {
        return 0;
      }
    }
    if (!stats.isDirectory()) {
      return stats.isFile() &&
        !this.shouldExclude(this.normalizeRelativePath(relativeDir))
        ? 1
        : 0;
    }

    let total = 0;
    const entries = fs.readdirSync(sourceDir, { withFileTypes: true });
    for (const entry of entries) {
      const childRelativePath = this.normalizeRelativePath(path.posix.join(relativeDir, entry.name));
      const childSourcePath = path.join(sourceDir, entry.name);
      if (entry.isSymbolicLink() || entry.isDirectory()) {
        total += this.countExportableFiles(childSourcePath, childRelativePath, workspaceRoot);
      } else if (entry.isFile() && !this.shouldExclude(childRelativePath)) {
        total += 1;
      }
    }
    return total;
  }

  private getDefaultSaveUri(workspaceFolder: vscode.WorkspaceFolder): vscode.Uri | undefined {
    if (workspaceFolder.uri.scheme !== 'file') {
      return undefined;
    }

    const defaultFileName = this.getDefaultZipFileName(workspaceFolder.uri.fsPath);
    const downloadsDir = path.join(os.homedir(), 'Downloads');
    const baseDir = fs.existsSync(downloadsDir) ? downloadsDir : workspaceFolder.uri.fsPath;
    return vscode.Uri.file(path.join(baseDir, defaultFileName));
  }

  private getDefaultZipFileName(workspacePath: string): string {
    const workspaceName = path.basename(workspacePath);
    const timestamp = this.getTimestamp();
    return `${workspaceName}-workspace-export-${timestamp}.zip`;
  }

  private getTimestamp(): string {
    const now = new Date();
    const pad = (value: number) => String(value).padStart(2, '0');
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  }

  private normalizeRelativePath(relativePath: string): string {
    return relativePath.replace(/\\/g, '/');
  }

  private getUriDisplayName(uri: vscode.Uri): string {
    if (uri.scheme === 'file' && uri.fsPath) {
      return path.basename(uri.fsPath);
    }

    const uriPathBaseName = path.posix.basename(uri.path);
    return uriPathBaseName || uri.toString(true);
  }

  private getUriClipboardText(uri: vscode.Uri): string {
    if (uri.scheme === 'file' && uri.fsPath) {
      return uri.fsPath;
    }

    return uri.toString(true);
  }

  private log(message: string): void {
    this.outputChannel.appendLine(`[${new Date().toISOString()}] [Export] ${message}`);
  }
}
