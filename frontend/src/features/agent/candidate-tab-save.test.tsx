import {act,fireEvent,render,renderHook,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {toRunSummary,type ReferenceState,type RunRef,type StateToken,type TurnUiSnapshot,type WorkspaceView} from 'agent';
import {syntheticRun} from '../../test/runs';
import {emptyWorkspace,initialTurnUi,useConversation} from './useConversation';
import {TurnDetailDialog} from './TurnDetailDialog';

let workspace:WorkspaceView;
let saves:{token:StateToken;ui:Partial<TurnUiSnapshot>;finish:(failure?:'rejected'|'lost-response')=>void}[];
beforeEach(()=>{
 workspace=structuredClone(emptyWorkspace);
 workspace.conversation.turns=[{id:'turn-1',askedAt:'2026-10-05T00:00:00Z',question:'후보 찾기',intent:'REVERSE_SEARCH',context:null,answerRunRefs:[],answerSnapshot:{implementationId:'v1',kind:'reverse_search',schemaVersion:1,result:{kind:'reverse_search',resultStatus:'MATCH',commonCandidates:[],goalResults:[],objectiveResults:[]}},ui:structuredClone(initialTurnUi)}];
 saves=[];
 vi.stubGlobal('fetch',vi.fn((path:string,init:RequestInit={})=>{
  if(path.endsWith('/ui')){
   const body=JSON.parse(String(init.body)) as {stateToken:StateToken;ui:Partial<TurnUiSnapshot>};
   return new Promise<Response>((resolve,reject)=>saves.push({token:body.stateToken,ui:body.ui,finish(failure){
    if(failure==='rejected'){resolve(Response.json({code:'WRITE_FAILED',message:'탭 저장 실패'},{status:500}));return;}
    if(JSON.stringify(body.stateToken)!==JSON.stringify(workspace.stateToken)){resolve(Response.json({code:'STALE_CONTEXT',message:'이전 문맥'},{status:409}));return;}
    workspace={...workspace,stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1},conversation:{...workspace.conversation,turns:workspace.conversation.turns.map(turn=>({...turn,ui:{...turn.ui,...body.ui,runDetailTabs:{...turn.ui.runDetailTabs,...body.ui.runDetailTabs}}}))}};
    if(failure==='lost-response')reject(new TypeError('응답 연결 끊김'));else resolve(Response.json(workspace));
   }}));
  }
  if(init.method){
   const body=JSON.parse(String(init.body)) as {stateToken:StateToken;candidateReference:ReferenceState;activeRun:RunRef|null};
   if(JSON.stringify(body.stateToken)!==JSON.stringify(workspace.stateToken))return Promise.resolve(Response.json({code:'STALE_CONTEXT',message:'이전 문맥'},{status:409}));
   if(path.endsWith('/reference'))workspace={...workspace,stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1},candidateReference:body.candidateReference,conversation:{...workspace.conversation,activeRun:body.activeRun}};
   if(path.endsWith('/new-conversation')||path.endsWith('/reset'))workspace={...workspace,stateToken:{workspaceEpoch:workspace.stateToken.workspaceEpoch+(path.endsWith('/reset')?1:0),conversationEpoch:workspace.stateToken.conversationEpoch+1,revision:workspace.stateToken.revision+1},conversation:{version:1,activeRun:null,turns:[]}};
  }
  if(path==='/api/workspace'||path.endsWith('/reference')||path.endsWith('/new-conversation')||path.endsWith('/reset'))return Promise.resolve(Response.json(workspace));
  throw new Error(`Unexpected transport: ${path}`);
 }));
});

const displayCases=[
 {name:'card',first:{selectedCandidateRunId:'RUN-A'},second:{selectedCandidateRunId:null},read:(ui:TurnUiSnapshot)=>ui.selectedCandidateRunId,before:null,one:'RUN-A',two:null},
 {name:'graph tab',first:{runDetailTabs:{'RUN-A':'ied'}},second:{runDetailTabs:{'RUN-A':'residual'}},read:(ui:TurnUiSnapshot)=>ui.runDetailTabs['RUN-A'],before:undefined,one:'ied',two:'residual'},
] satisfies {name:string;first:Partial<TurnUiSnapshot>;second:Partial<TurnUiSnapshot>;read:(ui:TurnUiSnapshot)=>unknown;before:unknown;one:unknown;two:unknown}[];

