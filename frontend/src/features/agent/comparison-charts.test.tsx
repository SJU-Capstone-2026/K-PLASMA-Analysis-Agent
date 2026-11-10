import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import type {ComparisonResultV3,ComparisonResultV2,RunOutput} from 'agent';
import wire from '../../../../agent/tests/support/answer-v3-wire.json';
import legacy from '../../../../agent/tests/support/answer-v2-wire.json';
import {ComparisonCharts,sameOutputSource,extent} from './ComparisonCharts';
import {RunColorsProvider} from '../../components/RunColors';
import {RunComparisonCard} from './RunComparisonCard';
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
test('mixed-sign scalar bars share a visible zero axis even when zero is close to another tick',()=>{
 const result=structuredClone(legacy.comparison.result) as ComparisonResultV2;
 result.metricIds=['potential.maximum'];
 result.runs.forEach((run,index)=>{
  run.metrics['potential.maximum']={status:'AVAILABLE',unit:'V',value:index===0?-8:0.1,reason:null,sourceValue:null};
 });
 render(<ComparisonCharts result={result} compact/>);
 const chart=screen.getByRole('img',{name:/막대 그래프/});
 const zeroLine=chart.querySelector('.comparison-zero-line');
 expect(zeroLine).toBeInTheDocument();
 const zero=Number(zeroLine?.getAttribute('y1'));
 const negative=chart.querySelector('[data-run-key="R1"]');
 const positive=chart.querySelector('[data-run-key="R2"]');
 expect(Number(negative?.getAttribute('y'))).toBeCloseTo(zero);
 expect(Number(positive?.getAttribute('y'))+Number(positive?.getAttribute('height'))).toBeCloseTo(zero);
 expect(chart.querySelector('.comparison-zero-label')).toHaveTextContent('0');
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

test('IEAD summarizes every Run version and requests only selected grids',async()=>{
 const base=wire.comparison.result as ComparisonResultV3;
 const result:ComparisonResultV3={...base,plotIds:['iead'],metricIds:['iead.maximum','iead.peakEnergy','iead.peakAngle'],resultStatus:'COMPARISON_PARTIAL',
  runs:Array.from({length:12},(_,index)=>({...base.runs[0],key:`R${index+1}`,ref:{
   runId:index<2?'SYNTHETIC-IEAD':`SYNTHETIC-IEAD-${index+1}`,runVersionId:`iead-version-${index+1}`,
  },metrics:{
   'iead.maximum':{value:null,unit:'원본 단위 미지정',status:'UNAVAILABLE',reason:index===11?'INSUFFICIENT_DATA':'UNIT_NOT_COMPARABLE',
    sourceValue:index===0?{value:0.0000123,unit:'원본 단위 미지정'}:null},
   'iead.peakEnergy':{value:index===11?null:200+index,unit:'eV',status:index===11?'UNAVAILABLE':'AVAILABLE',reason:index===11?'INSUFFICIENT_DATA':null,sourceValue:null},
   'iead.peakAngle':{value:index===11?null:10+index,unit:'°',status:index===11?'UNAVAILABLE':'AVAILABLE',reason:index===11?'INSUFFICIENT_DATA':null,sourceValue:null},
  }})),comparisons:[],summaries:[],
 };
 const outputs=result.runs.map((run,index):RunOutput=>{
  const missing=index===11;
  const maximum=index===0?0.0000123:index+4;
  return {
   metadata:{...wire.outputs[0].metadata,ref:run.ref,outputId:'iead',status:missing?'UNAVAILABLE':'AVAILABLE',
    reason:missing?'BIAS_OFF':null,sourceIntegrity:'iead-synthetic',sourceCount:4,xUnit:'°',yUnit:'eV',valueUnit:'원본 단위 미지정',
    extrema:missing?{}:{maximum:{value:maximum,x:10+index,y:200+index,count:1}}},
   features:{},display:missing?null:{kind:'grid',samples:[],rows:[
    {x:index-10,coordinates:[100+index,200+index],values:[0,maximum/4]},
    {x:index+10,coordinates:[100+index,200+index],values:[maximum/2,maximum]},
   ]},
  };
 });
 result.outputs=outputs.map(output=>output.metadata);
 const fetch=vi.fn(async(_url:string,request:RequestInit)=>{
  const {runRefs}=JSON.parse(String(request.body));
  return Response.json({outputs:outputs.filter(output=>runRefs.some((ref:{runVersionId:string})=>ref.runVersionId===output.metadata.ref.runVersionId))});
 });
 vi.stubGlobal('fetch',fetch);
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(null);
 try {
  render(<RunComparisonCard result={result} compact/>);
  const summary=screen.getByRole('table',{name:'IEAD 실험별 요약'});
  expect(within(summary).getAllByRole('row')).toHaveLength(13);
  expect(within(summary).getByText('1.23e-5')).toBeVisible();
  expect(within(summary).getByText('201 eV')).toBeVisible();
  expect(within(summary).getByText('11 °')).toBeVisible();
  expect(within(summary).getByRole('checkbox',{name:/R12 SYNTHETIC-IEAD-12/})).toBeDisabled();
  expect(within(summary).getByText('바이어스 꺼짐')).toBeVisible();
  expect(screen.queryByRole('table',{name:'선택한 실험 수치'})).not.toBeInTheDocument();
  expect(screen.queryByText(/일부 값이나 변화율은 계산할 수 없습니다/)).not.toBeInTheDocument();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
  const first=within(summary).getByRole('checkbox',{name:/R1 SYNTHETIC-IEAD /});
  const second=within(summary).getByRole('checkbox',{name:/R2 SYNTHETIC-IEAD /});
  fireEvent.click(first);
  await screen.findByRole('img',{name:/R1 SYNTHETIC-IEAD /});
  expect(JSON.parse(String(fetch.mock.calls[0][1].body))).toEqual({runRefs:[result.runs[0].ref],plotIds:['iead']});
  fireEvent.click(second);
  await screen.findByRole('img',{name:/R2 SYNTHETIC-IEAD /});
  expect(JSON.parse(String(fetch.mock.calls[1][1].body))).toEqual({runRefs:[result.runs[1].ref],plotIds:['iead']});
  for(const heatmap of screen.getAllByRole('img')){
   expect(within(heatmap).getByText('-10',{selector:'text'})).toBeVisible();
   expect(within(heatmap).getByText('201',{selector:'text'})).toBeVisible();
  }
  expect(screen.getByText('5',{selector:'.comparison-iead-color-key span'})).toBeVisible();
  fireEvent.click(first);
  await waitFor(()=>expect(screen.getAllByRole('img')).toHaveLength(1));
  expect(fetch).toHaveBeenCalledTimes(2);
  fetch.mockRejectedValueOnce(new Error('IEAD source request failed'));
  fireEvent.click(within(summary).getByRole('checkbox',{name:/R3 SYNTHETIC-IEAD-3/}));
  expect(await screen.findByRole('alert')).toHaveTextContent('IEAD source request failed');
  await waitFor(()=>expect(screen.getByRole('img',{name:/R2 SYNTHETIC-IEAD /})).toBeVisible());
 } finally {vi.restoreAllMocks();}
});
