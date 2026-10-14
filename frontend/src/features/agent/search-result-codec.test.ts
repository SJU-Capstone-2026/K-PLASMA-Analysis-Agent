import {expect,test} from 'vitest';
import {syntheticRun} from '../../test/runs';
import {snapshotResult,searchGroups,type SearchResult} from './agent-contract';
import {expandSearchResult,type CompactSearchResult} from './search-result-codec';

const run=syntheticRun(600);
const ref={runId:run.runId,runVersionId:run.runVersionId};
const result:CompactSearchResult={kind:'reverse_search',resultStatus:'MATCH',searchResultVersion:2,runsByVersion:{[run.runVersionId]:run},commonRunRefs:[ref],objectiveResults:[],candidateEvaluations:[{...ref,evaluations:[],matchPercent:100}]};

test('decodes compact references without mutating the saved snapshot',()=>{
 const original=JSON.stringify(result);const snapshot={result:JSON.parse(original)};
 const decoded=snapshotResult<SearchResult>(snapshot);
 expect(searchGroups(decoded)[0].runs).toEqual([run]);
 expect(snapshotResult(snapshot)).toBe(decoded);
 expect(JSON.stringify(snapshot.result)).toBe(original);
});
test('rejects a forged or missing version reference',()=>{
 expect(()=>expandSearchResult({...result,commonRunRefs:[{...ref,runId:'OTHER'}]})).toThrow();
 expect(()=>expandSearchResult({...result,runsByVersion:{}})).toThrow();
});
test('empty new search has no nearest group; historical snapshots remain readable',()=>{
 const empty={...result,resultStatus:'NO_MATCH',commonRunRefs:[],runsByVersion:{},candidateEvaluations:[]};
 expect(searchGroups(expandSearchResult(empty))).toHaveLength(1);
 const old={kind:'reverse_search',resultStatus:'NO_MATCH',commonCandidates:[],nearMisses:[{run,violations:[]}]};
 expect(searchGroups(snapshotResult<SearchResult>({result:JSON.parse(JSON.stringify(old))}))).toHaveLength(2);
});
