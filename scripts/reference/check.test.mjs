import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm, realpath, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { loadReference } from './load.mjs';
import { prepareReference } from './prepare.mjs';

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'kplasma-contract-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const files = {};
  for (const name of ['prototype/index.html', 'prototype/assets/analysis-data.js', 'raw/artificial.ini', 'tests/artificial.test.js']) {
    await mkdir(join(root, name, '..'), { recursive: true });
    await writeFile(join(root, name), 'artificial fixture');
    files[name] = createHash('sha256').update('artificial fixture').digest('hex');
  }
  const manifest = { version: 'v12.3.1', files };
  await writeFile(join(root, 'manifest.json'), JSON.stringify(manifest));
  return { root, manifest };
}
test('loader reads a checked external package', async t => {
  const { root } = await fixture(t);
  const result = await loadReference(root);
  assert.equal(result.version, 'v12.3.1');
  assert.equal(result.prototypeRoot, join(await realpath(root), 'prototype'));
  assert.equal(Object.keys(result.manifest.files).length, 4);
});
test('missing required prototype fails even with a matching listed checksum', async t => {
  const { root, manifest } = await fixture(t);
  delete manifest.files['prototype/assets/analysis-data.js'];
  await rm(join(root, 'prototype/assets/analysis-data.js'));
  await writeFile(join(root, 'manifest.json'), JSON.stringify(manifest));
  await assert.rejects(loadReference(root), /Required file/);
});
test('corrupted bytes fail checksum validation', async t => {
  const { root } = await fixture(t);
  await writeFile(join(root, 'raw/artificial.ini'), 'changed');
  await assert.rejects(loadReference(root), /Checksum mismatch/);
});
test('manifest paths cannot escape the package', async t => {
  const { root, manifest } = await fixture(t);
  manifest.files['../outside'] = 'a'.repeat(64);
  await writeFile(join(root, 'manifest.json'), JSON.stringify(manifest));
  await assert.rejects(loadReference(root), /Unsafe relative path/);
});
test('prepare copies explicit sources, preserves originals, and produces a checked package', async t => {
  const { root } = await fixture(t);
  const output = join(root, 'prepared');
  await prepareReference({ prototype: join(root, 'prototype'), raw: join(root, 'raw'), tests: join(root, 'tests'), output });
  assert.equal((await loadReference(output)).version, 'v12.3.1');
  assert.equal((await loadReference(root)).version, 'v12.3.1');
});
test('prepare refuses an output in the code repository', async t => {
  const { root } = await fixture(t);
  await assert.rejects(prepareReference({ prototype: join(root, 'prototype'), raw: join(root, 'raw'), tests: join(root, 'tests'), output: new URL('../../data/reference', import.meta.url).pathname }), /outside the repository/);
});
test('missing reference root explains the environment requirement', async () => {
  await assert.rejects(loadReference(undefined), /KPLASMA_REFERENCE_ROOT/);
});

test('loader rejects unlisted package bytes', async t => {
  const { root } = await fixture(t);
  await writeFile(join(root, 'raw/unlisted.ini'), 'unexpected');
  await assert.rejects(loadReference(root), /unlisted files/);
});
test('loader rejects a symbolic-link package section even when it points inside the package', async t => {
  const { root } = await fixture(t);
  await rm(join(root, 'raw'), { recursive: true });
  await mkdir(join(root, 'actual-raw'));
  await writeFile(join(root, 'actual-raw/artificial.ini'), 'artificial fixture');
  await symlink(join(root, 'actual-raw'), join(root, 'raw'));
  await assert.rejects(loadReference(root), /Symbolic link/);
});
test('prepare refuses overwrite and source/output overlap', async t => {
  const { root } = await fixture(t);
  const options = { prototype: join(root, 'prototype'), raw: join(root, 'raw'), tests: join(root, 'tests') };
  await assert.rejects(prepareReference({ ...options, output: root }), /must not overlap/);
  await assert.rejects(prepareReference({ ...options, output: join(root, 'prototype/child') }), /must not overlap/);
  await mkdir(join(root, 'existing'));
  await assert.rejects(prepareReference({ ...options, output: join(root, 'existing') }), /already exists/);
});
