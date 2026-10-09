import {ComparisonCharts} from './ComparisonCharts';
import {useRunColors} from '../../components/RunColors';
import type {ComparisonResultV2,ScalarDatum} from 'agent';
import type {ComparisonResult,ComparisonRow} from './agent-contract';
import {metricNames,numberText,reasons} from './agent-contract';
import type {AnswerAction} from './AnswerView';
const scalarText=(value:ScalarDatum)=>value.status==='AVAILABLE'?`${numberText(value.value)} ${value.unit}`:`— (${reasons[value.reason??'']??value.reason})${value.sourceValue?` · 원값 ${numberText(value.sourceValue.value)} ${value.sourceValue.unit}`:''}`;
function MultiRunComparison({result,onAction,storageId}:{storageId?:string;result:ComparisonResultV2;onAction?:AnswerAction}){
 const colors=useRunColors(result.runs.map(r=>r.ref.runId));
 const directional=result.comparisons.some(row=>row.kind!=='absolute_difference');
 const context=result.baselineKey
  ? `${result.baselineKey} 기준 · 변화량 = 대상 − 기준`
  : result.mode==='trend'
   ? '다른 조건이 같은 집합에서 축 순서에 따른 변화량을 비교합니다.'
   : result.mode==='overview'?'기준 미지정 · 절대 차이·범위 비교':'기준 미지정 · 절대 차이 비교';
 return <section className="v1-comparison">
  <header className="comparison-heading">
   <h3>선택한 실험 비교 · {result.runs.length}개</h3><p>{context}</p>
  </header>
  <div className="comparison-layout">
   <div className="comparison-numbers">
    <div className="v1-table-scroll" tabIndex={0}>
     <table className="v1-comparison-table comparison-run-table" aria-label="선택한 실험 수치">
      <thead><tr>
       <th scope="col" className="comparison-ref">번호</th><th scope="col" className="comparison-run">실험</th>
       {result.metricIds.map(metric=><th scope="col" className="comparison-value" key={metric}>
        {metricNames[metric]}<small>{result.runs[0]?.metrics[metric]?.unit}</small>
       </th>)}
       {onAction&&<th scope="col" className="comparison-detail">상세</th>}
      </tr></thead>
      <tbody>{result.runs.map(run=><tr key={run.key}>
       <td className="comparison-ref"><span><i aria-hidden="true" className="comparison-color" style={{background:colors.get(run.ref.runId)}}/>{run.key}</span></td>
       <th scope="row" className="comparison-run">{run.ref.runId}</th>
       {result.metricIds.map(metric=><td className="comparison-value" key={metric}>
        {run.metrics[metric]?.status==='AVAILABLE'?numberText(run.metrics[metric]!.value):scalarText(run.metrics[metric]!)}
       </td>)}
       {onAction&&<td className="comparison-detail"><button className="button button--ghost button--small" type="button"
        aria-label={`${run.key} ${run.ref.runId} 실험 상세 보기`} data-run-id={run.ref.runId} data-run-version-id={run.ref.runVersionId}
        onClick={e=>onAction('open-run-detail',e.currentTarget)}>보기</button></td>}
      </tr>)}</tbody>
     </table>
    </div>
    {result.comparisons.length>0&&<>
     <h4>계산된 차이</h4>
     <div className="v1-table-scroll" tabIndex={0}>
      <table className="v1-comparison-table" aria-label="계산된 차이">
       <thead><tr><th scope="col">실험</th><th scope="col">지표</th><th scope="col" className="comparison-value">{directional?'변화량':'절대 차이'}</th>{directional&&<th scope="col" className="comparison-value">변화율</th>}</tr></thead>
       <tbody>{result.comparisons.map(row=><tr key={row.id}>
        <th scope="row">{row.leftKey} {row.kind==='absolute_difference'?'↔':'→'} {row.rightKey}</th><td>{metricNames[row.metric]}</td>
        <td className="comparison-value">{scalarText(row.difference)}</td>{directional&&<td className="comparison-value">{row.percentChange?scalarText(row.percentChange):'—'}</td>}
       </tr>)}</tbody>
      </table>
     </div>
    </>}
    {result.mode==='overview'&&<>
     <h4>선택한 실험의 범위</h4>
     <div className="v1-table-scroll" tabIndex={0}>
      <table className="v1-comparison-table" aria-label="선택한 실험의 범위">
       <thead><tr><th scope="col">지표</th>{['최솟값','최댓값','범위 폭','가용 실험'].map(label=><th scope="col" className="comparison-value" key={label}>{label}</th>)}</tr></thead>
       <tbody>{result.summaries.map(row=><tr key={row.id}>
        <th scope="row">{metricNames[row.metric]}</th><td className="comparison-value">{scalarText(row.minimum)}</td><td className="comparison-value">{scalarText(row.maximum)}</td>
        <td className="comparison-value">{scalarText(row.range)}</td><td className="comparison-value">{row.availableCount}개</td>
       </tr>)}</tbody>
      </table>
     </div>
    </>}
    {result.trends.length>0&&<><h4>같은 조건 집합의 경향</h4><ul>{result.observations.filter(o=>o.source.kind==='trend').map(o=><li key={o.id}>{o.text}</li>)}</ul></>}
   </div>
   <ComparisonCharts result={result} storageId={storageId}/>
  </div>
  {result.resultStatus==='NO_COMPARABLE_DATA'&&<p className="alert">비교 가능한 측정값이 부족합니다.</p>}
  {result.resultStatus==='COMPARISON_PARTIAL'&&<p className="alert">일부 값이나 변화율은 계산할 수 없습니다. 표의 비가용 이유를 확인해 주세요.</p>}
 </section>;
}
export function RunComparisonCard({result,onAction,storageId}:{storageId?:string;result:ComparisonResult|ComparisonResultV2;onAction?:AnswerAction}){
 if('runs' in result)return <MultiRunComparison result={result} onAction={onAction} storageId={storageId}/>;
 function table(rows:ComparisonRow[],percent:boolean){return <div className="v1-table-scroll" tabIndex={0}><table className="v1-comparison-table"><thead><tr><th>항목</th><th>기준</th><th>대상</th><th>차이</th>{percent&&<th>변화율</th>}<th>단위·비가용 이유</th></tr></thead><tbody>{rows.map((row,index)=><tr key={`${row.metric??row.field}-${index}`}><th>{metricNames[row.metric??row.field??'']??row.metric??row.field}</th><td>{numberText(row.baseline)}</td><td>{numberText(row.target)}</td><td>{numberText(row.delta,2,true)}</td>{percent&&<td>{row.percentChange==null?'—':`${numberText(row.percentChange,1,true)}%`}</td>}<td>{row.unit}<small>{row.reason?(reasons[row.reason]??row.reason):''}</small>{row.sourceValues&&<small>원값: {row.sourceValues.baseline?`${numberText(row.sourceValues.baseline.value)} ${row.sourceValues.baseline.unit}`:'—'} → {row.sourceValues.target?`${numberText(row.sourceValues.target.value)} ${row.sourceValues.target.unit}`:'—'}</small>}</td></tr>)}</tbody></table></div>;}
 return <section className="v1-comparison"><h3>Run 수치 비교</h3><div className="v1-run-pair">{([['baseline','기준'],['target','대상']] as const).map(([role,label])=><div key={role}><small>{label}</small><strong>{result[role].runId}</strong><small>버전 {result[role].runVersionId}</small><small>{Object.values(result.quality?.[role]??{}).join(' · ')}</small>{onAction&&<button type="button" className="button button--ghost button--small" data-run-id={result[role].runId} data-run-version-id={result[role].runVersionId} onClick={e=>onAction('open-run-detail',e.currentTarget)}>실험 상세</button>}</div>)}</div><p>차이 = 대상 − 기준 · 변화율은 기준값의 크기에 대한 비율입니다.</p><h4>공정 조건</h4>{table(result.conditions??[],false)}<h4>결과 지표</h4>{table(result.metrics??[],true)}{result.resultStatus==='NO_COMPARABLE_DATA'&&<p className="alert">비교할 수 있는 결과 지표가 없습니다.</p>}{result.resultStatus==='COMPARISON_PARTIAL'&&<p className="alert">일부 항목은 비교하거나 변화율을 계산할 수 없습니다.</p>}</section>;
}
