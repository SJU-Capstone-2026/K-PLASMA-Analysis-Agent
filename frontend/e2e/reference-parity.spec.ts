import {expect,test,type APIRequestContext,type Locator,type Page} from '@playwright/test';
import type {FullRun,Pair,RunSummary} from 'agent';
import {createHash} from 'node:crypto';
import {navigate} from './helpers';
const reference=process.env.KPLASMA_PROTOTYPE_URL;
const digest=(value:unknown)=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
test.afterEach(async({request},info)=>{
 if(!reference||info.annotations.some(item=>item.type==='read-only'))return;
 const api=process.env.KPLASMA_E2E_API!;const current=await (await request.get(`${api}/api/workspace`)).json();
 expect((await request.post(`${api}/api/workspace/reset`,{data:{stateToken:current.stateToken}})).status()).toBe(200);
});
async function analysis(page:Page,url:string){await page.clock.setFixedTime(new Date(process.env.KPLASMA_E2E_INSTANT!));await page.goto(url);await navigate(page,'analysis');await expect(page.getByRole('img',{name:'IED 실제 수치 선 그래프'})).toBeVisible();await page.evaluate(()=>document.fonts.ready);}
const legacyLineLimits={ied:161,iad:101,current:121,potential:121,residual:81};
type LineId=keyof typeof legacyLineLimits;
type PlotId=LineId|'iead'|'density';
const analysisPlots={distribution:['iead','ied','iad'],waveforms:['current','potential'],density:['density'],convergence:['residual']} as const;

async function fullRun(request:APIRequestContext,sourcePower:number){
 const api=process.env.KPLASMA_E2E_API!;
 const summaries=await request.get(`${api}/api/runs`);expect(summaries.ok()).toBe(true);
 const runs=await summaries.json() as RunSummary[];
 expect(runs).toHaveLength(150);
 const run=runs.find(item=>item.pressure===6&&item.sourcePower===sourcePower&&item.biasPower===600);
 expect(run).toBeDefined();
 const response=await request.get(`${api}/api/run-versions/${run!.runVersionId}`);expect(response.ok()).toBe(true);
 return await response.json() as FullRun;
}

function outputPoints(run:FullRun,id:LineId):Pair[]{
 if(id==='ied')return run.iedDistribution.map(({energy,intensity})=>[energy,intensity]);
 if(id==='iad')return run.analysis.iad!;
 if(id==='residual')return run.analysis.residualTrace;
 const waveform=run.analysis[id]!;
 expect(waveform.points).toHaveLength(waveform.sourceCount);
 return waveform.points;
}

function expectedLine(points:Pair[],logY:boolean){
 const visible=points.filter(([,y])=>!logY||y>0);
 const ys=visible.map(([,y])=>logY?Math.log10(y):y);
 const first=visible[0][0],last=visible.at(-1)![0];
 const minY=logY?Math.min(...ys):Math.min(0,...ys);
 const maxY=Math.max(...ys);
 const spanY=maxY-minY||1;
 return visible.map(([x],index)=>{
  const svgX=58+602*((x-first)/(last-first||1));
  const svgY=18+218*(1-(ys[index]-minY)/spanY);
  return `${index?'L':'M'}${svgX.toFixed(1)} ${svgY.toFixed(1)}`;
 }).join(' ');
}

