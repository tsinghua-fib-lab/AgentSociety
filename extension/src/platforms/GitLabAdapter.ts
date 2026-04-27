/**
 * GitLab 平台适配器
 * 支持 gitlab.com 和自建 GitLab 实例
 */

import * as vscode from 'vscode';
import type { PlatformAdapter, RepoItem, SkillSource } from './PlatformAdapter';

export class GitLabAdapter implements PlatformAdapter {
  readonly name = 'GitLab';
  readonly platform = 'gitlab' as const;

  private readonly defaultApiBase = 'https://gitlab.com/api/v4';
  private readonly defaultWebBase = 'https://gitlab.com';
  private readonly timeoutMs = 45000;
  private readonly rawTimeoutMs = 28000;

  private _getApiBase(source: SkillSource): string {
    if (source.baseUrl) {
      // 移除尾部斜杠，添加 /api/v4
      return source.baseUrl.replace(/\/+$/, '') + '/api/v4';
    }
    return this.defaultApiBase;
  }

  private _getWebBase(source: SkillSource): string {
    if (source.baseUrl) {
      return source.baseUrl.replace(/\/+$/, '');
    }
    return this.defaultWebBase;
  }

  private _headers(source: SkillSource): Record<string, string> {
    const headers: Record<string, string> = {
      'User-Agent': 'AI-Social-Scientist-VSCode',
    };
    // GitLab 使用 Private-Token 或 JOB-TOKEN
    const token = vscode.workspace
      .getConfiguration('agentSkills')
      .get<string>('gitlabToken', '')
      ?.trim();
    if (token) {
      headers['Private-Token'] = token;
    }
    return headers;
  }

  /**
   * GitLab 项目 ID 是 URL 编码的 owner/repo 路径
   * 例如: owner/repo -> owner%2Frepo
   */
  private _projectId(source: SkillSource): string {
    return encodeURIComponent(`${source.owner}/${source.repo}`);
  }

  private async _fetchWithTimeout(
    url: string,
    headers: Record<string, string>,
    timeoutMs: number
  ): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { headers, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  async fetchRepoContents(source: SkillSource): Promise<RepoItem[]> {
    const apiBase = this._getApiBase(source);
    const projectId = this._projectId(source);
    const path = source.skillsPath
      ? `&path=${encodeURIComponent(source.skillsPath.replace(/^\/+|\/+$/g, ''))}`
      : '';

    // GitLab Tree API
    const apiUrl = `${apiBase}/projects/${projectId}/repository/tree?ref=${encodeURIComponent(source.branch)}${path}&per_page=100`;

    const response = await this._fetchWithTimeout(apiUrl, this._headers(source), this.timeoutMs);

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`GitLab API error: ${response.status} ${response.statusText} ${text.slice(0, 200)}`);
    }

    const contents = (await response.json()) as unknown;
    if (!Array.isArray(contents)) {
      throw new Error(`GitLab API returned non-array: ${JSON.stringify(contents).slice(0, 200)}`);
    }

    return contents
      .filter((item): item is { name: string; type: string; path: string } =>
        item && typeof item.name === 'string' && typeof item.type === 'string'
      )
      .map((item) => ({
        name: item.name,
        // GitLab 使用 'tree' 表示目录，'blob' 表示文件
        type: item.type === 'tree' ? 'dir' : item.type === 'blob' ? 'file' : (item.type as RepoItem['type']),
        path: item.path,
      }));
  }

  async fetchFileContent(source: SkillSource, filePath: string): Promise<string> {
    const apiBase = this._getApiBase(source);
    const projectId = this._projectId(source);
    // filePath 已经是相对于仓库根目录的完整路径

    // GitLab Raw File API
    const apiUrl = `${apiBase}/projects/${projectId}/repository/files/${encodeURIComponent(filePath)}/raw?ref=${encodeURIComponent(source.branch)}`;

    const response = await this._fetchWithTimeout(apiUrl, this._headers(source), this.rawTimeoutMs);

    if (!response.ok) {
      throw new Error(`Failed to fetch file: ${response.status} ${response.statusText}`);
    }

    return response.text();
  }

  getCloneUrl(source: SkillSource): string {
    const webBase = this._getWebBase(source);
    return `${webBase}/${source.owner}/${source.repo}.git`;
  }

  getRepoUrl(source: SkillSource): string {
    const webBase = this._getWebBase(source);
    return `${webBase}/${source.owner}/${source.repo}`;
  }

  getRawFileUrl(source: SkillSource, filePath: string): string {
    const webBase = this._getWebBase(source);
    // filePath 已经是相对于仓库根目录的完整路径，不需要再添加 skillsPath
    // GitLab raw URL 格式: /-/raw/<branch>/<path>
    return `${webBase}/${source.owner}/${source.repo}/-/raw/${source.branch}/${filePath}`;
  }
}
