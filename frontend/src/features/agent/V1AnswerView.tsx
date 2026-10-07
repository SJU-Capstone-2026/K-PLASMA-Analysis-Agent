import type {TurnSnapshot,Snapshot,ComparisonAnswer,ComparisonResultV2,GeneralAnswerResult} from 'agent';
import {PrototypeAnswerMarkup,type AnswerAction} from './PrototypeAnswerMarkup';
import {v1SearchModel} from './v1-search-model';
import {GeneralAnswerCard} from './GeneralAnswerCard';
import {ExplanationCard} from './ExplanationCard';
import {RunComparisonCard} from './RunComparisonCard';
import {metricNames,snapshotResult,type ComparisonResult,type ExplanationResult} from './agent-contract';
const titles:Record<string,string>={forward_lookup:'조건으로 Run 조회',reverse_search:'목표에 맞는 Run 탐색',compare_runs:'기준·대상 Run 비교',explain_change:'결과 변화 설명',explain_concept:'플라즈마 개념 설명',generate_answer:'일반 질문 답변'};
function AppliedInterpretation({snapshot}:{snapshot:Snapshot}){const selection=snapshot.toolSelection as unknown as {name:string;arguments:Record<string,unknown>}|undefined;const parsed=(snapshot.schemaVersion===2?{operations:[{kind:selection?.name??'',inputs:snapshot.resolvedInputs}]}:snapshot.interpretation) as unknown as {operations?:{kind:string;inputs:Record<string,unknown>}[]}|undefined;const history=snapshot.inputHistory as unknown as {text?:string;input?:{text?:string}}[]|undefined;return <details className="v1-interpretation"><summary>질문 해석·추가 입력</summary>{(history??[]).map((event,index)=><p key={index}>{event.text??event.input?.text??''}</p>)}{parsed?.operations?.map((op,index)=><div key={index}><strong>{titles[op.kind]??op.kind}</strong><ul>{Object.entries(op.inputs).map(([key,value])=><li key={key}>{metricNames[key]??({conditions:'조회 조건',constraints:'필수 조건',goals:'탐색 목표',metrics:'비교 지표',topics:'설명 개념',aspect:'설명 범위',baseline:'기준 Run',target:'대상 Run'}[key]??key)}: {inputLabel(value)}</li>)}</ul></div>)}</details>;}
function inputLabel(value:unknown):string{if(value==null)return '미지정';if(typeof value==='string')return metricNames[value]??value;if(typeof value==='number'||typeof value==='boolean')return String(value);if(Array.isArray(value))return value.map(inputLabel).join(', ');if(typeof value==='object')return Object.entries(value).map(([key,v])=>`${metricNames[key]??key} ${inputLabel(v)}`).join(' · ');return '';}
function answerBody(turn:TurnSnapshot,onAction:AnswerAction){
 const snapshot=turn.answerSnapshot;
 switch(String(snapshot.kind)){
  case 'compare_runs': return <RunComparisonCard result={snapshotResult<ComparisonResult|ComparisonResultV2>(snapshot)} answer={snapshot.answer as unknown as ComparisonAnswer|null} onAction={onAction}/>;
  case 'generate_answer': return <GeneralAnswerCard result={snapshotResult<GeneralAnswerResult>(snapshot)}/>;
  case 'explain_change':
  case 'explain_concept': return <ExplanationCard result={snapshotResult<ExplanationResult>(snapshot)} onAction={onAction}/>;
  case 'forward_lookup':
  case 'reverse_search': return <PrototypeAnswerMarkup answer={v1SearchModel(turn)} turn={turn} onAction={onAction}/>;
  default: return <p>지원 범위: 조건 조회 · 후보 탐색 · Run 비교 · 변화 설명 · 개념 설명</p>;
 }
}
export function V1AnswerView({turn,onAction}:{turn:TurnSnapshot;onAction:AnswerAction}){const snapshot=turn.answerSnapshot;const search=['forward_lookup','reverse_search'].includes(String(snapshot.kind));return <div className={search?'v1-search-answer':'v1-answer'} data-implementation="v1">{!search&&typeof snapshot.summary==='string'&&<p className="v1-summary">{snapshot.summary}</p>}{answerBody(turn,onAction)}{!search&&<AppliedInterpretation snapshot={snapshot}/>}</div>;}
