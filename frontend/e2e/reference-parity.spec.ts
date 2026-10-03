import {expect,test,type Page} from '@playwright/test';
import {createHash} from 'node:crypto';
import {navigate} from './helpers';
const reference=process.env.KPLASMA_PROTOTYPE_URL;
const digest=(value:unknown)=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
test.afterEach(async({request})=>{
 if(!reference)return;
 const api=process.env.KPLASMA_E2E_API!;const current=await (await request.get(`${api}/api/workspace`)).json();
 expect((await request.post(`${api}/api/workspace/reset`,{data:{stateToken:current.stateToken}})).status()).toBe(200);
});
async function analysis(page:Page,url:string){await page.clock.setFixedTime(new Date(process.env.KPLASMA_E2E_INSTANT!));await page.goto(url);await navigate(page,'analysis');await expect(page.getByRole('img',{name:'IED 실제 수치 선 그래프'})).toBeVisible();await page.evaluate(()=>document.fonts.ready);}
async function graphs(page:Page,selector='.analysis-chart-content svg'){return page.locator(selector).evaluateAll(elements=>elements.map(svg=>{function tree(node:Element):unknown{return {tag:node.tagName,attrs:Object.fromEntries([...node.attributes].map(attr=>[attr.name,attr.value]).sort()),text:node.children.length?null:node.textContent,children:[...node.children].map(tree)};}return tree(svg);}));}
for(const width of [390,800,1008,1440])test(`external actual SVG coordinates and layout at ${width}px`,async({page,context},info)=>{
 test.skip(!reference,'Default artificial CI excludes externally supplied actual reference.');
 await page.setViewportSize({width,height:1000});await analysis(page,'/');const original=await context.newPage();await original.setViewportSize({width,height:1000});await analysis(original,reference!);
 for(const tab of ['distribution','waveforms','density','convergence']){
  for(const target of [page,original])await target.locator(`[data-action="analysis-tab"][data-tab="${tab}"]`).click();
  expect(digest(await graphs(page))).toBe(digest(await graphs(original)));
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
 for(const tab of ['ied','iad','iead','current','potential','density','residual']){
  for(const target of [page,original]){const button=target.locator(`.agent-detail-tabs [data-tab="${tab}"]`);await button.click();await expect(button).toHaveAttribute('aria-selected','true');}
  expect(digest(await graphs(page,'.agent-detail-graph svg')),`${width}px ${tab}`).toBe(digest(await graphs(original,'.agent-detail-graph svg')));
  for(const [name,target] of [['react',page],['original',original]] as const)await target.screenshot({path:info.outputPath(`${name}-detail-${tab}-${width}.png`),fullPage:true,animations:'disabled'});
 }
 // Existing reviewed Minor: native source-file details survives a React tab change while original rerenders closed.
 for(const target of [page,original]){await target.locator('.agent-source-files summary').click();await target.locator('.agent-detail-tabs [data-tab="ied"]').click();}
 expect(await page.locator('.agent-source-files').getAttribute('open')).not.toBeNull();expect(await original.locator('.agent-source-files').getAttribute('open')).toBeNull();
 await info.attach('source-details-residual',{body:JSON.stringify({status:'DISCLOSED_MINOR',sourceAfterTab:'closed',reactAfterTab:'open',parityPass:false}),contentType:'application/json'});
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
