import {lazy,Suspense,useEffect,useMemo,useState,type ReactNode} from 'react';
import {isGraphV2AnswerSnapshot,type RunRef,type RunSummary,type Snapshot} from 'agent';
import {BrandMark} from '../../components/BrandMark';
import {measurementText,metricNames,numberText} from '../agent/agent-contract';
import {completeMathPrefix} from '../agent/StreamPreview';
import type {DecisionGoal,DecisionRule} from './decision-demo';

const AnswerMarkdown=lazy(()=>import('../agent/GeneralAnswerCard').then(module=>({default:module.AnswerMarkdown})));
const energyText=(run:RunSummary)=>measurementText(numberText(run.metrics.meanIonEnergy),run.units.meanIonEnergy);
const fluxText=(run:RunSummary)=>measurementText(numberText(run.metrics.ionFlux),run.units.ionFlux);
export const biasText=(run:RunSummary)=>measurementText(run.biasPower,run.units.biasPower);
export const fixedConditions=(run:RunSummary)=>[
  measurementText(run.pressure,run.units.pressure),measurementText(run.sourcePower,run.units.sourcePower),
].join(' · ');
export const conditionText=(run:RunSummary)=>`${fixedConditions(run)} · ${biasText(run)}`;
export const goalText={
  damage:'손상은 줄이고, 속도는 지금 정도로 유지하고 싶어.',
  rate:'더 빨리 깎되, 표면에 가해지는 에너지는 크게 늘리고 싶지 않아.',
};
function ruleDisplay(rule:DecisionRule) {
  return rule.operator==='between'?measurementText(`${rule.min}–${rule.max}`,rule.unit):
    `${{eq:'=',lte:'≤',gte:'≥'}[rule.operator]} ${measurementText(rule.value,rule.unit)}`;
}
const changePct=(value:number,baseline:number)=>`${numberText((value/baseline-1)*100,1,true)}%`;

export function DecisionCard({title,children,detail}:{title:string;children:ReactNode;detail?:string}){
  return <section className="agent-response agent-response--inline decision-card">
    <header className="decision-card-heading">
      <BrandMark className="decision-mark"/><h2>{title}</h2>
      {detail&&<span className="decision-detail">{detail}</span>}
    </header>
    {children}
  </section>;
}

export function GoalTranslation({baseline,goal,rules,children}:{baseline:RunSummary;goal:DecisionGoal;rules:DecisionRule[];children:ReactNode}){
  const damage=goal.mode==='damage';
  return <>
    <DecisionCard title="이렇게 이해했어요" detail="목표 → 지표">
      <p>{damage
        ?'표면 손상은 줄이면서, 깎이는 속도는 지금과 비슷하게 유지하고 싶은 거군요. 아래 두 지표로 바꿔 볼게요.'
        :'지금보다 빨리 깎고 싶고, 표면에 부딪히는 이온의 에너지는 크게 늘리고 싶지 않은 거군요. 아래 두 지표로 바꿔 볼게요.'}</p>
      <dl className="decision-criteria">
        {rules.filter(rule=>rule.metric==='meanIonEnergy'||rule.metric==='ionFlux').map(rule=>{
          const energy=rule.metric==='meanIonEnergy';
          return <div key={rule.metric}>
            <dt>{energy?(damage?'손상 줄이기':'에너지 증가 제한'):(damage?'속도 유지':'속도 높이기')} <span aria-hidden="true">→</span></dt>
            <dd><strong className={energy&&damage?'decision-metric--decrease':undefined}>
              {energy?(damage?'평균 이온 에너지 낮추기':'평균 이온 에너지 상한'):(damage?'이온 플럭스 유지':'이온 플럭스 높이기')}
            </strong>
              <small>{energy?'이온이 표면에 부딪힐 때의 평균 에너지':'표면에 도달하는 이온의 양'}</small>
              <span className="decision-range">현재 {energy?energyText(baseline):fluxText(baseline)} → {ruleDisplay(rule)}</span></dd>
          </div>;
        })}
      </dl>
      <p className="decision-note">압력 {measurementText(baseline.pressure,baseline.units.pressure)}와 소스 전력 {measurementText(baseline.sourcePower,baseline.units.sourcePower)}을 고정해 찾습니다. 두 지표는 식각 속도와 손상을 판단할 때 참고하는 값입니다.</p>
      {children}
    </DecisionCard>
    <DecisionCard title="지금 결과를 목표에 맞춰 보면" detail={baseline.runId}>
      <div className="decision-baseline">
        <div><strong>이온 플럭스 {fluxText(baseline)}</strong><small>{damage?'이 수준을 유지':'이 값보다 늘릴 기준'}</small></div>
        <div><strong>평균 이온 에너지 {energyText(baseline)}</strong><small>{damage?'이 값보다 낮출 기준':'이 값에서 증가 폭을 제한'}</small></div>
      </div>
    </DecisionCard>
  </>;
}

