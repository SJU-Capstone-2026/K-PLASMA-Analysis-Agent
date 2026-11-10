import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {startV1Environment} from './runtime.mjs';
import {command, freePort, repo} from '../reference/runtime.mjs';

const live = process.argv.includes('--live');
const output = await mkdtemp(join(tmpdir(), 'kplasma-v2-browser-'));
console.log(`Browser evidence: ${output}`);
const environment = await startV1Environment(output, live ? 'live' : 'stub-v2');
try {
  await command(join(repo, 'node_modules/.bin/playwright'), ['test', '--config', 'v2.playwright.config.ts'], {
    cwd: join(repo, 'frontend'),
    env: {...process.env, KPLASMA_E2E_API: environment.url, KPLASMA_E2E_OUTPUT: output,
      KPLASMA_E2E_PORT: String(await freePort()), KPLASMA_V2_MOCK: String(!live)},
  });
} finally {
  await environment.close();
}
