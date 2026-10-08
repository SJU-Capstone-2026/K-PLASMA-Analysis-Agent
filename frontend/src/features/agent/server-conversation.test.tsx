/* eslint-disable @typescript-eslint/no-explicit-any -- Heterogeneous synthetic HTTP endpoint bodies. */
import {act,renderHook,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {emptyWorkspace,initialTurnUi,useConversation} from './useConversation';
import type {WorkspaceView} from 'agent';
let workspace:WorkspaceView;
let calls:{path:string;body:any;key:string|null}[];
let request:any;
const answer={implementationId:'v1',schemaVersion:1,kind:'explain_concept',summary:'평균 이온 에너지 설명',result:{status:'CONCEPT_READY',knowledgeBasis:'MODEL_GENERAL_KNOWLEDGE',sections:[{topic_refs:['meanIonEnergy'],text:'입사 이온의 에너지 평균입니다.'}],limitations:[]}};
const view=(status='QUEUED')=>({requestId:'request-1',requestRevision:0,status,stage:'interpret',graphVersion:'v1',question:'평균 이온 에너지가 뭐야?',pendingInput:null,error:null,partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]});
function complete(){request={...request,status:'COMPLETED',turnId:'turn-1',answerSnapshot:answer};workspace={...workspace,activeAgentRequest:null,conversation:{...workspace.conversation,turns:[{id:'turn-1',askedAt:'2026-10-05T00:00:00Z',question:request.question,intent:'CONCEPT_EXPLANATION',context:null,answerRunRefs:[],answerSnapshot:answer,ui:structuredClone(initialTurnUi)}]}};}
beforeEach(()=>{workspace=structuredClone(emptyWorkspace);calls=[];request=view();vi.stubGlobal('fetch',vi.fn(async(path:string,init:RequestInit={})=>{const body=init.body?JSON.parse(String(init.body)):null;calls.push({path,body,key:new Headers(init.headers).get('Idempotency-Key')});if(path==='/api/agent/requests'){complete();return Response.json(request);}if(path==='/api/agent/requests/request-1/resume'){request.inputEvents.push({input:body.input});complete();return Response.json(request);}if(path==='/api/agent/requests/request-1/cancel'){request.status='CANCELLED';workspace.activeAgentRequest=null;return Response.json(request);}if(path==='/api/agent/requests/request-1')return Response.json(request);if(path.endsWith('/ui')){workspace.conversation.turns[0].ui={...workspace.conversation.turns[0].ui,...body.ui};return Response.json(workspace);}if(path==='/api/workspace')return Response.json(workspace);throw new Error(`Unexpected transport: ${path}`);}));});
afterEach(()=>vi.unstubAllGlobals());
test('new questions go to durable v1 endpoint and consume server-saved turn without local Run fetch or append',async()=>{const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));await act(()=>result.current.submit('평균 이온 에너지가 뭐야?'));expect(calls.some(call=>call.path==='/api/agent/requests')).toBe(true);await waitFor(()=>expect(result.current.state.conversation.turns).toHaveLength(1));expect(calls.map(call=>call.path)).not.toContain('/api/runs');expect(calls.some(call=>call.path.endsWith('/turns'))).toBe(false);expect(calls.find(call=>call.path==='/api/agent/requests')?.key).toBeTruthy();});
test('reload restores pending clarification and resumes the same request with revision and input id',async()=>{request={...view('NEEDS_INPUT'),requestRevision:3,pendingInput:{id:'input-1',message:'기준 Run을 알려 주세요.'}};workspace.activeAgentRequest=request;const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));expect(result.current.activeRequest?.pendingInput?.message).toBe('기준 Run을 알려 주세요.');await act(()=>result.current.resume({text:'RUN-A를 기준으로'}));expect(calls.find(call=>call.path.endsWith('/resume'))?.body).toEqual({expectedRequestRevision:3,pendingInputId:'input-1',input:{text:'RUN-A를 기준으로'}});await waitFor(()=>expect(result.current.state.conversation.turns).toHaveLength(1));});
test('failed explanation restores verified partial result without reporting successful completion',async()=>{request={...view('FAILED'),error:{code:'MODEL_UNAVAILABLE',message:'모델 연결 실패'},partialResult:{kind:'compare_runs',status:'COMPARED'},explanationComplete:false};workspace.failedAgentRequest=request;const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));expect(result.current.activeRequest?.status).toBe('FAILED');expect(result.current.activeRequest?.partialResult).toEqual(request.partialResult);expect(result.current.pending).toBe(false);expect(result.current.state.conversation.turns).toEqual([]);});
test('unmount stops browser polling without cancelling durable server work',async()=>{request=view('RUNNING');workspace.activeAgentRequest=request;const hook=renderHook(()=>useConversation());await waitFor(()=>expect(hook.result.current.ready).toBe(true));hook.unmount();expect(calls.some(call=>call.path.endsWith('/cancel'))).toBe(false);});
test('completed turn refresh failure keeps a recoverable request id and polls without resubmitting',async()=>{const original=globalThis.fetch;let reads=0;vi.stubGlobal('fetch',vi.fn((path:string,init?:RequestInit)=>{if(path==='/api/workspace'&&++reads===2)return Promise.reject(new TypeError('offline while loading result'));return original(path,init);}));const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));await act(()=>result.current.submit('평균 이온 에너지가 뭐야?').catch(()=>{}));await waitFor(()=>expect(result.current.state.conversation.turns).toHaveLength(1),{timeout:2500});expect(calls.filter(call=>call.path==='/api/agent/requests')).toHaveLength(1);});
test('accepted request refreshes the workspace revision before subsequent UI or reference mutations',async()=>{const original=globalThis.fetch;vi.stubGlobal('fetch',vi.fn((path:string,init?:RequestInit)=>{if(path==='/api/agent/requests'){request=view('RUNNING');workspace={...workspace,stateToken:{...workspace.stateToken,revision:7},activeAgentRequest:request};return Promise.resolve(Response.json(request));}return original(path,init);}));const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));await act(()=>result.current.submit('평균 이온 에너지가 뭐야?'));expect(result.current.state.stateToken.revision).toBe(7);expect(result.current.activeRequest?.status).toBe('RUNNING');});

