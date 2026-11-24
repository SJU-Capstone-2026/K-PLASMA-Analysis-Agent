import {test} from 'node:test';
import assert from 'node:assert/strict';
import {runtimeWorkerSpec,graphVersionArgument} from './runtime.mjs';
import {browserLaunchOptions} from './flow-browser.mjs';
import {get,terminalBatch} from '../reference/runtime.mjs';
import {createServer} from 'node:http';

async function withServer(handler,run){
  const server=createServer(handler);
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{return await run(`http://127.0.0.1:${server.address().port}`);}
  finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
}

test('version flags preserve v2 default and reject ambiguous or unknown identities',()=>{
  assert.equal(graphVersionArgument([]),'v2');
  for(const version of ['v2','v2_localLLM']){
    assert.equal(graphVersionArgument(['--graph-version',version]),version);
    assert.equal(graphVersionArgument([`--graph-version=${version}`]),version);
  }
  for(const args of [['--graph-version'],['--graph-version','local'],['--graph-version','v1'],['--graph-version','v3'],
    ['--graph-version=v2','--graph-version','v2_localLLM']])assert.throws(()=>graphVersionArgument(args),/graph version/);
});

test('scripted and live variant workers use their own production namespace',()=>{
  assert.deepEqual(runtimeWorkerSpec('v2_localLLM',{live:false}),
    ['agent/python/tests/v2_local_llm/runtime_worker.py']);
  assert.deepEqual(runtimeWorkerSpec('v2_localLLM',{live:true,envFile:'/private/local.env'}),
    ['-m','kplasma_agent.v2_local_llm.worker','--env-file','/private/local.env']);
  assert.throws(()=>runtimeWorkerSpec('v1',{live:false}),/graph version/);
  assert.throws(()=>runtimeWorkerSpec('v3',{live:false}),/graph version/);
  assert.deepEqual(runtimeWorkerSpec('v2',{live:false}),['agent/python/tests/runtime_v2_worker.py']);
  assert.throws(()=>runtimeWorkerSpec('local',{live:false}),/graph version/);
  assert.throws(()=>runtimeWorkerSpec('v2_localLLM',{live:true}),/env file/);
});

test('both graph versions launch a fresh browser without session state',()=>{
  for(const graphVersion of ['v2','v2_localLLM']){
    assert.deepEqual(browserLaunchOptions({graphVersion,headless:true}),{headless:true});
  }
  assert.throws(()=>browserLaunchOptions({graphVersion:'local'}),/graph version/);
});

test('reference read helpers preserve callers without origin headers',async()=>{
  await withServer((request,response)=>{
    assert.equal(request.headers.cookie,undefined);
    assert.equal(request.headers.origin,undefined);
    response.writeHead(200,{'Content-Type':'application/json'}).end(JSON.stringify({status:'SUCCESS'}));
  },async api=>{
    assert.deepEqual(await get(api,'/api/workspace'),{status:'SUCCESS'});
    assert.equal((await terminalBatch(api,'synthetic')).status,'SUCCESS');
  });
});
