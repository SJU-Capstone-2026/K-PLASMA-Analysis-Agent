import {expect, test, type Page} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import type {AgentRequestView, RunRef, RunSummary, WorkspaceView} from 'agent';

const api = process.env.KPLASMA_E2E_API;
const output = process.env.KPLASMA_E2E_OUTPUT;
const graphVersion=process.env.KPLASMA_E2E_GRAPH_VERSION??'v2';
if(!['v2','v2_localLLM'].includes(graphVersion))throw new Error('Unsupported graph version');
if (!api || !output) throw new Error('An isolated artificial-data backend and output directory are required.');
let apiHeaders:Record<string,string>={};
const browserErrors:string[]=[];
const observations:Record<string,unknown>[]=[];
let currentCase='setup';

function observe(kind:string,detail:Record<string,unknown>={}){
  observations.push({kind,case:currentCase,at:Date.now(),...detail});
}
function observeWorkspace(source:string,path:string,status:number,value:unknown){
  const body=value as Partial<WorkspaceView>;
  const token=body.stateToken;
  observe('workspace-response',{source,path,status,stateToken:token?{
    workspaceEpoch:token.workspaceEpoch,conversationEpoch:token.conversationEpoch,revision:token.revision,
  }:null,graphVersion:body.conversation?.agentGraphVersion??null});
}

