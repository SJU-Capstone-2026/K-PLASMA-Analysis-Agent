import { copyFile, mkdir, realpath, writeFile, access } from 'node:fs/promises';
import { basename, dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { listFiles, loadReference, sha256 } from './load.mjs';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
function inside(parent, child) { const rel = relative(parent, child); return rel === '' || (!rel.startsWith('..') && !rel.startsWith('/')); }
async function canonicalOutput(path) {
  path = resolve(path);
  try { return await realpath(path); }
  catch (error) { if (error.code !== 'ENOENT') throw error; return join(await canonicalOutput(dirname(path)), basename(path)); }
}
/** Copy explicit sources once; never alter originals or overwrite an existing package. */
export async function prepareReference({ prototype, raw, tests, output }) {
  if (![prototype, raw, tests, output].every(path => typeof path === 'string' && path.length)) throw new Error('Explicit --prototype, --raw, --tests and --output directories are required');
  output = await canonicalOutput(output);
  if (inside(await realpath(repositoryRoot), output)) throw new Error('Reference output must be outside the repository');
  const sources = { prototype: await realpath(prototype), raw: await realpath(raw), tests: await realpath(tests) };
  for (const source of Object.values(sources)) if (inside(source, output) || inside(output, source)) throw new Error('Output and source directories must not overlap');
  try { await access(output); throw new Error('Reference output already exists; choose a new external directory'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const inventories = {};
  for (const [kind, source] of Object.entries(sources)) inventories[kind] = await listFiles(source);
  await mkdir(output, { recursive: true });
  const files = {};
  for (const [kind, source] of Object.entries(sources)) {
    for (const path of inventories[kind]) {
      const target = join(output, kind, path);
      await mkdir(dirname(target), { recursive: true });
      await copyFile(join(source, path), target);
      files[`${kind}/${path}`] = await sha256(target);
      if (await sha256(join(source, path)) !== files[`${kind}/${path}`]) throw new Error(`Source changed during copy: ${kind}/${path}`);
    }
  }
  await writeFile(join(output, 'manifest.json'), `${JSON.stringify({ version: 'v12.3.1', files }, null, 2)}\n`, { flag: 'wx' });
  return loadReference(output);
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const options = {};
  for (let i = 0; i < args.length; i += 2) {
    if (!['--prototype', '--raw', '--tests', '--output'].includes(args[i]) || !args[i + 1] || Object.hasOwn(options, args[i].slice(2))) throw new Error('Usage: node scripts/reference/prepare.mjs --prototype DIR --raw DIR --tests DIR --output DIR');
    options[args[i].slice(2)] = args[i + 1];
  }
  try { const pkg = await prepareReference(options); console.log(`Prepared ${pkg.version}: ${Object.keys(pkg.manifest.files).length} checked files`); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
