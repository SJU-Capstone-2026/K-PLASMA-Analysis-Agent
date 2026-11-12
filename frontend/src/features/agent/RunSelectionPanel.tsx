import {useEffect,useMemo,useState} from 'react';
import type {AgentRequestView,LegacyRunOptions,RunOption,Snapshot} from 'agent';
import {fetchLegacyRunOptions} from '../../api/agent';
import {measurementText,metricNames,numberText,reasons,reverseSearchCriteria} from './agent-contract';
import {RunPicker} from './RunPicker';

type RunSelectionProps={request:AgentRequestView;sending:boolean;onResume:(input:Snapshot)=>Promise<void>;onError:(error:unknown)=>void;onCancel?:()=>Promise<void>};
export function RunSelectionPanel(props:RunSelectionProps){
 const key=`${props.request.requestId}:${props.request.requestRevision}:${props.request.pendingInput!.id}`;
 return ['v2','v3'].includes(props.request.graphVersion)?<LegacyRunPicker key={key} {...props}/>:<RunPicker key={key} {...props}/>;
}

function LegacyRunPicker({request,sending,onResume,onError,onCancel}:RunSelectionProps){
 const pending=request.pendingInput!;
 const [options,setOptions]=useState<RunOption[]>([]);const [loaded,setLoaded]=useState(false);const [error,setError]=useState('');
 const [criteria,setCriteria]=useState<LegacyRunOptions['searchCriteria']>();
 const [query,setQuery]=useState('');const [order,setOrder]=useState('source');const [selected,setSelected]=useState(new Set<string>());const [baseline,setBaseline]=useState('');const [retry,setRetry]=useState(0);
 useEffect(()=>{const controller=new AbortController();setLoaded(false);setCriteria(undefined);setError('');setSelected(new Set());setBaseline('');setQuery('');setOrder('source');
  fetchLegacyRunOptions(request.requestId,pending.id,controller.signal).then(result=>{
   if(controller.signal.aborted)return;
   if(result.requestId!==request.requestId||result.pendingInputId!==pending.id||result.requestRevision!==request.requestRevision)throw new Error('실험 선택 상태가 바뀌었습니다. 화면을 새로고침해 주세요.');
   setOptions(result.options);setCriteria(result.searchCriteria);setLoaded(true);
  }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:String(e));});return()=>controller.abort();
 },[request.requestId,request.requestRevision,pending.id,retry]);
 const visible=useMemo(()=>{
  const matches=options.filter(o=>`${o.key} ${o.ref.runId} ${o.ref.runVersionId} ${Object.values(o.conditions).map(v=>`${v.value} ${v.unit}`).join(' ')}`.toLowerCase().includes(query.toLowerCase()));
  if(order==='source')return matches;
  return matches.sort((a,b)=>(order==='ascending'?1:-1)*a.ref.runId.localeCompare(b.ref.runId,undefined,{numeric:true}));
 },[options,query,order]);
 const chosen=options.filter(o=>selected.has(o.key));
 const min=pending.minSelections??2;
 const max=pending.maxSelections;
 const exact=max===min;
 const atLimit=max!==undefined&&chosen.length>=max;
 const valid=chosen.length>=min&&(max===undefined||chosen.length<=max)&&chosen.every(o=>o.selectable)&&(!pending.baselineRequired||!!baseline)&&(!baseline||selected.has(baseline));
 const duplicateIds=useMemo(()=>{
  const seen=new Set<string>();
  const duplicates=new Set<string>();
  for(const {ref} of options){
   if(seen.has(ref.runId))duplicates.add(ref.runId);
   seen.add(ref.runId);
  }
  return duplicates;
 },[options]);
 const conditions=criteria?reverseSearchCriteria({constraints:criteria.constraints},true).join(' · '):'';
 const ordering=criteria?reverseSearchCriteria({goals:criteria.goals}).join(' · '):'';
 const shown=new Set(visible.map(o=>o.key));
 const hiddenSelection=chosen.filter(o=>!shown.has(o.key));
 function toggle(key:string){if(!selected.has(key)&&atLimit)return;setSelected(previous=>{const next=new Set(previous);if(next.has(key))next.delete(key);else next.add(key);return next;});if(baseline===key)setBaseline('');}
 const baselineField=<label className="v1-baseline">비교 기준 {pending.baselineRequired?'(필수)':'(선택)'}
  <select disabled={sending} value={baseline} onChange={e=>setBaseline(e.target.value)}>
   <option value="">{pending.baselineRequired?'기준 Run 선택':'기준 없이 비교'}</option>
   {chosen.map(o=><option key={o.key} value={o.key}>{o.key} · {o.ref.runId}</option>)}
  </select>
 </label>;

 return <div className="v1-run-selection">
  <h3>{criteria?'검색 결과':pending.message}</h3>
  {error?<div role="alert"><p>{error}</p><button type="button" className="button button--ghost button--small" onClick={()=>setRetry(v=>v+1)}>목록 다시 불러오기</button></div>:!loaded?<p role="status">실험 목록을 불러오고 있습니다.</p>:<>
   {criteria&&<p className="v1-picker-summary">
    <span>{conditions?conditions+' 조건에 맞는 Run을':'후보 Run을'} {options.length.toLocaleString('ko-KR')}개 찾았어요.</span>{' '}
    이 중에서 비교할 Run을 {exact?`${min}개 `:''}골라 주세요.
    {ordering&&<small>검색 정렬 기준 · {ordering}</small>}
   </p>}
   <div className="v1-picker-toolbar">
    <input type="search" aria-label="실험 검색" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Run 이름·버전·조건 검색"/>
    <span>{query?visible.length+'/'+options.length:options.length}개</span>
   </div>
   <fieldset className="v1-picker-list" aria-label="비교할 실험" disabled={sending}>
    {visible.map(o=><label key={o.key} className={`v1-picker-option${selected.has(o.key)?' is-selected':''}`} title={`버전 ${o.ref.runVersionId}`}>
     <input type="checkbox" aria-label={`${o.key} · ${o.ref.runId} · ${o.ref.runVersionId}`} checked={selected.has(o.key)} disabled={!o.selectable||(!selected.has(o.key)&&atLimit)} onChange={()=>toggle(o.key)}/>
     <span className="v1-picker-row">
      <strong>{o.ref.runId}</strong>
      <small>{(['pressure','sourcePower','biasPower'] as const).map(field=>{
       const {value,unit}=o.conditions[field];
       return `${{pressure:'',sourcePower:'소스 ',biasPower:'바이어스 '}[field]}${numberText(value)} ${unit}`;
      }).join(' · ')}</small>
      {o.searchMeasurements&&<small className="v1-picker-measurements">
       {Object.entries(o.searchMeasurements).map(([field,datum])=><span key={field} title={datum.reason?reasons[datum.reason]:undefined}>
        {metricNames[field]} {datum.value==null?'—':measurementText(numberText(datum.value),datum.unit)}
       </span>)}
      </small>}
      {duplicateIds.has(o.ref.runId)&&<small className="v1-picker-row-note">버전 {o.ref.runVersionId}</small>}
      {!o.selectable&&<small className="v1-picker-row-note">{reasons[o.unavailableReason??'']??'삭제되었거나 비교할 수 없는 실험입니다.'}</small>}
     </span>
    </label>)}
    {!visible.length&&<p>검색에 맞는 실험이 없습니다.</p>}
   </fieldset>
   {!!hiddenSelection.length&&<div className="v1-picker-chips" aria-label="검색에서 숨겨진 선택">
    {hiddenSelection.map(o=><button key={o.key} type="button" disabled={sending} onClick={()=>toggle(o.key)} aria-label={`${o.key} ${o.ref.runId} 선택 해제`}>{o.ref.runId} ×</button>)}
   </div>}
   {pending.baselineRequired&&baselineField}
   <details className="v1-picker-options" key={pending.id}>
    <summary>선택 옵션</summary>
    <div className="v1-picker-controls">
     <label>목록 정렬<select value={order} onChange={e=>setOrder(e.target.value)}><option value="source">{criteria?'검색 결과 순':'기본 순'}</option><option value="ascending">이름 오름차순</option><option value="descending">이름 내림차순</option></select></label>
     {!pending.baselineRequired&&baselineField}
    </div>
    <div className="v1-picker-actions">
     {max===undefined&&<button type="button" className="button button--ghost button--small" disabled={sending} onClick={()=>setSelected(new Set(options.filter(o=>o.selectable).map(o=>o.key)))}>선택 가능한 실험 전체 선택</button>}
     <button type="button" className="button button--ghost button--small" disabled={sending||!chosen.length} onClick={()=>{setSelected(new Set());setBaseline('');}}>선택 해제</button>
    </div>
   </details>
  </>}
  <div className="v1-picker-footer">
   {loaded&&<span role="status">{exact?`${chosen.length}/${min}개 선택`:`${chosen.length}개 선택 · 최소 ${min}개`}</span>}
   <div className="v1-picker-actions">
    {onCancel&&<button type="button" className="button button--ghost button--small" disabled={sending} onClick={()=>onCancel().catch(onError)}>분석 취소</button>}
    {loaded&&<button type="button" className="button button--primary button--small" disabled={sending||!valid} onClick={()=>onResume({type:'run_selection',runKeys:chosen.map(o=>o.key),baselineKey:baseline||null}).catch(onError)}>선택한 실험으로 계속</button>}
   </div>
  </div>
 </div>;
}

