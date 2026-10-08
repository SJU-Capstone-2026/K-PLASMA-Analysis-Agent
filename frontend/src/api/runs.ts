import type {FullRun,RunDeleteRequest,RunDeleteResult,RunRef,RunSummary} from 'agent';
import {request} from './client';
export function fetchRuns(signal?:AbortSignal):Promise<RunSummary[]>{return request('/api/runs',{signal});}
export function fetchRunVersion(ref:RunRef,signal?:AbortSignal):Promise<FullRun>{return request(`/api/run-versions/${encodeURIComponent(ref.runVersionId)}`,{signal});}
export function deleteRuns(body:RunDeleteRequest,signal?:AbortSignal):Promise<RunDeleteResult>{return request('/api/runs/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});}
