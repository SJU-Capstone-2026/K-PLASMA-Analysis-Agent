import {expect,test} from '@playwright/test';
import type {AgentSubmission,TurnSnapshot,WorkspaceView} from 'agent';
import general from '../../../../agent/tests/support/v2/contracts.json' with {type:'json'};
import {syntheticRun} from '../../test/runs';
import {emptyWorkspace,initialTurnUi} from './useConversation';

for(const width of [390,800,1008,1440])test(`saved rooms keep answers and Run tags at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:1000});
 const runs=[syntheticRun(200),syntheticRun(400)];
 const ref=(index:number)=>({runId:runs[index].runId,runVersionId:runs[index].runVersionId});
 const original:TurnSnapshot={id:'original',askedAt:'2026-11-05T00:00:00Z',question:'기존 대화의 질문',intent:'GENERAL_ANSWER',
  context:null,answerRunRefs:[],answerSnapshot:{...general.general_answer,answer:'저장된 원래 답변입니다.'},ui:structuredClone(initialTurnUi)};
 let workspace:WorkspaceView={...structuredClone(emptyWorkspace),stateToken:{workspaceEpoch:1,conversationEpoch:1,revision:0},
  conversation:{version:1,agentGraphVersion:'v2',activeRun:ref(0),turns:[original]},
  candidateReference:{kind:'단일 Run',runs:[ref(0)],catalogRefs:[ref(0)]},
  conversations:[{conversationEpoch:1,title:original.question,createdAt:original.askedAt,updatedAt:original.askedAt}]};
 type Room=Pick<WorkspaceView,'conversation'|'candidateReference'|'agentMessages'>;
 const rooms=new Map<number,Room>();
 const save=()=>rooms.set(workspace.stateToken.conversationEpoch,structuredClone({conversation:workspace.conversation,
  candidateReference:workspace.candidateReference,agentMessages:workspace.agentMessages}));
 const posted:AgentSubmission[]=[];
 await page.route('**/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  if(!path.startsWith('/api/'))return route.continue();
  if(path==='/api/runs')return route.fulfill({json:runs});
  if(path==='/api/decisions')return route.fulfill({json:[]});
  if(path==='/api/workspace'&&request.method()==='GET')return route.fulfill({json:workspace});
  const body=request.postDataJSON();
  if(path==='/api/workspace/new-conversation'){
   save();const next=Math.max(workspace.stateToken.conversationEpoch,...rooms.keys())+1;
   workspace={...workspace,stateToken:{...workspace.stateToken,conversationEpoch:next,revision:workspace.stateToken.revision+1},
    conversation:{version:1,agentGraphVersion:null,activeRun:null,turns:[]},candidateReference:null,agentMessages:[],
    conversations:[{conversationEpoch:next,title:'새 대화',createdAt:original.askedAt,updatedAt:original.askedAt},...workspace.conversations!]};
  }else if(path.endsWith('/activate')){
   save();const epoch=Number(path.split('/').at(-2));
   workspace={...workspace,...structuredClone(rooms.get(epoch)!),stateToken:{...workspace.stateToken,
    conversationEpoch:epoch,revision:workspace.stateToken.revision+1}};
  }else if(path.endsWith('/reference')){
   workspace={...workspace,candidateReference:body.candidateReference,conversation:{...workspace.conversation,activeRun:body.activeRun},
    stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1}};
  }else if(path==='/api/agent/requests'){
   posted.push(body);const turn:TurnSnapshot={...original,id:'second',question:body.text,
    answerSnapshot:{...general.general_answer,question:body.text,answer:'새 방에 저장된 답변입니다.'}};
   workspace={...workspace,conversation:{...workspace.conversation,agentGraphVersion:'v2',turns:[turn]},
    conversations:workspace.conversations!.map(room=>room.conversationEpoch===workspace.stateToken.conversationEpoch?{...room,title:body.text}:room),
    stateToken:{...workspace.stateToken,revision:workspace.stateToken.revision+1}};
   return route.fulfill({json:{requestId:turn.id,requestRevision:0,status:'COMPLETED',stage:'completed',graphVersion:'v2',
    question:body.text,pendingInput:null,error:null,partialResult:null,turnId:turn.id,answerSnapshot:turn.answerSnapshot,inputEvents:[]}});
  }else throw new Error(`Unexpected request ${request.method()} ${path}`);
  return route.fulfill({json:workspace});
 });
 await page.goto('/');
 const sidebar=page.getByRole('region',{name:'채팅방 목록'});
 const menu=page.getByRole('button',{name:'메뉴 열기'});
 async function showRooms(){if(await menu.isVisible())await menu.click();}
 await expect(page.getByText('저장된 원래 답변입니다.',{exact:true})).toBeVisible();
 const originalSnapshot=JSON.stringify(workspace.conversation.turns);
 await showRooms();await sidebar.getByRole('button',{name:'새 채팅 만들기'}).click();
 await expect(page.getByRole('heading',{name:'실제 Run과 공정 원리를 함께 설명합니다'})).toBeVisible();
 const composer=page.locator('#agent-query-form');
 await expect(composer.locator('.run-context-chip')).toHaveCount(0);
 await page.getByRole('combobox',{name:'Agent 버전'}).selectOption('v2');
 const input=composer.getByRole('textbox');
 await input.fill(`@${runs[1].runId}`);
 await page.getByRole('option').filter({hasText:runs[1].runId}).click();
 await expect(composer.locator('.run-context-chip strong')).toHaveText(runs[1].runId);
 await input.fill('두 번째 방의 질문');await composer.getByRole('button',{name:'분석',exact:true}).click();
 await expect(page.getByText('새 방에 저장된 답변입니다.',{exact:true})).toBeVisible();
 expect(posted[0].attachedRunRefs).toEqual([ref(1)]);
 await input.fill('두 번째 방에서 이어 쓸 질문');
 await showRooms();await sidebar.getByRole('button',{name:original.question,exact:true}).click();
 await expect(page.getByText('저장된 원래 답변입니다.',{exact:true})).toBeVisible();
 await expect(page.getByText('새 방에 저장된 답변입니다.',{exact:true})).toHaveCount(0);
 await expect(composer.locator('.run-context-chip strong')).toHaveText(runs[0].runId);
 await expect(input).toHaveValue('');
 await input.fill('기존 방에서 이어 쓸 질문');
 expect(JSON.stringify(workspace.conversation.turns)).toBe(originalSnapshot);
 await showRooms();await sidebar.getByRole('button',{name:'두 번째 방의 질문',exact:true}).click();
 await expect(page.getByText('새 방에 저장된 답변입니다.',{exact:true})).toBeVisible();
 await expect(composer.locator('.run-context-chip strong')).toHaveText(runs[1].runId);
 await expect(input).toHaveValue('두 번째 방에서 이어 쓸 질문');
 await page.reload();await expect(page.getByText('새 방에 저장된 답변입니다.',{exact:true})).toBeVisible();
 await expect(composer.locator('.run-context-chip strong')).toHaveText(runs[1].runId);
 const gaps=await page.locator('.agent-page--wide').evaluate(el=>{
  const box=el.getBoundingClientRect(),parent=el.parentElement!.getBoundingClientRect();
  return {left:box.left-parent.left,right:parent.right-box.right,width:box.width,overflow:document.documentElement.scrollWidth>innerWidth};
 });
 expect(Math.abs(gaps.left-gaps.right)).toBeLessThanOrEqual(1);
 expect(gaps.width).toBeLessThanOrEqual(850);expect(gaps.overflow).toBe(false);
 await page.screenshot({path:info.outputPath(`synthetic-conversation-rooms-${width}.png`),fullPage:false});
});