test.beforeEach(async({page})=>{
  await page.addInitScript(()=>{
    type Row=Record<string,unknown>;
    const key='kplasma.e2e.input-observations';
    let rows:Row[]=[];
    try{rows=JSON.parse(sessionStorage.getItem(key)??'[]');}catch{ /* about:blank has no origin storage. */ }
    const documentId=1+Math.max(0,...rows.map(row=>Number(row.documentId)||0));
    const ids=new WeakMap<Node,number>();let nextId=0;
    const id=(node:Node|null)=>{if(!node)return null;if(!ids.has(node))ids.set(node,++nextId);return ids.get(node);};
    const state=()=>{
      const input=document.querySelector<HTMLTextAreaElement>('#agent-query');
      const submit=document.querySelector<HTMLButtonElement>('#agent-query-form [type="submit"]');
      return {inputId:id(input),formId:id(input?.form??null),valueLength:input?.value.length??null,
        disabled:input?.disabled??null,valid:input?.validity.valid??null,submitDisabled:submit?.disabled??null};
    };
    const record=(kind:string,extra:Row={})=>{
      rows.push({kind,at:Date.now(),time:performance.now(),documentId,...state(),...extra});
      if(rows.length>2000)rows.splice(0,rows.length-2000);
    };
    Object.assign(window,{__kplasmaInputObservations:rows});
    const value=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!;
    Object.defineProperty(HTMLTextAreaElement.prototype,'value',{...value,set(next:string){
      const beforeLength=String(value.get!.call(this)).length;
      value.set!.call(this,next);
      if(this.id==='agent-query')record('value-write',{targetId:id(this),beforeLength,afterLength:this.value.length});
    }});
    for(const event of ['beforeinput','input','change','invalid','submit','focusin','focusout','click']){
      document.addEventListener(event,value=>{
        const target=value.target;
        if(target instanceof Element&&(target.id==='agent-query'||target.closest('#agent-query-form'))){
          record(event,{trusted:value.isTrusted,targetTag:target.tagName,
            inputType:value instanceof InputEvent?value.inputType:null});
        }
      },true);
    }
    let last='';
    new MutationObserver(()=>{
      const next=JSON.stringify(state());
      if(next!==last){last=next;record('form-state');}
    }).observe(document,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled']});
    for(const kind of ['DOMContentLoaded','pageshow','pagehide','beforeunload']){
      window.addEventListener(kind,()=>{
        record(kind);
        if(kind==='pagehide'||kind==='beforeunload'){
          try{sessionStorage.setItem(key,JSON.stringify(rows));}catch{ /* diagnostics never control the app. */ }
        }
      });
    }
    record('document-init');
  });
  const record=(message:string)=>browserErrors.push(message
    .replace(/(?:Bearer\s+|KPLASMA_LOCAL_SESSION=)[A-Za-z0-9_.-]+/g,'[redacted]').slice(0,600));
  page.on('pageerror',error=>record(error.message));
  page.on('console',message=>{if(message.type()==='error')record(message.text());});
  page.on('requestfailed',request=>record(`${new URL(request.url()).pathname}: ${request.failure()?.errorText}`));
  page.on('framenavigated',frame=>{if(frame===page.mainFrame())observe('navigation',{path:new URL(frame.url()).pathname});});
  page.on('response',async response=>{
    const path=new URL(response.url()).pathname;
    if(path==='/api/workspace'||path==='/api/workspace/new-conversation'){
      try{observeWorkspace('browser',path,response.status(),await response.json());}
      catch{observe('workspace-response-unreadable',{path,status:response.status()});}
    }
  });
  page.on('websocket',socket=>socket.on('framereceived',frame=>{
    try{
      const body=JSON.parse(String(frame.payload));
      if(['connected','update','full-reload','prune'].includes(body.type))observe('hmr',{type:body.type});
    }catch{ /* Only event types are observed; frames and URLs are never retained. */ }
  }));
});
test.afterEach(async({page})=>{
  let inputObservations:unknown[]=[];
  try{inputObservations=await page.evaluate(()=>(window as Window&{
    __kplasmaInputObservations?:unknown[];
  }).__kplasmaInputObservations??[]);}catch{observe('input-observations-unavailable');}
  await writeFile(join(output!,'browser-diagnostics.json'),JSON.stringify({graphVersion,errors:browserErrors,
    observations,inputObservations},null,2),{mode:0o600});
});

test.beforeEach(async({context,baseURL})=>{
  if(graphVersion!=='v2_localLLM')return;
  const connection=process.env.KPLASMA_E2E_CONNECTION;
  if(!connection||!baseURL)throw new Error('LOCAL_SYNTHETIC_SESSION_REQUIRED');
  let metadata;
  try{metadata=JSON.parse(await readFile(connection,'utf8'));}
  catch{throw new Error('LOCAL_SYNTHETIC_SESSION_INVALID');}
  const uiOrigin=new URL(baseURL).origin;
  const cookie=/^KPLASMA_LOCAL_SESSION=([A-Za-z0-9_-]{32,128})$/.exec(metadata.sessionCookie??'');
  if(metadata.graphVersion!==graphVersion||metadata.data!=='artificial-only'
    ||!['synthetic','real_model_on_artificial_data'].includes(metadata.evaluationMode)
    ||metadata.url!==api||metadata.uiOrigin!==uiOrigin||!cookie)throw new Error('LOCAL_SYNTHETIC_SESSION_INVALID');
  apiHeaders={Origin:uiOrigin,'Sec-Fetch-Site':'same-site'};
  // Seed HttpOnly state before this context makes its first data request or opens the app.
  try{
    await context.addCookies([{name:'KPLASMA_LOCAL_SESSION',value:cookie[1],domain:new URL(uiOrigin).hostname,
      path:'/api',httpOnly:true,sameSite:'Strict',secure:false}]);
  }catch{throw new Error('LOCAL_SYNTHETIC_SESSION_CONTEXT_FAILED');}
});

async function apiCall(page:Page,path:string,data?:unknown){
  try{
    const response=data===undefined?await page.request.get(`${api}${path}`,{headers:apiHeaders}):
      await page.request.post(`${api}${path}`,{data,headers:apiHeaders});
    if(path==='/api/workspace'||path==='/api/workspace/new-conversation'){
      observeWorkspace('test',path,response.status(),await response.json());
    }
    return response;
  }catch(error){
    // Playwright's raw API error can echo request cookies in its call log.
    // eslint-disable-next-line preserve-caught-error -- Playwright's cause can expose private session cookies.
    if(graphVersion==='v2_localLLM')throw new Error('LOCAL_SYNTHETIC_API_REQUEST_FAILED');
    throw error;
  }
}

const cases = [
  {id: 'concept', question: 'IED가 뭐야? 이온 에너지 분포라는 개념을 간단히 설명해줘.'},
  {id: 'strict-search', question: '이온 플럭스가 40보다 높은 실제 Run을 모두 찾아줘.'},
  {id: 'mixed-concept', question: '이온 플럭스가 40보다 높은 실제 Run을 찾고, 이온 플럭스의 개념도 설명해줘.'},
  {id: 'nested', question: '비교할 두 Run은 내가 고를게. 선택한 두 Run 모두보다 이온 플럭스가 높은 후보를 찾아줘.'},
];

async function ask(page: Page, text: string): Promise<AgentRequestView> {
  const submit=page.locator('#agent-query-form [type="submit"]');
  await expect(submit).toBeEnabled();
  const input=page.getByRole('textbox', {name: '공정 데이터에 질문하기'});
  observe('before-fill',{expectedLength:text.length});
  await input.fill(text);
  observe('fill-returned');
  await expect(input).toHaveValue(text);
  const accepted = page.waitForResponse(r => new URL(r.url()).pathname === '/api/agent/requests'
    && r.request().method() === 'POST',{timeout:20000});
  await expect(submit).toBeEnabled();
  observe('before-click');
  await submit.click();
  observe('click-returned');
  const response = await accepted;
  expect([200, 202]).toContain(response.status());
  return response.json();
}

async function terminal(page: Page, id: string, revision = 0): Promise<AgentRequestView> {
  let result!: AgentRequestView;
  await expect.poll(async () => {
    const response = await apiCall(page,`/api/agent/requests/${id}`);
    result = await response.json();
    return result.requestRevision >= revision ? result.status : 'WAITING';
  }, {timeout: graphVersion === 'v2_localLLM' ? 720000 : 100000, intervals: [300, 1000]})
    .toMatch(/COMPLETED|NEEDS_INPUT|FAILED|CANCELLED/);
  return result;
}

async function pick(page: Page, runs: RunSummary[]) {
  const rows = page.locator('.v1-run-selection');
  for (const run of runs) {
    await rows.getByRole('checkbox', {name: new RegExp(run.runId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))}).check();
  }
  const baseline = rows.getByLabel(/비교 기준/);
  if (await baseline.count()) {
    if (!await baseline.isVisible()) await rows.getByText('선택 옵션', {exact: true}).click();
    const values = await baseline.first().locator('option').evaluateAll(items =>
      items.map(item => (item as HTMLOptionElement).value).filter(Boolean));
    if (values.length) await baseline.first().selectOption(values[0]);
  }
  await page.getByRole('button', {name: '선택한 실험으로 계속'}).click();
}

