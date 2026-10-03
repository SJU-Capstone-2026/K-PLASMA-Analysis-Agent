import { loadReference } from './load.mjs';
try {
  const pkg = await loadReference(process.env.KPLASMA_REFERENCE_ROOT);
  console.log(`Reference ${pkg.version} integrity PASS (${Object.keys(pkg.manifest.files).length} files)`);
} catch (error) { console.error(error.message); process.exitCode = 1; }