export function ComparisonOptionsPanel({request,sending,onResume,onCancel,onError}: {
 request:AgentRequestView;sending:boolean;onResume:(input:Snapshot)=>Promise<void>;onCancel:()=>Promise<void>;onError:(error:unknown)=>void;
}){
 const pending=request.pendingInput!;
 const [baseline,setBaseline]=useState('');
 const [axis,setAxis]=useState('');
 useEffect(()=>{setBaseline('');setAxis('');},[pending.id]);
 const needsBaseline=pending.fields?.includes('baselineKey');
 const needsAxis=pending.fields?.includes('trendAxis');
 const valid=(!needsBaseline||!!baseline)&&(!needsAxis||!!axis);
 const runLabels=new Map(pending.options?.map(option=>[option.input.baselineKey,option.label]));
 return <form className="comparison-options-form" onSubmit={event=>{
  event.preventDefault();
  onResume({type:'comparison_options',...(needsBaseline?{baselineKey:baseline}:{}),...(needsAxis?{trendAxis:axis}:{})}).catch(onError);
 }}>
  {needsBaseline&&<div className="comparison-options-intro">
   <h3>비교 기준으로 쓸 Run을 먼저 선택해 주세요.</h3>
   <p>다른 Run의 값이 기준보다 얼마나 높거나 낮은지 보여드려요.</p>
  </div>}
  {needsAxis&&<p>{pending.message}</p>}
  {needsBaseline&&<label>
   <span className="sr-only">기준 실험</span>
   <select value={baseline} onChange={event=>setBaseline(event.target.value)} required disabled={sending}>
    <option value="">기준 Run 선택</option>
    {pending.allowedRunKeys?.map(key=><option key={key} value={key}>{runLabels.get(key)??key}</option>)}
   </select>
  </label>}
  {needsAxis&&<label>경향을 볼 조건
   <select value={axis} onChange={event=>setAxis(event.target.value)} required disabled={sending}>
    <option value="">조건 선택</option>
    {pending.allowedTrendAxes?.map(key=><option key={key} value={key}>{{pressure:'압력',sourcePower:'소스 전력',biasPower:'바이어스 전력'}[key]}</option>)}
   </select>
  </label>}
  <div className="comparison-options-actions">
   <button type="submit" className="button button--primary button--small" disabled={sending||!valid}>선택하고 계속</button>
   <button type="button" className="button button--ghost button--small" disabled={sending} onClick={()=>onCancel().catch(onError)}>분석 취소</button>
  </div>
 </form>;
}
