import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {toRunSummary,type BatchView,type JobView} from 'agent';
import type {CatalogData} from '../../api/imports';
import {App} from '../../App';
import {syntheticRun} from '../../test/runs';
import {CatalogPage} from './CatalogPage';

const first=syntheticRun(),second=syntheticRun(800);
const ready:JobView={jobId:'ready-first',runId:first.runId,runVersionId:first.runVersionId,status:'READY',reason:null,errors:[]};
const other:JobView={...ready,jobId:'ready-second',runId:second.runId,runVersionId:second.runVersionId};
const failed:JobView={jobId:'failed-unregistered',runId:'FAILED-UNREGISTERED',runVersionId:null,status:'PARSE_FAILED',reason:'인공 파일 오류',errors:[]};
const original:CatalogData={runs:[toRunSummary(first),toRunSummary(second)],jobs:[ready,other,failed],sourceFilesByVersion:{[first.runVersionId]:first.sourceFiles,[second.runVersionId]:second.sourceFiles}};
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status});
function api(options:{blocked?:string;cleanupPending?:boolean;reloadFails?:boolean;deferredDetail?:boolean;deferredDelete?:boolean;active?:boolean;alreadyMissing?:boolean}={}){
 let value=options.active?{...original,jobs:[...original.jobs,{...failed,jobId:'active',status:'PROCESSING' as const}]}:original;
 let committed=false,finishDetail!:(value:Response)=>void,finishDelete!:(value:Response)=>void;
 const calls:{url:string;init?:RequestInit}[]=[];
 const sendDelete=(ids:string[])=>{committed=true;value={runs:value.runs.filter(run=>!ids.includes(run.runId)),jobs:value.jobs.filter(job=>!job.runId||!ids.includes(job.runId)),sourceFilesByVersion:Object.fromEntries(value.runs.filter(run=>!ids.includes(run.runId)).map(run=>[run.runVersionId,value.sourceFilesByVersion[run.runVersionId]]))};return json({deletedRunIds:options.alreadyMissing?[]:ids,cleanupPending:!!options.cleanupPending});};
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  calls.push({url,init});
  if(url==='/api/runs/delete'){
   if(options.blocked)return json({code:options.blocked,message:'판단 기록에서 사용 중인 Run은 삭제할 수 없습니다.',requestId:'delete-test'},409);
   const ids=JSON.parse(init!.body as string).runIds as string[];
   if(options.deferredDelete)return new Promise<Response>(resolve=>{finishDelete=()=>resolve(sendDelete(ids));});
   return sendDelete(ids);
  }
  if(url==='/api/catalog')return committed&&options.reloadFails?json({code:'OFFLINE',message:'목록 연결 실패',requestId:'refresh'},503):json(value);
  if(url==='/api/runs')return committed&&options.reloadFails?json({code:'OFFLINE',message:'목록 연결 실패',requestId:'refresh'},503):json(value.runs);
  if(url.startsWith('/api/run-versions/'))return options.deferredDetail?new Promise<Response>(resolve=>{finishDetail=resolve;}):json(url.includes(second.runVersionId)?second:first);
  if(url.endsWith('/files'))return json([{path:'uploaded/original.dat',kind:'DAT',size:4,sha256:'synthetic'}]);
  if(url==='/api/decisions')return json([]);
  if(url==='/api/workspace')return json({stateToken:{workspaceEpoch:0,conversationEpoch:0,revision:0},conversation:{version:1,activeRun:null,turns:[]},candidateReference:null});
  throw new Error(`Unexpected request ${url}`);
 }));
 return {calls,finishDetail:()=>finishDetail(json({...first,sourceFiles:[{...first.sourceFiles[0],name:'LATE-DELETED-SOURCE.dat'}]})),finishDelete:()=>finishDelete(json(null))};
}
const deletes=(calls:ReturnType<typeof api>['calls'])=>calls.filter(call=>call.url==='/api/runs/delete');
async function selectFirst(){fireEvent.click(await screen.findByRole('button',{name:first.runId}));const trigger=screen.getByRole('button',{name:'선택 Run 삭제'});trigger.focus();fireEvent.click(trigger);return screen.getByRole('alertdialog');}
function confirm(){fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button',{name:'삭제'}));}
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});

