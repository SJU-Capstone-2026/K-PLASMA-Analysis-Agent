import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {createRecord,executeFallback,toRunSummary,type ReviewRecord,type TurnSnapshot} from 'agent';
import {fixtureRuns} from '../../test/runs';
import {AgentPage,candidateRefs} from './AgentPage';
import {AnswerView} from './AnswerView';
import {emptyWorkspace,initialTurnUi,type ConversationController} from './useConversation';
afterEach(()=>vi.unstubAllEnvs());

test('analysis offers general and local and opens a new room before switching a pinned conversation',async()=>{
 vi.stubEnv('VITE_AGENT_SUPPORTED_GRAPH_VERSIONS','v2,v2_localLLM');
 const selectGraphVersion=vi.fn();
 const newConversation=vi.fn(async()=>{});
 const conversation:ConversationController={state:structuredClone(emptyWorkspace),graphVersion:'v2',selectGraphVersion,
  ready:true,error:'',pending:false,provisionalMessage:null,activeRequest:null,sending:false,
  submit:vi.fn(),resume:vi.fn(),cancel:vi.fn(),updateTurnUi:vi.fn(),setReference:vi.fn(),refresh:vi.fn(),
  selectConversation:vi.fn(),newConversation,reset:vi.fn()};
 const page=(value:ConversationController)=><AgentPage conversation={value} records={[]} notify={vi.fn()} onDetail={vi.fn()}
  onRecord={vi.fn()} onEvidence={vi.fn()}/>;
 const {rerender}=render(page(conversation));
 const local=screen.getByRole('button',{name:'로컬'});
 expect(screen.getByRole('button',{name:'일반'})).toHaveAttribute('aria-pressed','true');
 fireEvent.click(local);
 await waitFor(()=>expect(selectGraphVersion).toHaveBeenCalledWith('v2_localLLM'));
 expect(newConversation).not.toHaveBeenCalled();

 rerender(page({...conversation,graphVersion:'v2_localLLM',state:{...conversation.state,
  conversation:{...conversation.state.conversation,agentGraphVersion:'v2_localLLM'}}}));
 fireEvent.click(screen.getByRole('button',{name:'일반'}));
 await waitFor(()=>expect(selectGraphVersion).toHaveBeenLastCalledWith('v2'));
 expect(newConversation).toHaveBeenCalledOnce();
 expect(newConversation.mock.invocationCallOrder[0]).toBeLessThan(selectGraphVersion.mock.invocationCallOrder[1]);
});
async function candidateTurn(){const response=await executeFallback({text:'Ion Flux는 높게, Mean Ion Energy는 30–40 eV에 가깝게 후보를 찾아줘',candidateReferences:[]},{candidateRunsLatest:fixtureRuns.map(toRunSummary),referenceRunsByVersion:new Map(),decisionRecords:[],hydrateFullRun:async ref=>fixtureRuns.find(r=>r.runId===ref.runId)!});return {id:'t1',askedAt:'2026-01-01T00:00:00Z',question:'후보 찾아줘',intent:response.intent,context:null,answerRunRefs:response.usedRunRefs,answerSnapshot:response.answerSnapshot,ui:initialTurnUi} satisfies TurnSnapshot;}
test('candidate card keyboard selects only its turn; group reference selects the whole active group without submitting',async()=>{const turn=await candidateTurn();const submit=vi.fn(async()=>{});const updateTurnUi=vi.fn(async()=>{});const setReference=vi.fn<ConversationController['setReference']>(async()=>{});render(<AgentPage conversation={{state:{...emptyWorkspace,conversation:{...emptyWorkspace.conversation,turns:[turn]}},graphVersion:'v1',selectGraphVersion:()=>{},ready:true,error:'',pending:false,provisionalMessage:null,activeRequest:null,sending:false,resume:async()=>{},cancel:async()=>{},submit,updateTurnUi,setReference,refresh:async()=>{},selectConversation:async()=>{},newConversation:async()=>{},reset:async()=>{}}} records={[]} notify={()=>{}} onDetail={()=>{}} onRecord={()=>{}} onEvidence={()=>{}}/>);const cards=document.querySelectorAll('.agent-fit-card-selectable');fireEvent.keyDown(cards[0],{key:' '});expect(updateTurnUi).toHaveBeenCalledWith('t1',{selectedCandidateRunId:cards[0].getAttribute('data-run-id')});expect(setReference).not.toHaveBeenCalled();expect(submit).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'전체 후보 채팅에 추가'}));const update=setReference.mock.calls[0][0];expect(typeof update==='function'?update(emptyWorkspace):update).toEqual({kind:'후보 집합',runs:candidateRefs(turn)});expect(submit).not.toHaveBeenCalled();});
test('versionless saved conversations show their history and disable new questions',async()=>{
 const turn=await candidateTurn();
 const submit=vi.fn(async()=>{});
 const newConversation=vi.fn(async()=>{});
 render(<AgentPage conversation={{state:{...emptyWorkspace,conversation:{...emptyWorkspace.conversation,turns:[turn]}},
  graphVersion:'v1',selectGraphVersion:vi.fn(),ready:true,error:'',pending:false,provisionalMessage:null,activeRequest:null,
  sending:false,submit,resume:vi.fn(),cancel:vi.fn(),updateTurnUi:vi.fn(),setReference:vi.fn(),refresh:vi.fn(),
  selectConversation:vi.fn(),newConversation,reset:vi.fn()}} records={[]} notify={vi.fn()}
  onDetail={vi.fn()} onRecord={vi.fn()} onEvidence={vi.fn()}/>);
 expect(screen.getByText(turn.question)).toBeVisible();
 expect(screen.getByText('이전 대화입니다. 새 대화에서 질문을 이어갈 수 있어요.')).toBeVisible();
 expect(screen.getByRole('button',{name:'분석'})).toBeDisabled();
 expect(screen.getByRole('button',{name:'일반'})).toHaveAttribute('aria-pressed','false');
 fireEvent.click(screen.getByRole('button',{name:'새 대화'}));
 expect(newConversation).toHaveBeenCalledOnce();
 expect(submit).not.toHaveBeenCalled();
});

