/**
 * 技能管理安全验证函数
 */

import * as path from 'path';
import * as fs from 'fs';
import * as vscode from 'vscode';
import { getPlatformAdapter, type SkillSource } from '../platforms';

/**
 * 校验 Git 分支名是否安全
 * 只允许字母、数字、连字符、下划线、点和斜杠
 */
export function isValidGitBranch(branch: string): boolean {
  // Git 分支名规则：不能以 . 或 - 开头，不能包含 .., ~, ^, :, ?, *, [, \, 空格等
  const validBranchPattern = /^[a-zA-Z0-9][a-zA-Z0-9._/-]*$/;
  return validBranchPattern.test(branch) &&
    !branch.includes('..') &&
    !branch.endsWith('/') &&
    !branch.endsWith('.');
}

/**
 * 校验 Git 仓库 URL 是否安全
 * 只允许 https:// 和 git:// 协议的 GitHub/GitLab/Gitee URL
 */
export function isValidGitRepoUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    // 只允许 https 和 git 协议
    if (!['https:', 'git:'].includes(parsed.protocol)) {
      return false;
    }
    // 只允许已知平台
    const allowedHosts = ['github.com', 'gitlab.com', 'gitee.com'];
    const isKnownHost = allowedHosts.some(
      (host) => parsed.hostname === host || parsed.hostname.endsWith('.' + host)
    );
    if (!isKnownHost) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

/**
 * 从源配置生成仓库 URL
 */
export function getRepoUrlFromSource(source: SkillSource): string {
  const adapter = getPlatformAdapter(source.platform);
  return adapter.getRepoUrl(source);
}

/**
 * 从源配置生成克隆 URL
 */
export function getCloneUrlFromSource(source: SkillSource): string {
  const adapter = getPlatformAdapter(source.platform);
  return adapter.getCloneUrl(source);
}

/**
 * 检查路径是否在指定目录下
 */
export function isUnderDir(resolvedPath: string, resolvedDir: string): boolean {
  return resolvedPath === resolvedDir || resolvedPath.startsWith(resolvedDir + path.sep);
}

/**
 * 安全地解析路径，处理符号链接
 * 返回路径的真实绝对路径，如果路径不存在或无法访问则返回 null
 */
export function safeResolvePath(inputPath: string): string | null {
  try {
    // 首先解析为绝对路径
    const absolutePath = path.resolve(inputPath);

    // 检查路径是否存在
    if (!fs.existsSync(absolutePath)) {
      return absolutePath; // 不存在的路径，返回解析后的路径用于后续检查
    }

    // 使用 realpath 获取真实路径（解析符号链接）
    const realPath = fs.realpathSync(absolutePath);
    return realPath;
  } catch {
    return null;
  }
}

/**
 * 检查路径是否在允许的目录内（安全版本，处理符号链接）
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
 * 检查是否可以读取技能目录
 */
export function canReadSkillDir(
  skillDir: string,
  extensionUri: vscode.Uri
): boolean {
  const resolved = safeResolvePath(skillDir);
  if (!resolved) {
    return false;
  }

  // 检查扩展自带技能目录
  const extSkills = safeResolvePath(path.join(extensionUri.fsPath, 'skills'));
  if (extSkills && isUnderDir(resolved, extSkills)) {
    return true;
  }

  // 检查工作区目录
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (workspaceFolder) {
    // 检查 custom/skills
    const customSkills = safeResolvePath(path.join(workspaceFolder, 'custom', 'skills'));
    if (customSkills && isUnderDir(resolved, customSkills)) {
      return true;
    }
    // 检查 .claude/skills
    const claudeSkills = safeResolvePath(path.join(workspaceFolder, '.claude', 'skills'));
    if (claudeSkills && isUnderDir(resolved, claudeSkills)) {
      return true;
    }
  }

  // 检查全局 Claude 技能目录
  const home = process.env.HOME || process.env.USERPROFILE || '';
  if (home) {
    const globalClaude = safeResolvePath(path.join(home, '.claude', 'skills'));
    if (globalClaude && isUnderDir(resolved, globalClaude)) {
      return true;
    }
  }

  return false;
}
