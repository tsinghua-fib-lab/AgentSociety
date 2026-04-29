/**
 * Gitee 平台适配器
 * Gitee API 与 GitHub 类似，但有一些差异
 */

import * as vscode from 'vscode';
import type { PlatformAdapter, RepoItem, SkillSource } from './PlatformAdapter';

export class GiteeAdapter implements PlatformAdapter {
  readonly name = 'Gitee';
  readonly platform = 'gitee' as const;

  private readonly defaultApiBase = 'https://gitee.com/api/v5';
  private readonly defaultWebBase = 'https://gitee.com';
  private readonly timeoutMs = 45000;
  private readonly rawTimeoutMs = 28000;

  private _getApiBase(source: SkillSource): string {
    if (source.baseUrl) {
      return source.baseUrl.replace(/\/+$/, '') + '/api/v5';
    }
    return this.defaultApiBase;
  }

  private _getWebBase(source: SkillSource): string {
    if (source.baseUrl) {
      return source.baseUrl.replace(/\/+$/, '');
    }
    return this.defaultWebBase;
  }

  private _getToken(source: SkillSource): string | undefined {
    // 优先使用 source 中的 token（如果未来支持）
    // 然后使用全局配置
    return vscode.workspace
      .getConfiguration('agentSkills')
      .get<string>('giteeToken', '')
      ?.trim() || undefined;
  }

  private _buildUrl(base: string, path: string, params: Record<string, string>): string {
    const url = new URL(`${base}${path}`);
    for (const [key, value] of Object.entries(params)) {
      if (value) {
        url.searchParams.set(key, value);
      }
    }
    return url.toString();
  }

  private async _fetchWithTimeout(
    url: string,
    timeoutMs: number
  ): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, {
        signal: controller.signal,
        headers: {
          'User-Agent': 'AI-Social-Scientist-VSCode',
        },
      });
    } finally {
      clearTimeout(timer);
    }
  }

  async fetchRepoContents(source: SkillSource): Promise<RepoItem[]> {
    const apiBase = this._getApiBase(source);
    const apiPath = source.skillsPath
      ? `/${source.skillsPath.replace(/^\/+|\/+$/g, '')}`
      : '';
    const token = this._getToken(source);

    // Gitee Contents API (类似 GitHub)
    const apiUrl = this._buildUrl(
      apiBase,
      `/repos/${source.owner}/${source.repo}/contents${apiPath}`,
      {
        ref: source.branch,
        ...(token ? { access_token: token } : {}),
      }
    );

    const response = await this._fetchWithTimeout(apiUrl, this.timeoutMs);

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Gitee API error: ${response.status} ${response.statusText} ${text.slice(0, 200)}`);
    }

    const contents = (await response.json()) as unknown;
    if (!Array.isArray(contents)) {
      const errBody =
        typeof contents === 'object' && contents !== null && 'message' in contents
          ? String((contents as { message: string }).message)
          : JSON.stringify(contents);
      throw new Error(`Gitee API returned non-array: ${errBody}`);
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
    const apiBase = this._getApiBase(source);
    const token = this._getToken(source);
    // filePath 已经是相对于仓库根目录的完整路径

    const apiUrl = this._buildUrl(
      apiBase,
      `/repos/${source.owner}/${source.repo}/contents/${filePath}`,
      {
        ref: source.branch,
        ...(token ? { access_token: token } : {}),
      }
    );

    const response = await this._fetchWithTimeout(apiUrl, this.rawTimeoutMs);

    if (!response.ok) {
      throw new Error(`Failed to fetch file: ${response.status} ${response.statusText}`);
    }

    // Gitee API 返回 JSON，包含 content 字段（base64 编码）
    const data = (await response.json()) as unknown;
    if (
      typeof data === 'object' &&
      data !== null &&
      'content' in data &&
      typeof (data as { content: string }).content === 'string'
    ) {
      // Base64 解码
      const base64 = (data as { content: string }).content.replace(/\n/g, '');
      return Buffer.from(base64, 'base64').toString('utf-8');
    }

    // 如果直接返回文本
    if (typeof data === 'string') {
      return data;
    }

    throw new Error('Gitee API returned unexpected content format');
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
    // Gitee raw URL 格式: /raw/<branch>/<path>
    return `${webBase}/${source.owner}/${source.repo}/raw/${source.branch}/${filePath}`;
  }
}