test('lost submit response discovers the accepted request before an edited retry can replace it',async()=>{
 const original=globalThis.fetch;const posted:string[]=[];
 vi.stubGlobal('fetch',vi.fn((path:string,init:RequestInit={})=>{
  if(path==='/api/agent/requests'){
   posted.push(JSON.parse(String(init.body)).text);
   if(posted.length>1)return Promise.resolve(Response.json({code:'REQUEST_IN_PROGRESS',message:'이미 진행 중'},{status:409}));
   request=view('RUNNING');workspace={...workspace,stateToken:{...workspace.stateToken,revision:1},activeAgentRequest:request};
   return Promise.reject(new TypeError('response lost after acceptance'));
  }
  return original(path,init);
 }));
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 await act(()=>result.current.submit('첫 질문').catch(()=>{}));
 await act(()=>result.current.submit('수정한 질문').catch(()=>{}));
 expect(posted).toEqual(['첫 질문']);
 expect(result.current.activeRequest?.requestId).toBe('request-1');
 expect(result.current.pending).toBe(true);
 await waitFor(()=>expect(calls.some(call=>call.path==='/api/agent/requests/request-1')).toBe(true));
});

test('edited retry settles an ambiguous original submission with its original key and body',async()=>{
 const original=globalThis.fetch;const attempts:{body:string;key:string|null}[]=[];
 vi.stubGlobal('fetch',vi.fn((path:string,init:RequestInit={})=>{
  if(path==='/api/agent/requests'){
   attempts.push({body:String(init.body),key:new Headers(init.headers).get('Idempotency-Key')});
   if(attempts.length===1)return Promise.reject(new TypeError('unknown acceptance'));
  }
  return original(path,init);
 }));
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 await act(()=>result.current.submit('첫 질문').catch(()=>{}));
 await act(()=>result.current.submit('수정한 질문').catch(()=>{}));
 expect(attempts).toHaveLength(2);expect(attempts[1]).toEqual(attempts[0]);
 expect(result.current.state.conversation.turns).toHaveLength(1);
});

test.each([false,true])('reference change reconciles an accepted in-flight submission (write failure: %s)',async fail=>{
 const original=globalThis.fetch;let resolve!:(response:Response)=>void;let referenceRevision:number|undefined;
 vi.stubGlobal('fetch',vi.fn((path:string,init:RequestInit={})=>{
  if(path==='/api/agent/requests'){
   request=view('RUNNING');workspace={...workspace,stateToken:{...workspace.stateToken,revision:9},activeAgentRequest:request};
   return new Promise<Response>(done=>resolve=done);
  }
  if(path==='/api/workspace/reference'){
   const body=JSON.parse(String(init.body));referenceRevision=body.stateToken.revision;
   if(fail)return Promise.resolve(Response.json({code:'WRITE_FAILED',message:'저장 실패'},{status:500}));
   if(referenceRevision!==workspace.stateToken.revision)return Promise.resolve(Response.json({code:'STALE_CONTEXT',message:'이전 문맥'},{status:409}));
   workspace={...workspace,stateToken:{...workspace.stateToken,revision:10},candidateReference:body.candidateReference,conversation:{...workspace.conversation,activeRun:body.activeRun}};
   return Promise.resolve(Response.json(workspace));
  }
  return original(path,init);
 }));
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let submitted!:Promise<void>;act(()=>{submitted=result.current.submit('첫 질문');});await waitFor(()=>expect(resolve).toBeDefined());
 await act(()=>result.current.setReference(null,{runId:'RUN-B',runVersionId:'version-b'}).catch(()=>{}));
 expect(referenceRevision).toBe(9);
 expect(result.current.activeRequest?.requestId).toBe('request-1');expect(result.current.pending).toBe(true);
 await act(async()=>{resolve(Response.json(request));await submitted;});
 expect(result.current.activeRequest?.requestId).toBe('request-1');
 expect(result.current.state.conversation.activeRun).toEqual(fail?null:{runId:'RUN-B',runVersionId:'version-b'});
});

test('a late poll from a cancelled request cannot replace the newly accepted request',async()=>{
 const original=globalThis.fetch;let resolvePoll!:(response:Response)=>void;
 request=view('RUNNING');workspace.activeAgentRequest=request;
 vi.stubGlobal('fetch',vi.fn((path:string,init:RequestInit={})=>{
  if(path==='/api/agent/requests/request-1')return new Promise<Response>(done=>resolvePoll=done);
  if(path==='/api/agent/requests'){
   request={...view('RUNNING'),requestId:'request-2'};workspace={...workspace,activeAgentRequest:request};
   return Promise.resolve(Response.json(request));
  }
  return original(path,init);
 }));
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(resolvePoll).toBeDefined());
 await act(async()=>{
  await result.current.cancel();await result.current.submit('새 질문');
  resolvePoll(Response.json(view('RUNNING')));await Promise.resolve();await Promise.resolve();
 });
 expect(result.current.activeRequest?.requestId).toBe('request-2');
});
