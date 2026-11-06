import type {AgentActivity,AgentExecutionSummary,AgentProgressSnapshot} from 'agent';
import {metricNames} from './agent-contract';

const activityText:Record<string,readonly [string,string]>={
 QUEUED:['분석을 시작할 준비 중','분석 준비를 마쳤어요'],
 QUESTION_CHECK:['질문과 선택한 Run을 확인하는 중','질문과 선택한 Run을 확인했어요'],
 PLAN:['요청에 맞는 작업 순서를 정리하는 중','작업 순서를 정리했어요'],
 PLAN_VALIDATE:['검색 조건·단위와 작업 연결을 확인하는 중','검색 조건·단위와 작업 연결을 확인했어요'],
 FORWARD_LOOKUP:['압력·전력 조건에 맞는 실제 실험을 조회하는 중','조건에 맞는 실제 실험을 조회했어요'],
 REVERSE_SEARCH:['목표 범위에 맞는 실험을 찾는 중','목표 범위에 맞는 실험을 조회했어요'],
 SEARCH_EMPTY:['해당 조건에 맞는 실험은 없어요','해당 조건에 맞는 실험은 없어요'],
 COMPARE_OUTPUTS:['선택한 실험의 출력 비교값을 확인하는 중','선택한 실험의 출력 비교값을 확인했어요'],
 COMPARE_IEAD:['실험별 IEAD 최대 강도와 피크 위치를 비교하는 중','실험별 IEAD 최대 강도와 피크 위치를 비교했어요'],
 DERIVE:['앞선 결과로 다음 검색의 기준값을 계산하는 중','다음 검색의 기준값을 계산했어요'],
 RESULT_VALIDATE:['측정값·단위와 비교 결과를 확인하는 중','측정값·단위와 비교 결과를 확인했어요'],
 REUSE_RESULT:['저장된 결과를 이어서 사용하는 중','저장된 결과를 이어서 사용했어요'],
 NEEDS_RUNS:['비교할 실험을 선택해 주세요','비교할 실험을 선택했어요'],
 NEEDS_BASELINE:['비교 기준으로 사용할 Run을 골라 주세요','비교 기준 Run을 확인했어요'],
 NEEDS_CONDITIONS:['조회에 필요한 조건을 확인해 주세요','조회 조건을 확인했어요'],
 RESUMED:['선택한 실험으로 분석을 이어가는 중','선택한 실험으로 분석을 이어갔어요'],
 REPLAN:['중간 결과를 반영해 남은 작업을 조정하는 중','남은 작업을 조정했어요'],
 GENERAL_ANSWER:['질문에 맞는 설명을 작성하는 중','질문에 맞는 설명을 작성했어요'],
 INTERPRET:['확인된 실험 결과를 해석하는 중','확인된 실험 결과를 해석했어요'],
 REVIEW:['해석이 근거에 맞는지 검토하는 중','해석의 근거 검토를 마쳤어요'],
 PLAN_REVIEW:['질문 조건과 작업 계획을 대조하는 중','작업 계획의 의미 검토를 마쳤어요'],
 REWRITE:['검토 결과를 반영해 해석을 수정하는 중','검토 결과를 반영해 해석을 수정했어요'],
 COMMIT:['답변을 저장하는 중','답변을 저장했어요'],
 RECOVERING:['저장된 처리 상태를 확인하고 이어가는 중','저장된 처리 상태를 확인했어요'],
};
const stages:Record<string,string>={load_comparison_outputs:'원본 파형의 특징을 계산하고 있습니다.',select_tool:'처리할 도구를 선택하고 있습니다.',guard:'실행 조건을 확인하고 있습니다.',calculate:'실험 값을 계산하고 있습니다.',generate_answer:'질문에 맞는 답변을 작성하고 있습니다.',validate_answer:'답변의 근거를 확인하고 있습니다.',interpret:'질문을 해석하고 있습니다.',decide:'실행 조건을 확인하고 있습니다.',gather:'실제 Run 데이터를 확인하고 있습니다.',forward:'조건에 맞는 Run을 조회하고 있습니다.',reverse:'목표에 맞는 Run을 찾고 있습니다.',compare:'Run 차이를 계산하고 있습니다.',validate_result:'수치를 검증하고 있습니다.',generate_explanation:'설명을 작성하고 있습니다.',validate_explanation:'설명을 검증하고 있습니다.',present:'답변을 준비하고 있습니다.',commit:'답변을 저장하고 있습니다.',sync_result:'저장된 답변을 불러오고 있습니다.'};

