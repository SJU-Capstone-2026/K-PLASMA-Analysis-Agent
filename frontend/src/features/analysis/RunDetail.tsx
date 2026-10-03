import {useEffect,useState} from 'react';
import type {FullRun,RunRef,Pair,Iead,Density,SourceFile} from 'agent';
import {buildRunDetailModel} from '../../prototype/view-models';
import {analysisLineChart,renderIeAdHeatmap,renderDensityHeatmap} from '../../prototype/charts';
import {fetchRunVersion} from '../../api/runs';
import {Modal} from '../../components/Modal';
export interface RunDetailProps {runRef:RunRef;onReference?:(ref:RunRef)=>void;run?:FullRun;tab?:string;onTabChange?:(tab:string)=>void;turnId?:string}
export function RunDetail({runRef,run:provided,tab,onTabChange,turnId='modal'}:RunDetailProps){
 const [run,setRun]=useState<FullRun|null>(provided??null);const [error,setError]=useState('');const [requested,setRequested]=useState(tab??'');
 useEffect(()=>{if(provided){setRun(provided);return;}const controller=new AbortController();setRun(null);setError('');fetchRunVersion(runRef,controller.signal).then(value=>{if(!controller.signal.aborted)setRun(value);}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[runRef.runVersionId,provided]);
 if(error)return <div className="agent-detail-empty" role="alert">{error}</div>;
 if(!run)return <div className="agent-detail-empty">검증된 Run 데이터를 불러오는 중입니다.</div>;
 const detail=buildRunDetailModel(run)!;const available=detail.graphs.filter(graph=>graph.available);const active=available.find(graph=>graph.id===(tab??requested))??available[0]??detail.graphs[0];
 let graph=<div className="analysis-chart-empty">{active.reason||'표시할 실제 수치가 없습니다.'}</div>;
 if(active.available&&active.id==='iead')graph=renderIeAdHeatmap(active.series[0] as Iead);
 else if(active.available&&active.id==='density')graph=renderDensityHeatmap(active.series[0] as Density);
 else if(active.available)graph=analysisLineChart(active.series as Pair[],{xLabel:active.id==='iad'?'Angle (°)':active.id==='residual'?'Iteration':active.id==='ied'?'Energy (eV)':'RF phase',yLabel:active.id==='residual'?'Max residual':'Actual value',logY:active.id==='residual',ariaLabel:`${detail.runId} ${active.label} 실제 수치 그래프`});
 const panelId=`run-detail-graph-${turnId}-${run.runId}`;
 return <section className="agent-run-detail" aria-label={`${run.runId} 실험 상세`}><div className="agent-detail-summary"><div className="agent-condition-summary">{detail.conditions.map(item=><div key={item.label}><span>{item.label}</span><strong>{item.value}</strong><small>{item.unit}</small></div>)}</div><div className="agent-detail-metrics">{detail.metrics.map(item=><div key={item.label}><span>{item.label}</span><strong>{item.value} <small>{item.unit}</small></strong></div>)}</div></div>
 <div className="agent-detail-tabs" role="tablist" aria-label={`${run.runId} 실제 그래프`}>{detail.graphs.map(item=><button key={item.id} type="button" role="tab" aria-selected={item.id===active.id} aria-controls={panelId} className={item.id===active.id?'is-active':''} data-action="run-detail-tab" data-turn-id={turnId} data-run-id={run.runId} data-tab={item.id} disabled={!item.available} onClick={()=>{setRequested(item.id);onTabChange?.(item.id);}}>{item.label}</button>)}</div>
 <div id={panelId} className="agent-detail-graph" role="tabpanel">{graph}<p>원본 결과 파일의 저장 샘플만 표시합니다. 예측·보간 곡선이 아닙니다.</p></div><details className="agent-source-files"><summary>원본 파일 {detail.sourceFiles.length}개</summary><div>{detail.sourceFiles.map((file:SourceFile)=><p key={file.path}><strong>{file.name}</strong><span>{file.path}</span><small>{file.size||''}</small></p>)}</div></details></section>;
}
export function RunDetailDialog({runRef,onClose}:{runRef:RunRef;onClose:()=>void}){
 const referenceKey=JSON.stringify([runRef.runId,runRef.runVersionId]);
 const [result,setResult]=useState<{referenceKey:string;run:FullRun|null;error:string;tab:string}>({referenceKey,run:null,error:'',tab:''});
 const current=result.referenceKey===referenceKey;const run=current?result.run:null;const error=current?result.error:'';const tab=current?result.tab:'';
 useEffect(()=>{const controller=new AbortController();setResult({referenceKey,run:null,error:'',tab:''});fetchRunVersion(runRef,controller.signal).then(value=>{if(!controller.signal.aborted)setResult({referenceKey,run:value,error:'',tab:''});}).catch(e=>{if(!controller.signal.aborted)setResult({referenceKey,run:null,error:e.message,tab:''});});return()=>controller.abort();},[referenceKey]);
 const setTab=(tab:string)=>setResult(value=>value.referenceKey===referenceKey?{...value,tab}:value);
 const detail=run?buildRunDetailModel(run):null;
 return <Modal titleId="run-detail-title" className="decision-modal run-detail-modal" onClose={onClose} focusKey={`${referenceKey}:${tab}`}><header className="modal-header"><div><span className="section-kicker">ACTUAL RUN DETAIL</span><div className="run-detail-title-row"><h2 id="run-detail-title">{runRef.runId} 실험 상세</h2>{detail&&<div className="run-detail-statuses" aria-label="검증 상태"><span className="badge badge--success">{detail.quality.qualityLabel}</span><span className="badge badge--success">{detail.quality.convergenceLabel}</span></div>}</div><p>저장된 원본 출력과 검증 상태만 표시합니다.</p></div><button className="icon-button modal-close" type="button" data-action="close-modal" aria-label={`${runRef.runId} 실험 상세 닫기`} onClick={onClose}>×</button></header><div className="run-detail-modal-body">{error?<div role="alert" className="agent-detail-empty">{error}</div>:run?<RunDetail runRef={runRef} run={run} tab={tab} onTabChange={setTab}/>:<div className="agent-detail-empty">검증된 Run 데이터를 불러오는 중입니다.</div>}</div></Modal>;
}
