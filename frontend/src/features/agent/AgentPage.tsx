import {memo,useCallback,useLayoutEffect,useRef,useState} from 'react';
import {queryDefaultUnits} from 'agent';
import {metricNames} from './agent-contract';
import type {DecisionRecord,ReferenceState,RunRef,Snapshot,TurnSnapshot} from 'agent';
import {ReferenceTray} from '../../components/ReferenceTray';
import {RunColorsProvider} from '../../components/RunColors';
import {AnswerView} from './AnswerView';
import {PendingRequest} from './PendingRequest';
import type {ConversationController} from './useConversation';
export interface AgentPageProps {conversation:ConversationController;records:DecisionRecord[];notify:(text:string,tone?:string)=>void;onDetail:(ref:RunRef,turn:TurnSnapshot)=>void;onRecord:(turn:TurnSnapshot)=>void;onEvidence:(turn:TurnSnapshot,runId:string)=>void;onDemo:()=>Promise<void>}
import {appendRunReferences,candidateRefs,displayAnswer,removeRunReference,resolveCandidateRef} from './references';
export {candidateRefs} from './references';
const reference=(refs:RunRef[]):ReferenceState=>refs.length?{kind:refs.length===1?'단일 Run':'후보 집합',runs:refs}:null;
const examples=[['example-forward','Run 조건 조회','8 mTorr · Source 300 W · Bias 600 W','압력 8 mTorr, 소스 300 W, 바이어스 600 W 결과를 보여줘'],['example-constraint','조건 일치 전체 조회','조건에 맞는 실제 Run 모두 보기','Ion Flux가 400 이상이고 Mean Ion Energy가 140–180 eV인 실제 Run을 모두 보여줘'],['example-reverse','목표 후보 탐색','Flux는 높게 · Energy는 범위에 가깝게','Ion Flux는 높게, Mean Ion Energy는 150–160 eV에 가깝게 후보를 찾아줘'],['example-comparison','Run 비교','기준 Run과 선택 Run의 수치 차이','기준 Run과 선택한 Run의 평균 이온 에너지와 이온 플럭스를 비교해줘'],['example-explanation','변화 설명','소스 전력 변화가 결과에 미친 영향','소스 전력을 올렸는데 플럭스는 많이 변하고 평균 이온 에너지는 상대적으로 적게 변했어. 왜 그런 거야?'],['example-concept','개념 설명','평균 이온 에너지가 뭐야?','평균 이온 에너지가 뭐야?']];
type TurnAction=(turnId:string,name:string,element:HTMLElement)=>void;
const ConversationTurn=memo(function ConversationTurn({turn,onAction}:{turn:TurnSnapshot;onAction:TurnAction}){
 const saved=displayAnswer(turn.answerSnapshot).reference;
 const refs=saved?.ids?.length?saved.ids.flatMap((id:string)=>turn.answerRunRefs.find(ref=>ref.runId===id)??[]):turn.context?[turn.context]:[];
 return <article className="agent-turn" data-turn-id={turn.id}><div className="agent-user-message">{refs.length?<ReferenceTray references={refs}/>:<span>질문</span>}<p>{turn.question}</p></div><section className="agent-response panel"><div id={`turn-answer-${turn.id}`}><AnswerView turn={turn} onAction={(name,element)=>onAction(turn.id,name,element)}/></div></section></article>;
});
export function AgentPage({conversation,notify,onDetail,onRecord,onEvidence,onDemo}:AgentPageProps){
 const [text,setText]=useState('');const {state,pending}=conversation;const colorScope=`${state.stateToken.workspaceEpoch}.${state.stateToken.conversationEpoch}`;const turns=state.conversation.turns;const active=state.conversation.activeRun;const composer=state.candidateReference??(active?reference([active]):null);
 const catchError=(e:unknown)=>notify(e instanceof Error?e.message:String(e),'info');
 async function run(text:string,clarification?:Snapshot){try{await conversation.submit(text,clarification);setText('');}catch(e){catchError(e);}}
 async function action(turn:TurnSnapshot,name:string,element:HTMLElement){const runId=element.dataset.runId;const ref=runId?(element.dataset.runVersionId?{runId,runVersionId:element.dataset.runVersionId}:resolveCandidateRef(turn,runId)):undefined;try{
  if(name==='select-candidate-card')await conversation.updateTurnUi(turn.id,{selectedCandidateRunId:turn.ui.selectedCandidateRunId===runId?null:runId!});
  else if(name==='candidate-group')await conversation.updateTurnUi(turn.id,{activeCandidateGroup:element.dataset.groupId!});
  else if(name==='continue-with-run'&&ref){await conversation.setReference(state=>appendRunReferences(state,[ref]));document.getElementById('agent-query')?.focus();notify(`${ref.runId}을 채팅에 추가했습니다.`,'info');}
  else if(name==='reference-candidate-group'){const refs=candidateRefs(turn);await conversation.setReference(state=>appendRunReferences(state,refs));document.getElementById('agent-query')?.focus();notify(`${refs.length}개 후보를 채팅에 추가했습니다.`,'info');}
  else if(name==='open-run-detail'&&ref)onDetail(ref,turn);
  else if(name==='open-experiment-record')onRecord(turn);
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
 return <RunColorsProvider key={colorScope} scope={colorScope} enabled={conversation.ready}><div className="agent-page agent-page--wide"><header className="agent-page-header"><div><span className="eyebrow">CONVERSATIONAL EVIDENCE ANALYSIS</span><h1>K-PLASMA 분석 Agent</h1><p>결론과 실제 수치를 먼저 보고, 필요한 실험 상세만 펼쳐 확인합니다.</p></div><div className="agent-page-actions"><div className="agent-trust-row"><span><i className="status-dot status-dot--success"/>등록된 실제 Run</span><span>예측·보간 없음</span></div><button className="button button--ghost button--small" type="button" data-action="new-conversation" disabled={!turns.length&&!conversation.activeRequest} onClick={()=>conversation.newConversation().catch(catchError)}>새 대화</button></div></header><section className="agent-conversation agent-conversation--wide"><div className="agent-thread" aria-live="polite">{turns.length?turns.map(turn=><ConversationTurn key={turn.id} turn={turn} onAction={dispatchAction}/>):<div className="agent-welcome panel"><div className="agent-welcome-mark" aria-hidden="true">K</div><h2>실제 Run과 공정 원리를 함께 설명합니다</h2><p>조건 조회, 목표 후보 탐색, 결과 변화와 기본 개념을 한 대화에서 이어갈 수 있습니다.</p><div><span>Registered Runs</span><span>예측·보간 없음</span><span>개념·근거 구분</span></div></div>}</div>
 {conversation.activeRequest&&<PendingRequest request={conversation.activeRequest} sending={conversation.sending} onResume={conversation.resume} onCancel={conversation.cancel} onError={catchError}/>}
 {conversation.error&&<div className="alert alert--danger" role="alert">{conversation.error}</div>}<form id="agent-query-form" className="agent-composer panel" onSubmit={event=>{event.preventDefault();void run(text);}}>{composer&&<ReferenceTray references={composer.runs} onRemove={()=>void clear()} onRemoveRun={ref=>void conversation.setReference(state=>removeRunReference(state,ref)).catch(catchError)}/>}<label htmlFor="agent-query">공정 데이터에 질문하기</label><div><textarea id="agent-query" name="queryText" rows={3} required aria-label="공정 데이터에 질문하기" placeholder="조건, 목표, 변화 이유 또는 기본 개념을 질문하세요" value={text} onChange={event=>setText(event.target.value)}/><button className="button button--primary" type="submit" disabled={pending||!conversation.ready}>분석</button></div>{active?<div className="agent-quick-followups"><span>이 Run에서 이어서</span>{[['전체 결과·분포','이 Run의 전체 결과와 이온 에너지 분포 보여줘'],['Energy만 조금 높게','이 결과에서 이온 에너지만 조금 더 높은 실제 조건 찾아줘'],['왜 이런 결과인지','왜 이런 결과가 나왔는지 설명해줘']].map(([label,prompt])=><button key={label} type="button" data-action="use-followup" data-prompt={prompt} disabled={pending} onClick={()=>void run(prompt)}>{label}</button>)}</div>:<small>지원 범위: 조건 조회 · 후보 탐색 · Run 비교 · 변화 설명 · 플라즈마 기본 개념</small>}<details className="v1-unit-help"><summary>단위 없이도 조회할 수 있어요 · 기본 단위 보기</summary><ul>{Object.entries(queryDefaultUnits).map(([metric,unit])=><li key={metric}>{metricNames[metric]} <strong>{unit}</strong></li>)}</ul><p>예: 압력 8, 소스 300, 바이어스 600 · 이온 플럭스 400 이상</p><p>단위를 쓰면 입력한 단위를 우선합니다. 생략하면 적용한 기본 단위를 답변에서 알려드립니다.</p></details></form><div className="agent-examples" aria-label="분석 예시">{examples.map(([action,label,title,prompt])=><button key={action} type="button" data-action={action} disabled={pending||!conversation.ready} onClick={()=>void run(prompt)}><span>{label}</span><strong>{title}</strong></button>)}</div><div className="memory-demo-actions"><span>기록 활용 시연 데이터가 필요하다면</span><button className="button button--ghost button--small" type="button" data-action="memory-demo" onClick={()=>onDemo().catch(catchError)}>데모 기록 불러오기</button><small>실제 사용자 기록과 구분되어 이 브라우저에만 저장됩니다.</small></div></section></div></RunColorsProvider>;
}
