import http from 'k6/http';
import {check} from 'k6';
const fixture=JSON.parse(open(__ENV.SELECTION_REQUEST));
export const options={scenarios:{requests:{executor:'shared-iterations',vus:1,iterations:Number(__ENV.SELECTION_ITERATIONS||100),maxDuration:'10m'}},discardResponseBodies:true,summaryTrendStats:['avg','med','p(95)','max'],thresholds:{http_req_failed:['rate==0'],checks:['rate==1']}};
export default function(){
 const suffix=__ENV.SELECTION_QUERY||'';
 const response=http.get('http://127.0.0.1:18049'+fixture.path+suffix,{tags:{scenario:__ENV.SELECTION_SCENARIO||'page'},timeout:'60s'});
 check(response,{'HTTP 200':r=>r.status===200});
}
export function handleSummary(data){return {[__ENV.SELECTION_SUMMARY]:JSON.stringify(data,null,2)};}
