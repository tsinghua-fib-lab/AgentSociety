/**
 * 平台适配器接口
 * 统一不同 Git 托管平台（GitHub、GitLab、Gitee）的 API 差异
 */

export interface RepoItem {
  name: string;
  type: 'file' | 'dir' | 'symlink' | 'submodule';
  path: string;
}

export interface SkillSource {
  owner: string;
  repo: string;
  branch: string;
  skillsPath: string;
  platform: 'github' | 'gitlab' | 'gitee';
  baseUrl?: string;
}

export interface PlatformAdapter {
  readonly name: string;
  readonly platform: 'github' | 'gitlab' | 'gitee';

  /**
   * 获取仓库目录内容
   */
  fetchRepoContents(source: SkillSource): Promise<RepoItem[]>;

  /**
   * 获取单个文件内容
   */
  fetchFileContent(source: SkillSource, filePath: string): Promise<string>;

  /**
   * 获取仓库克隆 URL
   */
  getCloneUrl(source: SkillSource): string;

  /**
   * 获取仓库主页 URL
   */
  getRepoUrl(source: SkillSource): string;

  /**
   * 获取文件原始内容 URL（用于预览）
   */
  getRawFileUrl(source: SkillSource, filePath: string): string;
}
