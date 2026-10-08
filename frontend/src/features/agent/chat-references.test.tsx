import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import type {AgentSubmission,RunRef,TurnSnapshot,WorkspaceView} from 'agent';
import {AgentPage} from './AgentPage';
import {emptyWorkspace,initialTurnUi,useConversation} from './useConversation';
import {syntheticRun} from '../../test/runs';

const runs=[600,800,1000].map(bias=>syntheticRun(bias));
const ref=(run:RunRef):RunRef=>({runId:run.runId,runVersionId:run.runVersionId});
const turn:TurnSnapshot={id:'candidates',askedAt:'2026-10-08T00:00:00Z',question:'인공 후보 조회',intent:'REVERSE_SEARCH',context:null,answerRunRefs:runs.map(ref),answerSnapshot:JSON.parse(JSON.stringify({implementationId:'v1',schemaVersion:1,kind:'reverse_search',result:{kind:'reverse_search',resultStatus:'MATCH',commonCandidates:runs.map(run=>({run,evaluations:[]})),goalResults:[],nearMisses:[]}})),ui:structuredClone(initialTurnUi)};
function Harness(){const conversation=useConversation();return <AgentPage conversation={conversation} records={[]} notify={()=>{}} onDetail={()=>{}} onRecord={()=>{}} onEvidence={()=>{}} onDemo={async()=>{}}/>;}
function server(){
 let workspace:WorkspaceView={...structuredClone(emptyWorkspace),conversation:{version:1,activeRun:null,turns:[structuredClone(turn)]}};
 const submitted:AgentSubmission[]=[];let release:(()=>void)|undefined;let hold=false;
 vi.stubGlobal('fetch',vi.fn(async(path:string,init:RequestInit={})=>{
  if(path==='/api/agent/requests'){
   submitted.push(JSON.parse(String(init.body)));
   return Response.json({requestId:'test-request',requestRevision:0,status:'FAILED',stage:'interpret',graphVersion:'v1',question:'비교해줘',pendingInput:null,error:{code:'TEST_STOP',message:'인공 요청 접수까지만 검증'},partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]});
  }
  if(path.endsWith('/reference')){
   if(hold){hold=false;await new Promise<void>(resolve=>{release=resolve;});}
   const body=JSON.parse(String(init.body));expect(body.stateToken).toEqual(workspace.stateToken);
   workspace={...workspace,stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1},candidateReference:body.candidateReference,conversation:{...workspace.conversation,activeRun:body.activeRun}};
  }
  if(path.endsWith('/ui')){const body=JSON.parse(String(init.body));workspace={...workspace,conversation:{...workspace.conversation,turns:workspace.conversation.turns.map(t=>({...t,ui:{...t.ui,...body.ui}}))}};}
  return Response.json(workspace);
 }));
 return {get workspace(){return workspace;},submitted,holdNext:()=>{hold=true;},get release(){return release;}};
}
afterEach(()=>vi.unstubAllGlobals());

test('quickly adding three Runs accumulates exact references, deduplicates and survives reload',async()=>{
 const api=server();const frozen=structuredClone(turn);const view=render(<Harness/>);
 await screen.findAllByRole('button',{name:'채팅에 추가하기'});
 const buttons=screen.getAllByRole('button',{name:'채팅에 추가하기'});
 api.holdNext();fireEvent.click(buttons[0]);await waitFor(()=>expect(api.release).toBeDefined());
 fireEvent.click(buttons[1]);fireEvent.click(buttons[2]);fireEvent.click(buttons[0]);
 await act(async()=>api.release!());
 await waitFor(()=>expect(api.workspace.candidateReference?.runs).toEqual(runs.map(ref)));
 expect(api.workspace.conversation.activeRun).toBeNull();
 expect(api.workspace.conversation.turns[0]).toEqual(frozen);
 expect(api.submitted).toEqual([]);
 view.unmount();render(<Harness/>);
 await waitFor(()=>expect(document.querySelector('#agent-query-form .reference-tray')).toHaveTextContent('후보 집합 · 3개'));
 const composer=within(document.getElementById('agent-query-form')!);
 runs.forEach(run=>expect(composer.getByText(run.runId)).toBeVisible());
 fireEvent.change(composer.getByRole('textbox'),{target:{value:'이 세 실험을 비교해줘'}});
 fireEvent.click(composer.getByRole('button',{name:'분석'}));
 await waitFor(()=>expect(api.submitted).toHaveLength(1));
 expect(api.submitted[0].attachedRunRefs).toEqual(runs.map(ref));
 expect(api.submitted[0].referenceOrigins?.map(origin=>origin.ref)).toEqual(runs.map(ref));
 expect(api.submitted[0].baseline).toBeUndefined();
});

test('individual removal and clear do not change saved answers or leave a hidden active Run',async()=>{
 const api=server();render(<Harness/>);const buttons=await screen.findAllByRole('button',{name:'채팅에 추가하기'});
 fireEvent.click(buttons[0]);fireEvent.click(buttons[1]);fireEvent.click(buttons[2]);
 await waitFor(()=>expect(api.workspace.candidateReference?.runs).toHaveLength(3));
 const composer=within(document.getElementById('agent-query-form')!);
 fireEvent.click(composer.getByRole('button',{name:`${runs[1].runId} 채팅에서 제거`}));
 await waitFor(()=>expect(api.workspace.candidateReference?.runs).toEqual([ref(runs[0]),ref(runs[2])]));
 expect(composer.queryByText(runs[1].runId)).not.toBeInTheDocument();
 fireEvent.click(composer.getByRole('button',{name:'참조 대상 해제'}));
 await waitFor(()=>expect(api.workspace.candidateReference).toBeNull());
 expect(api.workspace.conversation.activeRun).toBeNull();
 expect(api.workspace.conversation.turns[0]).toEqual(turn);
});

test('submitting while references are saving waits for every addition and sends the question once',async()=>{
 const api=server();render(<Harness/>);const buttons=await screen.findAllByRole('button',{name:'채팅에 추가하기'});
 api.holdNext();fireEvent.click(buttons[0]);await waitFor(()=>expect(api.release).toBeDefined());
 fireEvent.click(buttons[1]);fireEvent.click(buttons[2]);
 const composer=within(document.getElementById('agent-query-form')!);
 fireEvent.change(composer.getByRole('textbox'),{target:{value:'모두 비교해줘'}});
 fireEvent.click(composer.getByRole('button',{name:'분석'}));
 expect(api.submitted).toHaveLength(0);
 await act(async()=>api.release!());
 await waitFor(()=>expect(api.submitted).toHaveLength(1));
 expect(api.submitted[0].text).toBe('모두 비교해줘');
 expect(api.submitted[0].attachedRunRefs).toEqual(runs.map(ref));
});
