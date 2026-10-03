import {useEffect,useRef} from 'react';
export interface ToastMessage {id:number;text:string;tone?:string}
function ToastItem({message,onRemove}:{message:ToastMessage;onRemove:(id:number)=>void}){const remove=useRef(onRemove);remove.current=onRemove;useEffect(()=>{const timer=setTimeout(()=>remove.current(message.id),3200);return()=>clearTimeout(timer);},[message.id]);return <div className={`toast toast--${message.tone||'success'}`}>{message.text}</div>;}
export function Toast({messages,onRemove}:{messages:ToastMessage[];onRemove:(id:number)=>void}){return <div id="toast-region" className="toast-region" aria-live="polite" aria-atomic="true">{messages.map(message=><ToastItem key={message.id} message={message} onRemove={onRemove}/>)}</div>;}
