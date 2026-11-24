import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {startV1Environment,graphVersionArgument} from './runtime.mjs';
import {command, freePort, repo} from '../reference/runtime.mjs';

const live = process.argv.includes('--live');
const graphVersion=graphVersionArgument();
const output = await mkdtemp(join(tmpdir(), 'kplasma-v2-browser-'));
console.log(`Browser evidence: ${output}`);
const frontendPort=await freePort();
const environment = await startV1Environment(output, live ? 'live' : 'stub-v2',
  {graphVersion,decisionDemo:!live,uiOrigin:`http://127.0.0.1:${frontendPort}`});
try {
  await command(join(repo, 'node_modules/.bin/playwright'), ['test', '--config', 'v2.playwright.config.ts'], {
    cwd: join(repo, 'frontend'),
    env: {...process.env, KPLASMA_E2E_API: environment.url, KPLASMA_E2E_OUTPUT: output,
      KPLASMA_E2E_PORT: String(frontendPort), KPLASMA_V2_MOCK: String(!live),
      KPLASMA_E2E_GRAPH_VERSION:graphVersion,KPLASMA_E2E_CONNECTION:environment.connection},
  });
} finally {
  await environment.close();
}
