import {useEffect,useRef,useState} from 'react';
import type {FullRun,JobView,ManifestFile,RunRef,RunSummary,SourceFile} from 'agent';
import type {ShellContext} from '../../App';
import {fetchCatalog,fetchJobFiles,type CatalogData,type CatalogFilters} from '../../api/imports';
import {deleteRuns,fetchRuns,fetchRunVersion} from '../../api/runs';
import {Modal} from '../../components/Modal';
import {viewModels} from '../../prototype/view-models';
import {UploadControls,jobLabels} from './UploadControls';
import {describeImportError,useImportBatch} from './useImportBatch';

export interface CatalogState {catalogFilters:CatalogFilters;catalogSelectedRunId:string;catalogSelectedJobId:string}
export const initialCatalogState:CatalogState={catalogFilters:{search:'',status:'',quality:''},catalogSelectedRunId:'',catalogSelectedJobId:''};
export interface CatalogPageProps {state?:CatalogState;onStateChange?:(state:CatalogState)=>void;context?:ShellContext;onReference?:(ref:RunRef)=>void;onDecision?:(ref:RunRef)=>void;onDeleted?:(runIds:string[])=>void|Promise<void>}
type DisplayRun=RunSummary & {sourceFiles:SourceFile[]};
interface CatalogRow {runId:string;conditions:{label:string;value:string;unit:string}[];metrics:{label:string;value:string;unit:string}[];parsingStatus:string;parsingLabel:string;qualityStatus:string;qualityLabel:string;sourceFileCount:number;convergenceLabel:string;registeredAt:string;note:string;sourceRun:DisplayRun}
function displayRuns(catalog:CatalogData):DisplayRun[]{return catalog.runs.map(run=>{const files=catalog.sourceFilesByVersion?.[run.runVersionId];if(!Array.isArray(files))throw new Error('Run 원본 파일 메타데이터를 확인할 수 없습니다.');return {...run,sourceFiles:files};});}
function tone(status:string){return status==='READY'||status==='VERIFIED'?'badge--success':['PARSE_FAILED','INTERRUPTED','REJECTED'].includes(status)?'badge--danger':'badge--warning';}
export function CatalogPage({state:external,onStateChange,onReference,onDeleted}:CatalogPageProps){
 const [local,setLocal]=useState(initialCatalogState);const state=external??local;
 const update=(patch:Partial<CatalogState>)=>{const next={...state,...patch};if(onStateChange)onStateChange(next);else setLocal(next);};
 const [draft,setDraft]=useState(state.catalogFilters),[catalog,setCatalog]=useState<CatalogData|null>(null),[runs,setRuns]=useState<DisplayRun[]>([]),[error,setError]=useState(''),[full,setFull]=useState<FullRun|null>(null),[files,setFiles]=useState<ManifestFile[]|null>(null),[fullError,setFullError]=useState(''),[fileError,setFileError]=useState<{jobId:string;message:string}|null>(null);
 const [deletion,setDeletion]=useState<{runIds:string[];all:boolean}|null>(null),[deleting,setDeleting]=useState(false),[deleteError,setDeleteError]=useState(''),[deleteNotice,setDeleteNotice]=useState(''),[refreshError,setRefreshError]=useState('');
 const deletionRunning=useRef(false),deletionController=useRef<AbortController|null>(null);
 useEffect(()=>()=>deletionController.current?.abort(),[]);
 const loadSequence=useRef(0);
 async function load(signal:AbortSignal){const sequence=++loadSequence.current;try{const value=await fetchCatalog(undefined,signal);const next=displayRuns(value);if(!signal.aborted&&sequence===loadSequence.current){setCatalog(value);setRuns(next);setError('');}}catch(cause){if(!signal.aborted&&sequence===loadSequence.current)throw cause;}}
 useEffect(()=>{const controller=new AbortController();load(controller.signal).catch(cause=>{if(!controller.signal.aborted)setError(describeImportError(cause));});return()=>controller.abort();},[]);
 const imports=useImportBatch(async signal=>{await Promise.all([fetchRuns(signal),load(signal)]);});
 const observing=catalog?.jobs.some(job=>job.status==='QUEUED'||job.status==='PROCESSING')??false;
 const importActive=imports.pending||observing;
 const deleteDisabled=deleting||importActive;
 useEffect(()=>{
  if(!observing||imports.pending)return;
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>|null=null;
  const poll=async()=>{
   timer=null;
   try{await load(controller.signal);}catch(cause){if(!controller.signal.aborted)setError(describeImportError(cause));}
   if(!controller.signal.aborted)timer=setTimeout(poll,1000);
  };
  timer=setTimeout(poll,1000);
  return()=>{controller.abort();if(timer!==null)clearTimeout(timer);};
 },[observing,imports.pending]);
 const rows=viewModels.buildCatalogRows(runs,state.catalogFilters) as CatalogRow[];
 const selected=runs.find(run=>run.runId===state.catalogSelectedRunId);const selectedRow=selected?(viewModels.buildCatalogRows([selected],{}) as CatalogRow[])[0]:null;
 const jobs=catalog?.jobs??[];const explicitJob=jobs.find(job=>job.jobId===state.catalogSelectedJobId);
 // A retained Run ID follows the latest version; never pair it with an older upload inventory.
 const selectedJob=(explicitJob&&(!selected||explicitJob.status!=='READY'||explicitJob.runVersionId===selected.runVersionId)?explicitJob:undefined)??(selected?jobs.find(job=>job.runVersionId===selected.runVersionId&&job.status==='READY'):undefined)??null;
 useEffect(()=>{setFull(null);setFullError('');if(!selected)return;const controller=new AbortController();fetchRunVersion(selected,controller.signal).then(value=>{if(!controller.signal.aborted)setFull(value);}).catch(cause=>{if(!controller.signal.aborted)setFullError(describeImportError(cause));});return()=>controller.abort();},[selected?.runVersionId]);
 useEffect(()=>{setFiles(null);setFileError(null);if(!selectedJob)return;const controller=new AbortController();fetchJobFiles(selectedJob.jobId,controller.signal).then(value=>{if(!controller.signal.aborted){setFiles(value);setFileError(null);}}).catch(cause=>{if(!controller.signal.aborted)setFileError({jobId:selectedJob.jobId,message:describeImportError(cause)});});return()=>controller.abort();},[selectedJob?.jobId]);
 const ref=selected?{runId:selected.runId,runVersionId:selected.runVersionId}:null;
 function requestDeletion(runIds:string[],all:boolean){if(deleteDisabled||!runIds.length)return;setDeleteError('');setDeletion({runIds,all});}
 function closeDeletion(){if(!deletionRunning.current)setDeletion(null);}
 async function confirmDeletion(){
  if(!deletion||deletionRunning.current||importActive)return;
  deletionRunning.current=true;setDeleting(true);setDeleteError('');setDeleteNotice('');setRefreshError('');
  const controller=new AbortController();deletionController.current=controller;
  const runIds=deletion.runIds;
  try{
   const result=await deleteRuns({runIds},controller.signal);
   if(controller.signal.aborted)return;
   // Once the mutation commits, stale reads must not restore deleted rows or jobs.
   ++loadSequence.current;
   const removed=new Set(runIds);
   setCatalog(current=>current?{...current,runs:current.runs.filter(run=>!removed.has(run.runId)),jobs:current.jobs.filter(job=>!job.runId||!removed.has(job.runId)),sourceFilesByVersion:Object.fromEntries(current.runs.filter(run=>!removed.has(run.runId)).map(run=>[run.runVersionId,current.sourceFilesByVersion[run.runVersionId]]))}:current);
   setRuns(current=>current.filter(run=>!removed.has(run.runId)));
   const selectedRemoved=removed.has(state.catalogSelectedRunId),jobRemoved=jobs.some(job=>job.jobId===state.catalogSelectedJobId&&job.runId&&removed.has(job.runId));
   if(selectedRemoved||jobRemoved){update({catalogSelectedRunId:selectedRemoved?'':state.catalogSelectedRunId,catalogSelectedJobId:jobRemoved?'':state.catalogSelectedJobId});setFull(null);setFullError('');setFiles(null);setFileError(null);}
   imports.forgetDeletedRuns(runIds);setDeletion(null);
   setDeleteNotice(result.cleanupPending?`등록 Run ${result.deletedRunIds.length}개의 DB 삭제가 완료되었습니다. 관리 원본 파일 정리는 서버 재시작 시 재시도합니다.`:`등록 Run ${result.deletedRunIds.length}개를 삭제했습니다.`);
   const refreshed=await Promise.allSettled([Promise.resolve(onDeleted?.(runIds)),fetchRuns(controller.signal),load(controller.signal)]);
   if(!controller.signal.aborted){const failure=refreshed.find(item=>item.status==='rejected');if(failure?.status==='rejected')setRefreshError(`Run 삭제는 완료되었지만 목록 새로고침에 실패했습니다. 화면을 다시 열어 목록을 확인하세요. ${describeImportError(failure.reason)}`);}
  }catch(cause){if(!controller.signal.aborted)setDeleteError(describeImportError(cause));}
  finally{deletionRunning.current=false;if(!controller.signal.aborted)setDeleting(false);}
 }
 function chooseRun(runId:string){const run=runs.find(item=>item.runId===runId);update({catalogSelectedRunId:runId,catalogSelectedJobId:jobs.find(job=>job.runVersionId===run?.runVersionId&&job.status==='READY')?.jobId??''});}
 function chooseJob(job:JobView){update({catalogSelectedJobId:job.jobId,catalogSelectedRunId:job.status==='READY'&&job.runVersionId?runs.find(run=>run.runVersionId===job.runVersionId)?.runId??'':''});}
 const visibleJobs=jobs.filter(job=>job.status!=='READY').filter(job=>!state.catalogFilters.status||job.status===state.catalogFilters.status).filter(()=>!state.catalogFilters.quality).filter(job=>!state.catalogFilters.search||`${job.runId??''} ${job.reason??''}`.toLocaleUpperCase('en-US').includes(state.catalogFilters.search.trim().toLocaleUpperCase('en-US')));
 return <><div className="page-header"><div><span className="eyebrow">RUN DATA MANAGEMENT</span><h1>Run 데이터 관리</h1><p>Run 등록·파싱·품질·원본 파일 추적 상태를 확인합니다.</p></div><div className="page-actions"><span className="trust-label"><span className="status-dot status-dot--success"/>{catalog?`${catalog.runs.length} registered runs`:'등록 목록 준비 중'}</span><button className="button button--danger button--small" type="button" disabled={deleteDisabled||!catalog?.runs.length} aria-describedby={importActive?'run-delete-disabled':undefined} onClick={()=>requestDeletion(catalog?.runs.map(run=>run.runId)??[],true)}>전체 Run 삭제</button></div></div>
 <section className="catalog-summary">{[['전체 Run',catalog?String(runs.length+jobs.filter(job=>!['READY','DUPLICATE'].includes(job.status)).length):'—','Registered catalog'],['파싱 완료',catalog?String(runs.filter(run=>run.catalogStatus==='READY').length):'—','Ready for analysis'],['불완전',catalog?String(jobs.filter(job=>job.status==='INCOMPLETE').length):'—','Required file missing'],['실패',catalog?String(jobs.filter(job=>['PARSE_FAILED','INTERRUPTED'].includes(job.status)).length):'—','Needs correction']].map(([label,count,hint])=><article key={label}><span>{label}</span><strong>{count}</strong><small>{hint}</small></article>)}</section>
 {error&&<div className="partial-notice" role="alert">{error}</div>}
 {importActive&&<p id="run-delete-disabled" className="partial-notice">업로드 또는 재처리가 진행 중입니다. 완료 후 Run을 삭제할 수 있습니다.</p>}
 {deleteNotice&&<p className="partial-notice" role="status">{deleteNotice}</p>}
 {refreshError&&<p className="partial-notice" role="alert">{refreshError}</p>}
 <div className="catalog-layout"><section className="panel catalog-table-panel"><div className="panel-heading"><div><span className="section-kicker">RUN INDEX</span><h2>등록 Run</h2><p>{rows.length+visibleJobs.length}건 표시</p></div></div><form id="catalog-filter-form" className="catalog-toolbar" onSubmit={event=>{event.preventDefault();update({catalogFilters:{...draft}});}}><label><span className="sr-only">Run 또는 파일 검색</span><input name="search" value={draft.search} placeholder="Run ID 또는 파일명 검색" onChange={event=>setDraft({...draft,search:event.target.value})}/></label><label><span className="sr-only">파싱 상태</span><select name="status" value={draft.status} onChange={event=>setDraft({...draft,status:event.target.value})}><option value="">모든 파싱 상태</option>{Object.entries(jobLabels).filter(([key])=>!['SUCCESS','PARTIAL_SUCCESS','FAILED'].includes(key)).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></label><label><span className="sr-only">품질 상태</span><select name="quality" value={draft.quality} onChange={event=>setDraft({...draft,quality:event.target.value})}><option value="">모든 품질</option><option value="VERIFIED">검증됨</option><option value="UNVERIFIED">미검증</option><option value="REJECTED">제외됨</option></select></label><button className="button button--secondary" type="submit">적용</button></form>
 {rows.length||visibleJobs.length?<div className="catalog-table-wrap"><table className="catalog-table"><thead><tr>{['Run ID','Pressure','Source','Bias','Quality','Parsing','Files'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{rows.map(row=><tr className={row.runId===state.catalogSelectedRunId?'is-selected':''} key={row.sourceRun.runVersionId}><th scope="row"><button type="button" data-action="catalog-select" data-run-id={row.runId} onClick={()=>chooseRun(row.runId)}>{row.runId}</button></th>{row.conditions.map(item=><td key={item.label}>{item.value} <small>{item.unit}</small></td>)}<td><span className={`badge ${tone(row.qualityStatus)}`}>{row.qualityLabel}</span></td><td><span className={`badge ${tone(row.parsingStatus)}`}>{row.parsingLabel}</span></td><td>{row.sourceFileCount}</td></tr>)}{visibleJobs.map(job=><tr key={job.jobId} className={job.jobId===selectedJob?.jobId?'is-selected':''}><th scope="row"><button type="button" onClick={()=>chooseJob(job)}>{job.runId??job.jobId}</button></th><td colSpan={4}>{job.reason??jobLabels[job.status]}</td><td><span className={`badge ${tone(job.status)}`}>{jobLabels[job.status]}</span></td><td>—</td></tr>)}</tbody></table></div>:catalog?<div className="table-empty"><div className="empty-icon">⌕</div><h3>검색 결과가 없습니다</h3><p>필터를 변경하거나 Run ID를 다시 확인해 주세요.</p></div>:<p>등록 목록을 불러오는 중입니다.</p>}</section>
 <aside className="panel catalog-detail">{selectedRow?<><div className="panel-heading"><div><span className="section-kicker">RUN DETAIL</span><h2>{selectedRow.runId}</h2></div><span className={`badge ${tone(selectedRow.parsingStatus)}`}>{selectedRow.parsingLabel}</span></div>{selectedRow.parsingStatus!=='READY'&&<div className="partial-notice"><strong>분석 제외 상태</strong><p>{selectedRow.note||'필수 결과를 확인할 수 없습니다.'}</p></div>}<div className="detail-condition-grid">{selectedRow.conditions.map(item=><div key={item.label}><span>{item.label}</span><strong>{item.value}</strong><small>{item.unit}</small></div>)}</div><div className="detail-metric-list">{selectedRow.metrics.map(item=><div key={item.label}><span>{item.label}</span><strong>{item.value} <small>{item.unit}</small></strong></div>)}</div><dl className="detail-meta"><div><dt>수렴</dt><dd>{selectedRow.convergenceLabel}</dd></div><div><dt>품질</dt><dd>{selectedRow.qualityLabel}</dd></div><div><dt>등록</dt><dd>{selectedRow.registeredAt}</dd></div></dl><div className="detail-files"><span>원본 파일 {selectedRow.sourceFileCount}개</span>{(full?.sourceFiles??selectedRow.sourceRun.sourceFiles).map(file=><div key={file.path}><strong>{file.name}</strong><small>{['PARSED','READY'].includes(file.status)?'파싱 완료':'실패'}</small></div>)}</div>{selectedRow.parsingStatus==='READY'&&ref&&<button className="button button--secondary button--block" type="button" data-action="analysis-forward" data-run-id={ref.runId} onClick={()=>onReference?.(ref)}>Agent에서 자세히 보기</button>}<button className="button button--danger button--block" type="button" disabled={deleteDisabled} aria-describedby={importActive?'run-delete-disabled':undefined} onClick={()=>requestDeletion([selectedRow.runId],false)}>선택 Run 삭제</button></>:selectedJob?<><div className="panel-heading"><div><span className="section-kicker">RUN DETAIL</span><h2>{selectedJob.runId??selectedJob.jobId}</h2></div><span className={`badge ${tone(selectedJob.status)}`}>{jobLabels[selectedJob.status]}</span></div><div className="partial-notice"><strong>{selectedJob.status==='DUPLICATE'?'중복 등록 상태':'분석 제외 상태'}</strong><p>{selectedJob.reason??jobLabels[selectedJob.status]}</p>{selectedJob.errors.map((item,index)=><p key={index}>{item.message}{item.field?` (${item.field})`:''}</p>)}</div></>:<p>Run을 선택하세요.</p>}{fullError&&<p role="alert">{fullError}</p>}{fileError?.jobId===selectedJob?.jobId&&fileError&&<p role="alert">{fileError.message}</p>}{files&&<div className="detail-files"><span>이 Run의 업로드 원본 전체 {files.length}개</span>{files.map(file=><div key={file.path}><strong style={{overflowWrap:'anywhere'}}>{file.path}</strong><small>{file.kind} · {file.size} bytes</small></div>)}</div>}</aside></div>
 <UploadControls imports={imports} selectedJob={selectedJob} disabled={deleting}/>
 {deletion&&<Modal titleId="run-delete-title" descriptionId="run-delete-description" role="alertdialog" className="confirm-modal run-delete-modal" onClose={closeDeletion} synchronousFocus initialFocusSelector="[data-delete-cancel]">
  <div className="confirm-icon confirm-icon--warning" aria-hidden="true">!</div><h2 id="run-delete-title">{deletion.all?'등록된 전체 Run을 삭제할까요?':'선택 Run을 삭제할까요?'}</h2>
  <p id="run-delete-description">{deletion.all?'현재 필터와 관계없이 ':''}등록 Run {deletion.runIds.length}개의 모든 버전과 관리 원본 파일을 삭제합니다. 외부 원본 폴더는 유지됩니다.</p>
  {!deletion.all&&<p className="run-delete-id">{deletion.runIds[0]}</p>}
  <p>저장된 판단 기록에서 사용 중인 Run이 있으면 전체 삭제 요청이 취소됩니다. 일반 채팅에서 조회한 Run은 삭제할 수 있습니다.</p>
  {deleteError&&<p role="alert">{deleteError}</p>}
  <div className="form-actions"><button className="button button--ghost" type="button" disabled={deleting} data-delete-cancel onClick={closeDeletion}>취소</button><button className="button button--danger" type="button" disabled={deleteDisabled} onClick={()=>void confirmDeletion()}>{deleting?'삭제 중…':'삭제'}</button></div>
 </Modal>}</>;
}
