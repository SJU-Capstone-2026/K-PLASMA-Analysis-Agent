import {expect,test} from '@playwright/test';
import type {AgentMessage,AgentSubmission,RunRef,Snapshot,TurnSnapshot,WorkspaceView} from 'agent';
import contract from '../../../../agent/tests/support/v2/contracts.json' with {type:'json'};
import {syntheticRun} from '../../test/runs';
import {emptyWorkspace,initialTurnUi} from './useConversation';

test('Decision Agent approves criteria, compares the nominated Run and stays separate at all supported widths',async({page},info)=>{
 const stamp='2026-01-01T00:00:00Z';
 const defaultRun=syntheticRun();
 const baseline=syntheticRun(600,4);
 const candidate=syntheticRun(400,4);
 const lowest=syntheticRun(0,4);
 baseline.metrics.meanIonEnergy=80;
 candidate.metrics.meanIonEnergy=70;
 lowest.metrics.meanIonEnergy=25;
 const runs=[defaultRun,baseline,candidate,lowest];
 const ref=({runId,runVersionId}:RunRef)=>({runId,runVersionId});
 const constraints=[
  {metric:'pressure',operator:'eq',value:4,unit:'mTorr'},
  {metric:'sourcePower',operator:'eq',value:300,unit:'W'},
  {metric:'meanIonEnergy',operator:'lte',value:72,unit:'eV'},
  {metric:'ionFlux',operator:'between',min:1.9,max:2.1,unit:'10¹⁸ m⁻²s⁻¹'},
 ];
 const rooms=[{conversationEpoch:1,title:'기존 대화',createdAt:stamp,updatedAt:stamp}];
 let workspace:WorkspaceView={...structuredClone(emptyWorkspace),stateToken:{workspaceEpoch:1,conversationEpoch:1,revision:0},conversations:rooms};
 let demoTurns:TurnSnapshot[]=[];
 let demoMessages:AgentMessage[]=[];
 const posts:AgentSubmission[]=[];
 const requestKeys:(string|undefined)[]=[];
 await page.route('**/api/**',async route=>{
  const request=route.request();
  const path=new URL(request.url()).pathname;
  if(!path.startsWith('/api/'))return route.continue();
  if(path==='/api/decisions')return route.fulfill({json:[]});
  if(path==='/api/runs')return route.fulfill({json:runs});
  if(path==='/api/workspace')return route.fulfill({json:workspace});
  if(path==='/api/workspace/new-conversation'||path.endsWith('/activate')){
   if(path.endsWith('new-conversation'))expect(request.postDataJSON().decisionDemo).toBe(true);
   const isDemo=!path.endsWith('/1/activate');
   const revision=workspace.stateToken.revision+1;
   workspace={...workspace,stateToken:{workspaceEpoch:1,conversationEpoch:isDemo?2:1,revision},
    conversation:{version:1,activeRun:null,turns:isDemo?demoTurns:[],agentGraphVersion:isDemo?'v2':null},agentMessages:isDemo?demoMessages:[],
    conversations:[...rooms,{conversationEpoch:2,title:'시연 검색',createdAt:stamp,updatedAt:stamp,decisionDemo:true}]};
   return route.fulfill({json:workspace});
  }
  if(path==='/api/agent/requests'){
   const body=request.postDataJSON() as AgentSubmission;
   posts.push(body);
   requestKeys.push(request.headers()['idempotency-key']);
   expect(body.stateToken.conversationEpoch).toBe(2);
   expect(body.baseline).toEqual(ref(baseline));
   if(posts.length===1){
    workspace={...workspace,stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1}};
    return route.fulfill({status:409,json:{code:'STALE_CONTEXT',message:'Workspace revision has changed',requestId:'stale'}});
   }
   expect(body.stateToken).toEqual(workspace.stateToken);
   if(posts.length===2)return route.abort('failed');
   const followup=body.text.includes('후속 질문');
   const id=followup?'decision-followup':'decision-search';
   const text=followup?'최저 에너지 후보의 식각 가능성을 먼저 확인하세요.':'검색 근거로 바이어스 전력만 바꿔 볼 수 있습니다.';
   const answerSnapshot={...contract.general_answer,intent:'COMPOSITE_ANSWER',question:body.text,
    review:{status:'PASS',answers:[],reason:null},draft:{fact_ids:[],interpretations:[{id:'i1',text,assumptions:[],evidence_ids:['search:candidates']}],limitations:[]},
    stepResults:[{executionId:'search',stepId:'s1',status:'verified',groupId:'common',reason:null,runRefs:[ref(candidate),ref(lowest)],
     outputs:{toolResult:{kind:'reverse_search',resultStatus:'MATCH',constraints,searchResultVersion:2,
      runsByVersion:Object.fromEntries([candidate,lowest].map(run=>[run.runVersionId,run])),
      commonRunRefs:[ref(candidate),ref(lowest)],objectiveResults:[]}}}]} as unknown as Snapshot;
   demoTurns=[...demoTurns,{id,askedAt:stamp,question:body.text,intent:'COMPOSITE_ANSWER',context:ref(baseline),
    answerRunRefs:[ref(candidate),ref(lowest)],answerSnapshot,ui:initialTurnUi}];
   demoMessages=[...demoMessages,{requestId:id,clientMessageId:null,question:body.text,createdAt:stamp,status:'COMPLETED',turnId:id,submittedRunRefs:[ref(baseline)],
    executionSummary:{durationMs:2000,activities:[
     {activityId:'check',code:'QUESTION_CHECK',phase:'started',seq:1,occurredAt:stamp},
     {activityId:'check',code:'QUESTION_CHECK',phase:'completed',seq:2,occurredAt:stamp},
     {activityId:'plan',code:'PLAN',phase:'completed',seq:3,occurredAt:stamp},
     {activityId:'validate',code:'PLAN_VALIDATE',phase:'completed',seq:4,occurredAt:stamp},
     {activityId:'search',code:'REVERSE_SEARCH',phase:'completed',seq:5,occurredAt:stamp},
     {activityId:'found',code:'SEARCH_COMPLETE',phase:'completed',seq:6,occurredAt:stamp,runCount:2},
     {activityId:'explain',code:'INTERPRET',phase:'completed',seq:7,occurredAt:stamp},
     {activityId:'save',code:'COMMIT',phase:'started',seq:8,occurredAt:stamp},
    ]}}];
   workspace={...workspace,conversation:{...workspace.conversation,turns:demoTurns},agentMessages:demoMessages};
   return route.fulfill({json:{requestId:id,requestRevision:0,status:'COMPLETED',stage:'completed',graphVersion:'v2',
    question:body.text,pendingInput:null,error:null,partialResult:null,turnId:id,answerSnapshot,inputEvents:[]}});
  }
  throw new Error(`Unexpected request ${request.method()} ${path}`);
 });
 await page.emulateMedia({reducedMotion:'no-preference'});
 await page.goto('/');
 await expect(page).toHaveTitle('PLASMATE');
 const subtitle=page.getByText('플라즈마 공정 파트너');
 const logo=page.locator('.brand-mark');
 await expect(logo).toHaveAttribute('src','/plasmate.png');
 await expect.poll(()=>logo.evaluate(image=>(image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
 await page.getByRole('button',{name:'의사결정 Agent',exact:true}).click();
 await expect(page.locator('#current-view-label')).toHaveText('의사결정 Agent');
 await expect(page.getByRole('heading',{name:'의사결정 Agent',exact:true})).toHaveCount(0);
 const welcome=page.getByRole('heading',{name:'다음 실험 조건을 함께 찾아요'});
 const input=page.getByRole('textbox',{name:'공정 데이터에 질문하기'});
 const composerTag=page.locator('.decision-agent .agent-composer .run-context-chip');
 await expect(page.getByRole('button',{name:`${defaultRun.runId} 채팅에서 제거`})).toBeVisible();
 await expect(page.getByRole('group',{name:'분석 실행 모드'})).toHaveCount(0);
 for(const width of [390,800,1008,1440]){
  await page.setViewportSize({width,height:1000});
  if(width===390)await page.getByRole('button',{name:'메뉴 열기'}).click();
  await expect(subtitle).toBeInViewport();
  if(width===390)await page.getByRole('button',{name:'의사결정 Agent',exact:true}).click();
  await expect(welcome).toBeInViewport();
  await expect(page.locator('.decision-agent .agent-welcome')).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
  await expect(input).toBeVisible();
  const [tagBox,inputBox]=await Promise.all([composerTag.boundingBox(),input.boundingBox()]);
  expect(tagBox?.x,`tag and input alignment at ${width}px`).toBe(inputBox?.x);
  expect(inputBox!.y-tagBox!.y-tagBox!.height,`tag to input gap at ${width}px`).toBe(4);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth),`composer scroll width at ${width}px`).toBeLessThanOrEqual(width);
  await page.screenshot({path:info.outputPath(`decision-welcome-${width}.png`),animations:'disabled'});
 }
 await input.fill('@');
 await expect(input).toBeFocused();
 await expect(input).toHaveCSS('box-shadow','none');
 await page.getByRole('option').filter({hasText:baseline.runId}).click();
 await expect(page.getByRole('button',{name:`${baseline.runId} 채팅에서 제거`})).toBeVisible();
 await input.fill('지금 조건에서 효율이 별로야');
 await input.press('Enter');
 await expect(welcome).toHaveCount(0);
 await expect(page.locator('.agent-user-message .run-context-chip')).toHaveText(baseline.runId);
 const checkingQuestion=page.getByRole('status').filter({hasText:'기준 Run과 질문을 확인하고 있어요.'});
 await expect(checkingQuestion).toBeVisible();
 await expect(page.getByRole('heading',{name:'확인이 필요해요'})).toHaveCount(0);
 await expect(page.getByText(/효율.*어떤 쪽/)).toBeVisible();
 await expect(checkingQuestion).toHaveCount(0);
 await page.getByRole('button',{name:/손상 줄이기/}).click();
 const interpreting=page.getByRole('status').filter({hasText:'선택한 목표를 비교 지표로 정리하고 있어요.'});
 await expect(interpreting).toBeVisible();
 await expect(page.getByRole('heading',{name:'이렇게 이해했어요'})).toHaveCount(0);
 await expect(page.getByRole('heading',{name:'이렇게 이해했어요'})).toBeVisible();
 await expect(interpreting).toHaveCount(0);
 await expect(page.getByText('평균 이온 에너지 낮추기',{exact:true})).toHaveCSS('color','rgb(167, 67, 37)');
 await expect(page.getByText('이온 플럭스 유지',{exact:true})).toHaveCSS('color','rgb(35, 77, 151)');
 await expect(page.getByText('이온이 표면에 부딪힐 때의 평균 에너지')).toBeVisible();
 expect(posts).toHaveLength(0);
 await page.getByRole('button',{name:'이 해석으로 후보 찾기'}).click();
 await expect(page.getByRole('alert')).toContainText('로컬 서버에 연결할 수 없습니다');
 await page.getByRole('button',{name:'다시 검색'}).click();
 const candidateHeading=page.getByRole('heading',{name:'조건을 만족한 후보 2개'});
 const activities=page.getByRole('list',{name:'최근 작업 기록'});
 await expect(activities.getByRole('listitem')).toHaveCount(1);
 await expect(activities.getByText('기준 Run과 선택한 목표를 확인했어요')).toBeVisible();
 const searchPlan=activities.getByText('에너지 감소와 플럭스 유지에 맞춰 검색 순서를 정리했어요');
 await expect(searchPlan).toHaveCount(0);
 await expect(candidateHeading).toHaveCount(0);
 await expect(searchPlan).toBeVisible();
 await expect(activities.getByText('목표 범위에 들어오는 Run 2개를 찾았어요')).toBeVisible();
 await expect(activities.getByText('답변을 저장했어요')).toBeVisible();
 await expect(activities.getByRole('listitem')).toHaveCount(6);
 await expect(candidateHeading).toHaveCount(0);
 await expect(candidateHeading).toBeVisible();
 const skeleton=page.locator('.decision-table-skeleton');
 const candidateTable=page.getByRole('table',{name:'후보 Run 비교'});
 const writing=page.locator('.decision-narrative [aria-busy="true"]');
 await expect(skeleton).toBeVisible();
 await expect(skeleton.locator('span')).toHaveCount(5);
 await expect(candidateTable).toBeHidden();
 await expect(page.getByLabel('V2 분석 답변')).toHaveCount(0);
 await expect(candidateTable).toBeVisible();
 await expect(writing).toContainText('검색 근거로 바이어스');
 await expect(page.getByText('검색 근거로 바이어스 전력만 바꿔 볼 수 있습니다.',{exact:true})).toHaveCount(0);
 const progress=page.locator('.agent-progress-complete summary');
 await expect(progress).toHaveText(['2초 동안 작업함›']);
 await progress.first().click();
 await expect(page.getByText('바이어스에 따른 측정값 차이를 해석했어요')).toBeVisible();
 await expect(candidateTable).toBeVisible();
 await expect(skeleton).toBeHidden();
 await expect(page.getByText('검색 근거로 바이어스 전력만 바꿔 볼 수 있습니다.')).toBeVisible();
 expect(posts).toHaveLength(3);
 expect(posts[2]).toEqual(posts[1]);
 expect(requestKeys[1]).toBeTruthy();
 expect(requestKeys[2]).toBe(requestKeys[1]);
 expect(posts[0].text).toContain('평균 이온 에너지 72 eV 이하');
 await input.fill('그럼 에너지가 가장 낮은 후보로 하면 되겠네?');
 await input.press('Enter');
 await expect(activities.getByText('앞서 찾은 후보와 후속 질문을 확인했어요')).toBeVisible();
 await expect(activities.getByText('같은 조건으로 Run 2개를 다시 찾았어요')).toBeVisible();
 const tradeoffTable=page.getByRole('table',{name:'선택지별 장단점'});
 await expect(activities.getByText('답변을 저장했어요')).toBeVisible();
 await expect(activities.getByRole('listitem')).toHaveCount(5);
 await expect(tradeoffTable).toHaveCount(0);
 await expect(skeleton).toBeVisible();
 await expect(page.getByLabel('V2 분석 답변')).toHaveCount(1);
 await expect(tradeoffTable).toBeVisible();
 await expect(writing).toContainText('최저 에너지 후보의');
 await expect(progress).toHaveCount(2);
 await progress.last().click();
 await expect(page.getByText('후속 질문에 맞춰 후보별 장점과 주의점을 정리했어요')).toBeVisible();
 await expect(page.getByText('최저 에너지 후보의 식각 가능성을 먼저 확인하세요.')).toBeVisible();
 await expect(page.getByText(/식각에 필요한 최소 이온 에너지 기준/)).toBeVisible();
 await page.getByRole('button',{name:`${candidate.runId} 선택`}).click();
 const choice=page.locator('.agent-user-message').filter({hasText:'이 조건으로 다음 실험을 해볼게요.'});
 await expect(choice.getByText(candidate.runId)).toBeVisible();
 await expect(page.getByRole('heading',{name:'다음 실험에서 확인할 조건'})).toBeVisible();
 await expect(page.getByText('600 W → 400 W')).toBeVisible();
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.getByRole('button',{name:'분석 Agent',exact:true}).click();
 await expect(page.getByRole('group',{name:'분석 실행 모드'})).toBeVisible();
 await page.getByRole('button',{name:'의사결정 Agent',exact:true}).click();
 await expect(choice.getByText(candidate.runId)).toBeVisible();
 await expect(tradeoffTable).toBeVisible();
 await expect(skeleton).toHaveCount(0);
 await expect(writing).toHaveCount(0);
 await expect(progress).toHaveCount(2);
 for(const width of [390,800,1008,1440]){
  await page.setViewportSize({width,height:1000});
  await expect(page.getByRole('button',{name:`${lowest.runId} 선택`})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth),`page scroll width at ${width}px`).toBeLessThanOrEqual(width);
  await page.getByRole('heading',{name:'다음 실험에서 확인할 조건'}).scrollIntoViewIfNeeded();
  await page.screenshot({path:info.outputPath(`decision-${width}.png`),animations:'disabled'});
 }
 await page.getByRole('button',{name:'초기화',exact:true}).click();
 await expect(welcome).toBeInViewport();
});
