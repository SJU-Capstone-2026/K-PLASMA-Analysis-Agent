// Local synchronized load with a monotonic clock; no application/DB mocks.
import http from 'node:http';
import { createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { readFileSync, writeFileSync } from 'node:fs';
const base=new URL(process.env.BASE_URL);
if(base.protocol!=='http:'||!['127.0.0.1','localhost'].includes(base.hostname))throw Error('Local benchmark only');
const targets=JSON.parse(readFileSync(process.env.QUERY_MANIFEST,'utf8'));
const vus=Number(process.env.USER_VUS||100),period=5000;
if(vus!==100)throw Error('This control requires 100 users');
const duration=Number((process.env.DURATION||'70s').replace(/s$/,''))*1000;
const agents=Array.from({length:vus},()=>new http.Agent({keepAlive:true,maxSockets:1}));
const uploadOffset=Number(process.env.UPLOAD_OFFSET_MS||5000);
if(!Number.isFinite(uploadOffset)||uploadOffset<0||uploadOffset>=duration)throw Error('Invalid upload offset');
const origin=performance.now(),epochOrigin=Date.now();
let next=0,timer,completed=0,errors=0,stopped=false;
const now=()=>performance.now()-origin;
function finish(){
  stopped=true;clearTimeout(timer);clearTimeout(uploadTimer);for(const a of agents)a.destroy();
  writeFileSync(process.env.SUMMARY_PATH,JSON.stringify({engine:'node-monotonic',completed,errors}));
  process.exit(0);
}
process.on('SIGINT',finish);process.on('SIGTERM',finish);
function query(vu,cohort){
  const target=targets[(cohort*vus+vu-1)%targets.length];
  const id=`${process.env.TRIAL_ID}-${cohort}-${vu}`;
  const startMonoMs=now(),startEpochMs=Date.now();let socketMs=startMonoMs,sentMonoMs=null,firstByteMs=null,connectingMs=0,done=false;
  let connectedAt=null;
  function record(status,body,errorCode=0){
    if(done)return;done=true;const endMonoMs=now();
    const valid=status===200&&createHash('sha256').update(body).digest('hex')===target.sha256;
    completed++;if(!valid)errors++;
    console.log(JSON.stringify({id,vu,cohort,scheduledEpochMs:epochOrigin+cohort*period,scheduledMonoMs:cohort*period,
      startEpochMs,startMonoMs,sentMonoMs,endMonoMs,elapsedMs:endMonoMs-startMonoMs,durationMs:endMonoMs-socketMs,
      wallElapsedMs:Date.now()-startEpochMs,blockedMs:socketMs-startMonoMs,connectingMs,
      sendingMs:sentMonoMs===null?null:sentMonoMs-socketMs,waitingMs:firstByteMs===null||sentMonoMs===null?null:firstByteMs-sentMonoMs,
      receivingMs:firstByteMs===null?null:endMonoMs-firstByteMs,status,errorCode,valid,bodyCharacters:body.toString('utf8').length,version:target.runVersionId}));
  }
  const request=http.get(new URL(`/api/run-versions/${target.runVersionId}`,base),{agent:agents[vu-1],headers:{'X-Benchmark-Request-Id':id}},response=>{
    firstByteMs=now();const chunks=[];
    response.on('data',chunk=>chunks.push(chunk));
    response.on('end',()=>record(response.statusCode,Buffer.concat(chunks)));
    response.on('error',()=>record(0,Buffer.alloc(0),1));
  });
  request.on('socket',socket=>{socketMs=now();if(socket.connecting){connectedAt=socketMs;socket.once('connect',()=>{connectingMs=now()-connectedAt;});}});
  request.on('finish',()=>{sentMonoMs=now();});
  request.setTimeout(10000,()=>request.destroy(Error('timeout')));
  request.on('error',()=>record(0,Buffer.alloc(0),1));
}
function release(){
  if(stopped)return;
  if(now()<next*period){timer=setTimeout(release,next*period-now());return;}
  if(next*period>=duration){finish();return;}
  const cohort=next++;
  for(let vu=1;vu<=vus;vu++)query(vu,cohort);
  timer=setTimeout(release,Math.max(0,next*period-now()));
}
const uploadTimer=setTimeout(()=>writeFileSync(process.env.UPLOAD_TRIGGER_PATH,JSON.stringify({scheduledMonoMs:uploadOffset,triggerMonoMs:now()})),uploadOffset);
release();
