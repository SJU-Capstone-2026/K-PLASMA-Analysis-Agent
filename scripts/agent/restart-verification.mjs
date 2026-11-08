// Restart only the processes owned by this isolated synthetic environment.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {once} from 'node:events';
import {createWriteStream} from 'node:fs';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {repo, sleep} from '../reference/runtime.mjs';
import {startV1Environment} from './runtime.mjs';

const output = await mkdtemp(join(tmpdir(), 'kplasma-v2-restart-'));
const summary = {data: 'artificial-only', model: 'test-v2-scripted', status: 'FAIL', passed: []};
let environment, worker;
async function request(path, body, key = randomUUID()) {
  const response = await fetch(new URL(path, environment.url), body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': key}, body: JSON.stringify(body),
  });
  assert.ok(response.ok, `Test API returned HTTP ${response.status}`);
  return response.json();
}
async function terminal(id) {
  for (let count = 0; count < 180; count++) {
    const state = await request(`/api/agent/requests/${id}`);
    if (['COMPLETED', 'NEEDS_INPUT', 'FAILED', 'CANCELLED'].includes(state.status)) return state;
    await sleep(500);
  }
  throw new Error('Request did not reach a terminal/waiting state.');
}
async function submit(text) {
  return request('/api/agent/requests', {text, graphVersion: 'v2', stateToken: (await request('/api/workspace')).stateToken});
}
async function startWorker() {
  const metadata = JSON.parse(await readFile(environment.connection, 'utf8'));
  const env = {...process.env, PHOENIX_COLLECTOR_ENDPOINT: '', PHOENIX_API_KEY: '',
    AGENT_BACKEND_URL: environment.url, AGENT_WORKER_TOKEN: metadata.workerToken,
    PYTHONPATH: join(repo, 'agent/python/src')};
  delete env.OPENAI_API_KEY;
  const python = process.env.KPLASMA_VERIFY_PYTHON ?? join(repo, 'agent/python/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  worker = spawn(python, ['agent/python/tests/runtime_v2_worker.py', '--connection', environment.connection], {cwd: repo, env, stdio: ['ignore', 'pipe', 'pipe']});
  const log = createWriteStream(join(output, 'worker.log'), {flags: 'a'});
  worker.stdout.pipe(log, {end: false}); worker.stderr.pipe(log, {end: false}); worker.on('exit', () => log.end());
  await once(worker, 'spawn');
}
async function stopWorker(signal) {
  if (!worker || worker.exitCode !== null || worker.signalCode !== null) return;
  const stopped = once(worker, 'exit'); worker.kill(signal);
  await Promise.race([stopped, sleep(5000)]);
  if (worker.exitCode === null && worker.signalCode === null) {worker.kill('SIGKILL'); await stopped;}
}
function searchIds(state) {
  assert.equal(state.graphVersion, 'v2');
  assert.equal(state.answerSnapshot.implementationId, 'v2');
  assert.equal(state.answerSnapshot.executionStatus, 'COMPLETE');
  assert.equal(state.answerSnapshot.hasIncompleteWork, false);
  const steps = state.answerSnapshot.stepResults;
  return steps.findLast(step => step.outputs.toolResult?.kind === 'reverse_search').outputs.toolResult.commonRunIds.toSorted();
}
try {
  environment = await startV1Environment(output, 'none');
  const runs = (await request('/api/runs')).filter(run => run.catalogStatus === 'READY').sort((a, b) => a.metrics.ionFlux - b.metrics.ionFlux);
  assert.equal(runs.length, 3);
  const queued = await submit('이온 플럭스가 40보다 높은 실제 Run을 모두 찾아줘.');
  assert.equal(queued.status, 'QUEUED');
  await environment.restartBackend();
  assert.deepEqual(await request(`/api/agent/requests/${queued.requestId}`), queued);
  assert.equal((await request('/api/workspace')).activeAgentRequest.requestId, queued.requestId);
  await startWorker();
  const first = await terminal(queued.requestId); assert.equal(first.status, 'COMPLETED');
  assert.deepEqual(searchIds(first), runs.filter(run => run.metrics.ionFlux > 40).map(run => run.runId).toSorted());
  summary.passed.push('queued_v2_request_and_strict_search_after_server_restart');

  const accepted = await submit('비교할 두 Run은 내가 고를게. 선택한 두 Run 모두보다 이온 플럭스가 높은 후보를 찾아줘.');
  const pending = await terminal(accepted.requestId);
  assert.equal(pending.status, 'NEEDS_INPUT'); assert.equal(pending.pendingInput.type, 'run_selection');
  const optionsPath = `/api/agent/requests/${accepted.requestId}/run-options?pendingInputId=${encodeURIComponent(pending.pendingInput.id)}`;
  const options = await request(optionsPath); assert.equal(options.options.length, 3);
  await stopWorker('SIGKILL'); await environment.restartBackend();
  assert.deepEqual(await request(`/api/agent/requests/${accepted.requestId}`), pending);
  assert.deepEqual(await request(optionsPath), options);
  summary.passed.push('v2_checkpoint_and_frozen_picker_after_worker_and_server_restart');

  const chosen = runs.slice(0, 2).map(run => options.options.find(option => option.ref.runVersionId === run.runVersionId));
  assert.ok(chosen.every(option => option?.selectable));
  const resumeKey = randomUUID();
  const body = {expectedRequestRevision: pending.requestRevision, pendingInputId: pending.pendingInput.id,
    input: {type: 'run_selection', runKeys: chosen.map(option => option.key)}};
  await startWorker();
  await request(`/api/agent/requests/${accepted.requestId}/resume`, body, resumeKey);
  const completed = await terminal(accepted.requestId); assert.equal(completed.status, 'COMPLETED');
  assert.equal(completed.inputEvents.length, 1);
  const comparison = completed.answerSnapshot.stepResults.find(step => step.outputs.toolResult?.kind === 'compare_runs').outputs.toolResult;
  assert.deepEqual(comparison.usedRunRefs, chosen.map(option => option.ref));
  assert.deepEqual(searchIds(completed), runs.filter(run => run.metrics.ionFlux > runs[1].metrics.ionFlux).map(run => run.runId).toSorted());
  assert.equal(completed.executionSummary.activities.filter(activity => activity.code === 'PLAN_REVIEW' && activity.phase === 'started').length, 1);
  summary.passed.push('v2_compare_max_search_resumes_once_with_exact_selected_versions');

  const before = await request('/api/workspace');
  assert.equal(before.conversation.agentGraphVersion, 'v2'); assert.equal(before.conversation.turns.length, 2);
  assert.equal(new Set(before.conversation.turns.map(turn => turn.id)).size, 2);
  await environment.restartBackend();
  assert.deepEqual(await request(`/api/agent/requests/${accepted.requestId}/resume`, body, resumeKey), completed);
  const after = await request('/api/workspace');
  assert.deepEqual(after.conversation, before.conversation); assert.deepEqual(after.stateToken, before.stateToken);
  summary.passed.push('completed_v2_snapshot_and_idempotent_resume_after_server_restart');
  summary.status = 'PASS';
} catch (error) {
  summary.error = error instanceof Error ? error.message : 'Restart verification failed'; process.exitCode = 1;
} finally {
  await stopWorker('SIGTERM'); await environment?.close();
  await writeFile(join(output, 'summary.json'), JSON.stringify(summary, null, 2));
  console.log(`Graph v2 restart: ${summary.status}, ${summary.passed.length}/4 scenarios. Local evidence: ${output}`);
  if (summary.error) console.error('Restart verification failed; inspect the local synthetic summary.');
}
