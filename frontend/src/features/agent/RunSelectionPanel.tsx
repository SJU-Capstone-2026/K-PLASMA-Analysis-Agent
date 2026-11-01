import {useEffect,useState} from 'react';
import type {AgentRequestView,Snapshot} from 'agent';
import {RunPicker} from './RunPicker';
export function RunSelectionPanel(props:{request:AgentRequestView;sending:boolean;onResume:(input:Snapshot)=>Promise<void>;onError:(error:unknown)=>void}){
 return <RunPicker key={`${props.request.requestId}:${props.request.requestRevision}:${props.request.pendingInput!.id}`} {...props}/>;
}

export function ComparisonOptionsPanel({request,sending,onResume,onError}:{request:AgentRequestView;sending:boolean;onResume:(input:Snapshot)=>Promise<void>;onError:(error:unknown)=>void}){
 const pending=request.pendingInput!;const [baseline,setBaseline]=useState('');const [axis,setAxis]=useState('');
 useEffect(()=>{setBaseline('');setAxis('');},[pending.id]);
 const valid=(!pending.fields?.includes('baselineKey')||!!baseline)&&(!pending.fields?.includes('trendAxis')||!!axis);
 return <form onSubmit={e=>{e.preventDefault();onResume({type:'comparison_options',...(pending.fields?.includes('baselineKey')?{baselineKey:baseline}:{}),...(pending.fields?.includes('trendAxis')?{trendAxis:axis}:{})}).catch(onError);}}><p>{pending.message}</p>{pending.fields?.includes('baselineKey')&&<label>기준 실험<select value={baseline} onChange={e=>setBaseline(e.target.value)} required disabled={sending}><option value="">선택해 주세요</option>{pending.allowedRunKeys?.map(key=><option key={key}>{key}</option>)}</select></label>}{pending.fields?.includes('trendAxis')&&<label>경향을 볼 조건<select value={axis} onChange={e=>setAxis(e.target.value)} required disabled={sending}><option value="">선택해 주세요</option>{pending.allowedTrendAxes?.map(key=><option key={key} value={key}>{{pressure:'압력',sourcePower:'소스 전력',biasPower:'바이어스 전력'}[key]}</option>)}</select></label>}<button className="button button--primary button--small" disabled={sending||!valid}>선택하고 계속</button></form>;
}
