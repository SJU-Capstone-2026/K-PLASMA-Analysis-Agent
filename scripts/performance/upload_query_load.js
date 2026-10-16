import http from 'k6/http';
import crypto from 'k6/crypto';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { requestSlot } from './upload_query_user_schedule.mjs';

const targets=JSON.parse(open(__ENV.QUERY_MANIFEST));
const base=__ENV.BASE_URL;
if(!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base))throw new Error('Local benchmark only');
const rate=Number(__ENV.RATE||5);
if(!Number.isInteger(rate)||rate<1||rate>400)throw new Error('Rate must be an integer between 1 and 400');
const users=__ENV.LOAD_MODEL==='users';
const vus=Number(__ENV.USER_VUS||1);
if(users&&(!Number.isInteger(vus)||vus<1||vus>100))throw new Error('VUs must be between 1 and 100');
const duration=__ENV.DURATION||'90s';
const durationMs=Number(duration.replace(/s$/,''))*1000;
const arrival={executor:'constant-arrival-rate',rate,timeUnit:'1s',duration,preAllocatedVUs:60,maxVUs:60,gracefulStop:'10s'};
export const options={scenarios:{lookup:users?{executor:'constant-vus',vus,duration,gracefulStop:'10s'}:arrival},maxRedirects:0};
let nextSlot=0;
export default function(){
  let cohort=null,scheduledEpochMs=null;
  if(users){
    cohort=requestSlot(nextSlot,Date.now()-exec.scenario.startTime,5000);
    scheduledEpochMs=exec.scenario.startTime+cohort*5000;
    if(cohort*5000>=durationMs){sleep(5);return;}
    nextSlot=cohort+1;
    sleep(Math.max(0,(scheduledEpochMs-Date.now())/1000));
    // An intentional stop interrupts sleep: never issue a future slot early.
    if(Date.now()<scheduledEpochMs)return;
  }
  const sequence=exec.scenario.iterationInTest;
  const targetIndex=users?(cohort*vus+exec.vu.idInTest-1)%targets.length:sequence%targets.length;
  const target=targets[targetIndex];
  const id=`${__ENV.TRIAL_ID}-${sequence}`;
  const start=Date.now();
  const response=http.get(`${base}/api/run-versions/${target.runVersionId}`,{timeout:'10s',headers:{'X-Benchmark-Request-Id':id},tags:{name:'GET /api/run-versions/:id'}});
  const elapsed=Date.now()-start;
  const valid=response.status===200&&crypto.sha256(response.body||'','hex')===target.sha256;
  console.log(JSON.stringify({id,vu:exec.vu.idInTest,cohort,scheduledEpochMs,startEpochMs:start,elapsedMs:elapsed,durationMs:response.timings.duration,blockedMs:response.timings.blocked,connectingMs:response.timings.connecting,sendingMs:response.timings.sending,waitingMs:response.timings.waiting,receivingMs:response.timings.receiving,status:response.status,errorCode:response.error_code||0,valid,bodyCharacters:(response.body||'').length,version:target.runVersionId}));
}
export function handleSummary(data){return {[__ENV.SUMMARY_PATH]:JSON.stringify(data,null,2)};}
