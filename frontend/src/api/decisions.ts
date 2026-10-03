import type {DecisionRecord,DecisionWrite} from 'agent';
import {request} from './client';
export const fetchDecisions=(signal?:AbortSignal)=>request<DecisionRecord[]>('/api/decisions',{signal});
export const saveDecision=(body:DecisionWrite,key:string,signal?:AbortSignal)=>request<DecisionRecord>('/api/decisions',{method:'POST',signal,headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)});
