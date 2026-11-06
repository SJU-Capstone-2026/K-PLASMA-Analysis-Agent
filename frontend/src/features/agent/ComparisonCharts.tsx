import {useCallback,useEffect,useId,useMemo,useRef,useState} from 'react';
import type {ComparisonField,ComparisonResultV2,ComparisonResultV3,ComparisonRun,OutputMetadata,PlotId,RunOutput} from 'agent';
import {useRunColors,fixedRunColors} from '../../components/RunColors';
import {fetchRunOutputs} from '../../api/runs';
import {measurementText,metricNames,numberText,reasons} from './agent-contract';
import {ComparisonGridCanvas,gridColors} from './ComparisonGridCanvas';
export const plotNames:Record<PlotId,string>={ied:'이온 에너지 분포',iad:'이온 입사각 분포',iead:'에너지·입사각 분포',current:'RF 전류 밀도',potential:'전극 전위',density:'쉬스 이온 밀도',residual:'수렴 잔차'};
const cache=new Map<string,RunOutput>();
const ieadCache=new Map<string,RunOutput>();
const inFlight=new Map<string,Promise<RunOutput>>();
const sourceKey=(m:OutputMetadata)=>JSON.stringify([m.ref.runId,m.ref.runVersionId,m.outputId,m.sourceIntegrity,m.xUnit,m.yUnit,m.valueUnit]);
export function sameOutputSource(a:OutputMetadata,b:OutputMetadata){return sourceKey(a)===sourceKey(b);}
export const extent=(values:Iterable<number>):[number,number]=>{let min=Infinity,max=-Infinity;for(const value of values){min=Math.min(min,value);max=Math.max(max,value);}if(!Number.isFinite(min)||!Number.isFinite(max))return [0,1];return min===max?[min-1,max+1]:[min,max];};
const scale=(value:number,[min,max]:[number,number],start:number,end:number)=>start+(value-min)/(max-min)*(end-start);
const chartNumberText=(value:number)=>value!==0&&(Math.abs(value)>=1e6||Math.abs(value)<.01)?value.toExponential(2).replace('e+','e'):numberText(value);
const chartHeight=(compact:boolean)=>compact?184:330;
function useCompactChartWidth<T extends Element>(compact:boolean){
 const [width,setWidth]=useState(0);
 const ref=useCallback((element:T|null)=>{
  if(!compact||!element)return;
  const measure=()=>setWidth(element.clientWidth);
  measure();
  if(typeof ResizeObserver==='undefined')return;
  const observer=new ResizeObserver(measure);
  observer.observe(element);
  return ()=>observer.disconnect();
 },[compact]);
 return [ref,width] as const;
}
function chartLayout(yRange:[number,number],width=650,compact=false){
 const ticks=[0,.5,1].map(t=>({t,value:yRange[0]+t*(yRange[1]-yRange[0])}));
 const left=Math.max(52,...ticks.map(tick=>chartNumberText(tick.value).length*7+16));
 return {left,right:width-24,top:compact?24:32,bottom:compact?148:250,ticks};
}
function gridValueRange(rows:NonNullable<RunOutput['display']>['rows']):[number,number]{
 let min=Infinity,max=-Infinity;
 for(const row of rows)for(const value of row.values){min=Math.min(min,value);max=Math.max(max,value);}
 return [min,max];
}
const metadataReasons:Record<string,string>={BIAS_OFF:'바이어스 꺼짐',IAD_NOT_INDEXED:'IAD 데이터 미등록',OUTPUT_NOT_INDEXED:'출력 데이터 미등록',SOURCE_MISSING:'원본 파일 없음',SOURCE_INVALID:'원본 형식 확인 필요',VERSION_UNAVAILABLE:'실험 버전 없음',SOURCE_INTEGRITY_MISMATCH:'원본 무결성 불일치',SOURCE_MISMATCH:'답변에 저장된 원본·단위와 현재 그래프가 다릅니다.'};
const outputUnavailable='그래프를 표시할 수 없습니다.';
function Frame({children,xLabel,yLabel,xRange,yRange,categorical=false,width=650,compact=false}:{children:React.ReactNode;xLabel:string;yLabel?:string;xRange:[number,number];yRange:[number,number];categorical?:boolean;width?:number;compact?:boolean}){
 const {left,right,top,bottom,ticks}=chartLayout(yRange,width,compact);
 const xTickY=compact?bottom+14:284;
 const zero=categorical?scale(0,yRange,bottom,top):null;
 return <>
  <path d={`M${left} ${top}V${bottom}H${right}`} fill="none" stroke="#b7c3d6"/>
  {ticks.map(({t,value})=>{
   const y=bottom-t*(bottom-top);
   if(zero!==null&&Math.abs(y-zero)<18)return null;
   return <g key={t}>
    <line x1={left} y1={y} x2={right} y2={y} stroke="#e8edf5"/>
    <text x={left-8} y={y+4} textAnchor="end">{chartNumberText(value)}<title>{value}</title></text>
   </g>;
  })}
  {!categorical&&<>
   <text x={left} y={xTickY}>{chartNumberText(xRange[0])}<title>{xRange[0]}</title></text>
   <text x={right} y={xTickY} textAnchor="end">{chartNumberText(xRange[1])}<title>{xRange[1]}</title></text>
  </>}
  {xLabel&&<text x={(left+right)/2} y={compact?bottom+28:314} textAnchor="middle">{xLabel}</text>}
  {yLabel&&<text x={left} y="14">{yLabel}</text>}
  {children}
  {zero!==null&&<>
   <line className="comparison-zero-line" x1={left} y1={zero} x2={right} y2={zero}
    stroke="#465b75" strokeWidth="1.8" vectorEffect="non-scaling-stroke"/>
   <text className="comparison-zero-label" x={left-8} y={zero+4} textAnchor="end">0</text>
  </>}
 </>;
}
export function ScalarBars({result,metric,visible,colors,compact=false}:{result:ComparisonResultV2;metric:ComparisonField;visible:Set<string>;colors:ReadonlyMap<string,string>;compact?:boolean}){
 const runs=result.runs.filter(r=>visible.has(r.key));const valid=runs.filter(r=>r.metrics[metric]?.status==='AVAILABLE');
 const [scrollArea,availableWidth]=useCompactChartWidth<HTMLDivElement>(compact);
 if(!valid.length)return <p className="comparison-empty">표시할 수 있는 수치가 없습니다. 누락값은 0으로 그리지 않습니다.</p>;
 const values=valid.map(r=>r.metrics[metric]!.value!);let range:[number,number]=[Math.min(0,...values),Math.max(0,...values)];if(range[0]===range[1])range=[0,1];
 const allValues=result.runs.flatMap(run=>{
  const datum=run.metrics[metric];
  return datum?.status==='AVAILABLE'?[datum.value!]:[];
 });
 const labelWidth=Math.max(compact?44:55,...allValues.map(value=>
  chartNumberText(value).length*(compact?6:7)+(compact?8:12)));
 const axisSpace=compact?76:100;
 const baseWidth=compact?(availableWidth||460):650;
 const chartWidth=Math.max(baseWidth,runs.length*labelWidth+axisSpace);
 const {left,right,top,bottom}=chartLayout(range,chartWidth,compact);
 const fullWidth=Math.max(baseWidth,result.runs.length*labelWidth+axisSpace);
 const fullAxis=chartLayout([Math.min(0,...allValues),Math.max(0,...allValues)],fullWidth,compact);
 const naturalBarWidth=(fullAxis.right-fullAxis.left)/result.runs.length*.6;
 const barWidth=compact?Math.min(72,naturalBarWidth):naturalBarWidth;
 const zero=scale(0,range,bottom,top),slot=(right-left)/runs.length,unit=valid[0].metrics[metric]!.unit;
 return <figure className="comparison-figure"><figcaption>{metricNames[metric]} <span>{unit}</span></figcaption><div ref={scrollArea} className="comparison-bar-scroll"><svg style={{minWidth:compact||runs.length>8?chartWidth:undefined}} viewBox={`0 0 ${chartWidth} ${chartHeight(compact)}`} role="img" aria-label={`${metricNames[metric]} 실험별 막대 그래프`}><Frame width={chartWidth} compact={compact} categorical xRange={[1,runs.length]} yRange={range} xLabel={compact?'':'선택한 실험'}>{runs.map((r,i)=>{const d=r.metrics[metric]!,x=left+(i+.5)*slot,y=d.status==='AVAILABLE'?scale(d.value!,range,bottom,top):zero;return <g key={r.key}><title>{r.ref.runId}: {d.status==='AVAILABLE'?`${d.value} ${d.unit}`:`비가용 ${d.reason}`}</title>{d.status==='AVAILABLE'?<rect data-run-key={r.key} x={x-barWidth/2} y={Math.min(y,zero)} width={barWidth} height={Math.max(Math.abs(y-zero),1)} rx="3" fill={colors.get(r.ref.runId)??fixedRunColors[i%5]}/>:<text x={x} y={bottom-12} textAnchor="middle">—</text>}<text x={x} y={d.value!=null&&d.value<0?y+14:y-8} textAnchor="middle">{d.status==='AVAILABLE'?chartNumberText(d.value!):''}</text><text x={x} y={compact?bottom+31:284} textAnchor="middle">{r.key}</text></g>;})}</Frame></svg></div></figure>;
}
function SourceCharts({outputs,colors,compact}:{outputs:RunOutput[];colors:ReadonlyMap<string,string>;compact:boolean}){
 const [chartRef,availableWidth]=useCompactChartWidth<SVGSVGElement>(compact);
 const width=availableWidth||650;
 const viewBox=`0 0 ${width} ${chartHeight(compact)}`;
 const available=outputs.filter(o=>o.metadata.status==='AVAILABLE'&&o.display);const line=available.filter(o=>o.display?.kind==='line');
 const grids=available.filter(o=>o.display?.kind==='grid'&&o.display.rows.length);
 const gridRows=available.flatMap(o=>o.display!.rows);
 const xr=extent(gridRows.map(row=>row.x)),yr=extent(gridRows.flatMap(row=>[row.coordinates[0],row.coordinates[row.coordinates.length-1]]));
 const valueRange=gridValueRange(gridRows),gridBox=chartLayout(yr,width,compact);
 const xs=line.flatMap(o=>o.display!.samples.map(p=>p.x)),ys=line.flatMap(o=>o.display!.samples.map(p=>p.y));
 const lineX=extent(xs),lineY=extent(ys),lineBox=chartLayout(lineY,width,compact);
 return <>{line.length>0&&<figure className="comparison-figure"><figcaption>{plotNames[line[0].metadata.outputId]} <span>{line[0].metadata.valueUnit}</span></figcaption><svg ref={chartRef} viewBox={viewBox} role="img" aria-label={`${plotNames[line[0].metadata.outputId]} 원본 파형 비교`}><Frame width={width} compact={compact} xRange={lineX} yRange={lineY} xLabel={line[0].metadata.xUnit}>{line.map((o,i)=>{const m=o.metadata,color=colors.get(m.ref.runId)??fixedRunColors[i%5];return <g key={m.ref.runVersionId}><path data-run-id={m.ref.runId} fill="none" stroke={color} strokeWidth="2.5" strokeDasharray={line.filter(other=>other.metadata.ref.runId===m.ref.runId).findIndex(other=>other===o)%2?"7 4":undefined} d={o.display!.samples.map((p,index)=>`${index?'L':'M'}${scale(p.x,lineX,lineBox.left,lineBox.right)},${scale(p.y,lineY,lineBox.bottom,lineBox.top)}`).join(' ')}><title>{m.ref.runId} · 원본 {m.sourceCount}점</title></path>{Object.entries(m.extrema).map(([name,e])=><circle key={name} cx={scale(e.x,lineX,lineBox.left,lineBox.right)} cy={scale(e.value,lineY,lineBox.bottom,lineBox.top)} r="4" fill={color}><title>{name}: {e.value} {m.valueUnit} · {e.x} {m.xUnit} · 공동 극값 {e.count}개</title></circle>)}</g>;})}</Frame></svg><small>공통 축 · 원본 지점만 표시 · 피크·진폭은 전체 원본에서 계산</small></figure>}{grids.map((o,i)=>{
  const m=o.metadata;
  return <figure className="comparison-figure" key={m.ref.runVersionId}>
   <figcaption><i className="comparison-color" style={{background:colors.get(m.ref.runId)}}/>{m.ref.runId} <span>{plotNames[m.outputId]}</span></figcaption>
   <svg ref={!line.length&&i===0?chartRef:undefined} viewBox={viewBox} role="img" aria-label={`${m.ref.runId} ${plotNames[m.outputId]} 원본 격자`}>
    <Frame width={width} compact={compact} xRange={xr} yRange={yr} xLabel={m.xUnit} yLabel={m.yUnit}>
     <foreignObject x={gridBox.left} y={gridBox.top} width={gridBox.right-gridBox.left} height={gridBox.bottom-gridBox.top}>
      <ComparisonGridCanvas rows={o.display!.rows} width={gridBox.right-gridBox.left} height={gridBox.bottom-gridBox.top}
       xRange={xr} yRange={yr} valueRange={valueRange} metadata={m}/>
     </foreignObject>
     {m.extrema.maximum?.y!=null&&<circle cx={scale(m.extrema.maximum.x,xr,gridBox.left,gridBox.right)}
      cy={scale(m.extrema.maximum.y,yr,gridBox.bottom,gridBox.top)} r="5" fill="none" stroke="#172b4d" strokeWidth="2"/>}
    </Frame>
   </svg>
   <small>공통 강도 범위 {numberText(valueRange[0])}–{numberText(valueRange[1])} · {m.valueUnit} · 원본 좌표 유지</small>
  </figure>;
 })}</>;
}

