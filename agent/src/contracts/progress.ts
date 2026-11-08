import type {AgentRequestStatus, RunRef, Snapshot} from './index.js';

export interface AgentActivity {
  activityId:string; code:string; phase:'started'|'completed'|'reused';
  seq:number; occurredAt:string; stepId?:string; runCount?:number; metricIds?:string[];
}
export interface AgentStreamAnswer {
  streamId:string; answerRevision:number; mode:'general'|'interpretation';
  status:'writing'|'reviewing'|'rewriting'|'interrupted'|'done';
  blocks:Array<{id:string;text:string}>;
}
export interface AgentProgressSnapshot {
  lastEventSeq:number; activities:AgentActivity[]; answer:AgentStreamAnswer|null;
  resultRevision:number|null;
}
export interface AgentExecutionSummary {durationMs:number;activities:AgentActivity[]}
export interface AgentPublicEvent {
  schemaVersion:1; requestId:string; workspaceEpoch:number; conversationEpoch:number;
  requestRevision:number; seq:number; occurredAt:string;
  type:'activity'|'answer.start'|'answer.delta'|'answer.reset'|'results.ready'|'request.state';
  payload:Snapshot;
}
export interface AgentEventPage {
  events:AgentPublicEvent[]; lastEventSeq:number; status:AgentRequestStatus;
  requestRevision:number; workspaceEpoch:number; conversationEpoch:number; hasMore:boolean;
}
export interface AgentResultProjection {
  resultRevision:number;
  results:Array<{stepId:string;executionId:string;runRefs:RunRef[];toolResult:Snapshot}>;
}
