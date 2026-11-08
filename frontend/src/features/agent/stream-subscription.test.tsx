import {afterEach,expect,test,vi} from 'vitest';
import {cleanup,renderHook,waitFor} from '@testing-library/react';
import type {AgentRequestView,WorkspaceView} from 'agent';
import {useConversation} from './useConversation';

afterEach(()=>{cleanup();vi.unstubAllGlobals();localStorage.clear();});

test('a restored human-input wait does not open a stream that the server immediately closes',async()=>{
 const request:AgentRequestView={requestId:'waiting',requestRevision:0,status:'NEEDS_INPUT',stage:'wait_input',
  graphVersion:'v2',question:'인공 선택 질문',pendingInput:{id:'choose',type:'text',message:'선택해 주세요.'},
  error:null,partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[],workspaceEpoch:1,conversationEpoch:2,
  progress:{lastEventSeq:3,activities:[],answer:null,resultRevision:null}};
 const workspace:WorkspaceView={stateToken:{workspaceEpoch:1,conversationEpoch:2,revision:0},
  conversation:{version:1,activeRun:null,turns:[],agentGraphVersion:'v2'},candidateReference:null,activeAgentRequest:request};
 class Source {static opened=0;constructor(){Source.opened++;}close(){}}
 vi.stubGlobal('EventSource',Source);
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(workspace)));
 const hook=renderHook(()=>useConversation());
 await waitFor(()=>expect(hook.result.current.ready).toBe(true));
 expect(hook.result.current.activeRequest?.status).toBe('NEEDS_INPUT');
 expect(Source.opened).toBe(0);
});
