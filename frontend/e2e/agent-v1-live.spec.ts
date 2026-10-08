import {expect,test,type APIRequestContext,type Page} from '@playwright/test';
import type {AgentRequestView,RunSummary,TurnSnapshot,WorkspaceView} from 'agent';

const api=process.env.KPLASMA_E2E_API;
if(!api)throw new Error('The v1 live gate requires an isolated backend and running Python worker via KPLASMA_E2E_API.');
if(process.env.KPLASMA_E2E_REFERENCE==='true')throw new Error('The v1 live gate uses artificial registered Runs only; do not capture real result data.');
const widths=process.env.KPLASMA_V1_LIVE_WIDTHS?process.env.KPLASMA_V1_LIVE_WIDTHS.split(',').map(Number):[390,800,1008,1440];
const kindIntents={forward_lookup:'FORWARD_LOOKUP',reverse_search:'REVERSE_SEARCH',compare_runs:'RUN_COMPARISON',generate_answer:'GENERAL_ANSWER'};
async function workspace(request:APIRequestContext):Promise<WorkspaceView>{const response=await request.get(`${api}/api/workspace`);expect(response.status()).toBe(200);return response.json();}
async function status(request:APIRequestContext,id:string):Promise<AgentRequestView>{const response=await request.get(`${api}/api/agent/requests/${id}`);expect(response.status()).toBe(200);return response.json();}
async function terminal(request:APIRequestContext,id:string,minRevision=0){let saved:AgentRequestView;await expect.poll(async()=>{saved=await status(request,id);return saved.requestRevision>=minRevision?saved.status:'WAITING_FOR_RESUME';},{timeout:90000,intervals:[300,500,1000]}).toMatch(/^(COMPLETED|NEEDS_INPUT|FAILED|CANCELLED)$/);return saved!;}
async function ask(page:Page,text:string){await expect(page.locator('#agent-query-form [type="submit"]')).toBeEnabled();await page.getByRole('textbox',{name:'공정 데이터에 질문하기'}).fill(text);const accepted=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/agent/requests'&&r.request().method()==='POST',{timeout:30000});await page.locator('#agent-query-form [type="submit"]').click();const response=await accepted;expect([200,202]).toContain(response.status());return response.json() as Promise<AgentRequestView>;}
async function askComplete(page:Page,text:string,kind:keyof typeof kindIntents,count:number){const accepted=await ask(page,text);const result=await terminal(page.request,accepted.requestId);expect(result.status,result.error?.code??'expected completed v1 request').toBe('COMPLETED');await expect(page.locator('.agent-turn')).toHaveCount(count);await expect(page.locator('#agent-query-form [type="submit"]')).toBeEnabled();const view=await workspace(page.request);const turn=view.conversation.turns.at(-1)!;expect(turn.id).toBe(result.turnId);expect(turn.intent).toBe(kindIntents[kind]);expect(turn.answerSnapshot).toMatchObject({implementationId:'v1',schemaVersion:2,kind});return turn;}
async function reset(request:APIRequestContext){const current=await workspace(request);expect((await request.post(`${api}/api/workspace/reset`,{data:{stateToken:current.stateToken}})).status()).toBe(200);}

for(const width of widths)test(`v1 real HTTP answers four tools, clarification and reload at ${width}px`,async({page,request},info)=>{
 await reset(request);const runsResponse=await request.get(`${api}/api/runs`);expect(runsResponse.status()).toBe(200);const runs:RunSummary[]=await runsResponse.json();const usable=runs.filter(r=>r.qualityStatus==='VERIFIED'&&r.convergenceStatus==='CONVERGED'&&r.catalogStatus==='READY');expect(usable.length).toBeGreaterThanOrEqual(2);const a=usable[0];const b=usable.find(r=>r.runVersionId!==a.runVersionId&&(r.metrics.meanIonEnergy!==a.metrics.meanIonEnergy||r.metrics.ionFlux!==a.metrics.ionFlux))??usable[1];
 const errors:string[]=[];const clientAppends:string[]=[];let submitCount=0;page.on('pageerror',error=>errors.push(error.message));page.on('request',req=>{if(req.method()!=='POST')return;const path=new URL(req.url()).pathname;if(path==='/api/workspace/turns')clientAppends.push(path);if(path==='/api/agent/requests')submitCount++;});
 try{
  await page.setViewportSize({width,height:1000});await page.goto('/');await expect(page.locator('.agent-welcome')).toBeVisible();
  const forward=await askComplete(page,`압력 ${a.pressure}, 소스 ${a.sourcePower}, 바이어스 ${a.biasPower} 결과를 보여줘`,'forward_lookup',1);expect(forward.answerSnapshot.result).toMatchObject({resultStatus:'EXACT',selectedRun:{runId:a.runId,runVersionId:a.runVersionId}});
  expect(forward.answerSnapshot.unitAssumptions).toHaveLength(3);await expect(page.locator('.v1-unit-notice')).toContainText('압력 mTorr · 소스 전력 W · 바이어스 전력 W');
  const energy=a.metrics.meanIonEnergy!;const low=Math.max(0,energy-0.1),high=energy+0.1;
  const reverse=await askComplete(page,`Ion Flux는 높게, Mean Ion Energy는 ${low}–${high}에 가깝게 후보를 찾아줘`,'reverse_search',2);
  expect(reverse.answerSnapshot.unitAssumptions).toEqual([{metric:'meanIonEnergy',unit:'eV'}]);
  const searched=reverse.answerSnapshot.result as unknown as {resultStatus:string;commonCandidates:{run:RunSummary}[];goalResults:unknown[]};
  expect(searched.resultStatus).toBe('MATCH');
  expect(searched.goalResults).toEqual([]);
  expect(searched.commonCandidates.map(candidate=>candidate.run.runId)).toEqual(usable.filter(run=>run.metrics.meanIonEnergy!==null&&run.metrics.meanIonEnergy>=low&&run.metrics.meanIonEnergy<=high).sort((x,y)=>y.metrics.ionFlux!-x.metrics.ionFlux!).map(run=>run.runId));
  await expect(page.locator('[data-turn-id="'+reverse.id+'"] .agent-fit-card').first()).toBeVisible();
  const reverseView=page.locator(`[data-turn-id="${reverse.id}"]`);
  await expect(reverseView.getByRole('tab')).toHaveCount(2);
  await expect(reverseView.getByRole('tab',{name:/Ion Flux/})).toHaveCount(0);
  await expect(reverseView.locator('.agent-search-summary')).toContainText('Ion Flux 높은순');
  await expect(reverseView.locator('.agent-search-summary')).not.toContainText('현재 정렬');
  const acceptedCompare=await ask(page,`${a.runId}를 기준으로 ${b.runId}의 평균 이온 에너지와 이온 플럭스를 비교해줘`);
  const selection=await terminal(request,acceptedCompare.requestId);expect(selection.status).toBe('NEEDS_INPUT');expect(selection.pendingInput?.type).toBe('run_selection');
  await expect(page.getByRole('button',{name:'선택한 실험으로 계속'})).toBeDisabled();
  const optionResponse=await request.get(`${api}/api/agent/requests/${acceptedCompare.requestId}/run-options?pendingInputId=${encodeURIComponent(selection.pendingInput!.id)}`);expect(optionResponse.status()).toBe(200);
  const options=(await optionResponse.json()).options as {key:string;ref:{runId:string;runVersionId:string}}[];
  const keyA=options.find(o=>o.ref.runVersionId===a.runVersionId)!.key;const keyB=options.find(o=>o.ref.runVersionId===b.runVersionId)!.key;
  await page.reload();await expect(page.getByRole('checkbox',{name:`${keyA} · ${a.runId} · ${a.runVersionId}`})).toBeVisible();
  // Check actual picker geometry: generic full-width input CSS once squeezed
  // the Run text into a one-character column without overflowing the page.
  const geometry=await page.locator('.v1-picker-option').first().evaluate(el=>{
   const checkbox=el.querySelector('input')!.getBoundingClientRect();const text=el.querySelector('span')!.getBoundingClientRect();const row=el.getBoundingClientRect();
   return {checkboxWidth:checkbox.width,checkboxHeight:checkbox.height,textWidth:text.width,rowWidth:row.width,rowHeight:row.height};
  });
  expect(geometry.checkboxWidth).toBeLessThanOrEqual(24);expect(geometry.checkboxHeight).toBeLessThanOrEqual(24);
  expect(geometry.textWidth).toBeGreaterThan(geometry.rowWidth*.65);expect(geometry.rowHeight).toBeLessThan(180);
  await page.getByRole('checkbox',{name:`${keyA} · ${a.runId} · ${a.runVersionId}`}).check();await page.getByRole('checkbox',{name:`${keyB} · ${b.runId} · ${b.runVersionId}`}).check();
  await page.locator('.v1-run-selection').screenshot({path:info.outputPath(`picker-artificial-${width}.png`)});
  await page.getByLabel('비교 기준 (필수)').selectOption(keyA);const picked=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith(`/${acceptedCompare.requestId}/resume`)&&r.request().method()==='POST');await page.getByRole('button',{name:'선택한 실험으로 계속'}).click();expect((await picked).status()).toBe(200);
  const compared=await terminal(request,acceptedCompare.requestId,1);expect(compared.status,compared.error?.code).toBe('COMPLETED');await expect(page.locator('.agent-turn')).toHaveCount(3);
  const compare=(await workspace(request)).conversation.turns.at(-1)!;expect(compare.answerSnapshot).toMatchObject({schemaVersion:2,kind:'compare_runs',result:{baselineKey:keyA,runs:expect.arrayContaining([{key:keyA,ref:{runId:a.runId,runVersionId:a.runVersionId},conditions:expect.any(Object),metrics:expect.any(Object),quality:expect.any(Object)}])}});
  await page.locator(`[data-turn-id="${compare.id}"] .v1-comparison`).screenshot({path:info.outputPath(`comparison-artificial-${width}.png`)});
  // Reattach saved exact versions; the reason question uses the same comparison tool.
  const current=await workspace(request);expect((await request.put(`${api}/api/workspace/reference`,{data:{stateToken:current.stateToken,activeRun:null,candidateReference:{kind:'후보 집합',runs:compare.answerRunRefs}}})).status()).toBe(200);await page.reload();
  await askComplete(page,'태그한 실험들의 평균 이온 에너지와 이온 플럭스 차이가 나는 가능한 이유를 설명해줘','compare_runs',4);
  const concept=await askComplete(page,'평균 이온 에너지가 뭐야? 이온 에너지랑 다른건가?','generate_answer',5);expect(concept.answerRunRefs).toEqual([]);await expect(page.locator('.v1-general-answer')).toBeVisible();
  // Reload renders stored prose and exact Run versions, without another provider request.
  const completed=await workspace(request);await page.reload();await expect(page.locator('.agent-turn')).toHaveCount(5);expect((await workspace(request)).conversation.turns).toEqual(completed.conversation.turns);expect(submitCount).toBe(5);
  await page.locator(`[data-turn-id="${compare.id}"]`).getByRole('button',{name:'실험 상세'}).first().click();await expect(page.getByRole('dialog')).toBeVisible();expect(await page.getByRole('dialog').evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);await page.keyboard.press('Escape');
  // Missing input persists as a request, and a reply continues that request after reload.
  const pending=await ask(page,`압력 ${a.pressure} mTorr, 소스 ${a.sourcePower} W의 결과를 보여줘`);const awaiting=await terminal(request,pending.requestId);expect(awaiting.status,awaiting.error?.code??'expected clarification').toBe('NEEDS_INPUT');await expect(page.getByRole('heading',{name:'추가 정보가 필요합니다'})).toBeVisible();await page.reload();await expect(page.getByRole('heading',{name:'추가 정보가 필요합니다'})).toBeVisible();await page.locator(`#reply-${pending.requestId}`).fill(`${a.biasPower} W`);const resumed=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith(`/${pending.requestId}/resume`)&&r.request().method()==='POST');await page.getByRole('button',{name:'답변하고 계속'}).click();expect((await resumed).status()).toBe(200);const final=await terminal(request,pending.requestId,1);expect(final.status,final.error?.code??'expected resumed completion').toBe('COMPLETED');await expect(page.locator('.agent-turn')).toHaveCount(6);const last:TurnSnapshot=(await workspace(request)).conversation.turns.at(-1)!;expect(last.id).toBe(final.turnId);expect(last.answerSnapshot.kind).toBe('forward_lookup');expect(final.inputEvents).toHaveLength(1);await page.reload();await expect(page.locator('.agent-turn')).toHaveCount(6);expect(submitCount).toBe(6);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(clientAppends).toEqual([]);expect(errors).toEqual([]);await page.screenshot({path:info.outputPath(`v1-live-artificial-${width}.png`),fullPage:true});await info.attach('v1-live-summary',{body:JSON.stringify({width,apiMocking:false,registeredArtificialRuns:runs.length,operations:Object.keys(kindIntents),completedTurns:6,durableResume:true,exactVersionReload:true,clientAppendCount:clientAppends.length,model:process.env.OPENAI_MODEL??'worker-configured',reasoning:process.env.OPENAI_REASONING_EFFORT??'worker-configured'}),contentType:'application/json'});
 }finally{await reset(request);}
});
