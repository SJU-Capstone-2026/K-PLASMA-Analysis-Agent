import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import type {ComparisonResultV3,ScalarDatum,TurnSnapshot} from 'agent';
import general from '../../../../agent/tests/support/v2/contracts.json';
import wire from '../../../../agent/tests/support/answer-v3-wire.json';
import {AnswerView} from './AnswerView';
import {initialTurnUi} from './useConversation';
import {syntheticRun} from '../../test/runs';

test('saved v2 general answers render inline and display LaTeX',async()=>{
 const snapshot={...general.general_answer,answer:String.raw`이온 플럭스 \(\Gamma_i\)의 식입니다.

\[\Gamma_i = n_i u_i\]`};
 const turn={id:'general',askedAt:'',question:'이온 플럭스 공식을 알려줘',intent:'GENERAL_ANSWER',context:null,
  answerRunRefs:[],answerSnapshot:JSON.parse(JSON.stringify(snapshot)),ui:structuredClone(initialTurnUi)} as TurnSnapshot;
 const {container}=render(<AnswerView turn={turn} onAction={()=>{}}/>);
 await waitFor(()=>expect(Array.from(container.querySelectorAll('.katex annotation'),element=>element.textContent))
  .toEqual([String.raw`\Gamma_i`,String.raw`\Gamma_i = n_i u_i`]));
 expect(container.querySelectorAll('.katex-display')).toHaveLength(1);
});

test('mixed data and concept answers keep the saved result table and conceptual paragraphs',async()=>{
 const run=syntheticRun();
 const snapshot={...general.general_answer,intent:'COMPOSITE_ANSWER',
  stepResults:[{executionId:'lookup',stepId:'lookup',status:'verified',outputs:{toolResult:{
   kind:'forward_lookup',resultStatus:'EXACT',candidates:[run],
  }},runRefs:[{runId:run.runId,runVersionId:run.runVersionId}],groupId:null,reason:null}],
  draft:{paragraphs:['이온 플럭스는 단위 면적·시간당 입자 수입니다.'],sources:[]}};
 const turn={id:'mixed-concept',askedAt:'',question:'조회하고 개념을 설명해줘',intent:'COMPOSITE_ANSWER',context:null,
  answerRunRefs:[],answerSnapshot:JSON.parse(JSON.stringify(snapshot)),ui:structuredClone(initialTurnUi)} as TurnSnapshot;
 render(<AnswerView turn={turn} onAction={()=>{}}/>);
 expect(screen.getByRole('table',{name:'검색 Run 목록'})).toBeVisible();
 expect(await screen.findByText('이온 플럭스는 단위 면적·시간당 입자 수입니다.')).toBeVisible();
 expect(screen.getByRole('region',{name:'개념 설명'})).toBeVisible();
});

test('data answers show saved interpretation, assumptions and limitations without duplicating numeric prose',async()=>{
 const run=syntheticRun();
 const text='<img src=x onerror="alert(1)"> 측정된 조건의 차이가 확인됩니다.';
 const snapshot={
  ...general.general_answer,intent:'COMPOSITE_ANSWER',question:'조건을 찾고 의미를 설명해줘',
  answer:'REPEATED NUMERICAL FACTS',
  stepResults:[{executionId:'search',stepId:'search',status:'verified',outputs:{toolResult:{
   kind:'forward_lookup',resultStatus:'EXACT',candidates:[run],
  }},runRefs:[{runId:run.runId,runVersionId:run.runVersionId}],groupId:null,reason:null}],
  evidence:[{id:'fact',executionId:'search',field:'pressure',value:8,unit:'mTorr',runRef:null}],
  draft:{fact_ids:['fact'],interpretations:[{id:'meaning',text:`${text}\n\n${String.raw`\[\Delta p = p_2 - p_1\]`}`,evidence_ids:['fact'],
   assumptions:[String.raw`다른 조건 \(p_1\)도 영향을 줄 수 있어요.`]}],
   limitations:[{id:'limit',text:'압력만으로 원인을 확정할 수 없어요.',evidence_ids:['fact']}]},
 };
 const turn={id:'answer',askedAt:'',question:snapshot.question,intent:'COMPOSITE_ANSWER',context:null,
  answerRunRefs:[],answerSnapshot:JSON.parse(JSON.stringify(snapshot)),ui:structuredClone(initialTurnUi)} as TurnSnapshot;
 const {rerender}=render(<AnswerView turn={turn} onAction={()=>{}}/>);
 expect(screen.getByRole('table',{name:'검색 Run 목록'})).toBeVisible();
 expect(await screen.findByText(text)).toBeVisible();
 expect(screen.getByRole('region',{name:'결과 해석'}).querySelector('.katex-display annotation'))
  .toHaveTextContent(String.raw`\Delta p = p_2 - p_1`);
 expect(screen.getByRole('list',{name:'해석의 전제'}).querySelector('.katex annotation')).toHaveTextContent('p_1');
 expect(screen.getByText('압력만으로 원인을 확정할 수 없어요.')).toBeVisible();
 expect(screen.queryByText('REPEATED NUMERICAL FACTS')).not.toBeInTheDocument();
 expect(document.querySelector('img,script,[onerror]')).toBeNull();
 rerender(<AnswerView turn={{...turn,answerSnapshot:{...turn.answerSnapshot,draft:null}}} onAction={()=>{}}/>);
 expect(screen.queryByText(text)).not.toBeInTheDocument();
 expect(screen.getByRole('table',{name:'검색 Run 목록'})).toBeVisible();
});

