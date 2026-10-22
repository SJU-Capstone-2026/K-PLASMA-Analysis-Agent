import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import type {AgentRequestView,RunOption,Snapshot} from 'agent';
import {ComparisonOptionsPanel,RunSelectionPanel} from './RunSelectionPanel';
const request={requestId:'request',requestRevision:2,status:'NEEDS_INPUT',pendingInput:{type:'run_selection',id:'pending',message:'실험을 선택하세요',minSelections:2,baselineRequired:false,optionsFormat:2}} as AgentRequestView;
test('comparison options submit only the fields requested by the graph',async()=>{
 const resume=vi.fn(async(input:Snapshot)=>{void input;});
 const options={...request,pendingInput:{type:'comparison_options' as const,id:'baseline',message:'기준 선택',fields:['baselineKey'],allowedRunKeys:['R1','R2']}};
 render(<ComparisonOptionsPanel request={options} sending={false} onResume={resume} onError={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('기준 실험'),{target:{value:'R2'}});
 fireEvent.click(screen.getByRole('button',{name:'선택하고 계속'}));
 await waitFor(()=>expect(resume).toHaveBeenCalledWith({type:'comparison_options',baselineKey:'R2'}));
});
const datum={value:8,unit:'mTorr',status:'AVAILABLE',reason:null,sourceValue:null} as const;
const options:RunOption[]=Array.from({length:150},(_,i)=>({key:`R${i+1}`,ref:{runId:`Run-${i}`,runVersionId:`version-${i}`},conditions:{biasPower:{...datum,value:600,unit:'W'},pressure:datum,sourcePower:{...datum,value:300,unit:'W'}},selectable:i!==2,unavailableReason:i===2?'RUN_VERSION_DELETED':null}));
afterEach(()=>vi.unstubAllGlobals());
function pickerServer(){
 let revision=0;const chosen=new Set<string>();let baseline:string|null=null;
 const fetch=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const url=new URL(String(input),'http://local');const isSelected=url.pathname.endsWith('/run-selection');
  const body=init?.body?JSON.parse(String(init.body)):null;
  if(body){
   expect(body.expectedSelectionRevision).toBe(revision);
   if(body.operation==='add')body.keys.forEach((key:string)=>chosen.add(key));
   if(body.operation==='remove')body.keys.forEach((key:string)=>chosen.delete(key));
   if(body.operation==='search'||body.operation==='all')options.filter(o=>o.selectable&&(body.operation==='all'||o.ref.runId.includes(body.query))).forEach(o=>chosen.add(o.key));
   if(body.operation==='clear')chosen.clear();if(body.operation==='baseline')baseline=body.baselineKey;revision++;
  }
  const query=url.searchParams.get('query')??'';const filtered=options.filter(o=>(!isSelected||chosen.has(o.key))&&o.ref.runId.toLowerCase().includes(query.toLowerCase()));
  if(url.pathname.endsWith('/count'))return Response.json({matchingCount:filtered.length,totalCount:150});
  const offset=Number(url.searchParams.get('cursor')??0);const page=filtered.slice(offset,offset+30).map(o=>({...o,selected:chosen.has(o.key)}));
  return Response.json({format:2,requestId:'request',requestRevision:2,pendingInputId:'pending',snapshotId:'snapshot',selectionRevision:revision,baselineKey:baseline,totalCount:150,options:page,hasMore:filtered.length>offset+30,nextCursor:filtered.length>offset+30?String(offset+30):null,selectedCount:chosen.size,unavailableCount:0});
 });vi.stubGlobal('fetch',fetch);return fetch;
}
test('DB pages preserve selections across searches and resume with a bounded snapshot token',async()=>{
 const fetch=pickerServer();const resume=vi.fn(async(input:Snapshot)=>{void input;});
 render(<RunSelectionPanel request={request} sending={false} onResume={resume} onError={()=>{}}/>);
 await screen.findByRole('checkbox',{name:/R1 · Run-0/});expect(screen.getAllByRole('checkbox')).toHaveLength(30);
 expect(screen.getAllByText('8 mTorr · 300 W · 600 W')).toHaveLength(30);
 fireEvent.click(screen.getByRole('checkbox',{name:/R1 · Run-0/}));
 await screen.findByText(/선택 1개/);
 fireEvent.click(screen.getByRole('button',{name:'다음 페이지'}));
 await screen.findByRole('checkbox',{name:/R31 · Run-30/});fireEvent.click(screen.getByRole('checkbox',{name:/R31 · Run-30/}));
 await screen.findByText(/선택 2개/);
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'no-match'}});fireEvent.keyDown(screen.getByRole('searchbox'),{key:'Enter'});
 await screen.findByText('검색에 맞는 실험이 없습니다. 기존 선택은 유지됩니다.');
 await waitFor(()=>expect(screen.getByRole('button',{name:'선택한 실험으로 계속'})).toBeEnabled());
 fireEvent.click(screen.getByRole('button',{name:'선택한 실험으로 계속'}));
 await waitFor(()=>expect(resume).toHaveBeenCalledWith({type:'run_selection',snapshotId:'snapshot',selectionRevision:2}));
 expect(fetch.mock.calls.some(([url])=>String(url).includes('format=2'))).toBe(true);
});
test('page, search-all and catalogue-all selection are distinct server operations',async()=>{
 const fetch=pickerServer();render(<RunSelectionPanel request={request} sending={false} onResume={async()=>{}} onError={()=>{}}/>);
 await screen.findByRole('checkbox',{name:/R1 · Run-0/});
 await waitFor(()=>expect(screen.getByRole('button',{name:'현재 페이지 선택'})).toBeEnabled());
 fireEvent.click(screen.getByRole('button',{name:'현재 페이지 선택'}));await screen.findByText(/선택 29개/);
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'Run-149'}});fireEvent.keyDown(screen.getByRole('searchbox'),{key:'Enter'});
 await screen.findByRole('checkbox',{name:/R150 · Run-149/});
 fireEvent.click(screen.getByRole('button',{name:'검색 결과 전체 선택'}));await screen.findByText(/선택 30개/);
 fireEvent.click(screen.getByRole('button',{name:'전체 실험 선택'}));await screen.findByText(/선택 149개/);
 expect(screen.getAllByRole('checkbox')).toHaveLength(1);
 const mutations=fetch.mock.calls.filter(([,init])=>init?.method==='POST').map(([,init])=>JSON.parse(String(init?.body)));
 expect(mutations.map(m=>m.operation)).toEqual(['add','search','all']);expect(mutations[0].keys).toHaveLength(29);
});

