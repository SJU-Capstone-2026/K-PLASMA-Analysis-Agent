import {useEffect,useState} from 'react';
import type {AgentRequestView,AgentResultProjection,Snapshot} from 'agent';
import {RunComparisonCard} from './RunComparisonCard';
import type {ComparisonResult} from './agent-contract';
import type {ComparisonResultV2} from 'agent';
import {RunSelectionPanel,ComparisonOptionsPanel} from './RunSelectionPanel';
import {AgentProgress,CompletedAgentProgress} from './AgentProgress';
import {StreamPreview} from './StreamPreview';
const statusTitles:Partial<Record<AgentRequestView['status'],string>>={NEEDS_INPUT:'추가 정보가 필요합니다',FAILED:'분석을 완료하지 못했습니다',CANCELLED:'분석이 취소되었습니다'};
export function PendingRequest({request,sending,onResume,onCancel,onError,hideQuestion=false,resultPreview}: {
 hideQuestion?:boolean;resultPreview?:AgentResultProjection|null;request:AgentRequestView;sending:boolean;onResume:(input:Snapshot)=>Promise<void>;
 onCancel:()=>Promise<void>;onError:(error:unknown)=>void;
}){
 const [reply,setReply]=useState('');
 useEffect(()=>setReply(''),[request.requestId,request.pendingInput?.id]);
 const running=request.status==='RUNNING'||request.status==='QUEUED';
 const pending=request.status==='NEEDS_INPUT'?request.pendingInput:null;
 const selectingRuns=pending?.type==='run_selection';
 const selectingOptions=pending?.type==='comparison_options';
 const partial=request.partialResult as unknown as ComparisonResult|ComparisonResultV2|null;
 const panelStyle=running?'v1-pending--running':selectingRuns?'v1-pending--run-selection':selectingOptions?'v1-pending--comparison-options':'panel';
 const pickerProps={request,sending,onResume,onError,onCancel};

 return <section className={`v1-pending ${panelStyle}`} aria-label="진행 중인 분석 요청">
  {!running&&!selectingRuns&&!selectingOptions&&<h3>{statusTitles[request.status]??'분석 중'}</h3>}
  {!hideQuestion&&<p>{request.question}</p>}
  {request.inputEvents?.map((event,index)=>{
   const input=event.input as Snapshot|undefined;
   return typeof input?.text==='string'?<p key={index} className="v1-user-input">추가 입력: {input.text}</p>:null;
  })}
  {running&&<>
   <AgentProgress progress={request.progress} stage={request.stage} queued={request.status==='QUEUED'}/>
   <StreamPreview request={request} resultPreview={resultPreview}/>
  </>}
  {(request.status==='FAILED'||request.status==='CANCELLED')&&<CompletedAgentProgress summary={request.executionSummary} status={request.status}/>}
  {pending&&(selectingRuns?<RunSelectionPanel {...pickerProps}/>:selectingOptions?<ComparisonOptionsPanel {...pickerProps}/>:<form onSubmit={event=>{
   event.preventDefault();
   onResume({text:reply}).then(()=>setReply('')).catch(onError);
  }}>
   <label htmlFor={`reply-${request.requestId}`}>{pending.message}</label>
   <textarea id={`reply-${request.requestId}`} rows={2} value={reply} onChange={event=>setReply(event.target.value)} required placeholder="필요한 조건이나 Run을 알려 주세요"/>
   <div className="v1-card-actions">
    <button className="button button--primary button--small" disabled={sending||!reply.trim()}>답변하고 계속</button>
    {pending.options?.map((option,index)=><button key={index} type="button" className="button button--ghost button--small" disabled={sending}
     onClick={()=>onResume(option.input).then(()=>setReply('')).catch(onError)}>{option.label}</button>)}
   </div>
  </form>)}
  {request.status==='FAILED'&&<>
   <p role="alert">{request.error?.message??'요청이 실패했습니다.'}</p>
   {request.error?.code&&<small>오류 코드: {request.error.code}</small>}
   {!resultPreview?.results.length&&partial?.kind==='compare_runs'&&<div className="v1-partial-result">
    <h4>비교 완료 / 설명 실패</h4><p>검증된 비교 결과만 표시합니다. 설명은 완료되지 않았습니다.</p><RunComparisonCard result={partial}/>
   </div>}
  </>}
  {(request.status==='FAILED'||request.status==='CANCELLED')&&<StreamPreview request={request} resultPreview={resultPreview}/>}
  {pending&&!selectingRuns&&!selectingOptions&&<button type="button" className="button button--ghost button--small" disabled={sending} onClick={()=>onCancel().catch(onError)}>분석 취소</button>}
 </section>;
}
