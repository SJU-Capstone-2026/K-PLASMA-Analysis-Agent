import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import type {AgentRequestView,RunOption,Snapshot} from 'agent';
import {ComparisonOptionsPanel,RunSelectionPanel} from './RunSelectionPanel';
const request={requestId:'request',requestRevision:2,status:'NEEDS_INPUT',pendingInput:{type:'run_selection',id:'pending',message:'실험을 선택하세요',minSelections:2,baselineRequired:false}} as AgentRequestView;
test('comparison options submit only the fields requested by the graph',async()=>{
 const resume=vi.fn(async(input:Snapshot)=>{void input;});
 const options={...request,pendingInput:{type:'comparison_options' as const,id:'baseline',message:'기준 선택',fields:['baselineKey'],allowedRunKeys:['R1','R2']}};
 render(<ComparisonOptionsPanel request={options} sending={false} onResume={resume} onError={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('기준 실험'),{target:{value:'R2'}});
 fireEvent.click(screen.getByRole('button',{name:'선택하고 계속'}));
 await waitFor(()=>expect(resume).toHaveBeenCalledWith({type:'comparison_options',baselineKey:'R2'}));
});
const datum={value:8,unit:'mTorr',status:'AVAILABLE',reason:null,sourceValue:null} as const;
const options:RunOption[]=Array.from({length:150},(_,i)=>({key:`R${i+1}`,ref:{runId:`Run-${i}`,runVersionId:`version-${i}`},conditions:{pressure:datum,sourcePower:{...datum,value:300,unit:'W'},biasPower:{...datum,value:600,unit:'W'}},selectable:i!==2,unavailableReason:i===2?'RUN_VERSION_DELETED':null}));
afterEach(()=>vi.unstubAllGlobals());
test('local search and sort preserve exact selected aliases and all-select does not trim to a page',async()=>{
 const fetch=vi.fn(async()=>Response.json({requestId:'request',requestRevision:2,pendingInputId:'pending',options}));vi.stubGlobal('fetch',fetch);
 const resume=vi.fn(async(input:Snapshot)=>{void input;});render(<RunSelectionPanel request={request} sending={false} onResume={resume} onError={()=>{}}/>);
 await screen.findByRole('checkbox',{name:/R1 · Run-0/});
 fireEvent.click(screen.getByRole('checkbox',{name:/R1 · Run-0/}));fireEvent.click(screen.getByRole('checkbox',{name:/R2 · Run-1 ·/}));
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'Run-149'}});
 fireEvent.change(screen.getByRole('combobox',{name:'목록 정렬'}),{target:{value:'descending'}});
 expect(screen.getByRole('button',{name:'선택한 실험으로 계속'})).toBeEnabled();
 fireEvent.click(screen.getByRole('button',{name:'선택한 실험으로 계속'}));
 await waitFor(()=>expect(resume).toHaveBeenCalledWith({type:'run_selection',runKeys:['R1','R2'],baselineKey:null}));
 fireEvent.click(screen.getByRole('button',{name:'선택 가능한 실험 전체 선택'}));fireEvent.click(screen.getByRole('button',{name:'선택한 실험으로 계속'}));
 await waitFor(()=>expect(resume.mock.calls[1]?.[0].runKeys).toHaveLength(149));expect(fetch).toHaveBeenCalledTimes(1);
});
