const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const dryRun = process.argv.includes('--dry-run');
const deep = process.argv.includes('--deep');

function exists(targetPath) {
  try {
    fs.lstatSync(targetPath);
    return true;
  } catch {
    return false;
  }
}

function remove(targetPath) {
  if (!exists(targetPath)) {
    return false;
  }
  const relative = path.relative(root, targetPath) || path.basename(targetPath);
  if (dryRun) {
    console.log(`[dry-run] remove ${relative}`);
    return true;
  }
  fs.rmSync(targetPath, { recursive: true, force: true });
  console.log(`removed ${relative}`);
  return true;
}

function removeVsixArtifacts() {
  let removed = false;
  for (const entry of fs.readdirSync(root)) {
    if (!entry.endsWith('.vsix')) {
      continue;
    }
    removed = remove(path.join(root, entry)) || removed;
  }
  return removed;
}

const targets = [
  path.join(root, 'out'),
  path.join(root, 'dist'),
  path.join(root, 'node_modules', '.cache'),
];

if (deep) {
  targets.push(path.join(root, 'node_modules'));
}

let removedAny = false;
for (const target of targets) {
  removedAny = remove(target) || removedAny;
}
removedAny = removeVsixArtifacts() || removedAny;

if (!removedAny) {
  console.log(dryRun ? '[dry-run] nothing to clean' : 'nothing to clean');
}
