import {isGraphV2AnswerSnapshot,queryDefaultUnits,type RunSummary,type Snapshot} from 'agent';
import {metricNames,searchGroups,snapshotResult,type SearchResult} from '../agent/agent-contract';

export const demoRunId='RUN-P06-S300-B0600';
export type DecisionGoal={mode:'damage'|'rate';change:number;tolerance:number};
export const damageGoal:DecisionGoal={mode:'damage',change:10,tolerance:5};
export const rateGoal:DecisionGoal={mode:'rate',change:10,tolerance:5};
const conditions=['pressure','sourcePower','biasPower'] as const;
const conditionLabels={
  pressure:'압력|\\bpressure',
  sourcePower:'소스(?:\\s*(?:전력|파워))?|\\bsource(?:\\s*power)?',
  biasPower:'바이어스(?:\\s*(?:전력|파워))?|\\bbias(?:\\s*power)?',
};
const nonExact='이상|이하|초과|미만|또는|혹은|내지|대략|약|정도|내외|쯤|[<>≤≥≈~–]|-(?=\\s*\\d)';
const conditionBoundary=String.raw`(?:${Object.values(conditionLabels).join('|')}|${nonExact}|에서(?=\s|[,.!?]|$))`;
const requiredMetrics=[...conditions,'meanIonEnergy','ionFlux'] as const;
type Metric='pressure'|'sourcePower'|'meanIonEnergy'|'ionFlux';
export type DecisionRule={metric:Metric;unit:string}&(
  {operator:'eq'|'lte'|'gte';value:number}|{operator:'between';min:number;max:number}
);
const sameRef=(a:RunSummary,b:RunSummary)=>a.runId===b.runId&&a.runVersionId===b.runVersionId;

export function resolveDecisionRun(question:string,catalog:RunSummary[],selected:RunSummary|undefined) {
  const tokens=new Set(question.toUpperCase().match(/[A-Z0-9_-]+/g)??[]);
  const named=catalog.filter(run=>tokens.has(run.runId.toUpperCase()));
  if([...tokens].some(token=>token.startsWith('RUN-')&&!named.some(run=>run.runId.toUpperCase()===token)))return [];
  const stated=new Map<typeof conditions[number],number>();
  for(const key of conditions){
    const pattern=new RegExp(
      String.raw`(?:${conditionLabels[key]})\s*[:은는이가을를]?\s*(${nonExact}|=)?\s*([+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?)(?:\s*(?!${conditionBoundary})([a-z%]+|[가-힣]+))?\s*(${nonExact})?`,'gi');
    const baseUnits=key==='pressure'?['mtorr','밀리토르','밀리토어','millitorr']:['w','와트'];
    for(const [,operator,number,unit,suffix] of question.normalize('NFKC').matchAll(pattern)){
      const normalized=(unit??queryDefaultUnits[key]).toLowerCase();
      const scale=key==='pressure'&&['torr','토르','토어'].includes(normalized)?1000:baseUnits.includes(normalized)?1:null;
      const value=Number(number.replaceAll(',',''));
      if(scale===null||!valid(value*scale)||value<0||(operator&&operator!=='=')||suffix)return [];
      if(stated.has(key)&&stated.get(key)!==value*scale)return [];
      stated.set(key,value*scale);
    }
  }
  if(stated.size)return (named.length?named:catalog).filter(run=>[...stated].every(([key,value])=>
    run[key]===value&&run.units[key]===queryDefaultUnits[key]));
  return named.length?named:selected?[selected]:[];
}

const valid=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value);
const usable=(run:RunSummary)=>run.catalogStatus==='READY'&&run.qualityStatus==='VERIFIED'&&run.convergenceStatus==='CONVERGED';
const measurement=(run:RunSummary,metric:Metric)=>metric==='pressure'||metric==='sourcePower'?run[metric]:run.metrics[metric];

export function baselineIssue(run:RunSummary) {
  if(!usable(run))return '등록 상태, 수렴 또는 품질을 확인할 수 없습니다.';
  for(const metric of requiredMetrics){
    const value=metric==='biasPower'?run.biasPower:measurement(run,metric);
    if(!valid(value))return `${metricNames[metric]} 기준값이 없습니다.`;
    if(run.units[metric]!==queryDefaultUnits[metric])return `${metricNames[metric]} 단위를 확인할 수 없습니다.`;
    if((metric==='ionFlux'||metric==='meanIonEnergy')&&value<=0)return `${metricNames[metric]} 기준값으로 변화율을 계산할 수 없습니다.`;
  }
  return null;
}

