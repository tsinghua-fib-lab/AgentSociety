import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { localize } from '../i18n';
import { getMainOutputChannel } from '../shared/outputChannels';
import { resolveAgentsocietyPython } from './agentsocietyPythonResolver';
import { collectContentDigests, runPythonArchiveCommand } from './workspaceArchiveIo';
import {
  WORKSPACE_EXPORT_MANIFEST_RELATIVE_PATH,
  canonicalizeContentHash,
  formatExportRootSummary,
  parseExportManifest,
  planImportTarget,
  shouldSkipImportPath,
  verifyZipMagic,
} from './workspaceExportManifest';

export class WorkspaceImportManager implements vscode.Disposable {
  private readonly outputChannel: vscode.OutputChannel;

  constructor() {
    this.outputChannel = getMainOutputChannel();
  }

  async importWorkspaceZip(): Promise<void> {
    const zipUri = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: { 'ZIP Archive': ['zip'] },
      openLabel: localize('workspaceImport.openLabel'),
      title: localize('workspaceImport.title'),
    });
    if (!zipUri || zipUri.length === 0) {
      return;
    }
    const zipPath = zipUri[0].fsPath;
    if (!verifyZipMagic(zipPath)) {
      vscode.window.showErrorMessage(localize('workspaceImport.invalidZip'));
      return;
    }

    let stagingRoot: string | null = null;
    try {
      const pythonCommand = this.resolvePython();
      const manifest = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('workspaceImport.progress'),
          cancellable: false,
        },
        async () => {
          const inspected = await runPythonArchiveCommand(
            pythonCommand,
            'inspect',
            zipPath,
            '',
          );
          const result = parseExportManifest(inspected.manifest);
          if (!result.ok) {
            throw new Error(localize(
              result.error === 'unsupported_version'
                ? 'workspaceImport.unsupportedVersion'
                : 'workspaceImport.invalidManifest',
            ));
          }
          return result.manifest;
        },
      );

      const parent = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
        openLabel: localize('workspaceImport.pickParentLabel'),
        title: localize('workspaceImport.pickParentTitle'),
      });
      if (!parent || parent.length === 0) {
        return;
      }

      const parentPath = parent[0].fsPath;
      const projectName = await vscode.window.showInputBox({
        title: localize('workspaceImport.projectNameTitle'),
        prompt: localize('workspaceImport.projectNamePrompt', parentPath),
        value: manifest.workspaceName,
        valueSelection: [0, manifest.workspaceName.length],
        ignoreFocusOut: true,
        validateInput: (value) => {
          const plan = planImportTarget(parentPath, value);
          if (plan.ok) {
            return undefined;
          }
          return localize(`workspaceImport.target.${plan.error}`);
        },
      });
      if (projectName === undefined) {
        return;
      }
      const targetPlan = planImportTarget(parentPath, projectName);
      if (!targetPlan.ok) {
        throw new Error(localize(`workspaceImport.target.${targetPlan.error}`));
      }
      const targetRoot = targetPlan.targetPath;
      const rootSummary = formatExportRootSummary(manifest.roots)
        || localize('workspaceImport.successRootsFallback');

      const confirm = localize('workspaceImport.noticeConfirm');
      const choice = await vscode.window.showWarningMessage(
        [
          localize('workspaceImport.confirmSummary', projectName, targetRoot, rootSummary),
          '',
          localize('workspaceExport.share.copyright'),
          '',
          localize('workspaceExport.share.redistribution'),
          '',
          `• ${localize('workspaceImport.securitySecrets')}`,
          `• ${localize('workspaceImport.securitySkills')}`,
          `• ${localize('workspaceImport.securityIntegrity')}`,
          `• ${localize('workspaceImport.securityImporter')}`,
        ].join('\n'),
        { modal: true },
        confirm,
      );
      if (choice !== confirm) {
        return;
      }

      // Extract beside the final target so a verified install is a single rename
      // on the same filesystem; no second full copy and no partial target tree.
      stagingRoot = path.join(
        parentPath,
        `.${path.basename(targetRoot)}.import-${process.pid}-${Date.now()}`,
      );
      if (fs.existsSync(stagingRoot)) {
        throw new Error(localize('workspaceImport.target.target_exists'));
      }
      fs.mkdirSync(stagingRoot, { recursive: true });

      let skipped: string[] = [];
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('workspaceImport.progress'),
          cancellable: false,
        },
        async () => {
          await runPythonArchiveCommand(pythonCommand, 'extract', zipPath, stagingRoot!);
          const manifestPath = path.join(
            stagingRoot!,
            WORKSPACE_EXPORT_MANIFEST_RELATIVE_PATH,
          );
          if (!fs.existsSync(manifestPath)) {
            throw new Error(localize('workspaceImport.invalidManifest'));
          }
          const extracted = parseExportManifest(
            JSON.parse(fs.readFileSync(manifestPath, 'utf-8')),
          );
          if (!extracted.ok) {
            throw new Error(localize('workspaceImport.invalidManifest'));
          }
          if (
            extracted.manifest.contentHash !== manifest.contentHash ||
            extracted.manifest.workspaceName !== manifest.workspaceName
          ) {
            throw new Error(localize('workspaceImport.hashMismatch'));
          }
          const actualHash = canonicalizeContentHash(
            collectContentDigests(stagingRoot!),
          );
          if (actualHash !== extracted.manifest.contentHash) {
            throw new Error(localize('workspaceImport.hashMismatch'));
          }
          skipped = this.removeSkippedPaths(stagingRoot!);
        },
      );

      fs.renameSync(stagingRoot, targetRoot);
      stagingRoot = null;
      this.log(`Imported workspace into ${targetRoot}`);
      if (skipped.length > 0) {
        this.log(`Skipped sensitive or non-portable paths: ${skipped.join(', ')}`);
      }

      const openLabel = localize('workspaceImport.openFolder');
      const copyPathLabel = localize('workspaceImport.copyPath');
      const action = await vscode.window.showInformationMessage(
        localize(
          'workspaceImport.success',
          targetRoot,
          rootSummary,
        ),
        openLabel,
        copyPathLabel,
      );
      if (action === openLabel) {
        await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(targetRoot), true);
      } else if (action === copyPathLabel) {
        await vscode.env.clipboard.writeText(targetRoot);
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      this.log(`Import failed: ${message}`);
      const action = await vscode.window.showErrorMessage(
        localize('workspaceImport.failed', message),
        localize('workspaceExport.viewOutput'),
      );
      if (action === localize('workspaceExport.viewOutput')) {
        this.outputChannel.show(true);
      }
    } finally {
      if (stagingRoot) {
        fs.rmSync(stagingRoot, { recursive: true, force: true });
      }
    }
  }

  dispose(): void {
    return;
  }

  private removeSkippedPaths(root: string): string[] {
    const skipped: string[] = [];
    const walk = (dir: string, relativeDir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const relativePath = relativeDir ? `${relativeDir}/${entry.name}` : entry.name;
        const absolutePath = path.join(dir, entry.name);
        if (shouldSkipImportPath(relativePath)) {
          skipped.push(relativePath);
          fs.rmSync(absolutePath, { recursive: true, force: true });
          continue;
        }
        if (entry.isDirectory()) {
          walk(absolutePath, relativePath);
        } else if (!entry.isFile()) {
          skipped.push(relativePath);
          fs.rmSync(absolutePath, { recursive: true, force: true });
        }
      }
    };
    walk(root, '');
    return skipped;
  }

  private resolvePython(): string {
    const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const resolved = resolveAgentsocietyPython({
      workspacePath,
      extensionPath: vscode.extensions.getExtension('tsinghua-fib-lab.ai-social-scientist')?.extensionPath,
    });
    if (resolved) {
      return resolved;
    }
    return process.platform === 'win32' ? 'python' : 'python3';
  }

  private log(message: string): void {
    this.outputChannel.appendLine(`[${new Date().toISOString()}] [Import] ${message}`);
  }
}
