import {render,screen} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import {analysisLineChart,renderIeAdHeatmap,renderDensityHeatmap,comparisonLineChart,svgChart,compactNumber,renderAnalysisChartContent} from './charts';
import {syntheticRun} from '../test/runs';
test('line SVG preserves original scale, finite sample filtering and rounded path',()=>{const {container}=render(analysisLineChart([[0,1],[1,2],[NaN,3]]));expect(screen.getByRole('img')).toHaveAttribute('viewBox','0 0 680 280');expect(container.querySelector('.analysis-line')).toHaveAttribute('d','M58.0 127.0 L660.0 18.0');expect(container.querySelectorAll('.analysis-grid-line')).toHaveLength(3);expect(container.querySelectorAll('line text')).toHaveLength(0);});
test('strict marker uses log range only when threshold is inside plot',()=>{const {container,rerender}=render(analysisLineChart([[0,1e-5],[1,0],[2,1e-9]],{logY:true,threshold:1e-8}));expect(container.querySelector('.analysis-threshold')).toHaveAttribute('y1','181.5');expect(container.querySelector('.analysis-line')).toHaveAttribute('d','M58.0 18.0 L660.0 236.0');rerender(analysisLineChart([[0,1e-5],[2,2e-8]],{logY:true,threshold:1e-8}));expect(container.querySelector('.analysis-threshold')).toBeNull();});
test('IEAD row reversal and density original irregular distances preserve cell geometry',()=>{const {container,rerender}=render(renderIeAdHeatmap({energies:[1,2],angles:[0,10],values:[1,2,3,4],sourceShape:[2,2],angleRange:[0,10]}));let rects=container.querySelectorAll('rect');expect(rects[0]).toHaveAttribute('y','166.00');expect(rects[0]).toHaveAttribute('width','319.25');expect(rects[2]).toHaveAttribute('y','20.00');rerender(renderDensityHeatmap({rows:[[0,[0,.1],[1,2]],[1,[0,.2],[2,3]]],sourceShape:[2,2]}));rects=container.querySelectorAll('rect');expect(rects[1]).toHaveAttribute('y','93.00');expect(rects[1]).toHaveAttribute('height','146.50');expect(rects[3]).toHaveAttribute('height','292.50');});
test('nonpositive heatmap samples stay unavailable, empty charts remain empty',()=>{const {container,rerender}=render(renderIeAdHeatmap({energies:[1],angles:[0],values:[0],sourceShape:[1,1],angleRange:[0,0]}));expect(container.querySelector('rect')).toHaveAttribute('fill','#f2f5fb');rerender(analysisLineChart([]));expect(screen.getByText('표시할 실제 수치가 없습니다.')).toBeInTheDocument();expect(container.querySelector('svg')).toBeNull();});
test('legacy comparison and compact IED preserve original SVG boundary without adding navigation',()=>{const {container,rerender}=render(comparisonLineChart([{available:true,runId:'B',points:[[0,-1],[1,1]]},{available:false,runId:'A',points:[]}]));expect(screen.getByRole('img')).toHaveAttribute('viewBox','0 0 760 300');expect(container.querySelector('.comparison-line')).toHaveAttribute('style','--series-color: #4168e8;');rerender(svgChart(Array.from({length:9},(_,x)=>({x,y:x+1})),true));expect(screen.getByRole('img')).toHaveAttribute('viewBox','0 0 520 180');expect(container.querySelectorAll('circle')).toHaveLength(3);expect(compactNumber(.0001)).toBe('1.00e-4');});

test('analysis uses the plotted grid dimensions and source units',()=>{
 const run=syntheticRun();
 run.analysis.iead!.sourceShape=[201,2136];
 const {rerender}=render(renderAnalysisChartContent(run,'distribution'));
 expect(screen.getByText('2 × 2 actual samples')).toBeInTheDocument();
 rerender(renderAnalysisChartContent(run,'density'));
 expect(screen.getByText('2 × 2 actual samples')).toBeInTheDocument();
 expect(screen.getByText('Distance (cm)')).toBeInTheDocument();
 rerender(renderAnalysisChartContent(run,'waveforms'));
 expect(screen.getByText('Current density (statampere/cm²)')).toBeInTheDocument();
});

test('large IEAD draws original cells with logarithmic colors and reversed angle axis',()=>{
 const context={createImageData:(width:number,height:number)=>({width,height,data:new Uint8ClampedArray(width*height*4)}),putImageData:vi.fn()};
 const getContext=vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
 try {
  const angles=Array.from({length:201},(_,index)=>index);
  const energies=Array.from({length:2136},(_,index)=>index);
  const values=Array(angles.length*energies.length).fill(1);
  values[0]=0;
  values[values.length-1]=100;
  const {container}=render(renderIeAdHeatmap({angles,energies,values,sourceShape:[angles.length,energies.length],angleRange:[0,200]}));
  expect(screen.getByRole('img',{name:'Ion Energy Angle Distribution 실제 수치 히트맵'})).toContainElement(container.querySelector('canvas'));
  expect(container.querySelectorAll('rect')).toHaveLength(0);
  const [{width,height,data}]=context.putImageData.mock.calls[0];
  expect(width).toBeGreaterThanOrEqual(energies.length);
  expect(height).toBeGreaterThanOrEqual(angles.length);
  expect(Array.from(data.slice(4*(height-1)*width,4*(height-1)*width+4))).toEqual([242,245,251,255]);
  expect(Array.from(data.slice(4*(width-1),4*width))).toEqual([34,76,170,255]);
  expect(Array.from(data.slice(0,4))).toEqual([239,244,255,255]);
 } finally {
  getContext.mockRestore();
 }
});

test('large density draws every distance from each original phase column',()=>{
 const context={clearRect:vi.fn(),fillRect:vi.fn()};
 const getContext=vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
 try {
  const rows=Array.from({length:601},(_,phase):[number,number[],number[]]=>[
   (phase/600)**2,Array.from({length:31},(_,distance)=>distance*(phase===0?.002:.003)),Array(31).fill(phase+1),
  ]);
  const {container}=render(renderDensityHeatmap({rows,sourceShape:[601,31]}));
  expect(screen.getByRole('img',{name:'위상별 쉬스 이온 밀도 실제 수치 히트맵'})).toContainElement(container.querySelector('canvas'));
  expect(context.fillRect).toHaveBeenCalledTimes(601*31);
  const firstEdge=context.fillRect.mock.calls[30];
  const lastEdge=context.fillRect.mock.calls.at(-1)!;
  expect(firstEdge[1]).toBeGreaterThan(lastEdge[1]);
  expect(firstEdge[2]).toBeLessThan(lastEdge[2]);
 } finally {
  getContext.mockRestore();
 }
});
