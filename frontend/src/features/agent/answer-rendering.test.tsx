import {fireEvent,render,screen,within} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import type {TurnSnapshot} from 'agent';
import {syntheticRun} from '../../test/runs';
import {AgentPage,type AgentPageProps} from './AgentPage';
import {emptyWorkspace,initialTurnUi,type ConversationController} from './useConversation';
import * as searchModel from './v1-search-model';
import * as answerMarkup from './answer-markup';

const run=syntheticRun();
const other=syntheticRun(800);
const third=syntheticRun(1000);
const ref=(candidate:typeof run)=>({runId:candidate.runId,runVersionId:candidate.runVersionId});
function turn(id:string,candidate=run):TurnSnapshot{
 return {id,askedAt:'',question:'후보 찾기',intent:'REVERSE_SEARCH',context:null,answerRunRefs:[ref(candidate),ref(other),ref(third)],
  answerSnapshot:JSON.parse(JSON.stringify({implementationId:'v1',schemaVersion:1,kind:'reverse_search',result:{kind:'reverse_search',resultStatus:'MATCH',commonCandidates:[{run:candidate,evaluations:[]}],objectiveResults:[{objective:{id:'energy',metric:'meanIonEnergy',operator:'MIN',value:30,unit:'eV'},candidates:[{run:other,evaluations:[]},{run:third,evaluations:[]}]}],goalResults:[],nearMisses:[]}})),ui:structuredClone(initialTurnUi)};
}
function props(turns:TurnSnapshot[]):AgentPageProps{
 return {conversation:{state:{...emptyWorkspace,conversation:{version:1,activeRun:null,turns}},ready:true,error:'',pending:false,provisionalMessage:null,activeRequest:null,sending:false,submit:async()=>{},resume:async()=>{},cancel:async()=>{},updateTurnUi:async()=>{},setReference:async()=>{},refresh:async()=>{},newConversation:async()=>{},reset:async()=>{}},records:[],notify:()=>{},onDetail:()=>{},onRecord:()=>{},onEvidence:()=>{},onDemo:async()=>{}};
}
afterEach(()=>vi.restoreAllMocks());

test('typing and UI-only selections reuse saved search presentation without losing the selected card',()=>{
 const model=vi.spyOn(searchModel,'v1SearchModel');
 const markup=vi.spyOn(answerMarkup,'renderAgentAnswer');
 const first=turn('first');const second=turn('second');const initial=props([first,second]);
 const {rerender,container}=render(<AgentPage {...initial}/>);
 expect(model).toHaveBeenCalledTimes(2);
 expect(markup).toHaveBeenCalledTimes(2);
 fireEvent.change(screen.getByRole('textbox',{name:'공정 데이터에 질문하기'}),{target:{value:'후속 질문'}});
 expect(model).toHaveBeenCalledTimes(2);
 expect(markup).toHaveBeenCalledTimes(2);
 const selected={...second,ui:{...second.ui,selectedCandidateRunId:run.runId}};
 rerender(<AgentPage {...props([first,selected])}/>);
 expect(model).toHaveBeenCalledTimes(2);
 expect(markup).toHaveBeenCalledTimes(3);
 expect(container.querySelector('[data-turn-id="second"] .agent-fit-card')).toHaveClass('is-selected');
 expect(container.querySelector('[data-turn-id="first"] .agent-fit-card')).not.toHaveClass('is-selected');
 expect(container.querySelector('[data-turn-id="second"] .agent-fit-card')).toHaveTextContent(run.runId);
});

