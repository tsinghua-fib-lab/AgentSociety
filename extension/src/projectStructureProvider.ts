/**
 * 项目结构提供者 (Project Structure Provider)
 *
 * 这个文件实现了VSCode左侧边栏的树形视图，用于显示研究项目的层次结构。
 *
 * VSCode插件开发核心概念：
 * 1. TreeDataProvider: 实现这个接口可以创建自定义的树形视图
 * 2. TreeItem: 树形视图中的每个节点都是一个TreeItem
 * 3. FileSystemWatcher: 监听文件系统变化，实现实时更新
 * 4. EventEmitter: VSCode的事件系统，用于通知视图更新
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，注册TreeView和命令
 * - @extension/src/apiClient.ts - 调用后端API（初始化工作区、模块扫描等）
 * - @extension/src/workspaceManager.ts - 工作区状态管理
 *
 * 后端API：
 * - @packages/agentsociety2/agentsociety2/backend/routers/custom.py - /api/v1/custom/*
 * - @packages/agentsociety2/agentsociety2/backend/routers/modules.py - /api/v1/modules/*
 */

import * as vscode from 'vscode';
import { hasConfiguredLlmApiKey } from './runtimeConfig';
import * as path from 'path';
import * as fs from 'fs';
import * as yaml from 'js-yaml';
import { localize, isExtensionZh } from './i18n';
import { ApiClient } from './apiClient';
import { WorkspaceManager } from './workspaceManager';
import { getMainOutputChannel } from './shared/outputChannels';
import {
  listReviewRoundDirs,
  loadReviewRoundSummary,
  recommendationLabel,
  roundTreeDescription,
  reviewerTreeDescription,
  scoreTone,
} from './paperReviewUtils';

const IGNORED_DIR_NAMES = new Set([
  '__pycache__',
  '.git',
  '.hg',
  '.svn',
  '.vscode',
  'node_modules',
  '.venv',
  'venv',
  'virtualenv',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
  '.ipynb_checkpoints',
  'dist',
  'out',
  'build',
  'agentsociety_data',
  'logs',
  'mineru_output',
  '.eggs',
]);

const CUSTOM_SKILLS_PACKAGE_FILES = new Set([
  '__init__.py',
  'README.md',
  'readme.md',
  'py.typed',
]);

/** Boilerplate / scaffolding files users should not manage in the tree. */
const CUSTOM_CODE_BOILERPLATE_FILES = new Set([
  '__init__.py',
  'py.typed',
  '.gitkeep',
  'conftest.py',
]);

/** Scaffolding / cache dirs under custom/agents|envs. */
const CUSTOM_CODE_HIDDEN_DIRS = new Set([
  'examples',
  'tests',
  'test',
  '_tests',
  'fixtures',
  '.cache',
]);

const CUSTOM_SKILL_CHILD_DIRS = new Set(['scripts', 'references']);

const IGNORED_FILE_NAMES = new Set([
  '.DS_Store',
  'Thumbs.db',
  '.gitkeep',
]);

const IGNORED_FILE_EXTS = new Set([
  '.pyc',
  '.pyo',
  '.swp',
  '.swo',
  '.coverage',
  '.tmp',
  '.bak',
  '.lock',
]);

function shouldHideFsEntry(entryName: string): boolean {
  if (!entryName || entryName === '.' || entryName === '..') {
    return true;
  }
  if (IGNORED_FILE_NAMES.has(entryName)) {
    return true;
  }
  if (IGNORED_DIR_NAMES.has(entryName)) {
    return true;
  }
  if (entryName.endsWith('.egg-info')) {
    return true;
  }
  return false;
}

function customRelativePosix(workspacePath: string, dirPath: string): string {
  return path.relative(workspacePath, dirPath).replace(/\\/g, '/');
}

function customSkillsPackageRoot(workspacePath: string, dirPath: string): boolean {
  return customRelativePosix(workspacePath, dirPath) === 'custom/skills';
}

function customSkillRoot(workspacePath: string, dirPath: string): boolean {
  return /^custom\/skills\/[^/]+$/.test(customRelativePosix(workspacePath, dirPath));
}

function underCustomAgentsOrEnvs(workspacePath: string, dirPath: string): boolean {
  return /^custom\/(agents|envs)(\/|$)/.test(customRelativePosix(workspacePath, dirPath));
}

function isAgentSkillDirectory(dirPath: string): boolean {
  return fs.existsSync(path.join(dirPath, 'SKILL.md'));
}

function shouldShowDirectoryInTree(parentDir: string, entryName: string, workspacePath: string): boolean {
  if (shouldHideFsEntry(entryName)) {
    return false;
  }
  const fullPath = path.join(parentDir, entryName);
  if (customSkillsPackageRoot(workspacePath, parentDir)) {
    const stat = safeStatSync(fullPath);
    return !!stat?.isDirectory() && isAgentSkillDirectory(fullPath);
  }
  if (customSkillRoot(workspacePath, parentDir)) {
    return CUSTOM_SKILL_CHILD_DIRS.has(entryName.toLowerCase());
  }
  if (underCustomAgentsOrEnvs(workspacePath, parentDir)) {
    if (CUSTOM_CODE_HIDDEN_DIRS.has(entryName.toLowerCase())) {
      return false;
    }
  }
  return true;
}

const TREE_OPEN_AS_DOCUMENT_EXTS = new Set([
  'c', 'cc', 'cpp', 'cxx', 'cs', 'css', 'cts', 'go', 'h', 'hpp', 'ini', 'java', 'js',
  'jsx', 'kt', 'less', 'log', 'mjs', 'mts', 'php', 'py', 'rb', 'rs', 'r', 'sass', 'scala',
  'scss', 'sh', 'sql', 'swift', 'toml', 'ts', 'tsx', 'txt', 'vue', 'svelte',
  'tex', 'bib', 'cls', 'bst',  // LaTeX document files
]);

function workspaceRelativePosix(workspaceRoot: string, absolutePath: string): string {
  const rel = path.relative(workspaceRoot, absolutePath);
  if (!rel || rel.startsWith('..')) {
    return absolutePath;
  }
  return rel.split(path.sep).join('/');
}

function workspaceRelativeTreeTooltip(workspaceRoot: string, absolutePath: string): string {
  const rel = workspaceRelativePosix(workspaceRoot, absolutePath);
  if (rel === absolutePath) {
    return rel;
  }
  return localize('projectStructure.treeItem.pathHint', rel);
}

function shouldShowFileByExt(fileName: string): boolean {
  const ext = path.extname(fileName).toLowerCase();
  if (!ext) {
    // 无扩展名文件默认不展示（除非在明确白名单里）
    return fileName === 'pid.json';
  }
  if (IGNORED_FILE_EXTS.has(ext)) {
    return false;
  }
  // 只展示常见可读/可视化的产物，避免把大二进制/缓存塞满树
  return [
    '.json',
    '.jsonl',
    '.pdf',
    '.yaml',
    '.yml',
    '.md',
    '.txt',
    '.py',
    '.csv',
    '.tsv',
    '.html',
    '.htm',
    '.png',
    '.jpg',
    '.jpeg',
    '.gif',
    '.webp',
    '.svg',
    '.log',
    '.db',
    '.sqlite',
    '.tex',
    '.bib',
    '.cls',
    '.bst',
    '.cfg',
    '.conf',
    '.toml',
  ].includes(ext);
}

/** Process / cache / generator files — hide from user-facing sidebar trees. */
function isSidebarNoiseFile(fileName: string): boolean {
  const lower = fileName.toLowerCase();
  const ext = path.extname(lower);
  if (['.py', '.pyc', '.pyo', '.log', '.sh', '.cls', '.bst', '.sty', '.aux', '.out', '.toc', '.fls', '.fdb_latexmk', '.synctex.gz'].includes(ext)) {
    return true;
  }
  if (['gen.log', 'gen.py', 'easypaper.log', 'metadata.json', 'pid.json', 'input-manifest.yaml', 'input-manifest.yml'].includes(lower)) {
    return true;
  }
  if (lower === 'pdf-intake') {
    return true;
  }
  if (/^pid_\d+\.json$/i.test(fileName)) {
    return true;
  }
  if (lower.endsWith('.egg-info') || lower === '__pycache__') {
    return true;
  }
  return false;
}

/** User-facing deliverables under presentation / synthesis / paper (no scripts/logs). */
function shouldShowUserFacingArtifact(fileName: string): boolean {
  if (shouldHideFsEntry(fileName) || isSidebarNoiseFile(fileName)) {
    return false;
  }
  const ext = path.extname(fileName).toLowerCase();
  return [
    '.json',
    '.jsonl',
    '.pdf',
    '.yaml',
    '.yml',
    '.md',
    '.txt',
    '.csv',
    '.tsv',
    '.html',
    '.htm',
    '.png',
    '.jpg',
    '.jpeg',
    '.gif',
    '.webp',
    '.svg',
    '.tex',
    '.bib',
  ].includes(ext);
}

const CUSTOM_CODE_SUBDIR = new Set(['agents', 'envs']);

function shouldShowFileInTreeListing(parentDir: string, fileName: string, workspacePath?: string): boolean {
  if (!shouldShowFileByExt(fileName)) {
    return false;
  }
  const isCustomCodeBoilerplate =
    CUSTOM_CODE_BOILERPLATE_FILES.has(fileName) ||
    (fileName.startsWith('__') && fileName.endsWith('.py'));
  if (
    isCustomCodeBoilerplate &&
    workspacePath &&
    (underCustomAgentsOrEnvs(workspacePath, parentDir) ||
      customSkillsPackageRoot(workspacePath, parentDir) ||
      customSkillRoot(workspacePath, parentDir))
  ) {
    return false;
  }
  if (workspacePath && customSkillsPackageRoot(workspacePath, parentDir)) {
    return false;
  }
  if (workspacePath && customSkillRoot(workspacePath, parentDir)) {
    const lower = fileName.toLowerCase();
    if (CUSTOM_SKILLS_PACKAGE_FILES.has(fileName)) {
      return false;
    }
    return lower === 'skill.md' || lower.endsWith('.md');
  }
  const norm = parentDir.replace(/\\/g, '/');
  const segs = norm.split('/').filter(Boolean);
  const iCustom = segs.lastIndexOf('custom');
  if (iCustom >= 0 && iCustom + 1 < segs.length) {
    const sub = segs[iCustom + 1].toLowerCase();
    if (CUSTOM_CODE_SUBDIR.has(sub)) {
      // Fallback when workspacePath is unavailable: still hide package scaffolding.
      if (isCustomCodeBoilerplate) {
        return false;
      }
      const ext = path.extname(fileName).toLowerCase();
      if (
        [
          '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp',
          '.csv', '.tsv', '.html', '.htm', '.pdf',
        ].includes(ext)
      ) {
        return false;
      }
      if (['.log', '.db', '.sqlite'].includes(ext)) {
        return false;
      }
      return ['.py', '.md', '.json', '.yaml', '.yml', '.toml', '.txt'].includes(ext);
    }
  }
  return true;
}

function safeStatSync(fsPath: string): fs.Stats | null {
  try {
    return fs.statSync(fsPath);
  } catch {
    return null;
  }
}

function listDirEntriesSafe(dirPath: string): string[] {
  try {
    return fs.readdirSync(dirPath);
  } catch {
    return [];
  }
}

const REPORT_IMAGE_EXT = /\.(png|jpe?g|gif|webp|svg)$/i;

function listReportImageFilenames(dirPath: string): Set<string> {
  if (!fs.existsSync(dirPath)) {
    return new Set();
  }
  const dirStat = safeStatSync(dirPath);
  if (!dirStat?.isDirectory()) {
    return new Set();
  }
  const names = new Set<string>();
  for (const entry of listDirEntriesSafe(dirPath)) {
    const full = path.join(dirPath, entry);
    const entStat = safeStatSync(full);
    if (entStat?.isFile() && REPORT_IMAGE_EXT.test(entry)) {
      names.add(entry.toLowerCase());
    }
  }
  return names;
}

function chartsDirHasNonImageEntries(chartsDir: string): boolean {
  if (!fs.existsSync(chartsDir)) {
    return false;
  }
  for (const entry of listDirEntriesSafe(chartsDir)) {
    if (shouldHideFsEntry(entry) || isSidebarNoiseFile(entry)) {
      continue;
    }
    const full = path.join(chartsDir, entry);
    const entStat = safeStatSync(full);
    if (!entStat) {
      continue;
    }
    if (entStat.isDirectory()) {
      return true;
    }
    if (entStat.isFile() && !REPORT_IMAGE_EXT.test(entry)) {
      return true;
    }
  }
  return false;
}

/** Hide charts/ when empty, or when assets/ already mirrors the same report images. */
function shouldShowChartsOutputDir(baseDir: string): boolean {
  const chartsDir = path.join(baseDir, 'charts');
  if (!fs.existsSync(chartsDir)) {
    return false;
  }
  const entries = listDirEntriesSafe(chartsDir).filter((e) => !shouldHideFsEntry(e));
  if (entries.length === 0) {
    return false;
  }
  if (chartsDirHasNonImageEntries(chartsDir)) {
    return true;
  }
  const chartImages = listReportImageFilenames(chartsDir);
  if (chartImages.size === 0) {
    return false;
  }
  const assetImages = listReportImageFilenames(path.join(baseDir, 'assets'));
  if (assetImages.size === 0) {
    return true;
  }
  for (const name of chartImages) {
    if (!assetImages.has(name)) {
      return true;
    }
  }
  return false;
}

function isUnderUserArtifactTree(dirPath: string): boolean {
  const normalized = dirPath.replace(/\\/g, '/');
  return (
    /\/presentation(\/|$)/i.test(normalized) ||
    /\/synthesis(\/|$)/i.test(normalized) ||
    /\/paper(\/|$)/i.test(normalized) ||
    /\/analysis(\/|$)/i.test(normalized)
  );
}

function isAnalysisChartsDirectory(dirPath: string): boolean {
  const normalized = path.normalize(dirPath);
  if (path.basename(normalized) !== 'charts') {
    return false;
  }
  const parentName = path.basename(path.dirname(normalized));
  if (parentName === 'synthesis') {
    return true;
  }
  if (/^hypothesis_\d+$/i.test(parentName)) {
    return path.basename(path.dirname(path.dirname(normalized))) === 'presentation';
  }
  if (!/^experiment_\d+$/i.test(parentName)) {
    return false;
  }
  const hypothesisDir = path.basename(path.dirname(path.dirname(normalized)));
  if (!/^hypothesis_\d+$/i.test(hypothesisDir)) {
    return false;
  }
  const presentationDir = path.basename(path.dirname(path.dirname(path.dirname(normalized))));
  return presentationDir === 'presentation';
}

function collectPresentationReportFiles(dirPath: string): Record<string, string> {
  const reportFiles: Record<string, string> = {};
  if (!fs.existsSync(dirPath)) {
    return reportFiles;
  }
  for (const entry of fs.readdirSync(dirPath)) {
    const fullPath = path.join(dirPath, entry);
    const stat = safeStatSync(fullPath);
    if (stat?.isFile()) {
      reportFiles[entry] = fullPath;
    }
  }
  return reportFiles;
}

type RequiredBilingualReportSpec = {
  fileName: string;
  labelKey: string;
  itemType: 'reportMd' | 'reportHtml';
  preview: boolean;
};

const REQUIRED_HYPOTHESIS_REPORTS: RequiredBilingualReportSpec[] = [
  { fileName: 'report_zh.md', labelKey: 'projectStructure.reportMdZh', itemType: 'reportMd', preview: true },
  { fileName: 'report_en.md', labelKey: 'projectStructure.reportMdEn', itemType: 'reportMd', preview: true },
  { fileName: 'report_zh.html', labelKey: 'projectStructure.reportHtmlZh', itemType: 'reportHtml', preview: false },
  { fileName: 'report_en.html', labelKey: 'projectStructure.reportHtmlEn', itemType: 'reportHtml', preview: false },
];

const REQUIRED_SYNTHESIS_REPORTS: RequiredBilingualReportSpec[] = [
  {
    fileName: 'synthesis_report_zh.md',
    labelKey: 'projectStructure.reportMdZh',
    itemType: 'reportMd',
    preview: true,
  },
  {
    fileName: 'synthesis_report_en.md',
    labelKey: 'projectStructure.reportMdEn',
    itemType: 'reportMd',
    preview: true,
  },
  {
    fileName: 'synthesis_report_zh.html',
    labelKey: 'projectStructure.reportHtmlZh',
    itemType: 'reportHtml',
    preview: false,
  },
  {
    fileName: 'synthesis_report_en.html',
    labelKey: 'projectStructure.reportHtmlEn',
    itemType: 'reportHtml',
    preview: false,
  },
];

function hypothesisReportsComplete(reportFiles: Record<string, string>): boolean {
  return REQUIRED_HYPOTHESIS_REPORTS.every((r) => Boolean(reportFiles[r.fileName]));
}

function presentationDirHasReports(dirPath: string): boolean {
  return hypothesisReportsComplete(collectPresentationReportFiles(dirPath));
}

function countHypothesisPresentationReports(hypothesisDir: string): number {
  const reportFiles = collectPresentationReportFiles(hypothesisDir);
  const present = REQUIRED_HYPOTHESIS_REPORTS.filter((r) => reportFiles[r.fileName]).length;
  return present;
}

function appendRequiredBilingualReportTreeItems(
  items: ProjectItem[],
  specs: RequiredBilingualReportSpec[],
  reportFiles: Record<string, string>,
  baseDir: string
): void {
  for (const spec of specs) {
    const fullPath = reportFiles[spec.fileName] || path.join(baseDir, spec.fileName);
    const exists = Boolean(reportFiles[spec.fileName]);
    const item = new ProjectItem(
      localize(spec.labelKey),
      vscode.TreeItemCollapsibleState.None,
      spec.itemType,
      exists ? fullPath : undefined
    );
    if (!exists) {
      item.description = localize('projectStructure.reportRequiredMissing');
      item.iconPath = makeThemeIcon('warning', 'problemsWarningIcon.foreground');
    } else if (spec.preview) {
      item.command = {
        command: 'markdown.showPreview',
        title: 'Open Preview',
        arguments: [vscode.Uri.file(fullPath)]
      };
    } else if (spec.itemType === 'reportHtml') {
      item.command = {
        command: 'aiSocialScientist.openHtmlReport',
        title: 'Open HTML Report',
        arguments: [vscode.Uri.file(fullPath)]
      };
    }
    items.push(item);
  }
}

function appendPresentationReportTreeItems(
  items: ProjectItem[],
  reportFiles: Record<string, string>,
  baseDir: string
): void {
  appendRequiredBilingualReportTreeItems(
    items,
    REQUIRED_HYPOTHESIS_REPORTS,
    reportFiles,
    baseDir
  );
}

function collectSynthesisReportFiles(synthesisDir: string): Record<string, string> {
  return collectPresentationReportFiles(synthesisDir);
}

function countSynthesisReports(synthesisDir: string): number {
  const reportFiles = collectSynthesisReportFiles(synthesisDir);
  const present = REQUIRED_SYNTHESIS_REPORTS.filter((r) => reportFiles[r.fileName]).length;
  return present;
}

const HYPOTHESIS_PHASE_ORDER = ['frame', 'explore', 'claims', 'refine', 'produce'] as const;

const ANALYSIS_PHASE_LABEL_KEYS: Record<(typeof HYPOTHESIS_PHASE_ORDER)[number], string> = {
  frame: 'projectStructure.analysisPhase.frame',
  explore: 'projectStructure.analysisPhase.explore',
  claims: 'projectStructure.analysisPhase.claims',
  refine: 'projectStructure.analysisPhase.refine',
  produce: 'projectStructure.analysisPhase.produce',
};

