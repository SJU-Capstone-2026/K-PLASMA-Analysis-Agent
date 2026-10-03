import {expect,test,type Page} from '@playwright/test';
import {fixtureRuns} from '../src/test/runs';
import {toRunSummary} from 'agent';
const reference=process.env.KPLASMA_PROTOTYPE_URL;
async function setup(page:Page,original=false){
 await page.route('**/api/runs',route=>route.fulfill({json:fixtureRuns.map(toRunSummary)}));
 await page.route('**/api/run-versions/*',route=>route.fulfill({json:fixtureRuns.find(run=>route.request().url().endsWith(run.runVersionId))}));
 if(original)await page.route('**/assets/analysis-data.js',route=>route.fulfill({contentType:'text/javascript',body:`window.KPlasmaAnalysisData=${JSON.stringify({meta:{actualRunCount:150},runs:fixtureRuns})};`}));
 await page.goto(original?reference!:'/');
 if(page.viewportSize()!.width<760)await page.getByRole('button',{name:'메뉴 열기'}).click();
 await page.locator('.nav-stack [data-view="analysis"]').click();
 await expect(page.getByRole('img',{name:'IED 실제 수치 선 그래프'})).toBeVisible();
}
async function svgState(page:Page){return page.locator('.analysis-chart-content svg').evaluateAll(elements=>elements.map(svg=>{function tree(element:Element):unknown{return {tag:element.tagName,attrs:Object.fromEntries(Array.from(element.attributes).map(attr=>[attr.name,attr.value]).sort()),children:Array.from(element.children).map(tree),text:element.children.length?null:element.textContent};}return tree(svg);}));}
for(const width of [390,800,1008,1440]){
 test(`analysis reference SVG and layout at ${width}px`,async({page,context},testInfo)=>{
  test.skip(!reference,'Set KPLASMA_PROTOTYPE_URL to the untouched local original server; both screens receive synthetic data.');
  await page.setViewportSize({width,height:1000});await setup(page);const original=await context.newPage();await original.setViewportSize({width,height:1000});await setup(original,true);
  for(const tab of ['distribution','waveforms','density','convergence']){await page.locator(`[data-action="analysis-tab"][data-tab="${tab}"]`).click();await original.locator(`[data-action="analysis-tab"][data-tab="${tab}"]`).click();expect(await svgState(page)).toEqual(await svgState(original));await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await original.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await page.screenshot({path:testInfo.outputPath(`react-${tab}-${width}.png`),fullPage:true});await original.screenshot({path:testInfo.outputPath(`original-${tab}-${width}.png`),fullPage:true});
   for(const selector of ['.analysis-control-panel','.analysis-selection-card','.analysis-kpi-grid','.analysis-detail-panel','.analysis-provenance']){const actual=await page.locator(selector).boundingBox(),expected=await original.locator(selector).boundingBox();expect(actual!.width).toBeCloseTo(expected!.width,0);expect(actual!.x).toBeCloseTo(expected!.x,0);expect(actual!.y).toBeCloseTo(expected!.y,0);expect(actual!.height).toBeCloseTo(expected!.height,0);}
  }
  await page.locator('[data-action="analysis-select"][data-run-id="RUN-P04-S300-B0600"]').focus();await page.keyboard.press('Enter');await expect(page.locator('.analysis-run-title h2')).toHaveText('RUN-P04-S300-B0600');await page.locator('[data-action="analysis-select"][data-run-id="RUN-P06-S300-B0600"]').focus();await page.keyboard.press('Space');await expect(page.locator('.analysis-run-title h2')).toHaveText('RUN-P06-S300-B0600');
  await page.getByLabel('고정 값').selectOption('0');await expect(page.getByText('Bias-off 스칼라 결과')).toBeVisible();await original.getByLabel('고정 값').selectOption('0');await page.locator('[data-action="analysis-tab"][data-tab="distribution"]').click();await original.locator('[data-action="analysis-tab"][data-tab="distribution"]').click();await expect(page.getByText('Bias-off Run에는 쉬스 분포 출력이 없습니다')).toBeVisible();
  await page.screenshot({path:testInfo.outputPath(`react-bias-off-${width}.png`),fullPage:true});await original.screenshot({path:testInfo.outputPath(`original-bias-off-${width}.png`),fullPage:true});

  if(width<760){await page.getByRole('button',{name:'메뉴 열기'}).click();await original.getByRole('button',{name:'메뉴 열기'}).click();}
  await page.locator('.nav-tools summary').click();await original.locator('.nav-tools summary').click();await page.locator('.nav-stack [data-view="flow"]').click();await original.locator('.nav-stack [data-view="flow"]').click();
  await page.screenshot({path:testInfo.outputPath(`react-flow-${width}.png`),fullPage:true});await original.screenshot({path:testInfo.outputPath(`original-flow-${width}.png`),fullPage:true});
  for(const selector of ['.flow-hero','.flow-status']){const actual=await page.locator(selector).boundingBox(),expected=await original.locator(selector).boundingBox();expect(actual!.width).toBeCloseTo(expected!.width,0);expect(actual!.height).toBeCloseTo(expected!.height,0);expect(actual!.y).toBeCloseTo(expected!.y,0);}
  await original.close();
 });
}
