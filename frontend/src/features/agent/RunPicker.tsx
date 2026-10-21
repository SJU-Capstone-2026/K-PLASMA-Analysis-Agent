import {useEffect,useRef,useState} from 'react';
import type {AgentRequestView,RunOption,RunOptions,RunSelection,RunSelectionChange,Snapshot} from 'agent';
import {changeRunSelection,fetchRunOptions,fetchRunOptionCount,fetchRunSelection} from '../../api/agent';
import {numberText,reasons} from './agent-contract';

type Props={request:AgentRequestView;sending:boolean;onResume:(input:Snapshot)=>Promise<void>;onError:(error:unknown)=>void};
type Operation=Omit<RunSelectionChange,'pendingInputId'|'expectedRequestRevision'|'expectedSelectionRevision'>;
const message=(error:unknown)=>error instanceof Error?error.message:String(error);

/** The keyed parent resets this state only for a new request/pending revision. */
export function RunPicker({request,sending,onResume,onError}:Props){
 const pending=request.pendingInput!;
 const [page,setPage]=useState<RunOptions|null>(null),[selection,setSelection]=useState<RunSelection|null>(null);
 const current=useRef<RunSelection|null>(null),queue=useRef(Promise.resolve()),generation=useRef(0);
 const [draft,setDraft]=useState(''),[query,setQuery]=useState(''),[sort,setSort]=useState('ascending');
 const [cursors,setCursors]=useState<(string|null)[]>([null]),[selectedCursors,setSelectedCursors]=useState<(string|null)[]>([null]);
 const [loading,setLoading]=useState(true),[error,setError]=useState(''),[saveError,setSaveError]=useState(''),[saving,setSaving]=useState(0),[reload,setReload]=useState(0);
 const [matching,setMatching]=useState<number|null>(null),[expanded,setExpanded]=useState(false);
 const [optimistic,setOptimistic]=useState<Record<string,{value:boolean;option:RunOption;sequence:number}>>({});
 const sequence=useRef(0),countCache=useRef(new Map<string,number>());
 const failed=useRef<{body:RunSelectionChange;key:string}|null>(null),alive=useRef(true);
 const cursor=cursors.at(-1)??null,selectedCursor=selectedCursors.at(-1)??null;
 const snapshotReady=pending.optionsFormat===2||page!==null;
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;generation.current++;};},[]);
 useEffect(()=>{if(draft===query)return;const timer=setTimeout(()=>{setQuery(draft);setCursors([null]);},300);return()=>clearTimeout(timer);},[draft,query]);
 function accept(result:RunSelection){
  if(result.requestId!==request.requestId||result.pendingInputId!==pending.id||result.requestRevision!==request.requestRevision)throw new Error('실험 선택 요청이 변경되었습니다.');
  if(current.current&&result.selectionRevision<current.current.selectionRevision)return;
  current.current=result;setSelection(result);
 }
 useEffect(()=>{
  const controller=new AbortController();setLoading(true);setError('');
  fetchRunOptions(request.requestId,pending.id,{query,sort,cursor},controller.signal).then(result=>{
   if(controller.signal.aborted)return;
   if(result.requestId!==request.requestId||result.pendingInputId!==pending.id||result.requestRevision!==request.requestRevision)throw new Error('실험 선택 요청이 변경되었습니다.');
   if(current.current&&result.selectionRevision<current.current.selectionRevision){setReload(value=>value+1);return;}
   setPage(result);setLoading(false);
  }).catch(e=>{if(!controller.signal.aborted){setError(message(e));setLoading(false);}});
  return()=>controller.abort();
 },[request.requestId,request.requestRevision,pending.id,query,sort,cursor,reload]);
 useEffect(()=>{
  // An older pending request must finish its one-time snapshot conversion first.
  if(!snapshotReady)return;
  const controller=new AbortController();
  fetchRunSelection(request.requestId,pending.id,selectedCursor,controller.signal).then(result=>{if(!controller.signal.aborted)accept(result);}).catch(e=>{if(!controller.signal.aborted)setSaveError(message(e));});
  return()=>controller.abort();
 // accept reads only this keyed request's stable identifiers.
 },[request.requestId,pending.id,selectedCursor,reload,snapshotReady]);
 useEffect(()=>{
  if(!snapshotReady)return;
  const controller=new AbortController();
  if(countCache.current.has(query)){setMatching(countCache.current.get(query)!);return;}
  setMatching(null);fetchRunOptionCount(request.requestId,pending.id,query,controller.signal).then(result=>{
   if(controller.signal.aborted)return;
   if(countCache.current.size>=20)countCache.current.clear();countCache.current.set(query,result.matchingCount);setMatching(result.matchingCount);
  }).catch(()=>{});return()=>controller.abort();
 },[request.requestId,pending.id,query,snapshotReady]);

 function enqueue(operation:Operation,option?:RunOption,retry?:{body:RunSelectionChange;key:string}){
  if(!current.current)return;
  const serial=++sequence.current,epoch=generation.current;
  if(option)setOptimistic(values=>({...values,[option.key]:{value:operation.operation==='add',option,sequence:serial}}));
  setSaving(value=>value+1);setSaveError('');
  queue.current=queue.current.then(async()=>{
   if(!alive.current||epoch!==generation.current)return;
   const body=retry?.body??{...operation,pendingInputId:pending.id,expectedRequestRevision:request.requestRevision,expectedSelectionRevision:current.current!.selectionRevision};
   const key=retry?.key??crypto.randomUUID();
   try{
    const result=await changeRunSelection(request.requestId,body,key);
    if(!alive.current)return;accept(result);failed.current=null;setSelectedCursors([null]);
    if(option)setPage(previous=>previous?{...previous,options:previous.options.map(o=>o.key===option.key?{...o,selected:operation.operation==='add'}:o)}:previous);
    else setReload(value=>value+1);
   }catch(e){
    if(!alive.current)return;
    generation.current++;failed.current={body,key};setSaveError(message(e));setOptimistic({});setReload(value=>value+1);
   }finally{
    if(alive.current&&option)setOptimistic(values=>{if(values[option.key]?.sequence!==serial)return values[option.key]?{...values,[option.key]:{...values[option.key],option:{...values[option.key].option,selected:operation.operation==='add'}}}:values;const next={...values};delete next[option.key];return next;});
   }
  }).finally(()=>{if(alive.current)setSaving(value=>value-1);});
 }
 function checked(option:RunOption){return optimistic[option.key]?.value??!!option.selected;}
 function toggle(option:RunOption){enqueue({operation:checked(option)?'remove':'add',keys:[option.key]},option);}
 const chosen=new Map((selection?.options??[]).map(option=>[option.key,option]));
 for(const [key,change] of Object.entries(optimistic)){if(change.value)chosen.set(key,change.option);else chosen.delete(key);}
 const chosenRows=[...chosen.values()];
 const selectedCount=(selection?.selectedCount??0)+Object.values(optimistic).reduce((delta,change)=>delta+(change.value?1:0)-(change.option.selected?1:0),0);
 const baseline=selection?.baselineKey??'';
 const stale=draft!==query||loading||!!error;
 const valid=!!selection&&selectedCount>=(pending.minSelections??2)&&selection.unavailableCount===0&&(!pending.baselineRequired||!!baseline)&&!saving&&!saveError;
 const busy=sending||saving>0;
 return <div className="v1-run-selection">
  <p>{pending.message}</p>
  <div className="v1-picker-controls">
   <label>실험 검색<input type="search" value={draft} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){setQuery(draft);setCursors([null]);}}} placeholder="Run 이름·버전·조건 검색"/></label>
   <label>목록 정렬<select value={sort} onChange={e=>{setSort(e.target.value);setCursors([null]);}}><option value="ascending">이름 오름차순</option><option value="descending">이름 내림차순</option></select></label>
  </div>
  <div className="v1-card-actions">
   <button type="button" className="button button--ghost button--small" disabled={busy||stale||!selection||!page?.options.some(o=>o.selectable)} onClick={()=>enqueue({operation:'add',keys:page!.options.filter(o=>o.selectable).map(o=>o.key)})}>현재 페이지 선택</button>
   <button type="button" className="button button--ghost button--small" disabled={busy||stale||!selection||matching===0} onClick={()=>enqueue({operation:'search',query})}>검색 결과 전체 선택</button>
   <button type="button" className="button button--ghost button--small" disabled={busy||!selection} onClick={()=>enqueue({operation:'all'})}>전체 실험 선택</button>
   <button type="button" className="button button--ghost button--small" disabled={busy||!selectedCount} onClick={()=>enqueue({operation:'clear'})}>선택 해제</button>
   <span role="status">선택 {selectedCount}개 · 검색 {matching??'…'}개 / 전체 {page?.totalCount??'…'}개{saving>0?' · 저장 중':''}</span>
  </div>
  {saveError&&<div role="alert"><p>{saveError}</p><button className="button button--ghost button--small" disabled={busy} onClick={()=>failed.current?enqueue(failed.current.body,undefined,failed.current):setReload(v=>v+1)}>선택 저장 다시 시도</button></div>}
  <div className="v1-picker-chips" aria-label="선택한 실험">
   {(expanded?chosenRows:chosenRows.slice(0,6)).map(option=><button key={option.key} type="button" disabled={sending} onClick={()=>enqueue({operation:'remove',keys:[option.key]},{...option,selected:true})} aria-label={`${option.key} ${option.ref.runId} 선택 해제`}>{option.key} · {option.ref.runId}{!option.selectable?' (비가용)':''} ×</button>)}
  </div>
  {(selectedCount>6||expanded)&&<div className="v1-card-actions"><button className="button button--ghost button--small" onClick={()=>setExpanded(v=>!v)}>{expanded?'선택 목록 접기':'선택 목록 펼치기'}</button>{expanded&&<><button className="button button--ghost button--small" disabled={busy||selectedCursors.length<2} onClick={()=>setSelectedCursors(v=>v.slice(0,-1))}>선택 목록 이전</button><button className="button button--ghost button--small" disabled={busy||!selection?.hasMore} onClick={()=>setSelectedCursors(v=>[...v,selection!.nextCursor])}>선택 목록 다음</button></>}</div>}
  {error&&<div role="alert"><p>{error}</p><button className="button button--ghost button--small" onClick={()=>setReload(v=>v+1)}>목록 다시 불러오기</button></div>}
  {loading&&<p role="status">실험 목록을 불러오고 있습니다.</p>}
  <fieldset className="v1-picker-list" disabled={sending||stale||!selection} aria-busy={loading}><legend>비교할 실험 · 최소 {pending.minSelections??2}개</legend>
   {page?.options.map(option=><label key={option.key} className={`v1-picker-option${checked(option)?' is-selected':''}`}><input type="checkbox" aria-label={`${option.key} · ${option.ref.runId} · ${option.ref.runVersionId}`} checked={checked(option)} disabled={!option.selectable} onChange={()=>toggle(option)}/><span><strong>{option.key} · {option.ref.runId}</strong><small>버전 {option.ref.runVersionId}</small><small>{(['pressure','sourcePower','biasPower'] as const).map(field=>option.conditions[field]).map(v=>`${numberText(v.value)} ${v.unit}`).join(' · ')}</small>{!option.selectable&&<small>{reasons[option.unavailableReason??'']??'삭제되었거나 비교할 수 없는 실험입니다.'}</small>}</span></label>)}
   {!loading&&page?.options.length===0&&<p>검색에 맞는 실험이 없습니다. 기존 선택은 유지됩니다.</p>}
  </fieldset>
  <div className="v1-card-actions"><button className="button button--ghost button--small" disabled={stale||cursors.length<2} onClick={()=>setCursors(v=>v.slice(0,-1))}>이전 페이지</button><span>{cursors.length}페이지 · {page?.options.length??0}개 표시</span><button className="button button--ghost button--small" disabled={stale||!page?.hasMore} onClick={()=>setCursors(v=>[...v,page!.nextCursor])}>다음 페이지</button></div>
  <label className="v1-baseline">비교 기준 {pending.baselineRequired?'(필수)':'(선택)'}<select disabled={busy||!selection} value={baseline} onChange={e=>enqueue({operation:'baseline',baselineKey:e.target.value||null})}><option value="">기준 없이 값·절대 차이·범위 비교</option>{baseline&&!chosen.has(baseline)&&<option value={baseline}>{baseline} · 선택한 기준 실험</option>}{chosenRows.filter(o=>o.selectable).map(o=><option key={o.key} value={o.key}>{o.key} · {o.ref.runId}</option>)}</select></label>
  <p className="v1-limitation">화면을 처음 열었을 때의 실험 버전으로 비교합니다. 검색·페이지를 바꿔도 선택은 유지됩니다.</p>
  <button type="button" className="button button--primary" disabled={sending||!valid} onClick={()=>onResume({type:'run_selection',snapshotId:selection!.snapshotId,selectionRevision:selection!.selectionRevision}).catch(onError)}>선택한 실험으로 계속</button>
 </div>;
}