function resolveHypothesisHarnessStatePath(
  workspacePath: string,
  hypothesisDir: string
): string | undefined {
  const match = path.basename(hypothesisDir).match(/^hypothesis_(\d+)$/i);
  if (!match) {
    return undefined;
  }
  const canonical = path.join(
    workspacePath,
    '.agentsociety',
    'analysis',
    `hypothesis_${match[1]}`,
    'state.yaml'
  );
  if (fs.existsSync(canonical)) {
    return canonical;
  }
  const legacy = path.join(hypothesisDir, 'analysis', 'state.yaml');
  if (fs.existsSync(legacy)) {
    return legacy;
  }
  return undefined;
}

function resolveSynthesisHarnessStatePath(workspacePath: string): string | undefined {
  const canonical = path.join(
    workspacePath,
    '.agentsociety',
    'analysis',
    'synthesis',
    'state.yaml'
  );
  if (fs.existsSync(canonical)) {
    return canonical;
  }
  const legacy = path.join(workspacePath, 'synthesis', 'analysis', 'state.yaml');
  if (fs.existsSync(legacy)) {
    return legacy;
  }
  return undefined;
}

function readHarnessStateFile(statePath: string): Record<string, unknown> | undefined {
  try {
    const raw = yaml.load(fs.readFileSync(statePath, 'utf8'));
    return raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}

type PhaseCheckpointView = {
  structural_pass?: boolean;
  attestation_pass?: boolean;
  gate_pass?: boolean;
};

function resolvePhaseStepKind(
  phase: string,
  currentPhase: string,
  checkpoint: PhaseCheckpointView
): 'pass' | 'current' | 'attestation' | 'blocked' | 'pending' {
  if (checkpoint.gate_pass) {
    return 'pass';
  }
  const cur = HYPOTHESIS_PHASE_ORDER.indexOf(currentPhase as (typeof HYPOTHESIS_PHASE_ORDER)[number]);
  const idx = HYPOTHESIS_PHASE_ORDER.indexOf(phase as (typeof HYPOTHESIS_PHASE_ORDER)[number]);
  if (phase === currentPhase) {
    if (checkpoint.structural_pass && !checkpoint.attestation_pass) {
      return 'attestation';
    }
    return 'current';
  }
  if (idx >= 0 && cur >= 0 && idx < cur) {
    return 'blocked';
  }
  return 'pending';
}

function phaseStepStatusLabel(
  phase: string,
  currentPhase: string,
  checkpoints: Record<string, PhaseCheckpointView>
): string {
  const kind = resolvePhaseStepKind(phase, currentPhase, checkpoints[phase] || {});
  switch (kind) {
    case 'pass':
      return localize('projectStructure.phaseStatus.pass');
    case 'current':
      return localize('projectStructure.phaseStatus.current');
    case 'attestation':
      return localize('projectStructure.phaseStatus.attestationPending');
    case 'blocked':
      return localize('projectStructure.phaseStatus.blocked');
    default:
      return localize('projectStructure.phaseStatus.pending');
  }
}

function assignHarnessStatusCommand(
  item: ProjectItem,
  statePath: string,
  scope: 'hypothesis' | 'synthesis',
  focusPhase?: string
): void {
  item.command = {
    command: 'aiSocialScientist.viewAnalysisHarnessStatus',
    title: localize('extension.viewAnalysisHarness.commandTitle'),
    arguments: [{ statePath, scope, focusPhase }],
  };
}

function phaseStepIcon(kind: ReturnType<typeof resolvePhaseStepKind>): vscode.ThemeIcon {
  switch (kind) {
    case 'pass':
      return new vscode.ThemeIcon('pass-filled', new vscode.ThemeColor('charts.green'));
    case 'attestation':
      return new vscode.ThemeIcon('checklist', new vscode.ThemeColor('charts.yellow'));
    case 'current':
      return new vscode.ThemeIcon('circle-outline', new vscode.ThemeColor('charts.yellow'));
    case 'blocked':
      return new vscode.ThemeIcon('warning', new vscode.ThemeColor('charts.red'));
    default:
      return new vscode.ThemeIcon('circle-large-outline');
  }
}

function appendHypothesisPhaseProgress(
  items: ProjectItem[],
  workspacePath: string,
  hypothesisDir: string
): void {
  const statePath = resolveHypothesisHarnessStatePath(workspacePath, hypothesisDir);
  if (!statePath) {
    return;
  }
  const state = readHarnessStateFile(statePath);
  if (!state) {
    return;
  }
  const currentPhase = String(state.current_phase || 'frame');
  const checkpoints = (state.phase_checkpoints || {}) as Record<string, PhaseCheckpointView>;
  const passed = HYPOTHESIS_PHASE_ORDER.filter((p) => checkpoints[p]?.gate_pass).length;
  const group = new ProjectItem(
    localize('projectStructure.analysisProgress'),
    vscode.TreeItemCollapsibleState.Collapsed,
    'analysisPhaseGroup',
    statePath
  );
  group.iconPath = makeThemeIcon('list-tree', 'charts.green');
  const phaseKey = ANALYSIS_PHASE_LABEL_KEYS[currentPhase as keyof typeof ANALYSIS_PHASE_LABEL_KEYS];
  const currentLabel = phaseKey ? localize(phaseKey) : currentPhase;
  group.description = `${passed}/${HYPOTHESIS_PHASE_ORDER.length} · ${currentLabel}`;
  group.tooltip = localize('projectStructure.analysisProgressTooltip');
  items.push(group);
}

function buildHypothesisPhaseStepItems(statePath: string): ProjectItem[] {
  const state = readHarnessStateFile(statePath);
  if (!state) {
    return [];
  }
  const currentPhase = String(state.current_phase || 'frame');
  const checkpoints = (state.phase_checkpoints || {}) as Record<string, PhaseCheckpointView>;
  return HYPOTHESIS_PHASE_ORDER.map((phase) => {
    const label = localize(ANALYSIS_PHASE_LABEL_KEYS[phase]);
    const kind = resolvePhaseStepKind(phase, currentPhase, checkpoints[phase] || {});
    const item = new ProjectItem(
      label,
      vscode.TreeItemCollapsibleState.None,
      'analysisPhaseStep'
    );
    item.description = phaseStepStatusLabel(phase, currentPhase, checkpoints);
    item.iconPath = phaseStepIcon(kind);
    item.tooltip = `${label} — ${item.description}`;
    assignHarnessStatusCommand(item, statePath, 'hypothesis', phase);
    return item;
  });
}

function appendAnalysisOutputDirs(
  items: ProjectItem[],
  baseDir: string,
  options?: { includeData?: boolean }
): void {
  if (options?.includeData !== false) {
    const dataDir = path.join(baseDir, 'data');
    if (fs.existsSync(dataDir)) {
      const dataItem = new ProjectItem(
        localize('projectStructure.analysisData'),
        vscode.TreeItemCollapsibleState.Collapsed,
        'file',
        dataDir
      );
      dataItem.iconPath = makeThemeIcon('database', 'descriptionForeground');
      dataItem.resourceUri = undefined;
      items.push(dataItem);
    }
  }

  if (shouldShowChartsOutputDir(baseDir)) {
    const chartsDir = path.join(baseDir, 'charts');
    const chartsItem = new ProjectItem(
      localize('projectStructure.reportCharts'),
      vscode.TreeItemCollapsibleState.Collapsed,
      'file',
      chartsDir
    );
    chartsItem.tooltip = localize('projectStructure.reportChartsTooltip');
    chartsItem.iconPath = makeThemeIcon('graph-line', 'charts.blue');
    chartsItem.resourceUri = undefined;
    items.push(chartsItem);
  }

  const assetsDir = path.join(baseDir, 'assets');
  if (fs.existsSync(assetsDir)) {
    const assetsItem = new ProjectItem(
      localize('projectStructure.reportAssets'),
      vscode.TreeItemCollapsibleState.Collapsed,
      'file',
      assetsDir
    );
    assetsItem.tooltip = localize('projectStructure.reportAssetsTooltip');
    assetsItem.iconPath = makeThemeIcon('file-media', 'charts.yellow');
    assetsItem.resourceUri = undefined;
    items.push(assetsItem);
  }
}

function appendPresentationOutputDirs(items: ProjectItem[], baseDir: string): void {
  // data/ and harness metadata (artifact_manifest / report_outline) stay on disk
  // but are omitted from the default sidebar — users open reports + assets.
  appendAnalysisOutputDirs(items, baseDir, { includeData: false });
}

function appendSynthesisOutputDirs(items: ProjectItem[], synthesisDir: string): void {
  appendAnalysisOutputDirs(items, synthesisDir, { includeData: false });
}

function presentationChartsEntryRank(entryName: string, isDir: boolean): number {
  if (isDir) {
    return 0;
  }
  const ext = path.extname(entryName).toLowerCase();
  if (['.png', '.svg', '.jpg', '.jpeg', '.gif', '.webp'].includes(ext)) {
    return 1;
  }
  if (ext === '.csv' || ext === '.tsv') {
    return 2;
  }
  if (ext === '.json') {
    return 3;
  }
  return 4;
}

function comparePresentationChartsEntries(a: string, b: string, parentDir: string): number {
  const pathA = path.join(parentDir, a);
  const pathB = path.join(parentDir, b);
  const statA = safeStatSync(pathA);
  const statB = safeStatSync(pathB);
  if (!statA || !statB) {
    return a.localeCompare(b);
  }
  const rankDiff =
    presentationChartsEntryRank(a, statA.isDirectory()) -
    presentationChartsEntryRank(b, statB.isDirectory());
  if (rankDiff !== 0) {
    return rankDiff;
  }
  return a.localeCompare(b);
}

function shouldShowFileInPresentationCharts(fileName: string): boolean {
  return shouldShowUserFacingArtifact(fileName);
}

function getPresentationChartsFileDescription(fileName: string): string | undefined {
  const ext = path.extname(fileName).toLowerCase();
  if (['.png', '.svg', '.jpg', '.jpeg', '.gif', '.webp'].includes(ext)) {
    return localize('projectStructure.chartsCategory.image');
  }
  if (ext === '.csv' || ext === '.tsv') {
    return localize('projectStructure.chartsCategory.table');
  }
  if (ext === '.json') {
    return localize('projectStructure.chartsCategory.meta');
  }
  return undefined;
}

/**
 * ProjectItem - 项目树视图中的单个节点
 * 
 * 继承自 vscode.TreeItem，这是VSCode树形视图的基础类。
 * 每个节点可以显示标签、图标，并且可以展开/折叠。
 */
export class ProjectItem extends vscode.TreeItem {
  // Additional properties for experiment context
  public hypothesisId?: string;
  public experimentId?: string;
  /** 实验目录绝对路径；无 EXPERIMENT.md 时 filePath 为空，子节点必须依赖此字段 */
  public experimentRoot?: string;
  // Custom module properties
  public isCustom?: boolean;
  public moduleType?: string;
  public className?: string;

  /**
   * 构造函数
   * @param label - 节点显示的文本标签
   * @param collapsibleState - 节点的折叠状态：
   *   - Collapsed: 可以展开（有子节点）
   *   - Expanded: 已展开
   *   - None: 没有子节点，不能展开
   * @param type - 节点类型，用于区分不同类型的项目项（用于上下文菜单等）
   * @param filePath - 可选的文件路径，如果提供，点击节点会打开该文件
   */
  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly type: 'initWorkspace' | 'configureEnv' | 'fixWorkspace' | 'aiChat' | 'topic' | 'hypothesis' | 'experiment' | 'paper' | 'file' | 'papers' | 'userdata' | 'prefillParams' | 'prefillParamsGroup' | 'prefillParamsEnv' | 'prefillParamsAgent' | 'settings' | 'custom' | 'customScan' | 'customTest' | 'customClean' | 'customAgentItem' | 'customEnvItem' | 'customAgentsGroup' | 'customEnvsGroup' | 'customWorkspace' | 'presentation' | 'presentationHypothesis' | 'presentationExperiment' | 'synthesis' | 'analysisPhaseGroup' | 'analysisPhaseStep' | 'synthesisPhaseGroup' | 'reportHtml' | 'reportMd' | 'skillManagement' | 'datasets' | 'datasetItem' | 'paperPdfGroup' | 'paperMdGroup' | 'paperJsonGroup' | 'pidJson' | 'experimentInitGroup' | 'experimentRunGroup' | 'projectStats' | 'projectStatsMetric' | 'paperWorkspace' | 'paperSections' | 'paperFigures' | 'paperFigureSpecs' | 'paperTables' | 'paperTableSpecs' | 'paperCompileRuns' | 'paperCompileRun' | 'paperReviews' | 'paperReviewRound' | 'paperReviewer' | 'paperLit' | 'paperArtifact' | 'analysisWorkspace' | 'analysisHypothesis' | 'analysisExperiment' | 'analysisEda',
    public readonly filePath?: string
  ) {
    // 调用父类构造函数，初始化树节点
    super(label, collapsibleState);

    // tooltip: 鼠标悬停时显示的提示信息
    this.tooltip = filePath || label;

    // 获取文件扩展名（用于图标和命令设置；path.extname 对 a.b.md 等更可靠）
    const ext = filePath
      ? path.extname(filePath).replace(/^\./, '').toLowerCase()
      : '';

    // 检查是否为 markdown 文件（用于后续的 contextValue 和命令设置）
    const isMarkdown = ext === 'md';

    // 检查是否为 JSON 文件
    const isJson = ext === 'json';

    // 检查是否为 YAML 文件
    const isYaml = ext === 'yaml' || ext === 'yml';

    let isDirectoryPath = false;
    if (filePath) {
      try {
        isDirectoryPath = fs.existsSync(filePath) && fs.statSync(filePath).isDirectory();
      } catch {
        isDirectoryPath = false;
      }
    }

    const underPapers =
      !!filePath && filePath.replace(/\\/g, '/').toLowerCase().includes('/papers/');

    if (type === 'paperReviewRound' || type === 'paperReviewer') {
      this.contextValue = type;
    } else if (type === 'papers') {
      this.contextValue = 'papers literatureRoot';
    } else if (type === 'paper' && filePath && underPapers) {
      if (isDirectoryPath) {
        this.contextValue = 'paperFolder';
      } else if (path.basename(filePath).toLowerCase() === 'literature_index.json') {
        this.contextValue = 'literatureFile literatureIndex json';
      } else if (path.basename(filePath).toLowerCase() === 'library.bib') {
        this.contextValue = 'literatureFile literatureBib';
      } else if (isMarkdown) {
        this.contextValue = 'literatureFile markdown';
      } else if (isJson) {
        this.contextValue = 'literatureFile json';
      } else {
        this.contextValue = 'literatureFile';
      }
    } else if (isMarkdown) {
      this.contextValue = `${type} markdown`;
    } else if (isJson) {
      this.contextValue = `${type} json`;
    } else if (isYaml) {
      this.contextValue = `${type} yaml`;
    } else if (ext === 'pdf') {
      this.contextValue = `${type} pdf`;
    } else if (ext === 'html' || ext === 'htm') {
      this.contextValue = `${type} html`;
    } else if (ext === 'tex' || ext === 'bib') {
      this.contextValue = `${type} tex`;
    } else {
      this.contextValue = type;
    }

    if (filePath && !isDirectoryPath && (ext === 'csv' || ext === 'tsv')) {
      this.contextValue = `${this.contextValue} tabular`.trim();
    }

    // 根据节点类型设置不同的图标
    // ThemeIcon是VSCode内置的图标系统，使用Codicons图标库
    const iconMap: { [key: string]: string } = {
      'initWorkspace': 'add',      // 加号图标，初始化工作区
      'configureEnv': 'gear',      // 齿轮图标，配置环境变量
      'fixWorkspace': 'tools',     // 工具图标，修复工作区
      'aiChat': 'comment-discussion',  // 聊天气泡图标，AI Chat
      'topic': 'book',           // 书籍图标，表示研究话题
      'hypothesis': 'lightbulb',  // 灯泡图标，表示假设
      'experiment': 'beaker',     // 烧杯图标，表示实验
      'papers': 'library', // 文献库
      'userdata': 'database', // 用户数据（持久化存储）
      'datasets': 'table', // 数据集（与用户数据的 database 区分）
      'datasetItem': 'folder', // 单个数据集目录
      'prefillParams': 'settings', // 设置图标，表示预填充参数
      'prefillParamsGroup': 'server-environment', // 环境与智能体：运行环境/工作负荷
      'prefillParamsEnv': 'symbol-namespace', // 命名空间图标，表示环境模块预置参数
      'prefillParamsAgent': 'symbol-interface', // 接口图标，表示智能体类预置参数
      'settings': 'gear', // 齿轮设置图标，表示配置设置
      'custom': 'extensions', // 自定义模块 / 插件扩展
      'customWorkspace': 'library', // custom/ 根：研究扩展资产
      'customScan': 'search', // 搜索图标，扫描
      'customTest': 'debug-start', // 播放图标，测试
      'customAgentItem': 'hubot',
      'customEnvItem': 'server-environment',
      'customAgentsGroup': 'folder', // Agents组图标
      'customEnvsGroup': 'folder', // Envs组图标
      'presentation': 'graph-line', // 分析报告（图表/结果展示）
      'presentationHypothesis': 'folder', // 假设文件夹
      'presentationExperiment': 'folder', // 实验文件夹
      'analysisPhaseGroup': 'list-tree',
      'analysisPhaseStep': 'circle-filled',
      'synthesisPhaseGroup': 'list-tree',
      'synthesis': 'notebook', // 综合报告（汇总文档）
      'reportHtml': 'file-code', // HTML 报告图标
      'reportMd': 'file-text', // Markdown 报告图标
      'skillManagement': 'extensions', // 技能管理（打开面板）
      'paperPdfGroup': 'file-pdf',
      'paperMdGroup': 'markdown',
      'paperJsonGroup': 'list-tree',
      'pidJson': 'info', // 进程状态图标
      'experimentInitGroup': 'settings-gear', // 实验配置文件组
      'experimentRunGroup': 'graph-line', // 实验运行结果组
      'projectStats': 'graph', // 项目统计概览
      'projectStatsMetric': 'primitive-dot', // 拆行展示的统计子行
      'paperWorkspace': 'file-text',
      'paperSections': 'symbol-file',
      'paperFigures': 'file-media',
      'paperFigureSpecs': 'symbol-file',
      'paperTables': 'table',
      'paperTableSpecs': 'symbol-file',
      'paperCompileRuns': 'output',
      'paperCompileRun': 'file-pdf',
      'paperReviews': 'feedback',
      'paperReviewRound': 'comment-discussion',
      'paperReviewer': 'person',
      'paperLit': 'search',
      'paperArtifact': 'file',
      'analysisWorkspace': 'beaker',
      'analysisHypothesis': 'lightbulb',
      'analysisExperiment': 'flame',
      'analysisEda': 'graph',
    };

    // 对于 paper 和 file 类型，根据文件扩展名设置图标
    let iconId: string;
    if ((type === 'paper' || type === 'file') && isDirectoryPath) {
      // 目录节点应始终显示为文件夹，避免误显示为白色文件图标
      iconId = 'folder';
    } else if (type === 'paper' || type === 'file') {
      // 根据文件扩展名设置图标
      const fileIconMap: { [key: string]: string } = {
        'pdf': 'file-pdf',
        'md': 'markdown',
        'json': 'json',
        'py': 'python',
        'yaml': 'code',
        'yml': 'code',
        'html': 'browser',
        'csv': 'table',
        'txt': 'file-text',
        'db': 'database',
        'sqlite': 'database',
        'log': 'output',
        'png': 'file-media',
        'jpg': 'file-media',
        'jpeg': 'file-media',
        'gif': 'file-media',
      };
      iconId = (ext && fileIconMap[ext]) || 'file-text';
    } else {
      iconId = iconMap[type] || 'file';
    }

    // ThemeIcon的构造函数在类型定义中是私有的，但运行时可用
    // 使用类型断言绕过TypeScript的类型检查
    this.iconPath = new (vscode.ThemeIcon as any)(iconId);

    // 关键节点使用语义化颜色，提升树视图可读性
    if (type === 'skillManagement') {
      this.iconPath = makeThemeIcon('extensions', 'charts.blue');
    } else if (type === 'experiment') {
      this.iconPath = makeThemeIcon('beaker', 'charts.blue');
    } else if (type === 'projectStats') {
      this.iconPath = makeThemeIcon('graph', 'charts.blue');
    } else if (type === 'projectStatsMetric') {
      this.iconPath = makeThemeIcon('primitive-dot', 'descriptionForeground');
    } else if (type === 'prefillParamsGroup') {
      this.iconPath = makeThemeIcon('server-environment', 'charts.blue');
    } else if (type === 'customWorkspace') {
      this.iconPath = makeThemeIcon('library', 'charts.purple');
    } else if (type === 'customAgentItem') {
      this.iconPath = makeThemeIcon('hubot', 'charts.blue');
    } else if (type === 'customEnvItem') {
      this.iconPath = makeThemeIcon('server-environment', 'charts.orange');
    } else if (type === 'paperPdfGroup') {
      this.iconPath = makeThemeIcon('file-pdf', 'charts.red');
    } else if (type === 'paperJsonGroup') {
      this.iconPath = makeThemeIcon('list-tree', 'charts.blue');
    }

    // For paper/file/paperArtifact types, use themed file icons based on extension.
    // BUT: only set resourceUri (which overrides command) for binary/media files that
    // don't have custom viewers. For text-based files with custom viewers, we set
    // the command explicitly below.
    const isPaperArtifactType = type === 'paper' || type === 'file' || type === 'paperArtifact';
    const useThemedIcon =
      filePath &&
      fs.existsSync(filePath) &&
      (isPaperArtifactType ||
        ((type === 'reportHtml' || type === 'reportMd') && !isDirectoryPath));

    // Only set resourceUri for binary/media files — VSCode opens these natively.
    // PDF uses explicit vscode.open so it opens in the editor preview pane.
    const mediaExts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'];
    const useResourceUri =
      useThemedIcon &&
      mediaExts.includes(ext) &&
      type !== 'reportHtml' &&
      type !== 'reportMd';

    if (useResourceUri) {
      this.resourceUri = vscode.Uri.file(filePath);
      this.iconPath = undefined;
    }

    // 如果提供了文件路径，设置点击命令
    // 当用户点击这个节点时，会执行相应的命令打开文件
    // 注意：可展开的目录节点不应设置 command，否则点击会执行命令而非展开
    const isHarnessStatusNode =
      type === 'analysisPhaseStep' ||
      type === 'analysisPhaseGroup' ||
      type === 'synthesisPhaseGroup';

    if (type === 'paperReviewRound' || type === 'paperReviewer') {
      this.command = {
        command: 'aiSocialScientist.viewPaperReview',
        title: localize('extension.viewPaperReview.commandTitle'),
        arguments: [filePath]
      };
    } else if (filePath && collapsibleState === vscode.TreeItemCollapsibleState.None && !isHarnessStatusNode && !useResourceUri) {
      if (type === 'reportHtml' || (ext === 'html' && (type === 'presentationExperiment' || type === 'synthesis'))) {
        this.command = {
          command: 'aiSocialScientist.openHtmlReport',
          title: 'Open HTML Report',
          arguments: [vscode.Uri.file(filePath)]
        };
      } else if (type === 'reportMd' && isMarkdown) {
        // Markdown 报告默认以预览模式打开
        this.command = {
          command: 'markdown.showPreview',
          title: '打开预览',
          arguments: [vscode.Uri.file(filePath)]
        };
      } else if (isMarkdown) {
        // Markdown 文件默认以预览模式打开
        this.command = {
          command: 'markdown.showPreview',  // VSCode内置命令：预览 Markdown 文件
          title: '打开预览',
          arguments: [vscode.Uri.file(filePath)]  // 传递文件URI作为参数
        };
      } else if (isJson) {
        // JSON 文件：检查是否有专门的自定义编辑器
        const fileName = path.basename(filePath);
        const parentDir = path.basename(path.dirname(filePath));
        const hasCustomEditor =
          fileName === 'SIM_SETTINGS.json' ||
          (fileName === 'init_config.json' && parentDir === 'init');

        if (hasCustomEditor) {
          // 有自定义编辑器的配置文件：让 VSCode 自动选择对应插件编辑器。
          this.command = {
            command: 'vscode.open',
            title: '打开文件',
            arguments: [vscode.Uri.file(filePath)]
          };
        } else {
          // 其他 JSON 文件（含 paper/analysis）：使用通用可视化查看器
          this.command = {
            command: 'aiSocialScientist.viewJsonFile',
            title: '查看 JSON',
            arguments: [filePath]
          };
        }
      } else if (isYaml) {
        // YAML 文件：使用通用可视化查看器
        this.command = {
          command: 'aiSocialScientist.viewYamlFile',
          title: '查看 YAML',
          arguments: [filePath]
        };
      } else if (ext === 'csv' || ext === 'tsv') {
        this.command = {
          command: 'aiSocialScientist.viewCsvFile',
          title: localize('extension.viewCsv.commandTitle'),
          arguments: [filePath]
        };
      } else if ([
        'pdf',
        'png',
        'jpg',
        'jpeg',
        'gif',
        'webp',
        'svg'
      ].includes(ext)) {
        if (ext === 'pdf') {
          this.command = {
            command: 'aiSocialScientist.openPdfPreview',
            title: localize('extension.openAsset.commandTitle'),
            arguments: [filePath]
          };
        } else {
          this.command = {
            command: 'vscode.open',
            title: localize('extension.openAsset.commandTitle'),
            arguments: [vscode.Uri.file(filePath)]
          };
        }
      } else if (ext && TREE_OPEN_AS_DOCUMENT_EXTS.has(ext)) {
        this.command = {
          command: 'vscode.open',
          title: localize('extension.openDocument.commandTitle'),
          arguments: [vscode.Uri.file(filePath)]
        };
      } else {
        this.command = {
          command: 'aiSocialScientist.copyFilePath',
          title: localize('extension.copyPath.commandTitle'),
          arguments: [{ filePath }]
        };
      }
    } else if (type === 'prefillParamsGroup') {
      // 环境与智能体节点：点击时打开统一的管理界面
      this.command = {
        command: 'agentsociety.viewPrefillParams',
        title: localize('prefillParams.title'),
      };
    } else if (type === 'settings') {
      // 配置设置节点：点击时打开配置页（而非 VS Code 设置）
      this.command = {
        command: 'aiSocialScientist.openConfigPage',
        title: localize('projectStructure.settings')
      };
    }
  }
}

