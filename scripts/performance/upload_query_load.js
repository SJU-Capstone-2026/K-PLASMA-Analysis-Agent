import http from 'k6/http';
import crypto from 'k6/crypto';
import exec from 'k6/execution';

const targets=JSON.parse(open(__ENV.QUERY_MANIFEST));
const base=__ENV.BASE_URL;
if(!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base))throw new Error('Local benchmark only');
export const options={scenarios:{lookup:{executor:'constant-arrival-rate',rate:5,timeUnit:'1s',duration:__ENV.DURATION||'90s',preAllocatedVUs:60,maxVUs:60,gracefulStop:'10s'}},maxRedirects:0};
export default function(){
  const sequence=exec.scenario.iterationInTest;
  const target=targets[sequence%targets.length];
  const id=`${__ENV.TRIAL_ID}-${sequence}`;
  const start=Date.now();
  const response=http.get(`${base}/api/run-versions/${target.runVersionId}`,{timeout:'10s',headers:{'X-Benchmark-Request-Id':id},tags:{name:'GET /api/run-versions/:id'}});
  const elapsed=Date.now()-start;
  const valid=response.status===200&&crypto.sha256(response.body||'','hex')===target.sha256;
  console.log(JSON.stringify({id,startEpochMs:start,elapsedMs:elapsed,durationMs:response.timings.duration,blockedMs:response.timings.blocked,status:response.status,errorCode:response.error_code||0,valid,bodyCharacters:(response.body||'').length,version:target.runVersionId}));
}
export function handleSummary(data){return {[__ENV.SUMMARY_PATH]:JSON.stringify(data,null,2)};}