test('a late response from an older search cannot replace the newest page',async()=>{
 const server=pickerServer();let release:((response:Response)=>void)|undefined;
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const url=new URL(String(input),'http://local');
  if(url.pathname.endsWith('/run-options')&&url.searchParams.get('query')==='Run-1'){
   const response=await server(input,init);return new Promise<Response>(resolve=>{release=()=>resolve(response);});
  }
  return server(input,init);
 }));
 render(<RunSelectionPanel request={request} sending={false} onResume={async()=>{}} onError={()=>{}}/>);
 await screen.findByRole('checkbox',{name:/R1 · Run-0/});
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'Run-1'}});fireEvent.keyDown(screen.getByRole('searchbox'),{key:'Enter'});
 await waitFor(()=>expect(release).toBeDefined());
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'Run-149'}});fireEvent.keyDown(screen.getByRole('searchbox'),{key:'Enter'});
 await screen.findByRole('checkbox',{name:/R150 · Run-149/});release!(Response.json({}));
 await waitFor(()=>expect(screen.getAllByRole('checkbox')).toHaveLength(1));
 expect(screen.getByRole('checkbox',{name:/R150 · Run-149/})).toBeInTheDocument();
});

test('an ambiguous save failure retries the same mutation key without adding twice',async()=>{
 const server=pickerServer();let mutationKey:string|undefined;let calls=0;
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  if(init?.method==='POST'){
   calls++;const key=new Headers(init.headers).get('Idempotency-Key')!;
   if(calls===1){mutationKey=key;await server(input,init);throw new Error('연결 끊김');}
   expect(key).toBe(mutationKey);
   return server('/api/agent/requests/request/run-selection?pendingInputId=pending');
  }
  return server(input,init);
 }));
 render(<RunSelectionPanel request={request} sending={false} onResume={async()=>{}} onError={()=>{}}/>);
 await screen.findByRole('checkbox',{name:/R1 · Run-0/});fireEvent.click(screen.getByRole('checkbox',{name:/R1 · Run-0/}));
 await screen.findByRole('alert');expect(screen.getByRole('button',{name:'선택한 실험으로 계속'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'선택 저장 다시 시도'}));
 await waitFor(()=>expect(screen.queryByRole('alert')).not.toBeInTheDocument());
 expect(calls).toBe(2);expect(screen.getByText(/선택 1개/)).toBeInTheDocument();
});
