import {expect,test} from 'vitest';
import type {AgentPublicEvent,AgentRequestView} from 'agent';
import {applyProgressEvent} from './progress-events';

const initial:AgentRequestView={requestId:'req',requestRevision:0,workspaceEpoch:1,conversationEpoch:2,
 status:'RUNNING',stage:'compose',graphVersion:'v2',question:'인공 질문',pendingInput:null,error:null,
 partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]};
const event=(seq:number,type:AgentPublicEvent['type'],payload:AgentPublicEvent['payload']):AgentPublicEvent=>({
 schemaVersion:1,requestId:'req',requestRevision:0,workspaceEpoch:1,conversationEpoch:2,
 seq,occurredAt:'2026-11-06T00:00:00Z',type,payload,
});

test('a replayed chunk and an old revision cannot duplicate or replace current prose',()=>{
 let state=applyProgressEvent(initial,event(1,'answer.start',{streamId:'first',answerRevision:1,mode:'interpretation'}));
 state=applyProgressEvent(state,event(2,'answer.delta',{streamId:'first',answerRevision:1,blockId:'interpretations.0.text',text:'초안'}));
 expect(applyProgressEvent(state,event(2,'answer.delta',{streamId:'first',answerRevision:1,blockId:'interpretations.0.text',text:'초안'}))).toBe(state);
 state=applyProgressEvent(state,event(3,'results.ready',{}));
 state=applyProgressEvent(state,event(4,'answer.reset',{streamId:'first',answerRevision:1}));
 state=applyProgressEvent(state,event(5,'answer.start',{streamId:'second',answerRevision:2,mode:'interpretation',rewrite:true}));
 state=applyProgressEvent(state,event(6,'answer.delta',{streamId:'first',answerRevision:1,blockId:'interpretations.0.text',text:'늦은 초안'}));
 state=applyProgressEvent(state,event(7,'answer.delta',{streamId:'second',answerRevision:2,blockId:'interpretations.0.text',text:'수정문'}));
 expect(state.progress?.answer?.blocks).toEqual([{id:'interpretations.0.text',text:'수정문'}]);
 expect(state.progress?.resultRevision).toBe(3);
});

test('events belong to one request and original conversation',()=>{
 const wrongRoom={...event(1,'answer.start',{streamId:'wrong',answerRevision:1,mode:'general'}),conversationEpoch:3};
 expect(applyProgressEvent(initial,wrongRoom)).toBe(initial);
 expect(applyProgressEvent(initial,{...wrongRoom,conversationEpoch:2,requestId:'other'})).toBe(initial);
});

test('only a state transition can advance request revision and review status follows actual activity',()=>{
 let state=applyProgressEvent(initial,event(1,'answer.start',{streamId:'s',answerRevision:1,mode:'interpretation'}));
 const nextRevision={...event(2,'answer.delta',{streamId:'s',answerRevision:1,blockId:'x',text:'잘못된 조각'}),requestRevision:1};
 expect(applyProgressEvent(state,nextRevision)).toBe(state);
 state=applyProgressEvent(state,event(3,'activity',{activityId:'review',code:'REVIEW',phase:'started'}));
 expect(state.progress?.answer?.status).toBe('reviewing');
 state=applyProgressEvent(state,{...event(4,'request.state',{status:'QUEUED'}),requestRevision:1});
 expect(state.requestRevision).toBe(1);
 expect(state.progress?.answer).toBeNull();
});
