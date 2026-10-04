import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=resolve(fileURLToPath(new URL('../..',import.meta.url)));
const python=resolve(root,'agent/python/.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
if(!existsSync(python)){
  console.error('Python dependencies missing. Run: uv sync --project agent/python --frozen');
  process.exit(1);
}
const child=spawn(python,['-m','kplasma_agent.worker',...process.argv.slice(2)],{
  cwd:root,env:{...process.env,PYTHONPATH:resolve(root,'agent/python/src')},stdio:'inherit'});
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>child.kill(signal));
child.on('exit',code=>{process.exitCode=code??1;});