async function expectPlot(actual:Locator,original:Locator,run:FullRun,id:PlotId){
 await expect(actual).toBeVisible();
 await expect(original).toBeVisible();
 await expect(actual).toHaveAttribute('viewBox',(await original.getAttribute('viewBox'))!);
 const axisCoordinates=(plot:Locator)=>plot.locator('.analysis-axis').evaluateAll(lines=>lines.map(line=>['x1','y1','x2','y2'].map(axis=>line.getAttribute(axis))));
 expect(await axisCoordinates(actual)).toEqual(await axisCoordinates(original));
 if(id==='iead'||id==='density'){
  let cols:number,rows:number;
  if(id==='iead'){
   const grid=run.analysis.iead!;
   [rows,cols]=[grid.angles.length,grid.energies.length];
   expect([rows,cols]).toEqual(grid.sourceShape);
   expect(grid.values).toHaveLength(cols*rows);
  }else{
   const grid=run.analysis.density!;
   [cols,rows]=grid.sourceShape;
   expect(grid.rows).toHaveLength(cols);
   expect(grid.rows.every(([,distances,values])=>distances.length===rows&&values.length===rows)).toBe(true);
  }
  await expect(original.locator('rect')).toHaveCount(id==='iead'?31*61:41*31);
  const canvas=actual.locator('canvas');
  await expect(canvas).toBeVisible();
  await expect(actual.locator('rect')).toHaveCount(0);
  const backing=await canvas.evaluate((node:HTMLCanvasElement)=>[node.width,node.height]);
  expect(backing[0]).toBeGreaterThanOrEqual(cols);
  expect(backing[1]).toBeGreaterThanOrEqual(rows);
  await expect.poll(()=>canvas.evaluate((node:HTMLCanvasElement)=>{
   const {data}=node.getContext('2d')!.getImageData(Math.floor(node.width/2),0,1,node.height);
   return data.some((channel,index)=>index%4===3&&channel===255);
  })).toBe(true);
  return;
 }
 const points=outputPoints(run,id);
 const actualPath=(await actual.locator('.analysis-line').getAttribute('d'))!;
 const originalPath=(await original.locator('.analysis-line').getAttribute('d'))!;
 const sourceCount=points.filter(([,y])=>id!=='residual'||y>0).length;
 expect(actualPath.match(/[ML]/g)).toHaveLength(sourceCount);
 // Compare the projected full path without including physical values in assertion output.
 expect(digest(actualPath),`${id} original-coordinate projection`).toBe(digest(expectedLine(points,id==='residual')));
 const legacyCount=Math.min(legacyLineLimits[id],points.length);
 if(id==='residual')expect(originalPath.match(/[ML]/g)!.length).toBeLessThanOrEqual(legacyCount);
 else expect(originalPath.match(/[ML]/g)).toHaveLength(legacyCount);
}

