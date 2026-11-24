import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {startV1Environment} from './runtime.mjs';
import {freePort,repo,waitForHealth} from '../reference/runtime.mjs';

const output=await mkdtemp(join(tmpdir(),'kplasma-decision-preview-'));
const port=await freePort();
const url=`http://127.0.0.1:${port}`;
const environment=await startV1Environment(output,'stub-v2',{decisionDemo:true});
const frontend=spawn(process.execPath,[join(repo,'node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',String(port),'--strictPort'],{
  cwd:join(repo,'frontend'),
  env:{...process.env,VITE_API_TARGET:environment.url},
  stdio:'inherit',
});
const stopped=once(frontend,'exit');
function stop(){frontend.kill('SIGTERM');}
for(const signal of ['SIGINT','SIGTERM'])process.once(signal,stop);
try{
  await waitForHealth(url,frontend);
  console.log(`Decision Agent preview (synthetic Runs): ${url}`);
  await stopped;
}finally{
  stop();
  await environment.close();
}
