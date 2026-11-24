/**
 * Built-in skill manager.
 *
 * Bundled `agentsociety-*` skills are flat directories:
 * `extension/skills/<skill>/SKILL.md`.
 * User snapshots live at `~/.agentsociety/skill-versions/<skill>/<tag>/`.
 *
 * Workspaces receive a real directory copy at `.claude/skills/<skill>/`
 * (not a symlink), so exports and Windows both work without special cases.
 * Office skills (docx/pdf/pptx/xlsx) are handled by copyOfficialOfficeSkills.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { getMainOutputChannel } from './shared/outputChannels';

const SNAPSHOT_ROOT_REL = path.join('.agentsociety', 'skill-versions');

export interface SkillSnapshotInfo {
  id: string;
  label: string;
}

export interface SkillSyncResult {
  applied: string[];
  errors: Array<{ skill: string; message: string }>;
}

function isSafeSnapshotTag(tag: string): boolean {
  return (
    /^[A-Za-z0-9._-]+$/.test(tag) &&
    tag !== '.' &&
    tag !== '..' &&
    !tag.includes('/')
  );
}

export class BundledSkillManager {
  private readonly skillsSourcePath: string;
  private readonly outputChannel: vscode.OutputChannel;

  constructor(context: vscode.ExtensionContext, outputChannel?: vscode.OutputChannel) {
    this.skillsSourcePath = path.join(context.extensionPath, 'skills');
    this.outputChannel = outputChannel ?? getMainOutputChannel();
  }

  // ============ Identification ============

  static isManaged(skillName: string): boolean {
    return /^agentsociety-[A-Za-z0-9._-]+$/.test(skillName) && !skillName.includes('..');
  }

  /** All flat `agentsociety-*` skills present in the extension bundle. */
  listManagedSkills(): string[] {
    if (!fs.existsSync(this.skillsSourcePath)) {
      return [];
    }
    const result: string[] = [];
    for (const name of fs.readdirSync(this.skillsSourcePath)) {
      if (!BundledSkillManager.isManaged(name)) {
        continue;
      }
      const dir = path.join(this.skillsSourcePath, name);
      try {
        if (!fs.statSync(dir).isDirectory()) {
          continue;
        }
        if (fs.existsSync(path.join(dir, 'SKILL.md'))) {
          result.push(name);
        }
      } catch {
        /* skip unreadable */
      }
    }
    return result.sort();
  }

  bundledSkillPath(skillName: string): string {
    return path.join(this.skillsSourcePath, skillName);
  }

  // ============ Snapshots ============

  private snapshotRoot(): string {
    return path.join(os.homedir(), SNAPSHOT_ROOT_REL);
  }

  private snapshotSkillDir(skillName: string): string {
    return path.join(this.snapshotRoot(), skillName);
  }

  listSnapshots(skillName: string): SkillSnapshotInfo[] {
    const dir = this.snapshotSkillDir(skillName);
    if (!fs.existsSync(dir)) {
      return [];
    }
    try {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      const out: SkillSnapshotInfo[] = [];
      for (const e of entries) {
        if (!e.isDirectory() || e.name.startsWith('.')) {
          continue;
        }
        const stat = fs.statSync(path.join(dir, e.name));
        out.push({
          id: e.name,
          label: `Snapshot · ${stat.mtime.toISOString().slice(0, 10)}`,
        });
      }
      return out.sort((a, b) => a.id.localeCompare(b.id));
    } catch {
      return [];
    }
  }

  countSnapshots(skillName: string): number {
    return this.listSnapshots(skillName).length;
  }

  /** Take a snapshot of the skill currently realized at `.claude/skills/<skill>/`. */
  createSnapshot(
    workspacePath: string,
    skillName: string,
    tag: string,
  ): { success: boolean; message: string; path?: string } {
    if (!BundledSkillManager.isManaged(skillName)) {
      return { success: false, message: `不是受管内置技能: ${skillName}` };
    }
    const trimmed = tag.trim();
    if (!trimmed || !isSafeSnapshotTag(trimmed)) {
      return { success: false, message: `tag 非法（仅允许字母/数字/. _ -）: ${tag}` };
    }
    const liveDir = path.join(workspacePath, '.claude', 'skills', skillName);
    if (!fs.existsSync(liveDir)) {
      return {
        success: false,
        message: `未找到 .claude/skills/${skillName}/，请先同步内置技能再快照`,
      };
    }

    const targetDir = path.join(this.snapshotSkillDir(skillName), trimmed);
    if (fs.existsSync(targetDir)) {
      return { success: false, message: `快照 tag 已存在: ${trimmed}` };
    }

    try {
      this.replaceWithCopy(fs.realpathSync(liveDir), targetDir, false);
      return { success: true, message: `已生成快照: ${targetDir}`, path: targetDir };
    } catch (e) {
      return { success: false, message: `快照失败: ${(e as Error).message}` };
    }
  }

  /** Restore a snapshot into the workspace's `.claude/skills/<skill>/`. */
  restoreSnapshot(
    workspacePath: string,
    skillName: string,
    tag: string,
  ): { success: boolean; message: string } {
    if (!BundledSkillManager.isManaged(skillName)) {
      return { success: false, message: `不是受管内置技能: ${skillName}` };
    }
    if (!isSafeSnapshotTag(tag)) {
      return { success: false, message: `tag 非法: ${tag}` };
    }
    const source = path.join(this.snapshotSkillDir(skillName), tag);
    if (!fs.existsSync(source) || !fs.statSync(source).isDirectory()) {
      return { success: false, message: `快照不存在: ${tag}` };
    }
    const liveDir = path.join(workspacePath, '.claude', 'skills', skillName);
    try {
      this.replaceWithCopy(source, liveDir);
      return { success: true, message: `已从快照恢复: ${liveDir}` };
    } catch (e) {
      return { success: false, message: `恢复快照失败: ${(e as Error).message}` };
    }
  }

  // ============ Workspace sync ============

  /** Replace `.claude/skills/<skill>/` with a copy of the bundled flat skill. */
  syncBundledSkill(workspacePath: string, skillName: string): SkillSyncResult {
    return this.syncSkill(workspacePath, skillName, false);
  }

  private syncSkill(workspacePath: string, skillName: string, migrateSnapshot: boolean): SkillSyncResult {
    const result: SkillSyncResult = { applied: [], errors: [] };
    if (!BundledSkillManager.isManaged(skillName)) {
      result.errors.push({ skill: skillName, message: '不是受管内置技能' });
      return result;
    }
    let source = this.bundledSkillPath(skillName);
    const target = path.join(workspacePath, '.claude', 'skills', skillName);
    try {
      // A v1 workspace can still point at a user-selected snapshot.
      if (migrateSnapshot && fs.lstatSync(target, { throwIfNoEntry: false })?.isSymbolicLink()
          && fs.existsSync(target)) {
        const live = fs.realpathSync(target);
        const snapshots = this.snapshotSkillDir(skillName);
        if (fs.existsSync(snapshots) && path.dirname(live) === fs.realpathSync(snapshots)
            && isSafeSnapshotTag(path.basename(live))) {
          source = live;
        }
      }
      if (!fs.statSync(path.join(source, 'SKILL.md'), { throwIfNoEntry: false })?.isFile()) {
        result.errors.push({ skill: skillName, message: '内置技能目录不存在' });
        return result;
      }
      this.replaceWithCopy(source, target);
      result.applied.push(skillName);
    } catch (e) {
      result.errors.push({ skill: skillName, message: (e as Error).message });
    }
    return result;
  }

  /** Sync every managed skill into the workspace. */
  syncBundledSkills(workspacePath: string): SkillSyncResult {
    const result: SkillSyncResult = { applied: [], errors: [] };
    for (const skill of this.listManagedSkills()) {
      const one = this.syncSkill(workspacePath, skill, true);
      result.applied.push(...one.applied);
      result.errors.push(...one.errors);
    }
    return result;
  }

  // ============ Helpers ============

  /** Stage the complete copy before replacing the previous workspace entry. */
  private replaceWithCopy(source: string, target: string, replace = true): void {
    const parent = path.dirname(target);
    fs.mkdirSync(parent, { recursive: true });
    const stage = fs.mkdtempSync(path.join(parent, `.${path.basename(target)}.tmp-`));
    const incoming = path.join(stage, 'incoming');
    const previous = path.join(stage, 'previous');
    let saved = false;
    try {
      this.copyTree(source, incoming);
      if (replace && fs.lstatSync(target, { throwIfNoEntry: false })) {
        fs.renameSync(target, previous);
        saved = true;
      }
      try {
        fs.renameSync(incoming, target);
      } catch (error) {
        if (saved) {
          try {
            fs.renameSync(previous, target);
            saved = false;
          } catch (rollbackError) {
            this.outputChannel.appendLine(`Could not restore ${target}. Previous skill saved at ${previous}`);
            throw rollbackError;
          }
        }
        throw error;
      }
      saved = false;
    } finally {
      // If rollback itself failed, keep the backup for recovery.
      if (!saved) {
        fs.rmSync(stage, { recursive: true, force: true });
      }
    }
  }

  /** Copy a skill tree with Node's built-in recursive copy, skipping caches. */
  private copyTree(source: string, target: string): void {
    fs.cpSync(source, target, {
      recursive: true,
      force: true,
      filter: (src) => {
        const name = path.basename(src);
        return name !== '__pycache__' && !name.endsWith('.pyc');
      },
    });
  }
}
