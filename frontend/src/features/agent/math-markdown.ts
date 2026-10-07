import {fromMarkdown} from 'mdast-util-from-markdown';

type MarkdownNode={
 type:string;
 children?:MarkdownNode[];
 position?:{start:{offset?:number};end:{offset?:number}};
};

const protectedTypes=new Set(['code','inlineCode','html','link','image','definition']);

/** Display compatibility only: the stored Markdown remains the original model response. */
export function normalizeLegacyMath(markdown:string):string{
 if(!markdown.includes('\\(')&&!markdown.includes('\\['))return markdown;
 const protectedRanges:{start:number;end:number}[]=[];
 function visit(node:MarkdownNode){
  if(protectedTypes.has(node.type)){
   const start=node.position?.start.offset;const end=node.position?.end.offset;
   if(start!==undefined&&end!==undefined)protectedRanges.push({start,end});
   return;
  }
  node.children?.forEach(visit);
 }
 visit(fromMarkdown(markdown));
 function normalize(text:string){
  return text.replace(/(?<!\\)\\\(([\s\S]*?)(?<!\\)\\\)|(?<!\\)\\\[([\s\S]*?)(?<!\\)\\\]/g,(source,inline:string|undefined,block:string|undefined)=>{
   const formula=(inline??block??'').trim();
   if(!formula)return source;
   return inline!==undefined?`$${formula}$`:`\n$$\n${formula}\n$$\n`;
  });
 }
 let cursor=0;let output='';
 for(const {start,end} of protectedRanges.sort((a,b)=>a.start-b.start)){
  output+=normalize(markdown.slice(cursor,start))+markdown.slice(start,end);
  cursor=end;
 }
 return output+normalize(markdown.slice(cursor));
}
