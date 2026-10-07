import {writeFile} from 'node:fs/promises';
import {expect,test,type Page} from '@playwright/test';
import {toRunSummary,type TurnSnapshot,type WorkspaceView} from 'agent';
import {syntheticRun} from '../../test/runs';
import {emptyWorkspace,initialTurnUi} from './useConversation';

type Sample={domMs:number;frameMs:number};
async function measure(page:Page,selector:string,changedSelector:string):Promise<Sample>{
 await page.locator(selector).scrollIntoViewIfNeeded();
 await page.evaluate(({selector,changedSelector})=>{
  const state=window as typeof window&{turnUiSample?:Promise<Sample>};
  state.turnUiSample=new Promise(resolve=>{
   let start=0;
   const observer=new MutationObserver(()=>{
    if(!start||!document.querySelector(changedSelector))return;
    const domMs=performance.now()-start;observer.disconnect();
    // Two animation frames bracket a paint opportunity; this is a proxy, not INP.
    requestAnimationFrame(()=>requestAnimationFrame(()=>resolve({domMs,frameMs:performance.now()-start})));
   });
   document.addEventListener('click',()=>{start=performance.now();observer.observe(document.body,{subtree:true,childList:true,attributes:true});},{capture:true,once:true});
   if(!document.querySelector(selector))throw new Error('Measurement target is missing');
  });
 },{selector,changedSelector});
 await page.locator(selector).click();
 return page.evaluate(()=>(window as typeof window&{turnUiSample:Promise<Sample>}).turnUiSample);
}
function stats(samples:number[]){const sorted=[...samples].sort((a,b)=>a-b);const percentile=(p:number)=>sorted[Math.ceil(sorted.length*p)-1];return {median:percentile(.5),p95:percentile(.95),min:sorted[0],max:sorted.at(-1)};}

test('synthetic card and stored graph-tab click latency, with identical 500ms UI saves',async({page},info)=>{
 const runs=[600,800,1000,200,400].map(bias=>syntheticRun(bias));const run=runs[0];
 const turn:TurnSnapshot={id:'perf-turn',askedAt:'2026-10-08T00:00:00Z',question:'합성 후보 조회',intent:'REVERSE_SEARCH',context:null,
  answerRunRefs:runs.map(({runId,runVersionId})=>({runId,runVersionId})),ui:{...structuredClone(initialTurnUi),runDetailTabs:{[run.runId]:'ied'}},
  answerSnapshot:JSON.parse(JSON.stringify({implementationId:'v1',schemaVersion:1,kind:'reverse_search',summary:'합성 성능 검증',result:{kind:'reverse_search',resultStatus:'MATCH',constraints:[],goals:[],objectives:[],commonCandidates:runs.map(run=>({run:toRunSummary(run),evaluations:[],matchPercent:100})),objectiveResults:[],goalResults:[],nearMisses:[]}})),
 };
 let workspace:WorkspaceView={...structuredClone(emptyWorkspace),conversation:{version:1,activeRun:null,turns:[turn]}};let writes=0;
 await page.route('**/api/**',async route=>{
  const request=route.request();const path=new URL(request.url()).pathname;
  if(!path.startsWith('/api/'))return route.continue();
  if(path==='/api/decisions')return route.fulfill({json:[]});
  if(path==='/api/runs')return route.fulfill({json:runs.map(toRunSummary)});
  if(path.startsWith('/api/run-versions/'))return route.fulfill({json:run});
  if(path.endsWith('/ui')){
   const body=request.postDataJSON();await new Promise(resolve=>setTimeout(resolve,500));
   expect(body.stateToken).toEqual(workspace.stateToken);
   turn.ui={...turn.ui,...body.ui,runDetailTabs:{...turn.ui.runDetailTabs,...body.ui.runDetailTabs}};
   workspace={...workspace,stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1}};
   await route.fulfill({json:workspace});writes++;
   return;
  }
  return route.fulfill({json:workspace});
 });
 await page.goto('/');await expect(page.locator('.agent-fit-card')).toHaveCount(5);await page.evaluate(()=>document.fonts.ready);
 const card='.agent-fit-card:first-child';const control=`${card} [data-action="select-candidate-card"]`;
 const results:{card:Sample[];graph:Sample[]}={card:[],graph:[]};let expectedWrites=0;
 for(let index=0;index<22;index++){
  const sample=await measure(page,control,`${card}${index%2===0?'.is-selected':':not(.is-selected)'}`);
  if(index>=2)results.card.push(sample);await expect.poll(()=>writes).toBe(++expectedWrites);
 }
 await page.locator(card).getByRole('button',{name:'실험 자세히 보기'}).click();
 await expect(page.locator('[data-tab="ied"]')).toHaveAttribute('aria-selected','true');
 for(let index=0;index<22;index++){
  const selector=`[data-tab="${index%2===0?'residual':'ied'}"]`;
  const sample=await measure(page,selector,`${selector}[aria-selected="true"]`);
  if(index>=2)results.graph.push(sample);await expect.poll(()=>writes).toBe(++expectedWrites);
 }
 const report={variant:process.env.KPLASMA_UI_BASELINE_FILE?'before':'after',browser:page.context().browser()?.version(),viewport:{width:1440,height:1000},saveDelayMs:500,samplesPerAction:20,warmupPerAction:2,writes,
  stats:{card:{dom:stats(results.card.map(s=>s.domMs)),frame:stats(results.card.map(s=>s.frameMs))},graph:{dom:stats(results.graph.map(s=>s.domMs)),frame:stats(results.graph.map(s=>s.frameMs))}},samples:results};
 const path=process.env.KPLASMA_UI_PERF_REPORT??info.outputPath('turn-ui-performance.json');
 await writeFile(path,JSON.stringify(report,null,2));console.log(JSON.stringify({...report,samples:undefined}));
});