test('nine representative questions start collapsed and submit the selected text',()=>{
 const submit=vi.fn(async()=>{});
 render(<AgentPage conversation={{state:emptyWorkspace,graphVersion:'v2',selectGraphVersion:vi.fn(),
  ready:true,error:'',pending:false,provisionalMessage:null,activeRequest:null,sending:false,submit,
  resume:vi.fn(),cancel:vi.fn(),updateTurnUi:vi.fn(),setReference:vi.fn(),refresh:vi.fn(),
  selectConversation:vi.fn(),newConversation:vi.fn(),reset:vi.fn()}} records={[]} notify={vi.fn()}
  onDetail={vi.fn()} onRecord={vi.fn()} onEvidence={vi.fn()}/>);
 const summary=screen.getByText('대표 질문으로 시작해 보세요');
 const details=summary.closest('details')!;
 expect(details).not.toHaveAttribute('open');
 expect(details.querySelectorAll('li')).toHaveLength(9);
 fireEvent.click(summary);
 expect(details).toHaveAttribute('open');
 const question='평균 이온 에너지가 뭐야?';
 fireEvent.click(screen.getByRole('button',{name:question}));
 expect(submit).toHaveBeenCalledWith(question,undefined);
});
test('answer adapter preserves escaped text and removes legacy event attributes',()=>{const turn={id:'safe',askedAt:'',question:'',intent:'CLARIFICATION',context:null,answerRunRefs:[],answerSnapshot:{intent:'CLARIFICATION',summary:'<img src=x onerror="alert(1)">',missingConditions:['pressure']},ui:initialTurnUi} satisfies TurnSnapshot;render(<AnswerView turn={turn} onAction={()=>{}}/>);expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();expect(document.querySelector('script,img,[onerror],[onclick]')).toBeNull();});

