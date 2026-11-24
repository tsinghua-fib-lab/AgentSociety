import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';

export const WORKSPACE_EXPORT_FORMAT_VERSION = 2;
export const WORKSPACE_EXPORT_KIND = 'agentsociety-workspace';
export const WORKSPACE_EXPORT_GENERATOR = 'ai-social-scientist';
export const WORKSPACE_EXPORT_MANIFEST_RELATIVE_PATH = '_agentsociety/export-manifest.json';
export const WORKSPACE_EXPORT_SHARE_RELATIVE_PATH = '_agentsociety/SHARE.md';

export type WorkspaceExportTier = 'core' | 'agent' | 'external' | 'optional';

export type WorkspaceExportRootRecord = {
  archivePath: string;
  kind: 'file' | 'directory';
  tier: WorkspaceExportTier;
  bytes: number;
  fileCount: number;
};

export type WorkspaceExportNotice = {
  title: string;
  copyright: string;
  redistribution: string;
  secrets: string;
  importer: string;
};

export type WorkspaceExportManifest = {
  formatVersion: number;
  exportKind: typeof WORKSPACE_EXPORT_KIND;
  generator: typeof WORKSPACE_EXPORT_GENERATOR;
  exportedAt: string;
  workspaceName: string;
  extensionVersion: string;
  roots: WorkspaceExportRootRecord[];
  excluded: string[];
  secretsOmitted: true;
  contentHash: string;
  notice: WorkspaceExportNotice;
};

export type WorkspaceExportSelectionIssue = {
  level: 'error' | 'warning';
  code: string;
};

export type WorkspaceExportSelectionValidation = {
  issues: WorkspaceExportSelectionIssue[];
  totalBytes: number;
  totalFiles: number;
};

export type ManifestParseResult =
  | { ok: true; manifest: WorkspaceExportManifest }
  | { ok: false; error: 'invalid' | 'unsupported_version' };

const CORE_ROOT_FILES = new Set(['TOPIC.md']);
const CORE_ROOT_DIRECTORIES = new Set([
  '.agentsociety',
  'papers',
  'user_data',
  'datasets',
  'custom',
  'presentation',
  'synthesis',
  'paper',
]);

/** Top-level names that are never useful as research-share options. */
export const NON_RESEARCH_OPTIONAL_ROOTS = new Set([
  'packages',
  'extension',
  'frontend',
  'node_modules',
  '.github',
  '.git',
  'docs',
  'static',
  'scripts',
  'Makefile',
  'Dockerfile',
  'uv.lock',
  'pyproject.toml',
  'CHANGELOG.md',
  'LICENSE',
  'README.md',
]);

/** Recommended roots that should always appear in the picker (even if missing). */
export const RECOMMENDED_EXPORT_ROOTS: Array<{
  archivePath: string;
  kind: 'file' | 'directory';
}> = [
  { archivePath: 'TOPIC.md', kind: 'file' },
  { archivePath: 'papers', kind: 'directory' },
  { archivePath: 'paper', kind: 'directory' },
  { archivePath: '.agentsociety', kind: 'directory' },
  { archivePath: 'custom', kind: 'directory' },
  { archivePath: 'datasets', kind: 'directory' },
  { archivePath: 'user_data', kind: 'directory' },
  { archivePath: 'presentation', kind: 'directory' },
  { archivePath: 'synthesis', kind: 'directory' },
  { archivePath: 'CLAUDE.md', kind: 'file' },
  { archivePath: 'AGENTS.md', kind: 'file' },
  { archivePath: '.claude', kind: 'directory' },
];

const AGENT_ROOT_FILES = new Set(['CLAUDE.md', 'AGENTS.md']);
const AGENT_ROOT_DIRECTORIES = new Set(['.claude']);

/**
 * Human-readable exclusion list written into export manifests / SHARE.md.
 * Keep in sync with {@link shouldExcludeWorkspacePath}.
 */
export const WORKSPACE_EXPORT_EXCLUDED_PATTERNS = [
  '.env / .env.*',
  '.git',
  'node_modules',
  '.venv / venv',
  '__pycache__',
  'agentsociety_data',
  'mineru_output',
  'auth.json / credentials.json / secrets.json',
  '.netrc / .npmrc / .pypirc / id_rsa / id_ed25519',
  '*.pem / *.key',
  'easypaper_config.yaml',
  '.cursor / .vscode',
];

const EXCLUDED_DIRECTORY_NAMES = new Set([
  '.git',
  '.hg',
  '.svn',
  'node_modules',
  '.venv',
  'venv',
  '__pycache__',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
  '.cursor',
  '.vscode',
  'agentsociety_data',
  'mineru_output',
]);