const reducedMotionQuery='(prefers-reduced-motion: reduce)';
const reducedMotion=()=>window.matchMedia?.(reducedMotionQuery).matches??false;

function DecisionNarrative({snapshot,children}:{snapshot:Snapshot;children?:ReactNode}){
  const answer=isGraphV2AnswerSnapshot(snapshot)?snapshot:null;
  const draft=answer?.draft;
  const valid=answer?.executionStatus==='COMPLETE'&&!answer.hasIncompleteWork;
  const interpretations=Array.isArray(draft?.interpretations)?draft.interpretations:[];
  const limitations=Array.isArray(draft?.limitations)?draft.limitations:[];
  const group=valid&&answer.review.status==='PASS'?[...interpretations,...limitations]:
    valid&&interpretations.length===0?limitations:[];
  const prose=group.flatMap(item=>item&&typeof item==='object'&&!Array.isArray(item)&&typeof item.text==='string'
    ?[item.text,...(Array.isArray(item.assumptions)?item.assumptions.filter((value):value is string=>typeof value==='string'):[])]:[]);
  if(!prose.length)return <>
    <p className="decision-note">V2 해석을 완료하지 못했습니다. 표에 확인된 측정값을 표시합니다.</p>
    {children}
  </>;
  return <Suspense fallback={<p role="status">V2 답변을 표시하는 중입니다.</p>}>
    <TypedNarrative prose={prose}>{children}</TypedNarrative>
  </Suspense>;
}

function TypedNarrative({prose,children}:{prose:string[];children?:ReactNode}){
  const {blocks,total}=useMemo(()=>{
    let offset=0;
    const blocks=prose.map(text=>{
      const chunks=text.match(/(?:\S+\s*){1,3}|\s+/g)??[];
      const block={text,chunks,start:offset};
      offset+=chunks.length;
      return block;
    });
    return {blocks,total:offset};
  },[prose]);
  const [visible,setVisible]=useState(()=>reducedMotion()?Infinity:0);
  const writing=visible<total;

  useEffect(()=>{
    if(!writing)return;
    const step=Math.max(1,Math.ceil(total/14));
    const timer=window.setInterval(()=>setVisible(count=>Math.min(total,count+step)),160);
    return()=>window.clearInterval(timer);
  },[total,writing]);

  return <>
    <div className="decision-narrative" aria-label="V2 분석 답변">
      <div className={writing?'decision-narrative-writing':undefined} aria-busy={writing}>
        {blocks.map(({text,chunks,start},index)=>{
          const length=visible-start;
          if(length<=0&&index>0)return null;
          const markdown=length>=chunks.length?text:completeMathPrefix(chunks.slice(0,Math.max(0,length)).join(''));
          return <AnswerMarkdown key={index} markdown={markdown} preserveHtmlText/>;
        })}
      </div>
    </div>
    {!writing&&children}
  </>;
}

function DecisionTable({ready,onReady,children}:{ready:boolean;onReady:(ready:true)=>void;children:ReactNode}){
  useEffect(()=>{
    if(ready)return;
    const motion=window.matchMedia?.(reducedMotionQuery);
    const finish=()=>{if(motion?.matches)onReady(true);};
    motion?.addEventListener('change',finish);
    finish();
    return()=>motion?.removeEventListener('change',finish);
  },[ready,onReady]);

  return <div className={`v1-table-scroll decision-table-scroll${ready?'':' decision-table-entry'}`}
    onAnimationEnd={event=>{if(event.animationName==='decision-table-appear')onReady(true);}}>
    {children}
    {!ready&&<div className="decision-table-skeleton" aria-hidden="true">
      <span/><span/><span/><span/><span/>
    </div>}
  </div>;
}