export function getDecisionRules(run:RunSummary,goal:DecisionGoal):DecisionRule[]|null {
  if(baselineIssue(run))return null;
  const energy=run.metrics.meanIonEnergy;
  const flux=run.metrics.ionFlux;
  const base:DecisionRule[]=[
    {metric:'pressure',operator:'eq',value:run.pressure,unit:queryDefaultUnits.pressure},
    {metric:'sourcePower',operator:'eq',value:run.sourcePower,unit:queryDefaultUnits.sourcePower},
  ];
  const change=goal.change/100;
  const tolerance=goal.tolerance/100;
  const output:DecisionRule[]=goal.mode==='damage'?[
    {metric:'meanIonEnergy',operator:'lte',value:energy*(1-change),unit:queryDefaultUnits.meanIonEnergy},
    {metric:'ionFlux',operator:'between',min:flux*(1-tolerance),max:flux*(1+tolerance),unit:queryDefaultUnits.ionFlux},
  ]:[
    {metric:'ionFlux',operator:'gte',value:flux*(1+change),unit:queryDefaultUnits.ionFlux},
    {metric:'meanIonEnergy',operator:'lte',value:energy*(1+tolerance),unit:queryDefaultUnits.meanIonEnergy},
  ];
  return [...base,...output];
}

function ruleText(rule:DecisionRule) {
  const label=metricNames[rule.metric];
  if(rule.operator==='between')return `${label} ${rule.min} 이상 ${rule.max} 이하 (${rule.unit})`;
  const operator={eq:'정확히',lte:'이하',gte:'이상'}[rule.operator];
  return `${label} ${rule.value} ${rule.unit} ${operator}`;
}

export function searchQuestion(rules:DecisionRule[],followup?:string) {
  return `등록된 실제 Run에서 다음 조건을 모두 만족하는 후보 전체를 검색해줘. ${rules.map(ruleText).join(', ')}. 조건은 모두 필수야. 검색 후, 후보들의 측정값을 근거로 다음 비교에서 바이어스 전력만 바꿔 볼 이유와 이온 플럭스·평균 이온 에너지에서 관찰된 차이를 비전공자도 이해할 말로 해석해줘. 인과를 단정하거나 측정하지 않은 식각 속도·손상·최소 식각 에너지 기준을 실제 결과처럼 말하지 마.${followup?`\n후속 질문 ${JSON.stringify(followup)}`:''}`;
}

function sameRule(saved:Snapshot,rule:DecisionRule) {
  return saved.metric===rule.metric&&saved.operator===rule.operator&&saved.unit===rule.unit&&(
    rule.operator==='between'?saved.min===rule.min&&saved.max===rule.max:saved.value===rule.value);
}

function meetsRule(run:RunSummary,rule:DecisionRule) {
  const value=measurement(run,rule.metric);
  if(!valid(value)||run.units[rule.metric]!==rule.unit)return false;
  if(rule.operator==='between')return value>=rule.min&&value<=rule.max;
  if(rule.operator==='eq')return value===rule.value;
  return rule.operator==='lte'?value<=rule.value:value>=rule.value;
}

/** Read the common result only. Per-objective and near-match groups can violate approved bounds. */
export function confirmedCandidates(snapshot:Snapshot,baseline:RunSummary,rules:DecisionRule[]):RunSummary[]|null {
  if(!isGraphV2AnswerSnapshot(snapshot)||snapshot.executionStatus==='FAILED')return null;
  const searches=snapshot.stepResults.filter(step=>['verified','empty'].includes(step.status)&&
    step.outputs.toolResult&&typeof step.outputs.toolResult==='object'&&!Array.isArray(step.outputs.toolResult)&&
    step.outputs.toolResult.kind==='reverse_search');
  if(searches.length!==1)return null;
  const result=snapshotResult<SearchResult>({result:searches[0].outputs.toolResult});
  if(!['MATCH','NO_MATCH'].includes(result.resultStatus)||result.goals?.length||result.constraints?.length!==rules.length||
    !rules.every(rule=>result.constraints!.some(saved=>sameRule(saved,rule))))return null;
  const runs=searchGroups(result)[0].runs;
  if((result.resultStatus==='MATCH')!==Boolean(runs.length)||runs.some(run=>!usable(run)||
    !valid(run.biasPower)||run.units.biasPower!==queryDefaultUnits.biasPower||!rules.every(rule=>meetsRule(run,rule))))return null;
  return runs.filter(run=>!sameRef(run,baseline)&&run.biasPower!==baseline.biasPower)
    .sort((a,b)=>Math.abs(a.biasPower-baseline.biasPower)-Math.abs(b.biasPower-baseline.biasPower));
}
