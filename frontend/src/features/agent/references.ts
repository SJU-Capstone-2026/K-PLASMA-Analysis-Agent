import type {RunRef,Snapshot,TurnSnapshot} from 'agent';
export interface MemoryEntry {demo:boolean;decision:string;createdAt:string;question:string;conditions:Record<string,number>;note:string;sharedComment:string;recordId:string}
export interface MemoryRun {runId:string;entries:MemoryEntry[]}
export interface DisplayAnswer {candidateRunRefs?:RunRef[];nestedAnswer?:DisplayAnswer;candidateGroups?:{groups:{id:string;candidates:{runId:string}[]}[]};memoryResult?:{remaining:MemoryRun[];excluded:MemoryRun[]};runIds?:string[];reference?:{ids:string[]};memoryRequest?:{text:string;reference?:{ids:string[]};threshold:number|null;referenceRunRefs?:RunRef[]}}
export const displayAnswer=(snapshot:Snapshot)=>snapshot as unknown as DisplayAnswer;
/** Snapshot/UI selection only: never search or recompute persisted answers. */
export function candidateRefs(turn:TurnSnapshot):RunRef[]{
 const outer=displayAnswer(turn.answerSnapshot);const answer=outer.nestedAnswer??outer;
 const groups=answer.candidateGroups?.groups;const active=groups?.find(group=>group.id===turn.ui.activeCandidateGroup)??groups?.[0];
 const ids=answer.memoryResult?answer.memoryResult.remaining.map(item=>item.runId):active?active.candidates.map(candidate=>candidate.runId):answer.runIds??[];
 return [...new Set(ids)].flatMap(id=>resolveCandidateRef(turn,id)??[]);
}
export function latestCandidateRefs(turns:TurnSnapshot[]):RunRef[]{for(const turn of [...turns].reverse()){const outer=displayAnswer(turn.answerSnapshot);const answer=outer.nestedAnswer??outer;if(!answer.candidateGroups?.groups)continue;const refs=candidateRefs(turn);if(refs.length>1)return refs;}return [];}

export function resolveCandidateRef(turn:TurnSnapshot,id:string):RunRef|undefined {const outer=displayAnswer(turn.answerSnapshot);const roles=outer.candidateRunRefs??outer.nestedAnswer?.candidateRunRefs;return roles?.find(ref=>ref.runId===id)??outer.memoryRequest?.referenceRunRefs?.find(ref=>ref.runId===id)??[...turn.answerRunRefs].reverse().find(ref=>ref.runId===id);}
