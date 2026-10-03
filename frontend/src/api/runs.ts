import type {FullRun,RunRef,RunSummary} from 'agent';
import {request} from './client';
export function fetchRuns(signal?:AbortSignal):Promise<RunSummary[]>{return request('/api/runs',{signal});}
export function fetchRunVersion(ref:RunRef,signal?:AbortSignal):Promise<FullRun>{return request(`/api/run-versions/${encodeURIComponent(ref.runVersionId)}`,{signal});}