export function CandidateResults({baseline,runs,goal,rules,snapshot}:{baseline:RunSummary;runs:RunSummary[];goal:DecisionGoal;rules:DecisionRule[];snapshot:Snapshot}){
  const [tableReady,setTableReady]=useState(reducedMotion);
  const metric=goal.mode==='damage'?'meanIonEnergy':'ionFlux';
  const bars=[baseline,...runs].sort((a,b)=>b.biasPower-a.biasPower);
  const maximum=Math.max(...bars.map(run=>run.metrics[metric]));
  return <>
    <DecisionCard title={`조건을 만족한 후보 ${runs.length}개`}>
      <div className="decision-applied">
        <span>적용한 해석</span>{rules.slice(2).map(rule=><strong key={rule.metric}>{metricNames[rule.metric]} {ruleDisplay(rule)}</strong>)}
      </div>
      {runs.length>0?<DecisionTable ready={tableReady} onReady={setTableReady}><table className="v1-comparison-table decision-table" aria-label="후보 Run 비교">
        <thead><tr><th scope="col">Run</th><th scope="col">압력 · 소스 · 바이어스</th><th scope="col">이온 플럭스</th><th scope="col">평균 이온 에너지</th></tr></thead>
        <tbody>{runs.map(run=><tr key={run.runVersionId}>
          <th scope="row">{run.runId}</th>
          <td>{fixedConditions(run)} · <strong className="decision-bias">{biasText(run)}</strong></td>
          <td>{fluxText(run)}</td>
          <td>{energyText(run)} <small>({changePct(run.metrics.meanIonEnergy,baseline.metrics.meanIonEnergy)})</small></td>
        </tr>)}</tbody>
      </table></DecisionTable>:<DecisionNarrative snapshot={snapshot}/>}
    </DecisionCard>
    {tableReady&&runs.length>0&&<DecisionCard title="바꿔 볼 조건 · 바이어스 전력 하나">
      <p>다음 비교에서는 압력과 소스 전력을 <strong>{fixedConditions(baseline)}</strong>로 두고, 바이어스 전력만 바꿔 보세요.</p>
      <DecisionNarrative snapshot={snapshot}>
        {bars.every(run=>run.metrics[metric]>=0)&&<>
        <p className="decision-note">{metricNames[metric]} ({baseline.units[metric]})</p>
        <ul className="decision-bars" aria-label={`${metricNames[metric]} 비교`}>
          {bars.map(run=><li key={run.runVersionId}>
            <span className="decision-bar-stack"><strong>{numberText(run.metrics[metric])}</strong>
              <i aria-hidden="true" className={run===baseline?'decision-bar--baseline':''} style={{height:`${run.metrics[metric]/maximum*72}px`}}/></span>
            <span>{biasText(run)}{run===baseline?' · 기준':''}</span>
          </li>)}
        </ul>
        </>}
        <p className="decision-note">표에 나온 Run의 관찰값입니다. 식각 속도와 손상은 별도 측정으로 확인해야 합니다.</p>
      </DecisionNarrative>
    </DecisionCard>}
  </>;
}

export function Tradeoffs({runs,baseline,selected,onSelect,snapshot}:{runs:RunSummary[];baseline:RunSummary;selected:RunRef|null;onSelect:(run:RunSummary)=>void;snapshot:Snapshot}){
  const [tableReady,setTableReady]=useState(reducedMotion);
  const minEnergy=Math.min(...runs.map(run=>run.metrics.meanIonEnergy));
  const maxEnergy=Math.max(...runs.map(run=>run.metrics.meanIonEnergy));
  return <DecisionCard title="선택지별 얻는 것과 잃는 것">
    <DecisionTable ready={tableReady} onReady={setTableReady}><table className="v1-comparison-table decision-table decision-tradeoffs" aria-label="선택지별 장단점">
      <thead><tr><th scope="col">후보 (바이어스)</th><th scope="col">얻는 것</th><th scope="col">잃는 것 · 주의</th><th scope="col">선택</th></tr></thead>
      <tbody>{runs.map(run=>{
        const picked=selected?.runVersionId===run.runVersionId;
        const lowest=runs.length>1&&run.metrics.meanIonEnergy===minEnergy&&minEnergy<maxEnergy;
        const reducesEnergy=run.metrics.meanIonEnergy<baseline.metrics.meanIonEnergy;
        return <tr key={run.runVersionId} className={picked?'decision-selected':lowest?'decision-lowest':undefined}>
          <th scope="row">{biasText(run)} · {energyText(run)}<small>기준 대비 {changePct(run.metrics.meanIonEnergy,baseline.metrics.meanIonEnergy)}</small></th>
          <td>{lowest?'후보 중 평균 에너지가 가장 낮음. ':reducesEnergy?'평균 에너지를 낮춤. ':''}
            {run.metrics.ionFlux===baseline.metrics.ionFlux?'이온 플럭스는 기준과 같음.':`이온 플럭스 ${changePct(run.metrics.ionFlux,baseline.metrics.ionFlux)}.`}</td>
          <td>{lowest?'에너지가 낮아도 식각이 충분한지 확인 필요. ':'실제 식각 결과 확인 필요. '}
            {run.metrics.iedWidth==null?'IED 폭 데이터 없음.':''}</td>
          <td><button type="button" className="button button--ghost button--small" aria-label={`${run.runId} 선택`} disabled={!!selected} onClick={()=>onSelect(run)}>{picked?'✓ 선택':'선택'}</button></td>
        </tr>;
      })}</tbody>
    </table></DecisionTable>
    {tableReady&&<DecisionNarrative snapshot={snapshot}>
      <p className="decision-notice">이 Run 데이터에는 식각에 필요한 최소 이온 에너지 기준이 없습니다. 낮은 후보를 선택하기 전에 식각이 충분히 진행되는지 확인하세요.</p>
    </DecisionNarrative>}
  </DecisionCard>;
}