test('memoized answers use the latest handlers and current group when referencing experiments',()=>{
 const first=turn('first');const initial=props([first]);const obsolete=vi.fn();initial.onDetail=obsolete;
 const {rerender,container}=render(<AgentPage {...initial}/>);
 const onDetail=vi.fn();const setReference=vi.fn<ConversationController['setReference']>(async()=>{});const updateTurnUi=vi.fn(async()=>{});
 const current={...initial,onDetail,conversation:{...initial.conversation,setReference,updateTurnUi}};
 rerender(<AgentPage {...current}/>);
 fireEvent.click(screen.getByRole('button',{name:'실험 자세히 보기'}));
 expect(onDetail).toHaveBeenCalledWith(ref(run),first);expect(obsolete).not.toHaveBeenCalled();
 const selected={...first,ui:{...first.ui,selectedCandidateRunId:run.runId}};
 rerender(<AgentPage {...current} conversation={{...current.conversation,state:{...current.conversation.state,conversation:{version:1,activeRun:null,turns:[selected]}}}}/>);
 fireEvent.click(container.querySelector('[data-action="select-candidate-card"]')!);
 expect(updateTurnUi).toHaveBeenCalledWith(first.id,{selectedCandidateRunId:null});
 const group=container.querySelector<HTMLElement>('[data-action="candidate-group"][data-group-id^="objective-"]')!;
 expect(group).not.toBeNull();
 const grouped={...selected,ui:{...selected.ui,activeCandidateGroup:group.dataset.groupId!}};
 rerender(<AgentPage {...current} conversation={{...current.conversation,state:{...current.conversation.state,conversation:{version:1,activeRun:null,turns:[grouped]}}}}/>);
 const article=within(container.querySelector('[data-turn-id="first"]') as HTMLElement);
 expect(article.getByText(other.runId)).toBeInTheDocument();
 fireEvent.click(article.getByRole('button',{name:'전체 후보 채팅에 추가'}));
 const update=setReference.mock.calls[0][0];expect(typeof update==='function'?update(emptyWorkspace):update).toEqual({kind:'후보 집합',runs:[ref(other),ref(third)]});
});

test('a new answer snapshot rebuilds presentation and routes detail to its exact version',()=>{
 const model=vi.spyOn(searchModel,'v1SearchModel');const first=turn('first');const initial=props([first]);
 const {rerender,container}=render(<AgentPage {...initial}/>);
 const updatedRun={...run,runVersionId:'replacement-version',metrics:{...run.metrics,meanIonEnergy:81}};
 const updated=turn('first',updatedRun);const onDetail=vi.fn();
 rerender(<AgentPage {...props([updated])} onDetail={onDetail}/>);
 expect(model).toHaveBeenCalledTimes(2);
 expect(container.querySelector('.agent-fit-card')).toHaveTextContent('81 eV');
 fireEvent.click(screen.getByRole('button',{name:'실험 자세히 보기'}));
 expect(onDetail).toHaveBeenCalledWith(ref(updatedRun),updated);
});

test('changing the question invalidates the saved range interpretation notice',()=>{
 const model=vi.spyOn(searchModel,'v1SearchModel');const first=turn('first');
 first.answerSnapshot=JSON.parse(JSON.stringify({...first.answerSnapshot,versions:{promptVersion:'interpret-1'},result:{...first.answerSnapshot.result as object,goals:[{metric:'meanIonEnergy',direction:'target_range',min:30,max:40}]}}));
 const {rerender}=render(<AgentPage {...props([first])}/>);
 expect(screen.getByText(/범위를 정렬 목표로 해석한 이전 결과/)).toBeInTheDocument();
 rerender(<AgentPage {...props([{...first,question:'범위 밖 허용'}])}/>);
 expect(model).toHaveBeenCalledTimes(2);
 expect(screen.queryByText(/범위를 정렬 목표로 해석한 이전 결과/)).not.toBeInTheDocument();
});

test('clearing the conversation discards presentation and actions from the previous turn',()=>{
 const first=turn('first');const initial=props([first]);const obsolete=vi.fn();initial.onDetail=obsolete;
 const {rerender,container}=render(<AgentPage {...initial}/>);
 rerender(<AgentPage {...props([])}/>);
 expect(container.querySelector('.agent-turn')).toBeNull();
 const replacement={...run,runVersionId:'new-conversation-version',metrics:{...run.metrics,meanIonEnergy:93}};
 const current=turn('first',replacement);const onDetail=vi.fn();
 rerender(<AgentPage {...props([current])} onDetail={onDetail}/>);
 expect(container.querySelector('.agent-fit-card')).toHaveTextContent('93 eV');
 fireEvent.click(screen.getByRole('button',{name:'실험 자세히 보기'}));
 expect(onDetail).toHaveBeenCalledWith(ref(replacement),current);expect(obsolete).not.toHaveBeenCalled();
});
