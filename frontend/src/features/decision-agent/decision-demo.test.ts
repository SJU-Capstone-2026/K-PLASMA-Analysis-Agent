import {expect,test} from 'vitest';
import {queryDefaultUnits,type AgentActivity,type RunSummary,type Snapshot} from 'agent';
import contract from '../../../../agent/tests/support/v2/contracts.json';
import {confirmedCandidates,getDecisionRules,resolveDecisionRun} from './decision-demo';
import {decisionProgressLabel} from './decision-progress';

const run=(runId:string,pressure:number,biasPower:number,energy:number|null)=>({
  runId,runVersionId:runId+'-v1',pressure,sourcePower:100,biasPower,
  metrics:{meanIonEnergy:energy,ionFlux:20,iedWidth:null},units:queryDefaultUnits,
  catalogStatus:'READY',qualityStatus:'VERIFIED',convergenceStatus:'CONVERGED',
}) as unknown as RunSummary;
const baseline=run('RUN-BASELINE',2,400,100);
const alternative=run('RUN-ALTERNATIVE',4,600,80);

test('progress text reflects the goal or follow-up and uses the reported match count',()=>{
  const plan:AgentActivity={activityId:'plan',code:'PLAN',phase:'completed',seq:1,occurredAt:'2026-01-01T00:00:00Z'};
  expect(decisionProgressLabel(plan,'damage')).toContain('에너지 감소와 플럭스 유지');
  expect(decisionProgressLabel(plan,'rate')).toContain('플럭스 증가와 에너지 상한');
  expect(decisionProgressLabel({...plan,phase:'started'},'followup')).toContain('비교 근거를 정리하고 있어요');
  expect(decisionProgressLabel({...plan,code:'SEARCH_COMPLETE',runCount:7},'followup')).toBe('같은 조건으로 Run 7개를 다시 찾았어요');
  expect(decisionProgressLabel({...plan,code:'REPLAN'},'followup')).toBeUndefined();
});

test('resolves exact alternative Run identification and refuses ambiguous or missing explicit Runs',()=>{
  const catalog=[baseline,alternative];
  expect(resolveDecisionRun('RUN-ALTERNATIVE에서 효율이 별로야',catalog,baseline)).toEqual([alternative]);
  expect(resolveDecisionRun('압력 4, 소스 100, 바이어스 600에서 효율을 높이려면?',catalog,baseline)).toEqual([alternative]);
  expect(resolveDecisionRun('RUN-BASELINE과 RUN-ALTERNATIVE',catalog,baseline)).toHaveLength(2);
  expect(resolveDecisionRun('RUN-UNKNOWN으로 해봤어',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('압력 4 Pa, 소스 100 W, 바이어스 600 W',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('압력 4 파스칼, 소스 100 W, 바이어스 600 W',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('압력 4기압, 소스 100 W, 바이어스 600 W',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('압력 약 4 mTorr에서 효율이 떨어져요',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('압력 4 mTorr 정도에서 효율이 떨어져요',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('압력 .004 Torr, 소스 100 W, 바이어스 600 W',catalog,baseline)).toEqual([alternative]);
  expect(resolveDecisionRun('압력 4 소스 100 바이어스 600에서 효율을 높이려면?',catalog,baseline)).toEqual([alternative]);
  expect(resolveDecisionRun('압력 4 또는 8 mTorr, 소스 100 W, 바이어스 600 W',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('압력 -4, 소스 100 W, 바이어스 600 W',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('압력 4 이하, 소스 100 W, 바이어스 600 W',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('RUN-ALTERNATIVE 압력 2 mTorr',catalog,baseline)).toEqual([]);
  expect(resolveDecisionRun('압력 0.004 Torr, 소스 100 W, 바이어스 600 W',catalog,baseline)).toEqual([alternative]);
  expect(resolveDecisionRun('압력 0.004 토르, 소스 100와트, 바이어스 600와트',catalog,baseline)).toEqual([alternative]);
  expect(resolveDecisionRun('효율이 별로야',catalog,baseline)).toEqual([baseline]);
});

test('computes conditions from the exact Run and detects a missing baseline metric',()=>{
  const goal={mode:'damage' as const,change:10,tolerance:5};
  expect(getDecisionRules(alternative,goal)).toEqual([
    {metric:'pressure',operator:'eq',value:4,unit:'mTorr'},
    {metric:'sourcePower',operator:'eq',value:100,unit:'W'},
    {metric:'meanIonEnergy',operator:'lte',value:72,unit:'eV'},
    {metric:'ionFlux',operator:'between',min:19,max:21,unit:queryDefaultUnits.ionFlux},
  ]);
  expect(getDecisionRules(run('RUN-MISSING',4,600,null),goal)).toBeNull();
});

test('shows only candidates from a completed V2 search with the approved rules',()=>{
  const rules=getDecisionRules(alternative,{mode:'damage',change:10,tolerance:5})!;
  const near=run('RUN-NEAR',4,400,60);
  const far=run('RUN-FAR',4,0,30);
  const sameBias=run('RUN-SAME-BIAS',4,600,50);
  const answer=(runs:RunSummary[],constraints=rules,goals:Snapshot[]=[]):Snapshot=>({
    ...contract.general_answer,intent:'COMPOSITE_ANSWER',draft:null,
    stepResults:[{executionId:'search',stepId:'s1',status:runs.length?'verified':'empty',groupId:'common',reason:null,
      runRefs:runs.map(({runId,runVersionId})=>({runId,runVersionId})),
      outputs:{toolResult:{kind:'reverse_search',resultStatus:runs.length?'MATCH':'NO_MATCH',constraints,goals,
        commonCandidates:runs.map(run=>({run}))}}}],
  }) as unknown as Snapshot;
  expect(confirmedCandidates(answer([far,near,sameBias]),alternative,rules)).toEqual([near,far]);
  expect(confirmedCandidates(answer([]),alternative,rules)).toEqual([]);
  expect(confirmedCandidates(answer([],rules.slice(0,-1)),alternative,rules)).toBeNull();
  expect(confirmedCandidates(answer([],rules,[{metric:'iedWidth',direction:'minimize'}]),alternative,rules)).toBeNull();
  expect(confirmedCandidates(answer([run('RUN-WRONG',2,400,60)]),alternative,rules)).toBeNull();
});
