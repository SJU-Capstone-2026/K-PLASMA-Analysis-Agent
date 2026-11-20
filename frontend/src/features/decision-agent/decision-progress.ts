import type {AgentActivity} from 'agent';
import type {DecisionGoal} from './decision-demo';

type Labels=Record<string,readonly [string,string]>;

const searchLabels:Labels={
  QUESTION_CHECK:['기준 Run과 선택한 목표를 확인하고 있어요','기준 Run과 선택한 목표를 확인했어요'],
  PLAN_VALIDATE:['검색 조건에 쓸 수치와 단위를 대조하고 있어요','검색 조건의 수치와 단위를 확인했어요'],
  PLAN_REVIEW:['승인한 목표가 검색 계획에 반영됐는지 살펴보고 있어요','승인한 목표와 검색 계획을 대조했어요'],
  REVERSE_SEARCH:['압력과 소스 전력을 고정해 후보를 찾고 있어요','같은 압력과 소스 전력에서 후보를 조회했어요'],
  RESULT_VALIDATE:['후보의 측정값을 등록된 Run과 대조하고 있어요','후보의 측정값을 등록된 Run과 대조했어요'],
  SEARCH_EMPTY:['목표 범위에 맞는 Run이 없어요','목표 범위에 맞는 Run이 없어요'],
  INTERPRET:['바이어스에 따라 어떤 차이가 관찰됐는지 살펴보고 있어요','바이어스에 따른 측정값 차이를 해석했어요'],
  REVIEW:['바이어스에 대한 설명을 관찰값과 대조하고 있어요','바이어스에 대한 설명을 관찰값과 대조했어요'],
};

const followupLabels:Labels={
  QUESTION_CHECK:['앞서 찾은 후보와 후속 질문을 확인하고 있어요','앞서 찾은 후보와 후속 질문을 확인했어요'],
  PLAN:['후속 질문에 답하는 데 필요한 비교 근거를 정리하고 있어요','후속 질문에 필요한 비교 근거를 정리했어요'],
  PLAN_VALIDATE:['후보를 다시 조회할 때 쓸 조건과 단위를 확인하고 있어요','후보 재조회 조건과 단위를 확인했어요'],
  PLAN_REVIEW:['후속 질문에 답할 수 있는 작업 순서인지 살펴보고 있어요','후속 질문에 필요한 근거를 확인할 계획을 검토했어요'],
  REVERSE_SEARCH:['앞서 적용한 조건으로 후보를 다시 조회하고 있어요','앞서 적용한 조건으로 후보를 다시 조회했어요'],
  RESULT_VALIDATE:['다시 조회한 후보의 측정값을 검증하고 있어요','다시 조회한 후보의 측정값을 검증했어요'],
  SEARCH_EMPTY:['같은 조건에서 다시 찾은 후보가 없어요','같은 조건에서 다시 찾은 후보가 없어요'],
  INTERPRET:['질문에 맞춰 후보별 장점과 주의점을 살펴보고 있어요','후속 질문에 맞춰 후보별 장점과 주의점을 정리했어요'],
  REVIEW:['후보의 장단점 설명이 측정 결과에 부합하는지 확인하고 있어요','후보의 장단점 설명을 측정 결과와 대조했어요'],
};

export function decisionProgressLabel(activity:AgentActivity,mode:DecisionGoal['mode']|'followup'){
  const complete=activity.phase!=='started';
  if(activity.code==='PLAN'&&mode!=='followup'){
    const goal=mode==='damage'?'에너지 감소와 플럭스 유지':'플럭스 증가와 에너지 상한';
    return complete?`${goal}에 맞춰 검색 순서를 정리했어요`:`${goal}에 맞춰 검색 순서를 정리하고 있어요`;
  }
  const count=activity.runCount;
  if(activity.code==='SEARCH_COMPLETE'&&count!==undefined&&Number.isInteger(count)&&count>0)
    return mode==='followup'?`같은 조건으로 Run ${count}개를 다시 찾았어요`:`목표 범위에 들어오는 Run ${count}개를 찾았어요`;
  const labels=mode==='followup'?followupLabels:searchLabels;
  return labels[activity.code]?.[complete?1:0];
}