function makeThemeIcon(id: string, colorId?: string): vscode.ThemeIcon {
  if (!colorId) {
    return new (vscode.ThemeIcon as any)(id);
  }
  return new (vscode.ThemeIcon as any)(id, new vscode.ThemeColor(colorId));
}

function getCustomWorkspaceDirIcon(dirName: string): vscode.ThemeIcon | undefined {
  const normalized = dirName.trim().toLowerCase();
  if (normalized === 'agents') {
    return makeThemeIcon('hubot', 'charts.blue');
  }
  if (normalized === 'envs') {
    return makeThemeIcon('server-environment', 'charts.orange');
  }
  if (normalized === 'skills') {
    return makeThemeIcon('wand', 'charts.green');
  }
  return undefined;
}

/**
 * ProjectStructureProvider - 项目结构数据提供者
 * 
 * 实现 TreeDataProvider<ProjectItem> 接口，这是VSCode树形视图的核心。
 * 
 * 主要职责：
 * 1. 提供树形视图的数据（通过getChildren方法）
 * 2. 响应文件系统变化，自动刷新视图
 * 3. 管理文件监听器和资源清理
 */
export class ProjectStructureProvider implements vscode.TreeDataProvider<ProjectItem> {
  /**
   * _onDidChangeTreeData - 事件发射器
   * 
   * EventEmitter是VSCode事件系统的核心。
   * 当数据发生变化时，通过fire()方法发射事件，视图会自动刷新。
   * 
   * 类型说明：
   * - ProjectItem | undefined | null: 可以传递特定的节点来刷新，或undefined/null刷新整个树
   */
  private _onDidChangeTreeData: vscode.EventEmitter<ProjectItem | undefined | null> = new vscode.EventEmitter<ProjectItem | undefined | null>();

  /**
   * onDidChangeTreeData - 公开的事件属性
   * 
   * VSCode通过这个属性订阅数据变化事件。
   * 当_onDidChangeTreeData.fire()被调用时，VSCode会自动调用getChildren()重新获取数据。
   */
  readonly onDidChangeTreeData: vscode.Event<ProjectItem | undefined | null> = this._onDidChangeTreeData.event;

  // 文件系统监听器 - 监听工作区文件的变化（多个 pattern）
  private watchers: vscode.FileSystemWatcher[] = [];

  // 当前工作区的路径
  private workspacePath: string = '';

  // 批量操作标志 - 在批量文件操作期间暂停自动刷新
  private batchOperationInProgress: boolean = false;

  // 防抖定时器 - 用于限制刷新频率
  private refreshTimer: NodeJS.Timeout | undefined;

  // 防抖延迟时间（毫秒）- 文件监听触发的刷新合并窗口
  private readonly DEBOUNCE_DELAY = 800;

  // 输出通道 - 用于显示调试日志
  // 用户可以在"输出"面板中查看这些日志
  private outputChannel: vscode.OutputChannel;

  // 自定义模块缓存 - 存储扫描结果
  private customModulesCache: {
    agents: Array<{ type: string; class_name: string; description: string; file_path: string }>;
    envs: Array<{ type: string; class_name: string; description: string; file_path: string }>;
  } = { agents: [], envs: [] };

  // 树结构缓存 - 缓存节点的子项，避免重复的文件系统扫描
  private treeItemCache: Map<string, { items: ProjectItem[]; timestamp: number }> = new Map();

  // 缓存过期时间（5秒）
  private readonly CACHE_TTL = 5000;

  // Workspace Manager - 本地文件操作
  private workspaceManager: WorkspaceManager;

  private treeView: vscode.TreeView<ProjectItem> | undefined;
  private autoFixInProgress = false;

