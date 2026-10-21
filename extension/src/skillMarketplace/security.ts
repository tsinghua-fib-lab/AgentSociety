import * as path from 'path';
import * as fs from 'fs';
import * as vscode from 'vscode';
import { getPlatformAdapter, type SkillSource } from '../platforms';
import { isPrivateOrLocalHost } from './urlSafety';

export { isAllowedSkillSourceBaseUrl } from './urlSafety';

const SAFE_SKILL_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/;

/**
 * Return true when ``branch`` is a safe git branch name.
 */
export function isValidGitBranch(branch: string): boolean {
  const validBranchPattern = /^[a-zA-Z0-9][a-zA-Z0-9._/-]*$/;
  return validBranchPattern.test(branch) &&
    !branch.includes('..') &&
    !branch.endsWith('/') &&
    !branch.endsWith('.');
}

/**
 * Return true when ``id`` is a single-segment marketplace skill directory name.
 */
export function isValidSkillId(id: string): boolean {
  return SAFE_SKILL_ID_RE.test(id) && !id.includes('..');
}

/**
 * Return true when ``relativePath`` is a safe path inside a cloned skill repo.
 */
export function isSafeSkillRelativePath(relativePath: string): boolean {
  const normalized = relativePath.replace(/\\/g, '/').replace(/^\.\//, '').replace(/\/+$/, '');
  if (!normalized || normalized === '.') {
    return true;
  }
  if (normalized.startsWith('/') || /(?:^|\/)[A-Za-z]:/.test(normalized) || normalized.includes(':')) {
    return false;
  }
  return !normalized.split('/').some((segment) => segment === '' || segment === '.' || segment === '..');
}

/**
 * Return true when ``url`` is https and targets an allowed git host.
 */
export function isValidGitRepoUrl(url: string, extraAllowedHosts: string[] = []): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') {
      return false;
    }
    const hostname = parsed.hostname.toLowerCase();
    if (isPrivateOrLocalHost(hostname)) {
      return false;
    }
    const allowedHosts = [
      'github.com',
      'gitlab.com',
      'gitee.com',
      ...extraAllowedHosts
        .map((host) => host.trim().toLowerCase().replace(/^www\./, ''))
        .filter(Boolean),
    ];
    return allowedHosts.some(
      (host) => hostname === host || hostname.endsWith('.' + host),
    );
  } catch {
    return false;
  }
}

export function getRepoUrlFromSource(source: SkillSource): string {
  return getPlatformAdapter(source.platform).getRepoUrl(source);
}

export function getCloneUrlFromSource(source: SkillSource): string {
  return getPlatformAdapter(source.platform).getCloneUrl(source);
}

export function isUnderDir(resolvedPath: string, resolvedDir: string): boolean {
  return resolvedPath === resolvedDir || resolvedPath.startsWith(resolvedDir + path.sep);
}

/**
 * Resolve ``inputPath`` to an absolute path, following symlinks when present.
 */
export function safeResolvePath(inputPath: string): string | null {
  try {
    const absolutePath = path.resolve(inputPath);
    if (!fs.existsSync(absolutePath)) {
      return absolutePath;
    }
    return fs.realpathSync(absolutePath);
  } catch {
    return null;
  }
}

/**
 * Return true when ``inputPath`` resolves under ``allowedDir``.
 */
export function isPathSafe(inputPath: string, allowedDir: string): boolean {
  const resolvedInput = safeResolvePath(inputPath);
  const resolvedAllowed = safeResolvePath(allowedDir);
  if (!resolvedInput || !resolvedAllowed) {
    return false;
  }
  return isUnderDir(resolvedInput, resolvedAllowed);
}

/**
 * Return true when ``skillDir`` is under a known skills root.
 */
export function canReadSkillDir(
  skillDir: string,
  extensionUri: vscode.Uri
): boolean {
  const resolved = safeResolvePath(skillDir);
  if (!resolved) {
    return false;
  }

  const extSkills = safeResolvePath(path.join(extensionUri.fsPath, 'skills'));
  if (extSkills && isUnderDir(resolved, extSkills)) {
    return true;
  }

  const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (workspaceFolder) {
    const customSkills = safeResolvePath(path.join(workspaceFolder, 'custom', 'skills'));
    if (customSkills && isUnderDir(resolved, customSkills)) {
      return true;
    }
    const claudeSkills = safeResolvePath(path.join(workspaceFolder, '.claude', 'skills'));
    if (claudeSkills && isUnderDir(resolved, claudeSkills)) {
      return true;
    }
  }

  const home = process.env.HOME || process.env.USERPROFILE || '';
  if (home) {
    const globalClaude = safeResolvePath(path.join(home, '.claude', 'skills'));
    if (globalClaude && isUnderDir(resolved, globalClaude)) {
      return true;
    }
  }

  return false;
}
