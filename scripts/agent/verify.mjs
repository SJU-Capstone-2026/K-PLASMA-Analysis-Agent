import {join} from 'node:path';
import {mkdir,writeFile} from 'node:fs/promises';
import {repo,command,freePort} from '../reference/runtime.mjs';
import {startV1Environment} from './runtime.mjs';

const live=process.argv.includes('--live');
const output=join(repo,'agent/python/.runtime',`verify-${live?'live':'offline'}-${Date.now()}`);
await mkdir(output,{recursive:true});
const summary={mode:live?'actual-openai':'deterministic-model-test-double',data:'artificial-only',status:'FAIL'};
let environment;
try{
  environment=await startV1Environment(output,live?'live':'stub');
  const env={...process.env,KPLASMA_E2E_API:environment.url,KPLASMA_E2E_PORT:String(await freePort()),
    KPLASMA_E2E_OUTPUT:join(output,'browser'),KPLASMA_E2E_REFERENCE:'false',
    OPENAI_MODEL:live?'gpt-5.6-luna':'test-v1-deterministic',OPENAI_REASONING_EFFORT:'none'};
  await command(join(repo,'node_modules/.bin/playwright'),['test','--config','v1.playwright.config.ts'],{cwd:join(repo,'frontend'),env,log:join(output,'browser.log')});
  summary.status='PASS';
}catch(error){summary.error=error.message;process.exitCode=1;}
finally{
  await environment?.close();
  await writeFile(join(output,'summary.json'),JSON.stringify(summary,null,2));
  console.log(`Graph v1 ${summary.mode}: ${summary.status}. Local evidence: ${output}`);
  if(summary.error)console.error(summary.error);
}
