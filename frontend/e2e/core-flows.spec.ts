import {expect,test} from '@playwright/test';
import type {RunSummary} from 'agent';
import {registerWorkspaceDecisionGate} from '../src/features/agent/workspace.integration';
import {navigate} from './helpers';

const api=process.env.KPLASMA_E2E_API;
if(!api)throw new Error('Use npm run test:e2e: it provisions an isolated actual PostgreSQL/backend.');
const baseURL=`http://127.0.0.1:${process.env.KPLASMA_E2E_PORT??'5192'}`;
test('artificial folder UI upload goes through real HTTP and preserves duplicate versions',async({page})=>{
 test.skip(process.env.KPLASMA_E2E_REFERENCE==='true','External gate already registers both complete transports; UI upload is covered by artificial CI.');
 const before=await (await page.request.get(`${api}/api/runs`)).json();await page.goto('/');await navigate(page,'catalog');
 const accepted=page.waitForResponse(response=>response.url().endsWith('/api/import-batches')&&response.request().method()==='POST');
 await page.getByLabel('폴더 선택').setInputFiles(process.env.KPLASMA_E2E_SYNTHETIC_FOLDER!);
 const response=await accepted;expect(response.status()).toBe(202);const batch=await response.json();
 await expect.poll(async()=>(await (await page.request.get(`${api}/api/import-batches/${batch.batchId}`)).json()).status).toBe('SUCCESS');
 const terminal=await (await page.request.get(`${api}/api/import-batches/${batch.batchId}`)).json();expect(terminal.jobs.every((job:{status:string})=>job.status==='DUPLICATE')).toBe(true);
 expect(await (await page.request.get(`${api}/api/runs`)).json()).toEqual(before);
});
for(const width of [390,800,1008,1100,1440])test(`P-structure-01/03/04 actual DOM, local runtime and keyboard at ${width}px`,async({page,context},info)=>{
 await page.setViewportSize({width,height:1000});const external:string[]=[];
 page.on('request',request=>{if(!request.url().startsWith(baseURL)&&!request.url().startsWith('data:'))external.push(new URL(request.url()).hostname);});
 await page.goto('/');await expect(page.locator('.agent-welcome')).toBeVisible();
 expect(await page.locator('.nav-stack [data-view]').evaluateAll(elements=>elements.map(element=>element.getAttribute('data-view')))).toEqual(['agent','analysis','archive','catalog','flow']);
 for(const action of ['example-forward','example-constraint','example-reverse','example-explanation','example-concept','example-memory-filter','example-memory-reason'])await expect(page.locator(`[data-action="${action}"]`)).toHaveCount(1);
 expect(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim().toLowerCase())).toBe('#4168e8');
 expect(await page.locator('html').getAttribute('lang')).toBe('ko');
 for(const id of ['app','sidebar','topbar','view-root','modal-root','toast-region'])await expect(page.locator(`#${id}`)).toHaveCount(1);
 await expect(page.getByRole('navigation',{name:'분석 메뉴'})).toBeVisible();await expect(page.locator('#toast-region')).toHaveAttribute('aria-live','polite');
 await page.keyboard.press('Tab');await expect(page.locator('.skip-link')).toBeFocused();await page.keyboard.press('Enter');await expect(page.locator('#view-root')).toBeFocused();
 await navigate(page,'analysis');await expect(page.locator('.analysis-selection-card')).toBeVisible();
 const cells=page.locator('[data-action="analysis-select"]');await cells.first().focus();await page.keyboard.press('Enter');await expect(page.locator('.analysis-run-title h2')).toBeVisible();
 expect(await cells.first().evaluate(element=>parseFloat(getComputedStyle(element).outlineWidth))).toBeGreaterThan(0);
 const analysisGeometry=await page.evaluate(()=>{
  const map=document.querySelector('.condition-map')!.getBoundingClientRect(),card=document.querySelector('.analysis-selection-card')!.getBoundingClientRect();
  return {pageOverflows:document.documentElement.scrollWidth>innerWidth,mapOverlapsCard:!(map.right<=card.left||card.right<=map.left||map.bottom<=card.top||card.bottom<=map.top)};
 });
 expect(analysisGeometry).toEqual({pageOverflows:false,mapOverlapsCard:false});
 await page.screenshot({path:info.outputPath(`actual-analysis-${width}.png`),fullPage:true,animations:'disabled'});
 await navigate(page,'catalog');await expect(page.getByRole('heading',{name:'등록 Run'})).toBeVisible();
 const catalogGeometry=await page.locator('.catalog-toolbar').evaluate(toolbar=>{
  const bounds=toolbar.getBoundingClientRect(),children=Array.from(toolbar.children).map(child=>child.getBoundingClientRect());
  return {pageOverflows:document.documentElement.scrollWidth>innerWidth,childrenFit:children.every(child=>child.left>=bounds.left-1&&child.right<=bounds.right+1)};
 });
 expect(catalogGeometry).toEqual({pageOverflows:false,childrenFit:true});
 await page.screenshot({path:info.outputPath(`actual-catalog-${width}.png`),fullPage:true,animations:'disabled'});
 expect(external).toEqual([]);await info.attach('environment',{body:JSON.stringify({browser:context.browser()?.version(),fontFamily:await page.locator('body').evaluate(element=>getComputedStyle(element).fontFamily),width,locale:'ko-KR',timezone:'Asia/Seoul',deviceScaleFactor:1,apiMocking:false}),contentType:'application/json'});
});
test('P-structure-02 real memory container boundaries and reduced motion',async({page,request,context},info)=>{
 const initial=await (await request.get(`${api}/api/workspace`)).json();expect(initial.conversation.turns).toEqual([]);expect(await (await request.get(`${api}/api/decisions`)).json()).toEqual([]);
 try{
  await page.setViewportSize({width:1440,height:1000});await page.goto('/');await navigate(page,'analysis');await expect(page.locator('.analysis-run-title h2')).toBeVisible();
  expect(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim().toLowerCase())).toBe('#4168e8');
  await page.locator('[data-action="analysis-select"]').first().focus();expect(await page.locator('[data-action="analysis-select"]').first().evaluate(el=>parseFloat(getComputedStyle(el).outlineWidth))).toBeGreaterThan(0);
  const runId=(await page.locator('.analysis-run-title h2').textContent())!;
  const runs:RunSummary[]=await (await request.get(`${api}/api/runs`)).json();const run=runs.find(run=>run.runId===runId);expect(run).toBeDefined();if(!run)throw new Error('Selected registered Run missing.');expect(run).toBeDefined();
  await page.getByRole('button',{name:'실험 기록',exact:true}).click();await page.getByRole('radio',{name:/보류/}).check();await page.getByRole('textbox',{name:/판단 근거 코멘트/}).fill('memory container verification');
  await page.getByRole('button',{name:'코멘트와 결정 저장'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'이 Run으로 Agent에게 질문',exact:true}).first().click();
  await page.locator('#agent-query').fill(`Mean Ion Energy ${run.metrics.meanIonEnergy-0.5}–${run.metrics.meanIonEnergy+0.5} eV 후보 찾아줘`);await page.locator('#agent-query-form [type="submit"]').click();await expect(page.locator('.agent-fit-card-selectable').first()).toBeVisible();await expect(page.locator('#agent-query-form [type="submit"]')).toBeEnabled();
  await page.locator('[data-action="example-memory-filter"]').click();await expect(page.locator('.memory-answer .memory-row').first()).toBeVisible();await expect(page.locator('#agent-query-form [type="submit"]')).toBeEnabled();
  const answer=page.locator('.memory-answer').last();expect(await answer.evaluate(el=>getComputedStyle(el).containerType)).toBe('inline-size');
  const observations=[];
  // Fix only the real answer's content-box width; viewport stays1440 to test CONTAINER, not media queries.
  for(const width of [821,820,819,621,620,619]){
   await answer.evaluate((el,width)=>{const node=el as HTMLElement;node.style.boxSizing='content-box';node.style.width=`${width}px`;node.style.maxWidth='none';},width);
   const observed=await answer.evaluate(el=>({contentWidth:parseFloat(getComputedStyle(el).width),columns:getComputedStyle(el.querySelector('.memory-result-summary')!).gridTemplateColumns.split(' ').length,direction:getComputedStyle(el.querySelector('.memory-row')!).flexDirection,actionsWidth:el.querySelector('.memory-row-actions')!.getBoundingClientRect().width,rowInnerWidth:el.querySelector('.memory-row')!.clientWidth-28}));
   expect(observed.contentWidth).toBe(width);expect(observed.columns).toBe(width<=820?2:4);expect(observed.direction).toBe(width<=620?'column':'row');
   if(width<=620)expect(observed.actionsWidth).toBe(observed.rowInnerWidth);observations.push({width,...observed});
  }
  await page.emulateMedia({reducedMotion:'reduce'});expect(await page.locator('.nav-item').first().evaluate(el=>parseFloat(getComputedStyle(el).transitionDuration))).toBeLessThanOrEqual(.001);
  await info.attach('memory-container-boundaries',{body:JSON.stringify({observations,reducedMotion:true,viewportWidth:1440,apiMocking:false}),contentType:'application/json'});
  await info.attach('environment',{body:JSON.stringify({browser:context.browser()?.version(),fontFamily:await page.locator('body').evaluate(el=>getComputedStyle(el).fontFamily),locale:'ko-KR',timezone:'Asia/Seoul',deviceScaleFactor:1,apiMocking:false}),contentType:'application/json'});
  await page.screenshot({path:info.outputPath('memory-container-619.png'),fullPage:true});
 }finally{const current=await (await request.get(`${api}/api/workspace`)).json();expect((await request.post(`${api}/api/workspace/reset`,{data:{stateToken:current.stateToken}})).status()).toBe(200);}
});
registerWorkspaceDecisionGate({api,baseURL,widths:[390,800,1008,1440],candidateQuestion:process.env.KPLASMA_E2E_REFERENCE==='true'?undefined:'Mean Ion Energy 12–13 eV 후보 찾아줘'});