test('cancel and Escape leave the selected Run intact and return focus without a delete request',async()=>{
 const server=api();render(<CatalogPage/>);await selectFirst();
 expect(within(screen.getByRole('alertdialog')).getByRole('button',{name:'취소'})).toHaveFocus();
 expect(screen.getByRole('alertdialog')).toHaveAccessibleDescription(/등록 Run 1개.*모든 버전.*관리 원본/);
 expect(screen.getByRole('alertdialog')).toHaveTextContent('외부 원본 폴더');
 expect(screen.getByRole('alertdialog')).toHaveTextContent('판단 기록');
 expect(screen.getByRole('alertdialog')).not.toHaveTextContent('대화·판단');
 fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button',{name:'취소'}));
 expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'선택 Run 삭제'})).toHaveFocus();
 fireEvent.click(screen.getByRole('button',{name:'선택 Run 삭제'}));fireEvent.keyDown(screen.getByRole('alertdialog'),{key:'Escape'});
 expect(deletes(server.calls)).toHaveLength(0);expect(screen.getByRole('button',{name:first.runId})).toBeInTheDocument();
});
test('single deletion sends one Run ID and clears selected details and job inventory after refreshing both lists',async()=>{
 const server=api();render(<CatalogPage/>);await selectFirst();await screen.findByText('uploaded/original.dat');confirm();
 await waitFor(()=>expect(screen.queryByRole('button',{name:first.runId})).not.toBeInTheDocument());
 expect(deletes(server.calls)).toHaveLength(1);expect(deletes(server.calls)[0].init).toMatchObject({method:'POST',headers:expect.objectContaining({'Content-Type':'application/json'}),body:JSON.stringify({runIds:[first.runId]})});
 expect(screen.getByRole('button',{name:second.runId})).toBeInTheDocument();expect(screen.getByText('Run을 선택하세요.')).toBeInTheDocument();expect(screen.queryByText('uploaded/original.dat')).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'다시 처리'})).not.toBeInTheDocument();
 expect(server.calls.filter(call=>call.url==='/api/catalog')).toHaveLength(2);expect(server.calls.some(call=>call.url==='/api/runs')).toBe(true);
});
test('all deletion confirms the unfiltered registered count and excludes failed unregistered jobs from its payload',async()=>{
 const server=api();render(<CatalogPage/>);await screen.findByRole('button',{name:first.runId});
 fireEvent.change(screen.getByLabelText('Run 또는 파일 검색'),{target:{value:'NO-MATCH'}});fireEvent.submit(document.getElementById('catalog-filter-form')!);
 expect(screen.queryByRole('button',{name:first.runId})).not.toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:'전체 Run 삭제'}));
 expect(screen.getByRole('alertdialog')).toHaveAccessibleDescription(/등록 Run 2개/);confirm();await waitFor(()=>expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
 expect(JSON.parse(deletes(server.calls)[0].init!.body as string)).toEqual({runIds:[first.runId,second.runId]});
 fireEvent.change(screen.getByLabelText('Run 또는 파일 검색'),{target:{value:''}});fireEvent.submit(document.getElementById('catalog-filter-form')!);
 expect(screen.getByRole('button',{name:failed.runId!})).toBeInTheDocument();expect(screen.getByRole('button',{name:'전체 Run 삭제'})).toBeDisabled();
});
test.each(['RUN_IN_USE','IMPORT_IN_PROGRESS'])('%s preserves the entire catalog and displays the server reason',async code=>{
 const server=api({blocked:code});render(<CatalogPage/>);await screen.findByRole('button',{name:first.runId});fireEvent.click(screen.getByRole('button',{name:'전체 Run 삭제'}));confirm();
 expect(await within(screen.getByRole('alertdialog')).findByRole('alert')).toHaveTextContent(code);expect(screen.getByRole('button',{name:first.runId})).toBeInTheDocument();expect(screen.getByRole('button',{name:second.runId})).toBeInTheDocument();expect(deletes(server.calls)).toHaveLength(1);
});
test('cleanup pending reports completed database removal and restart cleanup without restoring the Run',async()=>{
 api({cleanupPending:true});render(<CatalogPage/>);await selectFirst();confirm();
 await waitFor(()=>expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());expect(screen.getByRole('status')).toHaveTextContent(/DB.*삭제.*완료/);expect(screen.getByRole('status')).toHaveTextContent(/재시작.*재시도/);expect(screen.queryByRole('button',{name:first.runId})).not.toBeInTheDocument();
});
test('refresh failure after committed deletion keeps the Run removed and does not offer a destructive retry',async()=>{
 const server=api({reloadFails:true});render(<CatalogPage/>);await selectFirst();confirm();
 expect(await screen.findByRole('alert')).toHaveTextContent(/삭제.*완료.*새로고침.*실패/);expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:first.runId})).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'선택 Run 삭제'})).not.toBeInTheDocument();expect(deletes(server.calls)).toHaveLength(1);
});
test('late selected Run detail cannot restore deleted files after a successful mutation',async()=>{
 const server=api({deferredDetail:true});render(<CatalogPage/>);await selectFirst();confirm();await waitFor(()=>expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
 await act(async()=>server.finishDetail());expect(screen.queryByText('LATE-DELETED-SOURCE.dat')).not.toBeInTheDocument();expect(screen.getByText('Run을 선택하세요.')).toBeInTheDocument();
});
test('rapid confirmation submits once and blocks uploads until deletion resolves',async()=>{
 const server=api({deferredDelete:true});render(<CatalogPage/>);await selectFirst();const button=within(screen.getByRole('alertdialog')).getByRole('button',{name:'삭제'});fireEvent.click(button);fireEvent.click(button);
 expect(deletes(server.calls)).toHaveLength(1);expect(screen.getByRole('button',{name:'폴더 선택'})).toBeDisabled();expect(screen.getByRole('button',{name:'ZIP 선택'})).toBeDisabled();expect(within(screen.getByRole('alertdialog')).getByRole('button',{name:'취소'})).toBeDisabled();
 await act(async()=>server.finishDelete());await waitFor(()=>expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
});
test('active server imports disable single and all deletion with an accessible explanation',async()=>{
 api({active:true});render(<CatalogPage/>);fireEvent.click(await screen.findByRole('button',{name:first.runId}));
 expect(screen.getByRole('button',{name:'선택 Run 삭제'})).toBeDisabled();expect(screen.getByRole('button',{name:'전체 Run 삭제'})).toBeDisabled();expect(screen.getByRole('button',{name:'전체 Run 삭제'})).toHaveAccessibleDescription(/업로드.*재처리.*완료/);
});
test('navigation to analysis after deleting all Runs fetches the empty list instead of retaining a deleted selection',async()=>{
 vi.spyOn(window,'scrollTo').mockImplementation(()=>{});const server=api();render(<App/>);
 fireEvent.click(screen.getByRole('button',{name:'실험 데이터 탐색'}));await screen.findByRole('heading',{name:`${first.runId} 세부 결과`});
 fireEvent.click(screen.getByText('도구 및 도움말'));fireEvent.click(screen.getByRole('button',{name:'Run 데이터 관리'}));await screen.findByRole('button',{name:first.runId});fireEvent.click(screen.getByRole('button',{name:'전체 Run 삭제'}));confirm();await waitFor(()=>expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
 await waitFor(()=>expect(server.calls.filter(call=>call.url==='/api/workspace')).toHaveLength(2));
 fireEvent.click(screen.getByRole('button',{name:'실험 데이터 탐색'}));expect(await screen.findByText('실제 Run 데이터를 찾을 수 없습니다.')).toBeInTheDocument();expect(screen.queryByRole('heading',{name:`${first.runId} 세부 결과`})).not.toBeInTheDocument();expect(server.calls.filter(call=>call.url==='/api/runs').length).toBeGreaterThanOrEqual(3);
});

class UploadRequest {
 static current:UploadRequest;upload={onprogress:null};status=202;responseText='';onload:(()=>void)|null=null;onerror:(()=>void)|null=null;onabort:(()=>void)|null=null;
 constructor(){UploadRequest.current=this;}open(){}setRequestHeader(){}send(){}abort(){this.onabort?.();}
 finish(){const batch:BatchView={batchId:'completed-upload',status:'PARTIAL_SUCCESS',receivedBytes:4,totalBytes:4,processedRuns:3,totalRuns:3,jobs:[ready,other,failed]};this.responseText=JSON.stringify(batch);this.onload?.();}
}
function startUpload(){vi.stubGlobal('XMLHttpRequest',UploadRequest);fireEvent.change(screen.getByLabelText('ZIP 선택'),{target:{files:[new File(['zip'],'synthetic.zip')]}});}
test('in-flight upload disables deletion and completed batch inventory forgets deleted Run jobs',async()=>{
 api();render(<CatalogPage/>);await screen.findByRole('button',{name:first.runId});startUpload();
 expect(screen.getByRole('button',{name:'전체 Run 삭제'})).toBeDisabled();await act(async()=>UploadRequest.current.finish());
 expect(document.querySelector('.parsing-status ul')).toHaveTextContent(first.runId);await selectFirst();confirm();await waitFor(()=>expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
 expect(document.querySelector('.parsing-status')).not.toHaveTextContent(first.runId);expect(screen.getByRole('button',{name:failed.runId!})).toBeInTheDocument();
});
test('late pre-upload catalog response cannot restore Run rows after deletion',async()=>{
 api();const normal=fetch;let resolveInitial!:(response:Response)=>void,requests=0;
 vi.stubGlobal('fetch',vi.fn((url:string,init?:RequestInit)=>url==='/api/catalog'&&++requests===1?new Promise<Response>(resolve=>{resolveInitial=resolve;}):normal(url,init)));
 render(<CatalogPage/>);startUpload();await act(async()=>UploadRequest.current.finish());await selectFirst();confirm();await waitFor(()=>expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
 await act(async()=>resolveInitial(json(original)));expect(screen.queryByRole('button',{name:first.runId})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:second.runId})).toBeInTheDocument();
});

test('successful deletion notifies retained shell selections even when its refresh fails',async()=>{
 api({reloadFails:true});const deleted=vi.fn();render(<CatalogPage onDeleted={deleted}/>);await selectFirst();confirm();
 await screen.findByRole('alert');expect(deleted).toHaveBeenCalledExactlyOnceWith([first.runId]);
});
test('idempotent success for an already missing Run clears its stale local selection',async()=>{
 api({alreadyMissing:true});render(<CatalogPage/>);await selectFirst();confirm();await waitFor(()=>expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
 expect(screen.queryByRole('button',{name:first.runId})).not.toBeInTheDocument();expect(screen.getByText('Run을 선택하세요.')).toBeInTheDocument();expect(screen.getByRole('status')).toHaveTextContent('0개');
});
