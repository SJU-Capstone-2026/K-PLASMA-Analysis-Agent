import {useLayoutEffect,useRef} from 'react';
import type {RunOutput} from 'agent';

type Range=[number,number];
type Grid=NonNullable<RunOutput['display']>['rows'];

// Sample the original cell under each canvas pixel, with blank pixels outside that Run's axes.
function pixelIndices(axis:number[],range:Range,size:number,reversed=false){
 const indices=new Int32Array(size).fill(-1);
 if(!axis.length)return indices;
 const step=(range[1]-range[0])/size;
 const margin=axis.length===1?step/2:0;
 let index=0;
 for(let pixel=0;pixel<size;pixel++){
  const coordinate=range[0]+(pixel+.5)*step;
  if(coordinate<axis[0]-margin||coordinate>axis[axis.length-1]+margin)continue;
  while(index+1<axis.length&&coordinate>axis[index]/2+axis[index+1]/2)index++;
  indices[reversed?size-1-pixel:pixel]=index;
 }
 return indices;
}

export const gridColors=['#e6edfa','#1e398f'] as const;
const colorStops=gridColors.map(color=>[1,3,5].map(index=>parseInt(color.slice(index,index+2),16)));
const palette=Array.from({length:256},(_,level)=>colorStops[0].map((light,channel)=>
 Math.round(light+(colorStops[1][channel]-light)*level/255)));

export function ComparisonGridCanvas({rows,width,height,xRange,yRange,valueRange,metadata,sharedY=false}:{
 rows:Grid;width:number;height:number;xRange:Range;yRange:Range;valueRange:Range;metadata:RunOutput['metadata'];sharedY?:boolean;
}){
 const canvas=useRef<HTMLCanvasElement>(null);
 const cells=useRef<{xs:Int32Array;sharedYs:Int32Array|null}|null>(null);
 const pixelWidth=width*2,pixelHeight=height*2;
 useLayoutEffect(()=>{
  const context=canvas.current?.getContext('2d');
  if(!context)return;
  const xs=pixelIndices(rows.map(row=>row.x),xRange,pixelWidth);
  const sharedYs=sharedY?pixelIndices(rows[0].coordinates,yRange,pixelHeight,true):null;
  cells.current={xs,sharedYs};
  const image=context.createImageData(pixelWidth,pixelHeight);
  const {data}=image;
  const [min,max]=valueRange;
  let previousRow=-1,ys=sharedYs;
  for(let x=0;x<pixelWidth;x++){
   const rowIndex=xs[x];
   if(rowIndex<0)continue;
   const row=rows[rowIndex];
   if(!sharedYs&&rowIndex!==previousRow)ys=pixelIndices(row.coordinates,yRange,pixelHeight,true);
   previousRow=rowIndex;
   for(let y=0;y<pixelHeight;y++){
    const index=ys![y];
    if(index<0)continue;
    const value=row.values[index];
    const level=min===max?128:Math.round(255*((value-min)/(max-min)));
    const [red,green,blue]=palette[level];
    const offset=(y*pixelWidth+x)*4;
    data[offset]=red;
    data[offset+1]=green;
    data[offset+2]=blue;
    data[offset+3]=255;
   }
  }
  context.putImageData(image,0,0);
 },[rows,pixelWidth,pixelHeight,xRange,yRange,valueRange,sharedY]);
 return <canvas ref={canvas} width={pixelWidth} height={pixelHeight} onPointerMove={event=>{
  const node=event.currentTarget,bounds=node.getBoundingClientRect();
  const x=Math.floor((event.clientX-bounds.left)/bounds.width*pixelWidth);
  const y=Math.floor((event.clientY-bounds.top)/bounds.height*pixelHeight);
  const row=rows[cells.current?.xs[x]??-1];
  const yIndex=row?(cells.current?.sharedYs??pixelIndices(row.coordinates,yRange,pixelHeight,true))[y]:-1;
  node.title=row&&yIndex>=0?`${row.x} ${metadata.xUnit}, ${row.coordinates[yIndex]} ${metadata.yUnit}: ${row.values[yIndex]} ${metadata.valueUnit}`:'';
 }}/>;
}