test('selected graph browser answers on artificial data', async ({page}) => {
  const allRuns = await (await apiCall(page,'/api/runs')).json() as RunSummary[];
  const runs = allRuns.filter(run => run.catalogStatus === 'READY' && run.sourcePower === 100).sort((a, b) => a.metrics.ionFlux - b.metrics.ionFlux);
  expect(runs.map(run => run.metrics.ionFlux), 'synthetic boundary and its two sides').toEqual([1, 40, 60]);
  const selected = runs.slice(0, 2);
  const expected = runs.filter(run => run.metrics.ionFlux > Math.max(...selected.map(r => r.metrics.ionFlux)))
    .map(r => r.runId).sort();
  const rows = [];
  for (const item of cases) {
    currentCase=item.id;
    observe('case-start');
    const before = await (await apiCall(page,'/api/workspace')).json() as WorkspaceView;
    await apiCall(page,'/api/workspace/new-conversation',{stateToken:before.stateToken});
    await page.goto('/?view=agent');
    const selector = page.getByRole('combobox', {name: 'Agent 버전'});
    await expect(selector).toBeVisible();
    await expect(page.getByRole('textbox', {name: '공정 데이터에 질문하기'})).toBeEnabled();
    if(graphVersion==='v2_localLLM')await expect(selector).toHaveValue(graphVersion);
    else {await expect(selector).toBeEnabled();await selector.selectOption(graphVersion);}
    const accepted = await ask(page, item.question);
    expect(accepted.graphVersion).toBe(graphVersion);
    let result = await terminal(page, accepted.requestId);
    await writeFile(join(output!, `v2-${item.id}-terminal.json`), JSON.stringify(result, null, 2));
    if (item.id === 'nested') {
      expect.soft(result.status, 'user must choose the two Runs before execution').toBe('NEEDS_INPUT');
      expect.soft(result.pendingInput?.type).toBe('run_selection');
      if (result.status === 'NEEDS_INPUT' && result.pendingInput?.type === 'run_selection') {
        await pick(page, selected);
        result = await terminal(page, accepted.requestId, result.requestRevision + 1);
        await writeFile(join(output!, `v2-${item.id}-terminal.json`), JSON.stringify(result, null, 2));
      }
    }
    const snapshot = result.answerSnapshot as Record<string, unknown> | null;
    expect.soft(snapshot?.graphVersion, item.id).toBe(graphVersion);
    expect.soft(snapshot?.implementationId, item.id).toBe(graphVersion);
    expect.soft(snapshot?.executionStatus, item.id).toBe('COMPLETE');
    expect.soft(snapshot?.hasIncompleteWork, item.id).toBe(false);
    const steps = (snapshot?.stepResults ?? []) as {outputs: {toolResult?: {kind?: string; commonRunIds?: string[]; usedRunRefs?: RunRef[]}}}[];
    if (item.id === 'nested') {
      const comparison = steps.find(step => step.outputs.toolResult?.kind === 'compare_runs')?.outputs.toolResult;
      expect.soft(comparison?.usedRunRefs, 'comparison must use exactly the selected versions')
        .toEqual(selected.map(({runId, runVersionId}) => ({runId, runVersionId})));
    }
    const search = [...steps].reverse().find(s => s.outputs.toolResult?.kind === 'reverse_search')?.outputs.toolResult;
    const actual = [...(search?.commonRunIds ?? [])].sort();
    const strictExpected = runs.filter(run => run.metrics.ionFlux > 40).map(run => run.runId).sort();
    let issue: string | null = null;
    if (result.status !== 'COMPLETED') issue = result.error?.code ?? result.status;
    else if (item.id === 'concept' && snapshot?.intent !== 'GENERAL_ANSWER' && snapshot?.kind !== 'generate_answer') issue = '일반 개념 경로 오분류';
    else if (item.id !== 'concept' && (search?.kind !== 'reverse_search'
        || JSON.stringify(actual) !== JSON.stringify(item.id === 'nested' ? expected : strictExpected))) {
      issue = '요청한 검색 또는 예상 후보가 누락됨';
    }
    expect.soft(issue, item.id).toBeNull();
    const activities = result.progress?.activities ?? result.executionSummary?.activities ?? [];
    const planReviews = activities.filter(a => a.code === 'PLAN_REVIEW' && a.phase === 'started');
    if (item.id !== 'concept') {
      expect.soft(planReviews.length, `${item.id}: live evaluations require Decisions plan review`).toBeGreaterThan(0);
    }
    if (process.env.KPLASMA_V2_MOCK === 'true') {
      expect.soft(planReviews, `${item.id}: structured HITL must reuse its plan review`)
        .toHaveLength(1);
      expect.soft(activities.filter(a => a.code === 'REVIEW'), `${item.id}: no experimental interpretation`).toHaveLength(0);
    }
    const answer = page.locator('.agent-response').last();
    if (item.id === 'concept' && result.status === 'COMPLETED') {
      await expect.soft(answer.locator('.v1-markdown')).toBeVisible();
    }
    if (item.id === 'mixed-concept' && result.status === 'COMPLETED') {
      await expect.soft(answer.getByRole('region', {name: '개념 설명'})).toContainText('이온 플럭스');
    }
    const visible = result.status === 'COMPLETED' ? await answer.innerText({timeout: 12000})
      : await page.locator('.agent-page').innerText();
    rows.push({id: item.id, question: item.question, graphVersion,
      evaluationMode:process.env.KPLASMA_V2_MOCK==='true'?'synthetic':'real_model_on_artificial_data',pass:issue===null,
      issue, status: result.status, visible, actual, snapshot, activities,
      expected: item.id === 'nested' ? expected : strictExpected});
    await writeFile(join(output!, 'v2-answers.json'), JSON.stringify(rows, null, 2));
    if (result.status === 'COMPLETED') {
      for (const width of [390, 800, 1008, 1440]) {
        await page.setViewportSize({width, height: 1000});
        const widthOk = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
        expect.soft(widthOk, `page must not overflow at ${width}px`).toBe(true);
        await answer.scrollIntoViewIfNeeded();
        await page.screenshot({path: join(output!, `v2-${item.id}-${width}.png`), animations: 'disabled'});
      }
    }
  }
});

