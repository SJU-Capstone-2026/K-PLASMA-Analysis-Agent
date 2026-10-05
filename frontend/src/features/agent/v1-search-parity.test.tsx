import {fireEvent,render,screen} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import type {TurnSnapshot} from 'agent';
import {syntheticRun} from '../../test/runs';
import {AnswerView} from './AnswerView';
import {initialTurnUi} from './useConversation';
import {v1SearchModel} from './v1-search-model';
import {renderAgentAnswer} from './answer-markup';

const run=syntheticRun(600,8);
const turn=(kind:string,result:unknown):TurnSnapshot=>({id:'parity',askedAt:'',question:'검증용 인공 질문',intent:kind==='forward_lookup'?'FORWARD_LOOKUP':'REVERSE_SEARCH',context:null,answerRunRefs:[run],answerSnapshot:JSON.parse(JSON.stringify({implementationId:'v1',schemaVersion:1,kind,result})),ui:structuredClone(initialTurnUi)});
test('v1 forward uses the prototype verdict, condition strip, metric cards and exact-version actions',()=>{
 const t=turn('forward_lookup',{kind:'forward_lookup',resultStatus:'EXACT',selectedRun:run,candidates:[run]});
 const action=vi.fn();render(<AnswerView turn={t} onAction={action}/>);
 expect(document.querySelector('.agent-forward-conclusion')).toHaveTextContent(run.runId);
 expect(screen.getByText('3개 공정 조건 정확히 일치')).toBeInTheDocument();
 expect(document.querySelectorAll('.agent-condition-summary > div')).toHaveLength(3);
 expect(document.querySelectorAll('.agent-delta-grid > article')).toHaveLength(3);
 expect(screen.queryByText(`버전 ${run.runVersionId}`)).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'상세 데이터'}));
 expect(action.mock.calls[0][0]).toBe('open-run-detail');
 expect(action.mock.calls[0][1].dataset.runVersionId).toBe(run.runVersionId);
});
test('v1 reverse defaults to filtered matches and preserves prototype tabs, saved proximity and criteria',()=>{
 const objective={id:'objective-1',metric:'meanIonEnergy',operator:'RANGE',comparisonOperator:'between',min:30,max:40,unit:'eV'};
 const evaluation={objectiveId:objective.id,metric:'meanIonEnergy',operator:'RANGE',actual:38,satisfied:true,targetLabel:'30–40',unit:'eV',rangeStatus:'IN_RANGE',matchPercent:91,referenceValue:35};
 const candidate={run,evaluations:[evaluation],matchPercent:91};
 const t=turn('reverse_search',{kind:'reverse_search',resultStatus:'MATCH',constraints:[{...objective,operator:'between'}],goals:[{metric:'ionFlux',direction:'maximize'}],objectives:[objective],commonCandidates:[candidate],objectiveResults:[{objective,candidates:[candidate],allConstraintsGuaranteed:false}],goalResults:[{goal:{metric:'ionFlux',direction:'maximize'},candidates:[run,syntheticRun(800)],allConstraintsGuaranteed:false}],candidateEvaluations:[{runId:run.runId,runVersionId:run.runVersionId,evaluations:[evaluation],matchPercent:91}]});
 render(<AnswerView turn={t} onAction={()=>{}}/>);
 expect(screen.getByRole('tab',{name:'조건 일치 결과 1'})).toHaveAttribute('aria-selected','true');
 expect(screen.getByRole('tab',{name:'Ion Flux 높은순 2'})).toBeInTheDocument();
 expect(screen.getByRole('tab',{name:'Mean Ion Energy 조건 1'})).toBeInTheDocument();
 expect(document.querySelector('.agent-fit-card')).toHaveTextContent('검색값 근접도91%');
 expect(document.querySelector('.agent-fit-rows')).toHaveTextContent('38 eV목표 30–40 eV91% 근접범위 안');
 expect(document.querySelector('.agent-fit-grid--scroll')).toBeInTheDocument();
});
test('v1 unavailable saved proximity never runs a legacy score calculation',()=>{
 const candidate={run,evaluations:[{metric:'meanIonEnergy',actual:38,satisfied:false,targetLabel:'30–40',unit:'eV'}]};
 const t=turn('reverse_search',{kind:'reverse_search',resultStatus:'MATCH',commonCandidates:[candidate]});
 const model=v1SearchModel(t);
 const groups=model.candidateGroups as {groups:{candidates:{objectiveRows:Record<string,unknown>[]}[]}[]};
 Object.defineProperty(groups.groups[0].candidates[0].objectiveRows[0],'percentDelta',{get(){throw new Error('Cannot recompute a saved v1 score');}});
 expect(()=>renderAgentAnswer(model,t)).not.toThrow();
 expect(renderAgentAnswer(model,t)).toContain('근접도 비가용');
});
test('historical soft interpretation stays frozen and fresh explicit soft answers have no old-result notice',()=>{
 const t=turn('reverse_search',{kind:'reverse_search',resultStatus:'MATCH',goals:[{metric:'meanIonEnergy',direction:'target_range',min:30,max:40}],commonCandidates:[{run}]});
 t.question='에너지30~40eV에 가깝게';t.answerSnapshot.versions={promptVersion:'interpret-1'};
 const saved=JSON.stringify(t);
 expect(v1SearchModel(t).interpretationNote).toContain('저장된 답변');
 expect(JSON.stringify(t)).toBe(saved);
 t.question='에너지30~40eV에 가깝게, 범위 밖도 포함해';t.answerSnapshot.versions={promptVersion:'interpret-2'};
 expect(v1SearchModel(t).interpretationNote).toBeUndefined();
});
