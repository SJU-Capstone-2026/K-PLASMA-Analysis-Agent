// Functional/responsive checks against the real product API, separate from timings.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createServer} from 'vite';
import react from '@vitejs/plugin-react';
import {chromium} from 'playwright';
const directory=process.argv[2];
const fixture=JSON.parse(await fs.readFile(path.join(directory,'request.json'),'utf8'));
const local='.local/performance/run-selection/qa-browser';
await fs.mkdir(local,{recursive:true});
await fs.writeFile(local+'/entry.tsx',`import React from 'react';import {createRoot} from 'react-dom/client';import {RunSelectionPanel} from '/frontend/src/features/agent/RunSelectionPanel.tsx';import '/frontend/src/prototype/styles.css';const request=${JSON.stringify(fixture.request)};createRoot(document.getElementById('root')!).render(<section className="v1-pending"><RunSelectionPanel request={request} sending={false} onResume={async input=>{const response=await fetch('/api/agent/requests/'+request.requestId+'/resume',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({expectedRequestRevision:request.requestRevision,pendingInputId:'pick',input})});if(!response.ok)throw new Error(await response.text());window.__resumed=await response.json();}} onError={error=>{window.__resumeError=String(error);}}/></section>);`);
await fs.writeFile(local+'/index.html',`<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body><div id="root" style="max-width:1200px;margin:auto"></div><script type="module" src="/${local}/entry.tsx"></script></body></html>`);
const server=await createServer({configFile:false,root:process.cwd(),plugins:[react()],server:{host:'127.0.0.1',port:15149,strictPort:true,watch:{ignored:['**/backend/**','**/docs/**','**/scripts/**','**/.local/performance/**']},proxy:{'/api':'http://127.0.0.1:18049'}}});
await server.listen();const browser=await chromium.launch();const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'ko-KR'});const evidence={checks:[],widths:[]};
async function saved(count){await page.getByRole('status').filter({hasText:new RegExp(`선택 ${count}개`)}).waitFor();await page.waitForFunction(()=>!Array.from(document.querySelectorAll('[role="status"]')).some(e=>e.textContent.includes('저장 중')));}
async function search(query){await page.getByRole('searchbox').fill(query);await page.getByRole('searchbox').press('Enter');}
try{
 await page.goto(`http://127.0.0.1:15149/${local}/index.html`);await page.getByRole('checkbox').first().waitFor();
 assert.equal(await page.getByRole('checkbox').count(),30);
 await page.getByRole('checkbox').first().check();await saved(1);
 await page.getByRole('button',{name:'다음 페이지',exact:true}).click();await page.getByRole('checkbox',{name:/^R31 ·/}).waitFor();await page.getByRole('checkbox').first().check();await saved(2);
 await search('no-such-synthetic-run');await page.getByText('검색에 맞는 실험이 없습니다. 기존 선택은 유지됩니다.').waitFor();await saved(2);
 await page.reload();await saved(2);await page.getByRole('checkbox').first().waitFor();
 await page.getByLabel(/비교 기준/).selectOption('R1');await saved(2);
 evidence.checks.push('page/search/reload preserve two selections and an exact baseline');
 for(const width of [390,800,1008,1440]){
  await page.setViewportSize({width,height:1000});
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const layout=await page.evaluate(()=>({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,rows:document.querySelectorAll('input[type="checkbox"]').length}));
  assert.ok(layout.scroll<=layout.client+1,`overflow at ${width}: ${JSON.stringify(layout)}`);
  await page.screenshot({path:path.join(directory,`qa-${width}.png`)});evidence.widths.push({width,...layout});
 }
 await page.getByRole('button',{name:'선택 해제',exact:true}).click();await saved(0);
 await page.getByRole('button',{name:'현재 페이지 선택',exact:true}).click();await saved(30);
 await search('RUN-P01-S005-B7450');await page.getByRole('checkbox',{name:/^R150 ·/}).waitFor();
 await page.getByRole('button',{name:'검색 결과 전체 선택',exact:true}).click();await saved(31);
 await page.getByRole('button',{name:'전체 실험 선택',exact:true}).click();await saved(149);
 assert.ok(await page.locator('.v1-picker-chips button').count()<=6);
 evidence.checks.push('page/search/catalogue bulk scopes union; all-selected DOM remains bounded');
 await page.getByRole('button',{name:'선택 해제',exact:true}).click();await saved(0);
 await search('');await page.getByRole('checkbox',{name:/^R1 ·/}).waitFor();
 await page.getByRole('checkbox').nth(0).check();await saved(1);await page.getByRole('checkbox').nth(1).check();await saved(2);
 await page.getByRole('button',{name:'선택한 실험으로 계속',exact:true}).click();
 await page.waitForFunction(()=>window.__resumed||window.__resumeError);const resumed=await page.evaluate(()=>window.__resumed);
 assert.ok(resumed);assert.equal(resumed.status,'QUEUED');assert.equal(resumed.inputEvents.at(-1).input.comparisonReference.entries.length,2);
 evidence.checks.push('browser resumes with a snapshot token; server supplies exactly two trusted versions');
 evidence.ok=true;
}catch(error){evidence.ok=false;evidence.error=String(error);throw error;}
finally{await fs.writeFile(path.join(directory,'qa.json'),JSON.stringify(evidence,null,2));await browser.close();await server.close();}