const ieadFields=['iead.maximum','iead.peakEnergy','iead.peakAngle'] as const;
const sourceNumberText=(value:number)=>value!==0&&(Math.abs(value)>=1e6||Math.abs(value)<.01)
 ?value.toExponential().replace('e+','e'):String(value);
function ieadValue(run:ComparisonRun,field:typeof ieadFields[number],metadata?:OutputMetadata){
 if(metadata?.status==='UNAVAILABLE')return '—';
 const datum=run.metrics[field];
 if(datum?.status==='AVAILABLE'&&datum.value!==null)return measurementText(sourceNumberText(datum.value),datum.unit);
 if(datum?.sourceValue?.value!=null){
  const text=sourceNumberText(datum.sourceValue.value);
  return field==='iead.maximum'?text:measurementText(text,datum.sourceValue.unit);
 }
 // Historical comparisons may have requested just a subset of metrics. Extrema are saved with the same source version.
 const peak=metadata?.extrema.maximum;
 if(peak&&metadata?.status==='AVAILABLE'&&(!datum||datum.reason==='UNIT_NOT_COMPARABLE')){
  if(field==='iead.maximum')return sourceNumberText(peak.value);
  if(field==='iead.peakAngle')return measurementText(sourceNumberText(peak.x),metadata.xUnit);
  if(peak.y!==null)return measurementText(sourceNumberText(peak.y),metadata.yUnit);
 }
 return '—';
}

