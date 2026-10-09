import {expect,test} from '@playwright/test';
import type {AgentSubmission,RunRef,TurnSnapshot,WorkspaceView} from 'agent';
import wire from '../../../../agent/tests/support/answer-v2-wire.json' with {type:'json'};
import {syntheticRun} from '../../test/runs';
import {emptyWorkspace,initialTurnUi} from './useConversation';

const runs=[200,400,600,800,1000,1200,1400,1600].map(bias=>syntheticRun(bias));
const ref=(run:RunRef):RunRef=>({runId:run.runId,runVersionId:run.runVersionId});
for(const width of [390,800,1008,1440])test(`answer chrome and multiple chat references at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:1000});const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 const turns:TurnSnapshot[]=[
  {id:'search',askedAt:'2026-10-08T00:00:00Z',question:'인공 후보 조회',intent:'REVERSE_SEARCH',context:null,answerRunRefs:runs.map(ref),answerSnapshot:JSON.parse(JSON.stringify({implementationId:'v1',schemaVersion:1,kind:'reverse_search',result:{kind:'reverse_search',resultStatus:'MATCH',commonCandidates:runs.map(run=>({run,evaluations:[]})),goalResults:[],nearMisses:[]}})),ui:structuredClone(initialTurnUi)},
  {id:'general',askedAt:'2026-10-08T00:00:00Z',question:'인공 개념 질문',intent:'GENERAL_ANSWER',context:null,answerRunRefs:[],answerSnapshot:JSON.parse(JSON.stringify({...wire.general,summary:'일반 지식에 따른 답변입니다.'})),ui:structuredClone(initialTurnUi)},
  {id:'comparison',askedAt:'2026-10-08T00:00:00Z',question:'인공 비교 질문',intent:'RUN_COMPARISON',context:null,answerRunRefs:wire.comparison.usedRunRefs,answerSnapshot:JSON.parse(JSON.stringify({...wire.comparison,summary:'선택한 실제 실험을 비교했습니다.'})),ui:structuredClone(initialTurnUi)},
 ];
 const frozen=structuredClone(turns);let workspace:WorkspaceView={...structuredClone(emptyWorkspace),conversation:{version:1,activeRun:null,turns}};const submissions:AgentSubmission[]=[];
 let holdReference=false;let releaseReference:(()=>void)|undefined;
 await page.route('**/api/**',async route=>{
  const request=route.request();const path=new URL(request.url()).pathname;
  if(!path.startsWith('/api/'))return route.continue();
  if(path==='/api/decisions')return route.fulfill({json:[]});
  if(path.endsWith('/reference')){if(holdReference){holdReference=false;await new Promise<void>(resolve=>{releaseReference=resolve;});}const body=request.postDataJSON();expect(body.stateToken).toEqual(workspace.stateToken);workspace={...workspace,stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1},candidateReference:body.candidateReference,conversation:{...workspace.conversation,activeRun:body.activeRun}};}
  if(path==='/api/agent/requests'){submissions.push(request.postDataJSON());return route.fulfill({json:{requestId:'synthetic-request',requestRevision:0,status:'FAILED',stage:'interpret',graphVersion:'v1',question:'인공 비교 요청',pendingInput:null,error:{code:'TEST_STOP',message:'인공 요청 접수 검증'},partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]}});}
  return route.fulfill({json:workspace});
 });
 await page.goto('/');const general=page.locator('[data-turn-id="general"]');const comparison=page.locator('[data-turn-id="comparison"]');
 await expect(general.locator('.v1-markdown')).toContainText('평균 이온 에너지');
 for(const answer of [general,comparison]){
  await expect(answer.locator('.v1-summary,.v1-interpretation')).toHaveCount(0);
  await expect(answer.getByText('LLM 일반 지식 기반',{exact:true})).toHaveCount(0);
  expect(await answer.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
 }
 const search=page.locator('[data-turn-id="search"]');const add=search.getByRole('button',{name:'채팅에 추가하기',exact:true});
 await expect(add).toHaveCount(8);
 await add.nth(0).click();await add.nth(1).click();await add.nth(2).click();
 await expect.poll(()=>workspace.candidateReference?.runs.length).toBe(3);
 await search.getByRole('button',{name:'전체 후보 채팅에 추가'}).click();
 await expect.poll(()=>workspace.candidateReference?.runs.length).toBe(8);
 await add.nth(0).click();await expect.poll(()=>workspace.stateToken.revision).toBe(5);
 expect(workspace.candidateReference?.runs).toEqual(runs.map(ref));
 const composer=page.locator('#agent-query-form');
 const tagColors=()=>composer.locator('.run-context-chip > i').evaluateAll(nodes=>nodes.map(node=>getComputedStyle(node).backgroundColor));
 const expectCompactTags=async()=>{
  for(const chip of await composer.locator('.run-context-chip:visible').all()){
   const bounds=await chip.boundingBox();
   expect(bounds!.height).toBeLessThanOrEqual(36);
   expect(bounds!.width).toBeLessThan(300);
   expect(await chip.locator('strong').evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
  }
 };
 await expect(composer.locator('.reference-tray-label')).toHaveText('후보 집합 · 8개');
 await composer.locator('.reference-tray-more summary').click();
 const assignedColors=await tagColors();
 expect(assignedColors.slice(0,5)).toEqual(['rgb(65, 104, 232)','rgb(10, 142, 155)','rgb(138, 91, 215)','rgb(224, 132, 42)','rgb(210, 80, 145)']);
 expect(new Set(assignedColors).size).toBe(8);
 await expectCompactTags();
 await composer.locator('.reference-tray').screenshot({path:info.outputPath(`synthetic-chat-references-expanded-${width}.png`)});
 await composer.getByRole('button',{name:`${runs[7].runId} 채팅에서 제거`}).click();
 await expect.poll(()=>workspace.candidateReference?.runs.length).toBe(7);
 await expectCompactTags();
 await composer.locator('.reference-tray').screenshot({path:info.outputPath(`synthetic-chat-references-seven-${width}.png`)});
 await composer.getByRole('button',{name:`${runs[0].runId} 채팅에서 제거`}).click();
 await expect.poll(()=>workspace.candidateReference?.runs.length).toBe(6);
 expect(submissions).toHaveLength(0);expect(workspace.conversation.turns).toEqual(frozen);
 await page.reload();await expect(composer.locator('.reference-tray-label')).toHaveText('후보 집합 · 6개');
 expect(await tagColors()).toEqual(assignedColors.slice(1,7));
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 expect(await composer.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
 const chips=composer.locator('.run-context-chip');
 for(const chip of await chips.all()){
  expect(await chip.locator('strong').evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
  expect(await chip.getByRole('button').evaluate(node=>node.getBoundingClientRect().width)).toBeLessThanOrEqual(32);
 }
 await composer.screenshot({path:info.outputPath(`synthetic-chat-references-${width}.png`)});
 holdReference=true;await add.nth(0).click();await expect.poll(()=>!!releaseReference).toBe(true);
 await add.nth(7).click();
 await composer.getByRole('textbox').fill('첨부한 실험들을 비교해줘');await composer.getByRole('button',{name:'분석',exact:true}).click();
 expect(submissions).toHaveLength(0);releaseReference!();
 await expect.poll(()=>submissions.length).toBe(1);
 await composer.locator('.reference-tray-more summary').click();
 expect(await tagColors()).toEqual([...assignedColors.slice(1,7),assignedColors[0],assignedColors[7]]);
 expect(submissions[0].attachedRunRefs).toEqual([...runs.slice(1,7),runs[0],runs[7]].map(ref));
 expect(submissions[0].baseline).toBeUndefined();expect(errors).toEqual([]);
});
