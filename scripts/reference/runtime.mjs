import {spawn,execFileSync} from 'node:child_process';
import {createReadStream,createWriteStream} from 'node:fs';
import {mkdir,readFile,writeFile,readdir,copyFile,stat} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {createServer,request} from 'node:http';
import {once} from 'node:events';
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {listFiles} from './load.mjs';

export const repo = resolve(fileURLToPath(new URL('../..',import.meta.url)));
export const sleep = ms=>new Promise(resolve=>setTimeout(resolve,ms));
export async function freePort() {
  const server=createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;
}
export async function command(file,args,{cwd=repo,env=process.env,log}={}) {
  const child=spawn(file,args,{cwd,env,stdio:log?['ignore','pipe','pipe']:'inherit'});
  const output=log?createWriteStream(log):null;
  if(output){child.stdout.pipe(output,{end:false});child.stderr.pipe(output,{end:false});}
  const [code]=await once(child,'exit');output?.end();
  if(code!==0)throw new Error(`${file} failed (exit ${code}); see local verification log.`);
}
export async function waitForHealth(url,child) {
  for(let index=0;index<120;index++) {
    if(child?.exitCode!==null && child?.exitCode!==undefined)throw new Error('Verification server exited; inspect its ignored log.');
    try {const response=await fetch(url);if(response.ok)return;}catch {/* server is starting */}
    await sleep(500);
  }
  throw new Error(`Verification service did not become ready: ${url}`);
}
/** New DB, storage, build directory, Gradle cache and stable JAR for each run. */
export async function startBackend(output,instant) {
  const container=`kplasma-verify-${randomUUID()}`;
  const password=randomUUID();let child;
  await mkdir(output,{recursive:true});
  const cleanup=async()=>{
    if(child && child.exitCode===null){child.kill('SIGTERM');await Promise.race([once(child,'exit'),sleep(10000)]);if(child.exitCode===null)child.kill('SIGKILL');}
    try{execFileSync('docker',['rm','-f',container],{stdio:'ignore'});}catch {/* only this isolated container */}
  };
  try {
    execFileSync('docker',['run','--detach','--name',container,'--publish','127.0.0.1::5432','--env',`POSTGRES_PASSWORD=${password}`,'--env','POSTGRES_USER=kplasma','--env','POSTGRES_DB=kplasma','postgres:18.6-alpine3.24'],{stdio:'pipe'});
    const binding=JSON.parse(execFileSync('docker',['inspect',container],{encoding:'utf8'}))[0].NetworkSettings.Ports['5432/tcp'][0].HostPort;
    for(let count=0;count<60;count++){try{execFileSync('docker',['exec',container,'pg_isready','-U','kplasma','-d','kplasma'],{stdio:'ignore'});break;}catch {if(count===59)throw new Error('Verification PostgreSQL failed readiness.');await sleep(500);}}
    const generated=join(output,'generated/com/kplasma/analysisagent/verification');await mkdir(generated,{recursive:true});
    // The fixed Clock exists only in this ignored generated verification build, never in product sources/JARs.
    await writeFile(join(generated,'VerificationClock.java'),`package com.kplasma.analysisagent.verification;
import java.time.*; import org.springframework.context.annotation.*;
@Configuration public class VerificationClock {
 @Bean @Primary Clock fixedRegistrationClock(){return Clock.fixed(Instant.parse("${new Date(instant).toISOString()}"),ZoneOffset.UTC);}
}`);
    const groovy=value=>JSON.stringify(value);
    const init=join(output,'build.gradle');
    await writeFile(init,`allprojects { layout.buildDirectory.set(file(${groovy(join(output,'build'))})); afterEvaluate { sourceSets.main.java.srcDir(${groovy(join(output,'generated'))}) } }\n`);
    await command(join(repo,'backend/gradlew'),['-p','backend','--project-cache-dir',join(output,'gradle-cache'),'--init-script',init,'bootJar','--console=plain'],{log:join(output,'build.log')});
    const jar=(await readdir(join(output,'build/libs'))).find(name=>name.endsWith('.jar')&&!name.includes('-plain'));
    if(!jar)throw new Error('Verification bootJar missing.');
    const stable=join(output,'server.jar');await copyFile(join(output,'build/libs',jar),stable);
    const port=await freePort();const url=`http://127.0.0.1:${port}`;
    const env={...process.env,DB_URL:`jdbc:postgresql://127.0.0.1:${binding}/kplasma`,POSTGRES_USER:'kplasma',POSTGRES_PASSWORD:password,BACKEND_PORT:String(port),KPLASMA_STORAGE_ROOT:join(output,'storage')};
    child=spawn(process.env.JAVA_HOME?join(process.env.JAVA_HOME,'bin/java'):'java',['-jar',stable],{cwd:repo,env,stdio:['ignore','pipe','pipe']});
    const log=createWriteStream(join(output,'server.log'));child.stdout.pipe(log,{end:false});child.stderr.pipe(log,{end:false});child.on('exit',()=>log.end());
    await waitForHealth(`${url}/api/health`,child);
    return {url,close:cleanup};
  } catch(error){await cleanup();throw error;}
}
export async function createZip(root,target) {
  await command(process.env.JAVA_HOME?join(process.env.JAVA_HOME,'bin/jar'):'jar',['--create','--file',target,'--no-manifest','-C',root,'.']);
}
/** Streams files; the actual150 folder can be >1GiB and must not be buffered into FormData. */
export async function upload(api,root,mode,archive) {
  const paths=mode==='FOLDER'?await listFiles(root):[archive];
  const boundary=`kplasma-${randomUUID()}`;
  const entries=paths.map((path,index)=>({partName:`file${index}`,relativePath:mode==='FOLDER'?path:'reference.zip'}));
  const headers=entries.map(entry=>Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="${entry.partName}"; filename="file"\r\nContent-Type: application/octet-stream\r\n\r\n`));
  const manifest=Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="manifest"\r\nContent-Type: application/json\r\n\r\n${JSON.stringify({mode,entries})}\r\n`);
  const suffix=Buffer.from(`--${boundary}--\r\n`);
  const files=paths.map(path=>mode==='FOLDER'?join(root,path):path);
  const sizes=await Promise.all(files.map(async path=>(await stat(path)).size));
  const length=manifest.length+suffix.length+sizes.reduce((sum,size,index)=>sum+size+headers[index].length+2,0);
  const req=request(new URL('/api/import-batches',api),{method:'POST',headers:{'Content-Type':`multipart/form-data; boundary=${boundary}`,'Content-Length':length,'Idempotency-Key':randomUUID()}});
  const response=new Promise((resolve,reject)=>{req.once('error',reject);req.once('response',async res=>{const chunks=[];for await(const chunk of res)chunks.push(chunk);if(res.statusCode!==202){reject(new Error(`Import rejected HTTP ${res.statusCode}; no response values logged.`));return;}resolve(JSON.parse(Buffer.concat(chunks).toString()));});});
  async function send(chunk){if(!req.write(chunk))await once(req,'drain');}
  await send(manifest);
  for(let index=0;index<files.length;index++){await send(headers[index]);for await(const chunk of createReadStream(files[index]))await send(chunk);await send(Buffer.from('\r\n'));}
  req.end(suffix);return response;
}
export async function get(api,path) {const response=await fetch(new URL(path,api));if(!response.ok)throw new Error(`API ${path.split('/').slice(0,3).join('/')} returned HTTP ${response.status}`);return response.json();}
export async function terminalBatch(api,id) {for(let count=0;count<1800;count++){const batch=await get(api,`/api/import-batches/${id}`);if(['SUCCESS','PARTIAL_SUCCESS','FAILED'].includes(batch.status))return batch;await sleep(500);}throw new Error('Import processing timed out.');}
export async function syntheticFolder(output) {
  const source=await readFile(join(repo,'backend/src/test/java/com/kplasma/analysisagent/ingestion/SyntheticRunFiles.java'),'utf8');
  const blocks=[...source.matchAll(/return """\n([\s\S]*?)\n\s*"""/g)].map(match=>match[1].split('\n').map(line=>line.replace(/^ {12}/,'')).join('\n')+'\n');
  const replace=(value,args)=>{let index=0;return value.replace(/%s/g,()=>args[index++]);};
  const root=join(output,'synthetic');
  for(const pressure of [2,4,6]){
    const files={'0d_setting.ini':replace(blocks[0],['0','0','\u0001']).replace('PRS=2',`PRS=${pressure}`),'0d_result/log/solver.log':replace(blocks[1],['OFF','','']).replace('Pressure = 2',`Pressure = ${pressure}`),'0d_result/log/residual.log':blocks[2],'0d_result/log/output.log':'INFO: Finished!\n'};
    for(const [name,value] of Object.entries(files)){const path=join(root,`artificial-${pressure}`,name);await mkdir(resolve(path,'..'),{recursive:true});await writeFile(path,value);}
  }
  return root;
}
