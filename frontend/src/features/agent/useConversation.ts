import {useEffect,useRef,useState} from 'react';
import {executeFallback,type WorkspaceView,type ReferenceState,type RunRef,type TurnUiSnapshot,type Snapshot,type StateToken} from 'agent';
import {latestCandidateRefs} from './references';
import {fetchRuns,fetchRunVersion} from '../../api/runs';
import {fetchDecisions} from '../../api/decisions';
import {appendTurn,fetchWorkspace,patchTurnUi,replaceConversation,writeReference} from '../../api/workspace';
export const emptyWorkspace:WorkspaceView={stateToken:{workspaceEpoch:0,conversationEpoch:0,revision:0},conversation:{version:1,activeRun:null,turns:[]},candidateReference:null};
export const initialTurnUi:TurnUiSnapshot={collapsed:false,openRunIds:[],runDetailTabs:{},activeCandidateGroup:'common',continuedRunId:null,lookupExpanded:false,selectedCandidateRunId:null};
const sameToken=(a:StateToken,b:StateToken)=>a.workspaceEpoch===b.workspaceEpoch&&a.conversationEpoch===b.conversationEpoch&&a.revision===b.revision;
const asRef=(r:RunRef):RunRef=>({runId:r.runId,runVersionId:r.runVersionId});
export function useConversation(){
 const [state,setState]=useState(emptyWorkspace);const current=useRef(state);const [ready,setReady]=useState(false);const [error,setError]=useState('');const [pending,setPending]=useState(false);
 const generation=useRef(0);const controllers=useRef(new Set<AbortController>());const queue=useRef<Promise<unknown>>(Promise.resolve());const mounted=useRef(true);
 const apply=(next:WorkspaceView)=>{current.current=next;if(mounted.current)setState(next);};
 useEffect(()=>{mounted.current=true;const controller=new AbortController();controllers.current.add(controller);fetchWorkspace(controller.signal).then(next=>{if(!controller.signal.aborted){apply(next);setReady(true);}}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>{mounted.current=false;generation.current++;controllers.current.forEach(c=>c.abort());controllers.current.clear();};},[]);
 function serialize(operation:()=>Promise<void>):Promise<void>{const next=queue.current.then(operation);queue.current=next.catch(()=>{});return next;}
 function invalidate(){generation.current++;controllers.current.forEach(c=>c.abort());controllers.current.clear();setPending(false);}
 async function submit(text:string,clarification?:Snapshot,requestContext?:{candidateReference:ReferenceState;activeRun:RunRef|null},question=text):Promise<void>{
  if(!text.trim()||!ready)return;
  if(pending)throw new Error('분석이 진행 중입니다.');
  const controller=new AbortController();controllers.current.add(controller);const epoch=generation.current;const token={...current.current.stateToken};const context=requestContext?{...current.current,candidateReference:requestContext.candidateReference,conversation:{...current.current.conversation,activeRun:requestContext.activeRun}}:current.current;setPending(true);setError('');
  const stale=()=>controller.signal.aborted||epoch!==generation.current||!sameToken(token,current.current.stateToken);
  try{
   const runs=await fetchRuns(controller.signal);if(stale())return;
   const records=await fetchDecisions(controller.signal);if(stale())return;
   const response=await executeFallback({text,baseline:context.conversation.activeRun??undefined,candidateReferences:context.candidateReference?.runs??[],clarification},{candidateRunsLatest:runs,latestCandidateReferences:latestCandidateRefs(context.conversation.turns),decisionRecords:records,referenceRunsByVersion:new Map(),hydrateFullRun:ref=>fetchRunVersion(ref,controller.signal)});
   if(stale())return;
   const id=crypto.randomUUID();const turn={id,askedAt:new Date().toISOString(),question,intent:response.intent,context:context.conversation.activeRun,answerRunRefs:response.usedRunRefs.map(asRef),answerSnapshot:response.answerSnapshot,ui:{...initialTurnUi,runDetailTabs:{},openRunIds:[]}};
   await serialize(async()=>{if(stale())return;const next=await appendTurn(token,turn,id,controller.signal);if(!stale())apply(next);});
  }catch(e){if(!controller.signal.aborted&&epoch===generation.current){const message=e instanceof Error?e.message:String(e);setError(message);throw e;}}
  finally{controllers.current.delete(controller);if(epoch===generation.current)setPending(false);}
 }
 const updateTurnUi=(id:string,patch:Partial<TurnUiSnapshot>)=>serialize(async()=>{const next=await patchTurnUi(current.current.stateToken,id,patch);apply(next);});
 const setReference=(reference:ReferenceState,activeRun?:RunRef|null)=>serialize(async()=>{invalidate();const target=activeRun===undefined?(reference?.runs.length===1?reference.runs[0]:null):activeRun;const next=await writeReference(current.current.stateToken,reference?{kind:reference.kind,runs:reference.runs.map(asRef)}:null,target?asRef(target):null);apply(next);});
 async function replace(reset:boolean){invalidate();await serialize(async()=>{const next=await replaceConversation(current.current.stateToken,reset);apply(next);setError('');});}
 return {state,ready,error,pending,submit,updateTurnUi,setReference,newConversation:()=>replace(false),reset:()=>replace(true)};
}
export type ConversationController=ReturnType<typeof useConversation>;
