import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readdir, readFile, realpath, lstat } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';

export async function sha256(path) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest('hex');
}
export async function listFiles(root, prefix = '') {
  const files = [];
  for (const entry of await readdir(join(root, prefix), { withFileTypes: true })) {
    const name = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isSymbolicLink()) throw new Error(`Symbolic link is not supported: ${name}`);
    if (entry.isDirectory()) files.push(...await listFiles(root, name));
    else if (entry.isFile()) files.push(name);
    else throw new Error(`Unsupported file: ${name}`);
  }
  return files.sort();
}
function safePath(path) {
  if (typeof path !== 'string' || isAbsolute(path) || path.includes('\\') || path.includes('\0') ||
    path.split('/').some(part => !part || part === '.' || part === '..') ||
    !/^(prototype|raw|tests)\//.test(path)) throw new Error(`Unsafe relative path: ${path}`);
}
/** @typedef {{root:string,version:string,prototypeRoot:string,rawRoot:string,testsRoot:string,manifest:{version:string,files:Record<string,string>}}} ReferencePackage */
/** Verify every byte without executing uploaded JavaScript. @returns {Promise<ReferencePackage>} */
export async function loadReference(root) {
  if (!root) throw new Error('Set KPLASMA_REFERENCE_ROOT to the external v12.3.1 reference package.');
  root = await realpath(resolve(root));
  const manifest = JSON.parse(await readFile(join(root, 'manifest.json'), 'utf8'));
  if (manifest.version !== 'v12.3.1' || !manifest.files || Array.isArray(manifest.files) || typeof manifest.files !== 'object') throw new Error('Invalid reference manifest version/files');
  for (const required of ['prototype/index.html', 'prototype/assets/analysis-data.js']) {
    if (!Object.hasOwn(manifest.files, required)) throw new Error(`Required file missing: ${required}`);
  }
  for (const kind of ['prototype', 'raw', 'tests']) {
    const stat = await lstat(join(root, kind)).catch(() => { throw new Error(`Required directory missing: ${kind}`); });
    if (stat.isSymbolicLink()) throw new Error(`Symbolic link is not supported: ${kind}`);
    if (!stat.isDirectory()) throw new Error(`Required directory missing: ${kind}`);
    if (!Object.keys(manifest.files).some(path => path.startsWith(`${kind}/`))) throw new Error(`Required files missing: ${kind}`);
  }
  for (const [path, expected] of Object.entries(manifest.files)) {
    safePath(path);
    if (!/^[a-f0-9]{64}$/.test(expected)) throw new Error(`Invalid SHA-256: ${path}`);
    const target = join(root, path);
    const stat = await lstat(target).catch(() => { throw new Error(`Required file missing: ${path}`); });
    if (!stat.isFile() || stat.isSymbolicLink() || relative(root, await realpath(target)).startsWith('..')) throw new Error(`Unsafe relative path: ${path}`);
    if (await sha256(target) !== expected) throw new Error(`Checksum mismatch: ${path}`);
  }
  const actual = (await Promise.all(['prototype', 'raw', 'tests'].map(async kind => (await listFiles(join(root, kind))).map(path => `${kind}/${path}`)))).flat().sort();
  if (JSON.stringify(actual) !== JSON.stringify(Object.keys(manifest.files).sort())) throw new Error('Reference contains unlisted files');
  return { root, version: manifest.version, prototypeRoot: join(root, 'prototype'), rawRoot: join(root, 'raw'), testsRoot: join(root, 'tests'), manifest };
}
