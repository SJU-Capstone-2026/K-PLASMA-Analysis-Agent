import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import type {AgentRequestView,RunOption,Snapshot} from 'agent';
import {ComparisonOptionsPanel,RunSelectionPanel} from './RunSelectionPanel';
const request={requestId:'request',requestRevision:2,status:'NEEDS_INPUT',graphVersion:'v2',pendingInput:{type:'run_selection',id:'pending',message:'실험을 선택하세요',minSelections:2,baselineRequired:false}} as AgentRequestView;
const v2Request:AgentRequestView={...request,graphVersion:'v2',pendingInput:{type:'run_selection',id:'pending',message:'실험을 선택하세요',minSelections:2,baselineRequired:false}};
test('comparison options submit only the fields requested by the graph',async()=>{
 const resume=vi.fn(async(input:Snapshot)=>{void input;});
 const options={...request,pendingInput:{type:'comparison_options' as const,id:'baseline',message:'기준 선택',fields:['baselineKey'],allowedRunKeys:['R1','R2'],
  options:[{label:'R2 · SYN-B',input:{type:'comparison_options',baselineKey:'R2'}}]}};
 render(<ComparisonOptionsPanel request={options} sending={false} onResume={resume} onCancel={async()=>{}} onError={()=>{}}/>);
 expect(screen.getByRole('option',{name:'R2 · SYN-B'})).toHaveValue('R2');
 expect(screen.getByRole('option',{name:'R1'})).toHaveValue('R1');
 fireEvent.change(screen.getByLabelText('기준 실험'),{target:{value:'R2'}});
 fireEvent.click(screen.getByRole('button',{name:'선택하고 계속'}));
 await waitFor(()=>expect(resume).toHaveBeenCalledWith({type:'comparison_options',baselineKey:'R2'}));
});
const datum={value:8,unit:'mTorr',status:'AVAILABLE',reason:null,sourceValue:null} as const;
const options:RunOption[]=Array.from({length:150},(_,i)=>({key:`R${i+1}`,ref:{runId:`Run-${i}`,runVersionId:`version-${i}`},conditions:{pressure:datum,sourcePower:{...datum,value:300,unit:'W'},biasPower:{...datum,value:600,unit:'W'}},selectable:i!==2,unavailableReason:i===2?'RUN_VERSION_DELETED':null}));
afterEach(()=>vi.unstubAllGlobals());
test.each(['v2','v2_localLLM'] as const)('%s Run selection retains cancellation',async(graphVersion)=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({requestId:'request',requestRevision:2,pendingInputId:'pending',options:options.slice(0,2)})));
 const cancel=vi.fn(async()=>{});
 render(<RunSelectionPanel request={{...v2Request,graphVersion}} sending={false} onResume={async()=>{}} onCancel={cancel} onError={()=>{}}/>);
 await screen.findByRole('checkbox',{name:/R1 · Run-0/});
 fireEvent.click(screen.getByRole('button',{name:'분석 취소'}));
 await waitFor(()=>expect(cancel).toHaveBeenCalledTimes(1));
});

