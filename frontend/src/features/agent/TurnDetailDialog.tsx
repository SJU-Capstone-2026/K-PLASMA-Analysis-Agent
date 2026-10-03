import {useEffect,useState} from 'react';
import {viewModels,type FullRun,type RunRef} from 'agent';
import {Modal} from '../../components/Modal';
import {RunDetail} from '../analysis/RunDetail';
import {fetchRunVersion} from '../../api/runs';
export function TurnDetailDialog({runRef,turnId,tab,onTabChange,onClose}:{runRef:RunRef;turnId:string;tab?:string;onTabChange:(tab:string)=>void;onClose:()=>void}){
 const key=JSON.stringify([turnId,runRef.runId,runRef.runVersionId]);
 const [result,setResult]=useState<{key:string;run:FullRun|null;error:string}>({key,run:null,error:''});const current=result.key===key;const run=current?result.run:null;const error=current?result.error:'';
 useEffect(()=>{const controller=new AbortController();fetchRunVersion(runRef,controller.signal).then(run=>{if(!controller.signal.aborted)setResult({key,run,error:''});}).catch(error=>{if(!controller.signal.aborted)setResult({key,run:null,error:error.message});});return()=>controller.abort();},[key]);
 const detail=run?viewModels.buildRunDetailModel(run):null;
 return <Modal titleId="run-detail-title" className="decision-modal run-detail-modal" onClose={onClose} focusKey={`${key}:${tab??''}`}><header className="modal-header"><div><span className="section-kicker">ACTUAL RUN DETAIL</span><div className="run-detail-title-row"><h2 id="run-detail-title">{runRef.runId} 실험 상세</h2>{detail&&<div className="run-detail-statuses" aria-label="검증 상태"><span className="badge badge--success">{detail.quality.qualityLabel}</span><span className="badge badge--success">{detail.quality.convergenceLabel}</span></div>}</div><p>저장된 원본 출력과 검증 상태만 표시합니다.</p></div><button className="icon-button modal-close" type="button" aria-label={`${runRef.runId} 실험 상세 닫기`} onClick={onClose}>×</button></header><div className="run-detail-modal-body">{error?<div className="agent-detail-empty" role="alert">{error}</div>:run?<RunDetail runRef={runRef} run={run} turnId={turnId} tab={tab} onTabChange={onTabChange}/>:<div className="agent-detail-empty">검증된 Run 데이터를 불러오는 중입니다.</div>}</div></Modal>;
}
