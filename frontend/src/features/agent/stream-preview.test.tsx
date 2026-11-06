import {render,screen} from '@testing-library/react';
import {expect,test} from 'vitest';
import type {AgentRequestView,AgentResultProjection,Snapshot} from 'agent';
import {StreamPreview} from './StreamPreview';
import {syntheticRun} from '../../test/runs';

const request:AgentRequestView={requestId:'ordered-stream',requestRevision:0,status:'RUNNING',stage:'compose',graphVersion:'v2',
 question:'인공 해석 질문',pendingInput:null,error:null,partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[]};
function withBlocks(blocks:Array<{id:string;text:string}>,mode:'general'|'interpretation'='interpretation'):AgentRequestView {
 return {...request,progress:{lastEventSeq:1,activities:[],resultRevision:null,
  answer:{streamId:'draft',answerRevision:1,mode,status:'writing',blocks}}};
}

test('interpretation text precedes its assumptions and all paths use numeric index order',async()=>{
 const {container}=render(<StreamPreview request={withBlocks([
  {id:'limitations.10.text',text:'열한 번째 한계'},
  {id:'interpretations.10.assumptions.10',text:'열한 번째 해석의 열한 번째 전제'},
  {id:'interpretations.2.assumptions.10',text:'세 번째 해석의 열한 번째 전제'},
  {id:'interpretations.10.text',text:'열한 번째 해석'},
  {id:'limitations.2.text',text:'세 번째 한계'},
  {id:'interpretations.2.text',text:'세 번째 해석'},
  {id:'interpretations.2.assumptions.2',text:'세 번째 해석의 세 번째 전제'},
 ])}/>);
 await screen.findByText('세 번째 해석');
 expect(Array.from(container.querySelectorAll('.v1-markdown'),element=>element.textContent)).toEqual([
  '세 번째 해석','세 번째 해석의 세 번째 전제','세 번째 해석의 열한 번째 전제',
  '열한 번째 해석','열한 번째 해석의 열한 번째 전제','세 번째 한계','열한 번째 한계',
 ]);
});

test('general paragraphs use their numeric path order rather than provider property arrival',async()=>{
 const {container}=render(<StreamPreview request={withBlocks([
  {id:'paragraphs.10',text:'열한 번째 문단'},
  {id:'paragraphs.2',text:'세 번째 문단'},
  {id:'paragraphs.1',text:'두 번째 문단'},
 ],'general')}/>);
 await screen.findByText('두 번째 문단');
 expect(Array.from(container.querySelectorAll('.v1-markdown'),element=>element.textContent)).toEqual([
  '두 번째 문단','세 번째 문단','열한 번째 문단',
 ]);
});

test('another prose chunk does not re-read unchanged verified Run rows',async()=>{
 const candidate=JSON.parse(JSON.stringify(syntheticRun())) as Snapshot;
 let pressureReads=0;
 Object.defineProperty(candidate,'pressure',{get:()=>{pressureReads++;return 6;},enumerable:true});
 const resultPreview:AgentResultProjection={resultRevision:1,results:[{stepId:'lookup',executionId:'lookup',runRefs:[],
  toolResult:{kind:'forward_lookup',resultStatus:'EXACT',candidates:[candidate]}}]};
 const {rerender}=render(<StreamPreview request={withBlocks([{id:'interpretations.0.text',text:'첫 문장'}])} resultPreview={resultPreview}/>);
 await screen.findByText('첫 문장');
 expect(screen.getByRole('table',{name:'검색 Run 목록'})).toBeVisible();
 const readsAfterFirstRender=pressureReads;
 expect(readsAfterFirstRender).toBeGreaterThan(0);
 rerender(<StreamPreview request={withBlocks([{id:'interpretations.0.text',text:'첫 문장과 이어진 내용'}])} resultPreview={resultPreview}/>);
 await screen.findByText('첫 문장과 이어진 내용');
 expect(pressureReads).toBe(readsAfterFirstRender);
});