function textFor(activity:AgentActivity){
 const count=typeof activity.runCount==='number'&&Number.isInteger(activity.runCount)&&activity.runCount>=0?activity.runCount:undefined;
 const complete=activity.phase!=='started';
 if(activity.code==='SEARCH_COMPLETE')return count===undefined?'조건에 맞는 실험을 확인했어요':`조건에 맞는 실험 ${count}개를 찾았어요`;
 if(activity.code==='COMPARE_RUNS'){
  const metrics=activity.metricIds?.flatMap(id=>Object.hasOwn(metricNames,id)?[metricNames[id]]:[])??[];
  return `${count===undefined?'선택한 실험':`${count}개 실험`}의 ${metrics.length?metrics.join('과 '):'차이'}를 ${complete?'비교했어요':'비교하는 중'}`;
 }
 return activityText[activity.code]?.[complete?1:0]??(complete?'작업을 마쳤어요':'작업을 처리하는 중');
}

function latestActivities(activities:AgentActivity[]){
 const byId=new Map<string,AgentActivity>();
 for(const activity of activities){
  const previous=byId.get(activity.activityId);
  if(!previous||previous.seq<activity.seq)byId.set(activity.activityId,activity);
 }
 return [...byId.values()].sort((a,b)=>a.seq-b.seq);
}

function ActivityRecord({activity,current=false}:{activity:AgentActivity;current?:boolean}){
 return <li className={`agent-activity${current?' agent-activity--current':''}`}>
  <span className={current?'agent-activity-spinner':'agent-activity-check'} aria-hidden="true">{current?'':activity.phase==='started'?'·':activity.phase==='reused'?'↺':'✓'}</span>
  <span role={current?'status':undefined}>{textFor(activity)}</span>
 </li>;
}

export function AgentProgress({progress,stage,queued=false}:{progress?:AgentProgressSnapshot;stage:string;queued?:boolean}){
 const activities=latestActivities(progress?.activities??[]);
 const current=queued?undefined:activities.filter(activity=>activity.phase==='started').at(-1);
 const completed=activities.filter(activity=>activity.phase!=='started');
 const recent=completed.slice(-3);
 const earlier=activities.filter(activity=>activity!==current&&!recent.includes(activity));
 return <div className="agent-progress" aria-live="off">
  {earlier.length>0&&<details className="agent-progress-history">
   <summary>이전 작업 {earlier.length}개</summary>
   <ul aria-label="이전 작업 기록">{earlier.map(activity=><ActivityRecord key={activity.activityId} activity={activity}/>)}</ul>
  </details>}
  <ul aria-label="최근 작업 기록">
   {recent.map(activity=><ActivityRecord key={activity.activityId} activity={activity}/>)}
   {current&&<ActivityRecord activity={current} current/>}
  </ul>
  {!current&&<p className="agent-activity agent-activity--current" role="status">
   <span className="agent-activity-spinner" aria-hidden="true"/>
   {queued?activityText.QUEUED[0]:activities.length?'요청을 처리하고 있습니다.':stages[stage]??'요청을 처리하고 있습니다.'}
  </p>}
 </div>;
}

export function CompletedAgentProgress({summary,status='COMPLETED'}:{summary?:AgentExecutionSummary|null;status?:'COMPLETED'|'FAILED'|'CANCELLED'}){
 const seconds=Math.floor(Math.max(0,summary?.durationMs??0)/1000);
 const elapsed=seconds<60?`${seconds}초`:`${Math.floor(seconds/60)}분${seconds%60?` ${seconds%60}초`:''}`;
 if(status==='CANCELLED')return <div className="agent-progress-complete">
  <p className="agent-progress-cancelled">{summary?`${elapsed} 후에 중단했습니다`:'분석을 중단했습니다'}</p><hr/>
 </div>;
 if(!summary)return null;
 const time=seconds===0?'1초 미만':elapsed;
 // COMPLETED is persisted only after the final answer has been saved.
 const activities=latestActivities(summary.activities).map(activity=>status==='COMPLETED'&&activity.code==='COMMIT'
  &&activity.phase==='started'?{...activity,phase:'completed' as const}:activity);
 return <div className="agent-progress-complete">
  <details className="agent-progress-history">
   <summary>{time} 동안 작업함{status==='FAILED'?' · 실패':''}<span className="agent-progress-chevron" aria-hidden="true">›</span></summary>
   {activities.length>0&&<ul aria-label="완료된 작업 기록">{activities.map(activity=><ActivityRecord key={activity.activityId} activity={activity}/>)}</ul>}
  </details>
  <hr/>
 </div>;
}
