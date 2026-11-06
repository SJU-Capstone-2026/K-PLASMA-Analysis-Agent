import {lazy,memo,Suspense,useMemo} from 'react';
import {fromMarkdown} from 'mdast-util-from-markdown';
import type {AgentRequestView,AgentResultProjection,ComparisonResultV2} from 'agent';
import {searchGroups,snapshotResult,type ComparisonResult,type SearchResult} from './agent-contract';
import {RunComparisonCard} from './RunComparisonCard';
import {V2SearchList} from './V2SearchList';

const AnswerMarkdown=lazy(()=>import('./GeneralAnswerCard').then(module=>({default:module.AnswerMarkdown})));
type MarkdownNode={type:string;children?:MarkdownNode[];position?:{start:{offset?:number};end:{offset?:number}}};

/** Keep an unfinished formula out of KaTeX without adding model text or closing delimiters. */
function completeMathPrefix(markdown:string){
 const protectedRanges:Array<{start:number;end:number}>=[];
 function visit(node:MarkdownNode){
  if(['code','inlineCode','html','link','image','definition'].includes(node.type)){
   const start=node.position?.start.offset;const end=node.position?.end.offset;
   if(start!==undefined&&end!==undefined)protectedRanges.push({start,end});
  }else node.children?.forEach(visit);
 }
 visit(fromMarkdown(markdown));
 let opening:number|null=null;let closing='';
 for(let index=0;index<markdown.length;index++){
  const protectedRange=protectedRanges.find(range=>range.start===index);
  if(protectedRange){index=protectedRange.end-1;continue;}
  if(closing){
   if(markdown.startsWith(closing,index)){index+=closing.length-1;opening=null;closing='';}
   else if(markdown[index]==='\\')index++;
   continue;
  }
  const pair=markdown.startsWith('\\(',index)?['\\(','\\)']:markdown.startsWith('\\[',index)?['\\[','\\]']
   :markdown.startsWith('$$',index)?['$$','$$']:markdown[index]==='$'?['$','$']:null;
  if(pair){opening=index;closing=pair[1];index+=pair[0].length-1;}
  else if(markdown[index]==='\\')index++;
 }
 return opening===null?markdown:markdown.slice(0,opening);
}

const titles={forward_lookup:'조건 조회 결과',reverse_search:'후보 검색 결과',compare_runs:'Run 비교 결과'};
const statuses={writing:'작성 중',reviewing:'검토 중',rewriting:'수정 중',interrupted:'작성 중단',done:'작성 완료'};

function blockOrder(id:string):number[]{
 let match=id.match(/^paragraphs\.(\d+)$/);
 if(match)return [0,Number(match[1])];
 match=id.match(/^interpretations\.(\d+)\.text$/);
 if(match)return [1,Number(match[1]),0];
 match=id.match(/^interpretations\.(\d+)\.assumptions\.(\d+)$/);
 if(match)return [1,Number(match[1]),1,Number(match[2])];
 match=id.match(/^limitations\.(\d+)\.text$/);
 return match?[2,Number(match[1])]:[3];
}

const StreamMarkdown=memo(function StreamMarkdown({text}:{text:string}){
 return <AnswerMarkdown markdown={completeMathPrefix(text)}/>;
});

export function StreamPreview({request,resultPreview}:{request:AgentRequestView;resultPreview?:AgentResultProjection|null}){
 const answer=request.status==='RUNNING'||request.status==='QUEUED'?request.progress?.answer:null;
 const requestId=request.requestId;
 const resultCards=useMemo(()=>{
  const toolResults=(resultPreview?.results??[]).flatMap(item=>{
   const result=item.toolResult;
   if(typeof result.kind!=='string'||!Object.hasOwn(titles,result.kind))return [];
   return [{...item,result,kind:result.kind as keyof typeof titles}];
  });
  const renderResult=(item:typeof toolResults[number])=>{
   if(item.kind==='compare_runs')return <RunComparisonCard compact storageId={`stream:${requestId}:${item.executionId}`}
    result={item.result as unknown as ComparisonResult|ComparisonResultV2}/>;
   const search=snapshotResult<SearchResult>({result:item.result});
   return <V2SearchList result={search} runs={searchGroups(search)[0]?.runs??[]} readOnly/>;
  };
  const last=toolResults.at(-1);
  return {
   primary:last?<section key={last.executionId} aria-label={titles[last.kind]} data-execution-id={last.executionId}>
    {last.kind!=='compare_runs'&&<h3>{titles[last.kind]}</h3>}{renderResult(last)}
   </section>:null,
   earlier:toolResults.slice(0,-1).map(item=><details key={item.executionId} className="v1-interpretation" data-execution-id={item.executionId}>
    <summary>{titles[item.kind]}</summary>{renderResult(item)}
   </details>),
  };
 },[requestId,resultPreview]);
 const blocks=useMemo(()=>(answer?.blocks??[]).map(block=>({block,order:blockOrder(block.id)})).sort((a,b)=>{
  for(let index=0;index<Math.max(a.order.length,b.order.length);index++){
   const difference=(a.order[index]??0)-(b.order[index]??0);
   if(difference)return difference;
  }
  return 0;
 }).map(item=>item.block),[answer?.blocks]);
 if(!resultCards.primary&&!answer)return null;
 return <div className="agent-stream-preview agent-v2-answer" aria-live="off">
  {resultCards.primary}
  {answer&&<section className="agent-stream-answer v2-answer-explanation" aria-label="작성 중인 답변" aria-live="off"
   data-stream-id={answer.streamId} data-answer-revision={answer.answerRevision}>
   <p className="agent-stream-status">{statuses[answer.status]}{answer.mode==='interpretation'&&<span> · 검토 전 초안</span>}</p>
   <Suspense fallback={<p className="agent-stream-status">답변을 표시하고 있습니다.</p>}>
    {answer.status!=='interrupted'&&blocks.map(block=><StreamMarkdown key={`${answer.streamId}:${block.id}`} text={block.text}/>)}
   </Suspense>
  </section>}
  {resultCards.earlier}
 </div>;
}
