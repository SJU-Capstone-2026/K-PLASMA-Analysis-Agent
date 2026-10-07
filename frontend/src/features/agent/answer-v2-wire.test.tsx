import {render,screen} from '@testing-library/react';
import {expect,test} from 'vitest';
import type {ComparisonResultV2,ComparisonAnswer} from 'agent';
import wire from '../../../../agent/tests/support/answer-v2-wire.json';
import {RunComparisonCard} from './RunComparisonCard';

test('shared comparison contract keeps every exact version, zero and unavailable reasons',()=>{
 render(<RunComparisonCard result={wire.comparison.result as ComparisonResultV2} answer={wire.comparison.answer as ComparisonAnswer}/>);
 expect(screen.getByText('선택한 실험 비교 · 2개')).toBeInTheDocument();
 expect(screen.getByText('버전 00000000-0000-0000-0000-000000000001')).toBeInTheDocument();
 expect(screen.getByText('버전 00000000-0000-0000-0000-000000000002')).toBeInTheDocument();
 expect(screen.getAllByText(/기준값이 0이므로 변화율 계산 불가/).length).toBeGreaterThan(0);
 expect(screen.getAllByText(/측정값 없음/).length).toBeGreaterThan(0);
 expect(screen.getAllByText(/0 10¹⁸/).length).toBeGreaterThan(0);
});

test('failed partial renders numeric evidence without a generated explanation',()=>{
 render(<RunComparisonCard result={wire.partial as ComparisonResultV2}/>);
 expect(screen.queryByText('가능한 해석 · LLM 일반 지식 기반')).not.toBeInTheDocument();
 expect(screen.getByText('선택한 실험 비교 · 2개')).toBeInTheDocument();
});
