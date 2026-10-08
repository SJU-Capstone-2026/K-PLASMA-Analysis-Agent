import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {expect,test,type Page} from '@playwright/test';
import {toRunSummary,type TurnSnapshot,type WorkspaceView} from 'agent';
import {syntheticRun} from '../../test/runs';
import {emptyWorkspace,initialTurnUi} from './useConversation';

type Sample={domMs:number;frameMs:number;clickStartMs:number};
async function measure(page:Page,selector:string,changedSelector:string):Promise<Sample>{
 await page.locator(selector).scrollIntoViewIfNeeded();
 await page.evaluate(({selector,changedSelector})=>{
  const state=window as typeof window&{turnUiSample?:Promise<Sample>};
  state.turnUiSample=new Promise(resolve=>{
   let start=0;
   const observer=new MutationObserver(()=>{
    if(!start||!document.querySelector(changedSelector))return;
    const domMs=performance.now()-start;observer.disconnect();
    // Two animation frames bracket a paint opportunity; this is a proxy, not INP.
    requestAnimationFrame(()=>requestAnimationFrame(()=>resolve({domMs,frameMs:performance.now()-start,clickStartMs:start})));
   });
   document.addEventListener('click',()=>{start=performance.now();observer.observe(document.body,{subtree:true,childList:true,attributes:true});},{capture:true,once:true});
   if(!document.querySelector(selector))throw new Error('Measurement target is missing');
  });
 },{selector,changedSelector});
 await page.locator(selector).click();
 return page.evaluate(()=>(window as typeof window&{turnUiSample:Promise<Sample>}).turnUiSample);
}
function stats(samples:number[]){const sorted=[...samples].sort((a,b)=>a-b);const percentile=(p:number)=>sorted[Math.ceil(sorted.length*p)-1];return {median:percentile(.5),p95:percentile(.95),min:sorted[0],max:sorted.at(-1)};}

test('synthetic card and stored graph-tab click latency, with identical 500ms UI saves',async({page},info)=>{
 test.skip(!!process.env.KPLASMA_UI_PERF_API,'Real HTTP mode uses the existing workspace test');
 const runs=[600,800,1000,200,400].map(bias=>syntheticRun(bias));const run=runs[0];
 const turn:TurnSnapshot={id:'perf-turn',askedAt:'2026-10-08T00:00:00Z',question:'합성 후보 조회',intent:'REVERSE_SEARCH',context:null,
  answerRunRefs:runs.map(({runId,runVersionId})=>({runId,runVersionId})),ui:{...structuredClone(initialTurnUi),runDetailTabs:{[run.runId]:'ied'}},
  answerSnapshot:JSON.parse(JSON.stringify({implementationId:'v1',schemaVersion:1,kind:'reverse_search',summary:'합성 성능 검증',result:{kind:'reverse_search',resultStatus:'MATCH',constraints:[],goals:[],objectives:[],commonCandidates:runs.map(run=>({run:toRunSummary(run),evaluations:[],matchPercent:100})),objectiveResults:[],goalResults:[],nearMisses:[]}})),
 };
 let workspace:WorkspaceView={...structuredClone(emptyWorkspace),conversation:{version:1,activeRun:null,turns:[turn]}};let writes=0;
 await page.route('**/api/**',async route=>{
  const request=route.request();const path=new URL(request.url()).pathname;
  if(!path.startsWith('/api/'))return route.continue();
  if(path==='/api/decisions')return route.fulfill({json:[]});
  if(path==='/api/runs')return route.fulfill({json:runs.map(toRunSummary)});
  if(path.startsWith('/api/run-versions/'))return route.fulfill({json:run});
  if(path.endsWith('/ui')){
   const body=request.postDataJSON();await new Promise(resolve=>setTimeout(resolve,500));
   expect(body.stateToken).toEqual(workspace.stateToken);
   turn.ui={...turn.ui,...body.ui,runDetailTabs:{...turn.ui.runDetailTabs,...body.ui.runDetailTabs}};
   workspace={...workspace,stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1}};
   await route.fulfill({json:workspace});writes++;
   return;
  }
  return route.fulfill({json:workspace});
 });
 await page.goto('/');await expect(page.locator('.agent-fit-card')).toHaveCount(5);await page.evaluate(()=>document.fonts.ready);
 const card='.agent-fit-card:first-child';const control=`${card} [data-action="select-candidate-card"]`;
 const results:{card:Sample[];graph:Sample[]}={card:[],graph:[]};let expectedWrites=0;
 for(let index=0;index<22;index++){
  const sample=await measure(page,control,`${card}${index%2===0?'.is-selected':':not(.is-selected)'}`);
  if(index>=2)results.card.push(sample);await expect.poll(()=>writes).toBe(++expectedWrites);
 }
 await page.locator(card).getByRole('button',{name:'실험 자세히 보기'}).click();
 await expect(page.locator('[data-tab="ied"]')).toHaveAttribute('aria-selected','true');
 for(let index=0;index<22;index++){
  const selector=`[data-tab="${index%2===0?'residual':'ied'}"]`;
  const sample=await measure(page,selector,`${selector}[aria-selected="true"]`);
  if(index>=2)results.graph.push(sample);await expect.poll(()=>writes).toBe(++expectedWrites);
 }
 const report={variant:(process.env.KPLASMA_UI_BASELINE_FILE||process.env.KPLASMA_UI_BASELINE_REF)?'before':'after',browser:page.context().browser()?.version(),viewport:{width:1440,height:1000},saveDelayMs:500,samplesPerAction:20,warmupPerAction:2,writes,
  stats:{card:{dom:stats(results.card.map(s=>s.domMs)),frame:stats(results.card.map(s=>s.frameMs))},graph:{dom:stats(results.graph.map(s=>s.domMs)),frame:stats(results.graph.map(s=>s.frameMs))}},samples:results};
 const path=process.env.KPLASMA_UI_PERF_REPORT??info.outputPath('turn-ui-performance.json');
 await writeFile(path,JSON.stringify(report,null,2));console.log(JSON.stringify({...report,samples:undefined}));
});