test('local search and sort preserve exact selected aliases and all-select does not trim to a page',async()=>{
 const fetch=vi.fn<(input:RequestInfo|URL)=>Promise<Response>>(async()=>Response.json({requestId:'request',requestRevision:2,pendingInputId:'pending',searchCriteria:{constraints:[{metric:'ionFlux',operator:'gte',value:50,unit:'10¹⁸ m⁻²s⁻¹'}],goals:[]},options:options.map((option,index)=>index===0?{...option,searchMeasurements:{ionFlux:{...datum,value:74.17,unit:'10¹⁸ m⁻²s⁻¹'}}}:option)}));vi.stubGlobal('fetch',fetch);
 const resume=vi.fn(async(input:Snapshot)=>{void input;});render(<RunSelectionPanel request={v2Request} sending={false} onResume={resume} onError={()=>{}}/>);
 await screen.findByRole('checkbox',{name:/R1 · Run-0/});
 expect(screen.getByText('이온 플럭스 50 × 10¹⁸ m⁻²s⁻¹ 이상 조건에 맞는 Run을 150개 찾았어요.')).toBeVisible();
 expect(screen.getByText('이온 플럭스 74.17 × 10¹⁸ m⁻²s⁻¹')).toBeVisible();
 fireEvent.click(screen.getByRole('checkbox',{name:/R1 · Run-0/}));fireEvent.click(screen.getByRole('checkbox',{name:/R2 · Run-1 ·/}));
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'Run-149'}});
 expect(screen.queryByText('버전 version-149')).not.toBeInTheDocument();
 fireEvent.click(screen.getByText('선택 옵션'));
 fireEvent.change(screen.getByRole('combobox',{name:'목록 정렬'}),{target:{value:'descending'}});
 expect(screen.getByRole('button',{name:'선택한 실험으로 계속'})).toBeEnabled();
 fireEvent.click(screen.getByRole('button',{name:'선택한 실험으로 계속'}));
 await waitFor(()=>expect(resume).toHaveBeenCalledWith({type:'run_selection',runKeys:['R1','R2'],baselineKey:null}));
 fireEvent.click(screen.getByRole('button',{name:'선택 가능한 실험 전체 선택'}));fireEvent.click(screen.getByRole('button',{name:'선택한 실험으로 계속'}));
 await waitFor(()=>expect(resume.mock.calls[1]?.[0].runKeys).toHaveLength(149));expect(fetch).toHaveBeenCalledTimes(1);
 expect(String(fetch.mock.calls[0]?.[0])).not.toContain('format=2');
});

test('search order survives filtering and exactly two selected Runs are required',async()=>{
 const source=[options[3],options[1],options[0]];
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({
  requestId:'request',requestRevision:2,pendingInputId:'pending',options:source,
  searchCriteria:{constraints:[],goals:[{metric:'ionFlux',direction:'maximize'}]},
 })));
 const resume=vi.fn(async()=>{});
 const exact={...v2Request,pendingInput:{...v2Request.pendingInput!,minSelections:2,maxSelections:2}};
 render(<RunSelectionPanel request={exact} sending={false} onResume={resume} onError={()=>{}}/>);
 await screen.findByRole('checkbox',{name:/R4 · Run-3/});
 expect(screen.getAllByRole('checkbox').map(box=>box.getAttribute('aria-label'))).toEqual(
  source.map(option=>`${option.key} · ${option.ref.runId} · ${option.ref.runVersionId}`),
 );
 const continueButton=screen.getByRole('button',{name:'선택한 실험으로 계속'});
 fireEvent.click(screen.getByRole('checkbox',{name:/R4 · Run-3/}));
 expect(continueButton).toBeDisabled();
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'Run-1'}});
 fireEvent.click(screen.getByRole('checkbox',{name:/R2 · Run-1 ·/}));
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:''}});
 expect(screen.getByText('2/2개 선택')).toBeVisible();
 expect(screen.getByRole('checkbox',{name:/R1 · Run-0/})).toBeDisabled();
 expect(continueButton).toBeEnabled();
 fireEvent.click(screen.getByText('선택 옵션'));
 fireEvent.change(screen.getByLabelText('목록 정렬'),{target:{value:'ascending'}});
 fireEvent.change(screen.getByLabelText('목록 정렬'),{target:{value:'source'}});
 expect(screen.getAllByRole('checkbox')[0]).toHaveAccessibleName(/R4 · Run-3/);
 fireEvent.click(continueButton);
 await waitFor(()=>expect(resume).toHaveBeenCalledWith({type:'run_selection',runKeys:['R4','R2'],baselineKey:null}));
 fireEvent.click(screen.getByRole('checkbox',{name:/R4 · Run-3/}));
 expect(screen.getByRole('checkbox',{name:/R1 · Run-0/})).toBeEnabled();
 expect(continueButton).toBeDisabled();
});
