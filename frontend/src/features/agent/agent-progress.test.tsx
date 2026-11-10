import {fireEvent,render,screen,within} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import type {AgentActivity,AgentProgressSnapshot,AgentRequestView,AgentResultProjection} from 'agent';
import {PendingRequest} from './PendingRequest';
import {CompletedAgentProgress} from './AgentProgress';
import {V2SearchList} from './V2SearchList';
import {syntheticRun} from '../../test/runs';

const request:AgentRequestView={requestId:'stream-request',requestRevision:1,status:'RUNNING',stage:'interpret',graphVersion:'v2',
 question:'실험 조건을 설명해줘',pendingInput:null,error:null,partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]};
const callbacks={sending:false,onResume:async()=>{},onCancel:async()=>{},onError:()=>{}};
const activity=(activityId:string,code:string,phase:AgentActivity['phase'],seq:number):AgentActivity=>
 ({activityId,code,phase,seq,occurredAt:'2026-11-06T00:00:00Z'});
const progress=(activities:AgentActivity[],text='',status:NonNullable<AgentProgressSnapshot['answer']>['status']='writing'):AgentProgressSnapshot=>({
 lastEventSeq:20,activities,answer:text?{streamId:'draft',answerRevision:1,mode:'interpretation',status,blocks:[{id:'meaning',text}]}:null,resultRevision:1,
});

test('running requests show recent actual activities inline and retain earlier records on demand',()=>{
 const activities=[
  activity('question','QUESTION_CHECK','started',1),activity('question','QUESTION_CHECK','completed',2),
  activity('plan','PLAN','completed',3),activity('rules','PLAN_VALIDATE','completed',4),
  {...activity('search','SEARCH_COMPLETE','completed',5),runCount:7},
  {...activity('compare','COMPARE_RUNS','started',6),runCount:7,metricIds:['pressure','ionFlux']},
 ];
 const {container}=render(<PendingRequest {...callbacks} request={{...request,progress:progress(activities)}} hideQuestion/>);
 expect(screen.queryByRole('heading',{name:'분석 중'})).not.toBeInTheDocument();
 expect(container.querySelector('.v1-pending.panel')).toBeNull();
 const records=screen.getByRole('list',{name:'최근 작업 기록'});
 expect(within(records).getAllByRole('listitem')).toHaveLength(4);
 expect(within(records).queryByText('질문과 선택한 Run을 확인했어요')).not.toBeInTheDocument();
 expect(screen.getByRole('status')).toHaveTextContent('7개 실험의 압력과 이온 플럭스를 비교하는 중');
 fireEvent.click(screen.getByText('이전 작업 1개'));
 expect(screen.getAllByText('질문과 선택한 Run을 확인했어요')).toHaveLength(1);
});

test('a streamed draft switches review and rewrite states while keeping verified result cards',async()=>{
 const run=syntheticRun();
 const resultPreview:AgentResultProjection={resultRevision:1,results:[{stepId:'lookup',executionId:'lookup-execution',
  runRefs:[{runId:run.runId,runVersionId:run.runVersionId}],toolResult:{kind:'forward_lookup',resultStatus:'EXACT',candidates:JSON.parse(JSON.stringify([run]))}}]};
 const {rerender}=render(<PendingRequest {...callbacks} request={{...request,progress:progress([], '처음 해석입니다.')}} resultPreview={resultPreview}/>);
 expect(screen.getByRole('table',{name:'검색 Run 목록'})).toBeVisible();
 expect(screen.getByText('작성 중')).toBeVisible();
 expect(await screen.findByText('처음 해석입니다.')).toBeVisible();
 expect(screen.queryByRole('button',{name:new RegExp(`${run.runId} (상세|판단 기록|채팅에 추가)`)})).not.toBeInTheDocument();
 rerender(<PendingRequest {...callbacks} request={{...request,progress:progress([], '처음 해석입니다.','reviewing')}} resultPreview={resultPreview}/>);
 expect(screen.getByText('검토 중')).toBeVisible();
 rerender(<PendingRequest {...callbacks} request={{...request,progress:{...progress([]),answer:{streamId:'rewrite',answerRevision:2,mode:'interpretation',status:'rewriting',blocks:[]}}}} resultPreview={resultPreview}/>);
 expect(screen.getByText('수정 중')).toBeVisible();
 expect(screen.queryByText('처음 해석입니다.')).not.toBeInTheDocument();
 expect(screen.getByRole('table',{name:'검색 Run 목록'})).toBeVisible();
});

