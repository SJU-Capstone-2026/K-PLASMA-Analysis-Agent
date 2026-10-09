import {useEffect,useRef,useState} from 'react';
import {isV1AnswerSnapshot,type AgentMessage,type AgentRequestView,type AgentSubmission,type WorkspaceView,type ReferenceState,type RunRef,type TurnUiSnapshot,type Snapshot,type StateToken} from 'agent';
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
type DisplayPatch=Partial<Pick<TurnUiSnapshot,'activeCandidateGroup'|'selectedCandidateRunId'|'runDetailTabs'>>;
type PendingTurnUi={patch:DisplayPatch;token:StateToken};
function selectedCandidate(workspace:WorkspaceView):RunRef|undefined{
 const selected=[...workspace.conversation.turns].reverse().flatMap(turn=>{
  const id=turn.ui.selectedCandidateRunId;if(!id)return [];
  return isV1AnswerSnapshot(turn.answerSnapshot)?resolveCandidateRef(turn,id)??[]:turn.answerRunRefs.filter(ref=>ref.runId===id);
 })[0];
 return selected?asRef(selected):undefined;
}
export function useConversation(){
 const [state,setState]=useState(emptyWorkspace);const current=useRef(state);const [ready,setReady]=useState(false);const [error,setError]=useState('');
 const [activeRequest,setActiveRequest]=useState<AgentRequestView|null>(null);const active=useRef<AgentRequestView|null>(null);const [sending,setSending]=useState(false);const busy=useRef(false);
 const initialization=useRef<Promise<void>>(Promise.resolve());const generation=useRef(0);const controllers=useRef(new Set<AbortController>());const queue=useRef<Promise<unknown>>(Promise.resolve());const mounted=useRef(true);
 const workspaceNeedsSync=useRef(false);const [subscriptionRevision,setSubscriptionRevision]=useState(0);
 const pendingUi=useRef(new Map<string,PendingTurnUi[]>());const uiGeneration=useRef(0);
 const reservation=useRef(false);const [provisionalMessage,setProvisionalMessage]=useState<AgentMessage|null>(null);
 const outboxKey='kplasma.agent-outbox.v1';
 function saveOutbox(){try{if(submission.current)localStorage.setItem(outboxKey,JSON.stringify({version:1,...submission.current,message:provisionalRef.current}));else localStorage.removeItem(outboxKey);}catch{/* An unavailable local store does not block this in-memory send. */}}
 const provisionalRef=useRef<AgentMessage|null>(null);
 function showMessage(message:AgentMessage|null){provisionalRef.current=message;if(mounted.current)setProvisionalMessage(message);}
 const submission=useRef<{key:string;body:AgentSubmission;posted?:boolean}|null>(null);const resumption=useRef<{key:string;requestId:string;body:{expectedRequestRevision:number;pendingInputId:string;input:Snapshot}}|null>(null);
 function showRequest(next:AgentRequestView|null){if(JSON.stringify(active.current)===JSON.stringify(next))return;active.current=next;if(mounted.current)setActiveRequest(next);}
 // Overlay display choices only; current keeps the server's snapshots and revision.
 function displayedWorkspace():WorkspaceView{
  const next=current.current;
  return pendingUi.current.size?{...next,conversation:{...next.conversation,turns:next.conversation.turns.map(turn=>{
   const pending=pendingUi.current.get(turn.id)?.filter(item=>sameEpoch(item.token,next.stateToken));
   return pending?.length?{...turn,ui:pending.reduce((ui,item)=>({...ui,...item.patch,runDetailTabs:{...ui.runDetailTabs,...item.patch.runDetailTabs}}),turn.ui)}:turn;
  })}}:next;
 }
 function showWorkspace(){if(mounted.current)setState(displayedWorkspace());}
 function apply(next:WorkspaceView){if(sameEpoch(next.stateToken,current.current.stateToken)&&next.stateToken.revision<current.current.stateToken.revision){showWorkspace();return;}current.current=next;
  for(const [id,pending] of pendingUi.current){const valid=pending.filter(item=>sameEpoch(item.token,next.stateToken));if(!valid.length||!next.conversation.turns.some(turn=>turn.id===id))pendingUi.current.delete(id);else pendingUi.current.set(id,valid);}
  showWorkspace();showRequest(next.activeAgentRequest??next.failedAgentRequest??null);
  const message=provisionalRef.current;
  if(message&&(next.agentMessages?.some(item=>item.clientMessageId===message.clientMessageId||item.requestId===message.requestId)||next.conversation.turns.some(turn=>turn.id===message.requestId))){showMessage(null);submission.current=null;saveOutbox();}
 }
 function controller(){const next=new AbortController();controllers.current.add(next);return next;}
 function invalidate(preserveRequest=false){generation.current++;setSubscriptionRevision(value=>value+1);controllers.current.forEach(c=>c.abort());controllers.current.clear();if(!preserveRequest){uiGeneration.current++;pendingUi.current.clear();showWorkspace();showRequest(null);submission.current=null;resumption.current=null;reservation.current=false;showMessage(null);saveOutbox();}workspaceNeedsSync.current=false;busy.current=false;setSending(false);}
 async function reconcile(c:AbortController,epoch:number){const loaded=await fetchWorkspace(c.signal);if(c.signal.aborted||epoch!==generation.current)return false;workspaceNeedsSync.current=false;apply(loaded);if(loaded.activeAgentRequest){submission.current=null;saveOutbox();}return true;}
 useEffect(()=>{mounted.current=true;const c=controller();initialization.current=fetchWorkspace(c.signal).then(next=>{if(!c.signal.aborted){apply(next);try{const saved=JSON.parse(localStorage.getItem(outboxKey)??'null');if(saved?.version===1&&sameEpoch(saved.body.stateToken,next.stateToken)&&!next.agentMessages?.some(item=>item.clientMessageId===saved.key)){submission.current={key:saved.key,body:saved.body,posted:saved.posted!==false};showMessage({...saved.message,status:saved.posted===false?'SENDING':'SEND_UNCERTAIN'});}else if(saved)localStorage.removeItem(outboxKey);}catch{/* Ignore malformed browser-only outbox content. */}setReady(true);}}).catch(e=>{if(!c.signal.aborted)setError(e.message);throw e;}).finally(()=>controllers.current.delete(c));void initialization.current.catch(()=>{});return()=>{mounted.current=false;generation.current++;controllers.current.forEach(c=>c.abort());controllers.current.clear();};},[]);
 function serialize(operation:()=>Promise<void>):Promise<void>{const next=queue.current.then(async()=>{await initialization.current;await operation();});queue.current=next.catch(()=>{});return next;}
 async function accept(next:AgentRequestView,c:AbortController,epoch:number){if(c.signal.aborted||epoch!==generation.current)return;showRequest(next);if(next.status==='COMPLETED'||workspaceNeedsSync.current){const loaded=await fetchWorkspace(c.signal);if(!c.signal.aborted&&epoch===generation.current){workspaceNeedsSync.current=false;apply(loaded);setError('');}}else if(next.status==='FAILED')setError(next.error?.message??'요청 처리에 실패했습니다.');}
 // Polling owns only the browser subscription. Leaving this page never cancels server work.
 useEffect(()=>{if(!polling(activeRequest))return;const id=activeRequest!.requestId;const epoch=generation.current;const c=controller();let timer:ReturnType<typeof setTimeout>|undefined;
  async function poll(){try{const next=await fetchAgentRequest(id,c.signal);if(active.current?.requestId!==id)return;await accept(next,c,epoch);if(!c.signal.aborted&&epoch===generation.current&&running(next))timer=setTimeout(poll,750);}catch(e){if(!c.signal.aborted&&epoch===generation.current){setError(`연결을 다시 확인하는 중입니다. ${e instanceof Error?e.message:String(e)}`);timer=setTimeout(poll,2000);}}}
  timer=setTimeout(poll,350);return()=>{clearTimeout(timer);c.abort();controllers.current.delete(c);};
 },[activeRequest?.requestId,activeRequest?.status,subscriptionRevision]);
 async function submit(text:string,_clarification?:Snapshot,requestContext?:{candidateReference:ReferenceState;activeRun:RunRef|null}):Promise<void>{
  if(!text.trim()||!ready)return;if(reservation.current||busy.current||inProgress(active.current))throw new Error('진행 중인 요청을 완료하거나 취소해 주세요.');
  reservation.current=true;setSending(true);
  const token={...current.current.stateToken};const intendedSelection=selectedCandidate(displayedWorkspace());
  try{if(!submission.current){const explicit=explicitReferences(displayedWorkspace(),requestContext);const key=crypto.randomUUID();submission.current={key,posted:false,body:{text,stateToken:token,attachedRunRefs:explicit.refs.map(asRef),referenceOrigins:explicit.origins,...(intendedSelection?{selectedRunRef:asRef(intendedSelection)}:{}),...(requestContext?.activeRun?{baseline:asRef(requestContext.activeRun)}:{}),...(requestContext?.candidateReference?{candidateReferences:requestContext.candidateReference.runs.map(asRef)}:{})}};showMessage({requestId:key,clientMessageId:key,createdAt:new Date().toISOString(),question:text,submittedRunRefs:explicit.refs.map(asRef),status:'SENDING',turnId:null});saveOutbox();}}catch(e){reservation.current=false;setSending(false);throw e;}
  const newSubmission=submission.current;const recoveringDifferentText=newSubmission.body.text!==text;
  // The reservation precedes every await; clicks and Enter cannot allocate a second key.
  try{
  // Reference writes invalidate old subscriptions; start this request only after those writes finish.
  await queue.current;await initialization.current;if(!mounted.current||!sameEpoch(token,current.current.stateToken)){reservation.current=false;setSending(false);return;}
  }catch(e){reservation.current=false;setSending(false);throw e;}
  if(busy.current||inProgress(active.current)){reservation.current=false;setSending(false);throw new Error('진행 중인 요청을 완료하거나 취소해 주세요.');}
  busy.current=true;setSending(true);setError('');const c=controller();const epoch=generation.current;let attempted=false;
  try{
   if(provisionalRef.current?.status==='SEND_UNCERTAIN'){if(!await reconcile(c,epoch))return;if(inProgress(active.current))throw new Error('진행 중인 요청을 복원했습니다. 완료하거나 취소한 뒤 새 질문을 입력해 주세요.');}
   const selected=selectedCandidate(current.current);
   if(JSON.stringify(selected??null)!==JSON.stringify(intendedSelection??null))throw new Error('선택 상태를 확정하지 못했습니다. 선택을 확인한 뒤 질문을 다시 보내 주세요.');
   if(!submission.current){throw new Error('이전 요청의 처리 상태를 복원했습니다. 새 질문은 다시 입력해 주세요.');}
   if(provisionalRef.current?.status==='SENDING'){const explicit=explicitReferences(current.current,requestContext);submission.current.body={...submission.current.body,stateToken:{...current.current.stateToken},attachedRunRefs:explicit.refs.map(asRef),referenceOrigins:explicit.origins};showMessage({...provisionalRef.current,submittedRunRefs:explicit.refs.map(asRef)});}
   submission.current.posted=true;saveOutbox();
   attempted=true;const next=await submitAgentRequest(submission.current.body,submission.current.key,c.signal);if(c.signal.aborted||epoch!==generation.current)return;if(provisionalRef.current)showMessage({...provisionalRef.current,requestId:next.requestId,status:next.status,turnId:next.turnId});submission.current=null;saveOutbox();workspaceNeedsSync.current=true;await accept(next,c,epoch);if(recoveringDifferentText)throw new Error('이전 요청의 처리 상태를 복원했습니다. 새 질문은 다시 입력해 주세요.');
  }catch(e){if(!c.signal.aborted&&epoch===generation.current){if(!attempted||e instanceof ApiClientError&&e.status<500){submission.current=null;showMessage(null);saveOutbox();}else if(provisionalRef.current){showMessage({...provisionalRef.current,status:'SEND_UNCERTAIN'});saveOutbox();}try{await reconcile(c,epoch);}catch{/* Keep the original key when acceptance is still unknown. */}if(!c.signal.aborted&&epoch===generation.current){setError(e instanceof Error?e.message:String(e));throw e;}}}finally{reservation.current=false;controllers.current.delete(c);if(epoch===generation.current){busy.current=false;setSending(false);}}
 }
 async function resume(input:Snapshot){const req=active.current;if(!req?.pendingInput||req.status!=='NEEDS_INPUT'||busy.current)return;busy.current=true;setSending(true);setError('');const c=controller();const epoch=generation.current;
  try{const body={expectedRequestRevision:req.requestRevision,pendingInputId:req.pendingInput.id,input};if(!resumption.current||JSON.stringify(resumption.current.body)!==JSON.stringify(body))resumption.current={key:crypto.randomUUID(),requestId:req.requestId,body};const next=await resumeAgentRequest(req.requestId,resumption.current.body,resumption.current.key,c.signal);if(c.signal.aborted||epoch!==generation.current)return;resumption.current=null;await accept(next,c,epoch);}catch(e){if(!c.signal.aborted&&epoch===generation.current){setError(e instanceof Error?e.message:String(e));throw e;}}finally{controllers.current.delete(c);if(epoch===generation.current){busy.current=false;setSending(false);}}
 }
 async function cancel(){const req=active.current;if(!req)return;const c=controller();const epoch=generation.current;try{await accept(await cancelAgentRequest(req.requestId,c.signal),c,epoch);setError('');}finally{controllers.current.delete(c);}}
 const updateTurnUi=(id:string,patch:Partial<TurnUiSnapshot>)=>{
  const uiEpoch=uiGeneration.current;
  const displayPatch:DisplayPatch={...(patch.activeCandidateGroup!==undefined?{activeCandidateGroup:patch.activeCandidateGroup}:{}),...(patch.selectedCandidateRunId!==undefined?{selectedCandidateRunId:patch.selectedCandidateRunId}:{}),...(patch.runDetailTabs!==undefined?{runDetailTabs:{...patch.runDetailTabs}}:{})};
  const pending=Object.keys(displayPatch).length&&current.current.conversation.turns.some(turn=>turn.id===id)?{patch:displayPatch,token:{...current.current.stateToken}}:null;
  if(pending){pendingUi.current.set(id,[...(pendingUi.current.get(id)??[]),pending]);showWorkspace();}
  const clear=()=>{if(!pending)return;const remaining=pendingUi.current.get(id)?.filter(item=>item!==pending);if(remaining?.length)pendingUi.current.set(id,remaining);else pendingUi.current.delete(id);};
  return serialize(async()=>{
   if(pending&&(uiEpoch!==uiGeneration.current||!sameEpoch(pending.token,current.current.stateToken)||!current.current.conversation.turns.some(turn=>turn.id===id))){clear();showWorkspace();return;}
   try{const next=await patchTurnUi(current.current.stateToken,id,patch);clear();apply(next);}
   catch(e){
    clear();
    if(pending&&mounted.current){const c=controller();try{if(!await reconcile(c,generation.current))showWorkspace();}catch{showWorkspace();/* Restore the last confirmed state if the server is unreachable. */}finally{controllers.current.delete(c);}}else showWorkspace();
    throw e;
   }
  });
 };
 // Resolve additions/removals inside the queue, after reconciling the latest saved references.
 const setReference=(reference:ReferenceState|((state:WorkspaceView)=>ReferenceState),activeRun?:RunRef|null)=>serialize(async()=>{invalidate(true);const c=controller();const epoch=generation.current;try{if(!await reconcile(c,epoch))return;const resolved=typeof reference==='function'?reference(current.current):reference;const target=activeRun===undefined?(resolved?.runs.length===1?resolved.runs[0]:null):activeRun;const next=await writeReference(current.current.stateToken,resolved?{kind:resolved.kind,runs:resolved.runs.map(asRef)}:null,target?asRef(target):null,c.signal);if(!c.signal.aborted&&epoch===generation.current)apply(next);}catch(e){if(!c.signal.aborted&&epoch===generation.current){try{await reconcile(c,epoch);}catch{/* The last restored request stays visible while offline. */}throw e;}}finally{controllers.current.delete(c);}});
 async function refresh(){invalidate(true);await serialize(async()=>{const c=controller();try{const next=await fetchWorkspace(c.signal);if(!c.signal.aborted){apply(next);setError('');}}finally{controllers.current.delete(c);}});}
 async function replace(reset:boolean){if(ready)invalidate();await serialize(async()=>{
  if(!ready)invalidate();const c=controller();const epoch=generation.current;
  try{
   // A UI write may have committed even if its response or recovery read was interrupted.
   if(!await reconcile(c,epoch))return;
   const next=await replaceConversation(current.current.stateToken,reset);
   if(!c.signal.aborted&&epoch===generation.current){apply(next);setError('');}
  }finally{controllers.current.delete(c);}
 });}
 return {state,ready,error,provisionalMessage,pending:sending||polling(activeRequest)||activeRequest?.status==='NEEDS_INPUT',activeRequest,sending,submit,resume,cancel,updateTurnUi,setReference,refresh,newConversation:()=>replace(false),reset:()=>replace(true)};
}
export type ConversationController=ReturnType<typeof useConversation>;