  /**
   * 构造函数
   * @param context - ExtensionContext，VSCode扩展的上下文对象
   * @param apiClient - ApiClient，与后端通信的客户端
   * 
   * ExtensionContext包含：
   * - subscriptions: 用于注册需要清理的资源（监听器、命令等）
   * - extensionPath: 扩展的安装路径
   * - workspaceState/globalState: 存储扩展的状态数据
   */
  constructor(private context: vscode.ExtensionContext, private apiClient: ApiClient) {
    // 创建输出通道，用于显示调试日志
    // 用户可以在VSCode的"输出"面板中选择"AI Social Scientist"查看日志
    this.outputChannel = getMainOutputChannel();
    this.workspaceManager = new WorkspaceManager(context);
    this.log('ProjectStructureProvider initialized');

    // 设置文件系统监听器
    this.setupFileWatchers();

    // 监听工作区文件夹的变化
    // 当用户添加/删除工作区文件夹时，需要重新设置监听器
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      this.log('Workspace folders changed, reinitializing watchers');
      this.disposeWatcher();  // 清理旧的监听器
      this.setupFileWatchers();  // 重新设置监听器
      this.refresh();  // 刷新视图
    });
  }

  attachTreeView(treeView: vscode.TreeView<ProjectItem>): void {
    this.treeView = treeView;
  }

  private setTreeMessage(message: string | undefined): void {
    if (this.treeView) {
      this.treeView.message = message;
    }
  }

  /**
   * 日志记录方法
   * 
   * 将日志同时输出到：
   * 1. 控制台（console.log）- 开发时在调试控制台查看
   * 2. 输出通道（OutputChannel）- 用户可以在VSCode的输出面板查看
   * 
   * @param message - 日志消息
   * @param args - 额外的参数（会被JSON序列化）
   */
  private log(message: string, ...args: any[]): void {
    const timestamp = new Date().toISOString();
    const logMessage = `[${timestamp}] [ProjectStructureProvider] ${message}`;

    // 输出到控制台（开发调试用）
    console.log(logMessage, ...args);

    // 输出到VSCode的输出面板（用户可见）
    this.outputChannel.appendLine(logMessage + (args.length > 0 ? ` ${JSON.stringify(args)}` : ''));
  }

  /**
   * 设置文件系统监听器
   * 
   * FileSystemWatcher可以监听文件系统的变化：
   * - onDidChange: 文件被修改
   * - onDidCreate: 文件被创建
   * - onDidDelete: 文件被删除
   * 
   * 使用RelativePattern可以指定监听的范围
   * 监听模式使用双星号加斜杠加星号表示递归匹配所有文件
   */
  private setupFileWatchers(): void {
    // 获取当前打开的第一个工作区文件夹
    // workspaceFolders是一个数组，支持多根工作区
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this.log('No workspace folder found, skipping file watcher setup');
      return;
    }

    // 保存工作区路径，后续会用到
    this.workspacePath = workspaceFolder.uri.fsPath;
    this.log(`Setting up file watcher for workspace: ${this.workspacePath}`);

    // 为避免大仓库下 `**/*` 监听带来的事件风暴，只监听本扩展核心工作区结构
    const patterns: string[] = [
      '.env',
      'TOPIC.md',
      'papers/**',
      'hypothesis_*/**',
      'custom/**',
      'presentation/**',
      'synthesis/**',
      'paper/**',
      'analysis/**',
      '.agentsociety/**',
      '.claude/skills/**',
    ];

    // 创建辅助函数：检查路径是否应该被忽略
    // 优化：使用更高效的路径匹配，提前检查常见情况
    const shouldIgnorePath = (filePath: string): boolean => {
      // 快速路径：检查路径中是否包含常见忽略目录
      const quickIgnorePatterns = [
        'node_modules',
        '.git',
        '__pycache__',
        '.venv',
        'venv',
        'virtualenv',
        '.pytest_cache',
        '.mypy_cache',
        '.ipynb_checkpoints',
        'dist',
        'out',
        'build',
        'agentsociety_data',
        'logs',
        'mineru_output',
      ];
      for (const pattern of quickIgnorePatterns) {
        if (filePath.includes(`/${pattern}/`) || filePath.includes(`\\${pattern}\\`)) {
          return true;
        }
      }

      // 文件扩展名快速检查
      const ext = filePath.toLowerCase();
      // 注意：实验 run/output.log 很常见，不能一概忽略；后续会在事件处理里更精细地过滤 .log 的 change 刷新
      const ignoredExts = ['.pyc', '.pyo', '.ds_store', '.swp', '.swo', '.coverage'];
      for (const ignoredExt of ignoredExts) {
        if (ext.endsWith(ignoredExt)) {
          return true;
        }
      }

      // 更复杂的模式匹配（仅在快速检查失败时执行）
      const complexIgnorePatterns = [
        /\/out\//,         // 编译输出
        /\/dist\//,        // 分发目录
        /\/\.claude\/virtualenv\//,  // 项目虚拟环境
        /\/\.claude\/\.venv\//,     // 项目虚拟环境
        /coverage/,        // 覆盖率报告
        /\.egg-info/,      // Python egg 信息
        /\/\.Python\//,    // Python build 目录
        /\/build\//,       // Python build 目录
        /\/\.ipynb\//,     // Jupyter notebook 数据
      ];
      return complexIgnorePatterns.some(pattern => pattern.test(filePath));
    };

    for (const pattern of patterns) {
      const watcher = vscode.workspace.createFileSystemWatcher(
        new vscode.RelativePattern(workspaceFolder, pattern),
      );

      watcher.onDidChange((uri) => {
        // 日志文件写入频繁，避免每次追加都触发树刷新；创建/删除仍可刷新
        if (uri.fsPath.toLowerCase().endsWith('.log')) {
          return;
        }
        if (shouldIgnorePath(uri.fsPath)) {
          return;
        }
        this.log(`File changed: ${uri.fsPath}`);
        this.refresh();
      });

      watcher.onDidCreate((uri) => {
        if (shouldIgnorePath(uri.fsPath)) {
          return;
        }
        this.log(`File created: ${uri.fsPath}`);
        this.refresh();
      });

      watcher.onDidDelete((uri) => {
        if (shouldIgnorePath(uri.fsPath)) {
          return;
        }
        this.log(`File deleted: ${uri.fsPath}`);
        this.refresh();
      });

      this.watchers.push(watcher);
      this.context.subscriptions.push(watcher);
    }

    this.log(`File watcher setup completed (${this.watchers.length} patterns)`);
  }

  /**
   * 清理文件监听器
   * 
   * 当工作区变化或扩展停用时调用，释放资源
   */
  private disposeWatcher(): void {
    if (this.watchers.length > 0) {
      this.log('Disposing file watchers');
      for (const watcher of this.watchers) {
        watcher.dispose();
      }
      this.watchers = [];
    }
  }

  /**
   * 生成缓存键
   * @param element - 树节点元素
   * @returns 缓存键字符串
   */
  private getCacheKey(element?: ProjectItem): string {
    if (!element) {
      return 'root';
    }
    return `${element.type}:${element.filePath || element.label || 'unknown'}`;
  }

  /**
   * 从缓存获取节点子项
   * @param element - 树节点元素
   * @returns 缓存的子项或 undefined
   */
  private getCachedChildren(element?: ProjectItem): ProjectItem[] | undefined {
    const key = this.getCacheKey(element);
    const cached = this.treeItemCache.get(key);
    if (cached && Date.now() - cached.timestamp < this.CACHE_TTL) {
      this.log(`Cache hit for key: ${key}`);
      return cached.items;
    }
    return undefined;
  }

  /**
   * 缓存节点子项
   * @param element - 树节点元素
   * @param items - 要缓存的子项
   */
  private setCachedChildren(element: ProjectItem | undefined, items: ProjectItem[]): void {
    const key = this.getCacheKey(element);
    this.treeItemCache.set(key, {
      items,
      timestamp: Date.now()
    });
    // 限制缓存大小，避免内存泄漏
    if (this.treeItemCache.size > 100) {
      const oldestKey = Array.from(this.treeItemCache.keys())[0];
      this.treeItemCache.delete(oldestKey);
    }
  }

  /**
   * 清除缓存
   * @param pattern - 可选的清除模式，如果提供则只清除匹配的缓存
   */
  private clearCache(pattern?: string): void {
    if (pattern) {
      for (const key of this.treeItemCache.keys()) {
        if (key.includes(pattern)) {
          this.treeItemCache.delete(key);
          this.log(`Cleared cache matching pattern: ${pattern}`);
        }
      }
    } else {
      this.treeItemCache.clear();
      this.log('Cleared all cache');
    }
  }

  /**
   * 刷新树形视图（文件监听等频繁触发时防抖合并）
   */
  refresh(): void {
    // 如果正在进行批量操作，跳过自动刷新
    if (this.batchOperationInProgress) {
      return;
    }

    // 清除缓存以强制重新读取
    this.clearCache();

    // 如果已有待执行的定时器，先清除它
    if (this.refreshTimer) {
      this.log('Debouncing: clearing existing refresh timer');
      clearTimeout(this.refreshTimer);
    }

    // 设置新的定时器
    // setTimeout返回一个定时器ID，用于后续清除
    this.refreshTimer = setTimeout(() => {
      this.log('Executing debounced refresh');

      // fire()方法会触发onDidChangeTreeData事件
      // VSCode监听到这个事件后，会调用getChildren()重新获取数据
      // 传递undefined表示刷新整个树
      this._onDidChangeTreeData.fire(undefined);

      // 清除定时器引用
      this.refreshTimer = undefined;
    }, this.DEBOUNCE_DELAY);
  }

  /** 立即刷新（跳过防抖），用于后台修复完成后的可见更新 */
  refreshNow(): void {
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = undefined;
    }
    this.clearCache();
    this._onDidChangeTreeData.fire(undefined);
  }

  private async runAutoFixInBackground(): Promise<void> {
    this.autoFixInProgress = true;
    this.setTreeMessage(localize('projectStructure.repairing'));
    try {
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('projectStructure.repairing.progress'),
        },
        async () => {
          const result = await this.workspaceManager.init({ topic: 'Fix Workspace' });
          if (result.success && result.filesCreated && result.filesCreated.length > 0) {
            this.log(`Auto-fixed workspace: created ${result.filesCreated.length} items`);
          }
        }
      );
    } catch (error: any) {
      this.log(`Auto-fix workspace failed: ${error}`);
    } finally {
      this.autoFixInProgress = false;
      this.setTreeMessage(undefined);
      this.refreshNow();
    }
  }

  /**
   * 清理资源
   * 
   * 当扩展停用时，VSCode会调用这个方法。
   * 需要清理所有资源，避免内存泄漏。
   */
  dispose(): void {
    this.log('Disposing ProjectStructureProvider');

    // 清除待执行的刷新定时器
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = undefined;
    }

    // 清理文件监听器
    this.disposeWatcher();

    // 清理 Workspace Manager
    this.workspaceManager.dispose();
  }

  /**
   * 获取树节点的显示信息
   * 
   * VSCode会为每个节点调用这个方法。
   * 由于ProjectItem本身就是TreeItem，直接返回即可。
   * 
   * @param element - 要显示的节点
   * @returns TreeItem对象，包含节点的显示信息
   */
  getTreeItem(element: ProjectItem): vscode.TreeItem {
    return element;
  }

  /**
   * 获取节点的子节点
   * 
   * 这是TreeDataProvider的核心方法。
   * VSCode会调用这个方法获取树形视图的数据：
   * - 当展开节点时，获取该节点的子节点
   * - 当首次加载视图时，element为undefined，返回根节点
   * 
   * 这个方法实现了递归的树形结构：
   * - 根节点（element为undefined）→ 显示"Research Topic"
   * - Topic节点 → 显示假设和论文
   * - Hypothesis节点 → 显示实验和SIM设置
   * - Experiment节点 → 显示初始化结果和运行结果
   * 
   * @param element - 当前节点，undefined表示根节点
   * @returns 子节点数组
   */
  async getChildren(element?: ProjectItem): Promise<ProjectItem[]> {
    const cached = this.getCachedChildren(element);
    if (cached) {
      return cached;
    }

    // 获取工作区文件夹
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      this.setTreeMessage(localize('projectStructure.noWorkspace'));
      return [];  // 没有工作区，返回空数组
    }

    const workspacePath = workspaceFolder.uri.fsPath;

    // 根节点：显示研究话题
    // element为undefined表示这是根节点
    if (!element) {
      this.setTreeMessage(
        this.autoFixInProgress
          ? localize('projectStructure.repairing')
          : localize('projectStructure.loading')
      );

      const topicFile = path.join(workspacePath, 'TOPIC.md');
      const envFile = path.join(workspacePath, '.env');
      const hasEnv = fs.existsSync(envFile);
      const hasTopic = fs.existsSync(topicFile);

      const { EnvManager } = await import('./envManager');
      const envManager = new EnvManager();
      const envConfig = envManager.readEnv();
      const hasApiKey = hasConfiguredLlmApiKey(envConfig);

      const workspaceHealth = this.checkWorkspaceHealth(workspacePath);
      const needsFix = !workspaceHealth.isHealthy;

      const items: ProjectItem[] = [];

      // 阶段1: 没有.env文件 -> 自动创建模板后继续
      if (!hasEnv) {
        envManager.createEnvFromExample();
        // 创建后直接进入阶段2（有.env但需配置 API key）
        const updatedConfig = envManager.readEnv();
        if (!updatedConfig.llmApiKey?.trim()) {
          const settingsItem = new ProjectItem(
            localize('projectStructure.settings'),
            vscode.TreeItemCollapsibleState.None,
            'settings',
            undefined
          );
          settingsItem.tooltip = localize('projectStructure.settings.tooltip');
          items.push(settingsItem);

          const infoItem = new ProjectItem(
            localize('projectStructure.apiKeyRequired.label'),
            vscode.TreeItemCollapsibleState.None,
            'initWorkspace',
            undefined
          );
          infoItem.command = {
            command: 'aiSocialScientist.openConfigPage',
            title: localize('projectStructure.settings')
          };
          infoItem.tooltip = localize('projectStructure.apiKeyRequired.tooltip');
          items.push(infoItem);
          this.setTreeMessage(localize('projectStructure.apiKeyRequired.message'));
          return items;
        }
      }

      // 阶段2: 有.env但没有配置API key -> 提示配置环境变量
      if (hasEnv && !hasApiKey) {
        const settingsItem = new ProjectItem(
          localize('projectStructure.settings'),
          vscode.TreeItemCollapsibleState.None,
          'settings',
          undefined
        );
        settingsItem.tooltip = localize('projectStructure.settings.tooltip');
        items.push(settingsItem);

        // 显示说明信息
        const infoItem = new ProjectItem(
          localize('projectStructure.apiKeyRequired.label'),
          vscode.TreeItemCollapsibleState.None,
          'initWorkspace',
          undefined
        );
        infoItem.command = {
          command: 'aiSocialScientist.openConfigPage',
          title: localize('projectStructure.settings')
        };
        infoItem.tooltip = localize('projectStructure.apiKeyRequired.tooltip');
        items.push(infoItem);
        this.setTreeMessage(localize('projectStructure.apiKeyRequired.message'));
        return items;
      }

      // 阶段3: 有.env且配置了API key，但没有TOPIC.md -> 提示初始化工作区
      if (hasEnv && hasApiKey && !hasTopic) {
        // 配置设置按钮始终在最上面
        const settingsItem = new ProjectItem(
          localize('projectStructure.settings'),
          vscode.TreeItemCollapsibleState.None,
          'settings',
          undefined
        );
        settingsItem.tooltip = localize('projectStructure.settings.tooltip');
        items.push(settingsItem);

        const initItem = new ProjectItem(
          localize('extension.initProject.button'),
          vscode.TreeItemCollapsibleState.None,
          'initWorkspace',
          undefined
        );
        initItem.command = {
          command: 'aiSocialScientist.initProject',
          title: localize('extension.initProject.commandTitle'),
        };
        initItem.tooltip = localize('extension.initProject.tooltip');
        items.push(initItem);

        this.setTreeMessage(localize('projectStructure.initRequired.message'));
        return items;
      }

      // 已初始化：配置入口在视图标题栏（齿轮），此处不再重复「配置设置」以免与标题操作重叠

      // 添加 AI Chat 入口
      const aiChatItem = new ProjectItem(
        localize('extension.aiChat.label'),
        vscode.TreeItemCollapsibleState.None,
        'aiChat',
        undefined
      );
      aiChatItem.command = {
        command: 'aiSocialScientist.openChat',
        title: localize('extension.aiChat.commandTitle'),
      };
      aiChatItem.tooltip = localize('extension.aiChat.tooltip');
      items.push(aiChatItem);

      // 工作区目录不完整时后台补全，不阻塞侧栏首屏
      if (needsFix && !this.autoFixInProgress) {
        void this.runAutoFixInBackground();
      }

      // 添加项目状态概览（统计信息）
      const statsOverview = this.getProjectStats(workspacePath);
      if (statsOverview) {
        const statsItem = new ProjectItem(
          statsOverview.label,
          vscode.TreeItemCollapsibleState.None,
          'projectStats',
          undefined
        );
        statsItem.description = statsOverview.description;
        statsItem.tooltip = statsOverview.tooltip;
        if (statsOverview.failedExperiments > 0) {
          statsItem.iconPath = makeThemeIcon('warning', 'charts.red');
        } else if (statsOverview.runningExperiments > 0) {
          statsItem.iconPath = makeThemeIcon('sync', 'charts.yellow');
        } else {
          statsItem.iconPath = makeThemeIcon('graph', 'charts.green');
        }
        items.push(statsItem);
      }

      const skillMgmt = new ProjectItem(
        localize('projectStructure.skillManagement.label'),
        vscode.TreeItemCollapsibleState.None,
        'skillManagement',
        undefined
      );
      skillMgmt.command = {
        command: 'aiSocialScientist.openSkillMarketplace',
        title: localize('projectStructure.skillManagement.commandTitle'),
      };
      skillMgmt.description = localize('projectStructure.skillManagement.description');
      skillMgmt.tooltip = localize('projectStructure.skillManagement.tooltip');
      items.push(skillMgmt);

      const prefillItem = new ProjectItem(
        localize('prefillParams.groupTitle'),
        vscode.TreeItemCollapsibleState.None,
        'prefillParamsGroup',
        undefined
      );
      prefillItem.description = localize('projectStructure.prefillParams.description');
      prefillItem.tooltip = localize('projectStructure.prefillParams.tooltip');
      items.push(prefillItem);

      const topicItem = new ProjectItem(
        localize('projectStructure.researchTopic'),
        vscode.TreeItemCollapsibleState.Expanded,
        'topic',
        topicFile
      );
      topicItem.tooltip = localize('projectStructure.researchTopic.tooltip');
      items.push(topicItem);

      if (this.autoFixInProgress) {
        this.setTreeMessage(localize('projectStructure.repairing'));
      } else {
        this.setTreeMessage(undefined);
      }
      this.setCachedChildren(undefined, items);
      return items;
    }

    if (element.type === 'skillManagement') {
      return [];
    }

    const isChinese = isExtensionZh();
    const topicFile = path.join(workspacePath, 'TOPIC.md');

    if (element.type === 'projectStats') {
      return this.buildProjectStatsMetricItems(workspacePath);
    }

    // 环境与智能体节点的子节点：已移空（测试功能移至webview内）
    if (element.type === 'prefillParamsGroup') {
      return [];
    }

    // 自定义模块节点的子节点：显示扫描结果（已废弃，保留兼容性）
    if (element.type === 'custom') {
      const items: ProjectItem[] = [];

      // 如果有扫描结果,显示分组
      if (this.customModulesCache.agents.length > 0) {
        items.push(new ProjectItem(
          `${localize('projectStructure.customAgents')} (${this.customModulesCache.agents.length})`,
          vscode.TreeItemCollapsibleState.Collapsed,
          'customAgentsGroup',
          undefined
        ));
      }

      if (this.customModulesCache.envs.length > 0) {
        items.push(new ProjectItem(
          `${localize('projectStructure.customEnvs')} (${this.customModulesCache.envs.length})`,
          vscode.TreeItemCollapsibleState.Collapsed,
          'customEnvsGroup',
          undefined
        ));
      }

      return items;
    }

    // 自定义Agents分组节点：显示所有Agent
    if (element.type === 'customAgentsGroup') {
      return this.customModulesCache.agents.map(agent => {
        const item = new ProjectItem(
          agent.class_name,
          vscode.TreeItemCollapsibleState.None,
          'customAgentItem',
          agent.file_path
        );
        item.tooltip = agent.description;
        item.isCustom = true;
        item.moduleType = 'agent';
        item.className = agent.class_name;
        return item;
      });
    }

    // 自定义Envs分组节点：显示所有环境模块
    if (element.type === 'customEnvsGroup') {
      return this.customModulesCache.envs.map(env => {
        const item = new ProjectItem(
          env.class_name,
          vscode.TreeItemCollapsibleState.None,
          'customEnvItem',
          env.file_path
        );
        item.tooltip = env.description;
        item.isCustom = true;
        item.moduleType = 'env';
        item.className = env.class_name;
        return item;
      });
    }

    // Topic节点的子节点：显示假设和论文
    if (element.type === 'topic') {
      const items: ProjectItem[] = [];

      if (fs.existsSync(topicFile)) {
        const topicFileItem = new ProjectItem(
          'TOPIC.md',
          vscode.TreeItemCollapsibleState.None,
          'topic',
          topicFile
        );
        topicFileItem.tooltip = localize('projectStructure.topicFile.tooltip');
        items.push(topicFileItem);
      }

      // 查找所有假设目录（hypothesis_12345格式）
      // findDirectories方法会匹配符合正则表达式的目录名
      const hypothesisDirs = this.findDirectories(workspacePath, /^hypothesis_\d+$/);
      if (hypothesisDirs.length > 0) {
        for (const dir of hypothesisDirs) {
          const hypothesisFile = path.join(dir, 'HYPOTHESIS.md');
          const dirName = path.basename(dir);  // 如hypothesis_12345
          // 提取数字部分，转换为友好的显示名称（如"假设 12345"）
          const match = dirName.match(/^hypothesis_(\d+)$/);

          // 统计实验数量和完成数量
          const experimentDirs = this.findDirectories(dir, /^experiment_\d+$/);
          const totalExperiments = experimentDirs.length;
          let completedExperiments = 0;
          let runningExperiments = 0;
          let failedExperiments = 0;

          for (const expDir of experimentDirs) {
            const pidFile = path.join(expDir, 'run', 'pid.json');
            if (fs.existsSync(pidFile)) {
              try {
                const pidContent = fs.readFileSync(pidFile, 'utf-8');
                const pidData = JSON.parse(pidContent);
                const st = this.normalizeExperimentStatus(pidData.status);
                if (st === 'completed') {
                  completedExperiments++;
                } else if (st === 'running') {
                  runningExperiments++;
                } else if (st === 'failed') {
                  failedExperiments++;
                }
              } catch { void 0; }
            }
          }

          const displayName = match
            ? `${localize('projectStructure.hypothesis')} ${match[1]}`
            : dirName;  // 如果格式不匹配，使用原目录名

          const item = new ProjectItem(
            displayName,  // 显示为"假设 12345"或"Hypothesis 12345"
            vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
            'hypothesis',
            fs.existsSync(hypothesisFile) ? hypothesisFile : undefined  // 如果存在HYPOTHESIS.md，点击可打开
          );

          // 设置 tooltip 显示详细状态
          if (totalExperiments > 0) {
            item.tooltip = `${localize('projectStructure.experiments')}: ${totalExperiments}\n${localize('projectStructure.completed')}: ${completedExperiments}`;
            if (runningExperiments > 0) {
              item.tooltip += `\n${localize('projectStructure.running')}: ${runningExperiments}`;
            }
            if (failedExperiments > 0) {
              item.tooltip += `\n${localize('projectStructure.statusFailed')}: ${failedExperiments}`;
            }
          }

          // 将状态信息放到 description，避免 label 过长/混入符号
          if (totalExperiments > 0) {
            const bits: string[] = [`${completedExperiments}/${totalExperiments}`];
            if (runningExperiments > 0) {
              bits.push(`${localize('projectStructure.running')}:${runningExperiments}`);
            }
            if (failedExperiments > 0) {
              bits.push(`${localize('projectStructure.statusFailed')}:${failedExperiments}`);
            }
            item.description = bits.join(' · ');

            // 为假设节点提供语义化图标：失败优先，其次运行中，否则完成/默认
            if (failedExperiments > 0) {
              item.iconPath = makeThemeIcon('warning', 'charts.red');
            } else if (runningExperiments > 0) {
              item.iconPath = makeThemeIcon('sync', 'charts.yellow');
            } else if (completedExperiments === totalExperiments && totalExperiments > 0) {
              item.iconPath = makeThemeIcon('pass-filled', 'charts.green');
            } else {
              item.iconPath = makeThemeIcon('lightbulb', 'charts.blue');
            }
          }

          items.push(item);
        }
      }

      // 查找papers目录，如果有论文文件，创建一个"文献库"节点
      const papersDir = path.join(workspacePath, 'papers');
      if (fs.existsSync(papersDir)) {
        // 创建一个"文献库"节点，可展开显示所有论文
        items.push(new ProjectItem(
          localize('projectStructure.literature'),  // 显示为"文献库"
          vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
          'papers',  // 节点类型为papers
          papersDir
        ));
        items[items.length - 1].contextValue = 'papers literatureRoot';
        items[items.length - 1].tooltip = localize('projectStructure.literature.tooltip');
      }

      // 查找user_data目录，如果存在，创建一个"用户数据"节点
      const userDataDir = path.join(workspacePath, 'user_data');
      if (fs.existsSync(userDataDir)) {
        // 创建一个"用户数据"节点，可展开显示所有文件
        items.push(new ProjectItem(
          localize('projectStructure.userData'),  // 显示为"用户数据"
          vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
          'userdata',  // 节点类型为userdata
          undefined  // 用户数据节点本身不关联文件
        ));
        items[items.length - 1].tooltip = localize('projectStructure.userData.tooltip');
      }

      // 查找datasets目录，如果存在，创建一个"数据集"节点
      const datasetsDir = path.join(workspacePath, 'datasets');
      if (fs.existsSync(datasetsDir)) {
        // 统计本地数据集数量（每个含 metadata.json 的子目录视为一个数据集）
        const datasetCount = fs.readdirSync(datasetsDir)
          .filter(name => {
            const subDir = path.join(datasetsDir, name);
            return fs.statSync(subDir).isDirectory() &&
              fs.existsSync(path.join(subDir, 'metadata.json'));
          }).length;

        const datasetsItem = new ProjectItem(
          localize('projectStructure.datasets'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'datasets',
          undefined
        );
        if (datasetCount > 0) {
          datasetsItem.description = localize('projectStructure.groupItemCount', datasetCount);
        }
        datasetsItem.tooltip = localize('projectStructure.datasets.tooltip');
        items.push(datasetsItem);
      }

      // 查找custom目录，如果存在，创建一个"自定义模块"节点
      const customDir = path.join(workspacePath, 'custom');
      if (fs.existsSync(customDir)) {
        // 创建一个"自定义模块"节点，可展开显示子目录
        items.push(new ProjectItem(
          localize('projectStructure.customModules'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'customWorkspace',
          undefined
        ));
        items[items.length - 1].tooltip = localize('projectStructure.customModules.tooltip');
      }

      // 查找presentation目录（分析报告）
      const presentationDir = path.join(workspacePath, 'presentation');
      if (fs.existsSync(presentationDir)) {
        items.push(new ProjectItem(
          localize('projectStructure.presentation'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'presentation',
          undefined
        ));
        items[items.length - 1].tooltip = localize('projectStructure.presentation.tooltip');
      }

      // 查找synthesis目录（综合报告）
      const synthesisDir = path.join(workspacePath, 'synthesis');
      if (fs.existsSync(synthesisDir)) {
        const synItem = new ProjectItem(
          localize('projectStructure.synthesis'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'synthesis',
          undefined
        );
        synItem.tooltip = localize('projectStructure.synthesis.tooltip');
        const synReportCount = countSynthesisReports(synthesisDir);
        if (synReportCount > 0) {
          synItem.description = localize(
            'projectStructure.presentationReportsAvailable',
            synReportCount
          );
        }
        items.push(synItem);
      }

      // paper-toolkit 论文工作区
      const paperDir = path.join(workspacePath, 'paper');
      if (fs.existsSync(paperDir)) {
        const paperItem = new ProjectItem(
          localize('projectStructure.paperWorkspace'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'paperWorkspace',
          paperDir
        );
        paperItem.tooltip = localize('projectStructure.paperWorkspace.tooltip');
        paperItem.iconPath = makeThemeIcon('book', 'charts.purple');
        items.push(paperItem);
      }

      // paper-toolkit 分析管线产物
      const analysisDir = path.join(workspacePath, 'analysis');
      if (fs.existsSync(analysisDir)) {
        const analysisItem = new ProjectItem(
          localize('projectStructure.analysisWorkspace'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'analysisWorkspace',
          analysisDir
        );
        analysisItem.tooltip = localize('projectStructure.analysisWorkspace.tooltip');
        analysisItem.iconPath = makeThemeIcon('beaker', 'charts.purple');
        items.push(analysisItem);
      }

      return items;
    }

    // Papers节点（文献库）的子节点：按类型分组显示
    if (element.type === 'papers') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const papersDir = path.join(workspacePath, 'papers');
      const items: ProjectItem[] = [];

      if (fs.existsSync(papersDir)) {
        const entries = listDirEntriesSafe(papersDir).filter(entry => !shouldHideFsEntry(entry));

        // 按类型分类文件
        const pdfFiles: { name: string; path: string }[] = [];
        const mdFiles: { name: string; path: string }[] = [];
        const jsonFiles: { name: string; path: string }[] = [];
        const otherFiles: { name: string; path: string }[] = [];
        const directories: { name: string; path: string; count: number }[] = [];

        for (const entry of entries) {
          const fullPath = path.join(papersDir, entry);
          const stat = safeStatSync(fullPath);
          if (!stat) {
            continue;
          }

          if (stat.isFile()) {
            if (!shouldShowFileByExt(entry)) {
              continue;
            }
            const ext = entry.toLowerCase().split('.').pop() || '';
            if (ext === 'pdf') {
              pdfFiles.push({ name: entry, path: fullPath });
            } else if (ext === 'md') {
              mdFiles.push({ name: entry, path: fullPath });
            } else if (ext === 'json') {
              jsonFiles.push({ name: entry, path: fullPath });
            } else {
              otherFiles.push({ name: entry, path: fullPath });
            }
          } else if (stat.isDirectory()) {
            let fileCount = 0;
            try {
              const subEntries = listDirEntriesSafe(fullPath).filter((sub: string) => !shouldHideFsEntry(sub));
              fileCount = subEntries.filter((sub: string) => {
                const subPath = path.join(fullPath, sub);
                const subStat = safeStatSync(subPath);
                return !!subStat && subStat.isFile() && shouldShowFileByExt(sub);
              }).length;
            } catch { void 0; }
            directories.push({ name: entry, path: fullPath, count: fileCount });
          }
        }

        // 文献索引文件（特殊处理，置顶显示）
        const literatureIndexFile = jsonFiles.find(f => f.name === 'literature_index.json');
        if (literatureIndexFile) {
          try {
            const content = fs.readFileSync(literatureIndexFile.path, 'utf-8');
            const data = JSON.parse(content);
            const count = data.entries?.length || 0;
            const fileItem = new ProjectItem(
              localize('projectStructure.literatureIndex'),
              vscode.TreeItemCollapsibleState.None,
              'paper',
              literatureIndexFile.path
            );
            fileItem.description = localize('projectStructure.literatureIndex.countSuffix', count);
            fileItem.tooltip = [
              localize('projectStructure.literatureIndex'),
              localize('projectStructure.literatureIndex.detail', count),
              workspaceRelativeTreeTooltip(workspacePath, literatureIndexFile.path),
            ].join('\n');
            fileItem.command = {
              command: 'aiSocialScientist.viewLiteratureIndex',
              title: '查看文献索引',
              arguments: [{ filePath: literatureIndexFile.path }]
            };
            items.push(fileItem);
          } catch { void 0; }
        }

        // PDF 文献组
        if (pdfFiles.length > 0) {
          const pdfGroup = new ProjectItem(
            localize('projectStructure.pdfFiles'),
            vscode.TreeItemCollapsibleState.Collapsed,
            'paperPdfGroup',
            papersDir
          );
          pdfGroup.description = localize('projectStructure.groupItemCount', pdfFiles.length);
          (pdfGroup as any).fileList = pdfFiles;
          items.push(pdfGroup);
        }

        // Markdown 笔记组
        if (mdFiles.length > 0) {
          const mdGroup = new ProjectItem(
            localize('projectStructure.mdFiles'),
            vscode.TreeItemCollapsibleState.Collapsed,
            'paperMdGroup',
            papersDir
          );
          mdGroup.description = localize('projectStructure.groupItemCount', mdFiles.length);
          (mdGroup as any).fileList = mdFiles;
          items.push(mdGroup);
        }

        // 其他 JSON 文件组
        const otherJsonFiles = jsonFiles.filter(f => f.name !== 'literature_index.json');
        if (otherJsonFiles.length > 0) {
          const jsonGroup = new ProjectItem(
            localize('projectStructure.jsonFiles'),
            vscode.TreeItemCollapsibleState.Collapsed,
            'paperJsonGroup',
            papersDir
          );
          jsonGroup.description = localize('projectStructure.groupItemCount', otherJsonFiles.length);
          (jsonGroup as any).fileList = otherJsonFiles;
          items.push(jsonGroup);
        }

        // 其他文件
        for (const file of otherFiles) {
          items.push(new ProjectItem(file.name, vscode.TreeItemCollapsibleState.None, 'paper', file.path));
        }

        // 子目录
        for (const dir of directories) {
          const displayName = dir.name === 'full_texts'
            ? localize('projectStructure.fullTextPdfs')
            : dir.name;
          const dirItem = new ProjectItem(
            displayName,
            vscode.TreeItemCollapsibleState.Collapsed,
            'paper',
            dir.path
          );
          if (dir.count > 0) {
            dirItem.description = localize('projectStructure.groupItemCount', dir.count);
          }
          dirItem.tooltip = [
            `${displayName} — ${dir.count} ${localize('projectStructure.files')}`,
            workspaceRelativeTreeTooltip(workspacePath, dir.path),
          ].join('\n');
          items.push(dirItem);
        }
      }

      return items;
    }

    // 处理paper类型节点：如果是目录，显示其子文件和子目录
    if (element.type === 'paper' && element.filePath) {
      const filePath = element.filePath;
      // 检查是否为目录
      if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
        const items: ProjectItem[] = [];
        // 读取目录内容，过滤无关目录/文件
        const entries = listDirEntriesSafe(filePath).filter(entry => !shouldHideFsEntry(entry));

        for (const entry of entries) {
          const fullPath = path.join(filePath, entry);
          const stat = safeStatSync(fullPath);
          if (!stat) {
            continue;
          }

          if (stat.isFile()) {
            if (!shouldShowFileInTreeListing(filePath, entry)) {
              continue;
            }
            const pi = new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.None,
              'paper',
              fullPath
            );
            pi.tooltip = workspaceRelativeTreeTooltip(workspacePath, fullPath);
            items.push(pi);
          } else if (stat.isDirectory()) {
            const pi = new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.Collapsed,
              'paper',
              fullPath
            );
            pi.tooltip = workspaceRelativeTreeTooltip(workspacePath, fullPath);
            items.push(pi);
          }
        }

        return items;
      }
    }

    // 处理文献分组节点（PDF/MD/JSON）
    if ((element.type === 'paperPdfGroup' || element.type === 'paperMdGroup' || element.type === 'paperJsonGroup') && (element as any).fileList) {
      const fileList: { name: string; path: string }[] = (element as any).fileList;
      const items: ProjectItem[] = [];

      for (const file of fileList) {
        const pi = new ProjectItem(
          file.name,
          vscode.TreeItemCollapsibleState.None,
          'paperArtifact',
          file.path
        );
        const ws = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        if (ws) {
          pi.tooltip = workspaceRelativeTreeTooltip(ws, file.path);
        }
        items.push(pi);
      }

      const extra = (element as ProjectItem & { extraChildren?: ProjectItem[] }).extraChildren;
      if (extra?.length) {
        items.push(...extra);
      }

      return items;
    }

    // 处理 pid.json 可视化
    if (element.type === 'pidJson' && element.filePath) {
      return []; // pid.json 没有子节点，点击打开可视化面板
    }

    // UserData节点（用户数据）的子节点：显示所有文件
    if (element.type === 'userdata') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const userDataDir = path.join(workspacePath, 'user_data');
      const items: ProjectItem[] = [];

      if (fs.existsSync(userDataDir)) {
        const entries = listDirEntriesSafe(userDataDir).filter(entry => !shouldHideFsEntry(entry));

        for (const entry of entries) {
          const fullPath = path.join(userDataDir, entry);
          const stat = safeStatSync(fullPath);
          if (!stat) {
            continue;
          }

          if (stat.isFile()) {
            if (!shouldShowFileByExt(entry)) {
              continue;
            }
            const fileItem = new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.None,
              'file',
              fullPath
            );
            fileItem.tooltip = workspaceRelativeTreeTooltip(workspacePath, fullPath);
            items.push(fileItem);
          } else if (stat.isDirectory()) {
            const dirItem = new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.Collapsed,
              'file',
              fullPath
            );
            dirItem.tooltip = workspaceRelativeTreeTooltip(workspacePath, fullPath);
            items.push(dirItem);
          }
        }
      }

      return items;
    }

    // Datasets节点（数据集）的子节点：显示每个本地数据集
    if (element.type === 'datasets') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const datasetsDir = path.join(workspaceFolder.uri.fsPath, 'datasets');
      if (!fs.existsSync(datasetsDir)) {
        return [];
      }

      const items: ProjectItem[] = [];
      const entries = fs.readdirSync(datasetsDir);

      for (const entry of entries) {
        const fullPath = path.join(datasetsDir, entry);
        if (!fs.statSync(fullPath).isDirectory()) { continue; }

        const metadataPath = path.join(fullPath, 'metadata.json');
        if (!fs.existsSync(metadataPath)) { continue; }

        // 读取 metadata.json 获取友好名称
        let displayName = entry;
        let description = '';
        try {
          const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf-8'));
          if (metadata.name) { displayName = metadata.name; }
          if (metadata.description) { description = metadata.description; }
          if (metadata.version) { displayName += ` (${metadata.version})`; }
        } catch {
          // metadata 解析失败，使用目录名
        }

        // 如果有 README.md，点击可预览
        const readmePath = path.join(fullPath, 'README.md');

        const item = new ProjectItem(
          displayName,
          vscode.TreeItemCollapsibleState.Collapsed,
          'datasetItem',
          fs.existsSync(readmePath) ? readmePath : undefined
        );
        item.tooltip = description || entry;
        (item as any).datasetDirPath = fullPath;
        items.push(item);
      }

      return items;
    }

    // DatasetItem展开时显示目录内容
    if (element.type === 'datasetItem') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      const workspacePathRoot = workspaceFolder?.uri.fsPath ?? '';
      const datasetDirPath = (element as any).datasetDirPath;
      if (!datasetDirPath || !fs.existsSync(datasetDirPath) || !fs.statSync(datasetDirPath).isDirectory()) {
        return [];
      }

      const items: ProjectItem[] = [];
      const entries = listDirEntriesSafe(datasetDirPath).filter(entry => !shouldHideFsEntry(entry));

      for (const entry of entries) {
        const fullPath = path.join(datasetDirPath, entry);
        const stat = safeStatSync(fullPath);
        if (!stat) {
          continue;
        }

        if (stat.isFile()) {
          if (!shouldShowFileByExt(entry)) {
            continue;
          }
          const fileItem = new ProjectItem(
            entry,
            vscode.TreeItemCollapsibleState.None,
            'file',
            fullPath
          );
          if (workspacePathRoot) {
            fileItem.tooltip = workspaceRelativeTreeTooltip(workspacePathRoot, fullPath);
          }
          if (entry.toLowerCase().endsWith('.md')) {
            fileItem.command = {
              command: 'markdown.showPreview',
              title: 'Open Preview',
              arguments: [vscode.Uri.file(fullPath)]
            };
          }
          items.push(fileItem);
        } else if (stat.isDirectory()) {
          const subdirItem = new ProjectItem(
            entry,
            vscode.TreeItemCollapsibleState.Collapsed,
            'file',
            fullPath
          );
          if (workspacePathRoot) {
            subdirItem.tooltip = workspaceRelativeTreeTooltip(workspacePathRoot, fullPath);
          }
          items.push(subdirItem);
        }
      }

      return items;
    }

    // 处理file类型节点：如果是目录，显示其子文件和子目录
    if (element.type === 'file' && element.filePath) {
      const filePath = element.filePath;
      // 检查是否为目录
      if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
        const items: ProjectItem[] = [];
        let entries = listDirEntriesSafe(filePath).filter(entry => !shouldHideFsEntry(entry));
        const chartsDir = isAnalysisChartsDirectory(filePath);
        if (chartsDir) {
          entries = [...entries].sort((a, b) => comparePresentationChartsEntries(a, b, filePath));
        }

        for (const entry of entries) {
          const fullPath = path.join(filePath, entry);
          const stat = safeStatSync(fullPath);
          if (!stat) {
            continue;
          }

          if (stat.isFile()) {
            const allowFile = chartsDir
              ? shouldShowFileInPresentationCharts(entry)
              : isUnderUserArtifactTree(filePath)
                ? shouldShowUserFacingArtifact(entry)
                : shouldShowFileInTreeListing(filePath, entry, workspacePath);
            if (!allowFile) {
              continue;
            }
            const fileItem = new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.None,
              'file',
              fullPath,
            );
            fileItem.tooltip = workspaceRelativeTreeTooltip(workspacePath, fullPath);
            if (chartsDir) {
              fileItem.description = getPresentationChartsFileDescription(entry);
            }
            items.push(fileItem);
          } else if (stat.isDirectory()) {
            if (!shouldShowDirectoryInTree(filePath, entry, workspacePath)) {
              continue;
            }
            const dirItem = new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.Collapsed,
              'file',
              fullPath,
            );
            dirItem.tooltip = workspaceRelativeTreeTooltip(workspacePath, fullPath);
            if (customSkillRoot(workspacePath, filePath)) {
              dirItem.iconPath = makeThemeIcon('folder', 'charts.blue');
            } else if (isAgentSkillDirectory(fullPath)) {
              dirItem.iconPath = makeThemeIcon('sparkle', 'charts.green');
              dirItem.description = localize('projectStructure.customSkills.skillDir');
            }
            items.push(dirItem);
          }
        }

        return items;
      }
    }

    // Custom Workspace节点（custom/目录）的子节点：显示agents和envs
    if (element.type === 'customWorkspace') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const customDir = path.join(workspacePath, 'custom');
      const items: ProjectItem[] = [];

      if (fs.existsSync(customDir)) {
        const entries = listDirEntriesSafe(customDir)
          .filter((entry) => !shouldHideFsEntry(entry))
          .sort((a, b) => {
          const rank = (name: string): number => {
            const normalized = name.toLowerCase();
            if (normalized === 'agents') { return 0; }
            if (normalized === 'envs') { return 1; }
            if (normalized === 'skills') { return 2; }
            return 10;
          };
          const rankDiff = rank(a) - rank(b);
          if (rankDiff !== 0) {
            return rankDiff;
          }
          return a.localeCompare(b);
        });

        for (const entry of entries) {
          const fullPath = path.join(customDir, entry);
          const stat = safeStatSync(fullPath);
          if (!stat) {
            continue;
          }

          if (stat.isDirectory()) {
            if (!shouldShowDirectoryInTree(customDir, entry, workspacePath)) {
              continue;
            }
            const dirItem = new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.Collapsed,
              'file',
              fullPath
            );
            const semanticIcon = getCustomWorkspaceDirIcon(entry);
            if (semanticIcon) {
              dirItem.iconPath = semanticIcon;
              dirItem.resourceUri = undefined;
            }
            dirItem.tooltip = workspaceRelativeTreeTooltip(workspacePath, fullPath);
            if (entry.toLowerCase() === 'skills') {
              const skillCount = listDirEntriesSafe(fullPath)
                .filter((name) => !shouldHideFsEntry(name))
                .filter((name) => {
                  const childPath = path.join(fullPath, name);
                  const childStat = safeStatSync(childPath);
                  return !!childStat?.isDirectory() && isAgentSkillDirectory(childPath);
                }).length;
              if (skillCount > 0) {
                dirItem.description = localize('projectStructure.customSkills.count', skillCount);
              }
            }
            items.push(dirItem);
          } else if (stat.isFile()) {
            if (!shouldShowFileInTreeListing(customDir, entry, workspacePath)) {
              continue;
            }
            const fileItem = new ProjectItem(
              entry,
              vscode.TreeItemCollapsibleState.None,
              'file',
              fullPath
            );
            fileItem.tooltip = workspaceRelativeTreeTooltip(workspacePath, fullPath);
            items.push(fileItem);
          }
        }
      }

      return items;
    }

    // Hypothesis节点的子节点：显示实验和SIM设置
    if (element.type === 'hypothesis') {
      // 获取假设目录的路径
      // element.filePath是HYPOTHESIS.md的路径，dirname获取其所在目录
      const hypothesisDir = path.dirname(element.filePath || '');

      // 提取 hypothesis_id（从目录名 hypothesis_xxx 中提取）
      const hypothesisDirName = path.basename(hypothesisDir);
      const hypothesisMatch = hypothesisDirName.match(/^hypothesis_(\d+)$/);
      const hypothesisId = hypothesisMatch ? hypothesisMatch[1] : undefined;

      // 查找该假设下的所有实验目录（experiment_123格式）
      const experimentDirs = this.findDirectories(hypothesisDir, /^experiment_\d+$/);

      const items: ProjectItem[] = [];

      // Show HYPOTHESIS.md as the first child for quick access
      if (element.filePath && fs.existsSync(element.filePath)) {
        const hypItem = new ProjectItem(
          'HYPOTHESIS.md',
          vscode.TreeItemCollapsibleState.None,
          'file',
          element.filePath,
        );
        items.push(hypItem);
      }

      // 为每个实验目录创建节点
      for (const dir of experimentDirs) {
        const experimentFile = path.join(dir, 'EXPERIMENT.md');
        const dirName = path.basename(dir);  // 如experiment_123
        // 提取数字部分，转换为友好的显示名称（如"实验 123"）
        const match = dirName.match(/^experiment_(\d+)$/);
        const experimentId = match ? match[1] : undefined;

        // 检查实验状态（通过 pid.json），通过 icon/description 呈现而非 emoji 拼接
        let statusKey: 'completed' | 'running' | 'failed' | 'pending' | 'unknown' = 'pending';
        let statusTooltip = '';
        const pidFile = path.join(dir, 'run', 'pid.json');
        if (fs.existsSync(pidFile)) {
          try {
            const pidContent = fs.readFileSync(pidFile, 'utf-8');
            const pidData = JSON.parse(pidContent);
            const status = this.normalizeExperimentStatus(pidData.status);
            if (status === 'completed') {
              statusKey = 'completed';
              statusTooltip = localize('projectStructure.statusCompleted');
            } else if (status === 'running') {
              statusKey = 'running';
              statusTooltip = localize('projectStructure.statusRunning');
            } else if (status === 'failed') {
              statusKey = 'failed';
              statusTooltip = localize('projectStructure.statusFailed');
            } else {
              statusKey = status === 'unknown' ? 'unknown' : 'pending';
              statusTooltip = localize('projectStructure.statusPaused');
            }
          } catch {
            statusKey = 'unknown';
          }
        }

        const displayName = match
          ? `${localize('projectStructure.experiment')} ${match[1]}`
          : dirName;  // 如果格式不匹配，使用原目录名
        const item = new ProjectItem(
          displayName,  // 显示为"实验 123"或"Experiment 123"
          vscode.TreeItemCollapsibleState.Collapsed,  // 可展开
          'experiment',
          fs.existsSync(experimentFile) ? experimentFile : undefined
        );
        if (statusTooltip) {
          item.tooltip = statusTooltip;
        }
        item.description = this.getExperimentStatusLabel(statusKey, isChinese);
        item.iconPath = this.getExperimentStatusIcon(statusKey);
        // Set hypothesis and experiment IDs for replay command
        item.hypothesisId = hypothesisId;
        item.experimentId = experimentId;
        item.experimentRoot = dir;
        items.push(item);
      }

      // 添加SIM_SETTINGS.json文件节点（如果存在）
      const simSettingsFile = path.join(hypothesisDir, 'SIM_SETTINGS.json');
      if (fs.existsSync(simSettingsFile)) {
        items.push(new ProjectItem(
          localize('projectStructure.simSettings'),  // 显示标签（国际化）
          vscode.TreeItemCollapsibleState.None,  // 文件没有子节点
          'file',
          simSettingsFile
        ));
      }

      return items;
    }

    // Experiment节点的子节点：显示初始化结果和运行结果
    if (element.type === 'experiment') {
      const experimentDir =
        element.experimentRoot && fs.existsSync(element.experimentRoot)
          ? element.experimentRoot
          : path.dirname(element.filePath || '');
      const items: ProjectItem[] = [];

      // Show EXPERIMENT.md as the first child for quick access
      const experimentMdPath = path.join(experimentDir, 'EXPERIMENT.md');
      if (fs.existsSync(experimentMdPath)) {
        items.push(new ProjectItem(
          'EXPERIMENT.md',
          vscode.TreeItemCollapsibleState.None,
          'file',
          experimentMdPath,
        ));
      }

      // 检查init目录（配置文件分组）
      const initDir = path.join(experimentDir, 'init');
      if (fs.existsSync(initDir)) {
        const initFiles = fs.readdirSync(initDir).filter(file => {
          const filePath = path.join(initDir, file);
          return fs.statSync(filePath).isFile();
        });

        if (initFiles.length > 0) {
          // 创建配置文件分组节点
          const configGroup = new ProjectItem(
            isChinese ? '配置文件' : 'Configuration',
            vscode.TreeItemCollapsibleState.Collapsed,
            'experimentInitGroup',
            undefined  // 不传递路径，通过 element 的其他属性获取
          );
          (configGroup as any).initDir = initDir;
          (configGroup as any).hypothesisId = element.hypothesisId;
          (configGroup as any).experimentId = element.experimentId;
          items.push(configGroup);
        }
      }

      // 检查run目录（运行结果分组）
      const runDir = path.join(experimentDir, 'run');
      if (fs.existsSync(runDir)) {
        const runFiles = fs.readdirSync(runDir);
        // 运行中常见仅有子目录（如 agents/）尚无顶层日志文件，仍需展示「运行结果」
        const hasRunContent = runFiles.some(file => {
          const filePath = path.join(runDir, file);
          try {
            const st = fs.statSync(filePath);
            return st.isFile() || st.isDirectory();
          } catch {
            return false;
          }
        });

        if (hasRunContent) {
          // 创建运行结果分组节点
          const runGroup = new ProjectItem(
            isChinese ? '运行结果' : 'Run Results',
            vscode.TreeItemCollapsibleState.Collapsed,
            'experimentRunGroup',
            undefined  // 不传递路径
          );
          (runGroup as any).runDir = runDir;
          (runGroup as any).hypothesisId = element.hypothesisId;
          (runGroup as any).experimentId = element.experimentId;
          items.push(runGroup);
        }
      }

      return items;
    }

    // 实验配置文件分组
    if (element.type === 'experimentInitGroup') {
      const initDir = (element as any).initDir;
      if (!initDir || !fs.existsSync(initDir)) {
        return [];
      }
      const items: ProjectItem[] = [];
      const initFiles = listDirEntriesSafe(initDir).filter(f => !shouldHideFsEntry(f));

      for (const file of initFiles) {
        const filePath = path.join(initDir, file);
        const stat = safeStatSync(filePath);
        if (!stat) {
          continue;
        }
        if (stat.isFile()) {
          if (!shouldShowFileByExt(file)) {
            continue;
          }
          const fileItem = new ProjectItem(
            file,
            vscode.TreeItemCollapsibleState.None,
            'file',
            filePath
          );

          if (file === 'steps.yaml') {
            fileItem.contextValue = 'yaml stepsYaml';
            fileItem.command = {
              command: 'aiSocialScientist.viewStepsYaml',
              title: '查看步骤时间线',
              arguments: [{ filePath: filePath }]
            };
          }

          items.push(fileItem);
        }
      }
      return items;
    }

    // 实验运行结果分组
    if (element.type === 'experimentRunGroup') {
      const runDir = (element as any).runDir;
      if (!runDir || !fs.existsSync(runDir)) {
        return [];
      }
      const items: ProjectItem[] = [];

      // output.log（实验运行主日志）
      const outputLog = path.join(runDir, 'output.log');
      if (fs.existsSync(outputLog)) {
        const logItem = new ProjectItem(
          'output.log',
          vscode.TreeItemCollapsibleState.None,
          'file',
          outputLog
        );
        logItem.tooltip = 'Experiment log (output.log)';
        logItem.iconPath = makeThemeIcon('output', 'descriptionForeground');
        items.push(logItem);
      }

      // artifacts/（ask 等步骤产物）
      const artifactsDir = path.join(runDir, 'artifacts');
      if (fs.existsSync(artifactsDir) && fs.statSync(artifactsDir).isDirectory()) {
        const artifactsItem = new ProjectItem(
          'artifacts',
          vscode.TreeItemCollapsibleState.Collapsed,
          'file',
          artifactsDir
        );
        artifactsItem.tooltip = 'Run artifacts';
        artifactsItem.iconPath = makeThemeIcon('archive', 'charts.purple');
        items.push(artifactsItem);
      }

      // replay/_schema.json
      const replayDir = path.join(runDir, 'replay');
      const replaySchema = path.join(replayDir, '_schema.json');
      if (fs.existsSync(replaySchema)) {
        const item = new ProjectItem(
          localize('projectStructure.resultsDatabase'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'file',
          replayDir
        );

        if (element.hypothesisId && element.experimentId) {
          item.command = {
            command: 'aiSocialScientist.openReplay',
            title: localize('projectStructure.openReplay'),
            arguments: [{
              hypothesisId: element.hypothesisId,
              experimentId: element.experimentId,
              filePath: replayDir
            }]
          };
          item.contextValue = 'replayableDatabase';
        }

        items.push(item);
      }

      // pid.json
      const pidFile = path.join(runDir, 'pid.json');
      if (fs.existsSync(pidFile)) {
        try {
          const pidContent = fs.readFileSync(pidFile, 'utf-8');
          const pidData = JSON.parse(pidContent);
          const status = this.normalizeExperimentStatus(pidData.status);

          const pidItem = new ProjectItem(
            `${localize('projectStructure.experimentStatus')}: ${status}`,
            vscode.TreeItemCollapsibleState.None,
            'pidJson',
            pidFile
          );
          pidItem.iconPath = this.getExperimentStatusIcon(status);
          pidItem.tooltip = `${localize('projectStructure.experimentStatus')}: ${status}\nPID: ${pidData.pid || 'N/A'}\n${localize('projectStructure.startTime')}: ${pidData.start_time || 'N/A'}\n${localize('projectStructure.endTime')}: ${pidData.end_time || 'N/A'}`;
          pidItem.description = pidData.experiment_id || '';
          pidItem.contextValue = 'pidJson';
          pidItem.command = {
            command: 'aiSocialScientist.viewPidStatus',
            title: '查看运行状态',
            arguments: [{ filePath: pidFile }]
          };
          items.push(pidItem);
        } catch { void 0; }
      }

      // 其他可读产物（避免把大文件/缓存塞满）
      const known = new Set(['replay', 'trace', 'agents', 'experiment_results.json', 'pid.json', 'output.log', 'artifacts']);
      const maxBytes = 50 * 1024 * 1024; // 50MB
      const others = listDirEntriesSafe(runDir)
        .filter(name => !shouldHideFsEntry(name))
        .filter(name => !known.has(name))
        .map(name => ({ name, fullPath: path.join(runDir, name) }))
        .filter(({ name, fullPath }) => {
          const stat = safeStatSync(fullPath);
          if (!stat) {
            return false;
          }
          if (stat.isDirectory()) {
            return true;
          }
          if (!stat.isFile()) {
            return false;
          }
          if (stat.size > maxBytes) {
            return false;
          }
          return shouldShowFileByExt(name);
        })
        .sort((a, b) => a.name.localeCompare(b.name));

      for (const { name, fullPath } of others) {
        const stat = safeStatSync(fullPath);
        if (!stat) {
          continue;
        }
        const collapsible = stat.isDirectory()
          ? vscode.TreeItemCollapsibleState.Collapsed
          : vscode.TreeItemCollapsibleState.None;
        items.push(new ProjectItem(name, collapsible, 'file', fullPath));
      }

      return items;
    }

    // Presentation节点（分析报告）的子节点：显示所有假设目录
    if (element.type === 'presentation') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const presentationDir = path.join(workspacePath, 'presentation');
      const items: ProjectItem[] = [];

      if (fs.existsSync(presentationDir)) {
        // 读取目录，查找所有hypothesis_*目录
        const entries = fs.readdirSync(presentationDir);
        for (const entry of entries) {
          const fullPath = path.join(presentationDir, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isDirectory() && entry.startsWith('hypothesis_')) {
            // 提取假设ID，转换为友好显示名称
            const match = entry.match(/^hypothesis_(\d+)$/);

            const reportCount = countHypothesisPresentationReports(fullPath);

            const displayName = match
              ? `${localize('projectStructure.hypothesis')} ${match[1]}`
              : entry;
            const hypItem = new ProjectItem(
              displayName,
              vscode.TreeItemCollapsibleState.Collapsed,
              'presentationHypothesis',
              fullPath
            );
            if (reportCount > 0) {
              hypItem.description = localize('projectStructure.presentationReportsAvailable', reportCount);
            }
            items.push(hypItem);
          }
        }
      }

      return items;
    }

    // PresentationHypothesis：展示 hypothesis 根目录下的分析产物（harness 约定）
    if (element.type === 'presentationHypothesis' && element.filePath) {
      const items: ProjectItem[] = [];

      if (fs.existsSync(element.filePath) && fs.statSync(element.filePath).isDirectory()) {
        const hypothesisDir = element.filePath;
        const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
        const hasHypothesisLevel =
          presentationDirHasReports(hypothesisDir) ||
          ['data', 'charts', 'assets'].some((name) =>
            fs.existsSync(path.join(hypothesisDir, name))
          ) ||
          ['artifact_manifest.json', 'report_outline.json'].some((name) =>
            fs.existsSync(path.join(hypothesisDir, name))
          ) ||
          Boolean(resolveHypothesisHarnessStatePath(workspacePath, hypothesisDir));

        if (hasHypothesisLevel) {
          appendHypothesisPhaseProgress(items, workspacePath, hypothesisDir);
          appendPresentationReportTreeItems(
            items,
            collectPresentationReportFiles(hypothesisDir),
            hypothesisDir
          );
          appendPresentationOutputDirs(items, hypothesisDir);
        }
      }

      return items;
    }

    if (element.type === 'analysisPhaseGroup' && element.filePath) {
      return buildHypothesisPhaseStepItems(element.filePath);
    }

    if (element.type === 'synthesisPhaseGroup' && element.filePath) {
      const state = readHarnessStateFile(element.filePath);
      const release = state?.workspace_release;
      const status =
        release === 'ready'
          ? localize('projectStructure.phaseStatus.pass')
          : localize('projectStructure.phaseStatus.pending');
      const item = new ProjectItem(
        localize('projectStructure.analysisPhase.synthesis'),
        vscode.TreeItemCollapsibleState.None,
        'analysisPhaseStep'
      );
      item.description = status;
      item.iconPath =
        release === 'ready'
          ? new vscode.ThemeIcon('pass-filled', new vscode.ThemeColor('charts.green'))
          : new vscode.ThemeIcon('circle-outline', new vscode.ThemeColor('charts.yellow'));
      item.tooltip = `${localize('projectStructure.analysisPhase.synthesis')} — ${status}`;
      assignHarnessStatusCommand(item, element.filePath, 'synthesis', 'synthesis');
      return [item];
    }


    // Synthesis节点（综合报告）的子节点：显示所有综合报告文件
    if (element.type === 'synthesis') {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }
      const workspacePath = workspaceFolder.uri.fsPath;
      const synthesisDir = path.join(workspacePath, 'synthesis');
      const items: ProjectItem[] = [];

      if (fs.existsSync(synthesisDir)) {
        const synthesisStatePath = resolveSynthesisHarnessStatePath(workspacePath);
        if (synthesisStatePath) {
          const group = new ProjectItem(
            localize('projectStructure.synthesisProgress'),
            vscode.TreeItemCollapsibleState.Collapsed,
            'synthesisPhaseGroup',
            synthesisStatePath
          );
          group.iconPath = makeThemeIcon('list-tree', 'charts.green');
          items.push(group);
        }

        const entries = fs.readdirSync(synthesisDir);
        const shownReportPaths = new Set<string>();

        const synthesisReportFiles = collectSynthesisReportFiles(synthesisDir);
        for (const spec of REQUIRED_SYNTHESIS_REPORTS) {
          const p = synthesisReportFiles[spec.fileName];
          if (p) {
            shownReportPaths.add(p);
          }
        }
        appendRequiredBilingualReportTreeItems(
          items,
          REQUIRED_SYNTHESIS_REPORTS,
          synthesisReportFiles,
          synthesisDir
        );

        const pushLegacySynthesisReportItem = (
          label: string,
          filePath: string,
          kind: 'reportHtml' | 'reportMd'
        ) => {
          if (shownReportPaths.has(filePath)) {
            return;
          }
          shownReportPaths.add(filePath);
          const item = new ProjectItem(
            label,
            vscode.TreeItemCollapsibleState.None,
            kind,
            filePath
          );
          item.tooltip = workspaceRelativeTreeTooltip(workspacePath, filePath);
          if (kind === 'reportMd') {
            item.command = {
              command: 'markdown.showPreview',
              title: 'Open Preview',
              arguments: [vscode.Uri.file(filePath)]
            };
          } else {
            item.command = {
              command: 'aiSocialScientist.openHtmlReport',
              title: 'Open HTML Report',
              arguments: [vscode.Uri.file(filePath)]
            };
          }
          items.push(item);
        };

        const briefPath = path.join(synthesisDir, 'synthesis_brief.json');
        if (fs.existsSync(briefPath) && fs.statSync(briefPath).isFile()) {
          const briefItem = new ProjectItem(
            localize('projectStructure.synthesisBrief'),
            vscode.TreeItemCollapsibleState.None,
            'file',
            briefPath
          );
          briefItem.iconPath = makeThemeIcon('notebook', 'charts.blue');
          items.push(briefItem);
        }

        appendSynthesisOutputDirs(items, synthesisDir);

        // Legacy 时间戳命名：synthesis_report_YYYYMMDD_HHMMSS_(zh|en).(html|md)
        const reportGroups: { [key: string]: { [lang: string]: string } } = {};

        for (const entry of entries) {
          const fullPath = path.join(synthesisDir, entry);
          const stat = fs.statSync(fullPath);

          if (stat.isFile() && entry.startsWith('synthesis_report_')) {
            if (shownReportPaths.has(fullPath)) {
              continue;
            }
            const langMatch = entry.match(/^synthesis_report_([\d_]+)_(zh|en)\.(html|md)$/);
            const genericMatch = entry.match(/^synthesis_report_([\d_]+)\.(html|md)$/);

            if (langMatch) {
              const timestamp = langMatch[1];
              const lang = langMatch[2];
              const ext = langMatch[3];
              const key = `${timestamp}.${ext}`;

              if (!reportGroups[key]) {
                reportGroups[key] = {};
              }
              reportGroups[key][lang] = fullPath;
            } else if (genericMatch) {
              const timestamp = genericMatch[1];
              const ext = genericMatch[2];
              const key = `${timestamp}.${ext}`;

              if (!reportGroups[key]) {
                reportGroups[key] = {};
              }
              reportGroups[key]['generic'] = fullPath;
            }
          }
        }

        // 生成显示项：优先显示语言特定版本，如果没有则显示通用版本
        for (const [key, paths] of Object.entries(reportGroups)) {
          const dotIndex = key.lastIndexOf('.');
          if (dotIndex < 0) {
            continue;
          }
          const timestamp = key.slice(0, dotIndex);
          const ext = key.slice(dotIndex + 1);
          const isHtml = ext === 'html';

          if (isHtml) {
            if (paths.zh) {
              pushLegacySynthesisReportItem(timestamp, paths.zh, 'reportHtml');
            }
            if (paths.en) {
              pushLegacySynthesisReportItem(timestamp, paths.en, 'reportHtml');
            }
            if (!paths.zh && !paths.en && paths.generic) {
              pushLegacySynthesisReportItem(timestamp, paths.generic, 'reportHtml');
            }
          } else {
            if (paths.zh) {
              pushLegacySynthesisReportItem(timestamp, paths.zh, 'reportMd');
            }
            if (paths.en) {
              pushLegacySynthesisReportItem(timestamp, paths.en, 'reportMd');
            }
            if (!paths.zh && !paths.en && paths.generic) {
              pushLegacySynthesisReportItem(timestamp, paths.generic, 'reportMd');
            }
          }
        }
      }

      return items;
    }

    // ── paper-toolkit: 论文工作区展开 ──────────────────────
    if (element.type === 'paperWorkspace' && element.filePath) {
      return buildPaperWorkspaceChildren(element.filePath);
    }
    if (element.type === 'paperSections' && element.filePath) {
      return buildPaperSubdirFileItems(element.filePath);
    }
    if (element.type === 'paperFigures' && element.filePath) {
      return buildPaperSubdirFileItems(element.filePath);
    }
    if (element.type === 'paperFigureSpecs' && element.filePath) {
      return buildPaperSubdirFileItems(element.filePath);
    }
    if (element.type === 'paperTables' && element.filePath) {
      return buildPaperSubdirFileItems(element.filePath);
    }
    if (element.type === 'paperTableSpecs' && element.filePath) {
      return buildPaperSubdirFileItems(element.filePath);
    }
    if (element.type === 'paperCompileRuns' && element.filePath) {
      return buildPaperCompileRunsChildren(element.filePath);
    }
    if (element.type === 'paperCompileRun' && element.filePath) {
      return buildPaperSubdirFileItems(element.filePath);
    }
    if (element.type === 'paperReviews' && element.filePath) {
      return buildPaperReviewsChildren(element.filePath);
    }
    if (element.type === 'paperReviewRound' && element.filePath) {
      return buildPaperReviewRoundChildren(element.filePath);
    }
    if (element.type === 'paperLit' && element.filePath) {
      return buildPaperSubdirFileItems(element.filePath);
    }

    // ── paper-toolkit: 分析管线展开 ──────────────────────
    if (element.type === 'analysisWorkspace' && element.filePath) {
      return buildAnalysisWorkspaceChildren(element.filePath);
    }
    if (element.type === 'analysisHypothesis' && element.filePath) {
      return buildAnalysisHypothesisChildren(element.filePath);
    }
    if (element.type === 'analysisExperiment' && element.filePath) {
      return buildAnalysisExperimentChildren(element.filePath);
    }
    if (element.type === 'analysisEda' && element.filePath) {
      return buildPaperSubdirFileItems(element.filePath);
    }

    // 其他类型的节点没有子节点
    return [];
  }

  private buildProjectStatsMetricItems(workspacePath: string): ProjectItem[] {
    const overview = this.getProjectStats(workspacePath);
    if (!overview) {
      return [];
    }
    const completionRate =
      overview.totalExperiments > 0
        ? Math.round((overview.completedExperiments / overview.totalExperiments) * 100)
        : 0;
    const rows: ProjectItem[] = [];
    rows.push(
      new ProjectItem(
        localize(
          'projectStructure.experimentStats.lineDone',
          overview.completedExperiments,
          overview.totalExperiments,
          completionRate
        ),
        vscode.TreeItemCollapsibleState.None,
        'projectStatsMetric',
        undefined
      )
    );
    if (overview.runningExperiments > 0) {
      rows.push(
        new ProjectItem(
          localize('projectStructure.experimentStats.lineRun', overview.runningExperiments),
          vscode.TreeItemCollapsibleState.None,
          'projectStatsMetric',
          undefined
        )
      );
    }
    if (overview.failedExperiments > 0) {
      rows.push(
        new ProjectItem(
          localize('projectStructure.experimentStats.lineFailed', overview.failedExperiments),
          vscode.TreeItemCollapsibleState.None,
          'projectStatsMetric',
          undefined
        )
      );
    }
    if (overview.pendingExperiments > 0) {
      rows.push(
        new ProjectItem(
          localize('projectStructure.experimentStats.linePending', overview.pendingExperiments),
          vscode.TreeItemCollapsibleState.None,
          'projectStatsMetric',
          undefined
        )
      );
    }
    if (overview.unknownExperiments > 0) {
      rows.push(
        new ProjectItem(
          localize('projectStructure.experimentStats.lineUnknown', overview.unknownExperiments),
          vscode.TreeItemCollapsibleState.None,
          'projectStatsMetric',
          undefined
        )
      );
    }
    return rows;
  }

  /**
   * 获取项目统计概览
   */
  private getProjectStats(
    workspacePath: string,
  ): {
    label: string;
    description: string;
    tooltip: string;
    totalExperiments: number;
    completedExperiments: number;
    runningExperiments: number;
    failedExperiments: number;
    pendingExperiments: number;
    unknownExperiments: number;
  } | null {
    let totalExperiments = 0;
    let completedExperiments = 0;
    let runningExperiments = 0;
    let failedExperiments = 0;
    let unknownExperiments = 0;
    let trackedExperiments = 0;

    // 统计所有假设下的实验
    const hypothesisDirs = this.findDirectories(workspacePath, /^hypothesis_\d+$/);
    for (const hypDir of hypothesisDirs) {
      const experimentDirs = this.findDirectories(hypDir, /^experiment_\d+$/);
      totalExperiments += experimentDirs.length;

      for (const expDir of experimentDirs) {
        const pidFile = path.join(expDir, 'run', 'pid.json');
        if (!fs.existsSync(pidFile)) {
          continue;
        }
        trackedExperiments++;
        try {
          const pidContent = fs.readFileSync(pidFile, 'utf-8');
          const pidData = JSON.parse(pidContent);
          const status = this.normalizeExperimentStatus(pidData.status);
          if (status === 'completed') {
            completedExperiments++;
          } else if (status === 'running') {
            runningExperiments++;
          } else if (status === 'failed') {
            failedExperiments++;
          } else {
            unknownExperiments++;
          }
        } catch {
          unknownExperiments++;
        }
      }
    }

    if (totalExperiments === 0) {
      return null;
    }

    const pendingExperiments = Math.max(totalExperiments - trackedExperiments, 0);
    const completionRate = Math.round((completedExperiments / totalExperiments) * 100);

    const descriptionShort = this.formatExperimentProgressDescription({
      completedExperiments,
      totalExperiments,
      completionRate,
      runningExperiments,
      failedExperiments,
      pendingExperiments,
      unknownExperiments,
    });

    const tooltipLines: string[] = [
      localize('projectStructure.experimentStats.tooltipTitle'),
      localize(
        'projectStructure.experimentStats.compact',
        completedExperiments,
        totalExperiments,
        completionRate,
        runningExperiments,
        failedExperiments,
        pendingExperiments
      ),
      localize('projectStructure.experimentStats.completionRate', completionRate),
      localize('projectStructure.experimentStats.seeTopicHint'),
    ];
    if (unknownExperiments > 0) {
      tooltipLines.push(localize('projectStructure.experimentStats.unknown', unknownExperiments));
    }

    return {
      label: localize('projectStructure.experimentStats.label'),
      description: descriptionShort,
      tooltip: tooltipLines.join('\n'),
      totalExperiments,
      completedExperiments,
      runningExperiments,
      failedExperiments,
      pendingExperiments,
      unknownExperiments,
    };
  }

  private formatExperimentProgressDescription(stats: {
    completedExperiments: number;
    totalExperiments: number;
    completionRate: number;
    runningExperiments: number;
    failedExperiments: number;
    pendingExperiments: number;
    unknownExperiments: number;
  }): string {
    const barWidth = 8;
    const filled = Math.max(0, Math.min(barWidth, Math.round((stats.completionRate / 100) * barWidth)));
    const bar = `${'▰'.repeat(filled)}${'▱'.repeat(barWidth - filled)}`;
    const segments = [
      `${stats.completedExperiments}/${stats.totalExperiments}`,
      `${bar} ${stats.completionRate}%`,
    ];
    if (stats.runningExperiments > 0) {
      segments.push(localize('projectStructure.experimentStats.run', stats.runningExperiments));
    }
    if (stats.failedExperiments > 0) {
      segments.push(localize('projectStructure.experimentStats.failed', stats.failedExperiments));
    }
    if (stats.pendingExperiments > 0) {
      segments.push(localize('projectStructure.experimentStats.pending', stats.pendingExperiments));
    }
    if (stats.unknownExperiments > 0) {
      segments.push(localize('projectStructure.experimentStats.unknown', stats.unknownExperiments));
    }
    return segments.join(' · ');
  }

  private normalizeExperimentStatus(status: unknown): 'completed' | 'running' | 'failed' | 'pending' | 'unknown' {
    if (typeof status !== 'string') {
      return 'unknown';
    }
    const normalized = status.trim().toLowerCase();
    if (normalized === 'completed' || normalized === 'running' || normalized === 'failed') {
      return normalized;
    }
    if (normalized === 'pending' || normalized === 'queued' || normalized === 'created') {
      return 'pending';
    }
    return 'unknown';
  }

  private getExperimentStatusIcon(status: 'completed' | 'running' | 'failed' | 'pending' | 'unknown'): vscode.ThemeIcon {
    switch (status) {
      case 'completed':
        return makeThemeIcon('pass-filled', 'charts.green');
      case 'running':
        return makeThemeIcon('sync', 'charts.yellow');
      case 'failed':
        return makeThemeIcon('error', 'charts.red');
      case 'pending':
        return makeThemeIcon('clock', 'descriptionForeground');
      default:
        return makeThemeIcon('question', 'descriptionForeground');
    }
  }

  private getExperimentStatusLabel(
    status: 'completed' | 'running' | 'failed' | 'pending' | 'unknown',
    isChinese: boolean
  ): string {
    if (isChinese) {
      if (status === 'completed') { return '已完成'; }
      if (status === 'running') { return '运行中'; }
      if (status === 'failed') { return '失败'; }
      if (status === 'pending') { return '待运行'; }
      return '未知';
    }
    if (status === 'completed') { return 'completed'; }
    if (status === 'running') { return 'running'; }
    if (status === 'failed') { return 'failed'; }
    if (status === 'pending') { return 'pending'; }
    return 'unknown';
  }

  /**
   * 查找符合模式的目录
   * 
   * 辅助方法，用于查找符合特定命名模式的目录。
   * 例如：查找所有hypothesis_12345格式的目录。
   * 
   * @param parentDir - 父目录路径
   * @param pattern - 正则表达式，用于匹配目录名
   * @returns 匹配的目录路径数组（已排序）
   */
  private findDirectories(parentDir: string, pattern: RegExp): string[] {
    // 如果父目录不存在，返回空数组
    if (!fs.existsSync(parentDir)) {
      return [];
    }

    // 读取目录内容，忽略mineru_output文件夹
    return fs.readdirSync(parentDir)
      .filter(name => {
        // 忽略mineru_output文件夹
        if (name === 'mineru_output') {
          return false;
        }
        const fullPath = path.join(parentDir, name);
        // 检查是否为目录且名称匹配正则表达式
        return fs.statSync(fullPath).isDirectory() && pattern.test(name);
      })
      .map(name => path.join(parentDir, name))  // 转换为完整路径
      .sort();  // 排序，确保顺序一致
  }

  /**
   * 初始化研究项目
   * 
   * 创建一个新的研究项目，包括：
   * 1. 创建TOPIC.md文件
   * 2. 创建papers目录
   * 
   * 这个方法通常由命令调用（如"Initialize Research Project"命令）。
   * 
   * @param topic - 研究话题的标题
   */
  async initProject(topic: string): Promise<void> {
    // 获取工作区文件夹
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('projectStructure.noWorkspace'));
      return;
    }

    // init() 是幂等的，所有写入都有 existsSync 守卫，直接执行

    try {
      // 使用进度提示显示初始化过程
      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('workspaceInit.initializing'),
          cancellable: false,
        },
        async (progress) => {
          // 使用本地 WorkspaceManager 初始化，传递 progress 对象
          return await this.workspaceManager.init({ topic, progress });
        }
      );

      if (result.success) {
        vscode.window.showInformationMessage(localize('workspaceInit.success', topic));
      } else {
        // 失败时显示错误消息
        vscode.window.showErrorMessage(result.message);
      }
    } catch (error: any) {
      // 异常时也显示错误消息
      vscode.window.showErrorMessage(localize('projectStructure.initWorkspace.failed', error.message || error));
    }

    // 刷新视图，显示新创建的文件和目录
    this.refresh();
  }

  /**
   * 扫描自定义模块（供后续树节点或 API 集成使用）
   */
  async scanCustomModules(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('customModules.noWorkspace'));
      return;
    }

    const workspacePath = workspaceFolder.uri.fsPath;

    try {
      const response = await this.apiClient.scanCustomModules({
        workspace_path: workspacePath
      });

      if (response.success) {
        const listResponse = await this.apiClient.listCustomModules();

        if (listResponse.success) {
          this.customModulesCache.agents = listResponse.agents.filter(a => a.is_custom);
          this.customModulesCache.envs = listResponse.envs.filter(e => e.is_custom);

          this.log(`Custom modules scan completed: ${this.customModulesCache.agents.length} agents, ${this.customModulesCache.envs.length} envs`);
          this.refresh();
        }
      } else {
        vscode.window.showErrorMessage(localize('customModules.scanFailed', response.message || 'Unknown error'));
      }
    } catch (error: any) {
      this.log(`Scan custom modules failed: ${error}`);
      vscode.window.showErrorMessage(localize('customModules.scanFailed', error.message || error));
    }
  }

  /**
   * 测试自定义模块
   */
  async testCustomModules(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('customModules.noWorkspace'));
      return;
    }

    const workspacePath = workspaceFolder.uri.fsPath;

    try {
      vscode.window.showInformationMessage(localize('customModules.testing'));

      const response = await this.apiClient.testCustomModules({
        workspace_path: workspacePath
      });

      if (response.success) {
        vscode.window.showInformationMessage(
          localize('customModules.testSuccess')
        );

        // 如果有测试输出，显示在输出通道
        if (response.test_output) {
          this.outputChannel.show();
          this.outputChannel.appendLine('=== Custom Modules Test Output ===');
          this.outputChannel.appendLine(response.test_output);
        }
      } else {
        vscode.window.showErrorMessage(
          localize('customModules.testFailed', response.error || 'Unknown error')
        );
      }
    } catch (error: any) {
      this.log(`Test custom modules failed: ${error}`);
      vscode.window.showErrorMessage(localize('customModules.testFailed', error.message || error));
    }
  }

  /**
   * 检查工作区目录结构健康状态
   * @returns 工作区健康状态信息
   */
  checkWorkspaceHealth(workspacePath: string): {
    isHealthy: boolean;
    missingItems: string[];
    issues: string[];
  } {
    const missingItems: string[] = [];
    const issues: string[] = [];

    // 必需的目录
    const requiredDirs = [
      'papers',
      'user_data',
      'datasets',
      'custom',
      'custom/agents',
      'custom/envs',
      '.agentsociety',
      '.claude',
      '.claude/skills'
    ];

    // 必需的文件
    const requiredFiles = [
      'TOPIC.md',
      'CLAUDE.md',
      'AGENTS.md',
      '.env',
      'papers/literature_index.json',
      '.agentsociety/prefill_params.json'
    ];

    // 检查目录
    for (const dir of requiredDirs) {
      const dirPath = path.join(workspacePath, dir);
      if (!fs.existsSync(dirPath)) {
        missingItems.push(`${dir}/`);
      }
    }

    // 检查文件
    for (const file of requiredFiles) {
      const filePath = path.join(workspacePath, file);
      if (!fs.existsSync(filePath)) {
        missingItems.push(file);
      }
    }

    // 检查custom目录中是否有示例文件（仅作为警告）
    const customAgentsDir = path.join(workspacePath, 'custom', 'agents');
    if (fs.existsSync(customAgentsDir)) {
      const agents = fs.readdirSync(customAgentsDir);
      if (agents.length === 0 || agents.every(f => f.startsWith('__') || f === 'examples')) {
        issues.push('custom/agents/ 目录为空或只有示例文件');
      }
    }

    return {
      isHealthy: missingItems.length === 0,
      missingItems,
      issues
    };
  }

  /**
   * 修复工作区目录结构
   */
  async fixWorkspace(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('customModules.noWorkspace'));
      return;
    }

    const workspacePath = workspaceFolder.uri.fsPath;
    const health = this.checkWorkspaceHealth(workspacePath);

    if (health.isHealthy) {
      vscode.window.showInformationMessage(localize('workspaceFix.healthy'));
      return;
    }

    try {
      const result = await this.workspaceManager.init({ topic: 'Fix Workspace' });

      if (result.success) {
        this.log(`Workspace fixed: created ${result.filesCreated?.length || 0} items`);
        this.refresh();
      } else {
        vscode.window.showErrorMessage(localize('workspaceFix.failed', result.message));
      }
    } catch (error: any) {
      this.log(`Fix workspace failed: ${error}`);
      vscode.window.showErrorMessage(localize('workspaceFix.failed', error.message || error));
    }
  }

  /**
   * Update extension-bundled skills by re-syncing to workspace .claude/skills/
   * AgentSociety skills (incl. analysis support under agentsociety-analysis/support/) and Office skills.
   */
  syncBundledClaudeSkillToWorkspace(skillName: string): { success: boolean; message: string } {
    return this.workspaceManager.syncSingleBundledSkill(skillName);
  }

  /**
   * Expose the SkillVersionManager so the skill marketplace webview / commands
   * can list/apply/snapshot skill versions without re-creating the manager.
   */
  getSkillVersionManager() {
    return this.workspaceManager.getVersionManager();
  }

  getWorkspaceManager() {
    return this.workspaceManager;
  }

  async updateExtensionSkills(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      vscode.window.showErrorMessage(localize('projectStructure.noWorkspace'));
      return;
    }

    // Declare in outer scope to be accessible in both steps
    let syncResult: { success: boolean; message: string; created: string[]; synced: string[] };

    // 启动批量操作模式，暂停文件监视器的自动刷新
    this.batchOperationInProgress = true;

    try {
      // Step 1: Sync AgentSociety extension skills
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('projectStructure.updateSkills.step1'),
          cancellable: false
        },
        async (progress) => {
          // Immediately report progress to ensure notification shows up
          progress.report({ increment: 0 });

          // Yield to event loop so progress notification can render
          await new Promise(resolve => setTimeout(resolve, 10));

          // Now execute the synchronous operation
          syncResult = this.workspaceManager.syncClaudeCodeResources();

          if (!syncResult.success) {
            throw new Error(syncResult.message);
          }

          progress.report({ increment: 50 });
          this.outputChannel.appendLine(`[updateExtensionSkills] Synced ${syncResult.synced.length} AgentSociety skills`);
        }
      );

      // Step 2: Office document skills (pdf, docx, xlsx, pptx)
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: localize('projectStructure.updateSkills.step2'),
          cancellable: false
        },
        async (progress) => {
          progress.report({ increment: 50 });
          await new Promise(resolve => setTimeout(resolve, 10));

          const officeSkillsResult = await this.workspaceManager.copyOfficialOfficeSkills();

          const agentSocietyCount = syncResult.synced.length;
          const officeSkillsCount = officeSkillsResult.downloaded.length;
          const totalSkills = agentSocietyCount + officeSkillsCount;

          if (officeSkillsCount === 0) {
            const message = localize('projectStructure.updateSkills.partialIssues')
              + localize('projectStructure.updateSkills.agentsociety', agentSocietyCount)
              + localize('projectStructure.updateSkills.officeFailed')
              + `⚠️ ${officeSkillsResult.message}\n\n`
              + localize('projectStructure.updateSkills.checkExtension');
            const result = await vscode.window.showWarningMessage(
              message,
              localize('projectStructure.updateSkills.viewDetails'),
              localize('projectStructure.updateSkills.close')
            );
            if (result === localize('projectStructure.updateSkills.viewDetails')) {
              this.workspaceManager.showOutput();
            }
          } else if (!officeSkillsResult.success && officeSkillsResult.downloaded.length > 0) {
            this.log(
              `Skills updated: ${agentSocietyCount} agentsociety, ${officeSkillsCount} office (partial: ${officeSkillsResult.message})`
            );
          } else {
            this.log(
              `Skills updated: ${agentSocietyCount} agentsociety, ${officeSkillsCount} office, ${totalSkills} total`
            );
          }

          progress.report({ increment: 100 });

          this.refresh();
        }
      );

    } catch (error: any) {
      const errorMessage = localize('projectStructure.updateSkills.failed', error.message || error);
      this.outputChannel.appendLine(`[updateExtensionSkills] Error: ${error.stack || error}`);

      // Offer to view output for debugging
      const viewOutput = await vscode.window.showErrorMessage(
        errorMessage,
        localize('projectStructure.updateSkills.viewOutput'),
        localize('projectStructure.updateSkills.close')
      );

      if (viewOutput === localize('projectStructure.updateSkills.viewOutput')) {
        this.workspaceManager.showOutput();
      }
    } finally {
      // 结束批量操作模式，恢复文件监视器的自动刷新
      this.batchOperationInProgress = false;

      // 批量操作完成后，手动触发一次刷新以显示所有更改
      this.refresh();
    }
  }

  /**
   * 打开 Skill 文档（SKILL.md）
   *
   * 对于内置 skill，文件路径在 Python 包内，前端无法直接访问，
   * 因此需要通过 API 获取内容并创建临时文件显示。
   * 对于自定义 skill，直接打开工作区中的文件。
   *
   * @param skillName - Skill 名称
   * @param skillPath - Skill 目录路径
   * @param isBuiltin - 是否为内置 skill
   */
  async openAgentSkillDoc(
    skillName: string,
    skillPath: string,
    isBuiltin: boolean,
    skillId?: string
  ): Promise<void> {
    // 对于内置 skill，始终通过 API 获取内容（路径在 Python 包内，前端无法直接访问）
    if (isBuiltin) {
      await this._openBuiltinSkillDoc(skillName, skillId ?? `built-in@${skillName}`);
      return;
    }

    // 对于自定义 skill，尝试直接打开文件
    const skillMdPath = path.join(skillPath, 'SKILL.md');
    if (fs.existsSync(skillMdPath) && fs.statSync(skillMdPath).isFile()) {
      const uri = vscode.Uri.file(skillMdPath);
      await vscode.commands.executeCommand('markdown.showPreview', uri);
      return;
    }

    // 如果文件不存在，也尝试通过 API 获取
    await this._openBuiltinSkillDoc(skillName, skillId ?? `custom@${skillName}`);
  }

  /**
   * 通过 API 获取 skill 文档内容并显示
   */
  private async _openBuiltinSkillDoc(skillName: string, skillId: string): Promise<void> {
    try {
      const response = await this.apiClient.getAgentSkillInfo(skillId);
      if (response.success && response.skill_md && response.skill_md.trim()) {
        // 创建临时文件显示内容
        const tempDir = path.join(this.context.globalStorageUri.fsPath, 'skill-docs');
        if (!fs.existsSync(tempDir)) {
          fs.mkdirSync(tempDir, { recursive: true });
        }

        const tempFilePath = path.join(tempDir, `${skillName}.md`);
        fs.writeFileSync(tempFilePath, response.skill_md, 'utf-8');

        const uri = vscode.Uri.file(tempFilePath);
        await vscode.commands.executeCommand('markdown.showPreview', uri);
      } else {
        vscode.window.showWarningMessage(localize('extension.skill.noDoc', skillName));
      }
    } catch (error: any) {
      vscode.window.showErrorMessage(localize('extension.skill.openDocFailed'));
    }
  }
}