test('Decision Agent runs approved @ searches and candidate selection through standard V2',async({page})=>{
  test.skip(graphVersion!=='v2'||process.env.KPLASMA_V2_MOCK!=='true','Scripted V2 integration only');
  const runs=await (await page.request.get(`${api}/api/runs`)).json() as RunSummary[];
  const baseline=runs.find(run=>run.pressure===6&&run.sourcePower===300&&run.biasPower===600)!;
  const alternative=runs.find(run=>run.pressure===6&&run.sourcePower===100)!;
  const candidate=runs.find(run=>run.pressure===6&&run.sourcePower===300&&run.biasPower===400)!;
  expect(baseline.metrics.meanIonEnergy).toBe(100);
  const before=await (await page.request.get(`${api}/api/workspace`)).json() as WorkspaceView;
  await page.goto('/');
  await page.getByRole('button',{name:'의사결정 Agent',exact:true}).click();
  const input=page.getByRole('textbox',{name:'공정 데이터에 질문하기'});
  await expect(page.getByRole('button',{name:`${baseline.runId} 채팅에서 제거`})).toBeVisible();
  async function searchFor(run:RunSummary){
    await input.fill('@');
    const option=page.getByRole('option').filter({hasText:run.runId});
    await expect(option).toBeVisible();
    await option.click({timeout:7000});
    await expect(input).toHaveValue('');
    await expect(page.getByRole('button',{name:`${run.runId} 채팅에서 제거`})).toBeVisible();
    await input.fill('지금 조건에서는 효율이 낮아. 어떻게 개선할까?');
    await input.press('Enter');
    await page.getByRole('button',{name:/손상 줄이기/}).click({timeout:7000});
    const accepted=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/agent/requests'&&response.request().method()==='POST',{timeout:15000});
    await page.getByRole('button',{name:'이 해석으로 후보 찾기'}).click({timeout:7000});
    const response=await accepted;
    expect(response.ok()).toBe(true);
    const request=await response.json() as AgentRequestView;
    expect(request.graphVersion).toBe('v2');
    expect(request.conversationEpoch).not.toBe(before.stateToken.conversationEpoch);
    const result=await terminal(page,request.requestId);
    expect(result.status).toBe('COMPLETED');
    expect(result.answerSnapshot?.executionStatus).toBe('COMPLETE');
    if(run===baseline)expect(result.answerSnapshot?.review).toMatchObject({status:'PASS'});
    const reviews=(result.progress?.activities??result.executionSummary?.activities??[])
      .filter(activity=>activity.code==='PLAN_REVIEW'&&activity.phase==='started');
    expect(reviews).toHaveLength(1);
  }
  await searchFor(baseline);
  await expect(page.getByRole('heading',{name:'조건을 만족한 후보 3개'})).toBeVisible({timeout:12000});
  const progress=page.locator('.agent-progress-complete summary');
  await expect(progress).toHaveCount(1);
  await expect(page.getByText(/평균 이온 에너지도 낮게 관찰됐어요/)).toBeVisible();
  await input.fill('에너지가 가장 낮은 후보를 고르면 될까?');
  await input.press('Enter');
  await expect(page.getByRole('table',{name:'선택지별 장단점'})).toBeVisible({timeout:12000});
  await expect(page.getByText(/평균 이온 에너지가 가장 낮은 조건부터 고를 필요는 없어요/)).toBeVisible();
  await expect(progress).toHaveCount(2);
  await page.getByRole('button',{name:`${candidate.runId} 선택`,exact:true}).click({timeout:7000});
  await expect(page.locator('.agent-user-message').filter({hasText:'이 조건으로 다음 실험을 해볼게요.'})).toContainText(candidate.runId);
  await expect(page.getByRole('heading',{name:'다음 실험에서 확인할 조건'})).toBeVisible();
  await searchFor(alternative);
  await expect(page.getByRole('heading',{name:'조건을 만족한 후보 0개'})).toBeVisible({timeout:12000});
  await page.getByRole('button',{name:'분석 Agent',exact:true}).click();
  await expect(page.getByRole('combobox',{name:'Agent 버전'})).toBeVisible();
  const after=await (await page.request.get(`${api}/api/workspace`)).json() as WorkspaceView;
  expect(after.stateToken.conversationEpoch).toBe(before.stateToken.conversationEpoch);
  expect(after.conversation).toEqual(before.conversation);
});
