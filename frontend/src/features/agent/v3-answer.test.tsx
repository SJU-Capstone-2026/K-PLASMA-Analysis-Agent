import {fireEvent,render,screen} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import {isGraphV2AnswerSnapshot,isGraphV3AnswerSnapshot,type TurnSnapshot,type V3DecisionEvidence} from 'agent';
import fixture from '../../../../agent/tests/support/v2/contracts.json';
import {AnswerView} from './AnswerView';
import {initialTurnUi} from './useConversation';
import {V3OptionsControls} from './V3OptionsControls';

const mode={rulesEnabled:true,ragEnabled:true,configDigest:'b'.repeat(64)};
const evidence:V3DecisionEvidence={schemaVersion:1,kind:'decision_rag',status:'ANSWERED',synthetic:true,answer:'저장된 비용 검토를 확인했습니다.',scopeRunRefs:[{runId:'R-SYNTH',runVersionId:'version-1'}],citations:[{
 citationId:'C1',documentId:'doc-synthetic',recordId:'review-synthetic',subjectRunId:'R-SYNTH',recordRunVersionId:'version-1',attribution:'PER_RUN',quote:'<img src=x onerror="alert(1)"> 견적이 높아 보류했다.',score:.86,decision:'HOLD',createdAt:'2026-11-01T00:00:00Z',sourceNoteSha256:'c'.repeat(64),sourceRecordSha256:'d'.repeat(64),
}],rules:{policy:'disabled',action:'DISABLED',threshold:null,perRun:[],excludedRunIds:[],remainingRunIds:['R-SYNTH'],completeAggregation:false},retrieval:{strategy:'LOCAL_DENSE_LEXICAL_RECALL',totalInScope:100,returned:1,model:'local-test'},snapshotFingerprint:'e'.repeat(64),limitations:['모의 기록은 실제 비용 측정이 아닙니다.']};
const snapshot=()=>({...structuredClone(fixture.general_answer),implementationId:'v3',graphVersion:'v3',executionMode:{...mode},decisionEvidence:[structuredClone(evidence)]});

test('v3 snapshots require their own version and immutable feature selection',()=>{
 const answer=snapshot();
 expect(isGraphV3AnswerSnapshot(answer)).toBe(true);
 expect(isGraphV2AnswerSnapshot(answer)).toBe(false);
 expect(isGraphV3AnswerSnapshot({...answer,executionMode:undefined})).toBe(false);
 expect(isGraphV3AnswerSnapshot({...answer,executionMode:{...mode,ragEnabled:'true'}})).toBe(false);
 expect(isGraphV3AnswerSnapshot({...answer,executionMode:{...mode,configDigest:'unknown'}})).toBe(false);
 expect(isGraphV3AnswerSnapshot({...answer,decisionEvidence:[{...evidence,citations:[{...evidence.citations[0],attribution:'OTHER_RUN'}]}]})).toBe(false);
});

test('v3 restores source quotes as text and shows the saved request mode',()=>{
 const answer=snapshot();
 const turn:TurnSnapshot={id:'turn-synthetic',askedAt:'',question:'이전 판단 근거를 보여줘',intent:'GENERAL_ANSWER',context:null,answerRunRefs:[],answerSnapshot:JSON.parse(JSON.stringify(answer)),ui:structuredClone(initialTurnUi)};
 const {container}=render(<AnswerView turn={turn} onAction={vi.fn()}/>);
 expect(screen.getByText(evidence.citations[0].quote)).toBeVisible();
 expect(screen.getByText('모의 판단 기록')).toBeVisible();
 expect(screen.getByLabelText('답변에 사용한 기능')).toHaveTextContent('판단 기록 규칙 ONRAG ON');
 expect(screen.getByRole('region',{name:'과거 판단 기록 검색 근거'})).toBeVisible();
 expect(container.querySelector('img,script,[onerror]')).toBeNull();
});

