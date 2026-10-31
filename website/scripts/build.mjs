import { cp, mkdir, readFile, readdir, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = path.join(root, 'src');
const output = path.join(root, 'dist');

if (path.resolve(output) !== path.join(path.resolve(root), 'dist')) throw new Error('Unsafe output path');
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await cp(source, output, { recursive: true });

const files = [];
async function collect(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) await collect(absolute);
    else files.push(absolute);
  }
}
await collect(output);

const errors = [];
for (const file of files.filter((name) => name.endsWith('.html'))) {
  const html = await readFile(file, 'utf8');
  for (const match of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
    const reference = match[1];
    if (/^(?:[a-z]+:|#|\/\/)/i.test(reference)) continue;
    const pathname = decodeURIComponent(reference.split('#')[0].split('?')[0]);
    if (!pathname) continue;
    const target = pathname.startsWith('/')
      ? path.join(output, pathname.slice(1))
      : path.resolve(path.dirname(file), pathname);
    if (!target.startsWith(output)) {
      errors.push(`${path.relative(output, file)}: path leaves output: ${reference}`);
      continue;
    }
    try {
      if (!(await stat(target)).isFile()) errors.push(`${reference}: not a file`);
    } catch {
      errors.push(`${path.relative(output, file)}: missing ${reference}`);
    }
  }
}

if (errors.length) throw new Error(`Static reference check failed:\n${errors.join('\n')}`);
console.log(`Built ${files.length} files to ${path.relative(root, output)}/`);
