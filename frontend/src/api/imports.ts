import type {ApiError, BatchView, CatalogView, ManifestFile, UploadManifest} from 'agent';
import {ApiClientError, request} from './client';

export interface UploadProgress {loaded:number;total:number|null}
export interface UploadOptions {signal?:AbortSignal;onProgress?:(progress:UploadProgress)=>void}
export interface CatalogFilters {search:string;status:string;quality:string}
// Source metadata is deliberately separate from graph-bearing FullRun payloads.
export type CatalogData=CatalogView;
export function fetchCatalog(filters:CatalogFilters={search:'',status:'',quality:''},signal?:AbortSignal):Promise<CatalogData>{
 const params=new URLSearchParams();for(const [key,value] of Object.entries(filters))if(value)params.set(key,value);
 return request(`/api/catalog${params.size?`?${params}`:''}`,{signal});
}
export function fetchImportBatch(batchId:string,signal?:AbortSignal):Promise<BatchView>{return request(`/api/import-batches/${encodeURIComponent(batchId)}`,{signal});}
export function fetchJobFiles(jobId:string,signal?:AbortSignal):Promise<ManifestFile[]>{return request(`/api/import-jobs/${encodeURIComponent(jobId)}/files`,{signal});}
export function reprocess(jobId:string,key:string,options:UploadOptions={}):Promise<BatchView>{return request(`/api/import-jobs/${encodeURIComponent(jobId)}/reprocess`,{method:'POST',headers:{'Idempotency-Key':key},signal:options.signal});}
function sendUpload(manifest:UploadManifest,files:{partName:string;file:File}[],key:string,options:UploadOptions):Promise<BatchView>{
 const body=new FormData();body.append('manifest',new Blob([JSON.stringify(manifest)],{type:'application/json'}),'manifest.json');for(const {partName,file} of files)body.append(partName,file,file.name);
 return new Promise((resolve,reject)=>{
  if(options.signal?.aborted){reject(new DOMException('Upload aborted','AbortError'));return;}
  const xhr=new XMLHttpRequest();const abort=()=>xhr.abort();const cleanup=()=>options.signal?.removeEventListener('abort',abort);
  xhr.open('POST','/api/import-batches');xhr.setRequestHeader('Accept','application/json');xhr.setRequestHeader('Idempotency-Key',key);
  xhr.upload.onprogress=event=>options.onProgress?.({loaded:event.loaded,total:event.lengthComputable?event.total:null});
  xhr.onload=()=>{cleanup();let value:BatchView|ApiError;try{value=JSON.parse(xhr.responseText);}catch{reject(new ApiClientError(xhr.status,{code:'INVALID_RESPONSE',message:'서버 응답을 읽을 수 없습니다.',requestId:''}));return;}
   if(xhr.status>=200&&xhr.status<300)resolve(value as BatchView);else reject(new ApiClientError(xhr.status,value as ApiError));};
  xhr.onerror=()=>{cleanup();reject(new ApiClientError(0,{code:'NETWORK_ERROR',message:'서버 연결이 중단되었습니다. 등록 상태를 확인한 뒤 다시 시도하세요.',requestId:''}));};
  xhr.onabort=()=>{cleanup();reject(new DOMException('Upload aborted','AbortError'));};options.signal?.addEventListener('abort',abort,{once:true});xhr.send(body);
 });
}
export function uploadFolder(files:File[],key:string,options:UploadOptions={}):Promise<BatchView>{
 if(!files.length||files.some(file=>!file.webkitRelativePath))return Promise.reject(new Error('상대경로가 있는 폴더 파일을 선택하세요.'));
 const parts=files.map((file,index)=>({partName:`file-${index}`,file}));return sendUpload({mode:'FOLDER',entries:parts.map(({partName,file})=>({partName,relativePath:file.webkitRelativePath}))},parts,key,options);
}
export function uploadZip(file:File,key:string,options:UploadOptions={}):Promise<BatchView>{return sendUpload({mode:'ZIP',entries:[{partName:'archive',relativePath:file.name}]},[{partName:'archive',file}],key,options);}
