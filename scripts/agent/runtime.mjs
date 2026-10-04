import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {createWriteStream} from 'node:fs';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import {once} from 'node:events';
import {repo,startBackend,syntheticFolder,upload,terminalBatch,sleep} from '../reference/runtime.mjs';

/** Owns only its freshly created synthetic DB, storage and child processes. */
export async function startV1Environment(output,mode='stub'){
  await mkdir(output,{recursive:true});
  const token=randomUUID();const previous=process.env.AGENT_WORKER_TOKEN;
  let backend,worker;
  async function close(){
    if(worker&&worker.exitCode===null){worker.kill('SIGTERM');await Promise.race([once(worker,'exit'),sleep(5000)]);if(worker.exitCode===null)worker.kill('SIGKILL');}
    await backend?.close();
  }
  try{
    try{process.env.AGENT_WORKER_TOKEN=token;backend=await startBackend(output,'2026-10-05T00:00:00Z');}
    finally{if(previous===undefined)delete process.env.AGENT_WORKER_TOKEN;else process.env.AGENT_WORKER_TOKEN=previous;}
    const folder=await syntheticFolder(output);
    for(const pressure of [4,6]){
      const path=join(folder,`artificial-${pressure}/0d_result/log/solver.log`);
      const text=await readFile(path,'utf8');
      await writeFile(path,text.replace('Ar+ 12.3456789',`Ar+ ${pressure*10}`).replace('Ar+ 1.e14',`Ar+ ${pressure}.e14`));
    }
    const accepted=await upload(backend.url,folder,'FOLDER');
    if((await terminalBatch(backend.url,accepted.batchId)).status!=='SUCCESS')throw new Error('Synthetic import failed');
    const connection=join(output,'connection.json');
    const metadata={url:backend.url,token,workerToken:token,output};
    await writeFile(connection,JSON.stringify(metadata),{mode:0o600});
    if(mode!=='none'){
      const python=join(repo,'agent/python/.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
      const args=mode==='live'?['-m','kplasma_agent.worker']:['agent/python/tests/runtime_worker.py','--connection',connection];
      const env={...process.env,AGENT_BACKEND_URL:backend.url,AGENT_WORKER_TOKEN:token,PYTHONPATH:join(repo,'agent/python/src')};
      if(mode==='live'){env.OPENAI_MODEL='gpt-5.6-luna';env.OPENAI_REASONING_EFFORT='none';}
      if(mode!=='live')delete env.OPENAI_API_KEY;
      worker=spawn(python,args,{cwd:repo,env,stdio:['ignore','pipe','pipe']});
      const log=createWriteStream(join(output,'worker.log'));worker.stdout.pipe(log,{end:false});worker.stderr.pipe(log,{end:false});worker.on('exit',()=>log.end());
      metadata.workerPid=worker.pid;await writeFile(connection,JSON.stringify(metadata),{mode:0o600});
    }
    return {url:backend.url,connection,worker,close};
  }catch(error){await close();throw error;}
}
