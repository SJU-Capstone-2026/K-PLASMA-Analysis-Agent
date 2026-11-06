import {expect,test,type Page,type Route} from '@playwright/test';
import type {AgentActivity,AgentEventPage,AgentProgressSnapshot,AgentPublicEvent,AgentRequestView,AgentResultProjection,Snapshot,TurnSnapshot,WorkspaceView} from 'agent';
import general from '../../../../agent/tests/support/v2/contracts.json' with {type:'json'};
import {syntheticRun} from '../../test/runs';
import {emptyWorkspace,initialTurnUi} from './useConversation';

// All prose, Runs, and histories below are artificial. No external model or experiment data is used.
const now='2026-11-06T00:00:00Z';
const executionId='10000000-0000-4000-8000-000000000001';
const plainSnapshot=(value:unknown):Snapshot=>JSON.parse(JSON.stringify(value));
const savedTurn=(id:string,text:string):TurnSnapshot=>({id,askedAt:now,question:`인공 기록 ${id}`,intent:'GENERAL_ANSWER',
 context:null,answerRunRefs:[],answerSnapshot:{...general.general_answer,answer:text},ui:structuredClone(initialTurnUi)});
type Write=Pick<AgentPublicEvent,'type'|'payload'>;
type WaitingStream={route:Route;after:number;resolve:()=>void;reject:(error:unknown)=>void};

class ControlledAgent {
 readonly events:AgentPublicEvent[]=[];
 readonly projections=new Map<number,AgentResultProjection>();
 readonly waiting=new Set<WaitingStream>();
 readonly errors:string[]=[];
 readonly history:TurnSnapshot[];
 readonly other=savedTurn('other-room','다른 방에 저장된 답변입니다.');
 selectedRoom=1;
 revision=0;
 submissions=0;
 cancellations=0;
 sseConnections=0;
 request:AgentRequestView={requestId:'controlled-stream',requestRevision:0,workspaceEpoch:1,conversationEpoch:1,
  status:'RUNNING',stage:'interpret',graphVersion:'v2',question:'인공 Run 조건과 의미를 설명해줘',pendingInput:null,
  error:null,partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[],
  progress:{lastEventSeq:0,activities:[],answer:null,resultRevision:null}};

 constructor(history:TurnSnapshot[]=[]){this.history=[...history];}

 workspace():WorkspaceView {
  const inOriginal=this.selectedRoom===1;
  const terminal=this.request.status==='FAILED'||this.request.status==='CANCELLED';
  return {...structuredClone(emptyWorkspace),stateToken:{workspaceEpoch:1,conversationEpoch:this.selectedRoom,revision:this.revision},
   conversation:{version:1,agentGraphVersion:'v2',activeRun:null,turns:inOriginal?this.history:[this.other]},
   conversations:[{conversationEpoch:1,title:'작업 중인 방',createdAt:now,updatedAt:now},
    {conversationEpoch:2,title:'다른 방의 기록',createdAt:now,updatedAt:now}],
   agentMessages:inOriginal?[{requestId:this.request.requestId,clientMessageId:'controlled-client',createdAt:now,
    question:this.request.question,submittedRunRefs:[],status:this.request.status,turnId:this.request.turnId,
    executionSummary:this.request.executionSummary}]:[],
   activeAgentRequest:inOriginal&&!terminal&&this.request.status!=='COMPLETED'?this.request:null,
   failedAgentRequest:inOriginal&&terminal?this.request:null};
 }

 activities():AgentActivity[]{
  return this.events.flatMap(event=>event.type==='activity'?[{...event.payload,seq:event.seq,occurredAt:event.occurredAt} as unknown as AgentActivity]:[]);
 }

 publish(...writes:Write[]){
  const added=writes.map((write,index)=>({schemaVersion:1 as const,requestId:this.request.requestId,workspaceEpoch:1,
   conversationEpoch:1,requestRevision:this.request.requestRevision,seq:this.events.length+index+1,occurredAt:now,...write}));
  this.events.push(...added);
  this.flush();
  return added;
 }

