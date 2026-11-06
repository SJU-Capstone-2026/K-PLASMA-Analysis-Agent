import {memo,useCallback,useLayoutEffect,useRef,useState,type SetStateAction} from 'react';
import {isGraphV2AnswerSnapshot,queryDefaultUnits} from 'agent';
import {metricNames,searchGroups,snapshotResult,type SearchResult} from './agent-contract';
import type {AgentMessage,DecisionRecord,ReferenceState,RunRef,Snapshot,TurnSnapshot,V2RecordSource} from 'agent';
import {ReferenceTray} from '../../components/ReferenceTray';
import {RunColorsProvider} from '../../components/RunColors';
import {AnswerView} from './AnswerView';
import {PendingRequest} from './PendingRequest';
import {CompletedAgentProgress} from './AgentProgress';
import {answerTextSize} from './progress-events';
import {RunMentionComposer} from './RunMentionComposer';
import type {ConversationController} from './useConversation';
export interface AgentPageProps {conversation:ConversationController;records:DecisionRecord[];notify:(text:string,tone?:string)=>void;onDetail:(ref:RunRef,turn:TurnSnapshot)=>void;onRecord:(turn:TurnSnapshot,source?:V2RecordSource,target?:RunRef)=>void;onEvidence:(turn:TurnSnapshot,runId:string)=>void;onDemo:()=>Promise<void>}
import {appendRunReferences,candidateRefs,displayAnswer,removeRunReference,resolveCandidateRef} from './references';
export {candidateRefs} from './references';
const reference=(refs:RunRef[]):ReferenceState=>refs.length?{kind:refs.length===1?'단일 Run':'후보 집합',runs:refs}:null;
const examples=[['example-forward','Run 조건 조회','8 mTorr · Source 300 W · Bias 600 W','압력 8 mTorr, 소스 300 W, 바이어스 600 W 결과를 보여줘'],['example-constraint','조건 일치 전체 조회','조건에 맞는 실제 Run 모두 보기','Ion Flux가 400 이상이고 Mean Ion Energy가 140–180 eV인 실제 Run을 모두 보여줘'],['example-reverse','목표 후보 탐색','Flux는 높게 · Energy는 범위에 가깝게','Ion Flux는 높게, Mean Ion Energy는 150–160 eV에 가깝게 후보를 찾아줘'],['example-comparison','Run 비교','기준 Run과 선택 Run의 수치 차이','기준 Run과 선택한 Run의 평균 이온 에너지와 이온 플럭스를 비교해줘'],['example-explanation','변화 설명','소스 전력 변화가 결과에 미친 영향','소스 전력을 올렸는데 플럭스는 많이 변하고 평균 이온 에너지는 상대적으로 적게 변했어. 왜 그런 거야?'],['example-concept','개념 설명','평균 이온 에너지가 뭐야?','평균 이온 에너지가 뭐야?']];
type TurnAction=(turnId:string,name:string,element:HTMLElement)=>void;
const v2Examples = [
 ['v2-search-compare', '검색 후 비교', '범위 안 후보의 압력과 Flux 비교',
  '평균 이온 에너지가 150–160 eV인 실제 Run을 모두 찾아서, 찾은 Run 전체의 압력과 이온 플럭스를 비교해줘.'],
 ['v2-two-searches', '두 조건 따로 검색', '에너지 범위별로 Flux 높은 순',
  '평균 이온 에너지가 140–149 eV인 후보와 150–160 eV인 후보를 각각 찾아줘. 두 그룹을 따로 보여주고 각 그룹 안에서는 이온 플럭스가 높은 순으로 정렬해줘.'],
 ['v2-derived-search', '비교값으로 다시 검색', '선택한 두 Run의 Flux를 기준으로 검색',
  '선택한 두 Run의 이온 플럭스와 평균 이온 에너지를 비교해줘. 그런 다음 두 Run 모두보다 이온 플럭스가 높고, 평균 이온 에너지가 150–160 eV인 후보를 찾아줘.'],
];
function UserMessage({question,refs}:{question:string;refs:RunRef[]}){return <div className="agent-user-message">{refs.length>0&&<ReferenceTray references={refs}/>}<p>{question}</p></div>;}
const ConversationTurn=memo(function ConversationTurn({turn,message,onAction}:{turn:TurnSnapshot;message?:AgentMessage;onAction:TurnAction}){
 const saved=displayAnswer(turn.answerSnapshot).reference;
 const refs=message?.submittedRunRefs??(saved?.ids?.length?saved.ids.flatMap((id:string)=>turn.answerRunRefs.find(ref=>ref.runId===id)??[]):turn.context?[turn.context]:[]);
 return <article className="agent-turn" data-turn-id={turn.id}><UserMessage question={message?.question??turn.question} refs={refs}/><section className="agent-response agent-response--inline"><CompletedAgentProgress summary={message?.executionSummary}/><div id={`turn-answer-${turn.id}`}><AnswerView turn={turn} onAction={(name,element)=>onAction(turn.id,name,element)}/></div></section></article>;
});
export function AgentPage({conversation,notify,onDetail,onRecord,onEvidence,onDemo}:AgentPageProps){
 const {state,pending}=conversation;const colorScope=`${state.stateToken.workspaceEpoch}.${state.stateToken.conversationEpoch}`;const turns=state.conversation.turns;const active=state.conversation.activeRun;const composer=state.candidateReference??(active?reference([active]):null);
 const [drafts,setDrafts]=useState<Record<string,string>>({});
 const text=drafts[colorScope]??'';
 function setText(update:SetStateAction<string>){
  setDrafts(current=>({...current,[colorScope]:typeof update==='function'?update(current[colorScope]??''):update}));
 }
 useLayoutEffect(()=>{setDrafts({});},[state.stateToken.workspaceEpoch]);
 const catchError=(e:unknown)=>notify(e instanceof Error?e.message:String(e),'info');
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
 async function run(text:string,clarification?:Snapshot){followingLatest.current=true;setShowLatestButton(false);try{const submitted=conversation.submit(text,clarification);setText(current=>current===text?'':current);await submitted;}catch(e){setText(current=>current||text);catchError(e);}}
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
   if(isGraphV2AnswerSnapshot(turn.answerSnapshot)){
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
  else if(name==='open-v2-step-record'&&ref&&isGraphV2AnswerSnapshot(turn.answerSnapshot)){
   const step=turn.answerSnapshot.stepResults.find(step=>step.executionId===element.dataset.executionId);
   const groupId=element.dataset.groupId;
   if(step&&groupId&&step.runRefs.some(r=>r.runId===ref.runId&&r.runVersionId===ref.runVersionId)){
    onRecord(turn,{turnId:turn.id,executionId:step.executionId,stepId:step.stepId,groupId},ref);
   }
  }
  else if(name==='open-experiment-record'&&!isGraphV2AnswerSnapshot(turn.answerSnapshot))onRecord(turn);
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

 return <RunColorsProvider key={colorScope} scope={colorScope} enabled={conversation.ready}><div className="agent-page agent-page--wide"><header className="agent-page-header"><div><span className="eyebrow">CONVERSATIONAL EVIDENCE ANALYSIS</span><h1>K-PLASMA 분석 Agent</h1><p>결론과 실제 수치를 먼저 보고, 필요한 실험 상세만 펼쳐 확인합니다.</p></div><div className="agent-page-actions"><label className="agent-graph-choice">Agent 버전 <select aria-label="Agent 버전" value={conversation.graphVersion} disabled={!conversation.ready||pending||!!conversation.provisionalMessage||!!state.conversation.agentGraphVersion||turns.length>0} onChange={event=>conversation.selectGraphVersion(event.target.value==='v2'?'v2':'v1')}><option value="v1">v1</option><option value="v2">v2</option></select></label><div className="agent-trust-row"><span><i className="status-dot status-dot--success"/>등록된 실제 Run</span><span>예측·보간 없음</span></div><button className="button button--ghost button--small" type="button" data-action="new-conversation" disabled={!turns.length&&!conversation.activeRequest&&!state.conversation.agentGraphVersion&&!state.agentMessages?.length} onClick={()=>conversation.newConversation().catch(catchError)}>새 대화</button></div></header><section ref={liveRegion} className="agent-conversation agent-conversation--wide"><details className="agent-help"><summary>사용 도움말</summary><details className="v1-unit-help"><summary>단위 없이도 조회할 수 있어요 · 기본 단위 보기</summary><ul>{Object.entries(queryDefaultUnits).map(([metric,unit])=><li key={metric}>{metricNames[metric]} <strong>{unit}</strong></li>)}</ul><p>예: 압력 8, 소스 300, 바이어스 600 · 이온 플럭스 400 이상</p><p>단위를 쓰면 입력한 단위를 우선합니다. 생략하면 적용한 기본 단위를 답변에서 알려드립니다.</p></details>{active?<div className="agent-quick-followups"><span>이 Run에서 이어서</span>{[['전체 결과·분포','이 Run의 전체 결과와 이온 에너지 분포 보여줘'],['Energy만 조금 높게','이 결과에서 이온 에너지만 조금 더 높은 실제 조건 찾아줘'],['왜 이런 결과인지','왜 이런 결과가 나왔는지 설명해줘']].map(([label,prompt])=><button key={label} type="button" data-action="use-followup" data-prompt={prompt} disabled={pending} onClick={()=>void run(prompt)}>{label}</button>)}</div>:null}<div className="memory-demo-actions"><span>기록 활용 시연 데이터가 필요하다면</span><button className="button button--ghost button--small" type="button" data-action="memory-demo" onClick={()=>onDemo().catch(catchError)}>데모 기록 불러오기</button><small>실제 사용자 기록과 구분되어 이 브라우저에만 저장됩니다.</small></div></details>
 <div className="agent-example-groups">
  <div className="agent-examples" aria-label="분석 예시">{examples.map(([action,label,title,prompt])=><button key={action} type="button" data-action={action} disabled={pending||!conversation.ready} onClick={()=>void run(prompt)}><span>{label}</span><strong>{title}</strong></button>)}</div>
  {conversation.graphVersion==='v2'&&<section className="agent-v2-examples" aria-label="v2 평가 예시">
   <p>v2 복합 질문 평가</p>
   <div className="agent-examples">
    {v2Examples.map(([action,label,title,prompt])=><button key={action} type="button" data-action={action}
      title={prompt} disabled={pending||!conversation.ready} onClick={()=>void run(prompt)}>
      <span>{label}</span><strong>{title}</strong>
    </button>)}
   </div>
  </section>}
 </div>
 <div className="agent-thread" aria-live="polite">{thread.length?thread.map(item=>item.turn?<ConversationTurn key={item.id} turn={item.turn} message={item.message} onAction={dispatchAction}/>:<div key={item.id}><UserMessage question={item.message!.question} refs={item.message!.submittedRunRefs}/>{item.message!.requestId!==conversation.activeRequest?.requestId&&['FAILED','CANCELLED'].includes(item.message!.status)&&<p className="v1-limitation">{item.message!.status==='FAILED'?'분석을 완료하지 못했습니다.':'분석을 취소했습니다.'}</p>}</div>):!conversation.provisionalMessage&&!conversation.activeRequest?<div className="agent-welcome panel"><div className="agent-welcome-mark" aria-hidden="true">K</div><h2>실제 Run과 공정 원리를 함께 설명합니다</h2><p>조건 조회, 목표 후보 탐색, 결과 변화와 기본 개념을 한 대화에서 이어갈 수 있습니다.</p><div><span>Registered Runs</span><span>예측·보간 없음</span><span>개념·근거 구분</span></div></div>:null}{conversation.provisionalMessage&&!state.agentMessages?.some(message=>message.clientMessageId===conversation.provisionalMessage?.clientMessageId||message.requestId===conversation.provisionalMessage?.requestId)&&!turns.some(turn=>turn.id===conversation.provisionalMessage?.requestId)&&<UserMessage question={conversation.provisionalMessage.question} refs={conversation.provisionalMessage.submittedRunRefs}/>}{conversation.activeRequest&&!state.agentMessages?.some(message=>message.requestId===conversation.activeRequest?.requestId)&&!conversation.provisionalMessage&&!turns.some(turn=>turn.id===conversation.activeRequest?.requestId)&&<UserMessage question={conversation.activeRequest.question} refs={[]}/>}</div>
 {conversation.activeRequest&&<PendingRequest request={conversation.activeRequest} resultPreview={conversation.resultPreview} hideQuestion sending={conversation.sending} onResume={conversation.resume} onCancel={conversation.cancel} onError={catchError}/>}
 {conversation.provisionalMessage&&!conversation.sending&&!conversation.activeRequest&&<div className="v1-card-actions"><span>{conversation.provisionalMessage.status==='SEND_UNCERTAIN'?'전송 수락 여부를 확인하지 못했습니다.':'아직 전송하지 않은 질문입니다.'}</span><button type="button" className="button button--ghost button--small" onClick={()=>void run(conversation.provisionalMessage!.question)}>같은 질문 다시 보내기</button></div>}
 {conversation.error&&<div className="alert alert--danger" role="alert">{conversation.error}</div>}<div className="agent-composer-dock">
  {showLatestButton&&<button className="agent-jump-latest" type="button" aria-label="최신 답변으로 이동"
    title="최신 답변으로 이동" onClick={jumpToLatest}>
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
     <path d="M12 5v14m-6-6 6 6 6-6"/>
    </svg>
  </button>}
  <form id="agent-query-form" className="agent-composer panel" onSubmit={event=>{event.preventDefault();void run(text);}}>{composer&&<ReferenceTray references={composer.runs} onRemove={()=>void clear()} onRemoveRun={ref=>void conversation.setReference(state=>removeRunReference(state,ref)).catch(catchError)}/>}<RunMentionComposer text={text} onText={setText} add={ref=>addRunTag(ref,'catalog')} disabled={pending||!conversation.ready}/></form></div></section></div></RunColorsProvider>;
}
