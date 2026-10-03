import {expect,test,type Page} from '@playwright/test';
import {toRunSummary,type JobView} from 'agent';
import {fixtureRuns} from '../../test/runs';
const jobs:JobView[]=fixtureRuns.map((run,index)=>({jobId:`synthetic-job-${index}`,runId:run.runId,runVersionId:run.runVersionId,status:'READY',reason:null,errors:[]}));
jobs.push({jobId:'failed-job',runId:'SYNTHETIC-BROKEN',runVersionId:null,status:'PARSE_FAILED',reason:'손상된 synthetic 파일',errors:[]});
async function navigate(page:Page,view:string){if(page.viewportSize()!.width<760)await page.getByRole('button',{name:'메뉴 열기'}).click();if(['catalog','flow'].includes(view)&&await page.locator('.nav-tools').getAttribute('open')===null)await page.locator('.nav-tools summary').click();await page.locator(`.nav-stack [data-view="${view}"]`).click();}
for(const width of [390,800,1008,1440])test(`catalog uploads, filters, navigation and layout at ${width}px`,async({page,context},testInfo)=>{
 await page.setViewportSize({width,height:1000});
 await page.route('**/api/workspace',route=>route.fulfill({json:{stateToken:{workspaceEpoch:0,conversationEpoch:0,revision:0},conversation:{version:1,activeRun:null,turns:[]},candidateReference:null}}));
 await page.route('**/api/decisions',route=>route.fulfill({json:[]}));
 await page.route('**/api/catalog',route=>route.fulfill({json:{runs:fixtureRuns.map(toRunSummary),jobs,sourceFilesByVersion:Object.fromEntries(fixtureRuns.map(run=>[run.runVersionId,run.sourceFiles]))}}));
 await page.route('**/api/runs',route=>route.fulfill({json:fixtureRuns.map(toRunSummary)}));
 await page.route('**/api/run-versions/*',route=>route.fulfill({json:fixtureRuns.find(run=>route.request().url().endsWith(run.runVersionId))}));
 await page.route('**/api/import-jobs/*/files',route=>route.fulfill({json:[{path:'wrapper/nested/synthetic.dat',kind:'DAT',size:4,sha256:'synthetic'}]}));
 await page.route('**/api/import-batches',async route=>{expect(route.request().method()).toBe('POST');expect(route.request().headers()['idempotency-key']).toBeTruthy();const payload=route.request().postData()!;expect(payload).toContain('name="archive"');expect(payload).toContain('synthetic.zip');await route.fulfill({status:202,json:{batchId:'batch',status:'PARTIAL_SUCCESS',receivedBytes:4,totalBytes:4,processedRuns:2,totalRuns:2,jobs:[jobs[0],jobs.at(-1)]}});});
 await page.goto('/src/features/catalog/browser-harness.html');await navigate(page,'catalog');
 await expect(page.getByRole('button',{name:fixtureRuns[0].runId,exact:true})).toBeVisible();
 if(process.env.KPLASMA_PROTOTYPE_URL){
  const original=await context.newPage();await original.setViewportSize({width,height:1000});
  await original.route('**/assets/analysis-data.js',route=>route.fulfill({contentType:'text/javascript',body:`window.KPlasmaAnalysisData=${JSON.stringify({meta:{actualRunCount:150},runs:fixtureRuns})};`}));
  await original.route('**/assets/mock-data.js',async route=>{const response=await route.fetch();await route.fulfill({response,body:`${await response.text()}\nwindow.KPlasmaData.runs=${JSON.stringify(fixtureRuns)};`});});
  await original.goto(process.env.KPLASMA_PROTOTYPE_URL);await navigate(original,'catalog');
  for(const selector of ['.catalog-summary','.catalog-layout','.catalog-table-panel','.catalog-detail','.parsing-lab','.catalog-toolbar']){const actual=await page.locator(selector).boundingBox(),expected=await original.locator(selector).boundingBox();expect(actual!.width).toBeCloseTo(expected!.width,0);expect(actual!.x).toBeCloseTo(expected!.x,0);}
  for(const selector of ['.catalog-layout','.parsing-lab'])expect(await page.locator(selector).evaluate(element=>Array.from(element.children).map(child=>child.className))).toEqual(await original.locator(selector).evaluate(element=>Array.from(element.children).map(child=>child.className)));
  await original.screenshot({path:testInfo.outputPath(`original-catalog-${width}.png`),fullPage:true});await original.close();
 }
 await page.getByRole('button',{name:fixtureRuns[0].runId,exact:true}).focus();await page.keyboard.press('Enter');await expect(page.getByRole('button',{name:'Agent에서 자세히 보기'})).toBeVisible();await expect(page.getByText('wrapper/nested/synthetic.dat')).toBeVisible();
 await page.getByLabel('Run 또는 파일 검색').fill('SYNTHETIC.DAT');await page.getByRole('button',{name:'적용',exact:true}).click();await expect(page.locator('.catalog-table tbody tr')).toHaveCount(4);
 await navigate(page,'flow');await navigate(page,'catalog');await expect(page.getByLabel('Run 또는 파일 검색')).toHaveValue('SYNTHETIC.DAT');await expect(page.locator('.catalog-detail h2')).toHaveText(fixtureRuns[0].runId);
 await page.getByLabel('ZIP 선택').setInputFiles({name:'synthetic.zip',mimeType:'application/zip',buffer:Buffer.from('test archive')});await expect(page.getByText('일부 완료',{exact:true})).toBeVisible();
 await page.getByLabel('Run 또는 파일 검색').fill('');await page.getByRole('button',{name:'적용',exact:true}).click();await page.getByRole('button',{name:'SYNTHETIC-BROKEN',exact:true}).click();await expect(page.getByText('분석 제외 상태',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Agent에서 자세히 보기'})).toHaveCount(0);await expect(page.getByRole('button',{name:'다시 처리'})).toBeVisible();
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);expect(overflow).toBe(false);
 for(const selector of ['.catalog-summary','.catalog-layout','.parsing-lab','.catalog-toolbar']){const box=await page.locator(selector).boundingBox();expect(box!.width).toBeGreaterThan(0);expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(width+1);}
 await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await page.screenshot({path:testInfo.outputPath(`catalog-${width}.png`),fullPage:true});
});
