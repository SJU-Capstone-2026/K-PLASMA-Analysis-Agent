import {test} from 'node:test';
import assert from 'node:assert/strict';
import {runtimeWorkerSpec,graphVersionArgument,createLocalSession} from './runtime.mjs';
import {browserLaunchOptions} from './flow-browser.mjs';
import {get,terminalBatch,upload} from '../reference/runtime.mjs';
import {createServer} from 'node:http';
import {mkdtemp,readFile,writeFile,stat,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

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

test('local real browser requires a session rather than an OS filter claim',()=>{
  assert.deepEqual(browserLaunchOptions({graphVersion:'v2',headless:true}),{headless:true});
  for(const extra of [{},{ready:true},{verified:true,executablePath:'/Applications/Chrome.app'}]){
    assert.throws(()=>browserLaunchOptions({graphVersion:'v2_localLLM',...extra}),/LOCAL_SESSION_REQUIRED/);
  }
  assert.deepEqual(browserLaunchOptions({graphVersion:'v2_localLLM',headless:true,
    sessionCookie:'KPLASMA_LOCAL_SESSION='+'A'.repeat(43)}),{headless:true});
});

test('synthetic session authenticates uploads and reads and refreshes after server restart',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'kplasma-session-unit-'));
  const uiOrigin='http://127.0.0.1:5173',bootstrap='synthetic-bootstrap-token';
  let consumed=false,cookie='A'.repeat(43);
  const paths=[];
  try{
    const folder=join(directory,'artificial');await mkdir(folder);
    await writeFile(join(folder,'artificial.txt'),'synthetic-only');
    await withServer(async(request,response)=>{
      paths.push(request.url);
      assert.equal(request.headers.origin,uiOrigin);
      assert.equal(request.headers['sec-fetch-site'],'same-site');
      if(request.url==='/api/local-runtime/session'){
        assert.equal(request.method,'POST');
        assert.equal(request.headers['x-local-bootstrap'],bootstrap);
        if(consumed){response.writeHead(401).end();return;}
        consumed=true;
        response.writeHead(204,{'Set-Cookie':`KPLASMA_LOCAL_SESSION=${cookie}; Path=/api; HttpOnly; SameSite=Strict`}).end();
        return;
      }
      assert.equal(request.headers.cookie,`KPLASMA_LOCAL_SESSION=${cookie}`);
      assert.equal(request.headers['x-local-bootstrap'],undefined);
      for await(const _ of request){ /* drain the synthetic multipart upload */ }
      const body=request.method==='POST'?{batchId:'synthetic'}:
        request.url.startsWith('/api/import-batches/')?{status:'SUCCESS'}:{ready:true};
      response.writeHead(request.method==='POST'?202:200,{'Content-Type':'application/json'}).end(JSON.stringify(body));
    },async api=>{
      const connection=join(directory,'connection.json'),metadata={graphVersion:'v2_localLLM'};
      const session=createLocalSession({api,uiOrigin,bootstrapToken:bootstrap,connection,metadata});
      const headers=session.headers;
      await session.refresh();
      assert.equal((await stat(connection)).mode&0o777,0o600);
      assert.equal(JSON.parse(await readFile(connection,'utf8')).uiOrigin,uiOrigin);
      assert.equal(JSON.parse(await readFile(connection,'utf8')).bootstrapToken,undefined);
      const imported=await upload(api,folder,'FOLDER',undefined,headers);
      assert.equal((await terminalBatch(api,imported.batchId,headers)).status,'SUCCESS');
      assert.deepEqual(await get(api,'/api/workspace',headers),{ready:true});
      await assert.rejects(session.refresh(),/LOCAL_SESSION_BOOTSTRAP_FAILED/);
      consumed=false;cookie='B'.repeat(43); // JVM restart discards the old session and one-time consumption.
      await session.refresh();
      assert.equal(session.headers,headers);
      assert.equal(headers.Cookie,`KPLASMA_LOCAL_SESSION=${cookie}`);
      assert.equal(JSON.parse(await readFile(connection,'utf8')).sessionCookie,headers.Cookie);
      assert.deepEqual(await get(api,'/api/workspace',headers),{ready:true});
      assert.equal(paths[0],'/api/local-runtime/session');
      assert.equal(paths.filter(path=>path==='/api/local-runtime/session').length,3);
    });
  }finally{await rm(directory,{recursive:true,force:true});}
});

test('reference read helpers preserve callers without session headers',async()=>{
  await withServer((request,response)=>{
    assert.equal(request.headers.cookie,undefined);
    assert.equal(request.headers.origin,undefined);
    response.writeHead(200,{'Content-Type':'application/json'}).end(JSON.stringify({status:'SUCCESS'}));
  },async api=>{
    assert.deepEqual(await get(api,'/api/workspace'),{status:'SUCCESS'});
    assert.equal((await terminalBatch(api,'synthetic')).status,'SUCCESS');
  });
});

test('session bootstrap refuses a cookie missing HttpOnly before creating connection metadata',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'kplasma-session-reject-'));
  try{
    await withServer((request,response)=>{
      response.writeHead(204,{'Set-Cookie':`KPLASMA_LOCAL_SESSION=${'A'.repeat(43)}; Path=/api; SameSite=Strict`}).end();
    },async api=>{
      const connection=join(directory,'connection.json');
      const session=createLocalSession({api,uiOrigin:'http://127.0.0.1:5173',bootstrapToken:'synthetic-bootstrap',connection,metadata:{}});
      await assert.rejects(session.refresh(),/LOCAL_SESSION_COOKIE_INVALID/);
      assert.deepEqual(session.headers,{});
      await assert.rejects(readFile(connection),{code:'ENOENT'});
    });
  }finally{await rm(directory,{recursive:true,force:true});}
});
