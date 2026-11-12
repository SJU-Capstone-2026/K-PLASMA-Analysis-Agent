import {isV1AnswerSnapshot,type RunRef,type Snapshot,type TurnSnapshot,type WorkspaceView,type ReferenceOrigin,type V2RecordSource} from 'agent';
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
const composerRefs=(state:WorkspaceView)=>state.candidateReference?.runs??(state.conversation.activeRun?[state.conversation.activeRun]:[]);
const sameRef=(a:RunRef,b:RunRef)=>a.runId===b.runId&&a.runVersionId===b.runVersionId;
function referenceFromRuns(runs:RunRef[],origins:NonNullable<NonNullable<WorkspaceView['candidateReference']>['v2Origins']> = [],catalog:RunRef[] = []):WorkspaceView['candidateReference']{
 const kept=origins.filter(origin=>runs.some(run=>sameRef(run,origin.ref)));
 const catalogRefs=catalog.filter(ref=>runs.some(run=>sameRef(run,ref)));
 return runs.length?{kind:runs.length===1?'단일 Run':'후보 집합',runs,...(kept.length?{v2Origins:kept}:{}),...(catalogRefs.length?{catalogRefs}:{})}:null;
}
/** One tag per Run, with the exact source chosen by the latest click. */
export function appendRunReferences(state:WorkspaceView,refs:RunRef[],source?:V2RecordSource|'catalog'){
 const runs=[...new Map([...composerRefs(state),...refs].map(run=>[run.runId,asRef(run)])).values()];
 const previous=(state.candidateReference?.v2Origins??[]).filter(origin=>!refs.some(ref=>ref.runId===origin.ref.runId));
 const catalog=(state.candidateReference?.catalogRefs??[]).filter(item=>!refs.some(ref=>ref.runId===item.runId));
 return referenceFromRuns(runs,[...previous,...(source&&source!=='catalog'?refs.map(ref=>({ref:asRef(ref),source})):[])],
  source==='catalog'?[...catalog,...refs.map(asRef)]:catalog);
}
export function removeRunReference(state:WorkspaceView,ref:RunRef){
 return referenceFromRuns(composerRefs(state).filter(run=>!sameRef(run,ref)).map(asRef),state.candidateReference?.v2Origins,state.candidateReference?.catalogRefs);
}
/** Only references selected in the UI qualify. Merely present historical candidates do not. */
export function explicitReferences(state:WorkspaceView,override?:{candidateReference:WorkspaceView['candidateReference'];activeRun:RunRef|null}):{refs:RunRef[];origins:ReferenceOrigin[]}{
 const reference=override?.candidateReference??state.candidateReference;
 const active=override?override.activeRun:state.conversation.activeRun;
 const proposed=[...new Map((reference?.runs??(active?[active]:[])).map(r=>[`${r.runId}\0${r.runVersionId}`,asRef(r)])).values()];
 // A catalog-only legacy reference has no saved turn origin; the comparison picker resolves it.
 const isCatalog=(ref:RunRef)=>reference?.catalogRefs?.some(item=>sameRef(item,ref));
 const refs=proposed.filter(ref=>isCatalog(ref)||reference?.v2Origins?.some(o=>sameRef(o.ref,ref))||
  state.conversation.turns.some(t=>!['v2','v3'].includes(String(t.answerSnapshot.implementationId))&&t.answerRunRefs.some(r=>sameRef(r,ref))));
 const origins=refs.map(ref=>{
  const explicit=reference?.v2Origins?.find(o=>sameRef(o.ref,ref));
  if(explicit)return {ref,kind:'candidate_group' as const,...explicit.source};
  if(isCatalog(ref))return {ref,kind:'catalog_tag' as const,turnId:null,groupId:null};
  const turn=state.conversation.turns.slice().reverse().find(t=>!['v2','v3'].includes(String(t.answerSnapshot.implementationId))&&t.answerRunRefs.some(r=>sameRef(r,ref)));
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
