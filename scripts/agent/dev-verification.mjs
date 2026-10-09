// Explicit isolated synthetic development environment; no user database access.
import {join} from 'node:path';
import {repo} from '../reference/runtime.mjs';
import {startV1Environment} from './runtime.mjs';
const output=join(repo,'agent/python/.runtime',`integration-${Date.now()}`);
const environment=await startV1Environment(output,process.argv.includes('--no-worker')?'none':'live');
try{
  console.log(`Isolated synthetic backend: ${environment.url}\nLocal connection: ${environment.connection}`);
  await new Promise(resolve=>{process.on('SIGTERM',resolve);process.on('SIGINT',resolve);environment.worker?.on('exit',resolve);});
}finally{await environment.close();}
