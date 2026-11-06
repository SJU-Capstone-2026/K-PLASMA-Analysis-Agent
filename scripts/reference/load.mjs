import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';
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

/** Replace the prototype display samples with the verified original graph rows. */
export async function withFullReferenceGraphs(reference, run) {
  const read = async (type, columns, visit) => {
    const file = run.sourceFiles.find(row => row.type === type && (type !== 'LOG' || row.name === 'residual.log'));
    const key = `raw/${file?.path}`;
    if (!file || !Object.hasOwn(reference.manifest.files, key)) throw new Error(`Missing reference graph: ${type}`);
    const reader = createInterface({input: createReadStream(join(reference.root, key), 'utf8'), crlfDelay: Infinity});
    let count = 0;
    for await (const raw of reader) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const values = line.split(/\s+#/, 1)[0].split(/\s+/).map(Number);
      if (values.length !== columns || values.some(value => !Number.isFinite(value)))
        throw new Error(`Invalid reference graph row: ${type}`);
      visit(values);
      count++;
    }
    if (!count) throw new Error(`Empty reference graph: ${type}`);
  };
  const points = async type => {
    const result = [];
    await read(type, 2, row => result.push(row));
    return result;
  };
  const waveform = async type => {
    const rows = await points(type);
    return {points: rows, phaseRange: [rows[0][0], rows.at(-1)[0]], sourceCount: rows.length};
  };
  const residualTrace = [];
  await read('LOG', 6, ([iteration, ...residuals]) => residualTrace.push([iteration, Math.max(...residuals.map(Math.abs))]));
  const analysis = {...run.analysis, residualTrace};
  if (!analysis.hasDistribution) return {...run, analysis};

  const iedDistribution = (await points('IED')).map(([energy, intensity]) => ({energy, intensity}));
  analysis.iad = await points('IAD');
  analysis.current = await waveform('CURRENT');
  analysis.potential = await waveform('POTENTIAL');
  const angles = [], energies = [], values = [];
  await read('IEAD', 3, ([angle, energy, intensity]) => {
    if (angles.at(-1) !== angle) angles.push(angle);
    if (angles.length === 1) energies.push(energy);
    values.push(intensity);
  });
  analysis.iead = {angles, energies, values, sourceShape: [angles.length, energies.length],
    angleRange: [angles[0], angles.at(-1)]};
  const rows = [];
  await read('DENSITY', 3, ([phase, distance, density]) => {
    if (rows.at(-1)?.[0] !== phase) rows.push([phase, [], []]);
    rows.at(-1)[1].push(distance);
    rows.at(-1)[2].push(density);
  });
  analysis.density = {rows, sourceShape: [rows.length, rows[0][1].length]};
  return {...run, iedDistribution, analysis};
}