// ── paper-toolkit sidebar helpers (module-level) ─────────────

function buildPaperWorkspaceChildren(paperDir: string): ProjectItem[] {
  const items: ProjectItem[] = [];
  const shownPaths = new Set<string>();

  const pushPaperFile = (
    relName: string,
    labelKey: string,
    icon: string,
    iconColor?: string,
    description?: string
  ): boolean => {
    const fullPath = path.join(paperDir, relName);
    if (!fs.existsSync(fullPath) || !safeStatSync(fullPath)?.isFile()) {
      return false;
    }
    if (shownPaths.has(fullPath)) {
      return false;
    }
    shownPaths.add(fullPath);
    const item = new ProjectItem(
      localize(labelKey),
      vscode.TreeItemCollapsibleState.None,
      'paperArtifact',
      fullPath
    );
    item.iconPath = makeThemeIcon(icon, iconColor);
    if (description) {
      item.description = description;
    }
    items.push(item);
    return true;
  };

  // 1) Deliverables users open most
  pushPaperFile('main.pdf', 'projectStructure.paperMainPdf', 'file-pdf', 'charts.red');
  pushPaperFile('main.tex', 'projectStructure.paperMainTex', 'file-code', 'charts.green');
  const refsPath = path.join(paperDir, 'refs.bib');
  if (fs.existsSync(refsPath)) {
    let bibDesc: string | undefined;
    try {
      const raw = fs.readFileSync(refsPath, 'utf-8');
      const bibItemCount = (raw.match(/^@\w+\{/gm) || []).length;
      if (bibItemCount > 0) {
        bibDesc = localize('projectStructure.paperBib.count', bibItemCount);
      }
    } catch { /* ignore */ }
    pushPaperFile('refs.bib', 'projectStructure.paperBib', 'list-tree', 'charts.yellow', bibDesc);
  }
  if (!pushPaperFile('venue.yaml', 'projectStructure.paperVenue', 'globe', 'charts.blue')) {
    pushPaperFile('paper_meta.yaml', 'projectStructure.paperVenue', 'globe', 'charts.blue');
  }

  // 2) Artifacts with dedicated PaperArtifactViewer / Yaml viewers
  type ViewerSpec = { name: string; labelKey: string; icon: string; iconColor?: string };
  const viewerArtifacts: ViewerSpec[] = [
    { name: 'state/paper_state.yaml', labelKey: 'projectStructure.paperState', icon: 'book', iconColor: 'charts.purple' },
    { name: 'paper_meta.yaml', labelKey: 'projectStructure.paperState', icon: 'book', iconColor: 'charts.purple' },
    { name: 'storyline_map.json', labelKey: 'projectStructure.analysisStoryline', icon: 'symbol-file', iconColor: 'charts.purple' },
    { name: 'claim_ledger.json', labelKey: 'projectStructure.analysisClaims', icon: 'checklist', iconColor: 'charts.green' },
    { name: 'evidence_backlog.json', labelKey: 'projectStructure.evidenceGraph', icon: 'graph', iconColor: 'charts.blue' },
    { name: 'figure_argument_map.json', labelKey: 'projectStructure.paperFigureArgMap', icon: 'graph', iconColor: 'charts.orange' },
    { name: 'research_pack.json', labelKey: 'projectStructure.researchPack', icon: 'archive', iconColor: 'charts.orange' },
    { name: 'human_gates.yaml', labelKey: 'projectStructure.paperHumanGates', icon: 'feedback', iconColor: 'charts.red' },
  ];
  const viewerLabels = new Set<string>();
  for (const spec of viewerArtifacts) {
    if (viewerLabels.has(spec.labelKey)) {
      continue;
    }
    if (pushPaperFile(spec.name, spec.labelKey, spec.icon, spec.iconColor)) {
      viewerLabels.add(spec.labelKey);
    }
  }

  // 3) Primary content directories (no specs/lit/state — those are pipeline internals)
  const primarySubDirs: { name: string; type: ProjectItem['type']; labelKey: string }[] = [
    { name: 'sections', type: 'paperSections', labelKey: 'projectStructure.paperSections' },
    { name: 'figures', type: 'paperFigures', labelKey: 'projectStructure.paperFigures' },
    { name: 'tables', type: 'paperTables', labelKey: 'projectStructure.paperTables' },
    { name: 'compile_runs', type: 'paperCompileRuns', labelKey: 'projectStructure.paperCompileRuns' },
    { name: 'reviews', type: 'paperReviews', labelKey: 'projectStructure.paperReviews' },
  ];
  const paperSubIconMap: Record<string, string> = {
    paperSections: 'symbol-file',
    paperFigures: 'file-media',
    paperTables: 'table',
    paperCompileRuns: 'output',
    paperReviews: 'feedback',
  };
  for (const sub of primarySubDirs) {
    const fullPath = path.join(paperDir, sub.name);
    if (!fs.existsSync(fullPath) || !safeStatSync(fullPath)?.isDirectory()) {
      continue;
    }
    let entryCount = 0;
    let description: string | undefined;
    if (sub.type === 'paperReviews') {
      const rounds = listReviewRoundDirs(fullPath);
      entryCount = rounds.length;
      if (rounds.length > 0) {
        const isZh = isExtensionZh();
        description = roundTreeDescription(rounds[0], isZh);
      }
    } else {
      try {
        entryCount = listDirEntriesSafe(fullPath).filter(
          (e) => !shouldHideFsEntry(e) && (safeStatSync(path.join(fullPath, e))?.isDirectory() || shouldShowUserFacingArtifact(e))
        ).length;
      } catch {
        continue;
      }
    }
    if (entryCount === 0) {
      continue;
    }
    const childItem = new ProjectItem(
      localize(sub.labelKey),
      vscode.TreeItemCollapsibleState.Collapsed,
      sub.type,
      fullPath
    );
    childItem.iconPath = makeThemeIcon(paperSubIconMap[sub.type] || 'folder', 'charts.purple');
    childItem.description = description || `${entryCount}`;
    items.push(childItem);
  }

  return items;
}

function recommendationIconColor(recommendation?: string, meanScore?: number): string {
  const key = (recommendation || '').toLowerCase().replace(/[\s-]+/g, '_');
  if (['accept', 'strong_accept', 'weak_accept', 'findings', 'minor_revision'].includes(key)) {
    return 'charts.green';
  }
  if (['borderline', 'borderline_accept', 'revise_and_resubmit', 'major_revision'].includes(key)) {
    return 'charts.yellow';
  }
  if (['reject', 'strong_reject', 'weak_reject'].includes(key)) {
    return 'charts.red';
  }
  const tone = scoreTone(meanScore);
  if (tone === 'good') {
    return 'charts.green';
  }
  if (tone === 'mid') {
    return 'charts.yellow';
  }
  if (tone === 'bad') {
    return 'charts.red';
  }
  return 'charts.purple';
}

function buildPaperReviewsChildren(reviewsDir: string): ProjectItem[] {
  const items: ProjectItem[] = [];
  const rounds = listReviewRoundDirs(reviewsDir);
  const isZh = isExtensionZh();
  for (const round of rounds) {
    // Prefer round_id; avoid "iclr-r1 · ICLR" duplication when venue already in id
    const label =
      round.venue && !round.roundId.toLowerCase().includes(round.venue.toLowerCase())
        ? `${round.roundId} · ${round.venue.toUpperCase()}`
        : round.roundId;
    const item = new ProjectItem(
      label,
      vscode.TreeItemCollapsibleState.Collapsed,
      'paperReviewRound',
      round.dirPath
    );
    item.description = roundTreeDescription(round, isZh);
    item.tooltip = [
      round.dirPath,
      isZh
        ? `展示分：${typeof round.displayScore === 'number' ? round.displayScore.toFixed(1) : '—'}（${round.scoreSource}）`
        : `Display: ${typeof round.displayScore === 'number' ? round.displayScore.toFixed(1) : '—'} (${round.scoreSource})`,
      isZh
        ? `建议：${recommendationLabel(round.displayRecommendation, true)}`
        : `Recommendation: ${recommendationLabel(round.displayRecommendation, false)}`,
      round.hasMetaReview
        ? isZh
          ? '已有 MetaReview'
          : 'MetaReview present'
        : isZh
          ? '尚无 MetaReview'
          : 'No MetaReview yet',
    ].join('\n');
    item.iconPath = makeThemeIcon(
      'comment-discussion',
      recommendationIconColor(round.displayRecommendation, round.displayScore)
    );
    items.push(item);
  }
  return items;
}

function buildPaperReviewRoundChildren(roundDir: string): ProjectItem[] {
  const items: ProjectItem[] = [];
  const round = loadReviewRoundSummary(roundDir);
  if (!round) {
    return items;
  }
  const isZh = isExtensionZh();

  if (round.metaReviewPath && fs.existsSync(round.metaReviewPath)) {
    const metaItem = new ProjectItem(
      isZh ? 'MetaReview（裁决）' : 'MetaReview',
      vscode.TreeItemCollapsibleState.None,
      'paperReviewRound',
      round.dirPath
    );
    // Reuse round path so click opens round summary (meta-first)
    metaItem.command = {
      command: 'aiSocialScientist.viewPaperReview',
      title: localize('extension.viewPaperReview.commandTitle'),
      arguments: [round.dirPath],
    };
    metaItem.contextValue = 'paperReviewRound';
    metaItem.description = round.hasMetaReview
      ? roundTreeDescription(round, isZh)
      : isZh
        ? '未完成'
        : 'incomplete';
    metaItem.iconPath = makeThemeIcon(
      'verified',
      recommendationIconColor(round.displayRecommendation, round.displayScore)
    );
    metaItem.tooltip = round.metaReviewPath;
    items.push(metaItem);
  }

  for (const reviewer of round.reviewers) {
    const item = new ProjectItem(
      reviewer.reviewerId,
      vscode.TreeItemCollapsibleState.None,
      'paperReviewer',
      reviewer.filePath
    );
    item.description = reviewerTreeDescription(reviewer, isZh);
    item.tooltip = [
      reviewer.filePath,
      isZh
        ? `分数：${reviewer.overall?.value ?? '—'} ${reviewer.overall?.label ? `（${reviewer.overall.label}）` : ''}`
        : `Score: ${reviewer.overall?.value ?? '—'} ${reviewer.overall?.label ? `(${reviewer.overall.label})` : ''}`,
      isZh
        ? `建议：${recommendationLabel(reviewer.recommendation, true)}`
        : `Recommendation: ${recommendationLabel(reviewer.recommendation, false)}`,
    ].join('\n');
    const n =
      typeof reviewer.overall?.value === 'number'
        ? reviewer.overall.value
        : Number(reviewer.overall?.value);
    item.iconPath = makeThemeIcon(
      'person',
      recommendationIconColor(
        reviewer.recommendation,
        Number.isFinite(n) ? n : undefined
      )
    );
    items.push(item);
  }

  return items;
}

function buildPaperSubdirFileItems(dirPath: string): ProjectItem[] {
  const items: ProjectItem[] = [];
  if (!fs.existsSync(dirPath)) { return items; }

  const entries = listDirEntriesSafe(dirPath).filter(e => !shouldHideFsEntry(e));
  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry);
    const stat = safeStatSync(fullPath);
    if (!stat) { continue; }
    if (stat.isDirectory()) {
      const subItems = listDirEntriesSafe(fullPath).filter(
        (e) => !shouldHideFsEntry(e) && shouldShowUserFacingArtifact(e)
      );
      if (subItems.length > 0) {
        const dirItem = new ProjectItem(entry, vscode.TreeItemCollapsibleState.Collapsed, 'analysisEda', fullPath);
        dirItem.iconPath = makeThemeIcon('folder', 'charts.blue');
        items.push(dirItem);
      }
    } else if (shouldShowUserFacingArtifact(entry)) {
      items.push(new ProjectItem(entry, vscode.TreeItemCollapsibleState.None, 'paperArtifact', fullPath));
    }
  }
  return items;
}