 result(toolResult:Snapshot){
  const event=this.publish({type:'results.ready',payload:{executionIds:[executionId]}})[0];
  const projection:AgentResultProjection={resultRevision:event.seq,results:[{stepId:'lookup',executionId,runRefs:[],toolResult}]};
  this.projections.set(event.seq,projection);
  return projection;
 }

 snapshot(progress:AgentProgressSnapshot){this.request={...this.request,progress};}

 finish(text:string){
  const projection=[...this.projections.values()].at(-1);
  const answerSnapshot=plainSnapshot({...general.general_answer,question:this.request.question,answer:text,
   intent:projection?'COMPOSITE_ANSWER':'GENERAL_ANSWER',
   stepResults:projection?.results.map(result=>({stepId:result.stepId,executionId:result.executionId,status:'verified',
    outputs:{toolResult:result.toolResult},runRefs:result.runRefs,groupId:null,reason:null}))??[],
   draft:projection?{fact_ids:[],interpretations:[{id:'meaning',text,evidence_ids:[],assumptions:[]}],limitations:[]}:
    {paragraphs:[text],sources:[]}});
  const summary={durationMs:38_000,activities:this.activities()};
  this.request={...this.request,status:'COMPLETED',stage:'completed',turnId:this.request.requestId,answerSnapshot,executionSummary:summary};
  this.history.push({...savedTurn(this.request.requestId,text),question:this.request.question,
   intent:projection?'COMPOSITE_ANSWER':'GENERAL_ANSWER',answerSnapshot});
  this.revision++;
  this.publish({type:'request.state',payload:{status:'COMPLETED',stage:'completed',turnId:this.request.requestId,durationMs:38_000}});
 }

 private eventPage(after:number):AgentEventPage {
  return {events:this.events.filter(event=>event.seq>after),lastEventSeq:this.events.at(-1)?.seq??0,status:this.request.status,
   requestRevision:this.request.requestRevision,workspaceEpoch:1,conversationEpoch:1,hasMore:false};
 }

 private async deliver(waiter:WaitingStream){
  const events=this.eventPage(waiter.after).events;
  // route.fulfill buffers the response, so each controlled batch closes and reconnects at its cursor.
  await waiter.route.fulfill({status:200,contentType:'text/event-stream',headers:{'Cache-Control':'no-cache'},
   body:events.map(event=>`id: ${event.seq}\ndata: ${JSON.stringify(event)}\n\n`).join('')});
 }

 private flush(){
  for(const waiter of this.waiting){
   if(!this.eventPage(waiter.after).events.length)continue;
   this.waiting.delete(waiter);
   void this.deliver(waiter).then(waiter.resolve,waiter.reject);
  }
 }

 async install(page:Page){
  page.on('pageerror',error=>this.errors.push(error.message));
  page.on('requestfailed',request=>{
   for(const waiter of this.waiting)if(waiter.route.request()===request){this.waiting.delete(waiter);waiter.resolve();}
  });
  page.on('close',()=>{for(const waiter of this.waiting)waiter.resolve();this.waiting.clear();});
  await page.route('**/api/**',async route=>{
   const request=route.request(),url=new URL(request.url()),path=url.pathname;
   if(!path.startsWith('/api/'))return route.continue();
   if(path==='/api/runs')return route.fulfill({json:[syntheticRun()]});
   if(path==='/api/decisions')return route.fulfill({json:[]});
   if(path==='/api/workspace'&&request.method()==='GET')return route.fulfill({json:this.workspace()});
   if(path==='/api/agent/requests'){
    this.submissions++;
    return route.fulfill({status:409,json:{code:'REQUEST_IN_PROGRESS',message:'이미 진행 중인 인공 요청입니다.',requestId:this.request.requestId}});
   }
   if(path===`/api/agent/requests/${this.request.requestId}`)return route.fulfill({json:this.request});
   if(path.endsWith('/results')){
    const result=this.projections.get(Number(url.searchParams.get('resultRevision')));
    if(!result)throw new Error(`Unexpected result revision ${url.searchParams.get('resultRevision')}`);
    return route.fulfill({json:result});
   }
   if(path.endsWith('/events')){
    const after=Number(url.searchParams.get('after')??0);
    if(url.searchParams.get('format')==='json')return route.fulfill({json:this.eventPage(after)});
    this.sseConnections++;
    if(this.eventPage(after).events.length)return this.deliver({route,after,resolve:()=>{},reject:()=>{}});
    if(['COMPLETED','FAILED','CANCELLED'].includes(this.request.status))return route.fulfill({status:204});
    return new Promise<void>((resolve,reject)=>this.waiting.add({route,after,resolve,reject}));
   }
   if(path.endsWith('/cancel')){
    this.cancellations++;
    this.request={...this.request,status:'CANCELLED',stage:'cancelled',executionSummary:{durationMs:1500,activities:this.activities()}};
    this.revision++;
    this.publish({type:'request.state',payload:{status:'CANCELLED',stage:'cancelled',turnId:null,durationMs:1500}});
    return route.fulfill({json:this.request});
   }
   if(path.startsWith('/api/workspace/conversations/')&&path.endsWith('/activate')){
    this.selectedRoom=Number(path.split('/').at(-2));this.revision++;
    return route.fulfill({json:this.workspace()});
   }
   throw new Error(`Unexpected API ${request.method()} ${path}`);
  });
 }
}

