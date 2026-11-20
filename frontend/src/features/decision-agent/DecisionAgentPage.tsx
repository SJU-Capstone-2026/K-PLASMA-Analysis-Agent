import {useEffect,useRef,useState,type FormEvent} from 'react';
import type {AgentActivity,RunRef,RunSummary,TurnSnapshot} from 'agent';
import {fetchRuns} from '../../api/runs';
import {ApiClientError} from '../../api/client';
import {BrandMark} from '../../components/BrandMark';
import {ReferenceTray} from '../../components/ReferenceTray';
import {AgentUserMessage} from '../agent/AgentUserMessage';
import {AgentProgress,CompletedAgentProgress,latestActivities} from '../agent/AgentProgress';
import {RunMentionComposer} from '../agent/RunMentionComposer';
import {biasText,CandidateResults,conditionText,DecisionCard,fixedConditions,GoalTranslation,goalText,Tradeoffs} from './DecisionResults';
import type {useConversation} from '../agent/useConversation';
import {baselineIssue,confirmedCandidates,damageGoal,demoRunId,getDecisionRules,rateGoal,resolveDecisionRun,searchQuestion,type DecisionGoal,type DecisionRule} from './decision-demo';
import {decisionProgressLabel} from './decision-progress';
import './decision-agent.css';

type Conversation=ReturnType<typeof useConversation>;
type Search={question:string;rules:DecisionRule[];previousTurns:Set<string>;error?:string};
function errorText(error:unknown){
  if(error instanceof TypeError&&/^(Failed to fetch|Load failed|NetworkError\b)/.test(error.message))
    return '로컬 서버에 연결할 수 없습니다. 연결이 돌아오면 다시 시도해 주세요.';
  return error instanceof Error?error.message:String(error);
}

function readCandidates(turn:TurnSnapshot|undefined,baseline:RunSummary|null,search:Search|null){
  if(!turn||!baseline||!search)return null;
  try{return confirmedCandidates(turn.answerSnapshot,baseline,search.rules);}
  catch{return null;}
}

