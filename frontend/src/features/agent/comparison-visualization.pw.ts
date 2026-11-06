import {expect,test,type Locator} from '@playwright/test';
import type {AgentSubmission,ComparisonResultV3,RunOutput,TurnSnapshot,WorkspaceView} from 'agent';
import wire from '../../../../agent/tests/support/answer-v3-wire.json' with {type:'json'};
import v2 from '../../../../agent/tests/support/v2/contracts.json' with {type:'json'};
import {syntheticRun} from '../../test/runs';
import {emptyWorkspace,initialTurnUi} from './useConversation';
async function expectChartLabelsInside(svg:Locator){
 const labels=await svg.evaluate(node=>{
  const bounds=node.getBoundingClientRect();return [...node.querySelectorAll('text')].map(text=>{
   const box=text.getBoundingClientRect();return {text:text.textContent,left:box.left-bounds.left,right:box.right-bounds.left,top:box.top-bounds.top,bottom:box.bottom-bounds.top,width:bounds.width,height:bounds.height};
  });
 });
 for(const label of labels){
  expect(label.left,label.text??'').toBeGreaterThanOrEqual(-1);expect(label.right,label.text??'').toBeLessThanOrEqual(label.width+1);
  expect(label.top,label.text??'').toBeGreaterThanOrEqual(-1);expect(label.bottom,label.text??'').toBeLessThanOrEqual(label.height+1);
 }
 for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++){
  const a=labels[i],b=labels[j];expect(a.left<b.right-.5&&b.left<a.right-.5&&a.top<b.bottom-.5&&b.top<a.bottom-.5,`${a.text} / ${b.text}`).toBe(false);
 }
}
const layouts=[390,800,1008,1440].flatMap(width=>(['v1','v2'] as const).map(version=>({width,version})));
for(const {width,version} of layouts)test(`${version} comparison charts and independent tagged message at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:1000});const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const result=structuredClone(wire.comparison.result) as ComparisonResultV3;
 const runCount=width===1440?12:5;
 const first=result.runs[0];result.runs=Array.from({length:runCount},(_,i)=>({...structuredClone(first),key:`R${i+1}`,ref:{runId:`SYNTHETIC-${i+1}-P08-S200-B0400`,runVersionId:`00000000-0000-0000-0000-${String(i+1).padStart(12,'0')}`}}));
 result.usedRunRefs=result.runs.map(r=>r.ref);result.plotIds=['current','potential','iead','density'];result.metricIds.push('current.minimum','residual.final');
 const outputs:RunOutput[]=result.runs.flatMap((r,i)=>{
  const current=structuredClone(wire.outputs[0]) as RunOutput;current.metadata={...current.metadata,ref:r.ref,sourceIntegrity:`artificial-${i}`};
  const factor=1e7*(i+1);current.display!.samples.forEach(p=>p.y*=factor);Object.values(current.metadata.extrema).forEach(e=>e.value*=factor);
  for(const metric of ['current.maximum','current.halfPeakToPeak'] as const)r.metrics[metric]!.value!*=factor;
  r.metrics['current.minimum']={value:-2*factor,unit:'statampere/cm²',status:'AVAILABLE',reason:null,sourceValue:null};r.metrics['residual.final']={value:(i+1)*1e-9,unit:'relative residual',status:'AVAILABLE',reason:null,sourceValue:null};
  const potential:RunOutput={metadata:{...current.metadata,outputId:'potential',valueUnit:'V',sourceCount:3,extrema:{maximum:{value:-7.44,x:0,y:null,count:2},minimum:{value:-987.65-i,x:.5,y:null,count:1}}},features:{},display:{kind:'line',samples:[{x:0,y:-7.44},{x:.5,y:-987.65-i},{x:1,y:-7.44}],rows:[]}};
  const coordinates=[100+i*10,200+i*10],multiplier=i+1;
  const iead:RunOutput={metadata:{...current.metadata,outputId:'iead',xUnit:'°',yUnit:'eV',valueUnit:'원본 단위 미지정',
   extrema:{maximum:{value:4*multiplier,x:10+i,y:coordinates[1],count:1}}},features:{},display:{kind:'grid',samples:[],rows:[
    {x:-10+i,coordinates,values:[1*multiplier,2*multiplier]},{x:10+i,coordinates,values:[3*multiplier,4*multiplier]},
   ]}};
  const density:RunOutput={metadata:{...current.metadata,outputId:'density',xUnit:'RF cycle',yUnit:'cm',valueUnit:'원본 단위 미지정',
   extrema:{maximum:{value:4,x:1,y:.5,count:1}}},features:{},display:{kind:'grid',samples:[],rows:[
    {x:0,coordinates:[0,1],values:[1,2]},{x:1,coordinates:[0,.5],values:[3,4]},
   ]}};
  return [current,potential,iead,density];
 });
 result.outputs=outputs.map(o=>o.metadata);
 const answerSnapshot=version==='v2'?{...v2.general_answer,intent:'COMPOSITE_ANSWER',draft:null,stepResults:[{
  executionId:'compare',stepId:'compare',status:'verified',outputs:{toolResult:result},runRefs:result.usedRunRefs,groupId:null,reason:null,
 }]}:{...wire.comparison,result,usedRunRefs:result.usedRunRefs};
 const turn={id:'artificial-compare',askedAt:'2026-10-09T00:00:00Z',question:'인공 파형 비교',intent:'RUN_COMPARISON',context:null,answerRunRefs:result.usedRunRefs,answerSnapshot,ui:structuredClone(initialTurnUi)} as unknown as TurnSnapshot;
 let workspace:WorkspaceView={...structuredClone(emptyWorkspace),conversation:{version:1,activeRun:null,turns:[turn],agentGraphVersion:version},candidateReference:{kind:'후보 집합',runs:result.usedRunRefs,...(version==='v2'?{catalogRefs:result.usedRunRefs}:{})},agentMessages:[{requestId:turn.id,clientMessageId:'saved-key',question:turn.question,submittedRunRefs:result.usedRunRefs,createdAt:turn.askedAt,status:'COMPLETED',turnId:turn.id}]};
 const posted:AgentSubmission[]=[];const detailVersions:string[]=[];const ieadRequests:string[][]=[];let release:(()=>void)|undefined;let graphCalls=0;
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;if(!path.startsWith('/api/'))return route.continue();
  if(path==='/api/decisions')return route.fulfill({json:[]});
  if(path==='/api/run-versions/outputs'){
   graphCalls++;const body=req.postDataJSON();const versions=body.runRefs.map((ref:{runVersionId:string})=>ref.runVersionId);
   if(body.plotIds.includes('iead'))ieadRequests.push(versions);
   return route.fulfill({json:{outputs:outputs.filter(o=>body.plotIds.includes(o.metadata.outputId)&&versions.includes(o.metadata.ref.runVersionId))}});
  }
  if(path.startsWith('/api/run-versions/')){
   const version=path.split('/').at(-1)!;detailVersions.push(version);const run=result.runs.find(r=>r.ref.runVersionId===version)!;
   return route.fulfill({json:{...syntheticRun(),...run.ref}});
  }
  if(path==='/api/agent/requests'){
   const body=req.postDataJSON();posted.push(body);await new Promise<void>(done=>release=done);
   const request={requestId:'new-request',requestRevision:0,status:'NEEDS_INPUT',stage:'wait_input',graphVersion:version,question:body.text,pendingInput:{id:'pick',message:'검증용 추가 입력'},error:null,partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]};
   workspace={...workspace,activeAgentRequest:request as WorkspaceView['activeAgentRequest'],agentMessages:[...workspace.agentMessages!,{requestId:request.requestId,clientMessageId:req.headers()['idempotency-key'],createdAt:'2026-10-09T00:01:00Z',question:body.text,submittedRunRefs:body.attachedRunRefs,status:'NEEDS_INPUT',turnId:null}]};return route.fulfill({json:request});
  }
  return route.fulfill({json:workspace});
 });
 await page.goto('/');const card=page.locator('[data-turn-id="artificial-compare"]');
 const table=card.getByRole('table',{name:'선택한 실험 수치',exact:true});await expect(table).toBeVisible();
 for(const label of ['계산 정의·원본','계산 근거','가능한 해석','설명의 한계','공정 조건·버전'])await expect(card.getByText(label,{exact:true})).toHaveCount(0);
 await expect(table.getByRole('columnheader',{name:'번호'})).toBeVisible();await expect(table.getByRole('columnheader',{name:'상세'})).toBeVisible();
 expect(await table.locator('tbody th').evaluateAll(cells=>cells.every(cell=>getComputedStyle(cell).whiteSpace==='nowrap'))).toBe(true);
 expect(await table.locator('tbody tr').evaluateAll(rows=>rows.every(row=>row.getBoundingClientRect().height<=46))).toBe(true);
 const numbers=await card.locator('.comparison-numbers').boundingBox(),graph=await card.locator('.comparison-charts').boundingBox();
 expect(graph!.y).toBeGreaterThanOrEqual(numbers!.y+numbers!.height);
 expect(Math.abs(graph!.width-numbers!.width)).toBeLessThanOrEqual(1);
 const selected=result.runs[1];await table.getByRole('button',{name:`${selected.key} ${selected.ref.runId} 실험 상세 보기`}).click();
 const detail=page.getByRole('dialog');await expect(detail.getByRole('heading',{name:selected.ref.runId})).toBeVisible();
 expect(new Set(detailVersions)).toEqual(new Set([selected.ref.runVersionId]));expect(await detail.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
 await page.keyboard.press('Escape');await expect(detail).toBeHidden();
 await table.locator('..').evaluate(node=>node.scrollLeft=0);
 await card.getByRole('region',{name:'비교 그래프'}).scrollIntoViewIfNeeded();
 await expect(card.locator('path[data-run-id]')).toHaveCount(runCount);
 const chart=card.getByRole('region',{name:'비교 그래프'});
 const waveformHeight=(await chart.getByRole('img').boundingBox())!.height;
 await expectChartLabelsInside(chart.getByRole('img'));await chart.screenshot({path:info.outputPath(`synthetic-source-labels-${width}.png`)});
 await chart.getByRole('button',{name:`R1 ${result.runs[0].ref.runId}`,exact:true}).click();await expect(card.locator('path[data-run-id]')).toHaveCount(runCount-1);
 await chart.getByRole('button',{name:'전체 숨기기'}).click();await expect(chart.getByText(/표시 중인 실험이 없습니다/)).toBeVisible();
 await chart.getByRole('button',{name:'전체 표시'}).click();
 for(const name of ['RF 전류 밀도 최댓값','RF 전류 밀도 최솟값','마지막 잔차']){
  await chart.getByRole('tab',{name,exact:true}).click();await expect(chart.locator('rect[data-run-key]')).toHaveCount(runCount);await expectChartLabelsInside(chart.getByRole('img'));
  if(version==='v2')expect(waveformHeight).toBeCloseTo((await chart.getByRole('img').boundingBox())!.height,0);
  if(name==='마지막 잔차')await expect(chart.getByRole('img').getByText('1.00e-9',{exact:true})).toBeVisible();
  if(name==='RF 전류 밀도 최댓값')await chart.screenshot({path:info.outputPath(`synthetic-bar-labels-${width}.png`)});
 }
 await chart.getByRole('tab',{name:'전극 전위',exact:true}).click();await expect(chart.locator('path[data-run-id]')).toHaveCount(runCount);await expectChartLabelsInside(chart.getByRole('img'));
 await chart.getByRole('tab',{name:'쉬스 이온 밀도',exact:true}).click();await expect(chart.getByRole('img')).toHaveCount(runCount);
 const densityCanvas=chart.locator('canvas').first();
 if(version==='v2')expect((await chart.getByRole('img').first().boundingBox())!.height).toBeCloseTo(waveformHeight,0);
 const densityOpacity=await densityCanvas.evaluate(node=>{
  const canvas=node as HTMLCanvasElement,context=canvas.getContext('2d')!,top=Math.floor(canvas.height*.25);
  return [.2,.8].map(position=>context.getImageData(Math.floor(canvas.width*position),top,1,1).data[3]);
 });
 expect(densityOpacity).toEqual([255,0]);
 await chart.getByRole('tab',{name:'에너지·입사각 분포',exact:true}).click();await expect(chart.getByRole('img')).toHaveCount(0);expect(graphCalls).toBe(3);
 const ieadSummary=card.getByRole('table',{name:'IEAD 실험별 요약'});
 await expect(ieadSummary.getByRole('row')).toHaveCount(runCount+1);
 for(const run of result.runs.slice(0,2)){
  await ieadSummary.getByRole('checkbox',{name:`${run.key} ${run.ref.runId} 히트맵`}).check();
  await expect(chart.getByRole('img',{name:new RegExp(`${run.key} ${run.ref.runId}`)})).toBeAttached();
 }
 await expect(chart.getByRole('img')).toHaveCount(2);
 expect(ieadRequests).toEqual(result.runs.slice(0,2).map(run=>[run.ref.runVersionId]));
 const heatmaps=chart.getByRole('region',{name:'선택한 IEAD 히트맵'});
 if(version==='v2')expect((await heatmaps.getByRole('img').first().boundingBox())!.height).toBeCloseTo(waveformHeight,0);
 const figureBounds=await heatmaps.locator('figure').evaluateAll(figures=>figures.map(figure=>figure.getBoundingClientRect().toJSON()));
 expect(figureBounds[0].y).toBe(figureBounds[1].y);expect(figureBounds[1].x).toBeGreaterThan(figureBounds[0].right);
 if(width>=800)expect(await heatmaps.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
 else expect(await heatmaps.evaluate(node=>{
  node.scrollLeft=node.scrollWidth;
  return node.lastElementChild!.getBoundingClientRect().right<=node.getBoundingClientRect().right+1;
 })).toBe(true);
 await heatmaps.evaluate(node=>{node.scrollLeft=0;});
 const sampledColors=await heatmaps.locator('canvas').evaluateAll(canvases=>canvases.map(node=>{
  const canvas=node as HTMLCanvasElement;
  return Array.from(canvas.getContext('2d')!.getImageData(Math.floor(canvas.width*.85),Math.floor(canvas.height*.2),1,1).data);
 }));
 expect(sampledColors).toEqual([[145,160,204,255],[30,57,143,255]]);
 for(const svg of await chart.getByRole('img').all())await expectChartLabelsInside(svg);
 await heatmaps.evaluate(node=>node.scrollIntoView({block:'center'}));
 await heatmaps.screenshot({path:info.outputPath(`synthetic-iead-heatmaps-${width}.png`)});
 await chart.getByRole('button',{name:'그래프 접기'}).click();await page.reload();await expect(chart.getByRole('button',{name:'그래프 펼치기'})).toBeVisible();
 await chart.getByRole('button',{name:'그래프 펼치기'}).click();await expect(chart.getByRole('img')).toHaveCount(2);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);expect(await card.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
 await card.screenshot({path:info.outputPath(`synthetic-comparison-${width}.png`)});
 await page.locator('#agent-query').fill('이 실험들 다시 비교해줘');await page.locator('#agent-query-form button[type=submit]').click();
 await expect.poll(()=>posted.length).toBe(1);const user=page.locator('.agent-user-message').filter({hasText:'이 실험들 다시 비교해줘'});
 await expect(user).toHaveCount(1);await expect(user.locator('.run-context-chip')).toHaveCount(runCount);
 await expect(user.locator('.run-context-chip strong').first()).toHaveText(result.runs[0].ref.runId);
 await page.locator('#agent-query-form').evaluate(form=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(posted).toHaveLength(1);release!();await expect(page.getByRole('heading',{name:'추가 정보가 필요합니다'})).toBeVisible();
 await expect(page.getByText('이 실험들 다시 비교해줘',{exact:true})).toHaveCount(1);expect(errors).toEqual([]);
});
