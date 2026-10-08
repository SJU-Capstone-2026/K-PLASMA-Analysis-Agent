import {useEffect,useMemo,useRef,useState} from 'react';
import type {ComparisonField,ComparisonResultV2,ComparisonResultV3,OutputMetadata,PlotId,RunOutput} from 'agent';
import {useRunColors,fixedRunColors} from '../../components/RunColors';
import {fetchRunOutputs} from '../../api/runs';
import {metricNames,numberText} from './agent-contract';
export const plotNames:Record<PlotId,string>={ied:'이온 에너지 분포',iad:'이온 입사각 분포',iead:'에너지·입사각 분포',current:'RF 전류 밀도',potential:'전극 전위',density:'쉬스 이온 밀도',residual:'수렴 잔차'};
const cache=new Map<string,RunOutput>();
const inFlight=new Map<string,Promise<RunOutput>>();
const sourceKey=(m:OutputMetadata)=>JSON.stringify([m.ref.runId,m.ref.runVersionId,m.outputId,m.sourceIntegrity,m.xUnit,m.yUnit,m.valueUnit]);
export function sameOutputSource(a:OutputMetadata,b:OutputMetadata){return sourceKey(a)===sourceKey(b);}
export const extent=(values:Iterable<number>):[number,number]=>{let min=Infinity,max=-Infinity;for(const value of values){min=Math.min(min,value);max=Math.max(max,value);}if(!Number.isFinite(min)||!Number.isFinite(max))return [0,1];return min===max?[min-1,max+1]:[min,max];};
const scale=(value:number,[min,max]:[number,number],start:number,end:number)=>start+(value-min)/(max-min)*(end-start);
const cellBounds=(coordinates:number[],index:number,range:[number,number],start:number,end:number):[number,number]=>{
 const center=coordinates[index],lower=index? (coordinates[index-1]+center)/2:range[0],upper=index<coordinates.length-1?(coordinates[index+1]+center)/2:range[1];
 const a=scale(lower,range,start,end),b=scale(upper,range,start,end);return [Math.min(a,b),Math.abs(b-a)];
};
const metadataReasons:Record<string,string>={BIAS_OFF:'Bias-off 출력 없음',SOURCE_MISSING:'원본 파일 없음',SOURCE_INVALID:'원본 형식 확인 필요',VERSION_UNAVAILABLE:'실험 버전 없음',SOURCE_INTEGRITY_MISMATCH:'원본 무결성 불일치',SOURCE_MISMATCH:'답변에 저장된 원본·단위와 현재 그래프가 다릅니다.'};
function Frame({children,xLabel,yLabel,xRange,yRange,categorical=false,width=650}:{children:React.ReactNode;xLabel:string;yLabel:string;xRange:[number,number];yRange:[number,number];categorical?:boolean;width?:number}){
 return <><path d={`M60 24V270H${width-30}`} fill="none" stroke="#b7c3d6"/>{[0,.5,1].map(t=><g key={t}><line x1="60" y1={270-t*246} x2={width-30} y2={270-t*246} stroke="#e8edf5"/><text x="52" y={274-t*246} textAnchor="end">{numberText(yRange[0]+t*(yRange[1]-yRange[0]))}</text></g>)}{!categorical&&<><text x="60" y="290">{numberText(xRange[0])}</text><text x={width-30} y="290" textAnchor="end">{numberText(xRange[1])}</text></>}<text x={(width+30)/2} y="313" textAnchor="middle">{xLabel}</text><text transform="translate(15,150) rotate(-90)" textAnchor="middle">{yLabel}</text>{children}</>;
}
export function ScalarBars({result,metric,visible,colors}:{result:ComparisonResultV2;metric:ComparisonField;visible:Set<string>;colors:ReadonlyMap<string,string>}){
 const runs=result.runs.filter(r=>visible.has(r.key));const valid=runs.filter(r=>r.metrics[metric]?.status==='AVAILABLE');
 if(!valid.length)return <p className="comparison-empty">표시할 수 있는 수치가 없습니다. 누락값은 0으로 그리지 않습니다.</p>;
 const values=valid.map(r=>r.metrics[metric]!.value!);let range:[number,number]=[Math.min(0,...values),Math.max(0,...values)];if(range[0]===range[1])range=[0,1];
 const chartWidth=Math.max(650,runs.length*55),zero=scale(0,range,270,24),slot=(chartWidth-90)/runs.length,unit=valid[0].metrics[metric]!.unit;
 return <figure className="comparison-figure"><figcaption>{metricNames[metric]} <span>{unit}</span></figcaption><div className="comparison-bar-scroll"><svg style={{minWidth:runs.length>8?chartWidth:undefined}} viewBox={`0 0 ${chartWidth} 330`} role="img" aria-label={`${metricNames[metric]} 실험별 막대 그래프`}><Frame width={chartWidth} categorical xRange={[1,runs.length]} yRange={range} xLabel="선택한 실험" yLabel={unit}>{runs.map((r,i)=>{const d=r.metrics[metric]!,x=60+(i+.5)*slot,y=d.status==='AVAILABLE'?scale(d.value!,range,270,24):zero;return <g key={r.key}><title>{r.ref.runId}: {d.status==='AVAILABLE'?`${numberText(d.value)} ${d.unit}`:`비가용 ${d.reason}`}</title>{d.status==='AVAILABLE'?<rect data-run-key={r.key} x={x-slot*.3} y={Math.min(y,zero)} width={slot*.6} height={Math.max(Math.abs(y-zero),1)} rx="3" fill={colors.get(r.ref.runId)??fixedRunColors[i%5]}/>:<text x={x} y="250" textAnchor="middle">—</text>}<text x={x} y={d.value!=null&&d.value<0?y+16:y-8} textAnchor="middle">{d.status==='AVAILABLE'?numberText(d.value):''}</text><text x={x} y="290" textAnchor="middle">{r.key}</text></g>;})}</Frame></svg></div></figure>;
}
function SourceCharts({outputs,colors}:{outputs:RunOutput[];colors:ReadonlyMap<string,string>}){
 const available=outputs.filter(o=>o.metadata.status==='AVAILABLE'&&o.display);const line=available.filter(o=>o.display?.kind==='line');
 const gridRows=available.flatMap(o=>o.display!.rows);const gridX=gridRows.map(r=>r.x),gridY=gridRows.flatMap(r=>r.coordinates);
 const xs=line.flatMap(o=>o.display!.samples.map(p=>p.x)),ys=line.flatMap(o=>o.display!.samples.map(p=>p.y));
 const values=available.flatMap(o=>o.display!.rows.flatMap(row=>row.values)),valueRange=extent(values);
 const lineX=extent(xs),lineY=extent(ys);
 return <>{outputs.filter(o=>o.metadata.status!=='AVAILABLE'||!o.display).map(o=><p className="alert" key={o.metadata.ref.runVersionId}>{o.metadata.ref.runId} · {metadataReasons[o.metadata.reason??'']??o.metadata.reason??'그래프를 표시할 수 없습니다.'}</p>)}{line.length>0&&<figure className="comparison-figure"><figcaption>{plotNames[line[0].metadata.outputId]} <span>{line[0].metadata.valueUnit}</span></figcaption><svg viewBox="0 0 650 330" role="img" aria-label={`${plotNames[line[0].metadata.outputId]} 원본 파형 비교`}><Frame xRange={lineX} yRange={lineY} xLabel={line[0].metadata.xUnit} yLabel={line[0].metadata.valueUnit}>{line.map((o,i)=>{const m=o.metadata,color=colors.get(m.ref.runId)??fixedRunColors[i%5];return <g key={m.ref.runVersionId}><path data-run-id={m.ref.runId} fill="none" stroke={color} strokeWidth="2.5" strokeDasharray={line.filter(other=>other.metadata.ref.runId===m.ref.runId).findIndex(other=>other===o)%2?"7 4":undefined} d={o.display!.samples.map((p,index)=>`${index?'L':'M'}${scale(p.x,lineX,60,620)},${scale(p.y,lineY,270,24)}`).join(' ')}><title>{m.ref.runId} · 원본 {m.sourceCount}점</title></path>{Object.entries(m.extrema).map(([name,e])=><circle key={name} cx={scale(e.x,lineX,60,620)} cy={scale(e.value,lineY,270,24)} r="4" fill={color}><title>{name}: {e.value} {m.valueUnit} · {e.x} {m.xUnit} · 공동 극값 {e.count}개</title></circle>)}</g>;})}</Frame></svg><small>공통 축 · 원본 지점만 표시 · 피크·진폭은 전체 원본에서 계산</small></figure>}{available.filter(o=>o.display!.kind==='grid').map(o=>{
  const {metadata:m,display:d}=o;const rows=d!.rows;const xr=extent(gridX),yr=extent(gridY);
  return <figure className="comparison-figure" key={m.ref.runVersionId}><figcaption><i className="comparison-color" style={{background:colors.get(m.ref.runId)}}/>{m.ref.runId} <span>{plotNames[m.outputId]}</span></figcaption><svg viewBox="0 0 650 330" role="img" aria-label={`${m.ref.runId} ${plotNames[m.outputId]} 원본 격자`}><Frame xRange={xr} yRange={yr} xLabel={m.xUnit} yLabel={m.yUnit}>{rows.map((row,i)=>row.values.map((v,j)=>{const [x,width]=cellBounds(rows.map(r=>r.x),i,xr,60,620),[y,height]=cellBounds(row.coordinates,j,yr,270,24);return <rect key={`${i}:${j}`} x={x} y={y} width={Math.max(width,1)} height={Math.max(height,1)} fill={`hsl(222 65% ${94-60*(v-valueRange[0])/(valueRange[1]-valueRange[0])}%)`}><title>{row.x} {m.xUnit}, {row.coordinates[j]} {m.yUnit}: {v} {m.valueUnit}</title></rect>;}))}{m.extrema.maximum&&<circle cx={scale(m.extrema.maximum.x,xr,60,620)} cy={scale(m.extrema.maximum.y!,yr,270,24)} r="5" fill="none" stroke="#172b4d" strokeWidth="2"/>}</Frame></svg><small>공통 강도 범위 {numberText(valueRange[0])}–{numberText(valueRange[1])} · {m.valueUnit} · 원본 좌표 유지</small></figure>;
 })}</>;
}
export function ComparisonCharts({result,storageId}:{result:ComparisonResultV2|ComparisonResultV3;storageId?:string}){
 const root=useRef<HTMLElement>(null);const [activated,setActivated]=useState(()=>typeof IntersectionObserver==='undefined');
 useEffect(()=>{if(activated||!root.current)return;const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setActivated(true);observer.disconnect();}},{rootMargin:'300px'});observer.observe(root.current);return()=>observer.disconnect();},[activated]);
 const extended='plotIds' in result?result:undefined;const plots=extended?.plotIds??[];const tabs=[...plots.map(id=>`plot:${id}`),...result.metricIds.map(id=>`scalar:${id}`)];
 const prefKey=storageId?`kplasma.comparison-view.v1:${storageId}`:null;
 const [prefs,setPrefs]=useState(()=>{try{const p=JSON.parse(prefKey?localStorage.getItem(prefKey)??'null':'null');return {active:tabs.includes(p?.active)?p.active:tabs[0],hidden:Array.isArray(p?.hidden)?p.hidden as string[]:[],collapsed:!!p?.collapsed};}catch{return {active:tabs[0],hidden:[] as string[],collapsed:false};}});
 const ids=useMemo(()=>result.runs.map(r=>r.ref.runId),[result.runs]);const colors=useRunColors(ids);const visible=new Set(result.runs.filter(r=>!prefs.hidden.includes(r.key)).map(r=>r.key));
 const [outputs,setOutputs]=useState<RunOutput[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState('');
 useEffect(()=>{if(prefKey)try{localStorage.setItem(prefKey,JSON.stringify(prefs));}catch{/* Browser-only chart preferences. */}},[prefKey,prefs]);
 const selectedPlot=prefs.active?.startsWith('plot:')?prefs.active.slice(5) as PlotId:null;
 useEffect(()=>{
  if(!selectedPlot||prefs.collapsed||!extended||!activated)return;const c=new AbortController();setOutputs([]);setError('');setLoading(true);
  const metadata=extended.outputs.filter(m=>m.outputId===selectedPlot);
  async function load(){const loaded:RunOutput[]=[];const missing:OutputMetadata[]=[];
   for(const m of metadata){const cached=cache.get(sourceKey(m));if(m.status!=='AVAILABLE')loaded.push({metadata:m,features:{},display:null});else if(cached)loaded.push(cached);else missing.push(m);}
   for(let i=0;i<missing.length;i+=25){const batch=missing.slice(i,i+25),fresh=batch.filter(m=>!inFlight.has(sourceKey(m)));
    if(fresh.length){
     // Shared reads survive a subscriber unmount; only live subscribers may update their UI.
     const response=fetchRunOutputs(fresh.map(m=>m.ref),[selectedPlot!]);
     for(const expected of fresh){const key=sourceKey(expected);const promise=response.then(data=>{
      const actual=data.outputs.find(o=>o.metadata.ref.runVersionId===expected.ref.runVersionId&&o.metadata.outputId===expected.outputId);
      const output:RunOutput=actual&&sameOutputSource(expected,actual.metadata)?actual:{metadata:{...expected,status:'UNAVAILABLE',reason:'SOURCE_MISMATCH'},features:{},display:null};
      if(output.metadata.status==='AVAILABLE'&&output.display){cache.set(key,output);while(cache.size>256)cache.delete(cache.keys().next().value!);}return output;
     }).finally(()=>inFlight.delete(key));inFlight.set(key,promise);}
    }
    loaded.push(...await Promise.all(batch.map(m=>inFlight.get(sourceKey(m))??Promise.resolve(cache.get(sourceKey(m))!))));if(c.signal.aborted)return;
   }
   if(!c.signal.aborted)setOutputs(metadata.map(m=>loaded.find(o=>o.metadata.ref.runVersionId===m.ref.runVersionId)!));
  }
  void load().catch(e=>{if(!c.signal.aborted)setError(e instanceof Error?e.message:'그래프 조회 실패');}).finally(()=>{if(!c.signal.aborted)setLoading(false);});return()=>c.abort();
 },[selectedPlot,prefs.collapsed,extended,activated]);
 return <section ref={root} className="comparison-charts" aria-label="비교 그래프"><div className="comparison-chart-heading"><strong>비교 그래프</strong><button type="button" className="button button--ghost button--small" aria-expanded={!prefs.collapsed} onClick={()=>setPrefs(p=>({...p,collapsed:!p.collapsed}))}>{prefs.collapsed?'그래프 펼치기':'그래프 접기'}</button></div>{!prefs.collapsed&&<><div className="comparison-tabs" role="tablist" aria-label="비교 지표">{tabs.map(tab=><button key={tab} type="button" role="tab" aria-selected={prefs.active===tab} onClick={()=>setPrefs(p=>({...p,active:tab}))}>{tab.startsWith('plot:')?plotNames[tab.slice(5) as PlotId]:metricNames[tab.slice(7)]??tab.slice(7)}</button>)}</div><div className="comparison-legend"><button type="button" onClick={()=>setPrefs(p=>({...p,hidden:[]}))}>전체 표시</button><button type="button" onClick={()=>setPrefs(p=>({...p,hidden:result.runs.map(r=>r.key)}))}>전체 숨기기</button>{result.runs.map((r,i)=><button type="button" key={r.key} aria-pressed={visible.has(r.key)} title={r.ref.runId} aria-label={`${r.key} ${r.ref.runId}`} onClick={()=>setPrefs(p=>({...p,hidden:p.hidden.includes(r.key)?p.hidden.filter(k=>k!==r.key):[...p.hidden,r.key]}))}><i className="comparison-color" style={{background:colors.get(r.ref.runId)??fixedRunColors[i%5]}}/>{r.key}<span>{r.ref.runId}{result.runs.filter(other=>other.ref.runId===r.ref.runId).length>1?` · ${r.ref.runVersionId.slice(0,8)}`:''}</span></button>)}</div>{!visible.size?<p className="comparison-empty">표시 중인 실험이 없습니다. 위에서 실험을 선택해 주세요.</p>:selectedPlot?<>{loading&&<p role="status">원본 그래프를 불러오고 있습니다.</p>}{error&&<p role="alert">{error}</p>}<SourceCharts outputs={outputs.filter(o=>result.runs.some(r=>visible.has(r.key)&&r.ref.runVersionId===o.metadata.ref.runVersionId))} colors={colors}/></>:<ScalarBars result={result} metric={prefs.active.slice(7) as ComparisonField} visible={visible} colors={colors}/>}</>}</section>;
}
