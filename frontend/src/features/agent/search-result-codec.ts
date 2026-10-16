import type {RunRef,RunSummary} from 'agent';
import type {SearchObjective,SearchResult} from './agent-contract';

export interface CompactSearchResult extends Omit<SearchResult,'objectiveResults'> {
 searchResultVersion:2;
 runsByVersion:Record<string,RunSummary>;
 commonRunRefs:RunRef[];
 objectiveResults:{objective:SearchObjective;candidateRefs:RunRef[];allConstraintsGuaranteed:boolean}[];
}

/** Read-only presentation adapter. Never replace/resave the original server snapshot. */
export function expandSearchResult(result:CompactSearchResult):SearchResult {
 const evaluations=new Map((result.candidateEvaluations??[]).map(entry=>[entry.runVersionId,entry]));
 function candidate(ref:RunRef) {
  const run=result.runsByVersion[ref.runVersionId];
  if(!run||run.runId!==ref.runId||run.runVersionId!==ref.runVersionId)throw new Error('Invalid saved search reference');
  return {run,evaluations:evaluations.get(ref.runVersionId)?.evaluations??[],matchPercent:evaluations.get(ref.runVersionId)?.matchPercent};
 }
 const common=result.commonRunRefs.map(candidate);
 return {...result,candidates:common.map(entry=>entry.run),commonCandidates:common,
  objectiveResults:result.objectiveResults.map(group=>({...group,candidates:group.candidateRefs.map(candidate)}))};
}
