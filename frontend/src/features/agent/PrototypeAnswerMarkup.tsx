import {createElement,Fragment,type CSSProperties,type ReactNode} from 'react';
import type {TurnSnapshot} from 'agent';
import {renderAgentAnswer} from './answer-markup';
export type AnswerAction=(action:string,element:HTMLElement)=>void;
const tags=new Set('article section div span strong small p h3 h4 ol li details summary i em b button input header footer'.split(' '));
/** Parse only inert, escaped prototype presentation markup. React mounts all live nodes and owns events. */
function nodes(markup:string,onAction:AnswerAction):ReactNode{
 const template=document.createElement('template');template.innerHTML=markup;
 function convert(node:Node,key:string):ReactNode{
  if(node.nodeType===Node.TEXT_NODE)return node.textContent;
  if(!(node instanceof HTMLElement)||!tags.has(node.localName))return null;
  const props:Record<string,unknown>={key};
  for(const attribute of Array.from(node.attributes)){
   const {name,value}=attribute;if(name.startsWith('on'))continue;
   if(name==='class')props.className=value;else if(name==='tabindex')props.tabIndex=Number(value);else if(name==='style'){
    const style:Record<string,string>={};for(const item of value.split(';')){const [property,...parts]=item.split(':');if(property&&parts.length)style[property.trim().replace(/-([a-z])/g,(_,letter:string)=>letter.toUpperCase())]=parts.join(':').trim();}props.style=style as CSSProperties;
   }else if(['disabled','required','hidden'].includes(name))props[name]=true;else if(name==='value')props.defaultValue=value;else props[name]=value;
  }
  if(node.dataset.action){props.onClick=(event:React.MouseEvent<HTMLElement>)=>onAction(node.dataset.action!,event.currentTarget);if(node.getAttribute('role')==='button')props.onKeyDown=(event:React.KeyboardEvent<HTMLElement>)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onAction(node.dataset.action!,event.currentTarget);}};}
  return createElement(node.localName,props,...Array.from(node.childNodes).map((child,index)=>convert(child,`${key}.${index}`)));
 }
 return <Fragment>{Array.from(template.content.childNodes).map((node,index)=>convert(node,String(index)))}</Fragment>;
}
export function PrototypeAnswerMarkup({answer,turn,onAction}:{answer:Record<string,unknown>;turn:TurnSnapshot;onAction:AnswerAction}){return nodes(renderAgentAnswer(answer,{...turn,contextRunId:turn.context?.runId??null}),onAction);}
