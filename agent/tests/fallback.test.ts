import { describe, expect, it } from 'vitest';
import { executeFallback, engine, explanationEngine, conversationStore, decisionMemory } from '../src';
import { toRunSummary, type AgentContext, type FullRun, type RunRef, type DecisionRecord } from '../src/contracts';
import { syntheticRun } from './support/synthetic-runs';
const ref = (run: FullRun): RunRef => ({ runId: run.runId, runVersionId: run.runVersionId });
function run(id: string, energy: number, source = 11): FullRun {
  const value = syntheticRun();
  return { ...value, runId: id, runVersionId: `version-${id}`, sourcePower: source, metrics: { ...value.metrics, meanIonEnergy: energy } };
}
function context(runs: FullRun[], references: FullRun[] = []): AgentContext {
  return { candidateRunsLatest: runs.map(toRunSummary), referenceRunsByVersion: new Map(references.map(r => [r.runVersionId, r])), decisionRecords: [],
    hydrateFullRun: async reference => { const full = [...runs, ...references].find(r => r.runVersionId === reference.runVersionId); if (!full) throw new Error('missing version'); return full; } };
}
const request = (text: string) => ({ text, candidateReferences: [] });
describe('preserved fallback', () => {
  it('keeps exact, nearest and no-data forward branches', async () => {
    const ctx = context([run('A', 17)]);
    expect((await executeFallback(request('Pressure 3 Source 11 Bias 7 결과 보여줘'), ctx)).status).toBe('EXACT');
    expect((await executeFallback(request('Pressure 4 Source 11 Bias 7 결과 보여줘'), ctx)).status).toBe('NEAREST_ONLY');
    expect((await executeFallback(request('Pressure 3 Source 11 Bias 7 결과 보여줘'), context([]))).status).toBe('NO_DATA');
  });
  it('returns every matching Run in original order without a six-card cutoff', async () => {
    const runs = Array.from({ length: 9 }, (_, i) => run(`R${i}`, 20 + i));
    const answer = await executeFallback(request('Mean Ion Energy 20–28 eV인 실제 Run 후보를 모두 찾아줘'), context(runs));
    expect(answer.status).toBe('MATCH');
    expect(answer.candidates.map(r => r.runId)).toEqual(['R4', 'R3', 'R5', 'R2', 'R6', 'R1', 'R7', 'R0', 'R8']);
  });
  it('preserves invalid and no-match reverse statuses', async () => {
    expect((await executeFallback(request('Mean Ion Energy 30–20 eV 후보 찾아줘'), context([run('A', 17)]))).status).toBe('INVALID');
    expect((await executeFallback(request('Mean Ion Energy 40–50 eV 후보 찾아줘'), context([run('A', 17)]))).status).toBe('NO_MATCH');
    expect(engine.searchReverse({ constraints: [{ metric: 'unknown', operator: 'MIN', value: 1 }], goals: [], confirmed: true }, []).status).toBe('INVALID');
  });
  it('requires missing forward conditions instead of guessing', async () => {
    const answer = await executeFallback(request('Pressure 3 결과 보여줘'), context([]));
    expect(answer.intent).toBe('CLARIFICATION'); expect(answer.status).toBe('NEEDS_INPUT');
    expect(answer.answerSnapshot.missingConditions).toEqual(['sourcePower', 'biasPower']);
  });
  it('uses historical baseline energy plus 5 through 20 as mandatory bounds', async () => {
    const old = run('BASE', 17); const latest = { ...run('BASE', 70), runVersionId: 'new-base' };
    const ctx = context([latest, run('LOW', 21), run('MIN', 22), run('MID', 30), run('MAX', 37), run('HIGH', 38)], [old]);
    const answer = await executeFallback({ ...request('Energy를 조금 더 높여줘'), baseline: ref(old) }, ctx);
    expect(answer.candidates.map(r => r.runId)).toEqual(['MID', 'MAX', 'MIN']);
    expect(answer.usedRunRefs).toContainEqual(ref(old));
    expect(answer.answerSnapshot.constraints).toEqual([{ metric: 'meanIonEnergy', operator: 'RANGE', min: 22, max: 37, unit: 'eV' }]);
  });
  it('hydrates both comparison runs before producing observed explanation and omits graphs in snapshots', async () => {
    const old = run('BASE', 17, 22); const before = run('BEFORE', 10, 11);
    const ctx = context([before, { ...run('BASE', 70, 22), runVersionId: 'new-base' }], [old]);
    const answer = await executeFallback({ ...request('왜 이런 결과인가요?'), baseline: ref(old) }, ctx);
    expect(answer.status).toBe('READY');
    expect(answer.usedRunRefs).toEqual(expect.arrayContaining([ref(before), ref(old)]));
    const observations = answer.explanation?.observations as unknown as { key: string; after: number }[];
    expect(observations.find(o => o.key === 'meanIonEnergy')?.after).toBe(17);
    expect(JSON.stringify(answer.answerSnapshot)).not.toMatch(/iedDistribution|residualTrace|sourceRun|"points"|"values"/);
  });
  it('propagates hydration failure instead of declaring graphs unavailable', async () => {
    const base = run('BASE', 17, 22);
    const ctx = context([run('BEFORE', 10, 11), base], [base]);
    ctx.hydrateFullRun = async () => { throw new Error('version load failed'); };
    await expect(executeFallback({ ...request('왜 이런 결과인가요?'), baseline: ref(run('BASE', 17, 22)) }, ctx)).rejects.toThrow('version load failed');
  });
  it('preserves missing pair and uncontrolled comparison statuses', async () => {
    const ctx = context([run('A', 17), { ...run('B', 18, 22), pressure: 4 }]);
    expect((await executeFallback({ ...request('Source power 변화 이유 설명'), clarification: { comparison: { beforeRunId: 'A', afterRunId: 'MISSING' } } }, ctx)).status).toBe('NO_PAIR');
    expect((await executeFallback({ ...request('Source power 변화 이유 설명'), clarification: { comparison: { beforeRunId: 'A', afterRunId: 'B' } } }, ctx)).status).toBe('NOT_CONTROLLED');
    expect(explanationEngine.buildControlledExplanation({ comparison: {} }, [], []).status).toBe('NO_PAIR');
  });
  it('preserves pure conversation UI and review validation functions', () => {
    const empty = conversationStore.createEmpty();
    const next = conversationStore.appendTurn(empty, { question: 'test', intent: 'CLARIFICATION', answerSnapshot: { runIds: [] } });
    const patched = conversationStore.updateTurnUi(next, next.turns[0].id, { collapsed: true });
    expect(patched.turns[0].ui.collapsed).toBe(true); expect(empty.turns).toEqual([]);
    expect(() => decisionMemory.createRecord({ targetRunId: 'A', decision: 'ADOPT', comment: '' }, [run('A', 17)])).toThrow();
  });
});