test.each(['cost-regex-1','cost-regex-2'])('a %s rule-only result is labelled separately from RAG retrieval',(policy)=>{
 const answer={...snapshot(),executionMode:{...mode,ragEnabled:false},decisionEvidence:[{...evidence,rules:{...evidence.rules,policy,action:'APPLY_EXISTING_COST_RULE',completeAggregation:true,threshold:2,perRun:[{runId:'R-SYNTH',count:2,status:'REJECTED',mixed:false,costRejectionRecordIds:['one','two']}],excludedRunIds:['R-SYNTH'],remainingRunIds:[]},retrieval:{strategy:'COMPLETE_RULE_AGGREGATION_WITH_PROOF',totalInScope:100,returned:1}}]};
 expect(isGraphV3AnswerSnapshot(answer)).toBe(true);
 expect(isGraphV3AnswerSnapshot({...answer,decisionEvidence:[{...answer.decisionEvidence[0],
   rules:{...answer.decisionEvidence[0].rules,policy:'cost-regex-unknown'}}]})).toBe(false);
 const turn:TurnSnapshot={id:'rule-synthetic',askedAt:'',question:'비용 반려 후보 제외',intent:'COMPOSITE_ANSWER',context:null,answerRunRefs:[],answerSnapshot:JSON.parse(JSON.stringify(answer)),ui:structuredClone(initialTurnUi)};
 render(<AnswerView turn={turn} onAction={vi.fn()}/>);
 expect(screen.getByRole('region',{name:'판단 기록 규칙 근거'})).toBeVisible();
 expect(screen.queryByRole('region',{name:'과거 판단 기록 검색 근거'})).not.toBeInTheDocument();
 expect(screen.getByText('RAG OFF')).toBeVisible();
 expect(screen.getByRole('cell',{name:'제외'})).toBeVisible();
});

test('search and rule attachments from the same pinned inventory both remain visible',()=>{
 const ruleEvidence:V3DecisionEvidence={...structuredClone(evidence),answer:'비용 반려 규칙 전체 집계',
   rules:{...evidence.rules,policy:'cost-regex-1',action:'APPLY_EXISTING_COST_RULE',completeAggregation:true,threshold:2},
   retrieval:{strategy:'COMPLETE_RULE_AGGREGATION_WITH_PROOF',totalInScope:100,returned:1}};
 const answer={...snapshot(),decisionEvidence:[structuredClone(evidence),ruleEvidence]};
 expect(isGraphV3AnswerSnapshot(answer)).toBe(true);
 const turn:TurnSnapshot={id:'two-steps',askedAt:'',question:'기록을 검색하고 비용 규칙도 적용해줘',intent:'COMPOSITE_ANSWER',context:null,answerRunRefs:[],answerSnapshot:JSON.parse(JSON.stringify(answer)),ui:structuredClone(initialTurnUi)};
 render(<AnswerView turn={turn} onAction={vi.fn()}/>);
 expect(screen.getByRole('region',{name:'과거 판단 기록 검색 근거'})).toBeVisible();
 expect(screen.getByRole('region',{name:'판단 기록 규칙 근거'})).toBeVisible();
});

test('disabled rule output cannot silently contain rule exclusions',()=>{
 const answer=snapshot();
 expect(isGraphV3AnswerSnapshot({...answer,decisionEvidence:[{...evidence,rules:{...evidence.rules,excludedRunIds:['R-SYNTH']}}]})).toBe(false);
});

test('pending mode controls are disabled, and enabled controls change only the requested flag',()=>{
 const onChange=vi.fn();
 const {rerender}=render(<V3OptionsControls mode={mode} disabled onChange={onChange}/>);
 expect(screen.getByRole('switch',{name:'RAG'})).toBeDisabled();
 expect(screen.getByRole('switch',{name:'판단 기록 규칙'})).toBeDisabled();
 rerender(<V3OptionsControls mode={mode} disabled={false} onChange={onChange}/>);
 fireEvent.click(screen.getByRole('switch',{name:'RAG'}));
 expect(onChange).toHaveBeenCalledWith({...mode,ragEnabled:false});
});