test.each(displayCases)('$name updates before the save response and restores on reload',async({first,read,before,one})=>{
 const hook=renderHook(()=>useConversation());await waitFor(()=>expect(hook.result.current.ready).toBe(true));
 const snapshot=hook.result.current.state.conversation.turns[0].answerSnapshot;
 let saved!:Promise<void>;act(()=>{saved=hook.result.current.updateTurnUi('turn-1',first);});
 expect(read(hook.result.current.state.conversation.turns[0].ui)).toBe(one);
 await waitFor(()=>expect(saves).toHaveLength(1));
 expect(read(workspace.conversation.turns[0].ui)).toBe(before);
 expect(hook.result.current.state.stateToken.revision).toBe(0);
 expect(hook.result.current.state.conversation.turns[0].answerSnapshot).toBe(snapshot);
 await act(async()=>{saves[0].finish();await saved;});hook.unmount();
 const reloaded=renderHook(()=>useConversation());await waitFor(()=>expect(reloaded.result.current.ready).toBe(true));
 expect(read(reloaded.result.current.state.conversation.turns[0].ui)).toBe(one);
 expect(reloaded.result.current.state.conversation.turns[0].answerSnapshot).toEqual(snapshot);
});

test.each(displayCases)('$name keeps the latest click while an older response arrives',async({first,second,read,two})=>{
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let a!:Promise<void>;let b!:Promise<void>;
 act(()=>{a=result.current.updateTurnUi('turn-1',first);});await waitFor(()=>expect(saves).toHaveLength(1));
 act(()=>{b=result.current.updateTurnUi('turn-1',second);});
 expect(read(result.current.state.conversation.turns[0].ui)).toBe(two);
 await act(async()=>{saves[0].finish();await a;});await waitFor(()=>expect(saves).toHaveLength(2));
 expect(read(result.current.state.conversation.turns[0].ui)).toBe(two);
 expect(saves[1].token.revision).toBe(1);
 await act(async()=>{saves[1].finish();await b;});
 expect(read(workspace.conversation.turns[0].ui)).toBe(two);
});

test.each(displayCases)('$name keeps the newer choice when the earlier save fails',async({first,second,read,two})=>{
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let a!:Promise<unknown>;let b!:Promise<void>;
 act(()=>{a=result.current.updateTurnUi('turn-1',first).catch(e=>e);});await waitFor(()=>expect(saves).toHaveLength(1));
 act(()=>{b=result.current.updateTurnUi('turn-1',second);});
 await act(async()=>{saves[0].finish('rejected');await a;});await waitFor(()=>expect(saves).toHaveLength(2));
 expect(read(result.current.state.conversation.turns[0].ui)).toBe(two);
 expect(saves[1].token.revision).toBe(0);
 await act(async()=>{saves[1].finish();await b;});
 expect(read(workspace.conversation.turns[0].ui)).toBe(two);
});

for(const failure of ['rejected','lost-response'] as const)test.each(displayCases)(`$name reconciles the server after ${failure}`,async({first,read,before,one})=>{
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let outcome!:Promise<unknown>;act(()=>{outcome=result.current.updateTurnUi('turn-1',first).catch(e=>e);});
 expect(read(result.current.state.conversation.turns[0].ui)).toBe(one);
 await waitFor(()=>expect(saves).toHaveLength(1));await act(async()=>{saves[0].finish(failure);await outcome;});
 expect(await outcome).toBeInstanceOf(Error);
 expect(read(result.current.state.conversation.turns[0].ui)).toBe(failure==='rejected'?before:one);
});

