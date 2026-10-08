import {viewModels,type RunRef,type RunSummary,type Snapshot} from 'agent';
export const metricNames:Record<string,string>={pressure:'압력',sourcePower:'소스 전력',biasPower:'바이어스 전력',ionFlux:'이온 플럭스',meanIonEnergy:'평균 이온 에너지',iedWidth:'IED 폭'};
export const reasons:Record<string,string>={ZERO_BASELINE:'기준값이 0이므로 변화율 계산 불가',MISSING_VALUE:'측정값 없음',INSUFFICIENT_DATA:'비교 자료 부족',MISSING_BASELINE:'기준값 없음',MISSING_TARGET:'대상값 없음',MISSING_BOTH:'양쪽 값 없음',INVALID_VALUE:'유효하지 않은 값',UNIT_NOT_COMPARABLE:'단위를 비교할 수 없음',NUMERIC_OVERFLOW:'계산 범위 초과'};
export interface ComparisonRow {field?:string;metric?:string;baseline:number|null;target:number|null;delta:number|null;percentChange?:number|null;unit:string;status:string;reason?:string|null;sourceValues?:{baseline?:{value:number;unit:string};target?:{value:number;unit:string}}}
export interface ComparisonResult {kind:'compare_runs';resultStatus:string;baseline:RunRef;target:RunRef;conditions:ComparisonRow[];metrics:ComparisonRow[];changedConditions:string[];quality?:{baseline:Record<string,string>;target:Record<string,string>}}
export interface ExplanationResult {kind:'explain_change'|'explain_concept';resultStatus:string;comparison?:ComparisonResult;knowledgeBasis:string;causality?:string;limitations?:string[];explanation?:{status:string;interpretations?:{text:string;observation_refs:string[];assumptions:string[]}[];sections?:{text:string;topic_refs:string[]}[];limitations?:string[];suggested_checks?:string[]}}
export interface SearchObjective extends Snapshot {id:string;metric:string}
export interface EvaluatedCandidate {run:RunSummary;evaluations?:Snapshot[];matchPercent?:number}
export interface SearchResult {kind:'forward_lookup'|'reverse_search';resultStatus:string;selectedRun?:RunSummary|null;requestedConditions?:Record<string,number>;candidates?:RunSummary[];constraints?:Snapshot[];goals?:{metric:string;direction:string;min?:number;max?:number}[];objectives?:SearchObjective[];commonCandidates?:EvaluatedCandidate[];candidateEvaluations?:(RunRef&{evaluations:Snapshot[];matchPercent:number})[];objectiveResults?:{objective:SearchObjective;candidates:EvaluatedCandidate[];allConstraintsGuaranteed:boolean}[];goalResults?:{goal:{metric:string;direction:string;min?:number;max?:number};candidates:RunSummary[];allConstraintsGuaranteed:boolean}[];nearMisses?:{run:RunSummary;violations:{metric:string;reason?:string;operator:string;actual:number|null;required:unknown}[]}[];excludedRuns?:{runId:string;reasons:{metric?:string;code:string}[]}[];sourceFileCount?:number|null}
export const searchMetricNames:Record<string,string>=Object.fromEntries(Object.entries(viewModels.METRIC_META).map(([key,meta])=>[key,meta.label]));
/** Saved ranking-only groups remain in historical snapshots but are not condition results. */
export function searchGroups(result:SearchResult){
 if(result.kind==='forward_lookup')return [{id:'common',label:result.resultStatus==='EXACT'?'정확 일치 Run':'근접 Run',runs:result.candidates??(result.selectedRun?[result.selectedRun]:[])}];
 return [
  {id:'common',label:'조건 일치 결과',runs:(result.commonCandidates??[]).map(candidate=>candidate.run)},
  ...(result.objectiveResults??[]).map((group,index)=>({id:`objective-${index}`,label:`${searchMetricNames[group.objective.metric]??group.objective.metric} 조건`,runs:group.candidates.map(candidate=>candidate.run)})),
  ...(result.resultStatus==='NO_MATCH'&&(result.nearMisses?.length??0)>0?[{id:'near',label:'조건 미충족 근접 후보',runs:result.nearMisses!.map(item=>item.run)}]:[]),
 ];
}
export function snapshotResult<T>(snapshot:Snapshot):T{return snapshot.result as unknown as T;}
export function numberText(value:number|null|undefined,digits=2,signed=false){if(typeof value!=='number'||!Number.isFinite(value))return '—';const rounded=Number(value.toFixed(digits));return `${signed&&rounded>0?'+':''}${rounded.toLocaleString('ko-KR',{maximumFractionDigits:digits})}`;}

for(const [plot,name] of Object.entries({current:'RF 전류 밀도',potential:'전극 전위'}))for(const [suffix,label] of Object.entries({maximum:'최댓값',minimum:'최솟값',peakToPeak:'첨두간 값',halfPeakToPeak:'반첨두간 진폭',maximumPhase:'첫 최대 RF 위상',minimumPhase:'첫 최소 RF 위상'}))metricNames[`${plot}.${suffix}`]=`${name} ${label}`;
Object.assign(metricNames,{'ied.maximum':'IED 최대 강도','ied.peakEnergy':'IED 첫 최대 에너지','iad.maximum':'IAD 최대 강도','iad.peakAngle':'IAD 첫 최대 입사각','iead.maximum':'IEAD 최대 강도','iead.peakEnergy':'IEAD 첫 최대 에너지','iead.peakAngle':'IEAD 첫 최대 입사각','density.maximum':'쉬스 이온 밀도 최댓값','density.maximumPhase':'밀도 첫 최대 RF 위상','density.maximumDistance':'밀도 첫 최대 거리','residual.maximum':'최대 잔차','residual.maximumIteration':'첫 최대 잔차 반복','residual.final':'마지막 잔차','residual.finalIteration':'마지막 반복'});