test('streamed Markdown buffers unfinished math and never executes embedded HTML',async()=>{
 const {container,rerender}=render(<PendingRequest {...callbacks} request={{...request,
  progress:progress([],String.raw`확인한 식입니다. \(\Gamma_i = n_i`)}}/>);
 expect(await screen.findByText('확인한 식입니다.')).toBeVisible();
 expect(container.querySelector('.katex')).toBeNull();
 expect(container.textContent).not.toContain('Gamma_i');
 rerender(<PendingRequest {...callbacks} request={{...request,
  progress:progress([],String.raw`확인한 식입니다. \(\Gamma_i = n_i u_i\) <img src=x onerror="alert(1)">`)}}/>);
 expect(container.querySelector('.katex annotation')).toHaveTextContent(String.raw`\Gamma_i = n_i u_i`);
 expect(container.querySelector('img,script,[onerror]')).toBeNull();
 expect(screen.getByLabelText('작성 중인 답변')).toHaveAttribute('aria-live','off');
});

test('read-only live search results keep pagination and omit saved-answer actions',()=>{
 const runs=Array.from({length:11},(_,index)=>syntheticRun(600,index+1));
 render(<V2SearchList result={{kind:'forward_lookup',resultStatus:'EXACT',candidates:runs}} runs={runs} readOnly onAction={vi.fn()}/>);
 expect(screen.queryByRole('columnheader',{name:'작업'})).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:/채팅에 추가|판단 기록|상세/})).not.toBeInTheDocument();
 expect(screen.getByText('1–10 / 11개')).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'다음'}));
 expect(screen.getByText('11–11 / 11개')).toBeVisible();
 expect(screen.getByRole('rowheader',{name:runs[10].runId})).toBeVisible();
});

test.each([{durationMs:999,label:'1초 미만'},{durationMs:38_000,label:'38초'},{durationMs:128_900,label:'2분 8초'}])(
 'completed requests keep their recorded duration and collapse the activity history ($label)',({durationMs,label})=>{
 const {container,rerender}=render(<CompletedAgentProgress summary={{durationMs,activities:[activity('check','QUESTION_CHECK','completed',2),activity('commit','COMMIT','started',3)]}}/>);
 expect(screen.getByText(`${label} 동안 작업함`)).toBeVisible();
 expect(container.querySelector('details')).not.toHaveAttribute('open');
 expect(screen.getByRole('separator')).toBeInTheDocument();
 fireEvent.click(screen.getByText(`${label} 동안 작업함`));
 expect(container.querySelector('details')).toHaveAttribute('open');
 expect(screen.getByText('질문과 선택한 Run을 확인했어요')).toBeVisible();
 expect(screen.getByText('답변을 저장했어요')).toBeVisible();
 expect(screen.queryByText('답변을 저장하는 중')).not.toBeInTheDocument();
 rerender(<CompletedAgentProgress/>);
 expect(container).toBeEmptyDOMElement();
});

test.each([{durationMs:999,label:'0초'},{durationMs:38_000,label:'38초'},{durationMs:128_900,label:'2분 8초'}])(
 'cancellation is a minimal elapsed-time note without a panel or unfinished activities ($label)',({durationMs,label})=>{
 const {container}=render(<PendingRequest {...callbacks} request={{...request,status:'CANCELLED',
  executionSummary:{durationMs,activities:[activity('write','INTERPRET','started',1)]}}} hideQuestion/>);
 expect(screen.getByText(`${label} 후에 중단했습니다`)).toBeVisible();
 expect(screen.queryByRole('heading')).not.toBeInTheDocument();
 expect(container.querySelector('.panel,details,[role=status],.agent-activity-spinner')).toBeNull();
 expect(screen.getByRole('separator')).toBeInTheDocument();
});

test('an older cancellation without a recorded duration does not invent a time',()=>{
 render(<CompletedAgentProgress status="CANCELLED"/>);
 expect(screen.getByText('분석을 중단했습니다')).toBeVisible();
 expect(screen.queryByText(/0초/)).not.toBeInTheDocument();
});

test('a failed rewrite keeps verified cards and removes the unfinished prose',()=>{
 const resultPreview:AgentResultProjection={resultRevision:1,results:[{stepId:'lookup',executionId:'empty-lookup',runRefs:[],
  toolResult:{kind:'forward_lookup',resultStatus:'NO_MATCH',candidates:[]}}]};
 render(<PendingRequest {...callbacks} resultPreview={resultPreview} request={{...request,status:'FAILED',
  error:{code:'MODEL_UNAVAILABLE',message:'수정을 완료하지 못했습니다.'},progress:progress([],'검증되지 않은 수정문','rewriting')}}/>);
 expect(screen.getByText('조건에 맞는 Run이 없습니다.')).toBeVisible();
 expect(screen.getByRole('alert')).toHaveTextContent('수정을 완료하지 못했습니다.');
 expect(screen.queryByText('검증되지 않은 수정문')).not.toBeInTheDocument();
});

