import {useEffect,useRef,useState} from 'react';
import type {BatchView} from 'agent';
import {fetchImportBatch,reprocess,uploadFolder,uploadZip,type UploadOptions,type UploadProgress} from '../../api/imports';
import {ApiClientError} from '../../api/client';
export const terminalBatch=(batch:BatchView)=>['SUCCESS','PARTIAL_SUCCESS','FAILED'].includes(batch.status);
export function describeImportError(error:unknown):string{if(error instanceof ApiClientError)return `${error.message} (${error.error.code}${error.error.requestId?`; ${error.error.requestId}`:''})`;return error instanceof Error?error.message:'등록 상태를 확인할 수 없습니다.';}
export function useImportBatch(onComplete:(signal:AbortSignal)=>Promise<void>){
 const [batch,setBatch]=useState<BatchView|null>(null),[progress,setProgress]=useState<UploadProgress|null>(null),[pending,setPending]=useState(false),[error,setError]=useState('');
 const running=useRef(false),mounted=useRef(false),controller=useRef<AbortController|null>(null),timer=useRef<ReturnType<typeof setTimeout>|null>(null),complete=useRef(onComplete);complete.current=onComplete;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;controller.current?.abort();if(timer.current!==null)clearTimeout(timer.current);};},[]);
 async function start(operation:(key:string,options:UploadOptions)=>Promise<BatchView>){
  if(running.current)return;running.current=true;setPending(true);setBatch(null);setError('');setProgress(null);
  const current=new AbortController();controller.current=current;
  const fail=(cause:unknown)=>{if(!mounted.current||current.signal.aborted)return;setError(describeImportError(cause));setPending(false);running.current=false;};
  const receive=async(value:BatchView)=>{
   if(!mounted.current||current.signal.aborted)return;setBatch(value);setProgress(null);
   if(terminalBatch(value)){try{await complete.current(current.signal);}catch(cause){fail(cause);return;}if(!mounted.current||current.signal.aborted)return;running.current=false;setPending(false);return;}
   timer.current=setTimeout(()=>{timer.current=null;fetchImportBatch(value.batchId,current.signal).then(receive).catch(fail);},1000);
  };
  try{await receive(await operation(crypto.randomUUID(),{signal:current.signal,onProgress:value=>{if(mounted.current&&!current.signal.aborted)setProgress(value);}}));}catch(cause){fail(cause);}
 }
 function forgetDeletedRuns(runIds:string[]){setBatch(current=>current&&terminalBatch(current)&&current.jobs.some(job=>job.runId&&runIds.includes(job.runId))?null:current);}
 return {batch,progress,pending,error,forgetDeletedRuns,uploadFolder:(files:File[])=>start((key,options)=>uploadFolder(files,key,options)),uploadZip:(file:File)=>start((key,options)=>uploadZip(file,key,options)),reprocess:(jobId:string)=>start((key,options)=>reprocess(jobId,key,options))};
}