test('pending card, graph and result tab changes do not replace each other',async()=>{
 workspace.conversation.turns[0].ui.runDetailTabs={'RUN-B':'density'};
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let card!:Promise<void>;let graph!:Promise<void>;let tab!:Promise<void>;
 act(()=>{card=result.current.updateTurnUi('turn-1',{selectedCandidateRunId:'RUN-A'});graph=result.current.updateTurnUi('turn-1',{runDetailTabs:{'RUN-A':'ied'}});tab=result.current.updateTurnUi('turn-1',{activeCandidateGroup:'objective-0'});});
 const expected={selectedCandidateRunId:'RUN-A',runDetailTabs:{'RUN-A':'ied','RUN-B':'density'},activeCandidateGroup:'objective-0'};
 expect(result.current.state.conversation.turns[0].ui).toMatchObject(expected);
 for(const [index,operation] of [card,graph,tab].entries()){
  await waitFor(()=>expect(saves).toHaveLength(index+1));await act(async()=>{saves[index].finish();await operation;});
  expect(result.current.state.conversation.turns[0].ui).toMatchObject(expected);
 }
});

for(const action of ['newConversation','reset'] as const)test.each(displayCases)(`${action} clears pending $name writes`,async({first,second})=>{
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let a!:Promise<void>;let b!:Promise<void>;let replacement!:Promise<void>;
 act(()=>{a=result.current.updateTurnUi('turn-1',first);});await waitFor(()=>expect(saves).toHaveLength(1));
 act(()=>{b=result.current.updateTurnUi('turn-1',second);replacement=result.current[action]();});
 await act(async()=>{saves[0].finish();await a;await b;await replacement;});
 expect(saves).toHaveLength(1);expect(result.current.state.conversation.turns).toEqual([]);
});

for(const selecting of [true,false])for(const failure of [undefined,'rejected','lost-response'] as const)test(`question waits for and verifies Run ${selecting?'selection':'deselection'} (${failure??'success'})`,async()=>{
 const run=syntheticRun();const ref={runId:run.runId,runVersionId:run.runVersionId};
 workspace.conversation.turns[0].answerRunRefs=[ref];
 workspace.conversation.turns[0].answerSnapshot.result=JSON.parse(JSON.stringify({kind:'reverse_search',resultStatus:'MATCH',commonCandidates:[{run:toRunSummary(run),evaluations:[]}]}));
 if(!selecting)workspace.conversation.turns[0].ui.selectedCandidateRunId=run.runId;
 let submitted:unknown;const original=globalThis.fetch;
 vi.stubGlobal('fetch',vi.fn((path:string,init:RequestInit={})=>{
  if(path==='/api/agent/requests'){submitted=JSON.parse(String(init.body));return Promise.resolve(Response.json({requestId:'diagnostic-request',requestRevision:0,status:'FAILED',stage:'interpret',graphVersion:'v1',question:'선택한 실험 설명',pendingInput:null,error:{code:'TEST',message:'실행 전 중단'},partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]}));}
  return original(path,init);
 }));
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let save!:Promise<unknown>;let question!:Promise<unknown>;
 act(()=>{save=result.current.updateTurnUi('turn-1',{selectedCandidateRunId:selecting?run.runId:null}).catch(e=>e);});
 await waitFor(()=>expect(saves).toHaveLength(1));
 act(()=>{question=result.current.submit('선택한 실험 설명').catch(e=>e);});
 expect(submitted).toBeUndefined();
 await act(async()=>{saves[0].finish(failure);await save;await question;});
 if(failure==='rejected'){expect(submitted).toBeUndefined();expect(await question).toBeInstanceOf(Error);}
 else {expect(submitted).toMatchObject({stateToken:{revision:1}});if(selecting)expect(submitted).toHaveProperty('selectedRunRef',ref);else expect(submitted).not.toHaveProperty('selectedRunRef');}
});

