/**
 * 技能管理工具函数
 */

import * as path from 'path';
import * as fs from 'fs';
import type { SkillFrontmatter, RawSkillSourceConfig } from '../webview/skillMarketplace/types';
import type { SkillSource } from '../platforms';

/** Claude 技能禁用保管区目录名 */
export const CLAUDE_DISABLED_VAULT = '.agentsociety-disabled-skills';

/** GitHub API 超时时间 */
export const GITHUB_API_TIMEOUT_MS = 45_000;

/** GitHub Raw 文件超时时间 */
export const GITHUB_RAW_TIMEOUT_MS = 28_000;

/** 市场分页大小 */
export const MARKETPLACE_PAGE_SIZE = 10;

/** 默认 Claude 技能源配置（来自 package.json） */
export const DEFAULT_CLAUDE_SKILL_SOURCES: Array<{
  owner: string;
  repo: string;
  branch: string;
  skillsPath: string;
}> = [
  {
    owner: 'anthropics',
    repo: 'skills',
    branch: 'main',
    skillsPath: 'skills'
  },
  {
    owner: 'obra',
    repo: 'superpowers',
    branch: 'main',
    skillsPath: 'skills'
  },
  {
    owner: 'affaan-m',
    repo: 'everything-claude-code',
    branch: 'main',
    skillsPath: '.agents/skills'
  }
];

/** 默认 Agent 技能源配置（无默认源，用户需自行配置） */
export const DEFAULT_AGENT_SKILL_SOURCES: Array<{
  owner: string;
  repo: string;
  branch: string;
  skillsPath: string;
}> = [];

/** 技能分类映射 */
export const CATEGORY_MAP: Record<string, { id: string; name: string; nameZh: string }> = {
  pdf: { id: 'document', name: 'Document Processing', nameZh: '文档处理' },
  docx: { id: 'document', name: 'Document Processing', nameZh: '文档处理' },
  xlsx: { id: 'document', name: 'Document Processing', nameZh: '文档处理' },
  pptx: { id: 'document', name: 'Document Processing', nameZh: '文档处理' },
  'artifacts-builder': { id: 'development', name: 'Development Tools', nameZh: '开发工具' },
  'canvas-design': { id: 'creative', name: 'Creative Tools', nameZh: '创意工具' },
  'algorithmic-art': { id: 'creative', name: 'Creative Tools', nameZh: '创意工具' },
  'mcp-builder': { id: 'integration', name: 'Integrations', nameZh: '集成工具' },
  'webapp-testing': { id: 'development', name: 'Development Tools', nameZh: '开发工具' },
  'skill-creator': { id: 'development', name: 'Development Tools', nameZh: '开发工具' },
  'internal-comms': { id: 'productivity', name: 'Productivity', nameZh: '效率工具' },
  'slack-gif-creator': { id: 'creative', name: 'Creative Tools', nameZh: '创意工具' },
  'brand-guidelines': { id: 'creative', name: 'Creative Tools', nameZh: '创意工具' },
  'theme-factory': { id: 'creative', name: 'Creative Tools', nameZh: '创意工具' }
};

/** GitHub 内容项类型 */
export interface GitHubContentItem {
  name: string;
  type: string;
  path: string;
}

/**
 * 查找目录中的 SKILL.md 文件路径
 */
export function skillMdPathInDir(skillDir: string): string | null {
  const exact = path.join(skillDir, 'SKILL.md');
  if (fs.existsSync(exact)) {
    return exact;
  }
  try {
    for (const f of fs.readdirSync(skillDir)) {
      if (f.toLowerCase() === 'skill.md') {
        return path.join(skillDir, f);
      }
    }
  } catch {
    /* unreadable */
  }
  return null;
}

/**
 * 提取 Markdown 正文（移除 YAML frontmatter）
 */
export function markdownBodyForPreview(full: string): string {
  const normalized = full.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
  const match = normalized.match(/^---\n[\s\S]*?\n---\s*\n?/);
  if (match && match.index === 0) {
    return normalized.slice(match[0].length).trim();
  }
  return normalized.trim();
}

/**
 * 解析 SKILL.md 的 YAML frontmatter
 */
export function parseFrontmatter(content: string): SkillFrontmatter {
  const result: SkillFrontmatter = {};
  const normalized = content.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
  const frontmatterMatch = normalized.match(/^---\n([\s\S]*?)\n---/);

  if (!frontmatterMatch) {
    return result;
  }

  const lines = frontmatterMatch[1].split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }
    const match = trimmed.match(/^([\w-]+):\s*(.*)$/);
    if (match) {
      const key = match[1] as keyof SkillFrontmatter;
      let value: string | string[] = match[2].trim();

      if (value.startsWith('[') && value.endsWith(']')) {
        value = value
          .slice(1, -1)
          .split(',')
          .map((s: string) => s.trim().replace(/['"]/g, ''));
      } else if (value.startsWith('"') && value.endsWith('"')) {
        value = value.slice(1, -1);
      }

      (result as Record<string, string | string[]>)[key] = value;
    }
  }

  return result;
}

/**
 * 格式化技能名称（kebab-case → Title Case）
 */
export function formatSkillName(name: string): string {
  return name
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * 规范化技能源配置
 */
export function normalizeSkillSources(sources: unknown[]): SkillSource[] {
  const out: SkillSource[] = [];
  for (const s of sources) {
    if (!s || typeof s !== 'object') {
      continue;
    }
    const raw = s as RawSkillSourceConfig;
    const owner = String(raw.owner ?? '').trim();
    const repo = String(raw.repo ?? '').trim();
    const branch = String(raw.branch ?? 'main').trim() || 'main';
    const skillsPath = String(raw.skillsPath ?? '')
      .trim()
      .replace(/^\/+|\/+$/g, '');
    const platform = raw.platform === 'gitlab' || raw.platform === 'gitee'
      ? raw.platform
      : 'github';
    const baseUrl = String(raw.baseUrl ?? '').trim() || undefined;
    if (!owner || !repo) {
      continue;
    }
    out.push({ owner, repo, branch, skillsPath, platform, baseUrl });
  }
  return out;
}

/**
 * 检查是否为网络或超时错误
 */
export function isNetworkOrTimeoutError(error: unknown): boolean {
  const e = error as { name?: string; message?: string };
  const msg = (e?.message || String(error)).toLowerCase();
  if (e?.name === 'AbortError') {
    return true;
  }
  return (
    msg.includes('fetch failed') ||
    msg.includes('network') ||
    msg.includes('econnrefused') ||
    msg.includes('enotfound') ||
    msg.includes('etimedout') ||
    msg.includes('timeout') ||
    msg.includes('getaddrinfo')
  );
}

/**
 * 去重市场技能列表
 */
export function dedupeMarketplaceSkills<T extends { id: string; path: string }>(skills: T[]): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const s of skills) {
    const segments = s.path.split('/').filter(Boolean);
    const key = (segments.length ? segments[segments.length - 1] : s.id).toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(s);
  }
  return result;
}
