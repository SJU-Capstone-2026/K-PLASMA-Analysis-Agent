import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import type {ComparisonResultV3,ComparisonResultV2} from 'agent';
import wire from '../../../../agent/tests/support/answer-v3-wire.json';
import legacy from '../../../../agent/tests/support/answer-v2-wire.json';
import {ComparisonCharts,sameOutputSource,extent} from './ComparisonCharts';
import {RunColorsProvider} from '../../components/RunColors';
afterEach(()=>{vi.unstubAllGlobals();localStorage.clear();});
test('large grid selections calculate common axes without an argument-count overflow',()=>{
 const values=Array.from({length:300000},(_,i)=>i-150000);
 expect(extent(values)).toEqual([-150000,149999]);
});
test('scalar answers use bars; hiding every Run is explicit and makes no server writes',()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 const {container}=render(<ComparisonCharts result={legacy.comparison.result as ComparisonResultV2}/>);
 expect(screen.getByRole('img',{name:/막대 그래프/})).toBeVisible();
 expect(container.querySelectorAll('rect[data-run-key]')).toHaveLength(2);
 fireEvent.click(screen.getByText('전체 숨기기'));expect(screen.getByText(/표시 중인 실험이 없습니다/)).toBeVisible();
 fireEvent.click(screen.getByText('전체 표시'));expect(container.querySelectorAll('rect[data-run-key]')).toHaveLength(2);
 expect(fetch).not.toHaveBeenCalled();
});
test('source curves share tag colors, exact versions and local toggles',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({outputs:wire.outputs})));
 const {container}=render(<RunColorsProvider scope="synthetic-comparison"><ComparisonCharts result={wire.comparison.result as ComparisonResultV3}/></RunColorsProvider>);
 await screen.findByRole('img',{name:/원본 파형 비교/});
 expect(container.querySelectorAll('path[data-run-id]')).toHaveLength(2);
 expect(container.querySelector('path[data-run-id="SYNTHETIC-A"]')).toHaveAttribute('stroke','#4168e8');
 fireEvent.click(screen.getByRole('button',{name:'R1 SYNTHETIC-A'}));expect(container.querySelectorAll('path[data-run-id]')).toHaveLength(1);
 fireEvent.click(screen.getByText('그래프 접기'));expect(screen.queryByRole('img')).not.toBeInTheDocument();
 fireEvent.click(screen.getByText('그래프 펼치기'));await waitFor(()=>expect(container.querySelectorAll('path[data-run-id]')).toHaveLength(1));
});
test('historical source identity must match version, output, integrity and units',()=>{
 const metadata=wire.outputs[0].metadata;
 expect(sameOutputSource(metadata as never,{...metadata,valueUnit:'A/m²'} as never)).toBe(false);
 expect(sameOutputSource(metadata as never,{...metadata,sourceIntegrity:'other'} as never)).toBe(false);
 expect(sameOutputSource(metadata as never,{...metadata,featurePolicyVersion:'new-policy'} as never)).toBe(true);
});
