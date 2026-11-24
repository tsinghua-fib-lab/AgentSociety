/**
 * Open workspace files with their preview editors.
 */

import * as path from 'path';
import * as vscode from 'vscode';

/** Use the PDF editor shipped with the workspace image, or the user's file association. */
export async function openPdfPreview(filePath: string): Promise<void> {
  const uri = vscode.Uri.file(filePath);
  if (vscode.extensions.getExtension('mathematic.vscode-pdf')) {
    await vscode.commands.executeCommand('vscode.openWith', uri, 'pdf.view');
    return;
  }
  await vscode.commands.executeCommand('vscode.open', uri);
}

/** Open a workspace file with an appropriate viewer. */
export async function openWorkspaceFile(filePath: string): Promise<void> {
  const uri = vscode.Uri.file(filePath);
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.md' || ext === '.markdown') {
    await vscode.commands.executeCommand('markdown.showPreview', uri);
    return;
  }
  if (ext === '.pdf') {
    await openPdfPreview(filePath);
    return;
  }
  await vscode.commands.executeCommand('vscode.open', uri);
}
