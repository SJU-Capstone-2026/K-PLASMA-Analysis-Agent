import { defineConfig } from 'vitest/config';

// Vitest workers rewrite argv; capture explicit real-data selection in the runner.
const referenceExplicit = process.argv.some(arg => /(?:^|\/)reference-parity\.test\.ts$/.test(arg));
export default defineConfig({
  test: { environment: 'node', env: { KPLASMA_REFERENCE_EXPLICIT: String(referenceExplicit) } },
});
