import type {RunRef} from 'agent';
import {ReferenceTray} from '../../components/ReferenceTray';

export function AgentUserMessage({question,refs=[]}:{question:string;refs?:RunRef[]}){
  return <div className="agent-user-message">
    {refs.length>0&&<ReferenceTray references={refs}/>}
    <p>{question}</p>
  </div>;
}
