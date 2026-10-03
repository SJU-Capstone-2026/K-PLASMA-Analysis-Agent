import {test} from 'node:test';
import assert from 'node:assert/strict';
import {compareRuns} from './compare-runs.mjs';

const original = [{runId:'ARTIFICIAL',registeredAt:'2026-09-17T00:20:00Z',metrics:{ionFlux:1},analysis:{trace:[{x:1,y:2},{x:2,y:3}]},sourceFiles:['sample.txt']}];
const actual = () => [{...structuredClone(original[0]),runVersionId:'version-artificial'}];
test('full exact comparison accepts only the extra immutable identity',()=>assert.equal(compareRuns(original,actual()).mismatches,0));
test('graph numeric difference cannot be hidden by tolerance',()=>{const runs=actual();runs[0].analysis.trace[1].y+=1e-12;assert.equal(compareRuns(original,runs).mismatches,1);});
test('shape, order, missing fields and unexpected physical fields fail',()=>{for(const mutation of [r=>r.analysis.trace.reverse(),r=>r.analysis.trace.pop(),r=>delete r.metrics,r=>r.metrics.invented=0]){const runs=actual();mutation(runs[0]);assert.ok(compareRuns(original,runs).mismatches>0);}});
test('frozen registration timestamp is included in the comparison',()=>{const runs=actual();runs[0].registeredAt='2026-10-03T00:00:00Z';assert.equal(compareRuns(original,runs).mismatches,1);});
test('timestamp offset notation denotes the same exact instant',()=>{const runs=actual();runs[0].registeredAt='2026-09-17T09:20:00+09:00';assert.equal(compareRuns(original,runs).mismatches,0);});
test('timestamp comparison retains submillisecond precision',()=>{const runs=actual();runs[0].registeredAt='2026-09-17T00:20:00.000000001Z';assert.equal(compareRuns(original,runs).mismatches,1);});
test('Run count and duplicate display identity are checked',()=>{assert.ok(compareRuns(original,[]).mismatches>0);assert.ok(compareRuns(original,[...actual(),...actual()]).mismatches>0);});