test('replanning replaces an invalidated result without retaining its old page or rows',()=>{
 const runs=Array.from({length:11},(_,index)=>syntheticRun(600,index+1));
 const resultPreview:AgentResultProjection={resultRevision:1,results:[{stepId:'lookup',executionId:'first-lookup',runRefs:[],
  toolResult:{kind:'forward_lookup',resultStatus:'EXACT',candidates:JSON.parse(JSON.stringify(runs))}}]};
 const {rerender}=render(<PendingRequest {...callbacks} request={request} resultPreview={resultPreview}/>);
 fireEvent.click(screen.getByRole('button',{name:'다음'}));
 expect(screen.getByRole('rowheader',{name:runs[10].runId})).toBeVisible();
 const replacement=syntheticRun(800,20);
 rerender(<PendingRequest {...callbacks} request={request} resultPreview={{resultRevision:2,results:[{stepId:'lookup',executionId:'new-lookup',runRefs:[],
  toolResult:{kind:'forward_lookup',resultStatus:'EXACT',candidates:JSON.parse(JSON.stringify([replacement]))}}]}}/>);
 expect(screen.queryByRole('rowheader',{name:runs[10].runId})).not.toBeInTheDocument();
 expect(screen.getByRole('rowheader',{name:replacement.runId})).toBeVisible();
});

test.each([
 {partial:'확인한 식입니다. $E = mc',complete:'확인한 식입니다. $E = mc^2$'},
 {partial:'확인한 식입니다.\n\n$$\nE = mc',complete:'확인한 식입니다.\n\n$$\nE = mc^2\n$$'},
 {partial:String.raw`확인한 식입니다. \[E = mc`,complete:String.raw`확인한 식입니다. \[E = mc^2\]`},
])('unfinished formula delimiters stay buffered until the real closing text arrives ($partial)',async({partial,complete})=>{
 const {container,rerender}=render(<PendingRequest {...callbacks} request={{...request,progress:progress([],partial)}}/>);
 expect(await screen.findByText('확인한 식입니다.')).toBeVisible();
 expect(container.textContent).not.toContain('E = mc');
 rerender(<PendingRequest {...callbacks} request={{...request,progress:progress([],complete)}}/>);
 expect(container.querySelector('.katex annotation')).toHaveTextContent('E = mc^2');
});

test('incomplete ordinary Markdown, escaped currency and code remain visible without math buffering',async()=>{
 const text='작성한 **초안과 \\$5, 코드 `$unfinished` 뒤 설명입니다.';
 const {container}=render(<PendingRequest {...callbacks} request={{...request,progress:progress([],text)}}/>);
 await screen.findByText('$unfinished',{selector:'code'});
 expect(container.textContent).toContain('**초안과 $5');
 expect(container.querySelector('code')).toHaveTextContent('$unfinished');
 expect(container.textContent).toContain('뒤 설명입니다.');
});

test('queue and user-input waits do not announce an earlier running activity as current work',()=>{
 const previous=progress([activity('write','INTERPRET','started',1)],'임시 답변');
 const {rerender}=render(<PendingRequest {...callbacks} request={{...request,status:'QUEUED',progress:previous}}/>);
 expect(screen.getByRole('status')).toHaveTextContent('분석을 시작할 준비 중');
 rerender(<PendingRequest {...callbacks} request={{...request,status:'NEEDS_INPUT',progress:previous,pendingInput:{id:'clarification',message:'조건을 입력해 주세요.'}}}/>);
 expect(screen.getByRole('textbox',{name:'조건을 입력해 주세요.'})).toBeVisible();
 expect(screen.queryByLabelText('작성 중인 답변')).not.toBeInTheDocument();
 expect(screen.queryByRole('status')).not.toBeInTheDocument();
});
test('plan meaning review has its own progress and completion does not claim it passed',()=>{
 const {rerender}=render(<PendingRequest {...callbacks} request={{...request,
  progress:progress([activity('plan-review','PLAN_REVIEW','started',1)])}}/>);
 expect(screen.getByRole('status')).toHaveTextContent('질문 조건과 작업 계획을 대조하는 중');
 rerender(<PendingRequest {...callbacks} request={{...request,
  progress:progress([activity('plan-review','PLAN_REVIEW','completed',2)])}}/>);
 expect(screen.getByText('작업 계획의 의미 검토를 마쳤어요')).toBeVisible();
 expect(screen.queryByText(/계획.*통과/)).not.toBeInTheDocument();
});
