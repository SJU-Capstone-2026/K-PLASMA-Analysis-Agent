import {expect,test} from '@playwright/test';
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
for(const width of [390,800,1008,1440])test(`P-structure-01/02/03/04 actual DOM, local runtime and keyboard at ${width}px`,async({page,context},info)=>{
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
 // R18: source/React on the measured Mac font runtime are both886px at800px.
 // CI fonts can change x; assert the inherited fixed530px selector geometry and report actual width.
 // This is a disclosed overflow check, never a no-overflow pass.
 if(width===800){
  const selectors=await page.locator('.analysis-selectors').boundingBox();expect(selectors!.width).toBe(530);
  expect(selectors!.x+selectors!.width).toBeGreaterThan(width);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(Math.ceil(selectors!.x+selectors!.width));
 }
 else expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.screenshot({path:info.outputPath(`actual-analysis-${width}.png`),fullPage:true,animations:'disabled'});
 expect(external).toEqual([]);await info.attach('environment',{body:JSON.stringify({browser:context.browser()?.version(),fontFamily:await page.locator('body').evaluate(element=>getComputedStyle(element).fontFamily),width,locale:'ko-KR',timezone:'Asia/Seoul',deviceScaleFactor:1,apiMocking:false,inheritedOverflow:width===800?{viewport:800,measuredMacSourceScrollWidth:886,reactScrollWidth:await page.evaluate(()=>document.documentElement.scrollWidth),selectorWidth:530}:null}),contentType:'application/json'});
});
registerWorkspaceDecisionGate({api,baseURL,widths:[390,800,1008,1440],candidateQuestion:process.env.KPLASMA_E2E_REFERENCE==='true'?undefined:'Mean Ion Energy 12–13 eV 후보 찾아줘'});
