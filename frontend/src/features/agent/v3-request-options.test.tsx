import {act,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import type {AgentRequestView,AgentSubmission,WorkspaceView} from 'agent';
import {emptyWorkspace,useConversation} from './useConversation';

const mode={rulesEnabled:true,ragEnabled:false,configDigest:'a'.repeat(64)};
function request(status:AgentRequestView['status']='NEEDS_INPUT'):AgentRequestView{
 return {requestId:'v3-request',requestRevision:2,status,stage:'execute',graphVersion:'v3',v3Options:{...mode},question:'선택한 Run의 판단 기록',pendingInput:status==='NEEDS_INPUT'?{id:'input-1',type:'text',message:'확인할 Run을 선택해 주세요.'}:null,error:null,partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]};
}
afterEach(()=>{vi.unstubAllGlobals();localStorage.clear();});

test('v3 submission snapshots its feature selection and locks it once accepted',async()=>{
 let workspace:WorkspaceView=structuredClone(emptyWorkspace);
 const posted:AgentSubmission[]=[];
 const accepted=request('RUNNING');
 vi.stubGlobal('fetch',vi.fn(async(path:string,init:RequestInit={})=>{
  if(path==='/api/workspace')return Response.json(workspace);
  if(path==='/api/agent/requests'){
   const body=JSON.parse(String(init.body)) as AgentSubmission;posted.push(body);
   accepted.v3Options={...body.v3Options!,configDigest:mode.configDigest};
   workspace={...workspace,conversation:{...workspace.conversation,agentGraphVersion:'v3'},activeAgentRequest:accepted};
   return Response.json(accepted);
  }
  if(path==='/api/agent/requests/v3-request')return Response.json(accepted);
  throw new Error(`Unexpected request ${path}`);
 }));
 const hook=renderHook(()=>useConversation());await waitFor(()=>expect(hook.result.current.ready).toBe(true));
 act(()=>hook.result.current.selectGraphVersion('v3'));
 act(()=>hook.result.current.setV3Options({rulesEnabled:false,ragEnabled:true}));
 await act(()=>hook.result.current.submit('선택한 Run의 판단 기록을 찾아줘'));
 expect(posted).toHaveLength(1);
 expect(posted[0]).toMatchObject({graphVersion:'v3',v3Options:{rulesEnabled:false,ragEnabled:true}});
 expect(hook.result.current.v3ModeLocked).toBe(true);
 act(()=>hook.result.current.setV3Options({rulesEnabled:true,ragEnabled:false}));
 expect(hook.result.current.v3Options).toMatchObject({rulesEnabled:false,ragEnabled:true});
 hook.unmount();
});

test('reload and HITL resume preserve the server mode without sending replacement options',async()=>{
 const pending=request();
 const workspace:WorkspaceView={...structuredClone(emptyWorkspace),conversation:{...emptyWorkspace.conversation,agentGraphVersion:'v3'},activeAgentRequest:pending};
 const resumed:unknown[]=[];
 vi.stubGlobal('fetch',vi.fn(async(path:string,init:RequestInit={})=>{
  if(path==='/api/workspace')return Response.json(workspace);
  if(path==='/api/agent/requests/v3-request/resume'){resumed.push(JSON.parse(String(init.body)));return Response.json({...pending,requestRevision:3});}
  throw new Error(`Unexpected request ${path}`);
 }));
 const hook=renderHook(()=>useConversation());await waitFor(()=>expect(hook.result.current.ready).toBe(true));
 expect(hook.result.current.graphVersion).toBe('v3');
 expect(hook.result.current.v3Options).toEqual(mode);
 act(()=>hook.result.current.setV3Options({rulesEnabled:false,ragEnabled:true}));
 await act(()=>hook.result.current.resume({text:'이 Run만 확인'}));
 expect(resumed).toEqual([{expectedRequestRevision:2,pendingInputId:'input-1',input:{text:'이 Run만 확인'}}]);
 expect(hook.result.current.v3Options).toEqual(mode);
 hook.unmount();
});

test.each(['v1','v2'] as const)('legacy %s requests do not receive v3 options',async(version)=>{
 const workspace:WorkspaceView=structuredClone(emptyWorkspace);
 const posted:AgentSubmission[]=[];
 vi.stubGlobal('fetch',vi.fn(async(path:string,init:RequestInit={})=>{
  if(path==='/api/workspace')return Response.json(workspace);
  if(path==='/api/agent/requests'){posted.push(JSON.parse(String(init.body)));return Response.json({...request('CANCELLED'),graphVersion:version,v3Options:null});}
  throw new Error(`Unexpected request ${path}`);
 }));
 const hook=renderHook(()=>useConversation());await waitFor(()=>expect(hook.result.current.ready).toBe(true));
 act(()=>hook.result.current.selectGraphVersion(version));
 act(()=>hook.result.current.setV3Options({rulesEnabled:false,ragEnabled:false}));
 await act(()=>hook.result.current.submit('평균 이온 에너지가 뭐야?'));
 expect(posted[0].v3Options).toBeUndefined();
 hook.unmount();
});
