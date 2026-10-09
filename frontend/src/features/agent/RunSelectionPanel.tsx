import {useEffect,useMemo,useState} from 'react';
import type {AgentRequestView,RunOption,Snapshot} from 'agent';
import {fetchRunOptions} from '../../api/agent';
import {numberText,reasons} from './agent-contract';

export function RunSelectionPanel({request,sending,onResume,onError}:{request:AgentRequestView;sending:boolean;onResume:(input:Snapshot)=>Promise<void>;onError:(error:unknown)=>void}){
 const pending=request.pendingInput!;
 const [options,setOptions]=useState<RunOption[]>([]);const [loaded,setLoaded]=useState(false);const [error,setError]=useState('');
 const [query,setQuery]=useState('');const [order,setOrder]=useState('ascending');const [selected,setSelected]=useState(new Set<string>());const [baseline,setBaseline]=useState('');const [retry,setRetry]=useState(0);
 useEffect(()=>{const controller=new AbortController();setLoaded(false);setError('');setSelected(new Set());setBaseline('');setQuery('');
  fetchRunOptions(request.requestId,pending.id,controller.signal).then(result=>{
   if(controller.signal.aborted)return;
   if(result.requestId!==request.requestId||result.pendingInputId!==pending.id||result.requestRevision!==request.requestRevision)throw new Error('실험 선택 상태가 바뀌었습니다. 화면을 새로고침해 주세요.');
   setOptions(result.options);setLoaded(true);
  }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:String(e));});return()=>controller.abort();
 },[request.requestId,request.requestRevision,pending.id,retry]);
 const visible=useMemo(()=>options.filter(o=>`${o.key} ${o.ref.runId} ${o.ref.runVersionId} ${Object.values(o.conditions).map(v=>`${v.value} ${v.unit}`).join(' ')}`.toLowerCase().includes(query.toLowerCase())).sort((a,b)=>(order==='ascending'?1:-1)*a.ref.runId.localeCompare(b.ref.runId,undefined,{numeric:true})),[options,query,order]);
 const chosen=options.filter(o=>selected.has(o.key));const valid=chosen.length>=(pending.minSelections??2)&&chosen.every(o=>o.selectable)&&(!pending.baselineRequired||!!baseline)&&(!baseline||selected.has(baseline));
 function toggle(key:string){setSelected(previous=>{const next=new Set(previous);if(next.has(key))next.delete(key);else next.add(key);return next;});if(baseline===key)setBaseline('');}
 return <div className="v1-run-selection"><p>{pending.message}</p>{error?<div role="alert"><p>{error}</p><button type="button" className="button button--ghost button--small" onClick={()=>setRetry(v=>v+1)}>목록 다시 불러오기</button></div>:!loaded?<p role="status">실험 목록을 불러오고 있습니다.</p>:<>
  <div className="v1-picker-controls"><label>실험 검색<input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Run 이름·버전·조건 검색"/></label><label>목록 정렬<select value={order} onChange={e=>setOrder(e.target.value)}><option value="ascending">이름 오름차순</option><option value="descending">이름 내림차순</option></select></label></div>
  <div className="v1-card-actions"><button type="button" className="button button--ghost button--small" disabled={sending} onClick={()=>setSelected(new Set(options.filter(o=>o.selectable).map(o=>o.key)))}>선택 가능한 실험 전체 선택</button><button type="button" className="button button--ghost button--small" disabled={sending||!chosen.length} onClick={()=>{setSelected(new Set());setBaseline('');}}>선택 해제</button><span role="status">선택 {chosen.length}개 · 목록 {visible.length}/{options.length}개</span></div>
  <div className="v1-picker-chips" aria-label="선택한 실험">{chosen.map(o=><button key={o.key} type="button" disabled={sending} onClick={()=>toggle(o.key)} aria-label={`${o.key} ${o.ref.runId} 선택 해제`}>{o.key} · {o.ref.runId} ×</button>)}</div>
  <fieldset className="v1-picker-list" disabled={sending}><legend>비교할 실험 · 최소 {pending.minSelections??2}개</legend>{visible.map(o=><label key={o.key} className={`v1-picker-option${selected.has(o.key)?' is-selected':''}`}><input type="checkbox" aria-label={`${o.key} · ${o.ref.runId} · ${o.ref.runVersionId}`} checked={selected.has(o.key)} disabled={!o.selectable} onChange={()=>toggle(o.key)}/><span><strong>{o.key} · {o.ref.runId}</strong><small>버전 {o.ref.runVersionId}</small><small>{Object.values(o.conditions).map(v=>`${numberText(v.value)} ${v.unit}`).join(' · ')}</small>{!o.selectable&&<small>{reasons[o.unavailableReason??'']??'삭제되었거나 비교할 수 없는 실험입니다.'}</small>}</span></label>)}{!visible.length&&<p>검색에 맞는 실험이 없습니다. 기존 선택은 유지됩니다.</p>}</fieldset>
  <label className="v1-baseline">비교 기준 {pending.baselineRequired?'(필수)':'(선택)'}<select disabled={sending} value={baseline} onChange={e=>setBaseline(e.target.value)}><option value="">기준 없이 값·절대 차이·범위 비교</option>{chosen.map(o=><option key={o.key} value={o.key}>{o.key} · {o.ref.runId}</option>)}</select></label>
  <p className="v1-limitation">선택한 정확한 버전으로 비교합니다. 검색·정렬을 바꿔도 선택은 유지됩니다.</p>
  <button type="button" className="button button--primary" disabled={sending||!valid} onClick={()=>onResume({type:'run_selection',runKeys:chosen.map(o=>o.key),baselineKey:baseline||null}).catch(onError)}>선택한 실험으로 계속</button>
 </>}</div>;
}

export function ComparisonOptionsPanel({request,sending,onResume,onError}:{request:AgentRequestView;sending:boolean;onResume:(input:Snapshot)=>Promise<void>;onError:(error:unknown)=>void}){
 const pending=request.pendingInput!;const [baseline,setBaseline]=useState('');const [axis,setAxis]=useState('');
 useEffect(()=>{setBaseline('');setAxis('');},[pending.id]);
 const valid=(!pending.fields?.includes('baselineKey')||!!baseline)&&(!pending.fields?.includes('trendAxis')||!!axis);
 return <form onSubmit={e=>{e.preventDefault();onResume({type:'comparison_options',...(pending.fields?.includes('baselineKey')?{baselineKey:baseline}:{}),...(pending.fields?.includes('trendAxis')?{trendAxis:axis}:{})}).catch(onError);}}><p>{pending.message}</p>{pending.fields?.includes('baselineKey')&&<label>기준 실험<select value={baseline} onChange={e=>setBaseline(e.target.value)} required disabled={sending}><option value="">선택해 주세요</option>{pending.allowedRunKeys?.map(key=><option key={key}>{key}</option>)}</select></label>}{pending.fields?.includes('trendAxis')&&<label>경향을 볼 조건<select value={axis} onChange={e=>setAxis(e.target.value)} required disabled={sending}><option value="">선택해 주세요</option>{pending.allowedTrendAxes?.map(key=><option key={key} value={key}>{{pressure:'압력',sourcePower:'소스 전력',biasPower:'바이어스 전력'}[key]}</option>)}</select></label>}<button className="button button--primary button--small" disabled={sending||!valid}>선택하고 계속</button></form>;
}
