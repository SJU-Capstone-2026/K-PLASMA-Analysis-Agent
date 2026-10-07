import {isV1AnswerSnapshot,type RunRef,type Snapshot,type TurnSnapshot,type WorkspaceView,type ReferenceOrigin} from 'agent';
import {searchGroups,snapshotResult,type SearchResult} from './agent-contract';
export interface MemoryEntry {demo:boolean;decision:string;createdAt:string;question:string;conditions:Record<string,number>;note:string;sharedComment:string;recordId:string}
export interface MemoryRun {runId:string;entries:MemoryEntry[]}
export interface DisplayAnswer {candidateRunRefs?:RunRef[];excludedRunRefs?:RunRef[];nestedAnswer?:DisplayAnswer;candidateGroups?:{groups:{id:string;candidates:{runId:string}[]}[]};memoryResult?:{remaining:MemoryRun[];excluded:MemoryRun[]};runIds?:string[];reference?:{ids:string[]};memoryRequest?:{text:string;reference?:{ids:string[]};threshold:number|null;referenceRunRefs?:RunRef[]}}
export const displayAnswer=(snapshot:Snapshot)=>snapshot as unknown as DisplayAnswer;
/** Exact saved candidates exclude contextual versions of the same Run. */
export function v1CandidateRefs(turn:TurnSnapshot):RunRef[]{
 if(!isV1AnswerSnapshot(turn.answerSnapshot)||!['forward_lookup','reverse_search'].includes(String(turn.answerSnapshot.kind)))return [];
 const refs=searchGroups(snapshotResult<SearchResult>(turn.answerSnapshot)).flatMap(group=>group.runs.map(asRef));
 return [...new Map(refs.map(ref=>[JSON.stringify(ref),ref])).values()];
}
const asRef=(run:RunRef):RunRef=>({runId:run.runId,runVersionId:run.runVersionId});
/** Only references selected in the UI qualify. Merely present historical candidates do not. */
export function explicitReferences(state:WorkspaceView,override?:{candidateReference:WorkspaceView['candidateReference'];activeRun:RunRef|null}):{refs:RunRef[];origins:ReferenceOrigin[]}{
 const reference=override?.candidateReference??state.candidateReference;
 const active=override?override.activeRun:state.conversation.activeRun;
 const proposed=[...new Map((reference?.runs??(active?[active]:[])).map(r=>[`${r.runId}\0${r.runVersionId}`,asRef(r)])).values()];
 // A catalog-only legacy reference has no saved turn origin; the comparison picker resolves it.
 const refs=proposed.filter(ref=>state.conversation.turns.some(t=>t.answerRunRefs.some(r=>r.runId===ref.runId&&r.runVersionId===ref.runVersionId)));
 const origins=refs.map(ref=>{
  const turn=state.conversation.turns.slice().reverse().find(t=>t.answerRunRefs.some(r=>r.runId===ref.runId&&r.runVersionId===ref.runVersionId));
  if(!turn)throw new Error(`${ref.runId}의 저장된 실험 참조를 찾을 수 없습니다. 실험 선택 화면에서 다시 선택해 주세요.`);
  const group=reference?.kind==='후보 집합'&&reference.runs.some(r=>r.runVersionId===ref.runVersionId)&&isV1AnswerSnapshot(turn.answerSnapshot)&&['forward_lookup','reverse_search'].includes(String(turn.answerSnapshot.kind))?searchGroups(snapshotResult<SearchResult>(turn.answerSnapshot)).find(g=>g.runs.some(r=>r.runId===ref.runId&&r.runVersionId===ref.runVersionId)):undefined;
  return {ref,kind:group?'candidate_group' as const:'run_tag' as const,turnId:turn.id,groupId:group?.id??null};
 });
 return {refs,origins};
}
/** Snapshot/UI selection only: never search or recompute persisted answers. */
export function candidateRefs(turn:TurnSnapshot):RunRef[]{
 if(isV1AnswerSnapshot(turn.answerSnapshot)){if(!['forward_lookup','reverse_search'].includes(String(turn.answerSnapshot.kind)))return [];const groups=searchGroups(snapshotResult<SearchResult>(turn.answerSnapshot));return (groups.find(g=>g.id===turn.ui.activeCandidateGroup)??groups[0]).runs.map(r=>({runId:r.runId,runVersionId:r.runVersionId}));}
 const outer=displayAnswer(turn.answerSnapshot);const answer=outer.nestedAnswer??outer;
 const groups=answer.candidateGroups?.groups;const active=groups?.find(group=>group.id===turn.ui.activeCandidateGroup)??groups?.[0];
 const ids=answer.memoryResult?answer.memoryResult.remaining.map(item=>item.runId):active?active.candidates.map(candidate=>candidate.runId):answer.runIds??[];
 return [...new Set(ids)].flatMap(id=>resolveCandidateRef(turn,id)??[]);
}
export function latestCandidateRefs(turns:TurnSnapshot[]):RunRef[]{for(const turn of [...turns].reverse()){if(isV1AnswerSnapshot(turn.answerSnapshot)){if(turn.answerSnapshot.kind!=='reverse_search')continue;const refs=candidateRefs(turn);if(refs.length>1)return refs;continue;}const outer=displayAnswer(turn.answerSnapshot);const answer=outer.nestedAnswer??outer;if(!answer.candidateGroups?.groups)continue;const refs=candidateRefs(turn);if(refs.length>1)return refs;}return [];}

export function resolveCandidateRef(turn:TurnSnapshot,id:string):RunRef|undefined {if(isV1AnswerSnapshot(turn.answerSnapshot)){const matches=v1CandidateRefs(turn).filter(ref=>ref.runId===id);return matches.length===1?matches[0]:undefined;}const outer=displayAnswer(turn.answerSnapshot);const roles=outer.candidateRunRefs??outer.nestedAnswer?.candidateRunRefs;return roles?.find(ref=>ref.runId===id)??outer.excludedRunRefs?.find(ref=>ref.runId===id)??outer.memoryRequest?.referenceRunRefs?.find(ref=>ref.runId===id)??[...turn.answerRunRefs].reverse().find(ref=>ref.runId===id);}
