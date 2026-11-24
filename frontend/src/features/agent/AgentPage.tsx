import {memo,useCallback,useLayoutEffect,useRef,useState,type SetStateAction} from 'react';
import {isCompositeAnswerSnapshot} from 'agent';
import {graphDeployment,isAnalysisGraphVersion,pinnedConversationGraph} from './graph-versions';
import {searchGroups,snapshotResult,type SearchResult} from './agent-contract';
import type {AgentMessage,DecisionRecord,ReferenceState,RunRef,Snapshot,TurnSnapshot,V2RecordSource} from 'agent';
import {ReferenceTray} from '../../components/ReferenceTray';
import {BrandMark} from '../../components/BrandMark';
import {RunColorsProvider} from '../../components/RunColors';
import {AnswerView} from './AnswerView';
import {PendingRequest} from './PendingRequest';
import {CompletedAgentProgress} from './AgentProgress';
import {answerTextSize} from './progress-events';
import {RunMentionComposer} from './RunMentionComposer';
import {AgentUserMessage} from './AgentUserMessage';
import type {ConversationController} from './useConversation';
import './analysis-agent.css';
export interface AgentPageProps {conversation:ConversationController;records:DecisionRecord[];notify:(text:string,tone?:string)=>void;onDetail:(ref:RunRef,turn:TurnSnapshot)=>void;onRecord:(turn:TurnSnapshot,source?:V2RecordSource,target?:RunRef)=>void;onEvidence:(turn:TurnSnapshot,runId:string)=>void}
import {appendRunReferences,candidateRefs,displayAnswer,removeRunReference,resolveCandidateRef} from './references';
export {candidateRefs} from './references';
const reference=(refs:RunRef[]):ReferenceState=>refs.length?{kind:refs.length===1?'단일 Run':'후보 집합',runs:refs}:null;
const exampleQuestions = [
 ['example-forward', '압력 8 · 소스 300 · 바이어스 600 결과는?', '압력 8 mTorr, 소스 300 W, 바이어스 600 W 결과를 보여줘'],
 ['example-constraint', 'Flux 400 이상 · Energy 140–180 eV인 Run은?', 'Ion Flux가 400 이상이고 Mean Ion Energy가 140–180 eV인 실제 Run을 모두 보여줘'],
 ['example-reverse', 'Flux는 높고 Energy는 150–160 eV에 가까운 후보는?', 'Ion Flux는 높게, Mean Ion Energy는 150–160 eV에 가깝게 후보를 찾아줘'],
 ['example-comparison', '기준 Run과 선택한 Run의 수치 차이는?', '기준 Run과 선택한 Run의 평균 이온 에너지와 이온 플럭스를 비교해줘'],
 ['example-explanation', '소스 전력을 올리면 왜 플럭스가 더 변해?', '소스 전력을 올렸는데 플럭스는 많이 변하고 평균 이온 에너지는 상대적으로 적게 변했어. 왜 그런 거야?'],
 ['example-concept', '평균 이온 에너지가 뭐야?', '평균 이온 에너지가 뭐야?'],
 ['v2-search-compare', '150–160 eV Run의 압력과 플럭스를 비교해줘', '평균 이온 에너지가 150–160 eV인 실제 Run을 모두 찾아서, 찾은 Run 전체의 압력과 이온 플럭스를 비교해줘.'],
 ['v2-two-searches', '두 에너지 범위의 후보를 Flux 높은 순으로 보여줘', '평균 이온 에너지가 140–149 eV인 후보와 150–160 eV인 후보를 각각 찾아줘. 두 그룹을 따로 보여주고 각 그룹 안에서는 이온 플럭스가 높은 순으로 정렬해줘.'],
 ['v2-derived-search', '선택한 두 Run보다 Flux가 높은 후보는?', '선택한 두 Run의 이온 플럭스와 평균 이온 에너지를 비교해줘. 그런 다음 두 Run 모두보다 이온 플럭스가 높고, 평균 이온 에너지가 150–160 eV인 후보를 찾아줘.'],
] as const;
const graphModes = [{version:'v2',label:'일반'},{version:'v2_localLLM',label:'로컬'}] as const;
type AnalysisGraphMode=typeof graphModes[number]['version'];
type TurnAction=(turnId:string,name:string,element:HTMLElement)=>void;
const ConversationTurn=memo(function ConversationTurn({turn,message,onAction}:{turn:TurnSnapshot;message?:AgentMessage;onAction:TurnAction}){
 const saved=displayAnswer(turn.answerSnapshot).reference;
 const refs=message?.submittedRunRefs??(saved?.ids?.length?saved.ids.flatMap((id:string)=>turn.answerRunRefs.find(ref=>ref.runId===id)??[]):turn.context?[turn.context]:[]);
 return <article className="agent-turn" data-turn-id={turn.id}><AgentUserMessage question={message?.question??turn.question} refs={refs}/><section className="agent-response agent-response--inline"><CompletedAgentProgress summary={message?.executionSummary}/><div id={`turn-answer-${turn.id}`}><AnswerView turn={turn} onAction={(name,element)=>onAction(turn.id,name,element)}/></div></section></article>;
});
export function AgentPage({conversation,notify,onDetail,onRecord,onEvidence}:AgentPageProps){
 const {state,pending}=conversation;const colorScope=`${state.stateToken.workspaceEpoch}.${state.stateToken.conversationEpoch}`;const turns=state.conversation.turns;const active=state.conversation.activeRun;const composer=state.candidateReference??(active?reference([active]):null);
 const graphVersions=graphDeployment().versions;
 const [changingMode,setChangingMode]=useState(false);
 const pinnedGraph=pinnedConversationGraph(state.conversation);
 const archivedConversation=!!pinnedGraph&&(!isAnalysisGraphVersion(pinnedGraph)||!graphVersions.includes(pinnedGraph));
 const hasConversation=!!(turns.length||conversation.activeRequest||state.conversation.agentGraphVersion||state.agentMessages?.length);
 const [drafts,setDrafts]=useState<Record<string,string>>({});
 const text=drafts[colorScope]??'';
 function setText(update:SetStateAction<string>){
  setDrafts(current=>({...current,[colorScope]:typeof update==='function'?update(current[colorScope]??''):update}));
 }
 useLayoutEffect(()=>{setDrafts({});},[state.stateToken.workspaceEpoch]);
 const catchError=(e:unknown)=>notify(e instanceof Error?e.message:String(e),'info');
 const canStop=conversation.activeRequest?.status==='RUNNING'||conversation.activeRequest?.status==='QUEUED';
 async function addRunTag(ref:RunRef,source?:V2RecordSource|'catalog'){
  if(pending||!conversation.ready)return false;
  try {
   await conversation.setReference(state=>appendRunReferences(state,[ref],source));
   notify(`${ref.runId}을 채팅에 추가했습니다.`,'info');
   return true;
  } catch(error) {
   catchError(error);
   return false;
  }
 }
 async function run(text:string,clarification?:Snapshot){if(changingMode||archivedConversation)return;followingLatest.current=true;setShowLatestButton(false);try{const submitted=conversation.submit(text,clarification);setText(current=>current===text?'':current);await submitted;}catch(e){setText(current=>current||text);catchError(e);}}
 async function action(turn:TurnSnapshot,name:string,element:HTMLElement){const runId=element.dataset.runId;const ref=runId?(element.dataset.runVersionId?{runId,runVersionId:element.dataset.runVersionId}:resolveCandidateRef(turn,runId)):undefined;try{
  if(name==='select-candidate-card')await conversation.updateTurnUi(turn.id,{selectedCandidateRunId:turn.ui.selectedCandidateRunId===runId?null:runId!});
  else if(name==='candidate-group')await conversation.updateTurnUi(turn.id,{activeCandidateGroup:element.dataset.groupId!});
  else if(name==='continue-with-run'&&ref){
   const executionId=element.dataset.executionId,stepId=element.dataset.stepId,groupId=element.dataset.groupId;
   const source=executionId&&stepId&&groupId?{turnId:turn.id,executionId,stepId,groupId}:undefined;
   await addRunTag(ref,source);
  }
  else if(name==='reference-candidate-group'){
   let refs=candidateRefs(turn);
   let source:V2RecordSource|undefined;
   if(isCompositeAnswerSnapshot(turn.answerSnapshot)){
    const step=turn.answerSnapshot.stepResults.find(s=>s.executionId===element.dataset.executionId);
    const result=step?.outputs.toolResult;
    if(!step||!result||typeof result!=='object'||Array.isArray(result))return;
    const group=searchGroups(snapshotResult<SearchResult>({result:result as Snapshot})).find(g=>g.id===element.dataset.groupId);
    if(!group)return;
    refs=group.runs.map(({runId,runVersionId})=>({runId,runVersionId}));
    source={turnId:turn.id,executionId:step.executionId,stepId:step.stepId,groupId:group.id};
   }
   await conversation.setReference(state=>appendRunReferences(state,refs,source));
   notify(`${refs.length}개 후보를 채팅에 추가했습니다.`,'info');
  }
  else if(name==='open-run-detail'&&ref)onDetail(ref,turn);
  else if(name==='open-v2-step-record'&&ref&&isCompositeAnswerSnapshot(turn.answerSnapshot)){
   const step=turn.answerSnapshot.stepResults.find(step=>step.executionId===element.dataset.executionId);
   const groupId=element.dataset.groupId;
   if(step&&groupId&&step.runRefs.some(r=>r.runId===ref.runId&&r.runVersionId===ref.runVersionId)){
    onRecord(turn,{turnId:turn.id,executionId:step.executionId,stepId:step.stepId,groupId},ref);
   }
  }
  else if(name==='open-experiment-record'&&!isCompositeAnswerSnapshot(turn.answerSnapshot))onRecord(turn);
  else if(name==='memory-evidence'&&runId)onEvidence(turn,runId);
  else if(name==='agent-use-suggestion')await run(element.dataset.prompt??'');
  else if(name==='memory-threshold'||name==='memory-undo'){
   const memory=displayAnswer(turn.answerSnapshot).memoryRequest!;const threshold=name==='memory-undo'?memory.threshold:Number(element.dataset.count??(document.getElementById(`threshold-${turn.id}`) as HTMLInputElement)?.value);
   if(name==='memory-threshold'&&(!Number.isInteger(threshold)||Number(threshold)<1)){notify('제외 기준은 1건 이상의 정수로 입력해 주세요.','info');return;}
   const ids:string[]=memory.reference?.ids??[];const refs=memory.referenceRunRefs??ids.flatMap(id=>turn.answerRunRefs.find(ref=>ref.runId===id)??[]);
   await conversation.submit(memory.text,{threshold,undo:name==='memory-undo',useSuppliedMemoryReference:true},{candidateReference:reference(refs),activeRun:turn.context});setText('');
  }
 }catch(e){catchError(e);}}
 // Keep memoized rows independent of parent callbacks, while actions use the latest committed turn.
 const committedActions=useRef({action,turns});
 useLayoutEffect(()=>{committedActions.current={action,turns};});
 const dispatchAction=useCallback<TurnAction>((id,name,element)=>{
  const current=committedActions.current;const turn=current.turns.find(turn=>turn.id===id);
  if(turn)void current.action(turn,name,element);
 },[]);
 const clear=()=>conversation.setReference(null,null).catch(catchError);
 const thread:Array<{id:string;at:string;turn?:TurnSnapshot;message?:AgentMessage}>=[
  ...turns.map(turn=>({id:turn.id,at:turn.askedAt,turn,message:state.agentMessages?.find(message=>message.requestId===turn.id||message.turnId===turn.id)})),
  ...(state.agentMessages??[]).filter(message=>!turns.some(turn=>turn.id===message.requestId||turn.id===message.turnId)).map(message=>({id:message.requestId,at:message.createdAt,message})),
 ].sort((a,b)=>a.at.localeCompare(b.at));
 const latest = thread.at(-1);
 const latestAnswer = Boolean(latest?.turn);
 const latestAnswerId = thread.filter(item => item.turn).at(-1)?.id;
 const lastSeenAnswer = useRef<{scope:string;id?:string} | null>(null);
 const followingLatest = useRef(false);
 const [showLatestButton,setShowLatestButton] = useState(false);
 const liveRegion=useRef<HTMLElement|null>(null);
 const jumpToLatest = useCallback(() => {
  followingLatest.current = true;
  setShowLatestButton(false);
  const page = document.scrollingElement;
  if (page) page.scrollTop = page.scrollHeight;
 }, []);
 useLayoutEffect(() => {
  if (!conversation.ready) return;
  let previousTop = document.scrollingElement?.scrollTop ?? 0;
  let previousHeight = document.scrollingElement?.scrollHeight ?? 0;
  const update = () => {
   const page = document.scrollingElement;
   if (!page) return;
   const atBottom = page.scrollHeight - page.clientHeight - page.scrollTop <= 32;
   const reachedPreviousBottom = page.scrollHeight > previousHeight
    && previousHeight - page.clientHeight - page.scrollTop <= 32;
   // Deferred Markdown can grow the page without the reader scrolling away.
   if (atBottom || reachedPreviousBottom && page.scrollTop >= previousTop) {
    followingLatest.current = true;
    setShowLatestButton(false);
   } else if (page.scrollTop < previousTop) followingLatest.current = false;
   previousTop = page.scrollTop;
   previousHeight = page.scrollHeight;
  };
  update();
  window.addEventListener('scroll', update, {passive: true});
  window.addEventListener('resize', update);
  return () => {
   window.removeEventListener('scroll', update);
   window.removeEventListener('resize', update);
  };
 }, [colorScope, conversation.ready]);
 useLayoutEffect(() => {
  if (!conversation.ready) return;
  const previous = lastSeenAnswer.current;
  lastSeenAnswer.current = {scope:colorScope,id:latestAnswerId};
  if (previous?.scope !== colorScope) setShowLatestButton(false);
  else if (latestAnswerId && latestAnswerId !== previous.id && !followingLatest.current) {
   setShowLatestButton(true);
  }
 }, [colorScope, conversation.ready, latestAnswerId]);
 useLayoutEffect(() => {
  if (!conversation.ready || !followingLatest.current) return;
  jumpToLatest();
 }, [conversation.ready, latest?.id, latestAnswer, conversation.provisionalMessage?.requestId,
  conversation.activeRequest?.requestId, jumpToLatest]);
 const liveAnswerSize=answerTextSize(conversation.activeRequest?.progress?.answer);
 const liveAnswerRevision=conversation.activeRequest?.progress?.answer?.answerRevision;
 const liveResultRevision=conversation.resultPreview?.resultRevision;
 const liveSeen=useRef<{scope:string;size:number;result?:number} | null>(null);
 useLayoutEffect(()=>{
  const region=liveRegion.current;if(!region||typeof ResizeObserver==='undefined')return;
  let frame=0;
  const observer=new ResizeObserver(()=>{
   if(!followingLatest.current)return;
   cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(followingLatest.current)jumpToLatest();});
  });
  observer.observe(region);
  return()=>{observer.disconnect();cancelAnimationFrame(frame);};
 },[colorScope,jumpToLatest]);
 useLayoutEffect(()=>{
  if(!conversation.ready)return;
  const previous=liveSeen.current;
  liveSeen.current={scope:colorScope,size:liveAnswerSize,result:liveResultRevision};
  if(previous?.scope!==colorScope)return;
  if(followingLatest.current)jumpToLatest();
  else if(liveAnswerSize>previous.size||liveResultRevision!==previous.result&&liveResultRevision!==undefined)setShowLatestButton(true);
 },[colorScope,conversation.ready,liveAnswerSize,liveAnswerRevision,liveResultRevision,jumpToLatest]);

 async function changeMode(version:AnalysisGraphMode){
  if(changingMode||version===conversation.graphVersion)return;
  setChangingMode(true);
  try{
   if(hasConversation)await conversation.newConversation();
   conversation.selectGraphVersion(version);
  }catch(error){catchError(error);}
  finally{setChangingMode(false);}
 }

 return <RunColorsProvider key={colorScope} scope={colorScope} enabled={conversation.ready}>
 <div className="agent-page agent-page--wide analysis-agent">
 <header className="agent-page-header analysis-agent-header">
  <div className="analysis-agent-modes" role="group" aria-label="분석 실행 모드">
   {graphModes.map(({version,label})=><button key={version} type="button"
    aria-pressed={conversation.graphVersion===version}
    disabled={!graphVersions.includes(version)||!conversation.ready||pending&&!archivedConversation||changingMode||!!conversation.provisionalMessage}
    onClick={()=>void changeMode(version)}>{label}</button>)}
  </div>
  {hasConversation&&<button className="button button--ghost button--small" type="button" data-action="new-conversation"
   disabled={changingMode} onClick={()=>conversation.newConversation().catch(catchError)}>새 대화</button>}
 </header>
 <section ref={liveRegion} className="agent-conversation agent-conversation--wide">
 <div className="agent-thread" aria-live="polite">{thread.length?thread.map(item=>item.turn?<ConversationTurn key={item.id} turn={item.turn} message={item.message} onAction={dispatchAction}/>:<div key={item.id}><AgentUserMessage question={item.message!.question} refs={item.message!.submittedRunRefs}/>{item.message!.requestId!==conversation.activeRequest?.requestId&&['FAILED','CANCELLED'].includes(item.message!.status)&&(item.message!.status==='CANCELLED'?<CompletedAgentProgress status="CANCELLED" summary={item.message!.executionSummary}/>:<p className="v1-limitation">분석을 완료하지 못했습니다.</p>)}</div>):!conversation.provisionalMessage&&!conversation.activeRequest?<section className="agent-welcome analysis-agent-welcome">
  <BrandMark className="agent-welcome-mark"/>
  <h1>실험 결과와 공정 조건을 질문해 보세요.</h1>
  <details className="analysis-agent-examples">
   <summary>대표 질문으로 시작해 보세요</summary>
   <ul aria-label="대표 질문">
    {exampleQuestions.map(([action,label,prompt])=><li key={action}>
     <button type="button" data-action={action} title={prompt} aria-label={prompt} disabled={pending||changingMode||!conversation.ready}
      onClick={()=>void run(prompt)}>{label}</button>
    </li>)}
   </ul>
  </details>
 </section>:null}{conversation.provisionalMessage&&!state.agentMessages?.some(message=>message.clientMessageId===conversation.provisionalMessage?.clientMessageId||message.requestId===conversation.provisionalMessage?.requestId)&&!turns.some(turn=>turn.id===conversation.provisionalMessage?.requestId)&&<AgentUserMessage question={conversation.provisionalMessage.question} refs={conversation.provisionalMessage.submittedRunRefs}/>}{conversation.activeRequest&&!state.agentMessages?.some(message=>message.requestId===conversation.activeRequest?.requestId)&&!conversation.provisionalMessage&&!turns.some(turn=>turn.id===conversation.activeRequest?.requestId)&&<AgentUserMessage question={conversation.activeRequest.question} refs={[]}/>}</div>
 {!archivedConversation&&conversation.activeRequest&&<PendingRequest request={conversation.activeRequest} resultPreview={conversation.resultPreview} hideQuestion sending={conversation.sending} onResume={conversation.resume} onCancel={conversation.cancel} onError={catchError}/>}
 {conversation.provisionalMessage&&!conversation.sending&&!conversation.activeRequest&&<div className="v1-card-actions"><span>{conversation.provisionalMessage.status==='SEND_UNCERTAIN'?'전송 수락 여부를 확인하지 못했습니다.':'아직 전송하지 않은 질문입니다.'}</span><button type="button" className="button button--ghost button--small" onClick={()=>void run(conversation.provisionalMessage!.question)}>같은 질문 다시 보내기</button></div>}
 {archivedConversation&&<p className="analysis-agent-history-note">이전 대화입니다. 새 대화에서 질문을 이어갈 수 있어요.</p>}
 {conversation.error&&<div className="alert alert--danger" role="alert">{conversation.error}</div>}<div className="agent-composer-dock">
  {showLatestButton&&<button className="agent-jump-latest" type="button" aria-label="최신 답변으로 이동"
    title="최신 답변으로 이동" onClick={jumpToLatest}>
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
     <path d="M12 5v14m-6-6 6 6 6-6"/>
    </svg>
  </button>}
  <form id="agent-query-form" className="agent-composer panel" onSubmit={event=>{event.preventDefault();void run(text);}}>{composer&&<ReferenceTray references={composer.runs} onRemove={()=>void clear()} onRemoveRun={ref=>void conversation.setReference(state=>removeRunReference(state,ref)).catch(catchError)}/>}<RunMentionComposer text={text} onText={setText} add={ref=>addRunTag(ref,'catalog')} disabled={pending||changingMode||archivedConversation||!conversation.ready} onStop={canStop?()=>conversation.cancel().catch(catchError):undefined}/></form></div></section></div></RunColorsProvider>;
}