test('existing workspace card and graph latency over real HTTP and PostgreSQL',async({page,request},info)=>{
 const api=process.env.KPLASMA_UI_PERF_API;
 test.skip(!api,'Requires an explicitly provided real local backend');
 const load=async()=>{const response=await request.get(`${api}/api/workspace`);expect(response.status()).toBe(200);return await response.json() as WorkspaceView;};
 const original=await load();expect(original.activeAgentRequest??null).toBeNull();
 const fingerprint=(value:WorkspaceView)=>createHash('sha256').update(JSON.stringify({...value.conversation,turns:value.conversation.turns.map(turn=>({...turn,ui:undefined}))})).digest('hex');
 const candidate=[...original.conversation.turns].reverse().find(turn=>turn.answerSnapshot.kind==='reverse_search'&&turn.ui.activeCandidateGroup==='common'&&Object.keys(turn.ui.runDetailTabs).some(id=>(turn.answerSnapshot.result as {commonCandidates?:{run:{runId:string}}[]})?.commonCandidates?.some(c=>c.run.runId===id)));
 if(!candidate)throw new Error('Real measurement requires an existing candidate with a saved graph tab; no conversation is fabricated');
 const candidates=(candidate.answerSnapshot.result as {commonCandidates:{run:{runId:string}}[]}).commonCandidates;
 const runId=Object.keys(candidate.ui.runDetailTabs).find(id=>candidates.some(c=>c.run.runId===id))!;
 const turnSelector=`[data-turn-id="${candidate.id}"]`;
 const card=`${turnSelector} .agent-fit-card:has([data-action="select-candidate-card"][data-run-id="${runId}"])`;
 const control=`${card} [data-action="select-candidate-card"]`;
 type LiveSample=Sample&{httpMs:number;clickToResponseMs:number;responseBytes:number};
 const samples:{card:LiveSample[];graph:LiveSample[]}={card:[],graph:[]};let writes=0;let mutationErrors=0;
 let lastSelection=candidate.ui.selectedCandidateRunId;let lastTab=candidate.ui.runDetailTabs[runId];
 page.on('request',req=>{if(req.method()==='PATCH'&&new URL(req.url()).pathname.endsWith(`/turns/${candidate.id}/ui`))writes++;});
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 async function click(action:'card'|'graph',selector:string,changedSelector:string){
  const saved=page.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname.endsWith(`/turns/${candidate!.id}/ui`));
  const sample=await measure(page,selector,changedSelector);const response=await saved;
  if(response.status()!==200)mutationErrors++;expect(response.status()).toBe(200);await response.finished();
  const timing=await page.evaluate(id=>{
   const entries=(performance.getEntriesByType('resource') as PerformanceResourceTiming[]).filter(e=>new URL(e.name).pathname.endsWith(`/turns/${id}/ui`));
   const last=entries.at(-1);if(!last)throw new Error('Real UI resource timing is unavailable');
   return {httpMs:last.duration,responseEnd:last.responseEnd,responseBytes:last.encodedBodySize};
  },candidate!.id);
  // Let the confirmed response render before the next independent click; no server delay is introduced.
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
  return {...sample,httpMs:timing.httpMs,clickToResponseMs:timing.responseEnd-sample.clickStartMs,responseBytes:timing.responseBytes,action};
 }
 let report:Record<string,unknown>|undefined;
 try{
  await page.goto('/');await expect(page.locator(control)).toBeVisible();await page.evaluate(()=>document.fonts.ready);
  for(let index=0;index<25;index++){
   const selected=(await page.locator(card).getAttribute('class'))!.includes('is-selected');lastSelection=selected?null:runId;
   const sample=await click('card',control,`${card}${selected?':not(.is-selected)':'.is-selected'}`);if(index>=5)samples.card.push(sample);
  }
  await page.locator(card).getByRole('button',{name:'실험 자세히 보기'}).click();
  await expect(page.locator('[data-tab="ied"]')).toBeEnabled();await expect(page.locator('[data-tab="residual"]')).toBeEnabled();
  for(let index=0;index<25;index++){
   const isIed=await page.locator('[data-tab="ied"]').getAttribute('aria-selected')==='true';lastTab=isIed?'residual':'ied';
   const selector=`[data-tab="${lastTab}"]`;const sample=await click('graph',selector,`${selector}[aria-selected="true"]`);if(index>=5)samples.graph.push(sample);
  }
  const live=await load();expect(fingerprint(live)).toBe(fingerprint(original));
  const runsResponse=await request.get(`${api}/api/runs`);expect(runsResponse.status()).toBe(200);const runs=await runsResponse.json() as unknown[];
  const aggregate=(values:LiveSample[])=>({dom:stats(values.map(s=>s.domMs)),frame:stats(values.map(s=>s.frameMs)),http:stats(values.map(s=>s.httpMs)),clickToResponse:stats(values.map(s=>s.clickToResponseMs)),responseBytes:stats(values.map(s=>s.responseBytes))});
  report={variant:(process.env.KPLASMA_UI_BASELINE_FILE||process.env.KPLASMA_UI_BASELINE_REF)?'before':'after',mode:'real-http-postgresql',browser:page.context().browser()?.version(),viewport:{width:1440,height:1000},artificialDelayMs:0,registeredRuns:runs.length,conversationTurns:original.conversation.turns.length,cardsInMeasuredGroup:candidates.length,samplesPerAction:20,warmupPerAction:5,writes,mutationErrors,pageErrors:errors.length,conversationSnapshotsUnchanged:true,stats:{card:aggregate(samples.card),graph:aggregate(samples.graph)},samples};
  expect(writes).toBe(50);expect(errors).toEqual([]);
 }finally{
  const live=await load();expect(live.stateToken.workspaceEpoch).toBe(original.stateToken.workspaceEpoch);expect(live.stateToken.conversationEpoch).toBe(original.stateToken.conversationEpoch);expect(fingerprint(live)).toBe(fingerprint(original));
  const turn=live.conversation.turns.find(t=>t.id===candidate.id)!;
  // Restore only our two fields and refuse to overwrite another writer's newer choice.
  expect(turn.ui.selectedCandidateRunId).toBe(lastSelection);expect(turn.ui.runDetailTabs[runId]).toBe(lastTab);
  const restored=await request.patch(`${api}/api/workspace/turns/${candidate.id}/ui`,{data:{stateToken:live.stateToken,ui:{selectedCandidateRunId:candidate.ui.selectedCandidateRunId,runDetailTabs:{[runId]:candidate.ui.runDetailTabs[runId]}}}});expect(restored.status()).toBe(200);
  const final=await load();expect(final.conversation.turns.map(t=>t.ui)).toEqual(original.conversation.turns.map(t=>t.ui));expect(fingerprint(final)).toBe(fingerprint(original));
  if(report){report.originalUiRestored=true;const path=process.env.KPLASMA_UI_PERF_REPORT??info.outputPath('real-turn-ui-performance.json');await writeFile(path,JSON.stringify(report,null,2),{mode:0o600});const verified=JSON.parse(await readFile(path,'utf8'));expect(verified.originalUiRestored).toBe(true);console.log(JSON.stringify({...report,samples:undefined}));}
 }
});
