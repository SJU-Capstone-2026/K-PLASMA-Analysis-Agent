import {expect,test,type Page,type APIRequestContext} from '@playwright/test';
import type {BatchView,CatalogView,FullRun,RunSummary,WorkspaceView} from 'agent';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';

// These tests require explicitly started actual APIs; only workspace/decision routes are test-only.
const isolated='http://127.0.0.1:18089',actual150='http://127.0.0.1:18087';
const evidence=resolve('../backend/.runtime/task-11-logs/integration-browser');
const fixtures=resolve('../backend/.runtime/task-11-fixtures');
let originalVersion='',newVersion='';
async function workspaceRoutes(page:Page,references:RunSummary[]=[]){
 let workspace:WorkspaceView={stateToken:{workspaceEpoch:0,conversationEpoch:0,revision:0},conversation:{version:1,activeRun:null,turns:[]},candidateReference:references.length?{kind:'후보 집합',runs:references.map(({runId,runVersionId})=>({runId,runVersionId}))}:null};
 await page.route('**/api/workspace',route=>route.fulfill({json:workspace}));await page.route('**/api/decisions',route=>route.fulfill({json:[]}));
 await page.route('**/api/workspace/reference',async route=>{const body=route.request().postDataJSON();workspace={...workspace,stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1},candidateReference:body.candidateReference,conversation:{...workspace.conversation,activeRun:body.activeRun}};await route.fulfill({json:workspace});});
 return ()=>workspace;
}
async function navigate(page:Page,view:string){if(page.viewportSize()!.width<760)await page.getByRole('button',{name:'메뉴 열기'}).click();if(['catalog','flow'].includes(view)&&await page.locator('.nav-tools').getAttribute('open')===null)await page.locator('.nav-tools summary').click();await page.locator(`.nav-stack [data-view="${view}"]`).click();}
async function waitBatch(page:Page,select:()=>Promise<void>):Promise<BatchView>{
 const response=page.waitForResponse(r=>r.url().endsWith('/api/import-batches')&&r.request().method()==='POST');await select();const accepted=await response;expect(accepted.status()).toBe(202);const batch=await accepted.json() as BatchView;
 await expect.poll(async()=>{const value=await page.request.get(`${isolated}/api/import-batches/${batch.batchId}`);return (await value.json() as BatchView).status;}).toMatch(/^(SUCCESS|PARTIAL_SUCCESS|FAILED)$/);
 const result=await page.request.get(`${isolated}/api/import-batches/${batch.batchId}`);await expect(page.locator('button').filter({hasText:/^ZIP 선택$/})).toBeEnabled();return result.json();
}
async function latest(api:APIRequestContext):Promise<RunSummary[]>{return (await api.get(`${isolated}/api/runs`)).json();}
async function prepare(){
 // Read the existing artificial Java fixture, never external experimental originals.
 const source=await readFile(resolve('../backend/src/test/java/com/kplasma/analysisagent/ingestion/SyntheticRunFiles.java'),'utf8');
 const blocks=[...source.matchAll(/return """\n([\s\S]*?)\n\s*"""/g)].map(match=>match[1].split('\n').map(line=>line.replace(/^ {12}/,'')).join('\n')+'\n');
 const replace=(value:string,args:string[])=>{let index=0;return value.replace(/%s/g,()=>args[index++]);};
 const ini=replace(blocks[0],['0','0','\u0001']);const solver=replace(blocks[1],['OFF','','']);const residual=blocks[2];
 async function runTree(root:string,mode:'good'|'missing'|'corrupt',changed=false){await mkdir(root,{recursive:true});const files:Record<string,string>={'0d_setting.ini':ini+`# synthetic ${changed?'changed':'base'}\n`};if(mode!=='missing'){files['0d_result/log/solver.log']=mode==='corrupt'?solver.replace('12.3456789','invalid'):changed?solver.replace('12.3456789','13.3456789'):solver;files['0d_result/log/residual.log']=residual;files['0d_result/log/output.log']='INFO: Finished!\n';}files['notes.txt']='Artificial integration lineage, no physical source\n';for(const [path,value] of Object.entries(files)){await mkdir(resolve(root,path,'..'),{recursive:true});await writeFile(resolve(root,path),value);}}
 await runTree(resolve(fixtures,'folder/good'),'good');await runTree(resolve(fixtures,'folder/missing'),'missing');await runTree(resolve(fixtures,'corrupt'),'corrupt');await runTree(resolve(fixtures,'changed'),'good',true);
 execFileSync('python3',['-c','import pathlib,sys,zipfile\nr=pathlib.Path(sys.argv[1])\nwith zipfile.ZipFile(sys.argv[2],"w") as z:\n for p in sorted(r.rglob("*")):\n  if p.is_file():z.write(p,p.relative_to(r).as_posix())',resolve(fixtures,'folder/good'),resolve(fixtures,'equivalent.zip')]);
 await mkdir(evidence,{recursive:true});
}
test.describe.serial('actual isolated catalog imports',()=>{
 test.beforeAll(prepare);
 test('actual folder partial success, complete Run inventory and postupload navigation use new data',async({page})=>{
  await workspaceRoutes(page);await page.goto('http://127.0.0.1:5189');await navigate(page,'catalog');
  const batch=await waitBatch(page,()=>page.getByLabel('폴더 선택').setInputFiles(resolve(fixtures,'folder')));expect(batch.status).toBe('PARTIAL_SUCCESS');expect(batch.jobs.map(job=>job.status).sort()).toEqual(['INCOMPLETE','READY']);const good=batch.jobs.find(job=>job.status==='READY')!;originalVersion=good.runVersionId!;
  await expect(page.getByRole('button',{name:good.runId!,exact:true})).toBeVisible();await expect(page.getByText('일부 완료',{exact:true})).toBeVisible();await page.getByRole('button',{name:good.runId!,exact:true}).click();await expect(page.getByText('folder/good/notes.txt',{exact:true})).toBeVisible();
  const inventory=await (await page.request.get(`${isolated}/api/import-jobs/${good.jobId}/files`)).json();expect(inventory).toHaveLength(5);expect(inventory.every((file:{path:string})=>file.path.startsWith('folder/good/'))).toBe(true);expect(inventory.some((file:{path:string})=>file.path.endsWith('output.log'))).toBe(true);
  const failed=batch.jobs.find(job=>job.status==='INCOMPLETE')!;await page.getByRole('button',{name:failed.jobId,exact:true}).click();await expect(page.getByText('분석 제외 상태',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Agent에서 자세히 보기'})).toHaveCount(0);
  await page.getByLabel('파싱 상태').selectOption('INCOMPLETE');await page.getByRole('button',{name:'적용',exact:true}).click();await navigate(page,'flow');await navigate(page,'catalog');await expect(page.getByLabel('파싱 상태')).toHaveValue('INCOMPLETE');await expect(page.locator('.catalog-detail h2')).toHaveText(failed.jobId);
  await navigate(page,'analysis');await expect(page.locator('.analysis-run-title h2')).toHaveText(good.runId!);await expect(page.getByText('Bias-off 스칼라 결과')).toBeVisible();
  await writeFile(resolve(evidence,'isolated-folder-summary.json'),JSON.stringify({status:batch.status,jobStatuses:batch.jobs.map(job=>job.status),inventoryCount:inventory.length,freshAnalysis:true}));
 });
 test('actual equivalent ZIP is duplicate, corrupt folder fails, changed original publishes new immutable version',async({page})=>{
  await workspaceRoutes(page);await page.goto('http://127.0.0.1:5189');await navigate(page,'catalog');
  const duplicate=await waitBatch(page,()=>page.getByLabel('ZIP 선택').setInputFiles(resolve(fixtures,'equivalent.zip')));expect(duplicate.jobs[0].status).toBe('DUPLICATE');expect(duplicate.jobs[0].runVersionId).toBe(originalVersion);
  const corrupt=await waitBatch(page,()=>page.getByLabel('폴더 선택').setInputFiles(resolve(fixtures,'corrupt')));expect(corrupt.status).toBe('FAILED');expect(corrupt.jobs[0].status).toBe('PARSE_FAILED');expect(corrupt.jobs[0].errors.length).toBeGreaterThan(0);expect((await latest(page.request))[0].runVersionId).toBe(originalVersion);
  const changed=await waitBatch(page,()=>page.getByLabel('폴더 선택').setInputFiles(resolve(fixtures,'changed')));newVersion=changed.jobs[0].runVersionId!;expect(changed.jobs[0].status).toBe('READY');expect(newVersion).not.toBe(originalVersion);
  if(!originalVersion){const catalog=await (await page.request.get(`${isolated}/api/catalog`)).json() as CatalogView;for(const job of catalog.jobs){if(!job.runVersionId)continue;const version=await (await page.request.get(`${isolated}/api/run-versions/${job.runVersionId}`)).json() as FullRun;if(version.metrics.meanIonEnergy===12.3456789){originalVersion=version.runVersionId;break;}}}expect(originalVersion).not.toBe('');
  const old=await (await page.request.get(`${isolated}/api/run-versions/${originalVersion}`)).json() as FullRun;const current=await (await page.request.get(`${isolated}/api/run-versions/${newVersion}`)).json() as FullRun;expect(current.metrics.meanIonEnergy).not.toBe(old.metrics.meanIonEnergy);
  await navigate(page,'analysis');await expect(page.locator('.analysis-run-title h2')).toHaveText(current.runId);await expect(page.locator('.analysis-kpi-grid article').first()).toBeVisible();
  await writeFile(resolve(evidence,'isolated-version-summary.json'),JSON.stringify({duplicate:true,corrupt:'PARSE_FAILED',priorSuccessRetained:true,changedVersion:true,oldVersionStable:true}));
 });
 test('actual explicit reprocessing preserves source lineage and creates new version with one replay attempt',async({page})=>{
  await workspaceRoutes(page);await page.goto('http://127.0.0.1:5189');await navigate(page,'catalog');const runs=await latest(page.request);await page.locator(`[data-action="catalog-select"][data-run-id="${runs[0].runId}"]`).click();
  const response=page.waitForResponse(r=>r.url().endsWith('/reprocess')&&r.request().method()==='POST');await page.getByRole('button',{name:'다시 처리'}).click();const result=await response;expect(result.status()).toBe(202);const accepted=await result.json() as BatchView;const key=result.request().headers()['idempotency-key'];const originalJob=result.request().url().split('/').at(-2)!;
  const replay=await page.request.post(`${isolated}/api/import-jobs/${originalJob}/reprocess`,{headers:{'Idempotency-Key':key}});expect((await replay.json() as BatchView).batchId).toBe(accepted.batchId);
  await expect.poll(async()=>(await (await page.request.get(`${isolated}/api/import-batches/${accepted.batchId}`)).json() as BatchView).status).toBe('SUCCESS');await expect(page.locator('button').filter({hasText:/^ZIP 선택$/})).toBeEnabled();
  const processed=await (await page.request.get(`${isolated}/api/import-batches/${accepted.batchId}`)).json() as BatchView;expect(processed.jobs[0].status).toBe('READY');expect(processed.jobs[0].runVersionId).not.toBe(newVersion);const before=await (await page.request.get(`${isolated}/api/import-jobs/${originalJob}/files`)).json();const after=await (await page.request.get(`${isolated}/api/import-jobs/${processed.jobs[0].jobId}/files`)).json();expect(after).toEqual(before);
  await writeFile(resolve(evidence,'isolated-reprocess-summary.json'),JSON.stringify({status:processed.status,newVersion:true,sameInventory:true,idempotentReplay:true}));
 });
 test('actual immutable old version remains the rendered modal source after reprocessing',async({page})=>{
  if(!originalVersion){const catalog=await (await page.request.get(`${isolated}/api/catalog`)).json() as CatalogView;for(const job of catalog.jobs){if(!job.runVersionId)continue;const version=await (await page.request.get(`${isolated}/api/run-versions/${job.runVersionId}`)).json() as FullRun;if(version.metrics.meanIonEnergy===12.3456789){originalVersion=version.runVersionId;break;}}}expect(originalVersion).not.toBe('');
  const old=await (await page.request.get(`${isolated}/api/run-versions/${originalVersion}`)).json() as FullRun;
  await page.goto(`http://127.0.0.1:5189/src/features/catalog/version.integration.harness.html?${new URLSearchParams({runId:old.runId,runVersionId:originalVersion})}`);
  await expect(page.locator('.agent-detail-metrics')).toContainText(`${Math.round(old.metrics.meanIonEnergy)} eV`);
  const current=(await latest(page.request))[0];expect(current.runVersionId).not.toBe(originalVersion);
  await expect(page.locator('[data-action="run-detail-tab"][data-tab="ied"]')).toBeDisabled();await expect(page.locator('[data-action="run-detail-tab"][data-tab="residual"]')).toBeEnabled();
  await writeFile(resolve(evidence,'isolated-old-version-summary.json'),JSON.stringify({explicitOldVersion:true,currentVersionDifferent:true,oldMetricsRendered:true}));
 });
});
async function retainedRuns(page:Page){const response=await page.request.get(`${actual150}/api/runs`);expect(response.status()).toBe(200);const runs=await response.json() as RunSummary[];expect(runs).toHaveLength(150);expect(runs.filter(run=>run.biasPower>0)).toHaveLength(125);expect(runs.filter(run=>run.analysis.strictConvergence)).toHaveLength(6);return runs;}
for(const width of [390,800,1008,1440]){
 test(`actual150 Run API graphs at ${width}px`,async({page},testInfo)=>{
  const runs=await retainedRuns(page);await workspaceRoutes(page);await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:5187');await navigate(page,'analysis');await expect(page.getByRole('img',{name:'IED 실제 수치 선 그래프'})).toBeVisible();
  for(const id of ['distribution','waveforms','density','convergence']){await page.locator(`[data-action="analysis-tab"][data-tab="${id}"]`).click();const graphs=page.locator('.analysis-chart-content svg');expect(await graphs.count()).toBeGreaterThan(0);for(let index=0;index<await graphs.count();index++)await expect(graphs.nth(index)).toBeVisible();}
  await page.getByLabel('고정 값').selectOption('0');await page.locator('[data-action="analysis-tab"][data-tab="distribution"]').click();await expect(page.getByText('Bias-off Run에는 쉬스 분포 출력이 없습니다')).toBeVisible();
  const on=runs.find(run=>run.biasPower>0)!,off=runs.find(run=>run.biasPower===0)!;
  await page.goto(`http://127.0.0.1:5187/src/features/catalog/version.integration.harness.html?${new URLSearchParams({runId:on.runId,runVersionId:on.runVersionId})}`);
  const tabs=page.getByRole('tab');await expect(tabs).toHaveCount(7);for(let index=0;index<7;index++){await tabs.nth(index).click();await expect(page.locator('.agent-detail-graph svg')).toBeVisible();}await page.screenshot({path:testInfo.outputPath(`actual-run-detail-${width}.png`),fullPage:true});
  await page.goto(`http://127.0.0.1:5187/src/features/catalog/version.integration.harness.html?${new URLSearchParams({runId:off.runId,runVersionId:off.runVersionId})}`);
  await expect(page.locator('[data-action="run-detail-tab"][data-tab="ied"]')).toBeDisabled();await expect(page.locator('[data-action="run-detail-tab"][data-tab="residual"]')).toBeEnabled();
  await writeFile(testInfo.outputPath('summary.json'),JSON.stringify({width,runCount:150,biasOn:125,biasOff:25,strictTrue:6,actualRunEndpoints:true,analysisTabs:4,modalTabs:7,workspaceRoutes:'test-only'}));
 });
 test(`actual150 catalog R1 reference at ${width}px`,async({page},testInfo)=>{
  const runs=await retainedRuns(page);const references=runs.filter(run=>run.biasPower>0).slice(0,2),off=runs.find(run=>run.biasPower===0&&run.pressure===6&&run.sourcePower===300)!;const state=await workspaceRoutes(page,references);await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:5187');await navigate(page,'catalog');
  await expect(page.locator('[role="alert"]')).toHaveCount(0);await page.getByLabel('Run 또는 파일 검색').fill(off.runId);await page.getByRole('button',{name:'적용',exact:true}).click();await page.locator(`[data-action="catalog-select"][data-run-id="${off.runId}"]`).click();await expect(page.getByRole('button',{name:'Agent에서 자세히 보기'})).toBeVisible();await expect(page.locator('.catalog-detail .detail-files').first()).toContainText('원본 파일 3개');
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await page.screenshot({path:testInfo.outputPath(`actual-catalog-${width}.png`),fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)).toBe(false);
  await page.getByRole('button',{name:'Agent에서 자세히 보기'}).click();await expect(page.locator('#current-view-label')).toHaveText('분석 Agent');expect(state().conversation.activeRun).toEqual({runId:off.runId,runVersionId:off.runVersionId});expect(state().candidateReference?.runs).toEqual(references.map(({runId,runVersionId})=>({runId,runVersionId})));
  await writeFile(testInfo.outputPath('summary.json'),JSON.stringify({width,runCount:150,actualCatalog:true,displaySourceFiles:3,workspaceRoutes:'test-only',referencePreserved:true}));
 });
}
