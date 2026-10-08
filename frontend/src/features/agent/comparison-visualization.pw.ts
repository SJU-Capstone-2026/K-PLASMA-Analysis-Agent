import {expect,test} from '@playwright/test';
import type {AgentSubmission,ComparisonResultV3,RunOutput,TurnSnapshot,WorkspaceView} from 'agent';
import wire from '../../../../agent/tests/support/answer-v3-wire.json' with {type:'json'};
import {emptyWorkspace,initialTurnUi} from './useConversation';
for(const width of [390,800,1008,1440])test(`comparison charts and independent tagged message at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:1000});const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const result=structuredClone(wire.comparison.result) as ComparisonResultV3;
 const first=result.runs[0];result.runs=Array.from({length:5},(_,i)=>({...structuredClone(first),key:`R${i+1}`,ref:{runId:`SYNTHETIC-${i+1}`,runVersionId:`00000000-0000-0000-0000-${String(i+1).padStart(12,'0')}`}}));
 result.usedRunRefs=result.runs.map(r=>r.ref);result.plotIds=['current','iead'];
 const outputs:RunOutput[]=result.runs.flatMap((r,i)=>{
  const current=structuredClone(wire.outputs[0]) as RunOutput;current.metadata={...current.metadata,ref:r.ref,sourceIntegrity:`artificial-${i}`};
  return [current,{metadata:{...current.metadata,outputId:'iead',xUnit:'°',yUnit:'eV',valueUnit:'원본 단위 미지정',extrema:{maximum:{value:4,x:10,y:200,count:1}}},features:{},display:{kind:'grid',samples:[],rows:[{x:-10,coordinates:[100,200],values:[1,2]},{x:10,coordinates:[100,200],values:[3,4]}]}}];
 });
 result.outputs=outputs.map(o=>o.metadata);
 const turn={id:'artificial-compare',askedAt:'2026-10-09T00:00:00Z',question:'인공 파형 비교',intent:'RUN_COMPARISON',context:null,answerRunRefs:result.usedRunRefs,answerSnapshot:{...wire.comparison,result,usedRunRefs:result.usedRunRefs},ui:structuredClone(initialTurnUi)} as unknown as TurnSnapshot;
 let workspace:WorkspaceView={...structuredClone(emptyWorkspace),conversation:{version:1,activeRun:null,turns:[turn]},candidateReference:{kind:'후보 집합',runs:result.usedRunRefs},agentMessages:[{requestId:turn.id,clientMessageId:'saved-key',question:turn.question,submittedRunRefs:result.usedRunRefs,createdAt:turn.askedAt,status:'COMPLETED',turnId:turn.id}]};
 const posted:AgentSubmission[]=[];let release:(()=>void)|undefined;let graphCalls=0;
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;if(!path.startsWith('/api/'))return route.continue();
  if(path==='/api/decisions')return route.fulfill({json:[]});
  if(path==='/api/run-versions/outputs'){graphCalls++;const body=req.postDataJSON();return route.fulfill({json:{outputs:outputs.filter(o=>body.plotIds.includes(o.metadata.outputId))}});}
  if(path==='/api/agent/requests'){
   const body=req.postDataJSON();posted.push(body);await new Promise<void>(done=>release=done);
   const request={requestId:'new-request',requestRevision:0,status:'NEEDS_INPUT',stage:'wait_input',graphVersion:'v1',question:body.text,pendingInput:{id:'pick',message:'검증용 추가 입력'},error:null,partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]};
   workspace={...workspace,activeAgentRequest:request as WorkspaceView['activeAgentRequest'],agentMessages:[...workspace.agentMessages!,{requestId:request.requestId,clientMessageId:req.headers()['idempotency-key'],createdAt:'2026-10-09T00:01:00Z',question:body.text,submittedRunRefs:body.attachedRunRefs,status:'NEEDS_INPUT',turnId:null}]};return route.fulfill({json:request});
  }
  return route.fulfill({json:workspace});
 });
 await page.goto('/');const card=page.locator('[data-turn-id="artificial-compare"]');await card.getByRole('region',{name:'비교 그래프'}).scrollIntoViewIfNeeded();
 await expect(card.locator('path[data-run-id]')).toHaveCount(5);
 const chart=card.getByRole('region',{name:'비교 그래프'});
 await chart.getByRole('button',{name:'R1 SYNTHETIC-1',exact:true}).click();await expect(card.locator('path[data-run-id]')).toHaveCount(4);
 await chart.getByRole('button',{name:'전체 숨기기'}).click();await expect(chart.getByText(/표시 중인 실험이 없습니다/)).toBeVisible();
 await chart.getByRole('button',{name:'전체 표시'}).click();
 await chart.getByRole('tab',{name:'RF 전류 밀도 최댓값',exact:true}).click();await expect(chart.locator('rect[data-run-key]')).toHaveCount(5);
 await chart.getByRole('tab',{name:'에너지·입사각 분포',exact:true}).click();await expect(chart.getByRole('img')).toHaveCount(5);expect(graphCalls).toBe(2);
 await chart.getByRole('button',{name:'그래프 접기'}).click();await page.reload();await expect(chart.getByRole('button',{name:'그래프 펼치기'})).toBeVisible();
 await chart.getByRole('button',{name:'그래프 펼치기'}).click();await expect(chart.getByRole('img')).toHaveCount(5);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);expect(await card.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
 await card.screenshot({path:info.outputPath(`synthetic-comparison-${width}.png`)});
 await page.locator('#agent-query').fill('이 실험들 다시 비교해줘');await page.locator('#agent-query-form button[type=submit]').click();
 await expect.poll(()=>posted.length).toBe(1);const user=page.locator('.agent-user-message').filter({hasText:'이 실험들 다시 비교해줘'});
 await expect(user).toHaveCount(1);await expect(user.locator('.run-context-chip')).toHaveCount(5);
 await page.locator('#agent-query-form').evaluate(form=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(posted).toHaveLength(1);release!();await expect(page.getByRole('heading',{name:'추가 정보가 필요합니다'})).toBeVisible();
 await expect(page.getByText('이 실험들 다시 비교해줘',{exact:true})).toHaveCount(1);expect(errors).toEqual([]);
});
