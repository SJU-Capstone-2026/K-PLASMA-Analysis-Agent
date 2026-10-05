import {expect,test,type Page} from '@playwright/test';
import {spawnSync} from 'node:child_process';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {toRunSummary,type TurnSnapshot,type WorkspaceView} from 'agent';
import {syntheticRun} from '../../test/runs';
import {emptyWorkspace,initialTurnUi} from './useConversation';

const prototype=process.env.KPLASMA_PROTOTYPE_URL;
const repo=resolve(dirname(fileURLToPath(import.meta.url)),'../../../..');
// Artificial observations, including a high-flux Run outside the requested range.
const runs=[600,800,1000,200,400,0].map((bias,index)=>({...syntheticRun(bias,8),metrics:{ionFlux:index+1,meanIonEnergy:index===5?165:151+index*2,iedWidth:bias?8:null}}));
const questions={forward_lookup:'압력 8 mTorr, 소스 300 W, 바이어스 600 W 결과를 보여줘',reverse_search:'Ion Flux는 높게, Mean Ion Energy는 150–160 eV에 가깝게 후보를 찾아줘'};
const inputs={forward_lookup:{conditions:{pressure:{value:8},sourcePower:{value:300},biasPower:{value:600}}},reverse_search:{constraints:[{metric:'meanIonEnergy',operator:'between',min:150,max:160,unit:'eV'}],goals:[{metric:'ionFlux',direction:'maximize'}]}};
function result(kind:keyof typeof questions){
 const python=process.env.KPLASMA_PYTHON??resolve(repo,'agent/python/.venv/bin/python');
 const executed=spawnSync(python,['-c','import json,sys; from kplasma_agent.domain import lookup_forward,search_reverse; p=json.load(sys.stdin); print(json.dumps((lookup_forward if p["kind"]=="forward_lookup" else search_reverse)(p["inputs"],p["runs"]),allow_nan=False))'],{input:JSON.stringify({kind,inputs:inputs[kind],runs}),encoding:'utf8',env:{...process.env,PYTHONPATH:resolve(repo,'agent/python/src')}});
 if(executed.status!==0)throw new Error(`Python synthetic search failed: ${executed.stderr}`);
 return JSON.parse(executed.stdout);
}
async function setup(page:Page,kind:keyof typeof questions){
 const searched=result(kind);
 const turn:TurnSnapshot={id:'parity',askedAt:'2026-10-05T00:00:00Z',question:questions[kind],intent:kind==='forward_lookup'?'FORWARD_LOOKUP':'REVERSE_SEARCH',context:null,answerRunRefs:searched.usedRunRefs,answerSnapshot:{implementationId:'v1',schemaVersion:1,kind,result:searched},ui:structuredClone(initialTurnUi)};
 let workspace:WorkspaceView={...structuredClone(emptyWorkspace),conversation:{version:1,activeRun:null,turns:[turn]}};
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(!path.startsWith('/api/'))return route.continue();
  if(path==='/api/runs')return route.fulfill({json:runs.map(toRunSummary)});
  if(path==='/api/decisions')return route.fulfill({json:[]});
  if(path.startsWith('/api/run-versions/'))return route.fulfill({json:runs.find(run=>path.endsWith(run.runVersionId))});
  if(path.endsWith('/ui')){const body=route.request().postDataJSON();turn.ui={...turn.ui,...body.ui};workspace={...workspace,conversation:{...workspace.conversation,turns:[turn]}};}
  return route.fulfill({json:workspace});
 });
 await page.goto('/');await expect(page.locator('.agent-compact-answer')).toBeVisible();
}
async function compare(page:Page,original:Page,selectors:string[]){
 expect(await page.locator('.agent-compact-answer').textContent()).toEqual(await original.locator('.agent-compact-answer').textContent());
 for(const selector of selectors){
  const actual=await page.locator(selector).first().boundingBox(),expected=await original.locator(selector).first().boundingBox();
  expect(actual,selector).not.toBeNull();expect(expected,selector).not.toBeNull();
  for(const key of ['x','y','width','height'] as const)expect(Math.abs(actual![key]-expected![key]),`${selector} ${key}`).toBeLessThanOrEqual(1/64);
 }
}
for(const width of [390,800,1008,1440])for(const kind of ['forward_lookup','reverse_search'] as const)test(`Python v1 ${kind} matches the approved prototype layout at ${width}px`,async({page,context},info)=>{
 test.skip(!prototype,'Set KPLASMA_PROTOTYPE_URL to the unchanged external v12.3.1 prototype; its real data is replaced by artificial Runs.');
 await page.setViewportSize({width,height:1000});await page.clock.setFixedTime(new Date('2026-10-05T00:00:00Z'));await setup(page,kind);
 const original=await context.newPage();await original.setViewportSize({width,height:1000});await original.clock.setFixedTime(new Date('2026-10-05T00:00:00Z'));
 await original.route('**/assets/analysis-data.js',route=>route.fulfill({contentType:'text/javascript',body:`window.KPlasmaAnalysisData=${JSON.stringify({meta:{actualRunCount:runs.length},runs})};`}));
 await original.goto(prototype!);await original.locator('#agent-query').fill(questions[kind]);await original.locator('#agent-query-form [type="submit"]').click();await expect(original.locator('.agent-compact-answer')).toBeVisible();
 // The external source stays untouched. Apply only the two user-approved layout
 // removals to its rendered DOM before measuring the remaining prototype UI.
 if(kind==='reverse_search'){
  await expect(original.getByRole('tab',{name:'Ion Flux 높은순 6'})).toBeVisible();
  await original.evaluate(()=>{
   for(const tab of document.querySelectorAll('.agent-candidate-tabs button'))if(tab.textContent?.trim()==='Ion Flux 높은순 6')tab.remove();
   for(const note of document.querySelectorAll('.agent-similarity-note'))if(note.querySelector('strong')?.textContent==='현재 정렬')note.remove();
  });
 }
 for(const target of [page,original]){await target.evaluate(()=>document.fonts.ready);expect(await target.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}
 await compare(page,original,kind==='forward_lookup'?['.agent-response','.agent-forward-conclusion','.agent-condition-summary','.agent-delta-grid','.agent-run-actions']:['.agent-response','.agent-result-intro','.agent-search-summary','.agent-candidate-tabs','.agent-fit-grid','.agent-fit-card','.agent-fit-rows']);
 if(kind==='reverse_search'){
  await expect(page.getByRole('tab',{name:'조건 일치 결과 5'})).toHaveAttribute('aria-selected','true');
  await expect(page.getByRole('tab')).toHaveCount(2);
  await expect(page.getByRole('tab',{name:/Ion Flux 높은순/})).toHaveCount(0);
  await expect(page.getByRole('tab',{name:'Mean Ion Energy 조건 5'})).toBeVisible();
  await expect(page.locator('.agent-search-summary')).toContainText('정렬Ion Flux 높은순');
  await expect(page.getByText('현재 정렬',{exact:true})).toHaveCount(0);
 }
 for(const [name,target] of [['v1',page],['prototype',original]] as const)await target.locator('.agent-response').screenshot({path:info.outputPath(`${name}-${kind}-${width}.png`),animations:'disabled'});
 await page.getByRole('button',{name:kind==='forward_lookup'?'상세 데이터':'실험 자세히 보기'}).first().click();await expect(page.getByRole('dialog')).toBeVisible();expect(await page.getByRole('dialog').evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
 await original.close();
});