for(const width of [390,800,1008,1440])test(`external full-resolution charts and layout at ${width}px`,async({page,context,request},info)=>{
 test.skip(!reference,'Default artificial CI excludes externally supplied actual reference.');
 const analysisRun=await fullRun(request,300),detailRun=await fullRun(request,400);
 await page.setViewportSize({width,height:1000});await analysis(page,'/');const original=await context.newPage();await original.setViewportSize({width,height:1000});await analysis(original,reference!);
 for(const [tab,plots] of Object.entries(analysisPlots)){
  for(const target of [page,original])await target.locator(`[data-action="analysis-tab"][data-tab="${tab}"]`).click();
  const actual=page.locator('.analysis-chart-content svg'),baseline=original.locator('.analysis-chart-content svg');
  await expect(actual).toHaveCount(plots.length);await expect(baseline).toHaveCount(plots.length);
  for(const [index,id] of plots.entries())await expectPlot(actual.nth(index),baseline.nth(index),analysisRun,id);
  for(const selector of ['.analysis-control-panel','.analysis-selection-card','.analysis-kpi-grid','.analysis-detail-panel','.analysis-provenance']){
   const actual=await page.locator(selector).boundingBox(),expected=await original.locator(selector).boundingBox();
   // R18 measured exactly 1/64px source/React layout rounding. Physical/SVG comparisons remain exact.
   for(const key of ['x','y','width','height'] as const)expect(Math.abs(actual![key]-expected![key]),`${selector}.${key}`).toBeLessThanOrEqual(1/64);
  }
  for(const [name,target] of [['react',page],['original',original]] as const)await target.screenshot({path:info.outputPath(`${name}-${tab}-${width}.png`),fullPage:true,animations:'disabled'});
 }
 const sourceScrollWidth=await original.evaluate(()=>document.documentElement.scrollWidth),reactScrollWidth=await page.evaluate(()=>document.documentElement.scrollWidth);
 expect(reactScrollWidth).toBe(sourceScrollWidth);
 await info.attach('layout-boundary',{body:JSON.stringify({width,sourceScrollWidth,reactScrollWidth,coordinateTolerancePx:1/64,svgTolerance:0,inheritedBaselineOverflow:sourceScrollWidth>width}),contentType:'application/json'});
 for(const target of [page,original]){await target.getByLabel('고정 값').selectOption('0');await target.locator('[data-action="analysis-tab"][data-tab="distribution"]').click();await expect(target.getByText('Bias-off Run에는 쉬스 분포 출력이 없습니다')).toBeVisible();}
 for(const target of [page,original]){
  await navigate(target,'agent');await target.locator('#agent-query').fill('Pressure 6 Source 400 Bias 600 결과 보여줘');await target.locator('#agent-query-form [type="submit"]').click();await expect(target.locator('.agent-response')).toHaveCount(1);
  await target.locator('.agent-response [data-action="open-run-detail"]').first().click();await expect(target.locator('.agent-detail-tabs')).toBeVisible();
  await expect(target.getByRole('dialog')).toHaveAttribute('aria-modal','true');await expect(target.getByRole('dialog')).toHaveAttribute('aria-labelledby','run-detail-title');
 }
 for(const tab of ['ied','iad','iead','current','potential','density','residual'] as const){
  for(const target of [page,original]){const button=target.locator(`.agent-detail-tabs [data-tab="${tab}"]`);await button.click();await expect(button).toHaveAttribute('aria-selected','true');}
  await expectPlot(page.locator('.agent-detail-graph svg'),original.locator('.agent-detail-graph svg'),detailRun,tab);
  for(const [name,target] of [['react',page],['original',original]] as const)await target.screenshot({path:info.outputPath(`${name}-detail-${tab}-${width}.png`),fullPage:true,animations:'disabled'});
 }
 // Both implementations close native source-file details on an effective graph-tab change.
 for(const target of [page,original]){await target.locator('.agent-source-files summary').click();await target.locator('.agent-detail-tabs [data-tab="ied"]').click();}
 expect(await page.locator('.agent-source-files').getAttribute('open')).toBeNull();expect(await original.locator('.agent-source-files').getAttribute('open')).toBeNull();
 await info.attach('source-details-parity',{body:JSON.stringify({status:'MATCH',sourceAfterTab:'closed',reactAfterTab:'closed',parityPass:true}),contentType:'application/json'});
 await original.close();
});
test('P-structure-05 contextual higher energy retains mandatory range and actual candidates',async({page,context})=>{
 test.skip(!reference,'Requires actual150 source; synthetic CI cannot establish actual contextual parity.');
 const original=await context.newPage();
 for(const target of [page,original]){
  await target.clock.setFixedTime(new Date(process.env.KPLASMA_E2E_INSTANT!));await target.goto(target===page?'/':reference!);
  await target.locator('#agent-query').fill('Pressure 6 Source 400 Bias 600 결과 보여줘');await target.locator('#agent-query-form [type="submit"]').click();await expect(target.locator('.agent-response')).toHaveCount(1);
  await target.locator('[data-action="continue-with-run"]').first().click();
  await target.locator('#agent-query').fill('Energy를 조금 더 높여줘');await target.locator('#agent-query-form [type="submit"]').click();await expect(target.locator('.agent-response')).toHaveCount(2);
 }
 expect(digest(await page.locator('.agent-response').last().textContent())).toBe(digest(await original.locator('.agent-response').last().textContent()));
 await original.close();
});
test('D1 demo EXP adoption conflict is exercised and explicitly deferred',async({page},info)=>{
 test.skip(!reference,'The preserved demo hard-coded Run IDs require the actual150 reference.');
 await page.goto('/');await expect(page.locator('.agent-welcome')).toBeVisible();
 const rejected=page.waitForResponse(response=>response.url().endsWith('/api/decisions')&&response.request().method()==='POST');
 await page.getByRole('button',{name:'데모 기록 불러오기'}).click();expect((await rejected).status()).toBe(400);
 await expect(page.locator('#toast-region')).toContainText('EXP requires exactly one adoption');
 expect(await (await page.request.get(`${process.env.KPLASMA_E2E_API}/api/decisions`)).json()).toEqual([]);
 await info.attach('D1-deferred',{body:JSON.stringify({status:'DEFERRED_KNOWN_CONFLICT',originalDemoEXP:4,ordinaryExactlyOneAdoptionPreserved:true,demoPersisted:0,httpStatus:400,parityPass:false}),contentType:'application/json'});
});

