import type {AgentEventPage,AgentPublicEvent,AgentRequestView,AgentResultProjection,AgentResume,AgentSubmission,LegacyRunOptions,RunOptions,RunSelection,RunSelectionChange} from 'agent';
import {request} from './client';
const base='/api/agent/requests';
const post=(body:unknown,key:string,signal?:AbortSignal):RequestInit=>({method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body),signal});
export const submitAgentRequest=(body:AgentSubmission,key:string,signal?:AbortSignal)=>request<AgentRequestView>(base,post(body,key,signal));
export const fetchAgentRequest=(id:string,signal?:AbortSignal)=>request<AgentRequestView>(`${base}/${encodeURIComponent(id)}`,{signal});
export const resumeAgentRequest=(id:string,body:AgentResume,key:string,signal?:AbortSignal)=>request<AgentRequestView>(`${base}/${encodeURIComponent(id)}/resume`,post(body,key,signal));
export const cancelAgentRequest=(id:string,signal?:AbortSignal)=>request<AgentRequestView>(`${base}/${encodeURIComponent(id)}/cancel`,post({},`cancel-${id}`,signal));
export const fetchLegacyRunOptions=(id:string,pendingId:string,signal?:AbortSignal)=>request<LegacyRunOptions>(`${base}/${encodeURIComponent(id)}/run-options?pendingInputId=${encodeURIComponent(pendingId)}`,{signal});
export const fetchAgentEvents=(id:string,after:number,signal?:AbortSignal)=>request<AgentEventPage>(`${base}/${encodeURIComponent(id)}/events?after=${after}&format=json`,{signal});
export const fetchAgentResults=(id:string,resultRevision:number,signal?:AbortSignal)=>request<AgentResultProjection>(`${base}/${encodeURIComponent(id)}/results?resultRevision=${resultRevision}`,{signal});
export function openAgentEvents(id:string,after:number,onEvent:(event:AgentPublicEvent)=>void,onError:()=>void){
 const source=new EventSource(`${base}/${encodeURIComponent(id)}/events?after=${after}`);
 source.onmessage=message=>{try{onEvent(JSON.parse(message.data) as AgentPublicEvent);}catch{onError();}};
 source.onerror=onError;
 return source;
}
export interface PickerQuery {query?:string;sort?:string;cursor?:string|null;pageSize?:number}
function pickerParams(pendingId:string,params:PickerQuery={}){const search=new URLSearchParams({pendingInputId:pendingId,format:'2'});for(const [key,value] of Object.entries(params))if(value!=null)search.set(key,String(value));return search.toString();}
export const fetchRunOptions=(id:string,pendingId:string,params:PickerQuery={},signal?:AbortSignal)=>request<RunOptions>(`${base}/${encodeURIComponent(id)}/run-options?${pickerParams(pendingId,params)}`,{signal});
export const fetchRunOptionCount=(id:string,pendingId:string,query:string,signal?:AbortSignal)=>request<{matchingCount:number;totalCount:number}>(`${base}/${encodeURIComponent(id)}/run-options/count?${pickerParams(pendingId,{query})}`,{signal});
export const fetchRunSelection=(id:string,pendingId:string,cursor:string|null=null,signal?:AbortSignal)=>request<RunSelection>(`${base}/${encodeURIComponent(id)}/run-selection?${pickerParams(pendingId,{cursor})}`,{signal});
export const changeRunSelection=(id:string,body:RunSelectionChange,key:string)=>request<RunSelection>(`${base}/${encodeURIComponent(id)}/run-selection`,post(body,key));
