import type {RunSummary,Snapshot,TurnSnapshot} from 'agent';
import {numberText,searchGroups,searchMetricNames,snapshotResult,type SearchResult} from './agent-contract';

const legacyOperators:Record<string,string>={between:'RANGE',gte:'MIN',lte:'MAX',eq:'EQUAL',gt:'>',lt:'<'};
const finite=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value);
const display=(value:unknown,digits=2)=>finite(value)?numberText(value,digits):'N/A';
const signed=(value:unknown,digits=2,suffix='')=>finite(value)?`${value<0?'−':''}${numberText(Math.abs(value),digits,value>0)}${suffix}`:'비교 불가';
const legacyRule=(rule:Snapshot)=>({...rule,operator:legacyOperators[String(rule.operator)]??rule.operator});
function groupNotice(id:string){
 if(id.startsWith('objective-'))return '개별 조건의 후보입니다. 모든 필수 조건을 만족하는 공통 후보와 구분합니다.';
 if(id==='near')return '필수 조건을 만족하지 못한 참고 후보입니다. 조건 일치 결과에 포함하지 않습니다.';
 return undefined;
}

/** Presentation only: saved Python order, evaluations and versions are authoritative.
 * Never execute the JS fallback, re-filter candidates or recompute a score here.
 */
export function v1SearchModel(turn:TurnSnapshot):Record<string,unknown>{
 const result=snapshotResult<SearchResult>(turn.answerSnapshot);
 if(result.kind==='forward_lookup')return {
  intent:'FORWARD_LOOKUP',status:result.resultStatus,runSummary:result.selectedRun??result.candidates?.[0]??null,
  // A converted pressure notice uses saved input and normalized server result.
  originalValues:originalConditions(turn,result),
 };
 const groups=searchGroups(result);
 const saved=new Map<string,{evaluations?:Snapshot[];matchPercent?:number}>();
 for(const entry of result.candidateEvaluations??[])saved.set(entry.runVersionId,entry);
 for(const entry of [...(result.commonCandidates??[]),...(result.objectiveResults??[]).flatMap(group=>group.candidates)])saved.set(entry.run.runVersionId,entry);
 const presentations=new Map<string,ReturnType<typeof buildCandidate>>();
 function candidate(run:RunSummary){
  const key=`${run.runId}\u0000${run.runVersionId}`;
  const cached=presentations.get(key);
  if(cached)return cached;
  const presentation=buildCandidate(run);presentations.set(key,presentation);return presentation;
 }
 function buildCandidate(run:RunSummary){
  const entry=saved.get(run.runVersionId);
  const rows=(entry?.evaluations??[]).map(evaluation=>{
   const unit=String(evaluation.unit??run.units[evaluation.metric as keyof typeof run.units]??'');
   const percent=finite(evaluation.percentDelta)?signed(evaluation.percentDelta,1,'%'):null;
   return {...evaluation,satisfied:evaluation.satisfied===true,label:searchMetricNames[String(evaluation.metric)]??evaluation.metric,
    actualLabel:display(evaluation.actual),unit,targetLabel:`${evaluation.targetLabel??''} ${unit}`.trim(),
    differenceLabel:evaluation.rangeStatus==='IN_RANGE'?'범위 안':!finite(evaluation.boundaryDelta)?'비교 불가':`${signed(evaluation.boundaryDelta,2,` ${unit}`)}${percent?` (${percent})`:''}`,
    referenceLabel:`${evaluation.operator==='RANGE'?'범위 중앙값':'검색 기준'} ${display(evaluation.referenceValue)} ${unit}`,
   };
  });
  const satisfied=rows.filter(row=>row.satisfied).length;
  const count=rows.length;
  return {runId:run.runId,runVersionId:run.runVersionId,
   conditions:(['pressure','sourcePower','biasPower'] as const).map(metric=>({metric,value:display(run[metric],0)})),
   metrics:(['ionFlux','meanIonEnergy','iedWidth'] as const).map(metric=>({metric,value:display(run.metrics[metric],0)})),
   objectiveRows:rows,matchPercent:entry?.matchPercent,savedEvaluationsOnly:true,proximityUnavailable:count>0&&!finite(entry?.matchPercent),
   matchSummary:count>0&&satisfied===count?`${count}개 목표 모두 기준 충족`:satisfied===0?`미충족 목표 ${count}개 · 수치 차이 기반`:`목표 ${satisfied}개 충족 · 미충족 목표 ${count-satisfied}개`,
   baselineRows:[],
  };
 }
 const displayGroups=groups.map(group=>({id:group.id,label:`${group.label} ${group.runs.length}`,notice:groupNotice(group.id),candidates:group.runs.map(candidate)}));
 const versions=turn.answerSnapshot.versions as {promptVersion?:string}|undefined;
 const oldRange=versions?.promptVersion==='interpret-1'&&(result.goals??[]).some(goal=>goal.direction==='target_range')&&!/범위\s*(?:밖|외).*(?:허용|포함)|allow.*outside.*range/i.test(turn.question);
 return {intent:'REVERSE_SEARCH',status:result.resultStatus,
  interpretationNote:oldRange?'저장된 답변은 범위를 정렬 목표로 해석한 이전 결과입니다. 수정된 범위 검색은 같은 질문을 다시 보내면 적용됩니다.':undefined,
  constraints:(result.constraints??[]).map(legacyRule),
  goals:(result.goals??[]).map(goal=>({...goal,direction:goal.direction==='minimize'?'MIN':goal.direction==='maximize'?'MAX':'TARGET_RANGE'})),
  objectives:result.objectives??[],showIndependentGroups:true,showCurrentSortNote:false,
  candidateGroups:{groups:displayGroups,activeGroupId:'common',viewportCardCount:6,conflictSummary:'모든 필수 조건을 동시에 만족하는 실제 Run이 없습니다. 조건별 결과를 확인하거나 범위를 조정해 주세요.'},
 };
}

function originalConditions(turn:TurnSnapshot,result:SearchResult){
 const interpretation=turn.answerSnapshot.interpretation as {operations?:{inputs?:{conditions?:Record<string,{value:number;unit?:string}>}}[]}|undefined;
 const selection=turn.answerSnapshot.toolSelection as {arguments?:{conditions?:Record<string,{value:number;unit?:string}>}}|undefined;
 const pressure=selection?.arguments?.conditions?.pressure??interpretation?.operations?.[0]?.inputs?.conditions?.pressure;
 return pressure?{pressure:{...pressure,normalizedValue:result.requestedConditions?.pressure}}:undefined;
}