function IeadSummary({runs,labels,metadata,loaded,selection,onToggle,renderActions}: {
 runs:ComparisonRun[];labels:Map<string,string>;metadata:Map<string,OutputMetadata>;loaded:Map<string,RunOutput>;
 selection:string[];onToggle:(version:string)=>void;renderActions?:(run:ComparisonRun)=>React.ReactNode;
}){
 return <section className="comparison-iead-summary" aria-label="IEAD 요약 및 히트맵 선택">
  <h4>IEAD 실험별 요약</h4>
  <p>히트맵에서 비교할 Run을 선택하세요.</p>
  <div className="v1-table-scroll comparison-iead-table-scroll" tabIndex={0}>
   <table className="v1-comparison-table" aria-label="IEAD 실험별 요약">
    <thead><tr>
     <th scope="col">히트맵</th><th scope="col">실험</th>
     {ieadFields.map(field=><th key={field} scope="col">{metricNames[field].replace('IEAD ','')}{field==='iead.maximum'&&<small>원본 단위 미지정</small>}</th>)}
     {renderActions&&<th scope="col">상세</th>}
    </tr></thead>
    <tbody>{runs.map(run=>{
     const version=run.ref.runVersionId,stored=metadata.get(version),current=loaded.get(version);
     const missing=stored?.status!=='AVAILABLE';
     const reason=missing?stored?.reason??outputUnavailable:current?.metadata.reason;
     return <tr key={run.key}>
      <td><input type="checkbox" aria-label={`${labels.get(version)} 히트맵`} checked={!missing&&selection.includes(version)} disabled={missing}
       onChange={()=>onToggle(version)}/>{reason&&<small>{metadataReasons[reason]??reason}</small>}</td>
      <th scope="row" title={version}>{labels.get(version)}</th>
      {ieadFields.map(field=>{
       const text=ieadValue(run,field,stored),reason=run.metrics[field]?.reason;
       return <td key={field}>{text}{stored?.status==='AVAILABLE'&&text==='—'&&reason&&<small>{reasons[reason]??reason}</small>}</td>;
      })}
      {renderActions&&<td className="comparison-detail">{renderActions(run)}</td>}
     </tr>;
    })}</tbody>
   </table>
  </div>
 </section>;
}

