import {useEffect,useRef,useState} from 'react';
import type {FullRun,RunRef,Pair,Iead,Density,SourceFile} from 'agent';
import {buildRunDetailModel} from '../../prototype/view-models';
import {analysisLineChart,renderIeAdHeatmap,renderDensityHeatmap} from '../../prototype/charts';
import {fetchRunVersion} from '../../api/runs';
import {ApiClientError} from '../../api/client';
import {Modal} from '../../components/Modal';
export interface RunDetailProps {runRef:RunRef;onReference?:(ref:RunRef)=>void;run?:FullRun;tab?:string;onTabChange?:(tab:string)=>void;turnId?:string}
export function RunDetailUnavailable({error,runId,onClose}:{error:unknown;runId:string;onClose?:()=>void}){
 const missing=error instanceof ApiClientError&&error.status===404;
 const title=missing?'삭제된 Run입니다':'상세 데이터를 불러오지 못했습니다';
 const message=missing?`${runId}은 데이터 관리에서 삭제되어 상세 결과를 볼 수 없습니다.`:'일시적인 오류가 발생했습니다. 상세 창을 닫았다가 다시 열어 주세요.';
 return <section className={`run-detail-unavailable ${missing?'is-missing':'is-error'}`} role="alert" aria-label={title}>
  <span className="run-detail-unavailable-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 12l6 6m0-6-6 6"/></svg></span>
  <span className="section-kicker">{missing?'RUN REMOVED':'DETAIL UNAVAILABLE'}</span>
  <h3>{title}</h3><p>{message}</p>
  {onClose&&<button className="button button--secondary" type="button" onClick={onClose}>창 닫기</button>}
 </section>;
}
export function RunDetail({runRef,run:provided,tab,onTabChange,turnId='modal'}:RunDetailProps){
 const [run,setRun]=useState<FullRun|null>(provided??null);const [error,setError]=useState<unknown>(null);const [requested,setRequested]=useState(tab??'');const sourceFiles=useRef<HTMLDetailsElement>(null);
 useEffect(()=>{if(provided){setRun(provided);setError(null);return;}const controller=new AbortController();setRun(null);setError(null);fetchRunVersion(runRef,controller.signal).then(value=>{if(!controller.signal.aborted)setRun(value);}).catch(e=>{if(!controller.signal.aborted)setError(e);});return()=>controller.abort();},[runRef.runVersionId,provided]);
 if(error)return <RunDetailUnavailable error={error} runId={runRef.runId}/>;
 if(!run)return <div className="agent-detail-empty">검증된 Run 데이터를 불러오는 중입니다.</div>;
 const detail=buildRunDetailModel(run)!;const available=detail.graphs.filter(graph=>graph.available);const active=available.find(graph=>graph.id===(tab??requested))??available[0]??detail.graphs[0];
 let graph=<div className="analysis-chart-empty">{active.reason||'표시할 실제 수치가 없습니다.'}</div>;
 if(active.available&&active.id==='iead')graph=renderIeAdHeatmap(active.series[0] as Iead);
 else if(active.available&&active.id==='density')graph=renderDensityHeatmap(active.series[0] as Density);
 else if(active.available)graph=analysisLineChart(active.series as Pair[],{xLabel:active.id==='iad'?'Angle (°)':active.id==='residual'?'Iteration':active.id==='ied'?'Energy (eV)':'RF phase',yLabel:active.id==='residual'?'Max residual':'Actual value',logY:active.id==='residual',ariaLabel:`${detail.runId} ${active.label} 실제 수치 그래프`});
 const panelId=`run-detail-graph-${turnId}-${run.runId}`;
 return <section className="agent-run-detail" aria-label={`${run.runId} 실험 상세`}><div className="agent-detail-summary"><div className="agent-condition-summary">{detail.conditions.map(item=><div key={item.label}><span>{item.label}</span><strong>{item.value}</strong><small>{item.unit}</small></div>)}</div><div className="agent-detail-metrics">{detail.metrics.map(item=><div key={item.label}><span>{item.label}</span><strong>{item.value} <small>{item.unit}</small></strong></div>)}</div></div>
 <div className="agent-detail-tabs" role="tablist" aria-label={`${run.runId} 실제 그래프`}>{detail.graphs.map(item=><button key={item.id} type="button" role="tab" aria-selected={item.id===active.id} aria-controls={panelId} className={item.id===active.id?'is-active':''} data-action="run-detail-tab" data-turn-id={turnId} data-run-id={run.runId} data-tab={item.id} disabled={!item.available} onClick={()=>{if(sourceFiles.current)sourceFiles.current.open=false;setRequested(item.id);onTabChange?.(item.id);}}>{item.label}</button>)}</div>
 <div id={panelId} className="agent-detail-graph" role="tabpanel">{graph}<p>원본 결과 파일의 저장 샘플만 표시합니다. 예측·보간 곡선이 아닙니다.</p></div><details key={active.id} ref={sourceFiles} className="agent-source-files"><summary>원본 파일 {detail.sourceFiles.length}개</summary><div>{detail.sourceFiles.map((file:SourceFile)=><p key={file.path}><strong>{file.name}</strong><span>{file.path}</span><small>{file.size||''}</small></p>)}</div></details></section>;
}
export function RunDetailDialog({runRef,onClose}:{runRef:RunRef;onClose:()=>void}){
 const referenceKey=JSON.stringify([runRef.runId,runRef.runVersionId]);
 const [result,setResult]=useState<{referenceKey:string;run:FullRun|null;error:unknown;tab:string}>({referenceKey,run:null,error:null,tab:''});
 const current=result.referenceKey===referenceKey;const run=current?result.run:null;const error=current?result.error:null;const tab=current?result.tab:'';
 useEffect(()=>{const controller=new AbortController();setResult({referenceKey,run:null,error:null,tab:''});fetchRunVersion(runRef,controller.signal).then(value=>{if(!controller.signal.aborted)setResult({referenceKey,run:value,error:null,tab:''});}).catch(e=>{if(!controller.signal.aborted)setResult({referenceKey,run:null,error:e,tab:''});});return()=>controller.abort();},[referenceKey]);
 const setTab=(tab:string)=>setResult(value=>value.referenceKey===referenceKey?{...value,tab}:value);
 const detail=run?buildRunDetailModel(run):null;
 return <Modal titleId="run-detail-title" className="decision-modal run-detail-modal" onClose={onClose} focusKey={`${referenceKey}:${tab}`}><header className="modal-header"><div><span className="section-kicker">ACTUAL RUN DETAIL</span><div className="run-detail-title-row"><h2 id="run-detail-title">{runRef.runId} 실험 상세</h2>{detail&&<div className="run-detail-statuses" aria-label="검증 상태"><span className="badge badge--success">{detail.quality.qualityLabel}</span><span className="badge badge--success">{detail.quality.convergenceLabel}</span></div>}</div><p>저장된 원본 출력과 검증 상태만 표시합니다.</p></div><button className="icon-button modal-close" type="button" data-action="close-modal" aria-label={`${runRef.runId} 실험 상세 닫기`} onClick={onClose}>×</button></header><div className="run-detail-modal-body">{error?<RunDetailUnavailable error={error} runId={runRef.runId} onClose={onClose}/>:run?<RunDetail runRef={runRef} run={run} tab={tab} onTabChange={setTab}/>:<div className="agent-detail-empty">검증된 Run 데이터를 불러오는 중입니다.</div>}</div></Modal>;
}