test('a rejected first graph-tab save restores the default tab in the open dialog',async()=>{
 const run=syntheticRun();const original=globalThis.fetch;
 vi.stubGlobal('fetch',vi.fn((path:string,init:RequestInit={})=>path.startsWith('/api/run-versions/')?Promise.resolve(Response.json(run)):original(path,init)));
 function Harness(){const conversation=useConversation();const ui=conversation.state.conversation.turns[0]?.ui;
  return ui?<TurnDetailDialog runRef={run} turnId="turn-1" tab={ui.runDetailTabs[run.runId]} onClose={()=>{}} onTabChange={tab=>void conversation.updateTurnUi('turn-1',{runDetailTabs:{[run.runId]:tab}}).catch(()=>{})}/>:null;
 }
 const view=render(<Harness/>);
 await waitFor(()=>expect(view.container.querySelector('[data-tab="ied"]')).toHaveAttribute('aria-selected','true'));
 fireEvent.click(view.container.querySelector('[data-tab="residual"]')!);
 expect(view.container.querySelector('[data-tab="residual"]')).toHaveAttribute('aria-selected','true');
 await waitFor(()=>expect(saves).toHaveLength(1));await act(async()=>{saves[0].finish('rejected');});
 await waitFor(()=>expect(view.container.querySelector('[data-tab="ied"]')).toHaveAttribute('aria-selected','true'));
});
afterEach(()=>vi.unstubAllGlobals());

test('candidate tab changes before the save response and restores from the server on reload',async()=>{
 const hook=renderHook(()=>useConversation());await waitFor(()=>expect(hook.result.current.ready).toBe(true));
 const answer=hook.result.current.state.conversation.turns[0].answerSnapshot;
 let saved!:Promise<void>;act(()=>{saved=hook.result.current.updateTurnUi('turn-1',{activeCandidateGroup:'goal-0'});});
 await waitFor(()=>expect(saves).toHaveLength(1));
 expect(hook.result.current.state.conversation.turns[0].ui.activeCandidateGroup).toBe('goal-0');
 expect(workspace.conversation.turns[0].ui.activeCandidateGroup).toBe('common');
 expect(hook.result.current.state.stateToken.revision).toBe(0);
 expect(hook.result.current.state.conversation.turns[0].answerSnapshot).toBe(answer);
 await act(async()=>{saves[0].finish();await saved;});
 hook.unmount();const reloaded=renderHook(()=>useConversation());await waitFor(()=>expect(reloaded.result.current.ready).toBe(true));
 expect(reloaded.result.current.state.conversation.turns[0].ui.activeCandidateGroup).toBe('goal-0');
 expect(reloaded.result.current.state.stateToken.revision).toBe(1);
 expect(reloaded.result.current.state.conversation.turns[0].answerSnapshot).toEqual(answer);
});

test('an earlier tab save response cannot replace the latest visible selection',async()=>{
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let first!:Promise<void>;act(()=>{first=result.current.updateTurnUi('turn-1',{activeCandidateGroup:'goal-0'});});
 await waitFor(()=>expect(saves).toHaveLength(1));
 let second!:Promise<void>;act(()=>{second=result.current.updateTurnUi('turn-1',{activeCandidateGroup:'objective-0'});});
 expect(result.current.state.conversation.turns[0].ui.activeCandidateGroup).toBe('objective-0');
 await act(async()=>{saves[0].finish();await first;});await waitFor(()=>expect(saves).toHaveLength(2));
 expect(result.current.state.conversation.turns[0].ui.activeCandidateGroup).toBe('objective-0');
 expect(saves[1].token.revision).toBe(1);
 await act(async()=>{saves[1].finish();await second;});
 expect(result.current.state.conversation.turns[0].ui.activeCandidateGroup).toBe('objective-0');
 expect(workspace.conversation.turns[0].ui.activeCandidateGroup).toBe('objective-0');
});

test.each(['rejected','lost-response'] as const)('failed tab save reconciles the actual saved selection (%s)',async failure=>{
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let outcome!:Promise<unknown>;act(()=>{outcome=result.current.updateTurnUi('turn-1',{activeCandidateGroup:'goal-0'}).catch(error=>error);});
 await waitFor(()=>expect(saves).toHaveLength(1));
 expect(result.current.state.conversation.turns[0].ui.activeCandidateGroup).toBe('goal-0');
 await act(async()=>{saves[0].finish(failure);await outcome;});
 expect(await outcome).toBeInstanceOf(Error);
 expect(result.current.state.conversation.turns[0].ui.activeCandidateGroup).toBe(failure==='rejected'?'common':'goal-0');
 expect(result.current.state.stateToken.revision).toBe(failure==='rejected'?0:1);
});

