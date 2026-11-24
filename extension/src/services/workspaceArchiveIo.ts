import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { digestFileContents, isExportSidecar } from './workspaceExportManifest';

const ARCHIVE_COMMAND_TIMEOUT_MS = 10 * 60 * 1_000;

const ZIP_SCRIPT = [
  'import json, os, sys, zipfile',
  '',
  'def is_safe_archive_path(name):',
  '    normalized = name.replace("\\\\", "/").removeprefix("./").rstrip("/")',
  '    if not normalized or normalized.startswith("/") or ":" in normalized:',
  '        return False',
  '    return all(part not in ("", ".", "..") for part in normalized.split("/"))',
  '',
  'MAX_ENTRIES = 100_000',
  'MAX_FILE_BYTES = 4 * 1024 ** 3',
  'MAX_TOTAL_BYTES = 8 * 1024 ** 3',
  'COPY_CHUNK_BYTES = 1024 * 1024',
  '',
  'action, source, destination = sys.argv[1], sys.argv[2], sys.argv[3]',
  'if action == "create":',
  '    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:',
  '        for root, dirs, files in os.walk(source):',
  '            dirs.sort()',
  '            files.sort()',
  '            rel_root = os.path.relpath(root, source)',
  '            if rel_root != ".":',
  '                zf.write(root, rel_root.replace(os.sep, "/") + "/")',
  '            for file_name in files:',
  '                absolute_path = os.path.join(root, file_name)',
  '                relative_path = os.path.relpath(absolute_path, source).replace(os.sep, "/")',
  '                zf.write(absolute_path, relative_path)',
  '    print(json.dumps({"ok": True}))',
  'elif action == "inspect":',
  '    with zipfile.ZipFile(source) as zf:',
  '        try:',
  '            info = zf.getinfo("_agentsociety/export-manifest.json")',
  '        except KeyError:',
  '            raise SystemExit("export manifest is missing")',
  '        if info.file_size > 1024 * 1024:',
  '            raise SystemExit("export manifest is too large")',
  '        manifest = json.loads(zf.read(info).decode("utf-8"))',
  '    print(json.dumps({"ok": True, "manifest": manifest}))',
  'elif action == "extract":',
  '    dest_root = os.path.abspath(destination)',
  '    os.makedirs(dest_root, exist_ok=True)',
  '    with zipfile.ZipFile(source) as zf:',
  '        items = zf.infolist()',
  '        if len(items) > MAX_ENTRIES:',
  '            raise SystemExit("archive contains too many entries")',
  '        declared_total = 0',
  '        for item in items:',
  '            name = item.filename.replace("\\\\", "/")',
  '            checked = name.rstrip("/") or name',
  '            if not is_safe_archive_path(checked):',
  '                raise SystemExit("unsafe archive path: " + name)',
  '            if item.flag_bits & 1:',
  '                raise SystemExit("encrypted archive entries are not supported")',
  '            if item.file_size > MAX_FILE_BYTES:',
  '                raise SystemExit("archive entry is too large: " + name)',
  '            declared_total += item.file_size',
  '            if declared_total > MAX_TOTAL_BYTES:',
  '                raise SystemExit("archive expands beyond the allowed size")',
  '        extracted_total = 0',
  '        for item in items:',
  '            name = item.filename.replace("\\\\", "/")',
  '            target = os.path.abspath(os.path.join(dest_root, name))',
  '            if os.path.commonpath((dest_root, target)) != dest_root:',
  '                raise SystemExit("unsafe archive path: " + name)',
  '            if name.endswith("/"):',
  '                os.makedirs(target, exist_ok=True)',
  '                continue',
  '            os.makedirs(os.path.dirname(target), exist_ok=True)',
  '            with zf.open(item) as src, open(target, "wb") as dst:',
  '                file_bytes = 0',
  '                while chunk := src.read(COPY_CHUNK_BYTES):',
  '                    file_bytes += len(chunk)',
  '                    extracted_total += len(chunk)',
  '                    if file_bytes > MAX_FILE_BYTES or extracted_total > MAX_TOTAL_BYTES:',
  '                        raise SystemExit("archive expands beyond the allowed size")',
  '                    dst.write(chunk)',
  '        print(json.dumps({"ok": True}))',
  'else:',
  '    raise SystemExit("unknown action")',
].join('\n');

export function runPythonArchiveCommand(
  pythonCommand: string,
  action: 'create' | 'extract' | 'inspect',
  source: string,
  destination: string,
): Promise<{ ok: true; manifest?: unknown }> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonCommand, ['-c', ZIP_SCRIPT, action, source, destination], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill();
      reject(new Error('Archive command timed out'));
    }, ARCHIVE_COMMAND_TIMEOUT_MS);
    child.stdout?.on('data', (chunk: Buffer | string) => {
      stdout += chunk.toString();
    });
    child.stderr?.on('data', (chunk: Buffer | string) => {
      stderr += chunk.toString();
    });
    child.on('error', (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.on('close', (code) => {
      clearTimeout(timeout);
      if (timedOut) {
        return;
      }
      if (code !== 0) {
        reject(new Error(stderr.trim() || `Python exited with code ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout.trim()) as { ok: true; manifest?: unknown });
      } catch {
        reject(new Error('Archive command returned invalid output'));
      }
    });
  });
}

export function collectContentDigests(stagingPath: string): Array<{ relativePath: string; sha256: string }> {
  const entries: Array<{ relativePath: string; sha256: string }> = [];
  const walk = (dir: string, relativeDir: string) => {
    for (const item of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const relativePath = relativeDir ? `${relativeDir}/${item.name}` : item.name;
      const absolutePath = path.join(dir, item.name);
      if (item.isDirectory()) {
        walk(absolutePath, relativePath);
      } else if (item.isFile() && !isExportSidecar(relativePath)) {
        entries.push({ relativePath, sha256: digestFileContents(absolutePath) });
      }
    }
  };
  walk(stagingPath, '');
  return entries;
}
