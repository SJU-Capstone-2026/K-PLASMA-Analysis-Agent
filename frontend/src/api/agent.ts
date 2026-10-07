import type {AgentRequestView,AgentResume,AgentSubmission,RunOptions} from 'agent';
import {request} from './client';
const base='/api/agent/requests';
const post=(body:unknown,key:string,signal?:AbortSignal):RequestInit=>({method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body),signal});
export const submitAgentRequest=(body:AgentSubmission,key:string,signal?:AbortSignal)=>request<AgentRequestView>(base,post(body,key,signal));
export const fetchAgentRequest=(id:string,signal?:AbortSignal)=>request<AgentRequestView>(`${base}/${encodeURIComponent(id)}`,{signal});
export const resumeAgentRequest=(id:string,body:AgentResume,key:string,signal?:AbortSignal)=>request<AgentRequestView>(`${base}/${encodeURIComponent(id)}/resume`,post(body,key,signal));
export const cancelAgentRequest=(id:string,signal?:AbortSignal)=>request<AgentRequestView>(`${base}/${encodeURIComponent(id)}/cancel`,post({},`cancel-${id}`,signal));
export const fetchRunOptions=(id:string,pendingId:string,signal?:AbortSignal)=>request<RunOptions>(`${base}/${encodeURIComponent(id)}/run-options?pendingInputId=${encodeURIComponent(pendingId)}`,{signal});
