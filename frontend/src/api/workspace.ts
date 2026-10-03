import type {ReferenceState,RunRef,StateToken,TurnSnapshot,TurnUiSnapshot,WorkspaceView} from 'agent';
import {request} from './client';
const json=(body:unknown,signal?:AbortSignal):RequestInit=>({headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});
export const fetchWorkspace=(signal?:AbortSignal)=>request<WorkspaceView>('/api/workspace',{signal});
export const appendTurn=(stateToken:StateToken,turn:TurnSnapshot,key:string,signal?:AbortSignal)=>request<WorkspaceView>('/api/workspace/turns',{...json({stateToken,turn},signal),method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key}});
export const patchTurnUi=(stateToken:StateToken,id:string,ui:Partial<TurnUiSnapshot>,signal?:AbortSignal)=>request<WorkspaceView>(`/api/workspace/turns/${encodeURIComponent(id)}/ui`,{...json({stateToken,ui},signal),method:'PATCH'});
/** R1: both fields are explicit, including null; active Run and candidate reference are independent. */
export const writeReference=(stateToken:StateToken,candidateReference:ReferenceState,activeRun:RunRef|null,signal?:AbortSignal)=>request<WorkspaceView>('/api/workspace/reference',{...json({stateToken,candidateReference,activeRun},signal),method:'PUT'});
export const replaceConversation=(stateToken:StateToken,reset=false)=>request<WorkspaceView>(`/api/workspace/${reset?'reset':'new-conversation'}`,{...json({stateToken}),method:'POST'});
