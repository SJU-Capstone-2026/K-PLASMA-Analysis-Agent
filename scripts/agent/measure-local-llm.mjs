import {spawn} from 'node:child_process';
import {statSync,createWriteStream} from 'node:fs';
import {mkdtemp,writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {once} from 'node:events';
import {startEvaluationEnvironment} from './runtime.mjs';
import {command,freePort,repo,sleep} from '../reference/runtime.mjs';

const args=process.argv.slice(2);
let validProfile=false;
try{validProfile=args.length===2&&args[0]==='--env-file'&&statSync(args[1]).isFile();}catch{ /* invalid profile */ }
if(!validProfile){
 process.stderr.write('Usage: node -- scripts/agent/measure-local-llm.mjs --env-file <existing-local.env>\n');
 process.exit(2);
}
const envFile=resolve(args[1]);
const output=await mkdtemp(join(tmpdir(),'kplasma-local-measure-'));
const port=await freePort(),web=`http://127.0.0.1:${port}`;
const require=createRequire(join(repo,'frontend/package.json'));
const {chromium}=require('@playwright/test');
let environment,frontend,browser;
async function stopFrontend(){
 if(!frontend||frontend.exitCode!==null||frontend.signalCode!==null)return;
 const stopped=once(frontend,'exit');frontend.kill('SIGTERM');
 await Promise.race([stopped,sleep(5000)]);
 if(frontend.exitCode===null&&frontend.signalCode===null){frontend.kill('SIGKILL');await stopped;}
}
try{
 environment=await startEvaluationEnvironment(output,'none',{graphVersion:'v2_localLLM',uiOrigin:web});
 const log=createWriteStream(join(output,'frontend.log'));
 frontend=spawn(process.execPath,[join(repo,'node_modules/vite/bin/vite.js'),'--host','127.0.0.1',
  '--port',String(port),'--strictPort'],{cwd:join(repo,'frontend'),stdio:['ignore','pipe','pipe'],
  env:{...process.env,VITE_API_TARGET:environment.url,VITE_AGENT_SUPPORTED_GRAPH_VERSIONS:'v2_localLLM',
   VITE_AGENT_DEFAULT_GRAPH_VERSION:'v2_localLLM'}});
 frontend.stdout.pipe(log,{end:false});frontend.stderr.pipe(log,{end:false});frontend.once('exit',()=>log.end());
 let ready=false;
 for(let count=0;count<60;count++){
  if(frontend.exitCode!==null)throw new Error('LOCAL_MEASUREMENT_FRONTEND_FAILED');
  try{if((await fetch(web)).ok){ready=true;break;}}catch{ /* wait for this owned Vite process */ }
  await sleep(500);
 }
 if(!ready)throw new Error('LOCAL_MEASUREMENT_FRONTEND_TIMEOUT');
 browser=await chromium.launch({headless:true});
 const context=await browser.newContext();
 const page=await context.newPage();
 await page.goto(web+'/?view=agent',{waitUntil:'networkidle'});
 const mode=page.getByRole('group',{name:'분석 실행 모드'}).getByRole('button',{name:'로컬',exact:true});
 await mode.waitFor();
 if(await mode.getAttribute('aria-pressed')!=='true')throw new Error('LOCAL_MEASUREMENT_GRAPH_MISMATCH');
 await writeFile(join(output,'stack-ready.json'),JSON.stringify({synthetic_only:true,web}),{mode:0o600});
 await command(join(repo,'agent/python/.venv/bin/python'),['-m','evals.local_llm_measure','--env-file',envFile,
  '--stack-connection',environment.connection,'--output',join(output,'measurement.json')],{
  cwd:join(repo,'agent/python'),env:{...process.env,PYTHONPATH:join(repo,'agent/python/src')},
  log:join(output,'measurement.log')});
 console.log(`Local measurement passed: ${join(output,'measurement.json')}`);
}catch{
 console.error(`Local measurement failed; inspect ${join(output,'measurement.log')}`);
 process.exitCode=2;
}finally{
 const closed=await Promise.allSettled([browser?.close(),stopFrontend(),environment?.close()]);
 if(closed.some(result=>result.status==='rejected')){console.error('LOCAL_MEASUREMENT_CLEANUP_FAILED');process.exitCode=2;}
}
