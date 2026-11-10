import type {AgentActivity,AgentProgressSnapshot,AgentPublicEvent,AgentRequestView,AgentStreamAnswer} from 'agent';

export function applyProgressEvent(request:AgentRequestView,event:AgentPublicEvent):AgentRequestView{
 if(event.schemaVersion!==1||event.requestId!==request.requestId||
  request.workspaceEpoch!==undefined&&event.workspaceEpoch!==request.workspaceEpoch||
  request.conversationEpoch!==undefined&&event.conversationEpoch!==request.conversationEpoch||
  event.requestRevision<request.requestRevision||
  event.requestRevision>request.requestRevision&&event.type!=='request.state')return request;
 const previous=request.progress??{lastEventSeq:0,activities:[],answer:null,resultRevision:null};
 if(!Number.isSafeInteger(event.seq)||event.seq<=previous.lastEventSeq)return request;
 const progress:AgentProgressSnapshot={...previous,lastEventSeq:event.seq};
 const payload=event.payload;
 if(event.requestRevision>request.requestRevision)progress.answer=null;
 if(event.type==='activity'&&typeof payload.activityId==='string'&&typeof payload.code==='string'&&
  ['started','completed','reused'].includes(String(payload.phase))){
  const activity={...payload,seq:event.seq,occurredAt:event.occurredAt} as unknown as AgentActivity;
  progress.activities=[...progress.activities,activity];
  if(progress.answer&&payload.phase==='started'){
   const status=payload.code==='REVIEW'?'reviewing':payload.code==='REWRITE'?'rewriting':undefined;
   if(status)progress.answer={...progress.answer,status};
  }
 }else if(event.type==='answer.start'&&typeof payload.streamId==='string'&&
  Number.isSafeInteger(payload.answerRevision)&&Number(payload.answerRevision)>(progress.answer?.answerRevision??0)&&
  (payload.mode==='general'||payload.mode==='interpretation')){
  progress.answer={streamId:payload.streamId,answerRevision:Number(payload.answerRevision),mode:payload.mode,
   status:payload.rewrite?'rewriting':'writing',blocks:[]};
 }else if(event.type==='answer.delta'&&progress.answer&&payload.streamId===progress.answer.streamId&&
  payload.answerRevision===progress.answer.answerRevision&&typeof payload.blockId==='string'&&typeof payload.text==='string'){
  const block=progress.answer.blocks.find(block=>block.id===payload.blockId);
  const next={id:payload.blockId,text:(block?.text??'')+payload.text};
  progress.answer={...progress.answer,blocks:block?progress.answer.blocks.map(block=>block.id===next.id?next:block):[...progress.answer.blocks,next]};
 }else if(event.type==='answer.reset'&&progress.answer&&payload.streamId===progress.answer.streamId&&
  payload.answerRevision===progress.answer.answerRevision){
  progress.answer={...progress.answer,blocks:[],status:'interrupted'};
 }else if(event.type==='results.ready')progress.resultRevision=event.seq;
 return {...request,requestRevision:event.requestRevision,progress};
}

export function mergeRequestSnapshot(current:AgentRequestView|null,next:AgentRequestView):AgentRequestView{
 if(current?.requestId===next.requestId&&current.requestRevision===next.requestRevision&&
  (current.progress?.lastEventSeq??0)>(next.progress?.lastEventSeq??0))return {...next,progress:current.progress};
 return next;
}

export function answerTextSize(answer?:AgentStreamAnswer|null){
 return answer?.blocks.reduce((total,block)=>total+block.text.length,0)??0;
}