test.each([
 {allMissing:false, missingReason:'BIAS_OFF', laterFailure:false, warn:false},
 {allMissing:true, missingReason:'BIAS_OFF', laterFailure:false, warn:false},
 {allMissing:false, missingReason:'SOURCE_MISSING', laterFailure:false, warn:true},
 {allMissing:false, missingReason:'BIAS_OFF', laterFailure:true, warn:true},
])('graph output gaps and request errors stay distinct (%j)',async({allMissing,missingReason,laterFailure,warn})=>{
 const base=wire.comparison.result as ComparisonResultV3;
 const unavailable:ScalarDatum={value:null,unit:'a.u.',status:'UNAVAILABLE',reason:'INSUFFICIENT_DATA',sourceValue:null};
 const outputRows=wire.outputs.map((output,index)=>{
  const missing=allMissing||index===1;
  return {
   metadata:{...output.metadata,outputId:'iad' as const,status:missing?'UNAVAILABLE' as const:'AVAILABLE' as const,
    reason:missing?missingReason:null,sourceIntegrity:'availability-test-'+index,valueUnit:'a.u.',xUnit:'°'},
   display:missing?null:output.display,
  };
 });
 const result:ComparisonResultV3={
  ...base,plotIds:['iad'],metricIds:['iad.maximum'],resultStatus:'NO_COMPARABLE_DATA',
  outputs:outputRows.map(output=>output.metadata),
  runs:base.runs.map((run,index)=>({...run,metrics:{
   'iad.maximum':outputRows[index].display?{...unavailable,value:4,status:'AVAILABLE',reason:null}:unavailable,
  }})),
  comparisons:[{...base.comparisons[0],metric:'iad.maximum',direction:'unavailable',difference:unavailable}],
 };
 const step={executionId:'compare',stepId:'compare',status:'partial',outputs:{toolResult:result},
  runRefs:result.usedRunRefs,groupId:null,reason:result.resultStatus};
 const oldNotice='제공된 비교 결과에는 Run별 IAD 값이 아니라 범위 요약만 포함되어 있어 상세 비교는 제한됩니다.';
 const snapshot={
  ...general.general_answer,intent:'COMPOSITE_ANSWER',hasIncompleteWork:true,executionStatus:'PARTIAL',
  draft:allMissing?null:{fact_ids:[],interpretations:[],limitations:[
   {text:oldNotice},
   {text:'IAD 곡선만으로 조건 변화의 원인을 확정할 수 없어요.'},
  ]},
  stepResults:laterFailure?[step,{...step,executionId:'next',stepId:'next',status:'failed',outputs:{},reason:'TOOL_EXECUTION_FAILED'}]:[step],
 };
 const turn={id:'iad',askedAt:'',question:'IAD 비교',intent:'COMPOSITE_ANSWER',context:null,
  answerRunRefs:[],answerSnapshot:JSON.parse(JSON.stringify(snapshot)),ui:structuredClone(initialTurnUi)} as TurnSnapshot;
 const fetch=vi.fn(async()=>Response.json({outputs:outputRows}));
 vi.stubGlobal('fetch',fetch);
 try{
  render(<AnswerView turn={turn} onAction={()=>{}}/>);
  const graph=screen.getByRole('region',{name:'비교 그래프'});
  if(allMissing){
   expect(within(graph).getByText('2개 모두 바이어스가 꺼져 IAD 출력이 없습니다.')).toBeVisible();
   expect(within(graph).queryByRole('button',{name:'전체 표시'})).not.toBeInTheDocument();
   expect(fetch).not.toHaveBeenCalled();
  }else{
   await within(graph).findByRole('img',{name:/원본 파형 비교/});
   const summary=within(graph).getByText(/2개 중 1개 표시 가능/);
   const disclosure=within(graph).getByRole('button',{name:'출력 없음 1개'});
   fireEvent.click(summary);
   expect(disclosure).toHaveAttribute('aria-expanded','false');
   expect(within(graph).queryByRole('button',{name:'R2 SYNTHETIC-B'})).not.toBeInTheDocument();
   fireEvent.click(disclosure);
   const missing=within(graph).getByRole('list',{name:/출력이 없는 Run/});
   expect(within(missing).getByText('SYNTHETIC-B')).toBeVisible();
   expect(screen.queryByText(oldNotice)).not.toBeInTheDocument();
   expect(screen.getByText('IAD 값이 있는 1개 Run의 개별 값은 위 비교 표에서 확인할 수 있어요.')).toBeVisible();
   expect(await screen.findByText('IAD 곡선만으로 조건 변화의 원인을 확정할 수 없어요.')).toBeVisible();
  }
  const warning=screen.queryByText(/요청의 일부를 처리하지 못했습니다/);
  if(warn)expect(warning).toBeVisible();
  else expect(warning).not.toBeInTheDocument();
 }finally{
  vi.unstubAllGlobals();
 }
});
