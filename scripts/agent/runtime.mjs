import {spawn,spawnSync} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {createWriteStream} from 'node:fs';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import {once} from 'node:events';
import {repo,startBackend,syntheticFolder,upload,terminalBatch,sleep} from '../reference/runtime.mjs';

export function graphVersionArgument(argv=process.argv.slice(2)){
  const entries=argv.flatMap((arg,index)=>arg==='--graph-version'?[argv[index+1]]:
    arg.startsWith('--graph-version=')?[arg.slice('--graph-version='.length)]:[]);
  const version=entries.length?entries[0]:'v2';
  if(!['v2','v2_localLLM'].includes(version)||entries.length>1)
    throw new Error('Unsupported graph version');
  return version;
}

export function runtimeWorkerSpec(graphVersion,{live=false,envFile}={}){
  if(!['v2','v2_localLLM'].includes(graphVersion))throw new Error('Unsupported graph version');
  if(!live)return [graphVersion==='v2'?'agent/python/tests/runtime_v2_worker.py':
    'agent/python/tests/v2_local_llm/runtime_worker.py'];
  if(graphVersion!=='v2'&&!envFile)throw new Error('An explicit env file is required');
  return ['-m',graphVersion==='v2'?'kplasma_agent.worker':
    'kplasma_agent.v2_local_llm.worker',...(envFile?['--env-file',envFile]:[])];
}

export function assertLocalReadiness(python,envFile,env=process.env){
  if(!envFile)throw new Error('An explicit local env file is required');
  const checked=spawnSync(python,runtimeWorkerSpec('v2_localLLM',{live:true,envFile}).concat('--check'),
    {cwd:repo,env,encoding:'utf8',timeout:600000,maxBuffer:65536});
  let status;
  try{status=JSON.parse(checked.stdout);}catch{throw new Error('LOCAL_READINESS_CHECK_FAILED');}
  if(checked.error||checked.status!==0||status.graphVersion!=='v2_localLLM'||status.ready!==true
    ||!Array.isArray(status.blockers)||status.blockers.length)throw new Error('LOCAL_RUNTIME_NOT_READY');
}

function localOrigin(value){
  try{
    const url=new URL(value);
    if(url.protocol==='http:'&&['127.0.0.1','[::1]'].includes(url.hostname)
      &&url.port&&!url.username&&!url.password&&!url.search&&!url.hash&&value===url.origin)return value;
  }catch{ /* Report no supplied URL. */ }
  throw new Error('LOCAL_BROWSER_ORIGIN_INVALID');
}

/** Owns only its freshly created synthetic DB, storage and child processes. */
export async function startEvaluationEnvironment(output,mode='stub',options={}){
  const graphVersion=options.graphVersion??'v2';
  const envFile=options.envFile??process.env.KPLASMA_VERIFY_ENV_FILE;
  const python=process.env.KPLASMA_VERIFY_PYTHON??join(repo,'agent/python/.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
  const workerSpec=runtimeWorkerSpec(graphVersion,{live:mode==='live',envFile});
  if(graphVersion==='v2_localLLM'&&mode==='live'){
    assertLocalReadiness(python,envFile,{...process.env,PYTHONPATH:join(repo,'agent/python/src')});
  }
  const isLocal=graphVersion==='v2_localLLM';
  const uiOrigin=isLocal?localOrigin(options.uiOrigin):undefined;
  await mkdir(output,{recursive:true});
  const token=randomUUID();const previous=process.env.AGENT_WORKER_TOKEN;
  const versionKeys=['AGENT_SUPPORTED_GRAPH_VERSIONS','AGENT_DEFAULT_GRAPH_VERSION',
    'AGENT_LOCAL_RUNTIME_ENABLED','AGENT_LOCAL_UI_ORIGIN','AGENT_LOCAL_API_HOST'];
  const oldVersions=Object.fromEntries(versionKeys.map(key=>[key,process.env[key]]));
  let backend,worker;
  async function close(){
    if(worker&&worker.exitCode===null){worker.kill('SIGTERM');await Promise.race([once(worker,'exit'),sleep(5000)]);if(worker.exitCode===null)worker.kill('SIGKILL');}
    await backend?.close();
  }
  try{
    try{
      process.env.AGENT_WORKER_TOKEN=token;
      process.env.AGENT_SUPPORTED_GRAPH_VERSIONS=graphVersion;
      process.env.AGENT_DEFAULT_GRAPH_VERSION=graphVersion;
      if(isLocal){
        process.env.AGENT_LOCAL_RUNTIME_ENABLED='true';process.env.AGENT_LOCAL_UI_ORIGIN=uiOrigin;
        process.env.AGENT_LOCAL_API_HOST='';
      }
      backend=await startBackend(output,'2026-10-05T00:00:00Z');
    }finally{
      if(previous===undefined)delete process.env.AGENT_WORKER_TOKEN;else process.env.AGENT_WORKER_TOKEN=previous;
      for(const key of versionKeys){if(oldVersions[key]===undefined)delete process.env[key];else process.env[key]=oldVersions[key];}
    }
    const connection=join(output,'connection.json');
    const metadata={url:backend.url,token,workerToken:token,output,graphVersion,
      data:'artificial-only',evaluationMode:mode==='live'?'real_model_on_artificial_data':'synthetic'};
    const headers=isLocal?{Origin:uiOrigin,'Sec-Fetch-Site':'same-site'}:{};
    if(isLocal)metadata.uiOrigin=uiOrigin;
    const folder=await syntheticFolder(output,{decisionDemo:graphVersion==='v2'&&options.decisionDemo});
    for(const pressure of [4,6]){
      const path=join(folder,`artificial-${pressure}/0d_result/log/solver.log`);
      const text=await readFile(path,'utf8');
      await writeFile(path,text.replace('Ar+ 12.3456789',`Ar+ ${pressure*10}`).replace('Ar+ 1.e14',`Ar+ ${pressure}.e15`));
    }
    const accepted=await upload(backend.url,folder,'FOLDER',undefined,headers);
    if((await terminalBatch(backend.url,accepted.batchId,headers)).status!=='SUCCESS')throw new Error('Synthetic import failed');
    await writeFile(connection,JSON.stringify(metadata),{mode:0o600});
    if(mode!=='none'){
      const args=mode==='live'?workerSpec:workerSpec.concat('--connection',connection);
      const env={...process.env,PHOENIX_COLLECTOR_ENDPOINT:'',PHOENIX_API_KEY:'',AGENT_BACKEND_URL:backend.url,AGENT_WORKER_TOKEN:token,PYTHONPATH:join(repo,'agent/python/src')};
      if(mode==='live'&&isLocal){
        env.AGENT_V2_LOCAL_LLM_BACKEND_URL=backend.url;env.AGENT_V2_LOCAL_LLM_WORKER_TOKEN=token;
      }else if(mode==='live'){
        env.AGENT_V2_PLAN_REVIEW_ENABLED='true';
        env.AGENT_MODEL_TIMEOUT_SECONDS='90';
      }
      if(mode!=='live')delete env.OPENAI_API_KEY;
      worker=spawn(python,args,{cwd:repo,env,stdio:['ignore','pipe','pipe']});
      const log=createWriteStream(join(output,'worker.log'));worker.stdout.pipe(log,{end:false});worker.stderr.pipe(log,{end:false});worker.on('exit',()=>log.end());
      metadata.workerPid=worker.pid;await writeFile(connection,JSON.stringify(metadata),{mode:0o600});
    }
    return {url:backend.url,connection,worker,close,headers,graphVersion,restartBackend:()=>backend.restart()};
  }catch(error){await close();throw error;}
}
