import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, expect, test, vi} from 'vitest';
import {AnalysisPage} from './AnalysisPage';
import {RunDetail} from './RunDetail';
import {fixtureRuns, syntheticRun} from '../../test/runs';
import {toRunSummary} from 'agent';
afterEach(()=>vi.restoreAllMocks());
function api(){vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/runs' ? fixtureRuns.map(toRunSummary) : fixtureRuns.find(r=>url.endsWith(r.runVersionId))))));}
test('fixed controls retain original grid selection and four page tabs',async()=>{api();render(<AnalysisPage/>);await screen.findByText('실험 결과를 조건별로 탐색합니다');
 await screen.findByRole('img',{name:'IED 실제 수치 선 그래프'});
 expect(screen.getByLabelText('고정 변수')).toHaveValue('biasPower');expect(screen.getByLabelText('고정 값')).toHaveValue('600');
 fireEvent.change(screen.getByLabelText('셀 표시 지표'),{target:{value:'ionFlux'}});expect(screen.getByLabelText(/RUN-P04-S300-B0600, Ar\+ 플럭스/)).toBeInTheDocument();
 fireEvent.click(screen.getByLabelText(/RUN-P04-S300-B0600, Ar\+ 플럭스/));await waitFor(()=>expect(document.querySelector('.analysis-run-title h2')).toHaveTextContent('RUN-P04-S300-B0600'));
 for(const name of ['파형전류 · 전위','쉬스 밀도위상 · 거리','수렴잔차 추이','분포IED · IAD · IEAD']){fireEvent.click(screen.getByRole('tab',{name}));expect(screen.getByRole('tab',{name})).toHaveAttribute('aria-selected','true');}
 fireEvent.change(screen.getByLabelText('고정 값'),{target:{value:'0'}});await screen.findByText('Bias-off Run에는 쉬스 분포 출력이 없습니다');expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
});
test('seven modal graphs use immutable version API and preserve source files',async()=>{api();render(<RunDetail runRef={fixtureRuns[0]} onReference={vi.fn()}/>);const tabs=await screen.findAllByRole('tab');expect(tabs).toHaveLength(7);
 for(const tab of tabs){fireEvent.click(tab);expect(tab).toHaveAttribute('aria-selected','true');expect(screen.getByRole('tabpanel')).toBeInTheDocument();}expect(screen.getByText('synthetic.dat')).toBeInTheDocument();expect(fetch).toHaveBeenCalledWith('/api/run-versions/v-RUN-P06-S300-B0600',expect.anything());
});
test('Bias-off modal disables unavailable files but keeps scalar values and residual',async()=>{api();render(<RunDetail runRef={syntheticRun(0)} onReference={vi.fn()}/>);await screen.findByRole('tab',{name:'Residual Convergence'});expect(screen.getByRole('tab',{name:'Ion Energy Distribution'})).toBeDisabled();expect(screen.getByRole('tab',{name:'Residual Convergence'})).toHaveAttribute('aria-selected','true');});
test('missing API never inserts fixture Runs',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({message:'Unavailable'}),{status:503})));render(<AnalysisPage/>);await screen.findByRole('alert');expect(screen.queryByRole('button',{name:/RUN-P/})).not.toBeInTheDocument();});
test('late version response cannot overwrite newly selected immutable Run',async()=>{
 let first!:(value:Response)=>void;let second!:(value:Response)=>void;
 vi.stubGlobal('fetch',vi.fn((url:string)=>new Promise<Response>(resolve=>{if(url.endsWith(fixtureRuns[0].runVersionId))first=resolve;else second=resolve;})));
 const {rerender}=render(<RunDetail runRef={fixtureRuns[0]}/>);rerender(<RunDetail runRef={fixtureRuns[2]}/>);
 second(new Response(JSON.stringify(fixtureRuns[2])));await screen.findByRole('tab',{name:'Ion Energy Distribution'});
 await act(async()=>{first(new Response(JSON.stringify(fixtureRuns[0])));});await waitFor(()=>expect(screen.getByRole('region')).toHaveAttribute('aria-label',`${fixtureRuns[2].runId} 실험 상세`));
});
test('analysis reference and decision actions pass only immutable refs without graph payloads',async()=>{api();const reference=vi.fn(),decision=vi.fn();render(<AnalysisPage onReference={reference} onDecision={decision}/>);await screen.findByRole('img',{name:'IED 실제 수치 선 그래프'});fireEvent.click(screen.getAllByRole('button',{name:'이 Run으로 Agent에게 질문'})[0]);fireEvent.click(screen.getByRole('button',{name:'실험 기록'}));const expected={runId:fixtureRuns[0].runId,runVersionId:fixtureRuns[0].runVersionId};expect(reference).toHaveBeenCalledWith(expected);expect(decision).toHaveBeenCalledWith(expected);});
