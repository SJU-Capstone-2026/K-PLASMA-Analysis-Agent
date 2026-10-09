import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import type {DecisionRecord,ExperimentRecord,RunRef,TurnSnapshot} from 'agent';
import {syntheticRun} from '../../test/runs';
import {AnswerView} from './AnswerView';
import {DecisionDialog} from '../archive/DecisionDialog';
import {candidateRefs,resolveCandidateRef,v1CandidateRefs} from './references';
import {v1RecordModel} from './v1-record-model';
import {initialTurnUi} from './useConversation';

const candidate=syntheticRun(800);
const historical={...candidate,runVersionId:'historical-objective-version',metrics:{...candidate.metrics,meanIonEnergy:999}};
const near=[syntheticRun(200),syntheticRun(400),syntheticRun(600)].map(run=>({...run,metrics:{...run.metrics,ionFlux:1}}));
const objective={id:'objective-1',metric:'ionFlux',operator:'MIN',comparisonOperator:'gte',value:2,unit:'10¹⁸ m⁻²s⁻¹'};
const contextObjective={id:'objective-2',metric:'meanIonEnergy',operator:'MIN',comparisonOperator:'gt',value:40,unit:'eV',policyVersion:'v1'};
const evaluations=[{objectiveId:objective.id,metric:'ionFlux',actual:2,satisfied:true,targetLabel:'≥ 2',boundaryDelta:0},{objectiveId:contextObjective.id,metric:'meanIonEnergy',actual:36,satisfied:false,targetLabel:'> 40',boundaryDelta:-4}];
const ref=(run:RunRef)=>({runId:run.runId,runVersionId:run.runVersionId});
const result={kind:'reverse_search',resultStatus:'NO_MATCH',objectives:[objective,contextObjective],commonCandidates:[],objectiveResults:[{objective,candidates:[{run:candidate,evaluations}],allConstraintsGuaranteed:false}],goalResults:[],nearMisses:near.map(run=>({run,violations:[{metric:'ionFlux',operator:'gte',actual:1,required:2},{metric:'meanIonEnergy',operator:'gt',actual:36,required:40}]}))};
const turn:TurnSnapshot={id:'objective-turn',askedAt:'',question:'플럭스 2 이상, 기준보다 에너지가 높은 후보',intent:'REVERSE_SEARCH',context:ref(historical),answerRunRefs:[ref(candidate),...near.map(ref),ref(historical)],answerSnapshot:JSON.parse(JSON.stringify({implementationId:'v1',schemaVersion:1,kind:'reverse_search',result,interpretation:{operations:[{kind:'reverse_search',inputs:{goals:[{metric:'ionFlux',direction:'maximize'}],context_rules:[{kind:'above_baseline',metric:'meanIonEnergy'}]}}]}})),ui:structuredClone(initialTurnUi)};

test('hard-objective-only candidates are displayed and retain exact reference actions',()=>{
 const action=vi.fn();const {rerender}=render(<AnswerView turn={turn} onAction={action}/>);
 expect(screen.getAllByRole('tab')).toHaveLength(3);
 expect(screen.getByRole('tab',{name:'조건 미충족 근접 후보 3'})).toBeInTheDocument();
 fireEvent.click(screen.getByRole('tab',{name:'Ion Flux 조건 1'}));
 expect(action.mock.calls[0][0]).toBe('candidate-group');const groupId=action.mock.calls[0][1].dataset.groupId;
 const selected={...turn,ui:{...turn.ui,activeCandidateGroup:groupId}};
 rerender(<AnswerView turn={selected} onAction={action}/>);
 expect(screen.getByText(candidate.runId)).toBeInTheDocument();expect(screen.getByText(/개별 조건의 후보입니다/)).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'실험 자세히 보기'}));
 expect(action.mock.calls[1][1].dataset.runVersionId).toBe(candidate.runVersionId);
 expect(candidateRefs(selected)).toEqual([ref(candidate)]);
 expect(resolveCandidateRef(selected,candidate.runId)).toEqual(ref(candidate));
 expect(v1CandidateRefs(selected)).toContainEqual(ref(candidate));
 expect(v1CandidateRefs(selected)).not.toContainEqual(ref(historical));
});

test.each([{goals:[]},{goals:[{metric:'ionFlux',direction:'maximize'}]}])('record criteria preserve verified objectives with interpretation goals %j',({goals})=>{
 const commonCandidate={...candidate,metrics:{...candidate.metrics,meanIonEnergy:44}};
 const commonEvaluations=[evaluations[0],{...evaluations[1],actual:44,satisfied:true,boundaryDelta:4}];
 const common={...result,commonCandidates:[{run:commonCandidate,evaluations:commonEvaluations}],objectiveResults:[],nearMisses:[]};
 const commonTurn={...turn,answerSnapshot:JSON.parse(JSON.stringify({...turn.answerSnapshot,result:common,interpretation:{operations:[{kind:'reverse_search',inputs:{goals}}]}}))};
 const model=v1RecordModel(commonTurn)!;
 expect(model.objectives).toEqual([objective,contextObjective]);
 expect(model.candidates.find(item=>item.runId===candidate.runId)?.objectiveEvaluations).toEqual(commonEvaluations);
});

test('manual decision saves an objective-only candidate with its verified criteria and exact version',async()=>{
 const save=vi.fn(async(_record:DecisionRecord,_refs:RunRef[])=>{void _record;void _refs;});
 render(<DecisionDialog turn={turn} runs={[historical,candidate,...near]} workspaceEpoch={0} onSave={save} onClose={()=>{}}/>);
 fireEvent.click(screen.getByLabelText(`${candidate.runId} 채택`));
 fireEvent.click(screen.getByRole('button',{name:'다음: 후보별 판단'}));
 fireEvent.change(screen.getByRole('textbox',{name:'공통 실험 코멘트 필수'}),{target:{value:'개별 조건 후보를 검토했습니다.'}});
 fireEvent.click(screen.getByRole('button',{name:'실험 기록 저장'}));
 await waitFor(()=>expect(save).toHaveBeenCalledTimes(1));
 const saved=save.mock.calls[0][0] as ExperimentRecord;
 expect(saved.targetRunRef).toEqual(ref(candidate));expect(saved.candidates[0].metrics).toEqual(candidate.metrics);
 expect(saved.objectives).toEqual([objective,contextObjective]);expect(saved.candidates[0].objectiveEvaluations).toEqual(evaluations);
});