describe('version and record reuse boundaries', () => {
  it('returns latest candidate versions while keeping historical baseline comparisons', async () => {
    const old = run('BASE', 17); const latest = { ...run('BASE', 30), runVersionId: 'new-base' };
    const answer = await executeFallback({ ...request('Energy를 조금 더 높여줘'), baseline: ref(old) }, context([latest], [old]));
    expect(answer.candidates).toEqual([ref(latest)]);
    expect(answer.usedRunRefs).toEqual([ref(old), ref(latest)]);
  });
  it('uses historical run for contextual full-results questions', async () => {
    const old = run('BASE', 17); const latest = { ...run('BASE', 70), runVersionId: 'new-base' };
    const answer = await executeFallback({ ...request('이 Run 전체 결과 보여줘'), baseline: ref(old) }, context([latest], [old]));
    expect(answer.candidates).toEqual([ref(old)]);
    expect(((answer.answerSnapshot.runSummary as { metrics: { meanIonEnergy: number } }).metrics.meanIonEnergy)).toBe(17);
  });
  it('attributes cost rejection to original Run ID across versions and preserves undo', async () => {
    const old = run('A', 17); const latest = { ...run('A', 19), runVersionId: 'new-a' }; const b = run('B', 21);
    const ctx = context([latest, b], [old]);
    const record = decisionMemory.createRecord({ targetRunId: 'A', decision: 'REJECT', comment: '비용이 높아서 반려', analysisType: 'REVERSE' }, [old]);
    ctx.decisionRecords = [{ ...record, targetRunRef: ref(old), comparedRunRefs: [], runSnapshots: record.runSnapshots.map(snapshot => ({ ...snapshot, ...ref(old) })) }] as unknown as DecisionRecord[];
    const input = { ...request('이 후보들 중 비용 반려 1건 이상 제외해줘'), candidateReferences: [ref(old), ref(b)] };
    const answer = await executeFallback(input, ctx);
    expect(answer.intent).toBe('RECORD_REUSE'); expect(answer.candidates).toEqual([ref(b)]);
    expect((answer.answerSnapshot.memoryResult as { excluded: { runId: string }[] }).excluded.map(r => r.runId)).toEqual(['A']);
    const undo = await executeFallback({ ...input, clarification: { undo: true } }, ctx);
    expect(undo.candidates).toEqual([ref(old), ref(b)]);
    expect(undo.answerSnapshot.canUndo).toBe(false);
  });
  it('requires a threshold and refuses unrelated rejection reasons', async () => {
    const a = run('A', 17); const ctx = context([a]);
    const pending = await executeFallback({ ...request('비용 반려가 많은 후보 제외해줘'), candidateReferences: [ref(a)] }, ctx);
    expect(pending.status).toBe('NEEDS_INPUT'); expect(pending.answerSnapshot.pendingThreshold).toBe(true);
    const other = await executeFallback({ ...request('성능 때문에 반려된 후보 제외해줘'), candidateReferences: [ref(a)] }, ctx);
    expect(other.status).toBe('NEEDS_INPUT'); expect(other.candidates).toEqual([]);
  });
  it.each([
    ['pending threshold', {}],
    ['invalid threshold notice', { threshold: 0 }],
  ])('preserves historical selected candidates through %s persistence and retry', async (_label, clarification) => {
    const oldA = run('A', 17); const oldB = run('B', 21);
    const latestA = { ...run('A', 70), runVersionId: 'new-a' };
    const latestB = { ...run('B', 80), runVersionId: 'new-b' };
    const text = '비용 반려가 많은 후보 제외해줘';
    const answer = await executeFallback({ ...request(text), candidateReferences: [ref(oldA), ref(oldB)], clarification },
      context([latestA, latestB], [oldA, oldB]));
    expect(answer.status).toBe('NEEDS_INPUT'); expect(answer.candidates).toEqual([]);
    expect(answer.usedRunRefs).toEqual([ref(oldA), ref(oldB)]);
    expect(answer.answerSnapshot.reference).toEqual({ kind: '후보 집합', ids: ['A', 'B'] });
    const persisted = JSON.parse(JSON.stringify({ answerSnapshot: answer.answerSnapshot, usedRunRefs: answer.usedRunRefs }));
    expect(JSON.stringify(persisted.answerSnapshot)).not.toMatch(/iedDistribution|residualTrace|sourceRun|"points"|"values"/);
    const retry = await executeFallback({ ...request(persisted.answerSnapshot.memoryRequest.text), candidateReferences: persisted.usedRunRefs,
      clarification: { threshold: 1 } }, context([{ ...latestA, runVersionId: 'newest-a' }, { ...latestB, runVersionId: 'newest-b' }], [oldA, oldB]));
    expect(retry.status).toBe('READY');
    expect(retry.candidates).toEqual([ref(oldA), ref(oldB)]);
  });
  it('keeps latest numeric search candidates and historical selected snapshot context together', async () => {
    const old = run('A', 17); const latest = { ...run('A', 70), runVersionId: 'new-a' };
    const answer = await executeFallback({ ...request('Flux가 13 이상인 후보를 찾되, 비용 때문에 반려된 건 제외해줘'), candidateReferences: [ref(old)] },
      context([latest], [old]));
    expect(answer.status).toBe('READY');
    expect(answer.candidates).toEqual([ref(latest)]);
    expect(answer.usedRunRefs).toEqual([ref(old), ref(latest)]);
  });
  it('rejects a hydration response from the wrong immutable version', async () => {
    const a = run('A', 17); const ctx = context([]); ctx.hydrateFullRun = async () => a;
    await expect(executeFallback({ ...request('이 Run 결과 보여줘'), baseline: { ...ref(a), runVersionId: 'wrong' } }, ctx)).rejects.toThrow('requested version');
  });
});