const draftStart:Write={type:'answer.start',payload:{streamId:'first',answerRevision:1,mode:'interpretation',rewrite:false}};
const delta=(text:string,streamId='first',answerRevision=1,chunkIndex=0):Write=>({type:'answer.delta',
 payload:{streamId,answerRevision,blockId:'interpretations:0',text,chunkIndex}});

for(const width of [390,800,1008,1440])test(`inline work, real draft, rewrite, and saved summary at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1000});
 const fixture=new ControlledAgent();await fixture.install(page);await page.goto('/');
 await expect(page.getByRole('region',{name:'진행 중인 분석 요청'})).toBeVisible();
 await expect.poll(()=>fixture.sseConnections).toBeGreaterThan(0);
 fixture.publish(
  {type:'activity',payload:{activityId:'question',code:'QUESTION_CHECK',phase:'completed'}},
  {type:'activity',payload:{activityId:'plan',code:'PLAN',phase:'completed'}},
  {type:'activity',payload:{activityId:'validate',code:'PLAN_VALIDATE',phase:'completed'}},
  {type:'activity',payload:{activityId:'search',code:'SEARCH_COMPLETE',phase:'completed',runCount:11}},
  {type:'activity',payload:{activityId:'compare',code:'COMPARE_RUNS',phase:'started',runCount:11,metricIds:['pressure','ionFlux']}});
 const pending=page.getByRole('region',{name:'진행 중인 분석 요청'});
 await expect(pending.getByRole('list',{name:'최근 작업 기록'}).getByRole('listitem')).toHaveCount(4);
 await expect(pending.getByRole('heading',{name:'분석 중',exact:true})).toHaveCount(0);
 await expect(pending).not.toHaveClass(/\bpanel\b/);
 const questionFont=await page.locator('.agent-user-message p').last().evaluate(element=>getComputedStyle(element).fontSize);
 expect(questionFont).toBe('15px');
 await expect(pending.locator('.agent-progress')).toHaveCSS('font-size','14px');
 await expect(pending.getByRole('button',{name:'분석 취소',exact:true})).toHaveCount(0);
 await expect(page.locator('#agent-query-form').getByRole('button',{name:'분석 중지',exact:true})).toBeEnabled();
 await pending.locator('.agent-progress-history summary').click();
 await expect(pending.getByText('질문과 선택한 Run을 확인했어요')).toBeVisible();
 fixture.result(plainSnapshot({kind:'forward_lookup',resultStatus:'EXACT',candidates:Array.from({length:11},(_,index)=>syntheticRun(600,index+1))}));
 fixture.publish(draftStart,delta(String.raw`처음 해석입니다. \(\Gamma_i`));
 const preview=page.getByRole('region',{name:'작성 중인 답변'});
 await expect(preview).toContainText('처음 해석입니다.');
 await expect(preview.locator('.v1-markdown p').first()).toHaveCSS('font-size',questionFont);
 await expect(preview.locator('.agent-stream-status')).toHaveCSS('font-size','14px');
 await expect(preview.locator('.katex')).toHaveCount(0);
 await expect(preview).not.toContainText('Gamma_i');
 await expect(preview).toHaveAttribute('aria-live','off');
 await expect(pending.getByRole('table',{name:'검색 Run 목록'})).toBeVisible();
 await expect(pending.getByRole('columnheader',{name:'작업'})).toHaveCount(0);
 await pending.getByRole('button',{name:'다음',exact:true}).click();
 await expect(pending.getByText('11–11 / 11개')).toBeVisible();
 fixture.publish(delta(String.raw` = n_i u_i\)`, 'first',1,1),
  {type:'activity',payload:{activityId:'review',code:'REVIEW',phase:'started'}});
 await expect(preview.locator('.katex annotation')).toHaveText(String.raw`\Gamma_i = n_i u_i`);
 await expect(preview).toContainText('검토 중');
 fixture.publish({type:'answer.reset',payload:{streamId:'first',answerRevision:1,reason:'REWRITE'}},
  {type:'answer.start',payload:{streamId:'revised',answerRevision:2,mode:'interpretation',rewrite:true}});
 await expect(preview).toContainText('수정 중');
 await expect(preview).not.toContainText('처음 해석입니다.');
 await expect(pending.getByRole('table',{name:'검색 Run 목록'})).toBeVisible();
 fixture.publish(delta('수정된 해석을 작성하고 있습니다.','revised',2));
 await expect(preview).toContainText('수정된 해석을 작성하고 있습니다.');
 expect(fixture.request.status).toBe('RUNNING');
 fixture.finish('검토를 마친 최종 답변입니다.');
 const final=page.locator(`[data-turn-id="${fixture.request.requestId}"]`);
 await expect(final).toContainText('검토를 마친 최종 답변입니다.');
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toHaveCount(0);
 await expect(final.locator('.agent-progress-complete summary')).toContainText('38초 동안 작업함');
 await expect(final.locator('.agent-progress-complete summary')).toHaveCSS('font-size','14px');
 await expect(final.locator('.v1-markdown p').first()).toHaveCSS('font-size',questionFont);
 await expect(final.locator('.agent-progress-complete details')).not.toHaveAttribute('open');
 const divider=await final.getByRole('separator').boundingBox();
 const answer=await final.getByRole('region',{name:'조건 조회 결과'}).boundingBox();
 expect(divider!.y).toBeLessThan(answer!.y);
 await final.locator('.agent-progress-complete summary').focus();await page.keyboard.press('Enter');
 await expect(final.getByRole('list',{name:'완료된 작업 기록'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(fixture.submissions).toBe(0);expect(fixture.errors).toEqual([]);
});

test('reading history keeps its position while the down arrow resumes following streamed text',async({page})=>{
 const history=Array.from({length:14},(_,index)=>savedTurn(`history-${index}`,`인공 과거 답변 ${index}\n\n${'이전 기록을 읽는 문장입니다. '.repeat(30)}`));
 const fixture=new ControlledAgent(history);await fixture.install(page);await page.goto('/');
 await expect(page.getByRole('region',{name:'진행 중인 분석 요청'})).toBeVisible();
 await page.evaluate(()=>window.scrollTo({top:document.documentElement.scrollHeight,behavior:'auto'}));
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollHeight-innerHeight-scrollY)).toBeLessThanOrEqual(32);
 fixture.publish(draftStart,delta(`${'첫 생성 문단입니다.\n\n'.repeat(35)}첫 스트림 끝.`));
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toContainText('첫 스트림 끝.');
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollHeight-innerHeight-scrollY)).toBeLessThanOrEqual(32);
 await page.locator('[data-turn-id="history-3"]').scrollIntoViewIfNeeded();
 const readingPosition=await page.evaluate(()=>scrollY);
 fixture.publish(delta(`${'이어지는 생성 문단입니다.\n\n'.repeat(35)}두 번째 스트림 끝.`,'first',1,1));
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toContainText('두 번째 스트림 끝.');
 expect(Math.abs(await page.evaluate(()=>scrollY)-readingPosition)).toBeLessThanOrEqual(3);
 await page.getByRole('button',{name:'최신 답변으로 이동'}).click();
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollHeight-innerHeight-scrollY)).toBeLessThanOrEqual(32);
 fixture.publish(delta(`${'다시 따라 읽는 문단입니다.\n\n'.repeat(20)}세 번째 스트림 끝.`,'first',1,2));
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toContainText('세 번째 스트림 끝.');
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollHeight-innerHeight-scrollY)).toBeLessThanOrEqual(32);
 expect(fixture.submissions).toBe(0);expect(fixture.errors).toEqual([]);
});

test('reload restores the same draft and cursor without submitting or duplicating text',async({page})=>{
 const fixture=new ControlledAgent();await fixture.install(page);await page.goto('/');
 fixture.publish(draftStart,delta('새로고침 전에 받은 초안입니다.'));
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toContainText('새로고침 전에 받은 초안입니다.');
 fixture.snapshot({lastEventSeq:fixture.events.length,activities:fixture.activities(),resultRevision:null,
  answer:{streamId:'first',answerRevision:1,mode:'interpretation',status:'writing',blocks:[{id:'interpretations:0',text:'새로고침 전에 받은 초안입니다.'}]}});
 await page.reload();
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toContainText('새로고침 전에 받은 초안입니다.');
 fixture.publish(delta(' 복원 후 이어지는 문장입니다.','first',1,1));
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toContainText('새로고침 전에 받은 초안입니다. 복원 후 이어지는 문장입니다.');
 await expect(page.getByText('새로고침 전에 받은 초안입니다. 복원 후 이어지는 문장입니다.',{exact:true})).toHaveCount(1);
 expect(fixture.submissions).toBe(0);expect(fixture.cancellations).toBe(0);expect(fixture.errors).toEqual([]);
});

test('cancellation discards late draft chunks and remains cancelled after reload',async({page})=>{
 const fixture=new ControlledAgent();await fixture.install(page);await page.goto('/');
 fixture.publish(draftStart,delta('취소하기 전의 임시 해석입니다.'));
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toContainText('취소하기 전의 임시 해석입니다.');
 await page.locator('#agent-query-form').getByRole('button',{name:'분석 중지',exact:true}).click();
 await expect(page.getByRole('heading',{name:'분석이 취소되었습니다'})).toBeVisible();
 fixture.publish(delta('취소 뒤 도착한 오래된 조각입니다.','first',1,1));
 await expect(page.getByText('취소 뒤 도착한 오래된 조각입니다.',{exact:true})).toHaveCount(0);
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toHaveCount(0);
 await page.reload();
 await expect(page.getByRole('heading',{name:'분석이 취소되었습니다'})).toBeVisible();
 await expect(page.locator(`[data-turn-id="${fixture.request.requestId}"]`)).toHaveCount(0);
 expect(fixture.cancellations).toBe(1);expect(fixture.submissions).toBe(0);expect(fixture.errors).toEqual([]);
});

test('a different room never receives old chunks and the original room restores its saved answer',async({page})=>{
 const fixture=new ControlledAgent();await fixture.install(page);await page.goto('/');
 fixture.publish(draftStart,delta('원래 방에서 생성 중인 해석입니다.'));
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toContainText('원래 방에서 생성 중인 해석입니다.');
 const rooms=page.getByRole('region',{name:'채팅방 목록'});
 await rooms.getByRole('button',{name:'다른 방의 기록',exact:true}).click();
 await expect(page.getByText('다른 방에 저장된 답변입니다.',{exact:true})).toBeVisible();
 fixture.publish(delta(' 다른 방 이동 뒤 도착한 조각입니다.','first',1,1));
 fixture.finish('원래 방에만 저장된 최종 답변입니다.');
 await expect(page.getByRole('region',{name:'작성 중인 답변'})).toHaveCount(0);
 await expect(page.getByText('원래 방에만 저장된 최종 답변입니다.',{exact:true})).toHaveCount(0);
 await rooms.getByRole('button',{name:'작업 중인 방',exact:true}).click();
 await expect(page.getByText('원래 방에만 저장된 최종 답변입니다.',{exact:true})).toBeVisible();
 await expect(page.getByText('38초 동안 작업함')).toBeVisible();
 await expect(page.getByText('다른 방에 저장된 답변입니다.',{exact:true})).toHaveCount(0);
 expect(fixture.submissions).toBe(0);expect(fixture.cancellations).toBe(0);expect(fixture.errors).toEqual([]);
});
