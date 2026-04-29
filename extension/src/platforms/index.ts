/**
 * 平台适配器工厂
 * 根据平台类型返回对应的适配器实例
 */

import type { PlatformAdapter } from './PlatformAdapter';
import { GitHubAdapter } from './GitHubAdapter';
import { GitLabAdapter } from './GitLabAdapter';
import { GiteeAdapter } from './GiteeAdapter';

export type { PlatformAdapter, RepoItem, SkillSource } from './PlatformAdapter';
export { GitHubAdapter } from './GitHubAdapter';
export { GitLabAdapter } from './GitLabAdapter';
export { GiteeAdapter } from './GiteeAdapter';

// 单例实例缓存
const adapters: Record<string, PlatformAdapter> = {};

/**
 * 获取平台适配器
 */
export function getPlatformAdapter(platform: 'github' | 'gitlab' | 'gitee'): PlatformAdapter {
  if (!adapters[platform]) {
    switch (platform) {
      case 'github':
        adapters[platform] = new GitHubAdapter();
        break;
      case 'gitlab':
        adapters[platform] = new GitLabAdapter();
        break;
      case 'gitee':
        adapters[platform] = new GiteeAdapter();
        break;
      default:
        throw new Error(`Unknown platform: ${platform}`);
    }
  }
  return adapters[platform];
}