function IeadHeatmaps({outputs,labels,compact}:{outputs:RunOutput[];labels:Map<string,string>;compact:boolean}){
 const [chartRef,availableWidth]=useCompactChartWidth<SVGSVGElement>(compact);
 const grids=outputs.flatMap(({metadata,display})=>metadata.status==='AVAILABLE'&&display?.kind==='grid'&&display.rows.length
  ? [{metadata,rows:display.rows}]:[]);
 if(!grids.length)return null;
 const xRange=extent(grids.flatMap(({rows})=>[rows[0].x,rows[rows.length-1].x]));
 const yRange=extent(grids.flatMap(({rows})=>{
  const axis=rows[0].coordinates;
  return [axis[0],axis[axis.length-1]];
 }));
 const valueRange=gridValueRange(grids.flatMap(({rows})=>rows)),[min,max]=valueRange,width=availableWidth||410;
 const box=chartLayout(yRange,width,compact);
 return <>
  <div className="comparison-iead-color-key" role="group" aria-label="IEAD 공통 강도 범위">
   <strong>공통 강도</strong><span>{sourceNumberText(min)}</span>
   {min!==max&&<><i aria-hidden="true" style={{background:`linear-gradient(to right, ${gridColors.join(', ')})`}}/>
    <span>{sourceNumberText(max)}</span></>}
   <small>{grids[0].metadata.valueUnit}</small>
  </div>
  <div className="comparison-iead-heatmaps" role="region" aria-label="선택한 IEAD 히트맵" tabIndex={0}>
   {grids.map(({metadata,rows},index)=>{
    const version=metadata.ref.runVersionId,label=labels.get(version),peak=metadata.extrema.maximum;
    return <figure className="comparison-figure" key={version}>
     <figcaption title={version}>{label}</figcaption>
     <svg ref={index===0?chartRef:undefined} viewBox={`0 0 ${width} ${chartHeight(compact)}`} role="img" aria-label={`${label} IEAD 원본 격자`}>
      <Frame width={width} compact={compact} xRange={xRange} yRange={yRange} xLabel={`입사각 (${metadata.xUnit})`} yLabel={`에너지 (${metadata.yUnit})`}>
       <foreignObject x={box.left} y={box.top} width={box.right-box.left} height={box.bottom-box.top}>
        <ComparisonGridCanvas rows={rows} width={box.right-box.left} height={box.bottom-box.top} xRange={xRange} yRange={yRange}
         valueRange={valueRange} metadata={metadata} sharedY/>
       </foreignObject>
       {peak?.y!=null&&<circle cx={scale(peak.x,xRange,box.left,box.right)} cy={scale(peak.y,yRange,box.bottom,box.top)} r="4"
        fill="none" stroke="#fff" strokeWidth="1.5" style={{filter:'drop-shadow(0 0 1px #172b4d)'}}>
        <title>{peak.x} {metadata.xUnit}, {peak.y} {metadata.yUnit}: {peak.value} {metadata.valueUnit}</title>
       </circle>}
      </Frame>
     </svg>
    </figure>;
   })}
  </div>
 </>;
}

