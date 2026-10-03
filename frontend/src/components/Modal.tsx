import {useEffect,useLayoutEffect,useRef,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
export function Modal({titleId,onClose,children,className='decision-modal',focusKey,synchronousFocus=false,role='dialog',descriptionId,initialFocusSelector}:{titleId:string;onClose:()=>void;children:ReactNode;className?:string;focusKey?:string;synchronousFocus?:boolean;role?:'dialog'|'alertdialog';descriptionId?:string;initialFocusSelector?:string}){
 const panel=useRef<HTMLElement>(null);const trigger=useRef<HTMLElement|null>(null);const close=useRef(onClose);close.current=onClose;
 useLayoutEffect(()=>{trigger.current=document.activeElement instanceof HTMLElement?document.activeElement:null;document.body.classList.add('modal-open');return()=>{document.body.classList.remove('modal-open');if(trigger.current?.isConnected)trigger.current.focus();};},[]);
 useEffect(()=>{const focus=()=>{const target=initialFocusSelector?panel.current?.querySelector<HTMLElement>(initialFocusSelector):null;(target??panel.current)?.focus();};if(synchronousFocus){focus();return;}const frame=requestAnimationFrame(focus);return()=>cancelAnimationFrame(frame);},[focusKey,synchronousFocus,initialFocusSelector]);
 useEffect(()=>{
 function onKeyDown(event:KeyboardEvent){
  if(event.key==='Escape'){event.preventDefault();close.current();return;}
  if(event.key!=='Tab')return;
  const elements=Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')??[]).filter(el=>{for(let current:HTMLElement|null=el;current&&current!==panel.current;current=current.parentElement){if(current.hidden||getComputedStyle(current).display==='none')return false;}return !el.closest('details:not([open])');});
  const first=elements[0],last=elements.at(-1);const active=document.activeElement;
  if(!first){event.preventDefault();panel.current?.focus();return;}
  if(event.shiftKey&&(active===first||active===panel.current||!panel.current?.contains(active))){event.preventDefault();last?.focus();}
  else if(!event.shiftKey&&(active===last||active===panel.current||!panel.current?.contains(active))){event.preventDefault();first.focus();}
 }
 document.addEventListener('keydown',onKeyDown);return()=>document.removeEventListener('keydown',onKeyDown);
 },[]);
 const content=<div className="modal-backdrop"><section ref={panel} className={className} role={role} aria-modal="true" aria-describedby={descriptionId} aria-labelledby={titleId} tabIndex={-1} data-modal-panel>{children}</section></div>;
 const root=document.getElementById('modal-root');return root?createPortal(content,root):content;
}