test('candidate role resolves latest A independently of historical baseline A',async()=>{const latest=fixtureRuns[0];const historical={...latest,runVersionId:'historical-A',metrics:{...latest.metrics,meanIonEnergy:20}};const response=await executeFallback({text:'Mean Ion Energy 30–40 eV인 실제 Run 후보를 모두 찾아줘',baseline:historical,candidateReferences:[]},{candidateRunsLatest:[toRunSummary(latest)],referenceRunsByVersion:new Map([[historical.runVersionId,historical]]),decisionRecords:[],hydrateFullRun:async()=>latest});const turn:TurnSnapshot={id:'versions',askedAt:'',question:'후보',intent:response.intent,context:historical,answerRunRefs:response.usedRunRefs,answerSnapshot:response.answerSnapshot,ui:initialTurnUi};expect(turn.answerRunRefs.map(ref=>ref.runVersionId)).toEqual(['historical-A',latest.runVersionId]);expect(candidateRefs(turn)).toEqual([{runId:latest.runId,runVersionId:latest.runVersionId}]);});


test('numeric excluded row details use latest result version while threshold and undo retain old retry reference',async()=>{
 const latest=fixtureRuns[0];const historical={...latest,runVersionId:'historical-excluded'};const other=fixtureRuns[1];const raw=createRecord({targetRunId:latest.runId,decision:'REJECT',comment:'비용이 높아 예산 초과',analysisType:'FORWARD'},[historical,other]);const rejection:ReviewRecord={...raw,decision:'REJECT',targetRunRef:{runId:historical.runId,runVersionId:historical.runVersionId},comparedRunRefs:[],runSnapshots:raw.runSnapshots.map(snapshot=>({...snapshot,runVersionId:historical.runVersionId}))};const response=await executeFallback({text:'Ion Flux 1 이상인 후보를 찾되 비용 때문에 반려된 건 제외해줘',candidateReferences:[historical],clarification:{threshold:1}},{candidateRunsLatest:[latest,other].map(toRunSummary),decisionRecords:[rejection],referenceRunsByVersion:new Map([[historical.runVersionId,historical]]),hydrateFullRun:async ref=>[historical,latest,other].find(r=>r.runVersionId===ref.runVersionId)!});const turn:TurnSnapshot={id:'excluded',askedAt:'',question:'',intent:response.intent,context:null,answerRunRefs:response.usedRunRefs,answerSnapshot:response.answerSnapshot,ui:initialTurnUi};const {resolveCandidateRef,displayAnswer}=await import('./references');expect(displayAnswer(response.answerSnapshot).memoryResult?.excluded.map(r=>r.runId)).toContain(latest.runId);expect(resolveCandidateRef(turn,latest.runId)).toEqual({runId:latest.runId,runVersionId:latest.runVersionId});expect(displayAnswer(response.answerSnapshot).memoryRequest?.referenceRunRefs).toEqual([{runId:latest.runId,runVersionId:historical.runVersionId}]);
});

test('a cancelled first request still allows leaving its pinned conversation', () => {
 const newConversation=vi.fn(async()=>{});
 const conversation:ConversationController={
  state:{...emptyWorkspace,conversation:{...emptyWorkspace.conversation,agentGraphVersion:'v2'},
   agentMessages:[{requestId:'cancelled',clientMessageId:null,createdAt:'2026-11-06T00:00:00Z',question:'취소한 질문',
    submittedRunRefs:[],status:'CANCELLED',turnId:null,executionSummary:{durationMs:38_000,activities:[]}}]},
  graphVersion:'v2',selectGraphVersion:vi.fn(),ready:true,error:'',provisionalMessage:null,pending:false,
  activeRequest:null,sending:false,submit:vi.fn(),resume:vi.fn(),cancel:vi.fn(),updateTurnUi:vi.fn(),
  setReference:vi.fn(),refresh:vi.fn(),selectConversation:vi.fn(),newConversation,reset:vi.fn(),
 };
 render(<AgentPage conversation={conversation} records={[]} notify={vi.fn()} onDetail={vi.fn()}
  onRecord={vi.fn()} onEvidence={vi.fn()}/>);
 expect(screen.getByRole('button',{name:'일반'})).toHaveAttribute('aria-pressed','true');
 expect(screen.getByText('38초 후에 중단했습니다')).toBeVisible();
 const button=screen.getByRole('button',{name:'새 대화'});
 expect(button).toBeEnabled();
 fireEvent.click(button);
 expect(newConversation).toHaveBeenCalledOnce();
});
