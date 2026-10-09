import {fireEvent,render,screen} from '@testing-library/react';
import {expect,test} from 'vitest';
import type {ComparisonResultV2,TurnSnapshot} from 'agent';
import wire from '../../../../agent/tests/support/answer-v2-wire.json';
import {RunComparisonCard} from './RunComparisonCard';
import {V1AnswerView} from './V1AnswerView';

test('shared comparison contract keeps every exact version, zero and unavailable reasons',()=>{
 render(<RunComparisonCard result={wire.comparison.result as ComparisonResultV2}/>);
 expect(screen.getByText('선택한 실험 비교 · 2개')).toBeInTheDocument();
 expect(screen.getByText('버전 00000000-0000-0000-0000-000000000001')).not.toBeVisible();
 fireEvent.click(screen.getAllByText('공정 조건·버전')[0]);
 expect(screen.getByText('버전 00000000-0000-0000-0000-000000000001')).toBeInTheDocument();
 expect(screen.getByText('버전 00000000-0000-0000-0000-000000000002')).toBeInTheDocument();
 expect(screen.getAllByText(/기준값이 0이므로 변화율 계산 불가/).length).toBeGreaterThan(0);
 expect(screen.getAllByText(/측정값 없음/).length).toBeGreaterThan(0);
 expect(screen.getAllByText(/0 10¹⁸/).length).toBeGreaterThan(0);
});

test('trend comparisons keep adjacent signed changes without a global baseline',()=>{
 const result=structuredClone(wire.comparison.result) as ComparisonResultV2;
 result.mode='trend';result.baselineKey=null;result.comparisons.forEach(row=>row.kind='adjacent_delta');
 render(<RunComparisonCard result={result}/>);
 expect(screen.getByRole('columnheader',{name:'변화량'})).toBeVisible();
 expect(screen.getByRole('columnheader',{name:'변화율'})).toBeVisible();
 expect(screen.getByText(/기준값이 0이므로 변화율 계산 불가/)).toBeVisible();
});

test('failed partial renders numeric evidence without a generated explanation',()=>{
 render(<RunComparisonCard result={wire.partial as ComparisonResultV2}/>);
 expect(screen.queryByText('가능한 해석')).not.toBeInTheDocument();
 expect(screen.getByText('선택한 실험 비교 · 2개')).toBeInTheDocument();
});

test.each([wire.general,wire.comparison])('saved general and comparison answers omit fixed introductions and interpretation details',async snapshot=>{
 const summary=snapshot.kind==='generate_answer'?'일반 지식에 따른 답변입니다.':'선택한 실제 실험을 비교했습니다.';
 const turn={question:'인공 질문',answerSnapshot:{...snapshot,summary},ui:{}} as unknown as TurnSnapshot;
 const {container}=render(<V1AnswerView turn={turn} onAction={()=>{}}/>);
 if(snapshot.kind==='generate_answer')await screen.findByText('평균 이온 에너지',{selector:'strong'});
 expect(screen.queryByText(summary)).not.toBeInTheDocument();
 expect(screen.queryByText('LLM 일반 지식 기반',{exact:true})).not.toBeInTheDocument();
 expect(screen.queryByText('질문 해석·추가 입력')).not.toBeInTheDocument();
 expect(container.querySelector('.v1-summary,.v1-interpretation')).toBeNull();
 if(snapshot.kind==='compare_runs'){
  expect(screen.queryByText('계산 근거')).not.toBeInTheDocument();
  expect(screen.queryByText('가능한 해석')).not.toBeInTheDocument();
  expect(screen.queryByText('설명의 한계')).not.toBeInTheDocument();
  expect(screen.getByRole('region',{name:'비교 그래프'})).toBeInTheDocument();
 }
});

test('reopening a saved search displays its applied defaults and older answers do not gain a notice',()=>{
 const turn={question:'인공 질문',answerSnapshot:wire.forward,ui:{}} as unknown as TurnSnapshot;
 const view=render(<V1AnswerView turn={turn} onAction={()=>{}}/>);
 expect(screen.getByText(/단위를 생략해 기본 단위로 조회했습니다: 압력 mTorr/)).toBeVisible();
 view.rerender(<V1AnswerView turn={{...turn,answerSnapshot:{...turn.answerSnapshot,unitAssumptions:[]}}} onAction={()=>{}}/>);
 expect(screen.queryByText(/단위를 생략해/)).not.toBeInTheDocument();
});