function buildPaperCompileRunsChildren(compileRunsDir: string): ProjectItem[] {
  const items: ProjectItem[] = [];
  if (!fs.existsSync(compileRunsDir)) { return items; }

  const entries = listDirEntriesSafe(compileRunsDir).filter(e => !shouldHideFsEntry(e));
  // Sort run directories (r1, r2, ...) in reverse order (latest first)
  const runDirs = entries
    .filter(e => /^r\d+$/.test(e))
    .sort((a, b) => {
      const na = parseInt(a.slice(1), 10);
      const nb = parseInt(b.slice(1), 10);
      return nb - na;
    });

  for (const runName of runDirs) {
    const runPath = path.join(compileRunsDir, runName);
    if (!fs.statSync(runPath).isDirectory()) { continue; }

    const item = new ProjectItem(runName, vscode.TreeItemCollapsibleState.Collapsed, 'paperCompileRun', runPath);
    item.iconPath = makeThemeIcon('file-pdf', 'charts.orange');

    // Check for compiled PDF and show status
    const pdfPath = path.join(runPath, 'main.pdf');
    if (fs.existsSync(pdfPath)) {
      item.description = 'PDF';
    }

    // Read run.json for status
    const runJsonPath = path.join(runPath, 'run.json');
    if (fs.existsSync(runJsonPath)) {
      try {
        const runData = JSON.parse(fs.readFileSync(runJsonPath, 'utf-8'));
        if (runData.success === true) {
          item.iconPath = makeThemeIcon('pass-filled', 'charts.green');
        } else if (runData.success === false) {
          item.iconPath = makeThemeIcon('error', 'charts.red');
        }
      } catch { /* ignore */ }
    }

    items.push(item);
  }
  return items;
}

