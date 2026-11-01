// Mount the real picker in isolation: excludes unrelated catalogue and chat loading.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createServer} from 'vite';
import react from '@vitejs/plugin-react';
import {chromium} from 'playwright';
const [directory,variant]=process.argv.slice(2);
const root=process.cwd();
const fixture=JSON.parse(await fs.readFile(path.join(directory,'request.json'),'utf8'));
const local='.local/performance/run-selection/browser-'+variant;
await fs.mkdir(local,{recursive:true});
const source=variant==='A'?'.local/performance/run-selection/A/RunSelectionPanel.tsx':'frontend/src/features/agent/RunSelectionPanel.tsx';
await fs.writeFile(local+'/entry.tsx',`import React from 'react';import {createRoot} from 'react-dom/client';import {RunSelectionPanel} from '/${source}';import '/frontend/src/prototype/styles.css';createRoot(document.getElementById('root')!).render(<RunSelectionPanel request={${JSON.stringify(fixture.request)}} sending={false} onResume={async()=>{}} onError={console.error}/>);`);
await fs.writeFile(local+'/index.html',`<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body><div id="root" style="max-width:1200px;margin:auto;padding:16px"></div><script type="module" src="/${local}/entry.tsx"></script></body></html>`);
const server=await createServer({configFile:false,root,plugins:[react()],server:{host:'127.0.0.1',port:15149,strictPort:true,watch:{ignored:['**/backend/**','**/docs/**','**/scripts/**','**/.local/performance/**']},proxy:{'/api':'http://127.0.0.1:18049'}}});
await server.listen();const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'ko-KR'});
const rows=[];const size=Number(path.basename(directory));
try{
 for(let i=-2;i<(size>=100000?10:20);i++){
  try{
   const start=performance.now();
   await page.goto(`http://127.0.0.1:15149/${local}/index.html`,{timeout:20000,waitUntil:'domcontentloaded'});
   await page.getByRole('checkbox').first().waitFor({timeout:20000});
   await page.waitForFunction(()=>{const first=document.querySelector('input[type=checkbox]');return first&&!first.matches(':disabled');},{},{timeout:20000});
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const firstMs=performance.now()-start;const domNodes=await page.locator('*').count();
   const t=performance.now();await page.getByRole('searchbox').fill('RUN-P01-S005-B0050');
   await page.waitForFunction(()=>document.querySelectorAll('input[type="checkbox"]').length===1,{},{timeout:20000});
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));
   if(i>=0)rows.push({index:i,ok:true,firstMs,searchMs:performance.now()-t,domNodes});
  }catch(e){rows.push({index:i,ok:false,error:String(e)});break;}
 }
 if(rows.every(row=>row.ok))await page.screenshot({path:path.join(directory,'picker.png'),fullPage:false,timeout:10000}).catch(()=>{});
}finally{await fs.writeFile(path.join(directory,'browser.json'),JSON.stringify(rows,null,2));await browser.close();await server.close();}