const EXCLUDED_FILE_NAMES = new Set([
  '.DS_Store',
  'Thumbs.db',
  '.netrc',
  '.npmrc',
  '.pypirc',
  'auth.json',
  'credentials.json',
  'secrets.json',
  'id_rsa',
  'id_ed25519',
  'easypaper_config.yaml',
]);

const IMPORT_ONLY_EXCLUDED_DIRECTORY_NAMES = new Set([
  '_agentsociety',
]);

export function normalizeArchiveRelativePath(relativePath: string): string {
  return relativePath.replace(/\\/g, '/').replace(/^\.\//, '').replace(/\/+$/, '');
}

export function isSecretEnvFileName(fileName: string): boolean {
  return fileName === '.env' || fileName.startsWith('.env.');
}

/**
 * Return true when a workspace-relative path must be omitted from export/import.
 */
export function shouldExcludeWorkspacePath(relativePath: string): boolean {
  const normalized = normalizeArchiveRelativePath(relativePath);
  if (!normalized || normalized === '.') {
    return false;
  }

  const segments = normalized.split('/');
  const fileName = segments[segments.length - 1];

  if (segments.some((segment) => EXCLUDED_DIRECTORY_NAMES.has(segment))) {
    return true;
  }
  if (EXCLUDED_FILE_NAMES.has(fileName) || isSecretEnvFileName(fileName)) {
    return true;
  }
  if (/\.(pyc|pyo)$/i.test(fileName)) {
    return true;
  }
  if (/\.(pem|key)$/i.test(fileName)) {
    return true;
  }
  return false;
}

/**
 * Return true when an extracted archive path must not be written on import.
 * Adds export-sidecar skipping on top of {@link shouldExcludeWorkspacePath}.
 */
export function shouldSkipImportPath(relativePath: string): boolean {
  const normalized = normalizeArchiveRelativePath(relativePath);
  if (!normalized || normalized === '.') {
    return false;
  }
  if (!isSafeArchivePath(normalized)) {
    return true;
  }
  if (normalized.split('/').some((segment) => IMPORT_ONLY_EXCLUDED_DIRECTORY_NAMES.has(segment))) {
    return true;
  }
  return shouldExcludeWorkspacePath(normalized);
}

export function resolveExportTier(archivePath: string, source: 'workspace' | 'external'): WorkspaceExportTier {
  if (source === 'external') {
    return 'external';
  }
  if (CORE_ROOT_FILES.has(archivePath) || CORE_ROOT_DIRECTORIES.has(archivePath)) {
    return 'core';
  }
  if (/^hypothesis_[^/\\]+$/.test(archivePath)) {
    return 'core';
  }
  if (AGENT_ROOT_FILES.has(archivePath) || AGENT_ROOT_DIRECTORIES.has(archivePath)) {
    return 'agent';
  }
  return 'optional';
}

export function isDefaultExportTier(tier: WorkspaceExportTier): boolean {
  return tier === 'core' || tier === 'agent';
}

export function isNonResearchOptionalRoot(archivePath: string): boolean {
  const top = normalizeArchiveRelativePath(archivePath).split('/')[0] ?? '';
  return NON_RESEARCH_OPTIONAL_ROOTS.has(top);
}

export function resolveSafeExportSymlink(
  symlinkPath: string,
  allowedRoot: string,
): string | undefined {
  try {
    const resolved = fs.realpathSync(symlinkPath);
    const relative = path.relative(fs.realpathSync(allowedRoot), resolved);
    if (
      relative === '..' || relative.startsWith('..' + path.sep) ||
      path.isAbsolute(relative) || shouldExcludeWorkspacePath(relative)
    ) {
      return undefined;
    }
    return resolved;
  } catch {
    return undefined;
  }
}

export function formatExportRootSummary(roots: Array<{ archivePath: string }>): string {
  const names = roots.map((root) => root.archivePath).filter(Boolean);
  if (names.length === 0) {
    return '';
  }
  const preview = names.slice(0, 6).join(', ');
  return names.length > 6 ? `${preview} (+${names.length - 6})` : preview;
}

export function digestFileContents(filePath: string): string {
  const hash = crypto.createHash('sha256');
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  const file = fs.openSync(filePath, 'r');
  try {
    let bytesRead = 0;
    do {
      bytesRead = fs.readSync(file, buffer, 0, buffer.length, null);
      if (bytesRead > 0) {
        hash.update(buffer.subarray(0, bytesRead));
      }
    } while (bytesRead > 0);
    return hash.digest('hex');
  } finally {
    fs.closeSync(file);
  }
}

export function isExportSidecar(relativePath: string): boolean {
  const normalized = relativePath.replace(/\\/g, '/');
  return normalized === WORKSPACE_EXPORT_MANIFEST_RELATIVE_PATH || normalized === WORKSPACE_EXPORT_SHARE_RELATIVE_PATH;
}

export function canonicalizeContentHash(entries: Array<{ relativePath: string; sha256: string }>): string {
  const lines = entries
    .map((entry) => `${entry.relativePath.replace(/\\/g, '/')}\t${entry.sha256}`)
    .sort();
  return crypto.createHash('sha256').update(lines.join('\n')).digest('hex');
}

export function buildExportManifest(input: {
  workspaceName: string;
  extensionVersion: string;
  roots: WorkspaceExportRootRecord[];
  contentHash: string;
  notice: WorkspaceExportNotice;
}): WorkspaceExportManifest {
  return {
    formatVersion: WORKSPACE_EXPORT_FORMAT_VERSION,
    exportKind: WORKSPACE_EXPORT_KIND,
    generator: WORKSPACE_EXPORT_GENERATOR,
    exportedAt: new Date().toISOString(),
    workspaceName: input.workspaceName,
    extensionVersion: input.extensionVersion,
    roots: input.roots,
    excluded: [...WORKSPACE_EXPORT_EXCLUDED_PATTERNS],
    secretsOmitted: true,
    contentHash: input.contentHash,
    notice: input.notice,
  };
}

export function buildShareMarkdown(
  manifest: WorkspaceExportManifest,
  labels: { includedTitle: string; excludedTitle: string },
): string {
  const roots = manifest.roots.map((root) => `- \`${root.archivePath}\``).join('\n');
  return [
    `# ${manifest.notice.title}`,
    '',
    manifest.notice.copyright,
    '',
    manifest.notice.redistribution,
    '',
    manifest.notice.secrets,
    '',
    manifest.notice.importer,
    '',
    `## ${labels.includedTitle}`,
    '',
    roots || '-',
    '',
    `## ${labels.excludedTitle}`,
    '',
    manifest.excluded.map((item) => `- \`${item}\``).join('\n'),
    '',
  ].join('\n');
}

export function writeExportSidecars(
  stagingPath: string,
  manifest: WorkspaceExportManifest,
  shareMarkdown: string,
): void {
  const manifestPath = path.join(stagingPath, WORKSPACE_EXPORT_MANIFEST_RELATIVE_PATH);
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf-8');
  fs.writeFileSync(
    path.join(stagingPath, WORKSPACE_EXPORT_SHARE_RELATIVE_PATH),
    shareMarkdown,
    'utf-8',
  );
}

export function parseExportManifest(raw: unknown): ManifestParseResult {
  if (!raw || typeof raw !== 'object') {
    return { ok: false, error: 'invalid' };
  }
  const value = raw as Record<string, unknown>;
  if (value.exportKind !== WORKSPACE_EXPORT_KIND || value.generator !== WORKSPACE_EXPORT_GENERATOR) {
    return { ok: false, error: 'invalid' };
  }
  if (value.formatVersion !== WORKSPACE_EXPORT_FORMAT_VERSION) {
    return { ok: false, error: 'unsupported_version' };
  }
  if (typeof value.exportedAt !== 'string' || typeof value.workspaceName !== 'string' || typeof value.extensionVersion !== 'string') {
    return { ok: false, error: 'invalid' };
  }
  if (!isSafeWorkspaceName(value.workspaceName)) {
    return { ok: false, error: 'invalid' };
  }
  if (value.secretsOmitted !== true || typeof value.contentHash !== 'string' || !/^[a-f0-9]{64}$/.test(value.contentHash)) {
    return { ok: false, error: 'invalid' };
  }
  if (
    !Array.isArray(value.roots) ||
    value.roots.length === 0 ||
    value.roots.length > 1_000 ||
    !Array.isArray(value.excluded) ||
    value.excluded.some((item) => typeof item !== 'string')
  ) {
    return { ok: false, error: 'invalid' };
  }
  const allowedTiers = new Set(['core', 'agent', 'external', 'optional']);
  const rootPaths = new Set<string>();
  for (const root of value.roots) {
    if (!root || typeof root !== 'object') {
      return { ok: false, error: 'invalid' };
    }
    const record = root as Record<string, unknown>;
    if (
      typeof record.archivePath !== 'string' ||
      record.archivePath.length > 500 ||
      !isSafeArchivePath(record.archivePath) ||
      rootPaths.has(record.archivePath)
    ) {
      return { ok: false, error: 'invalid' };
    }
    rootPaths.add(record.archivePath);
    if (record.kind !== 'file' && record.kind !== 'directory') {
      return { ok: false, error: 'invalid' };
    }
    if (typeof record.tier !== 'string' || !allowedTiers.has(record.tier)) {
      return { ok: false, error: 'invalid' };
    }
    if (
      typeof record.bytes !== 'number' ||
      !Number.isSafeInteger(record.bytes) ||
      record.bytes < 0 ||
      typeof record.fileCount !== 'number' ||
      !Number.isSafeInteger(record.fileCount) ||
      record.fileCount < 0
    ) {
      return { ok: false, error: 'invalid' };
    }
  }
  const notice = value.notice;
  if (!notice || typeof notice !== 'object') {
    return { ok: false, error: 'invalid' };
  }
  const noticeRecord = notice as Record<string, unknown>;
  for (const key of ['title', 'copyright', 'redistribution', 'secrets', 'importer']) {
    if (typeof noticeRecord[key] !== 'string' || !noticeRecord[key]) {
      return { ok: false, error: 'invalid' };
    }
  }
  return { ok: true, manifest: value as WorkspaceExportManifest };
}

export function isSafeArchivePath(relativePath: string): boolean {
  const normalized = relativePath.replace(/\\/g, '/').replace(/^\.\//, '').replace(/\/+$/, '');
  if (!normalized || normalized.startsWith('/') || /(?:^|\/)[A-Za-z]:/.test(normalized) || normalized.includes(':')) {
    return false;
  }
  return !normalized.split('/').some((segment) => segment === '' || segment === '.' || segment === '..');
}

export function isSafeWorkspaceName(name: string): boolean {
  const normalized = name.trim();
  if (
    normalized !== name ||
    normalized.length === 0 ||
    normalized.length > 100 ||
    normalized.endsWith('.') ||
    /[<>:"/\\|?*]/.test(normalized) ||
    [...normalized].some((character) => character.charCodeAt(0) < 32)
  ) {
    return false;
  }
  const windowsReserved = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i;
  return !windowsReserved.test(normalized) &&
    isSafeArchivePath(normalized) &&
    !normalized.includes('/');
}

export function planImportTarget(
  parentDirectory: string,
  workspaceName: string,
):
  | { ok: true; targetPath: string }
  | { ok: false; error: 'invalid_name' | 'parent_invalid' | 'target_exists' } {
  if (!isSafeWorkspaceName(workspaceName)) {
    return { ok: false, error: 'invalid_name' };
  }
  let parentStats: fs.Stats;
  try {
    parentStats = fs.statSync(parentDirectory);
  } catch {
    return { ok: false, error: 'parent_invalid' };
  }
  if (!parentStats.isDirectory()) {
    return { ok: false, error: 'parent_invalid' };
  }
  const targetPath = path.join(parentDirectory, workspaceName);
  if (fs.existsSync(targetPath)) {
    return { ok: false, error: 'target_exists' };
  }
  return { ok: true, targetPath };
}

export function verifyZipMagic(zipPath: string): boolean {
  const stats = fs.statSync(zipPath);
  if (!stats.isFile() || stats.size < 22) {
    return false;
  }
  const fd = fs.openSync(zipPath, 'r');
  const header = Buffer.alloc(4);
  fs.readSync(fd, header, 0, 4, 0);
  fs.closeSync(fd);
  return header[0] === 0x50 && header[1] === 0x4b && (header[2] === 0x03 || header[2] === 0x05 || header[2] === 0x07);
}

export function validateExportSelection(input: {
  selectedRoots: WorkspaceExportRootRecord[];
}): WorkspaceExportSelectionValidation {
  const issues: WorkspaceExportSelectionIssue[] = [];
  const totalBytes = input.selectedRoots.reduce((sum, root) => sum + root.bytes, 0);
  const totalFiles = input.selectedRoots.reduce((sum, root) => sum + root.fileCount, 0);

  if (input.selectedRoots.length === 0) {
    issues.push({ level: 'error', code: 'empty_selection' });
    return { issues, totalBytes, totalFiles };
  }

  if (totalFiles === 0) {
    issues.push({ level: 'error', code: 'empty_payload' });
  }

  const hasCoreResearch = input.selectedRoots.some((root) =>
    root.archivePath === 'TOPIC.md' ||
    root.archivePath === 'papers' ||
    root.archivePath === 'paper' ||
    root.archivePath === 'presentation' ||
    root.archivePath === 'synthesis' ||
    root.archivePath.startsWith('hypothesis_')
  );

  if (!hasCoreResearch) {
    issues.push({ level: 'warning', code: 'no_core_research' });
  }

  const hasAgentConfig = input.selectedRoots.some((root) => root.tier === 'agent');
  if (!hasAgentConfig) {
    issues.push({ level: 'warning', code: 'no_agent_config' });
  }

  if (input.selectedRoots.some((root) => root.tier === 'external')) {
    issues.push({ level: 'warning', code: 'includes_external' });
  }

  if (input.selectedRoots.some((root) => root.kind === 'directory' && root.fileCount === 0)) {
    issues.push({ level: 'warning', code: 'includes_empty_directories' });
  }

  if (totalBytes > 512 * 1024 * 1024) {
    issues.push({ level: 'warning', code: 'large_archive' });
  }

  issues.push({ level: 'warning', code: 'share_notice' });

  return { issues, totalBytes, totalFiles };
}
