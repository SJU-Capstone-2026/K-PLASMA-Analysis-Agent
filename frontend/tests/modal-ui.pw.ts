import {expect,test} from '@playwright/test';
import {fixtureRuns} from '../src/test/runs';
for(const width of [390,800,1008,1440]){
 test(`modal keyboard, seven tabs and reference overflow at ${width}px`,async({page,context},testInfo)=>{
  await page.setViewportSize({width,height:1000});await page.emulateMedia({reducedMotion:'reduce'});
  await page.route('**/api/run-versions/*',route=>route.fulfill({json:fixtureRuns[0]}));await page.goto('/tests/harness.html');
  await expect(page.locator('.reference-tray-runs > .run-context-chip')).toHaveCount(6);await expect(page.locator('.reference-tray-more-grid > .run-context-chip')).toHaveCount(2);await page.locator('.reference-tray-more summary').click();await expect(page.getByText('SYNTHETIC-7')).toBeVisible();
  const reference=process.env.KPLASMA_PROTOTYPE_URL;const original=reference?await context.newPage():null;let originalHelpers='';
  if(original){await original.setViewportSize({width,height:1000});await original.emulateMedia({reducedMotion:'reduce'});await original.route('**/assets/analysis-data.js',route=>route.fulfill({contentType:'text/javascript',body:`window.KPlasmaAnalysisData=${JSON.stringify({meta:{actualRunCount:150},runs:fixtureRuns})};`}));await original.goto(reference!);const code=await (await original.request.get(`${reference}/assets/app.js`)).text();originalHelpers=code.slice(code.indexOf('  function svgChart('),code.indexOf('  function renderAnalysisChartContent('))+code.slice(code.indexOf('  function renderRunDetail('),code.indexOf('  function renderRunActions('))+code.slice(code.indexOf('  function openRunDetail('),code.indexOf('  function openDecision('));}
  const trigger=page.getByRole('button',{name:'실험 자세히 보기'});await trigger.click();const dialog=page.getByRole('dialog');await expect(dialog).toBeFocused();await expect(dialog.getByRole('tab')).toHaveCount(7);
  for(const tab of await dialog.getByRole('tab').all()){await tab.click();await expect(tab).toHaveAttribute('aria-selected','true');await expect(dialog).toBeFocused();
   if(original){const tabId=await tab.getAttribute('data-tab');await original.evaluate(({helpers,runId,tabId})=>{const prefix=`const viewModels=window.KPlasmaViewModels;const modalRoot=document.getElementById('modal-root');const getRun=id=>window.KPlasmaAnalysisData.runs.find(run=>run.runId===id);const state={conversation:{turns:[{id:'modal',ui:{runDetailTabs:{[${JSON.stringify(runId)}]:${JSON.stringify(tabId)}}}}]},returnFocus:null};const escapeHtml=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');const toast=()=>{};`;new Function(prefix+helpers+`openRunDetail('modal',${JSON.stringify(runId)});`)();},{helpers:originalHelpers,runId:fixtureRuns[0].runId,tabId});
    const svg=async(p:typeof page)=>p.locator('.agent-detail-graph svg').evaluate(element=>{function tree(el:Element):unknown{return {tag:el.tagName,attrs:Object.fromEntries(Array.from(el.attributes).map(attr=>[attr.name,attr.value]).sort()),text:el.children.length?null:el.textContent,children:Array.from(el.children).map(tree)};}return tree(element);});expect(await svg(page)).toEqual(await svg(original));const actual=await dialog.boundingBox(),expected=await original.getByRole('dialog').boundingBox();expect(actual!.width).toBeCloseTo(expected!.width,0);expect(actual!.height).toBeCloseTo(expected!.height,0);
   }
  }
  if(original){await original.screenshot({path:testInfo.outputPath(`original-modal-${width}.png`),fullPage:true});await original.close();}
  await page.screenshot({path:testInfo.outputPath(`modal-${width}.png`),fullPage:true});const box=await dialog.boundingBox();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(width);expect(box!.height).toBeLessThanOrEqual(1000);
  await page.keyboard.press('Tab');await expect(dialog.getByRole('button',{name:/실험 상세 닫기/})).toBeFocused();await page.keyboard.press('Shift+Tab');await expect(dialog.getByRole('tab',{name:'Residual Convergence'})).toBeFocused();await page.keyboard.press('Tab');await expect(dialog.getByRole('button',{name:/실험 상세 닫기/})).toBeFocused();
  await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(trigger).toBeFocused();await page.getByRole('button',{name:'참조 대상 해제'}).click();await expect(page.locator('.reference-tray')).toHaveCount(0);
  const transition=await page.locator('.nav-item').first().evaluate(element=>getComputedStyle(element).transitionDuration);expect(parseFloat(transition)).toBeLessThanOrEqual(.001);
 });
}
test('review regression: initial native Shift+Tab and outside document keys stay recoverable',async({page})=>{
 await page.setViewportSize({width:390,height:1000});await page.route('**/api/run-versions/*',route=>route.fulfill({json:fixtureRuns[0]}));await page.goto('/tests/harness.html');const trigger=page.getByRole('button',{name:'실험 자세히 보기'});await trigger.click();const dialog=page.getByRole('dialog');await expect(dialog).toBeFocused();await expect(dialog.getByRole('tab',{name:'Residual Convergence'})).toBeVisible();
 await page.keyboard.press('Shift+Tab');await expect(dialog.getByRole('tab',{name:'Residual Convergence'})).toBeFocused();
 await trigger.focus();await page.keyboard.press('Tab');await expect(dialog.getByRole('button',{name:/실험 상세 닫기/})).toBeFocused();
 await trigger.focus();await page.keyboard.press('Shift+Tab');await expect(dialog.getByRole('tab',{name:'Residual Convergence'})).toBeFocused();
 await trigger.focus();await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(trigger).toBeFocused();await page.keyboard.press('Tab');await expect(page.locator('.reference-tray-more summary')).toBeFocused();
});