for(const width of [390,800,1008,1440])test(`read-only actual source disclosure graph parity at ${width}px`,async({page,context,request},info)=>{
 test.skip(!reference,'Requires externally supplied actual prototype and retained API.');
 info.annotations.push({type:'read-only',description:'Immutable-version harness; no workspace writes or reset.'});
 const api=process.env.KPLASMA_E2E_API!;const before=await (await request.get(`${api}/api/workspace`)).json();
 const run=await fullRun(request,400);
 await page.setViewportSize({width,height:1000});await page.clock.setFixedTime(new Date(process.env.KPLASMA_E2E_INSTANT!));
 await page.goto(`/src/features/catalog/version.integration.harness.html?${new URLSearchParams({runId:run.runId,runVersionId:run.runVersionId})}`);
 await expect(page.locator('.agent-detail-tabs')).toBeVisible();
 const original=await context.newPage();await original.setViewportSize({width,height:1000});await original.clock.setFixedTime(new Date(process.env.KPLASMA_E2E_INSTANT!));await original.goto(reference!);
 await original.locator('#agent-query').fill('Pressure 6 Source 400 Bias 600 결과 보여줘');await original.locator('#agent-query-form [type="submit"]').click();await expect(original.locator('.agent-response')).toHaveCount(1);
 await original.locator('.agent-response [data-action="open-run-detail"]').first().click();await expect(original.locator('.agent-detail-tabs')).toBeVisible();
 for(const target of [page,original]){
  await target.evaluate(()=>document.fonts.ready);await target.locator('.agent-detail-tabs [data-tab="ied"]').click();
  await target.locator('.agent-source-files summary').click();await expect(target.locator('.agent-source-files')).toHaveAttribute('open','');
  await target.locator('.agent-detail-tabs [data-tab="ied"]').click();await expect(target.locator('.agent-source-files')).not.toHaveAttribute('open');
  await target.locator('.agent-source-files summary').click();await expect(target.locator('.agent-source-files')).toHaveAttribute('open','');
  await target.locator('.agent-detail-tabs [data-tab="iad"]').click();await expect(target.locator('.agent-source-files')).not.toHaveAttribute('open');
  await expect(target.locator('.agent-detail-tabs [data-tab="iad"]')).toHaveAttribute('aria-selected','true');
 }
 await expectPlot(page.locator('.agent-detail-graph svg'),original.locator('.agent-detail-graph svg'),run,'iad');
 for(const [name,target] of [['react',page],['original',original]] as const)await target.locator('.agent-run-detail').screenshot({path:info.outputPath(`${name}-disclosure-${width}.png`),animations:'disabled'});
 await info.attach('source-details-parity',{body:JSON.stringify({width,status:'MATCH',sourceAfterTab:'closed',reactAfterTab:'closed',sameTabAfterClick:'closed',differentTabAfterClick:'closed',fullResolutionGraphVerified:true,workspaceWrites:0,parityPass:true}),contentType:'application/json'});
 expect(await (await request.get(`${api}/api/workspace`)).json()).toEqual(before);await original.close();
});
