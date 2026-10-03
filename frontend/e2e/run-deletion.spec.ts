import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {expect,test,type APIRequestContext,type Page} from '@playwright/test';
import type {RunSummary} from 'agent';
import {navigate} from './helpers';

const api=process.env.KPLASMA_E2E_API;
if(!api)throw new Error('Use npm run test:e2e to provision an isolated PostgreSQL/backend.');
const source=process.env.KPLASMA_E2E_SYNTHETIC_FOLDER;
test.beforeEach(()=>test.skip(process.env.KPLASMA_E2E_REFERENCE==='true'||!source,'Deletion is tested only with isolated artificial data.'));

async function runs(request:APIRequestContext):Promise<RunSummary[]>{
 const response=await request.get(`${api}/api/runs`);expect(response.status()).toBe(200);return response.json();
}
async function resetRecords(request:APIRequestContext){
 const current=await (await request.get(`${api}/api/workspace`)).json();
 expect((await request.post(`${api}/api/workspace/reset`,{data:{stateToken:current.stateToken}})).status()).toBe(200);
}
async function restoreArtificialRuns(page:Page){
 await page.goto('/');await navigate(page,'catalog');
 const accepted=page.waitForResponse(response=>response.url().endsWith('/api/import-batches')&&response.request().method()==='POST');
 await page.getByLabel('폴더 선택').setInputFiles(source!);
 const response=await accepted;expect(response.status()).toBe(202);const batch=await response.json();
 await expect.poll(async()=>(await (await page.request.get(`${api}/api/import-batches/${batch.batchId}`)).json()).status).toBe('SUCCESS');
 await expect.poll(async()=>(await runs(page.request)).length).toBe(3);
}

for(const width of [390,800,1008,1440])test(`registered Run deletion confirms exact scope and keeps external files at ${width}px`,async({page,request},info)=>{
 const before=await runs(request);expect(before).toHaveLength(3);
 const first=before[0];const originalPath=join(source!,'artificial-2/0d_setting.ini');
 const original=await readFile(originalPath,'utf8');
 await resetRecords(request);
 try{
  await page.setViewportSize({width,height:1000});await page.goto('/');await navigate(page,'catalog');
  await page.locator(`[data-action="catalog-select"][data-run-id="${first.runId}"]`).click();
  const openDelete=page.getByRole('button',{name:'선택 Run 삭제',exact:true});await openDelete.click();
  const dialog=page.getByRole('alertdialog');await expect(dialog).toContainText('등록 Run 1개');
  const bounds=await dialog.boundingBox();expect(bounds).not.toBeNull();expect(bounds!.x).toBeGreaterThanOrEqual(0);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(width);
  await expect(dialog.getByRole('button',{name:'취소',exact:true})).toBeFocused();
  await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(openDelete).toBeFocused();
  expect(await runs(request)).toEqual(before);
  await openDelete.click();
  const deleted=page.waitForResponse(response=>response.url().endsWith('/api/runs/delete')&&response.request().method()==='POST');
  await dialog.getByRole('button',{name:'삭제',exact:true}).click();
  const result=await deleted;expect(result.status()).toBe(200);expect(await result.json()).toEqual({deletedRunIds:[first.runId],cleanupPending:false});
  await expect(dialog).toHaveCount(0);await expect(page.locator(`[data-action="catalog-select"][data-run-id="${first.runId}"]`)).toHaveCount(0);
  expect((await request.get(`${api}/api/run-versions/${first.runVersionId}`)).status()).toBe(404);
  expect((await runs(request)).map(run=>run.runId)).toEqual(before.slice(1).map(run=>run.runId));
  // Filtering must not silently narrow the scope of the explicit "all" action.
  await page.getByRole('textbox',{name:'Run 또는 파일 검색'}).fill(before[1].runId);
  await page.getByRole('button',{name:'적용',exact:true}).click();
  await expect(page.locator('[data-action="catalog-select"]')).toHaveCount(1);
  await page.getByRole('button',{name:'전체 Run 삭제',exact:true}).click();
  await expect(dialog).toContainText('등록 Run 2개');
  await page.screenshot({path:info.outputPath(`delete-confirm-${width}.png`),fullPage:true});
  await dialog.getByRole('button',{name:'삭제',exact:true}).click();await expect(dialog).toHaveCount(0);
  await expect.poll(async()=>runs(request)).toEqual([]);
  await page.reload();await navigate(page,'catalog');await expect(page.locator('[data-action="catalog-select"]')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'전체 Run 삭제',exact:true})).toBeDisabled();
  expect(await readFile(originalPath,'utf8')).toBe(original);
  const catalog=await (await request.get(`${api}/api/catalog`)).json();expect(catalog.runs).toEqual([]);expect(catalog.jobs).toEqual([]);
 }finally{await resetRecords(request);await restoreArtificialRuns(page);}
});

test('a saved decision blocks both selected and all Run deletion without changing records',async({page,request})=>{
 await resetRecords(request);const before=await runs(request);
 try{
  await page.goto('/');await navigate(page,'analysis');await expect(page.locator('.analysis-run-title h2')).toBeVisible();
  const runId=(await page.locator('.analysis-run-title h2').textContent())!;
  await page.getByRole('button',{name:'실험 기록',exact:true}).click();
  await page.getByRole('radio',{name:/보류/}).check();
  await page.getByRole('textbox',{name:/판단 근거 코멘트/}).fill('Synthetic deletion reference protection');
  await page.getByRole('button',{name:'코멘트와 결정 저장'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  const records=await (await request.get(`${api}/api/decisions`)).json();expect(records).toHaveLength(1);
  await page.setViewportSize({width:390,height:420});
  await navigate(page,'catalog');await page.locator(`[data-action="catalog-select"][data-run-id="${runId}"]`).click();
  for(const action of ['선택 Run 삭제','전체 Run 삭제']){
   await page.getByRole('button',{name:action,exact:true}).click();
   const rejected=page.waitForResponse(response=>response.url().endsWith('/api/runs/delete')&&response.request().method()==='POST');
   await page.getByRole('alertdialog').getByRole('button',{name:'삭제',exact:true}).click();
   const response=await rejected;expect(response.status()).toBe(409);expect((await response.json()).code).toBe('RUN_IN_USE');
   await expect(page.getByRole('alertdialog')).toContainText(runId);
   // A refusal can list many referenced Runs. The message must scroll inside the
   // dialog instead of putting its cancel action outside a short viewport.
   const bounds=await page.getByRole('alertdialog').boundingBox();
   expect(bounds!.y).toBeGreaterThanOrEqual(0);expect(bounds!.y+bounds!.height).toBeLessThanOrEqual(420);
   await page.getByRole('alertdialog').getByRole('button',{name:'취소',exact:true}).click();
   expect(await runs(request)).toEqual(before);expect(await (await request.get(`${api}/api/decisions`)).json()).toEqual(records);
  }
 }finally{await resetRecords(request);}
});
