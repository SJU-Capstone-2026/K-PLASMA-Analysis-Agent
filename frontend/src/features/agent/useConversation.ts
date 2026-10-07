import {useEffect,useRef,useState} from 'react';
import {isV1AnswerSnapshot,type AgentRequestView,type AgentSubmission,type WorkspaceView,type ReferenceState,type RunRef,type TurnUiSnapshot,type Snapshot,type StateToken} from 'agent';
import {cancelAgentRequest,fetchAgentRequest,resumeAgentRequest,submitAgentRequest} from '../../api/agent';
import {ApiClientError} from '../../api/client';
import {resolveCandidateRef,explicitReferences} from './references';
import {fetchWorkspace,patchTurnUi,replaceConversation,writeReference} from '../../api/workspace';
export const emptyWorkspace:WorkspaceView={stateToken:{workspaceEpoch:0,conversationEpoch:0,revision:0},conversation:{version:1,activeRun:null,turns:[]},candidateReference:null};
export const initialTurnUi:TurnUiSnapshot={collapsed:false,openRunIds:[],runDetailTabs:{},activeCandidateGroup:'common',continuedRunId:null,lookupExpanded:false,selectedCandidateRunId:null};
const sameEpoch=(a:StateToken,b:StateToken)=>a.workspaceEpoch===b.workspaceEpoch&&a.conversationEpoch===b.conversationEpoch;
const asRef=(r:RunRef):RunRef=>({runId:r.runId,runVersionId:r.runVersionId});
const running=(r:AgentRequestView|null)=>r?.status==='QUEUED'||r?.status==='RUNNING';
const polling=(r:AgentRequestView|null)=>running(r)||r?.status==='COMPLETED';
const inProgress=(r:AgentRequestView|null)=>polling(r)||r?.status==='NEEDS_INPUT';
export function useConversation(){
 const [state,setState]=useState(emptyWorkspace);const current=useRef(state);const [ready,setReady]=useState(false);const [error,setError]=useState('');
 const [activeRequest,setActiveRequest]=useState<AgentRequestView|null>(null);const active=useRef<AgentRequestView|null>(null);const [sending,setSending]=useState(false);const busy=useRef(false);
 const initialization=useRef<Promise<void>>(Promise.resolve());const generation=useRef(0);const controllers=useRef(new Set<AbortController>());const queue=useRef<Promise<unknown>>(Promise.resolve());const mounted=useRef(true);
 const workspaceNeedsSync=useRef(false);const [subscriptionRevision,setSubscriptionRevision]=useState(0);
 const pendingTabs=useRef(new Map<string,{group:string;token:StateToken}>());const tabGeneration=useRef(0);
 const submission=useRef<{key:string;body:AgentSubmission}|null>(null);const resumption=useRef<{key:string;requestId:string;body:{expectedRequestRevision:number;pendingInputId:string;input:Snapshot}}|null>(null);
 function showRequest(next:AgentRequestView|null){if(JSON.stringify(active.current)===JSON.stringify(next))return;active.current=next;if(mounted.current)setActiveRequest(next);}
 // Only the displayed tab is optimistic; current keeps the server's snapshots and revision.
 function showWorkspace(){
  if(!mounted.current)return;const next=current.current;
  setState(pendingTabs.current.size?{...next,conversation:{...next.conversation,turns:next.conversation.turns.map(turn=>{
   const pending=pendingTabs.current.get(turn.id);
   return pending&&sameEpoch(pending.token,next.stateToken)?{...turn,ui:{...turn.ui,activeCandidateGroup:pending.group}}:turn;
  })}}:next);
 }
 function apply(next:WorkspaceView){if(sameEpoch(next.stateToken,current.current.stateToken)&&next.stateToken.revision<current.current.stateToken.revision){showWorkspace();return;}current.current=next;
  for(const [id,pending] of pendingTabs.current)if(!sameEpoch(pending.token,next.stateToken)||!next.conversation.turns.some(turn=>turn.id===id))pendingTabs.current.delete(id);
  showWorkspace();showRequest(next.activeAgentRequest??next.failedAgentRequest??null);
 }
 function controller(){const next=new AbortController();controllers.current.add(next);return next;}
 function invalidate(preserveRequest=false){generation.current++;setSubscriptionRevision(value=>value+1);controllers.current.forEach(c=>c.abort());controllers.current.clear();if(!preserveRequest){tabGeneration.current++;pendingTabs.current.clear();showWorkspace();showRequest(null);submission.current=null;resumption.current=null;}workspaceNeedsSync.current=false;busy.current=false;setSending(false);}
 async function reconcile(c:AbortController,epoch:number){const loaded=await fetchWorkspace(c.signal);if(c.signal.aborted||epoch!==generation.current)return false;workspaceNeedsSync.current=false;apply(loaded);if(loaded.activeAgentRequest)submission.current=null;return true;}
 useEffect(()=>{mounted.current=true;const c=controller();initialization.current=fetchWorkspace(c.signal).then(next=>{if(!c.signal.aborted){apply(next);setReady(true);}}).catch(e=>{if(!c.signal.aborted)setError(e.message);throw e;}).finally(()=>controllers.current.delete(c));void initialization.current.catch(()=>{});return()=>{mounted.current=false;generation.current++;controllers.current.forEach(c=>c.abort());controllers.current.clear();};},[]);
 function serialize(operation:()=>Promise<void>):Promise<void>{const next=queue.current.then(async()=>{await initialization.current;await operation();});queue.current=next.catch(()=>{});return next;}
 async function accept(next:AgentRequestView,c:AbortController,epoch:number){if(c.signal.aborted||epoch!==generation.current)return;showRequest(next);if(next.status==='COMPLETED'||workspaceNeedsSync.current){const loaded=await fetchWorkspace(c.signal);if(!c.signal.aborted&&epoch===generation.current){workspaceNeedsSync.current=false;apply(loaded);setError('');}}else if(next.status==='FAILED')setError(next.error?.message??'요청 처리에 실패했습니다.');}
 // Polling owns only the browser subscription. Leaving this page never cancels server work.
 useEffect(()=>{if(!polling(activeRequest))return;const id=activeRequest!.requestId;const epoch=generation.current;const c=controller();let timer:ReturnType<typeof setTimeout>|undefined;
  async function poll(){try{const next=await fetchAgentRequest(id,c.signal);if(active.current?.requestId!==id)return;await accept(next,c,epoch);if(!c.signal.aborted&&epoch===generation.current&&running(next))timer=setTimeout(poll,750);}catch(e){if(!c.signal.aborted&&epoch===generation.current){setError(`연결을 다시 확인하는 중입니다. ${e instanceof Error?e.message:String(e)}`);timer=setTimeout(poll,2000);}}}
  timer=setTimeout(poll,350);return()=>{clearTimeout(timer);c.abort();controllers.current.delete(c);};
 },[activeRequest?.requestId,activeRequest?.status,subscriptionRevision]);
 async function submit(text:string,_clarification?:Snapshot,requestContext?:{candidateReference:ReferenceState;activeRun:RunRef|null}):Promise<void>{
  if(!text.trim()||!ready)return;if(busy.current||inProgress(active.current))throw new Error('진행 중인 요청을 완료하거나 취소해 주세요.');
  busy.current=true;setSending(true);setError('');const c=controller();const epoch=generation.current;const token={...current.current.stateToken};
  try{await queue.current;await initialization.current;if(c.signal.aborted||epoch!==generation.current||!sameEpoch(token,current.current.stateToken))return;
   const recoveringDifferentText=!!submission.current&&submission.current.body.text!==text;
   if(submission.current){if(!await reconcile(c,epoch))return;if(inProgress(active.current))throw new Error('진행 중인 요청을 복원했습니다. 완료하거나 취소한 뒤 새 질문을 입력해 주세요.');}
   const selected=[...current.current.conversation.turns].reverse().flatMap(turn=>{
    const id=turn.ui.selectedCandidateRunId;if(!id)return [];
    return isV1AnswerSnapshot(turn.answerSnapshot)?resolveCandidateRef(turn,id)??[]:turn.answerRunRefs.filter(ref=>ref.runId===id);
   })[0];
   if(!submission.current){const explicit=explicitReferences(current.current,requestContext);submission.current={key:crypto.randomUUID(),body:{text,stateToken:current.current.stateToken,attachedRunRefs:explicit.refs,referenceOrigins:explicit.origins,...(selected?{selectedRunRef:asRef(selected)}:{}),...(requestContext?.activeRun?{baseline:asRef(requestContext.activeRun)}:{}),...(requestContext?.candidateReference?{candidateReferences:requestContext.candidateReference.runs.map(asRef)}:{})}};}
   const next=await submitAgentRequest(submission.current.body,submission.current.key,c.signal);if(c.signal.aborted||epoch!==generation.current)return;submission.current=null;workspaceNeedsSync.current=true;await accept(next,c,epoch);if(recoveringDifferentText)throw new Error('이전 요청의 처리 상태를 복원했습니다. 새 질문은 다시 입력해 주세요.');
  }catch(e){if(!c.signal.aborted&&epoch===generation.current){if(e instanceof ApiClientError&&e.status<500)submission.current=null;try{await reconcile(c,epoch);}catch{/* Keep the original key when acceptance is still unknown. */}if(!c.signal.aborted&&epoch===generation.current){setError(e instanceof Error?e.message:String(e));throw e;}}}finally{controllers.current.delete(c);if(epoch===generation.current){busy.current=false;setSending(false);}}
 }
 async function resume(input:Snapshot){const req=active.current;if(!req?.pendingInput||req.status!=='NEEDS_INPUT'||busy.current)return;busy.current=true;setSending(true);setError('');const c=controller();const epoch=generation.current;
  try{const body={expectedRequestRevision:req.requestRevision,pendingInputId:req.pendingInput.id,input};if(!resumption.current||JSON.stringify(resumption.current.body)!==JSON.stringify(body))resumption.current={key:crypto.randomUUID(),requestId:req.requestId,body};const next=await resumeAgentRequest(req.requestId,resumption.current.body,resumption.current.key,c.signal);if(c.signal.aborted||epoch!==generation.current)return;resumption.current=null;await accept(next,c,epoch);}catch(e){if(!c.signal.aborted&&epoch===generation.current){setError(e instanceof Error?e.message:String(e));throw e;}}finally{controllers.current.delete(c);if(epoch===generation.current){busy.current=false;setSending(false);}}
 }
 async function cancel(){const req=active.current;if(!req)return;const c=controller();const epoch=generation.current;try{await accept(await cancelAgentRequest(req.requestId,c.signal),c,epoch);setError('');}finally{controllers.current.delete(c);}}
 const updateTurnUi=(id:string,patch:Partial<TurnUiSnapshot>)=>{
  const tabEpoch=tabGeneration.current;
  const pending=patch.activeCandidateGroup!==undefined&&current.current.conversation.turns.some(turn=>turn.id===id)?{group:patch.activeCandidateGroup,token:{...current.current.stateToken}}:null;
  if(pending){pendingTabs.current.set(id,pending);showWorkspace();}
  const clear=()=>{if(pending&&pendingTabs.current.get(id)===pending)pendingTabs.current.delete(id);};
  return serialize(async()=>{
   if(pending&&(tabEpoch!==tabGeneration.current||!sameEpoch(pending.token,current.current.stateToken))){clear();showWorkspace();return;}
   try{const next=await patchTurnUi(current.current.stateToken,id,patch);clear();apply(next);}
   catch(e){
    clear();
    if(pending&&mounted.current){const c=controller();try{if(!await reconcile(c,generation.current))showWorkspace();}catch{showWorkspace();/* Restore the last confirmed state if the server is unreachable. */}finally{controllers.current.delete(c);}}else showWorkspace();
    throw e;
   }
  });
 };
 const setReference=(reference:ReferenceState,activeRun?:RunRef|null)=>serialize(async()=>{invalidate(true);const c=controller();const epoch=generation.current;try{if(!await reconcile(c,epoch))return;const target=activeRun===undefined?(reference?.runs.length===1?reference.runs[0]:null):activeRun;const next=await writeReference(current.current.stateToken,reference?{kind:reference.kind,runs:reference.runs.map(asRef)}:null,target?asRef(target):null,c.signal);if(!c.signal.aborted&&epoch===generation.current)apply(next);}catch(e){if(!c.signal.aborted&&epoch===generation.current){try{await reconcile(c,epoch);}catch{/* The last restored request stays visible while offline. */}throw e;}}finally{controllers.current.delete(c);}});
 async function refresh(){invalidate();await serialize(async()=>{const c=controller();try{const next=await fetchWorkspace(c.signal);if(!c.signal.aborted){apply(next);setError('');}}finally{controllers.current.delete(c);}});}
 async function replace(reset:boolean){if(ready)invalidate();await serialize(async()=>{
  if(!ready)invalidate();const c=controller();const epoch=generation.current;
  try{
   // A tab write may have committed even if its response or recovery read was interrupted.
   if(!await reconcile(c,epoch))return;
   const next=await replaceConversation(current.current.stateToken,reset);
   if(!c.signal.aborted&&epoch===generation.current){apply(next);setError('');}
  }finally{controllers.current.delete(c);}
 });}
 return {state,ready,error,pending:sending||polling(activeRequest)||activeRequest?.status==='NEEDS_INPUT',activeRequest,sending,submit,resume,cancel,updateTurnUi,setReference,refresh,newConversation:()=>replace(false),reset:()=>replace(true)};
}
export type ConversationController=ReturnType<typeof useConversation>;
