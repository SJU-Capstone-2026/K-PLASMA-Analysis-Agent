import {fireEvent,render,screen} from '@testing-library/react';
import {expect,test} from 'vitest';
import type {ComparisonResultV2,ComparisonAnswer,TurnSnapshot} from 'agent';
import wire from '../../../../agent/tests/support/answer-v2-wire.json';
import {RunComparisonCard} from './RunComparisonCard';
import {V1AnswerView} from './V1AnswerView';

test('shared comparison contract keeps every exact version, zero and unavailable reasons',()=>{
 render(<RunComparisonCard result={wire.comparison.result as ComparisonResultV2} answer={wire.comparison.answer as ComparisonAnswer}/>);
 expect(screen.getByText('선택한 실험 비교 · 2개')).toBeInTheDocument();
 expect(screen.getByText('버전 00000000-0000-0000-0000-000000000001')).not.toBeVisible();
 fireEvent.click(screen.getAllByText('버전·데이터 상태')[0]);
 expect(screen.getByText('버전 00000000-0000-0000-0000-000000000001')).toBeInTheDocument();
 expect(screen.getByText('버전 00000000-0000-0000-0000-000000000002')).toBeInTheDocument();
 expect(screen.getAllByText(/기준값이 0이므로 변화율 계산 불가/).length).toBeGreaterThan(0);
 expect(screen.getAllByText(/측정값 없음/).length).toBeGreaterThan(0);
 expect(screen.getAllByText(/0 10¹⁸/).length).toBeGreaterThan(0);
});

test('calculation observations start collapsed and stay available on demand',()=>{
 render(<RunComparisonCard result={wire.comparison.result as ComparisonResultV2} answer={wire.comparison.answer as ComparisonAnswer}/>);
 const fact=screen.getByText(wire.comparison.result.observations[0].text);
 expect(fact).not.toBeVisible();
 fireEvent.click(screen.getByText('계산 근거'));
 expect(fact).toBeVisible();
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
 expect(screen.queryByText('가능한 해석 · LLM 일반 지식 기반')).not.toBeInTheDocument();
 expect(screen.getByText('선택한 실험 비교 · 2개')).toBeInTheDocument();
});

test('reopening a saved search displays its applied defaults and older answers do not gain a notice',()=>{
 const turn={question:'인공 질문',answerSnapshot:wire.forward,ui:{}} as unknown as TurnSnapshot;
 const view=render(<V1AnswerView turn={turn} onAction={()=>{}}/>);
 expect(screen.getByText(/단위를 생략해 기본 단위로 조회했습니다: 압력 mTorr/)).toBeVisible();
 view.rerender(<V1AnswerView turn={{...turn,answerSnapshot:{...turn.answerSnapshot,unitAssumptions:[]}}} onAction={()=>{}}/>);
 expect(screen.queryByText(/단위를 생략해/)).not.toBeInTheDocument();
});
