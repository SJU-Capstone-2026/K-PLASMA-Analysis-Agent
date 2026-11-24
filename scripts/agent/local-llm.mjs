import {spawn,spawnSync} from 'node:child_process';
import {existsSync,statSync} from 'node:fs';
import {arch,cpus,platform,totalmem} from 'node:os';
import {delimiter,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(fileURLToPath(new URL('../..',import.meta.url)));
const python=join(root,'agent/python/.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const moduleName='kplasma_agent.v2_local_llm.worker';
const output=value=>process.stdout.write(JSON.stringify(value)+'\n');
const pending=code=>({graphVersion:'v2_localLLM',ready:false,blockers:[code]});

function hostFacts(){
 const onPath=name=>(process.env.PATH??'').split(delimiter).some(path=>existsSync(join(path,name)));
 return {
  platform:platform(),arch:arch(),cpu:cpus()[0]?.model??'unknown',memoryGiB:totalmem()/2**30,
  prerequisites:{pythonEnvironment:existsSync(python),llamaServerOnPath:onPath('llama-server')},
 };
}

function argumentsFor(argv){
 const args=[...argv];
 const command=args.shift()??'status';
 if(command==='--help')return {command};
 if(!['status','start','smoke'].includes(command))throw new Error('LOCAL_CLI_USAGE');
 let envFile;
 while(args.length){
  if(args.shift()!=='--env-file'||envFile||!args[0]||args[0].startsWith('--'))throw new Error('LOCAL_CLI_USAGE');
  envFile=resolve(args.shift());
 }
 if(!envFile)throw new Error('LOCAL_ENV_FILE_REQUIRED');
 if(!existsSync(envFile)||!statSync(envFile).isFile())throw new Error('LOCAL_ENV_FILE_MISSING');
 return {command,envFile};
}

function readiness(envFile,environment){
 const result=spawnSync(python,['-m',moduleName,'--env-file',envFile,'--check'],{
  cwd:root,env:environment,encoding:'utf8',timeout:600_000,maxBuffer:64*1024,
 });
 if(result.error)return pending('LOCAL_READINESS_CHECK_FAILED');
 try{
  const value=JSON.parse(result.stdout);
  if(typeof value.ready!=='boolean'||!Array.isArray(value.blockers)
   ||value.blockers.some(code=>typeof code!=='string'||!/^[A-Z][A-Z0-9_]{0,95}$/.test(code))
   ||(value.ready?(result.status!==0||value.blockers.length!==0):(result.status!==2||value.blockers.length===0))){
   return pending('LOCAL_READINESS_CHECK_INVALID');
  }
  return {graphVersion:'v2_localLLM',ready:value.ready,blockers:value.blockers};
 }catch{return pending('LOCAL_READINESS_CHECK_INVALID');}
}

async function launch(args,environment,cwd=root){
 return new Promise(resolveExit=>{
  const child=spawn(python,args,{cwd,env:environment,stdio:'inherit'});
  const handlers=new Map(['SIGTERM','SIGINT'].map(signal=>[signal,()=>child.kill(signal)]));
  for(const [signal,handler] of handlers)process.on(signal,handler);
  const cleanup=()=>{for(const [signal,handler] of handlers)process.off(signal,handler);};
  child.once('error',()=>{cleanup();output(pending('LOCAL_PROCESS_START_FAILED'));resolveExit(2);});
  child.once('exit',code=>{cleanup();resolveExit(code??1);});
 });
}

async function main(){
 let options;
 try{options=argumentsFor(process.argv.slice(2));}
 catch(error){output(pending(error.message));return 2;}
 if(options.command==='--help'){
  process.stdout.write('Usage: node -- scripts/agent/local-llm.mjs status|smoke|start --env-file <local.env>\n');
  return 0;
 }
 if(!existsSync(python)){output({...pending('LOCAL_PYTHON_ENVIRONMENT_MISSING'),host:hostFacts()});return 2;}
 const environment={...process.env,PYTHONPATH:join(root,'agent/python/src'),PYTHONNOUSERSITE:'1'};
 if(options.command==='smoke'){
  return launch(['-m','evals.local_llm_smoke','--env-file',options.envFile,'--live'],environment,join(root,'agent/python'));
 }
 const checked=readiness(options.envFile,environment);
 if(options.command==='status'||!checked.ready){
  output({...checked,host:hostFacts()});
  return checked.ready?0:2;
 }
 // The private worker rechecks evidence before it constructs clients or claims work.
 return launch(['-m',moduleName,'--env-file',options.envFile],environment);
}

process.exitCode=await main();
