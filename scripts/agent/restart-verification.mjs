// Restart only the Spring process owned by this isolated synthetic environment.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {once} from 'node:events';
import {createWriteStream} from 'node:fs';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {repo,sleep} from '../reference/runtime.mjs';
import {startV1Environment} from './runtime.mjs';

const output=join(repo,'agent/python/.runtime',`restart-${Date.now()}`);
await mkdir(output,{recursive:true});
const summary={data:'artificial-only',model:'test-v1-deterministic',status:'FAIL',passed:[]};
let environment,worker;
async function request(path,body,key=randomUUID()){
  const response=await fetch(new URL(path,environment.url),body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)});
  assert.ok(response.ok,`Test API returned HTTP ${response.status}`);
  return response.json();
}
async function terminal(id){
  for(let count=0;count<180;count++){
    const state=await request(`/api/agent/requests/${id}`);
    if(['COMPLETED','NEEDS_INPUT','FAILED','CANCELLED'].includes(state.status))return state;
    await sleep(500);
  }
  throw new Error('Request did not reach a terminal/waiting state.');
}
async function submit(text){return request('/api/agent/requests',{text,stateToken:(await request('/api/workspace')).stateToken});}
try{
  environment=await startV1Environment(output,'none');
  const runs=await request('/api/runs');
  const run=runs.find(item=>item.catalogStatus==='READY'&&item.qualityStatus==='VERIFIED'&&item.convergenceStatus==='CONVERGED');
  assert.ok(run);
  const question=`압력 ${run.pressure} mTorr, 소스 ${run.sourcePower} W, 바이어스 ${run.biasPower} W 결과를 보여줘`;
  const queued=await submit(question);
  assert.equal(queued.status,'QUEUED');
  await environment.restartBackend();
  assert.deepEqual(await request(`/api/agent/requests/${queued.requestId}`),queued);
  assert.equal((await request('/api/workspace')).activeAgentRequest.requestId,queued.requestId);
  const metadata=JSON.parse(await readFile(environment.connection,'utf8'));
  const env={...process.env,AGENT_BACKEND_URL:environment.url,AGENT_WORKER_TOKEN:metadata.workerToken,PYTHONPATH:join(repo,'agent/python/src')};
  delete env.OPENAI_API_KEY;
  worker=spawn(join(repo,'agent/python/.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python'),['agent/python/tests/runtime_worker.py','--connection',environment.connection],{cwd:repo,env,stdio:['ignore','pipe','pipe']});
  const log=createWriteStream(join(output,'worker.log'));worker.stdout.pipe(log,{end:false});worker.stderr.pipe(log,{end:false});worker.on('exit',()=>log.end());
  const first=await terminal(queued.requestId);
  assert.equal(first.status,'COMPLETED');
  const selected=first.answerSnapshot.result.selectedRun;
  assert.equal(selected.runId,run.runId);assert.equal(selected.runVersionId,run.runVersionId);
  assert.deepEqual(selected.metrics,run.metrics);
  summary.passed.push('queued_request_and_exact_result_after_server_restart');

  const missing=`압력 ${run.pressure} mTorr, 소스 ${run.sourcePower} W의 결과를 보여줘`;
  const accepted=await submit(missing);
  const pending=await terminal(accepted.requestId);
  assert.equal(pending.status,'NEEDS_INPUT');assert.ok(pending.pendingInput);
  await environment.restartBackend();
  assert.deepEqual(await request(`/api/agent/requests/${accepted.requestId}`),pending);
  const resumeKey=randomUUID();
  const body={expectedRequestRevision:pending.requestRevision,pendingInputId:pending.pendingInput.id,input:{text:`${run.biasPower} W`}};
  await request(`/api/agent/requests/${accepted.requestId}/resume`,body,resumeKey);
  const completed=await terminal(accepted.requestId);
  assert.equal(completed.status,'COMPLETED');assert.equal(completed.inputEvents.length,1);
  assert.deepEqual(completed.inputEvents[0].input,body.input);
  assert.equal(completed.answerSnapshot.result.selectedRun.runVersionId,run.runVersionId);
  assert.deepEqual(completed.answerSnapshot.result.selectedRun.metrics,run.metrics);
  summary.passed.push('pending_checkpoint_and_short_reply_after_server_restart');

  const before=await request('/api/workspace');
  assert.equal(before.conversation.turns.length,2);
  assert.equal(new Set(before.conversation.turns.map(turn=>turn.id)).size,2);
  await environment.restartBackend();
  const replay=await request(`/api/agent/requests/${accepted.requestId}/resume`,body,resumeKey);
  assert.deepEqual(replay,completed);
  const after=await request('/api/workspace');
  assert.deepEqual(after.conversation,before.conversation);
  assert.deepEqual(after.stateToken,before.stateToken);
  summary.passed.push('completed_answer_and_idempotent_resume_after_server_restart');

  const other=runs.find(item=>item.runVersionId!==run.runVersionId&&item.catalogStatus==='READY'&&item.qualityStatus==='VERIFIED'&&item.convergenceStatus==='CONVERGED');assert.ok(other);
  const comparison=await submit(`${run.runId}를 기준으로 ${other.runId}의 평균 이온 에너지와 이온 플럭스를 비교해줘`);
  const picker=await terminal(comparison.requestId);assert.equal(picker.status,'NEEDS_INPUT');assert.equal(picker.pendingInput.type,'run_selection');
  const optionsPath=`/api/agent/requests/${comparison.requestId}/run-options?pendingInputId=${encodeURIComponent(picker.pendingInput.id)}`;
  const options=await request(optionsPath);
  const exited=new Promise(resolve=>worker.once('exit',resolve));worker.kill('SIGKILL');await exited;
  await environment.restartBackend();
  assert.deepEqual(await request(optionsPath),options);assert.deepEqual(await request(`/api/agent/requests/${comparison.requestId}`),picker);
  worker=spawn(join(repo,'agent/python/.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python'),['agent/python/tests/runtime_worker.py','--connection',environment.connection],{cwd:repo,env,stdio:['ignore','pipe','pipe']});
  const resumedLog=createWriteStream(join(output,'resumed-worker.log'));worker.stdout.pipe(resumedLog,{end:false});worker.stderr.pipe(resumedLog,{end:false});worker.on('exit',()=>resumedLog.end());
  const chosen=[run,other].map(run=>options.options.find(option=>option.ref.runVersionId===run.runVersionId));assert.ok(chosen.every(Boolean));
  await request(`/api/agent/requests/${comparison.requestId}/resume`,{expectedRequestRevision:picker.requestRevision,pendingInputId:picker.pendingInput.id,input:{type:'run_selection',runKeys:chosen.map(option=>option.key),baselineKey:chosen[0].key}});
  const compared=await terminal(comparison.requestId);assert.equal(compared.status,'COMPLETED');
  assert.equal(compared.answerSnapshot.schemaVersion,2);assert.deepEqual(compared.answerSnapshot.usedRunRefs,chosen.map(option=>option.ref));
  summary.passed.push('frozen_picker_and_native_comparison_after_worker_kill_and_server_restart');
  summary.status='PASS';
}catch(error){summary.error=error instanceof Error?error.message:'Restart verification failed';process.exitCode=1;}
finally{
  if(worker&&worker.exitCode===null&&worker.signalCode===null){const stopped=once(worker,'exit');worker.kill('SIGTERM');await Promise.race([stopped,sleep(5000)]);if(worker.exitCode===null&&worker.signalCode===null){worker.kill('SIGKILL');await stopped;}}
  await environment?.close();
  await writeFile(join(output,'summary.json'),JSON.stringify(summary,null,2));
  console.log(`Graph v1 restart: ${summary.status}, ${summary.passed.length}/4 scenarios. Local evidence: ${output}`);
  if(summary.error)console.error('Restart verification failed; inspect the local synthetic summary.');
}