export function DecisionAgentPage({active,conversation}:{active:boolean;conversation:Conversation}){
  const [catalog,setCatalog]=useState<RunSummary[]|null>(null);
  const [catalogError,setCatalogError]=useState('');
  const [catalogAttempt,reloadCatalog]=useState(0);
  const [reference,setReference]=useState<RunRef|null|undefined>();
  const [question,setQuestion]=useState('');
  const [input,setInput]=useState('');
  const [baseline,setBaseline]=useState<RunSummary|null>(null);
  const [matches,setMatches]=useState<RunSummary[]>([]);
  const [goal,setGoal]=useState<DecisionGoal|null>(null);
  const [interpreting,setInterpreting]=useState(false);
  const [editing,setEditing]=useState<DecisionGoal|null>(null);
  const [description,setDescription]=useState('');
  const [draftDescription,setDraftDescription]=useState('');
  const [search,setSearch]=useState<Search|null>(null);
  const [followup,setFollowup]=useState('');
  const [followupSearch,setFollowupSearch]=useState<Search|null>(null);
  const [visibleSteps,setVisibleSteps]=useState(1);
  const [selected,setSelected]=useState<RunRef|null>(null);
  const [error,setError]=useState('');
  const latest=useRef<HTMLDivElement>(null);
  const resultStart=useRef<HTMLDivElement>(null);
  const submitting=useRef(false);
  const findTurn=(attempt:Search|null)=>active&&attempt
    ?conversation.state.conversation.turns.find(item=>item.question===attempt.question&&!attempt.previousTurns.has(item.id)):undefined;
  const turn=findTurn(search);
  const followupTurn=findTurn(followupSearch);
  const candidates=readCandidates(turn,baseline,search);
  const choice=selected&&candidates?.find(run=>run.runId===selected.runId&&run.runVersionId===selected.runVersionId);
  const followupRuns=readCandidates(followupTurn,baseline,followupSearch);
  const sameCandidates=!!candidates&&!!followupRuns&&candidates.length===followupRuns.length&&
    candidates.every(run=>followupRuns.some(ref=>ref.runId===run.runId&&ref.runVersionId===run.runVersionId));
  const request=active?conversation.activeRequest:null;
  const running=request?.status==='QUEUED'||request?.status==='RUNNING';
  const failed=request?.status==='FAILED'||request?.status==='CANCELLED';
  const summaryFor=(id:string)=>conversation.state.agentMessages?.find(message=>message.turnId===id||message.requestId===id)?.executionSummary;
  const attempt=followupSearch??search;
  const resultTurn=followupSearch?followupTurn:turn;
  const attemptRequest=attempt&&request?.question===attempt.question&&(!request.turnId||!attempt.previousTurns.has(request.turnId))?request:null;
  const resultReady=!!resultTurn||attemptRequest?.status==='COMPLETED';
  const summary=(resultTurn&&summaryFor(resultTurn.id))??attemptRequest?.executionSummary;
  const events=latestActivities(summary?.activities??attemptRequest?.progress?.activities??[],resultReady);
  const completed=events.filter(activity=>activity.phase!=='started');
  const describeSearch=goal?(activity:AgentActivity)=>decisionProgressLabel(activity,goal.mode):undefined;
  const describeFollowup=(activity:AgentActivity)=>decisionProgressLabel(activity,'followup');
  const describeProgress=followupSearch?describeFollowup:describeSearch;
  const visibleStep=completed[visibleSteps-1];
  const visibleLabel=visibleStep&&describeProgress?.(visibleStep);
  const stepDelay=500+Math.min(260,Math.max(0,(visibleLabel?.length??0)-20)*12);
  const queueText=followupSearch?'후속 질문을 준비하고 있어요.':'승인한 조건으로 검색을 준비하고 있어요.';
  const hasUnshownSteps=visibleSteps<completed.length;
  const showingFinalSteps=active&&resultReady&&completed.length>0&&visibleSteps<=completed.length;
  const paceProgress=active&&(showingFinalSteps||running&&hasUnshownSteps);
  const pending=active&&(conversation.pending||showingFinalSteps);
  const rules=baseline&&goal&&!interpreting?getDecisionRules(baseline,goal):null;
  const canUseComposer=!question||candidates!==null;
  const taggedRun=catalog?.find(run=>reference===undefined?run.runId===demoRunId:
    run.runId===reference?.runId&&run.runVersionId===reference.runVersionId);

  useEffect(()=>{
    if(!active)return;
    const controller=new AbortController();
    fetchRuns(controller.signal).then(runs=>{
      if(controller.signal.aborted)return;
      setCatalog(runs);setCatalogError('');
    }).catch(cause=>{if(!controller.signal.aborted)setCatalogError(errorText(cause));});
    return()=>controller.abort();
  },[active,catalogAttempt]);

  useEffect(()=>{
    if(!interpreting)return;
    const timer=window.setTimeout(()=>setInterpreting(false),1000);
    return()=>window.clearTimeout(timer);
  },[interpreting]);

  useEffect(()=>{
    if(!paceProgress)return;
    const timer=window.setTimeout(()=>setVisibleSteps(visibleSteps+1),stepDelay);
    return()=>window.clearTimeout(timer);
  },[paceProgress,visibleSteps,stepDelay]);

  useEffect(()=>{
    if(!active||!question)return;
    if(resultStart.current&&!selected)resultStart.current.scrollIntoView?.({block:'start'});
    else latest.current?.scrollIntoView?.({block:'nearest'});
  },[active,question,baseline,goal,interpreting,turn?.id,followup,followupTurn?.id,selected,visibleSteps,showingFinalSteps]);

  function reset(){
    setQuestion('');setInput('');setBaseline(null);setMatches([]);setGoal(null);setEditing(null);
    setDescription('');setDraftDescription('');setSearch(null);setFollowup('');setFollowupSearch(null);setSelected(null);setError('');
    setInterpreting(false);
    setReference(undefined);
    requestAnimationFrame(()=>document.getElementById('decision-query')?.focus());
  }

  function acceptQuestion(event:FormEvent){
    event.preventDefault();
    const text=input.trim();
    if(!text||pending||!canUseComposer)return;
    if(/(?:^|\s)@[A-Z0-9-]*$/i.test(text)){
      setError('자동완성 목록에서 기준 Run을 선택하거나 Run ID를 입력해 주세요.');
      return;
    }
    if(question&&!taggedRun){
      if(!candidates?.length||followup){
        setError('@로 기준 Run을 선택해 다음 시연을 시작할 수 있습니다.');
        return;
      }
      if(/RUN-|다시\s*(?:찾|검색)|조건.*변경해/i.test(text)){
        setError('현재 후보를 선택할 때의 장단점을 물어보세요. 기준 Run이나 검색 조건을 바꾸려면 새 시연을 시작해 주세요.');
        return;
      }
      setError('');
      setFollowup(text);setInput('');void findCandidates(text);
      return;
    }
    if(!catalog||catalogError)return;
    const found=resolveDecisionRun(text,reference?catalog.filter(run=>run===taggedRun):catalog,taggedRun);
    if(!found.length){setError('질문과 일치하는 Run을 찾을 수 없습니다. 등록된 Run ID나 공정 조건을 확인해 주세요.');return;}
    if(question)reset();
    setError('');setQuestion(text);setInput('');setReference(null);
    setBaseline(found.length===1?found[0]:null);
    setMatches(found.length>1?found:[]);
    setInterpreting(found.length===1);
  }

  function chooseGoal(next:DecisionGoal,note=''){
    setGoal(next);setDescription(note);setEditing(null);setError('');setSearch(null);
    setInterpreting(true);
  }

  async function findCandidates(followupText?:string){
    if(!baseline||!rules||pending||submitting.current)return;
    const question=searchQuestion(rules,followupText);
    const ref={runId:baseline.runId,runVersionId:baseline.runVersionId};
    submitting.current=true;
    const setAttempt=followupText?setFollowupSearch:setSearch;
    setAttempt({question,rules,previousTurns:new Set(conversation.state.conversation.turns.map(turn=>turn.id))});
    setVisibleSteps(1);
    setError('');
    const submit=()=>conversation.submit(question,undefined,{activeRun:ref,candidateReference:null,room:conversation.state.stateToken});
    try{
      await submit().catch(cause=>{
        if(cause instanceof ApiClientError&&cause.error.code==='STALE_CONTEXT')return submit();
        throw cause;
      });
    }
    catch(cause){setAttempt(current=>current&&({...current,error:errorText(cause)}));}
    finally{submitting.current=false;}
  }

  return <div className="agent-page agent-page--wide decision-agent">
    {question&&<header className="agent-page-header">
      <button className="button button--ghost button--small" type="button" disabled={pending} onClick={reset}>새 시연</button>
    </header>}

    <section className="agent-conversation agent-conversation--wide">
    <div className="agent-thread">
      {catalogError?<p role="alert" className="decision-notice">{catalogError} <button className="text-button" type="button" onClick={()=>reloadCatalog(value=>value+1)}>다시 불러오기</button></p>
        :catalog===null?<p role="status">등록된 Run을 불러오는 중입니다.</p>
        :!catalog.length?<p role="status">등록된 Run이 없습니다. Run 데이터 관리에서 실험을 등록해 주세요.</p>
        :!question&&<section className="agent-welcome">
          <BrandMark className="agent-welcome-mark"/>
          <h2>다음 실험 조건을 함께 찾아요</h2>
          <p>채팅창에서 <strong>@</strong>로 기준 Run을 고르고, 어떤 점을 개선하고 싶은지 알려 주세요.</p>
        </section>}
      {question&&<AgentUserMessage question={question} refs={baseline?[baseline]:[]}/>}
      {matches.length>1&&!baseline&&<DecisionCard title="어느 Run을 기준으로 볼까요?">
        <div className="decision-actions">{matches.map(run=><button type="button" key={run.runVersionId} className="button button--ghost" onClick={()=>{setBaseline(run);setInterpreting(true);}}>{run.runId} · {conditionText(run)}</button>)}</div>
      </DecisionCard>}
      {baseline&&(goal||(!interpreting&&!editing))&&<DecisionCard title="확인이 필요해요">
        <p>‘효율’은 목적에 따라 뜻이 달라요. 어떤 쪽을 원하세요?</p>
        <div className="decision-goals">
          <button type="button" disabled={!!goal} aria-pressed={goal?.mode==='rate'&&!description} onClick={()=>chooseGoal(rateGoal)}><strong>더 빨리 깎기</strong><small>식각 속도를 올리고 싶어요</small></button>
          <button type="button" disabled={!!goal} aria-pressed={goal?.mode==='damage'&&!description} onClick={()=>chooseGoal(damageGoal)}><strong>손상 줄이기</strong><small>속도는 지금 정도로 유지하고 싶어요</small></button>
          <button type="button" disabled={!!goal} aria-pressed={!!description} onClick={()=>setEditing(damageGoal)}><strong>직접 설명하기</strong><small>원하는 목표를 입력하세요</small></button>
        </div>
      </DecisionCard>}
      {editing&&<DecisionCard title="목표와 지표 기준">
        <form className="decision-edit" onSubmit={event=>{event.preventDefault();chooseGoal(editing,draftDescription.trim());}}>
          <label>목표 설명<textarea value={draftDescription} maxLength={500} onChange={event=>setDraftDescription(event.target.value)}/></label>
          <div className="decision-goals">
            <label>우선 목표<select value={editing.mode} onChange={event=>setEditing({...editing,mode:event.target.value as DecisionGoal['mode']})}>
              <option value="damage">평균 이온 에너지 줄이기</option><option value="rate">이온 플럭스 늘리기</option>
            </select></label>
            <label>목표 변화율 (%)<input type="number" min="1" max="100" step="any" required value={Number.isNaN(editing.change)?'':editing.change} onChange={event=>setEditing({...editing,change:event.target.valueAsNumber})}/></label>
            <label>보조 지표 허용 변화율 (%)<input type="number" min="0" max="100" step="any" required value={Number.isNaN(editing.tolerance)?'':editing.tolerance} onChange={event=>setEditing({...editing,tolerance:event.target.valueAsNumber})}/></label>
          </div>
          <button type="submit" className="button button--primary">해석 확인</button>
          <button type="button" className="button button--ghost" onClick={()=>setEditing(null)}>취소</button>
        </form>
      </DecisionCard>}
      {baseline&&goal&&!editing&&<AgentUserMessage question={description||goalText[goal.mode]}/>}
      {interpreting&&<AgentProgress stage="interpret"
        statusText={goal?'선택한 목표를 비교 지표로 정리하고 있어요.':'기준 Run과 질문을 확인하고 있어요.'}/>}
      {baseline&&goal&&!editing&&!interpreting&&(rules?<GoalTranslation baseline={baseline} goal={goal} rules={rules}>
          {!candidates&&<div className="decision-actions">
            <button type="button" className="button button--primary" disabled={pending} onClick={()=>void findCandidates()}>{failed||turn||search?.error?'다시 검색':'이 해석으로 후보 찾기'}</button>
            <button type="button" className="button button--ghost" disabled={pending} onClick={()=>{setDraftDescription(description);setEditing(goal);}}>해석 고치기</button>
          </div>}
        </GoalTranslation>:<DecisionCard title="이렇게 이해했어요">
          <p className="decision-notice">{baselineIssue(baseline)} 다른 기준 Run을 선택해 주세요.</p>
        </DecisionCard>)}
      {error&&<p role="alert" className="decision-notice">{error}</p>}
      {!showingFinalSteps&&!candidates&&(search?.error||search&&active&&conversation.error||turn)&&<p role="alert" className="decision-notice">{search?.error||conversation.error||'승인한 기준과 일치하는 V2 검색 결과를 확인하지 못했습니다.'}</p>}
      {baseline&&goal&&candidates&&turn&&search&&(!showingFinalSteps||followupSearch)&&<div className="decision-result" ref={followup?undefined:resultStart}>
        <CompletedAgentProgress summary={summaryFor(turn.id)} describeActivity={describeSearch}/>
        <CandidateResults baseline={baseline} runs={candidates} goal={goal} rules={search.rules} snapshot={turn.answerSnapshot}/>
      </div>}
      {followup&&<AgentUserMessage question={followup}/>}
      {pending&&conversation.sending&&!running&&!showingFinalSteps&&request?.status!=='NEEDS_INPUT'&&
        <AgentProgress stage="queued" queued statusText={queueText}/>}
      {(running||showingFinalSteps)&&<section className="v1-pending v1-pending--running" aria-label="분석 작업 기록">
        <AgentProgress events={resultReady||hasUnshownSteps?completed.slice(0,visibleSteps):events}
          stage={attemptRequest?.stage??'queued'} queued={attemptRequest?.status==='QUEUED'} pending={!resultReady}
          recentLimit={(followupSearch?5:6)-(resultReady?0:1)} describeActivity={describeProgress}
          statusText={attemptRequest?.status==='QUEUED'?queueText:undefined}/>
      </section>}
      {pending&&request?.status==='NEEDS_INPUT'&&<DecisionCard title="분석에 추가 확인이 필요합니다">
        <p>{request.pendingInput?.message} 취소한 뒤 기준을 확인해 주세요.</p>
        <button type="button" className="button button--ghost button--small" onClick={()=>void conversation.cancel().catch(cause=>setError(errorText(cause)))}>분석 취소</button>
      </DecisionCard>}
      {request?.status==='CANCELLED'&&<CompletedAgentProgress summary={request.executionSummary} status="CANCELLED"/>}
      {followupSearch&&!pending&&!sameCandidates&&(followupTurn||failed||followupSearch.error||conversation.error)&&
        <DecisionCard title="후속 답변을 확인하지 못했습니다">
          <p role="alert">{followupSearch.error||conversation.error||(followupRuns?'후보가 바뀌었습니다. 새 시연에서 기준을 다시 확인해 주세요.':'승인한 후보에 대한 분석을 확인하지 못했습니다.')}</p>
          {!followupRuns&&<button type="button" className="button button--ghost" onClick={()=>void findCandidates(followup)}>다시 분석</button>}
        </DecisionCard>}
      {!showingFinalSteps&&followup&&baseline&&candidates?.length&&sameCandidates&&followupTurn&&<div className="decision-result" ref={resultStart}>
        <CompletedAgentProgress summary={summaryFor(followupTurn.id)} describeActivity={describeFollowup}/>
        <Tradeoffs runs={candidates} baseline={baseline} selected={selected} snapshot={followupTurn.answerSnapshot}
          onSelect={({runId,runVersionId})=>setSelected({runId,runVersionId})}/>
      </div>}
      {baseline&&choice&&<>
        <AgentUserMessage question="이 조건으로 다음 실험을 해볼게요." refs={[choice]}/>
        <DecisionCard title="다음 실험에서 확인할 조건">
          <div role="status">
            <p>압력과 소스 전력은 <strong>{fixedConditions(baseline)}</strong>로 유지하고, 바이어스 전력만 <strong>{biasText(baseline)} → {biasText(choice)}</strong>로 바꿔 보세요.</p>
            <p>다음 Run에서는 이온 플럭스와 평균 이온 에너지를 다시 비교하고, 실제 식각 속도와 표면 손상도 확인해 주세요.</p>
          </div>
        </DecisionCard>
      </>}
      <div ref={latest} className="decision-latest"/>
    </div>

    <div className="agent-composer-dock">
      <form className="agent-composer panel" onSubmit={acceptQuestion}>
        {taggedRun&&<ReferenceTray references={[taggedRun]} onRemoveRun={()=>setReference(null)}/>}
        <RunMentionComposer inputId="decision-query" text={input} onText={setInput}
          runs={catalog??undefined} add={async ref=>{setReference(ref);return true;}}
          disabled={!canUseComposer||pending||!catalog?.length||!!catalogError}
          onStop={running?()=>conversation.cancel().catch(cause=>setError(errorText(cause))):undefined}/>
      </form>
    </div>
    </section>
  </div>;
}