function buildAnalysisWorkspaceChildren(analysisDir: string): ProjectItem[] {
  const items: ProjectItem[] = [];
  if (!fs.existsSync(analysisDir)) { return items; }

  const entries = listDirEntriesSafe(analysisDir).filter(e => !shouldHideFsEntry(e));
  for (const entry of entries) {
    const fullPath = path.join(analysisDir, entry);
    const stat = safeStatSync(fullPath);
    if (!stat || !stat.isDirectory()) { continue; }

    if (/^hypothesis_\d+$/.test(entry)) {
      const match = entry.match(/^hypothesis_(\d+)$/);
      const displayName = match
        ? `${localize('projectStructure.hypothesis')} ${match[1]}`
        : entry;
      const hypItem = new ProjectItem(
        displayName,
        vscode.TreeItemCollapsibleState.Collapsed,
        'analysisHypothesis',
        fullPath
      );
      hypItem.iconPath = makeThemeIcon('lightbulb', 'charts.purple');
      // Count experiments inside
      try {
        const expEntries = listDirEntriesSafe(fullPath).filter(e => !shouldHideFsEntry(e) && /^experiment_\d+$/.test(e));
        if (expEntries.length > 0) {
          hypItem.description = `${expEntries.length} experiments`;
        }
      } catch { /* ignore */ }
      items.push(hypItem);
    } else if (entry === 'synthesis') {
      // Show synthesis_brief.json files directly
      const synEntries = listDirEntriesSafe(fullPath).filter(e => !shouldHideFsEntry(e));
      for (const synEntry of synEntries) {
        const synHypPath = path.join(fullPath, synEntry);
        if (!fs.statSync(synHypPath).isDirectory()) { continue; }
        const briefPath = path.join(synHypPath, 'synthesis_brief.json');
        if (fs.existsSync(briefPath)) {
          const synItem = new ProjectItem(
            `${localize('projectStructure.analysisSynthesis')} — ${synEntry}`,
            vscode.TreeItemCollapsibleState.None,
            'paperArtifact',
            briefPath
          );
          synItem.iconPath = makeThemeIcon('notebook', 'charts.purple');
          items.push(synItem);
        }
      }
    }
  }
  return items;
}

