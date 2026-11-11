/** Check local documentation links and unused screenshots without network access. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const docs = path.join(repo, 'packages/agentsociety2/docs');
const relative = file => path.relative(repo, file);
// Released walkthroughs link to these files on GitHub main. Keep the original
// URLs working even after current guides switch to a consolidated recording.
const hostedCompatibilityAssets = [
  'init-01-workspace.gif',
  'init-02-web-import.gif',
  'init-03-llm-wizard.gif',
  'init-04-cli-finish.gif',
].map(name => path.join(repo, 'extension/resources/walkthrough/images/gif', name));
const managed = [
  'extension/resources/walkthrough/images',
  'extension/resources/readme',
  'packages/agentsociety2/docs/_static/images',
].map(file => path.join(repo, file));

function files(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    if (['_build', 'locale', 'node_modules', '__pycache__'].includes(entry.name)) return [];
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? files(file) : [file];
  });
}

const sources = [
  ...files(docs), ...files(path.join(repo, 'extension/resources/walkthrough')),
  ...files(path.join(repo, 'extension/docs')),
  ...['extension/README.md', 'extension/src/webview/README.md', 'frontend/README.md', 'packages/agentsociety2/README.md', 'packages/agentsociety2/README_zh.md'].map(file => path.join(repo, file)),
].filter(file => /\.(md|rst)$/.test(file));
const used = new Set(hostedCompatibilityAssets);
const errors = [];
let checked = 0;
let exportedLinks = 0;

for (const asset of hostedCompatibilityAssets) {
  if (!fs.existsSync(asset)) errors.push(`Missing hosted compatibility asset: ${relative(asset)}`);
}

function check(source, reference, isImage) {
  let target = reference.trim().replace(/^<|>$/g, '');
  // Also check repository assets linked through the public mirror, including GIF demos.
  const mirror = /^https:\/\/(?:github\.com\/tsinghua-fib-lab\/agentsociety\/blob\/main\/|raw\.githubusercontent\.com\/tsinghua-fib-lab\/agentsociety\/main\/)(.+)$/i.exec(target);
  if (mirror) target = mirror[1];
  else if (/^(?:[a-z][a-z0-9+.-]*:|#|\/\/)/i.test(target)) return;
  if (!isImage && target.startsWith('/')) return; // Web application routes.
  try { target = decodeURIComponent(target.split(/[?#]/)[0]); }
  catch { errors.push(`${relative(source)}: invalid encoded link`); return; }
  if (!target) return;
  const file = mirror ? path.resolve(repo, target)
    : target.startsWith('/') ? path.resolve(docs, '.' + target)
      : path.resolve(path.dirname(source), target);
  checked++;
  if (!fs.existsSync(file)) errors.push(`${relative(source)} → ${target}`);
  else used.add(path.resolve(file));
}

for (const source of sources) {
  const text = fs.readFileSync(source, 'utf8');
  if (source.endsWith('.rst')) {
    for (const match of text.matchAll(/^\.\. (?:image|figure|literalinclude)::\s+(.+)$/gm)) check(source, match[1], true);
    for (const match of text.matchAll(/`[^`\n]*<([^>\n]+)>`_/g)) check(source, match[1], false);
  } else {
    // Ignore links shown as examples inside fenced code blocks.
    let fence;
    const prose = text.split('\n').filter(line => {
      const match = /^\s*(`{3,}|~{3,})/.exec(line);
      if (match) {
        if (!fence) fence = match[1];
        else if (match[1][0] === fence[0] && match[1].length >= fence.length) fence = undefined;
        return false;
      }
      return !fence;
    }).join('\n');
    for (const match of prose.matchAll(/(!?)\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)/g)) {
      check(source, match[2], match[1] === '!');
    }
  }
}

for (const asset of managed.flatMap(files).filter(file => /\.(png|jpe?g|gif|svg|webp)$/i.test(file))) {
  if (!used.has(path.resolve(asset))) errors.push(`Unused documentation image: ${relative(asset)}`);
}

// Optional check of the actual Sphinx output, including viewcode links whose
// fragments are not covered by source-level doc/ref validation.
const htmlRootOption = process.argv.indexOf('--html-root');
if (htmlRootOption !== -1) {
  const directory = process.argv[htmlRootOption + 1];
  if (!directory || directory.startsWith('--')) {
    errors.push('--html-root requires a Sphinx HTML output directory');
  } else {
    const htmlRoot = path.resolve(directory);
    if (!fs.existsSync(htmlRoot) || !fs.statSync(htmlRoot).isDirectory()) {
      errors.push(`HTML output directory not found: ${htmlRoot}`);
    } else {
      const documents = new Map();
      const decode = value => value.replace(/&(?:amp|quot|apos|lt|gt|#\d+|#x[\da-f]+);/gi, entity => {
        const named = { '&amp;': '&', '&quot;': '"', '&apos;': "'", '&lt;': '<', '&gt;': '>' };
        if (named[entity.toLowerCase()]) return named[entity.toLowerCase()];
        const hex = /^&#x/i.test(entity);
        return String.fromCodePoint(Number.parseInt(entity.slice(hex ? 3 : 2, -1), hex ? 16 : 10));
      });
      function document(file) {
        if (!documents.has(file)) {
          const html = fs.readFileSync(file, 'utf8');
          documents.set(file, {
            ids: new Set([...html.matchAll(/<[^>]+\bid="([^"]*)"/g)].map(match => decode(match[1]))),
            links: [...html.matchAll(/<a\b[^>]*\bhref="([^"]*)"/g)].map(match => decode(match[1])),
          });
        }
        return documents.get(file);
      }
      for (const file of files(htmlRoot).filter(file => file.endsWith('.html'))) {
        for (const reference of document(file).links) {
          if (/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(reference)) continue;
          const url = new URL(reference, 'https://docs.invalid/');
          // Resolve relative paths from their source page, preserving parent segments.
          const rawPath = reference.split(/[?#]/)[0];
          const resolved = rawPath ? path.resolve(path.dirname(file), decodeURIComponent(rawPath)) : file;
          if (!resolved.startsWith(htmlRoot + path.sep) || !resolved.endsWith('.html')) continue;
          exportedLinks++;
          const label = `${path.relative(htmlRoot, file)} → ${reference}`;
          if (!fs.existsSync(resolved)) errors.push(`Missing generated page: ${label}`);
          else if (url.hash && !document(resolved).ids.has(decodeURIComponent(url.hash.slice(1)))) {
            errors.push(`Missing generated anchor: ${label}`);
          }
        }
      }
    }
  }
}
if (errors.length) {
  console.error(errors.join('\n'));
  process.exitCode = 1;
} else {
  console.log(`${sources.length} documentation files, ${checked} local/mirror links checked; no missing links or unused images; ${hostedCompatibilityAssets.length} hosted compatibility assets retained.${exportedLinks ? ` ${exportedLinks} generated HTML links checked.` : ''}`);
}