test('reference change preserves a tab selection queued behind it in the same conversation',async()=>{
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let first!:Promise<void>;act(()=>{first=result.current.updateTurnUi('turn-1',{activeCandidateGroup:'goal-0'});});
 await waitFor(()=>expect(saves).toHaveLength(1));
 const ref={runId:'RUN-REFERENCE',runVersionId:'reference-version'};
 let reference!:Promise<void>;let second!:Promise<void>;
 act(()=>{reference=result.current.setReference(null,ref);second=result.current.updateTurnUi('turn-1',{activeCandidateGroup:'objective-0'});});
 expect(result.current.state.conversation.turns[0].ui.activeCandidateGroup).toBe('objective-0');
 await act(async()=>{saves[0].finish();await first;await reference;});
 expect(result.current.state.conversation.turns[0].ui.activeCandidateGroup).toBe('objective-0');
 await waitFor(()=>expect(saves).toHaveLength(2));
 expect(saves[1].token.revision).toBe(2);
 await act(async()=>{saves[1].finish();await second;});
 expect(result.current.state.conversation.activeRun).toEqual(ref);
 expect(workspace.conversation.turns[0].ui.activeCandidateGroup).toBe('objective-0');
});

test.each([
 ['newConversation',undefined],['reset',undefined],['newConversation','lost-response'],['reset','lost-response'],
] as const)('%s clears pending tab selections and prevents queued old-tab writes (response: %s)',async(action,failure)=>{
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let first!:Promise<unknown>;act(()=>{first=result.current.updateTurnUi('turn-1',{activeCandidateGroup:'goal-0'}).catch(error=>error);});
 await waitFor(()=>expect(saves).toHaveLength(1));
 let second!:Promise<void>;let replaced!:Promise<unknown>;let replacementDone=false;
 act(()=>{second=result.current.updateTurnUi('turn-1',{activeCandidateGroup:'objective-0'});replaced=result.current[action]().catch(error=>error).finally(()=>{replacementDone=true;});});
 await act(async()=>{saves[0].finish(failure);await first;});
 await waitFor(()=>expect(saves.length===2||replacementDone).toBe(true));
 await act(async()=>{saves[1]?.finish();await second;await replaced;});
 expect(await replaced).toBeUndefined();
 expect(saves).toHaveLength(1);
 expect(result.current.state.conversation.turns).toEqual([]);
 expect(workspace.conversation.turns).toEqual([]);
});

test.each(['newConversation','reset'] as const)('%s recovers the saved revision when it interrupts tab-save reconciliation',async action=>{
 const original=globalThis.fetch;let reads=0;let recovering=false;
 vi.stubGlobal('fetch',vi.fn((path:string,init:RequestInit={})=>{
  if(path==='/api/workspace'&&++reads===2)return new Promise<Response>((_resolve,reject)=>{
   recovering=true;init.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});
  });
  return original(path,init);
 }));
 const {result}=renderHook(()=>useConversation());await waitFor(()=>expect(result.current.ready).toBe(true));
 let first!:Promise<unknown>;act(()=>{first=result.current.updateTurnUi('turn-1',{activeCandidateGroup:'goal-0'}).catch(error=>error);});
 await waitFor(()=>expect(saves).toHaveLength(1));
 await act(async()=>{saves[0].finish('lost-response');});await waitFor(()=>expect(recovering).toBe(true));
 let outcome:unknown;await act(async()=>{outcome=await result.current[action]().catch(error=>error);await first;});
 expect(outcome).toBeUndefined();
 expect(result.current.state.conversation.turns).toEqual([]);
 expect(workspace.conversation.turns).toEqual([]);
});
