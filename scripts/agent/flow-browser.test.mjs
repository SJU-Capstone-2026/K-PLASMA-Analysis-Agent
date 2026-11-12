import {test} from 'node:test';
import assert from 'node:assert/strict';
import {planRunSelection,comparisonInput} from './flow-browser.mjs';

const options = [{key:'R1',ref:{runId:'ART-A',runVersionId:'synthetic-a'},selectable:true},
  {key:'R2',ref:{runId:'ART-B',runVersionId:'synthetic-b'},selectable:true}];

test('HITL selects the configured Runs and baseline from actual options',()=>{
  const result=planRunSelection(options,{minSelections:2,maxSelections:2,baselineRequired:true},
    {runIds:['ART-A','ART-B'],baselineRunId:'ART-B'});
  assert.deepEqual(result.input,{type:'run_selection',runKeys:['R1','R2'],baselineKey:'R2'});
});

test('HITL rejects unavailable or ambiguous Runs instead of picking a replacement',()=>{
  const expected={runIds:['ART-A','ART-B']};
  assert.throws(()=>planRunSelection([{...options[0],selectable:false},options[1]],{},expected),/unavailable/);
  assert.throws(()=>planRunSelection([...options,options[0]],{},expected),/ambiguous/);
  assert.throws(()=>planRunSelection(options,{minSelections:3},expected),/outside/);
});

test('comparison input respects offered axes and exact Run labels',()=>{
  const pending={fields:['baselineKey','trendAxis'],allowedRunKeys:['R1','R2'],allowedTrendAxes:['pressure'],
    options:[{label:'ART-A',input:{baselineKey:'R1'}},{label:'ART-B',input:{baselineKey:'R2'}}]};
  assert.deepEqual(comparisonInput(pending,{baselineRunId:'ART-B',trendAxis:'pressure'},new Map()),
    {type:'comparison_options',baselineKey:'R2',trendAxis:'pressure'});
  assert.throws(()=>comparisonInput(pending,{baselineRunId:'ART-B',trendAxis:'sourcePower'},new Map()),/unavailable/);
  assert.throws(()=>comparisonInput(pending,{baselineRunId:'ART-BB',trendAxis:'pressure'},new Map()),/missing/);
});