function PlotAvailability({plot,total,available,missingByReason}:{
 plot:PlotId;total:number;available:number;missingByReason:Map<string,ComparisonRun[]>;
}){
 const [open,setOpen]=useState(false);
 const panelId=useId();
 const plotLabel=plot==='iad'?'IAD':plotNames[plot];
 const missingCount=total-available;
 const allBiasOff=missingByReason.get('BIAS_OFF')?.length===total;
 return <div className="comparison-availability">
  <div className="comparison-availability-heading">
   <span>{allBiasOff
    ? `${missingCount}개 모두 바이어스가 꺼져 ${plotLabel} 출력이 없습니다.`
    : <><strong>{plotLabel} 비교</strong> · {total}개 중 {available}개 표시 가능</>}
   </span>
   <button type="button" className="comparison-availability-toggle" aria-expanded={open} aria-controls={panelId}
    onClick={()=>setOpen(!open)}>{allBiasOff?'Run 목록':`출력 없음 ${missingCount}개`}</button>
  </div>
  <div id={panelId} className="comparison-availability-body" hidden={!open}>
   {[...missingByReason].map(([reason,runs])=>{
    const reasonLabel=metadataReasons[reason]??reason;
    return <div key={reason} className="comparison-availability-group">
     {!allBiasOff&&<div className="comparison-availability-reason">{reasonLabel} · {runs.length}개</div>}
     <ul role="list" aria-label={`출력이 없는 Run · ${reasonLabel}`}>
      {runs.map(run=><li key={run.key}><small>{run.key}</small><span>{run.ref.runId}</span></li>)}
     </ul>
    </div>;
   })}
  </div>
 </div>;
}

