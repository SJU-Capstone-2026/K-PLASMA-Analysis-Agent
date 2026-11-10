import {useState} from 'react';
import type {ConversationSummary} from 'agent';

export function ConversationList({rooms,activeEpoch,disabled,onNew,onSelect,onOpened,onError}: {
 rooms:ConversationSummary[];
 activeEpoch:number;
 disabled:boolean;
 onNew:()=>Promise<void>;
 onSelect:(epoch:number)=>Promise<void>;
 onOpened:()=>void;
 onError:(message:string)=>void;
}) {
 const [changing,setChanging]=useState(false);
 async function open(action:()=>Promise<void>) {
  if(changing||disabled)return;
  setChanging(true);
  try{await action();onOpened();}
  catch(error){onError(error instanceof Error?error.message:String(error));}
  finally{setChanging(false);}
 }
 return <section className="conversation-list" aria-label="채팅방 목록">
  <header><h2>대화</h2><button type="button" className="conversation-create" aria-label="새 채팅 만들기"
   title="새 대화" disabled={disabled||changing} onClick={()=>void open(onNew)}>+</button></header>
  <div className="conversation-list-items">
   {rooms.map(room=><button key={room.conversationEpoch} type="button" className="conversation-item"
    aria-current={room.conversationEpoch===activeEpoch?'page':undefined} title={room.title}
    disabled={disabled||changing} onClick={()=>void open(()=>onSelect(room.conversationEpoch))}>
    <span>{room.title}</span>
   </button>)}
  </div>
 </section>;
}
