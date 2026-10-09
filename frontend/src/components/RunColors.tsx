import {createContext,useCallback,useContext,useEffect,useLayoutEffect,useMemo,useRef,useState,type ReactNode} from 'react';

export const fixedRunColors=['#4168e8','#0a8e9b','#8a5bd7','#e0842a','#d25091'] as const;
export const runColorStorageKey='kplasma.agent-run-colors.v1';
type RunColors=ReadonlyMap<string,string>;
const emptyColors:RunColors=new Map();
const hex=(channels:number[])=>'#'+channels.map(value=>Math.round(value).toString(16).padStart(2,'0')).join('');
const rgb=(color:string)=>[1,3,5].map(offset=>parseInt(color.slice(offset,offset+2),16));

/** Pick the most distinct of a bounded set of random, saturated colors. */
function randomRunColor(used:string[]){
 const previous=used.map(rgb);let best='';let bestDistance=-1;
 for(let attempt=0;attempt<32;attempt++){
  const hue=Math.random()*6;const saturation=.6+Math.random()*.2;const value=.7+Math.random()*.15;
  const chroma=value*saturation;const x=chroma*(1-Math.abs(hue%2-1));const offset=value-chroma;
  const sector=[[chroma,x,0],[x,chroma,0],[0,chroma,x],[0,x,chroma],[x,0,chroma],[chroma,0,x]][Math.floor(hue)];
  const channels=sector.map(channel=>Math.round((channel+offset)*255));const color=hex(channels);
  if(used.includes(color))continue;
  const distance=Math.min(...previous.map(other=>channels.reduce((sum,channel,index)=>sum+(channel-other[index])**2,0)));
  if(distance>bestDistance){best=color;bestDistance=distance;}
 }
 if(best)return best;
 // A repeated random source must not reuse a color or cause an unbounded retry.
 let value=0x64748b;
 for(let attempt=0;attempt<=used.length;attempt++){
  const color='#'+value.toString(16).padStart(6,'0');if(!used.includes(color))return color;
  value=(value+1)%0x1000000;
 }
 return '#64748b';
}

export function assignRunColors(colors:RunColors,runIds:string[]):RunColors{
 let next:Map<string,string>|undefined;
 for(const runId of runIds){
  if((next??colors).has(runId))continue;
  next??=new Map(colors);
  next.set(runId,next.size<fixedRunColors.length?fixedRunColors[next.size]:randomRunColor([...next.values()]));
 }
 return next??colors;
}

function loadRunColors(scope:string):RunColors{
 try{
  const saved=JSON.parse(localStorage.getItem(runColorStorageKey)??'null');
  if(saved?.version!==1||saved.scope!==scope||!Array.isArray(saved.entries))return emptyColors;
  const entries:unknown[]=saved.entries;
  if(entries.some(entry=>!Array.isArray(entry)||entry.length!==2||typeof entry[0]!=='string'||typeof entry[1]!=='string'||!/^#[0-9a-f]{6}$/.test(entry[1])))return emptyColors;
  return new Map(entries as [string,string][]);
 }catch{return emptyColors;}
}

const RunColorContext=createContext<{colors:RunColors;register:(runIds:string[])=>void}|null>(null);

/** The scope is the current workspace/conversation epoch; no server snapshot is changed. */
export function RunColorsProvider({scope,enabled=true,children}:{scope:string;enabled?:boolean;children:ReactNode}){
 const [colors,setColors]=useState(()=>loadRunColors(scope));const latest=useRef(colors);
 const register=useCallback((runIds:string[])=>{
  if(!enabled)return;
  const next=assignRunColors(latest.current,runIds);
  if(next!==latest.current){latest.current=next;setColors(next);}
 },[enabled]);
 useEffect(()=>{
  if(!enabled)return;
  try{localStorage.setItem(runColorStorageKey,JSON.stringify({version:1,scope,entries:[...colors]}));}
  catch{/* Cosmetic preferences still work in memory when browser storage is unavailable. */}
 },[colors,enabled,scope]);
 const value=useMemo(()=>({colors,register}),[colors,register]);
 return <RunColorContext.Provider value={value}>{children}</RunColorContext.Provider>;
}

/** Tags and future chart consumers share the same Run ID → color association. */
export function useRunColors(runIds:string[]){
 const context=useContext(RunColorContext);
 useLayoutEffect(()=>{context?.register(runIds);},[context,runIds]);
 return context?.colors??emptyColors;
}