export function ComparisonCharts({result,storageId,compact=false,renderIeadRunActions}:{
 result:ComparisonResultV2|ComparisonResultV3;storageId?:string;compact?:boolean;renderIeadRunActions?:(run:ComparisonRun)=>React.ReactNode;
}){
 const root=useRef<HTMLElement>(null);const [activated,setActivated]=useState(()=>typeof IntersectionObserver==='undefined');
 useEffect(()=>{if(activated||!root.current)return;const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setActivated(true);observer.disconnect();}},{rootMargin:'300px'});observer.observe(root.current);return()=>observer.disconnect();},[activated]);
 const extended='plotIds' in result?result:undefined,plots=extended?.plotIds??[];
 const hasIead=plots.includes('iead');
 const scalarTabs=result.metricIds.filter(id=>!(hasIead&&id==='iead.maximum')||result.runs.some(run=>run.metrics[id]?.status==='AVAILABLE'));
 const tabs=[...plots.map(id=>`plot:${id}`),...scalarTabs.map(id=>`scalar:${id}`)];
 const prefKey=storageId?`kplasma.comparison-view.v1:${storageId}`:null;
 const [prefs,setPrefs]=useState(()=>{try{const p=JSON.parse(prefKey?localStorage.getItem(prefKey)??'null':'null');return {active:tabs.includes(p?.active)?p.active:tabs[0],hidden:Array.isArray(p?.hidden)?p.hidden as string[]:[],collapsed:!!p?.collapsed,ieadSelection:Array.isArray(p?.ieadSelection)?p.ieadSelection as string[]:[]};}catch{return {active:tabs[0],hidden:[] as string[],collapsed:false,ieadSelection:[] as string[]};}});
 const ids=useMemo(()=>result.runs.map(r=>r.ref.runId),[result.runs]);const colors=useRunColors(ids);
 const [outputs,setOutputs]=useState<RunOutput[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState('');
 const lastIeadOutputs=useRef(new Map<string,RunOutput>());
 useEffect(()=>{if(prefKey)try{localStorage.setItem(prefKey,JSON.stringify(prefs));}catch{/* Browser-only chart preferences. */}},[prefKey,prefs]);
 const selectedPlot=prefs.active?.startsWith('plot:')?prefs.active.slice(5) as PlotId:null;
 const isIead=selectedPlot==='iead';
 const ieadMetadata=useMemo(()=>new Map(extended?.outputs.filter(output=>output.outputId==='iead')
  .map(output=>[output.ref.runVersionId,output])),[extended]);
 const labels=useMemo(()=>new Map(result.runs.map(run=>{
  const duplicate=result.runs.some(other=>other!==run&&other.ref.runId===run.ref.runId);
  return [run.ref.runVersionId,`${run.key} ${run.ref.runId}${duplicate?` · 버전 ${run.ref.runVersionId.slice(-8)}`:''}`];
 })),[result.runs]);
 const requestedMetadata=useMemo(()=>extended?.outputs.filter(output=>output.outputId===selectedPlot&&
  (!isIead||(output.status==='AVAILABLE'&&prefs.ieadSelection.includes(output.ref.runVersionId))))??[],
 [extended,selectedPlot,isIead,prefs.ieadSelection]);
 const storedOutputs = new Map(extended?.outputs.filter(output=>output.outputId===selectedPlot)
  .map(output=>[output.ref.runVersionId,output]));
 const loadedOutputs = new Map(outputs.filter(output=>output.metadata.outputId===selectedPlot)
  .map(output=>[output.metadata.ref.runVersionId,output]));
 const missingByReason = new Map<string,typeof result.runs>();
 const legendRuns = selectedPlot ? result.runs.filter(run=>{
  const loaded=loadedOutputs.get(run.ref.runVersionId);
  const metadata=loaded?.metadata??storedOutputs.get(run.ref.runVersionId);
  if(metadata?.status==='AVAILABLE' && (!loaded || loaded.display))return true;
  const reason=metadata?.reason??outputUnavailable;
  const missing=missingByReason.get(reason)??[];
  missing.push(run);
  missingByReason.set(reason,missing);
  return false;
 }) : result.runs;
 const visible = new Set(legendRuns.filter(run=>!prefs.hidden.includes(run.key)).map(run=>run.key));
 useEffect(()=>{
  if(!selectedPlot||prefs.collapsed||!extended||!activated)return;
  const c=new AbortController();setError('');
  if(!isIead)setOutputs([]);
  if(isIead&&!requestedMetadata.length){lastIeadOutputs.current.clear();setOutputs([]);setLoading(false);return;}
  setLoading(true);
  const outputCache=isIead?ieadCache:cache;
  const batchSize=isIead?2:25;
  async function load(){const loaded:RunOutput[]=[];const missing:OutputMetadata[]=[];
   for(const m of requestedMetadata){
    const key=sourceKey(m),cached=(isIead?lastIeadOutputs.current.get(key):undefined)??outputCache.get(key);
    if(m.status!=='AVAILABLE')loaded.push({metadata:m,features:{},display:null});else if(cached)loaded.push(cached);else missing.push(m);
   }
   for(let i=0;i<missing.length;i+=batchSize){const batch=missing.slice(i,i+batchSize),fresh=batch.filter(m=>!inFlight.has(sourceKey(m)));
    if(fresh.length){
     // Shared reads survive a subscriber unmount; only live subscribers may update their UI.
     const response=fetchRunOutputs(fresh.map(m=>m.ref),[selectedPlot!]);
     for(const expected of fresh){const key=sourceKey(expected);const promise=response.then(data=>{
      const actual=data.outputs.find(o=>o.metadata.ref.runVersionId===expected.ref.runVersionId&&
       o.metadata.ref.runId===expected.ref.runId&&o.metadata.outputId===expected.outputId);
      if(isIead&&actual?.metadata.status==='UNAVAILABLE')return actual;
      const matches=actual&&sameOutputSource(expected,actual.metadata);
      const invalidGrid=isIead&&matches&&(actual.display?.kind!=='grid'||!actual.display.rows.length);
      const output:RunOutput=matches&&!invalidGrid?actual:{metadata:{...expected,status:'UNAVAILABLE',
       reason:invalidGrid?'SOURCE_INVALID':'SOURCE_MISMATCH'},features:{},display:null};
      if(output.metadata.status==='AVAILABLE'&&output.display){outputCache.set(key,output);while(outputCache.size>(isIead?8:256))outputCache.delete(outputCache.keys().next().value!);}return output;
     }).finally(()=>inFlight.delete(key));inFlight.set(key,promise);}
    }
    const promises=batch.map(m=>inFlight.get(sourceKey(m))??Promise.resolve(outputCache.get(sourceKey(m))!));
    if(isIead){
     const responses=await Promise.allSettled(promises);
     if(c.signal.aborted)return;
     for(const response of responses){
      if(response.status==='fulfilled')loaded.push(response.value);
      else setError(response.reason instanceof Error?response.reason.message:'그래프 조회 실패');
     }
    }else loaded.push(...await Promise.all(promises));
    if(c.signal.aborted)return;
   }
   if(!c.signal.aborted){
    if(isIead)lastIeadOutputs.current=new Map(loaded.filter(output=>output.metadata.status==='AVAILABLE').map(output=>[sourceKey(output.metadata),output]));
    setOutputs(loaded);
   }
  }
  void load().catch(e=>{if(!c.signal.aborted)setError(e instanceof Error?e.message:'그래프 조회 실패');}).finally(()=>{if(!c.signal.aborted)setLoading(false);});return()=>c.abort();
 },[selectedPlot,prefs.collapsed,extended,activated,isIead,requestedMetadata]);
 return <>
  {hasIead&&<IeadSummary runs={result.runs} labels={labels} metadata={ieadMetadata} loaded={isIead?loadedOutputs:new Map()}
   selection={prefs.ieadSelection} renderActions={renderIeadRunActions} onToggle={version=>{
    setActivated(true);
    setPrefs(p=>({...p,active:'plot:iead',collapsed:false,ieadSelection:p.ieadSelection.includes(version)
     ?p.ieadSelection.filter(id=>id!==version):[...p.ieadSelection,version]}));
   }}/>}
  <section ref={root} className={compact?"comparison-charts comparison-charts--compact":"comparison-charts"} aria-label="비교 그래프">
  <div className="comparison-chart-heading">
   <strong>비교 그래프</strong>
   <button type="button" className="button button--ghost button--small" aria-expanded={!prefs.collapsed}
    onClick={()=>setPrefs(p=>({...p,collapsed:!p.collapsed}))}>{prefs.collapsed?'그래프 펼치기':'그래프 접기'}</button>
  </div>
  {!prefs.collapsed&&<>
   <div className="comparison-tabs" role="tablist" aria-label="비교 지표">
    {tabs.map(tab=><button key={tab} type="button" role="tab" aria-selected={prefs.active===tab}
     onClick={()=>setPrefs(p=>({...p,active:tab}))}>
     {tab.startsWith('plot:')?plotNames[tab.slice(5) as PlotId]:metricNames[tab.slice(7)]??tab.slice(7)}
    </button>)}
   </div>
   {selectedPlot&&missingByReason.size>0&&<PlotAvailability key={selectedPlot} plot={selectedPlot}
    total={result.runs.length} available={legendRuns.length} missingByReason={missingByReason}/>}
   {!isIead&&legendRuns.length>0&&<div className="comparison-legend">
    <button type="button" onClick={()=>setPrefs(p=>({...p,hidden:[]}))}>전체 표시</button>
    <button type="button" onClick={()=>setPrefs(p=>({...p,hidden:result.runs.map(r=>r.key)}))}>전체 숨기기</button>
    {legendRuns.map((run,i)=><button type="button" key={run.key} aria-pressed={visible.has(run.key)}
     title={run.ref.runId} aria-label={`${run.key} ${run.ref.runId}`}
     onClick={()=>setPrefs(p=>({...p,hidden:p.hidden.includes(run.key)
      ? p.hidden.filter(key=>key!==run.key) : [...p.hidden,run.key]}))}>
     <i className="comparison-color" style={{background:colors.get(run.ref.runId)??fixedRunColors[i%5]}}/>
     {run.key}
     {!compact&&<span>{run.ref.runId}
      {result.runs.filter(other=>other.ref.runId===run.ref.runId).length>1?` · ${run.ref.runVersionId.slice(0,8)}`:''}
     </span>}
    </button>)}
   </div>}
   {loading&&selectedPlot&&<p role="status">원본 그래프를 불러오고 있습니다.</p>}
   {error&&selectedPlot&&<p role="alert">{error}</p>}
   {isIead?(!requestedMetadata.length
    ? legendRuns.length>0&&<p className="comparison-empty">위 IEAD 표에서 표시할 실험을 선택해 주세요.</p>
    : <IeadHeatmaps outputs={result.runs.flatMap(run=>{
     const version=run.ref.runVersionId,output=loadedOutputs.get(version);
     return output&&prefs.ieadSelection.includes(version)?[output]:[];
    })} labels={labels} compact={compact}/>) : legendRuns.length>0&&(!visible.size
    ? <p className="comparison-empty">표시 중인 실험이 없습니다. 위에서 실험을 선택해 주세요.</p>
    : selectedPlot
     ? <SourceCharts outputs={legendRuns.filter(run=>visible.has(run.key)).flatMap(run=>{
      const output=loadedOutputs.get(run.ref.runVersionId);
      return output?[output]:[];
     })} colors={colors} compact={compact}/>
     : <ScalarBars result={result} metric={prefs.active.slice(7) as ComparisonField} visible={visible} colors={colors} compact={compact}/>)}
  </>}
 </section></>;
}
