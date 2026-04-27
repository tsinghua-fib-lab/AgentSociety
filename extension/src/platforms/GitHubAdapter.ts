/**
 * GitHub 平台适配器
 */

import * as vscode from 'vscode';
import type { PlatformAdapter, RepoItem, SkillSource } from './PlatformAdapter';

export class GitHubAdapter implements PlatformAdapter {
  readonly name = 'GitHub';
  readonly platform = 'github' as const;

  private readonly defaultApiBase = 'https://api.github.com';
  private readonly defaultRawBase = 'https://raw.githubusercontent.com';
  private readonly timeoutMs = 45000;
  private readonly rawTimeoutMs = 28000;

  private _headers(): Record<string, string> {
    const headers: Record<string, string> = {
      Accept: 'application/vnd.github.v3+json',
      'User-Agent': 'AI-Social-Scientist-VSCode',
    };
    const token = vscode.workspace
      .getConfiguration('agentSkills')
      .get<string>('githubToken', '')
      ?.trim();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
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
    const base = `${this.defaultApiBase}/repos/${source.owner}/${source.repo}/contents`;
    const apiPath = source.skillsPath
      ? `${source.skillsPath.replace(/^\/+|\/+$/g, '')}`
      : '';
    const apiUrl = apiPath
      ? `${base}/${apiPath}?ref=${encodeURIComponent(source.branch)}`
      : `${base}?ref=${encodeURIComponent(source.branch)}`;

    const response = await this._fetchWithTimeout(apiUrl, this._headers(), this.timeoutMs);

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`GitHub API error: ${response.status} ${response.statusText} ${text.slice(0, 200)}`);
    }

    const contents = (await response.json()) as unknown;
    if (!Array.isArray(contents)) {
      const errBody =
        typeof contents === 'object' && contents !== null && 'message' in contents
          ? String((contents as { message: string }).message)
          : JSON.stringify(contents);
      throw new Error(`GitHub API returned non-array: ${errBody}`);
    }

    return contents
      .filter((item): item is { name: string; type: string; path: string } =>
        item && typeof item.name === 'string' && typeof item.type === 'string'
      )
      .map((item) => ({
        name: item.name,
        type: item.type as RepoItem['type'],
        path: item.path,
      }));
  }

  async fetchFileContent(source: SkillSource, filePath: string): Promise<string> {
    const url = this.getRawFileUrl(source, filePath);
    const response = await this._fetchWithTimeout(
      url,
      { 'User-Agent': 'AI-Social-Scientist-VSCode' },
      this.rawTimeoutMs
    );

    if (!response.ok) {
      throw new Error(`Failed to fetch file: ${response.status} ${response.statusText}`);
    }

    return response.text();
  }

  getCloneUrl(source: SkillSource): string {
    return `https://github.com/${source.owner}/${source.repo}.git`;
  }

  getRepoUrl(source: SkillSource): string {
    return `https://github.com/${source.owner}/${source.repo}`;
  }

  getRawFileUrl(source: SkillSource, filePath: string): string {
    // filePath 已经是相对于仓库根目录的完整路径，不需要再添加 skillsPath
    return `${this.defaultRawBase}/${source.owner}/${source.repo}/${source.branch}/${filePath}`;
  }
}