function buildAnalysisHypothesisChildren(hypothesisDir: string): ProjectItem[] {
  const items: ProjectItem[] = [];
  if (!fs.existsSync(hypothesisDir)) { return items; }

  const entries = listDirEntriesSafe(hypothesisDir).filter(e => !shouldHideFsEntry(e));
  for (const entry of entries) {
    const fullPath = path.join(hypothesisDir, entry);
    const stat = safeStatSync(fullPath);
    if (!stat || !stat.isDirectory()) { continue; }

    if (/^experiment_\d+$/.test(entry)) {
      const match = entry.match(/^experiment_(\d+)$/);
      const displayName = match
        ? `${localize('projectStructure.analysisExperiment')} ${match[1]}`
        : entry;
      const expItem = new ProjectItem(
        displayName,
        vscode.TreeItemCollapsibleState.Collapsed,
        'analysisExperiment',
        fullPath
      );
      expItem.iconPath = makeThemeIcon('flame', 'charts.orange');
      // Check for claims.json
      if (fs.existsSync(path.join(fullPath, 'claims.json'))) {
        try {
          const claimsData = JSON.parse(fs.readFileSync(path.join(fullPath, 'claims.json'), 'utf-8'));
          const claimCount = Array.isArray(claimsData) ? claimsData.length : 0;
          if (claimCount > 0) {
            expItem.description = `${claimCount} claims`;
          }
        } catch { /* ignore */ }
      }
      items.push(expItem);
    }
  }
  return items;
}

function buildAnalysisExperimentChildren(experimentDir: string): ProjectItem[] {
  const items: ProjectItem[] = [];
  if (!fs.existsSync(experimentDir)) { return items; }

  // Special files with labels and icons
  const specialFiles: { name: string; labelKey: string; icon: string; iconColor?: string }[] = [
    { name: 'claims.json', labelKey: 'projectStructure.analysisClaims', icon: 'checklist', iconColor: 'charts.green' },
    { name: 'report_context.md', labelKey: 'projectStructure.analysisContext', icon: 'note', iconColor: 'charts.blue' },
    { name: 'evidence_index.json', labelKey: 'projectStructure.evidenceGraph', icon: 'graph', iconColor: 'charts.blue' },
  ];

  for (const spec of specialFiles) {
    const fullPath = path.join(experimentDir, spec.name);
    if (!fs.existsSync(fullPath)) { continue; }
    const item = new ProjectItem(
      localize(spec.labelKey),
      vscode.TreeItemCollapsibleState.None,
      'paperArtifact',
      fullPath
    );
    item.iconPath = makeThemeIcon(spec.icon, spec.iconColor);
    items.push(item);
  }

  // Generic config/state files
  const genericFiles = ['analysis_plan.yaml', 'state.yaml', 'config.yaml'];
  for (const name of genericFiles) {
    const fullPath = path.join(experimentDir, name);
    if (!fs.existsSync(fullPath)) { continue; }
    items.push(new ProjectItem(name, vscode.TreeItemCollapsibleState.None, 'paperArtifact', fullPath));
  }

  // EDA directory
  const edaDir = path.join(experimentDir, 'eda');
  if (fs.existsSync(edaDir) && fs.statSync(edaDir).isDirectory()) {
    try {
      const edaEntries = listDirEntriesSafe(edaDir).filter(e => !shouldHideFsEntry(e));
      if (edaEntries.length > 0) {
        const edaItem = new ProjectItem(
          localize('projectStructure.analysisEda'),
          vscode.TreeItemCollapsibleState.Collapsed,
          'analysisEda',
          edaDir
        );
        edaItem.iconPath = makeThemeIcon('graph', 'charts.blue');
        items.push(edaItem);
      }
    } catch { /* ignore */ }
  }

  return items;
}
