/* eslint-disable @typescript-eslint/no-unused-vars -- Preserve original omission destructuring and storage catch bindings. */
// v12.3.1: preserved pure implementation; only IIFE/module boundaries changed.


const STORAGE_KEY = 'kplasma.prototype.decisionMemory.v1';
const DECISIONS = ['ADOPT', 'HOLD', 'REJECT'];
const EXPERIMENT_DECISIONS = ['ADOPT', 'HOLD', 'REJECT', 'ALTERNATIVE', 'COMPARISON'];
let sequence = 0;

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function fail(message, field) {
  const error = new Error(message);
  error.field = field;
  throw error;
}

function createRecord(input, runs, now = new Date()) {
  const catalog = Array.isArray(runs) ? runs : [];
  const runIds = new Set(catalog.map((run) => run.runId));
  const targetRunId = String(input.targetRunId || '').trim();
  const comparedRunIds = Array.isArray(input.comparedRunIds) ? input.comparedRunIds.map(String) : [];
  const comment = String(input.comment || '').trim();
  const decision = String(input.decision || '').trim();
  const analysisType = ['FORWARD', 'REVERSE', 'EXPLANATION'].includes(input.analysisType) ? input.analysisType : 'REVERSE';

  if (!comment) fail('판단 근거 코멘트를 입력해 주세요.', 'comment');
  if (!DECISIONS.includes(decision)) fail('채택·보류·제외 중 하나의 결정을 선택해 주세요.', 'decision');
  if (!runIds.has(targetRunId)) fail('존재하지 않는 대상 Run입니다.', 'targetRunId');
  if (comparedRunIds.includes(targetRunId)) fail('대상 Run은 비교 Run으로 다시 선택할 수 없습니다.', 'comparedRunIds');
  if (new Set(comparedRunIds).size !== comparedRunIds.length) fail('비교 Run을 중복 선택할 수 없습니다.', 'comparedRunIds');
  if (comparedRunIds.length > 2) fail('비교 Run은 최대 2개까지 선택할 수 있습니다.', 'comparedRunIds');
  if (comparedRunIds.some((runId) => !runIds.has(runId))) fail('존재하지 않는 비교 Run이 포함되어 있습니다.', 'comparedRunIds');
  if (analysisType === 'EXPLANATION' && comparedRunIds.length !== 1) {
    fail('변화 설명 기록에는 검증된 기준 Run 1개가 필요합니다.', 'comparedRunIds');
  }

  const runSnapshots = [targetRunId, ...comparedRunIds].map((runId) => {
    const run = catalog.find((item) => item.runId === runId);
    return {
      runId,
      conditions: {
        pressure: run.pressure,
        sourcePower: run.sourcePower,
        biasPower: run.biasPower,
      },
      metrics: clone(run.metrics || {}),
      supportingMetrics: {
        electronDensity: run.analysis && run.analysis.electronDensity,
        electronTemperature: run.analysis && run.analysis.electronTemperature,
      },
    };
  });

  sequence += 1;
  const stamp = now.toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  return Object.freeze({
    reviewId: `REV-${stamp}-${String(sequence).padStart(3, '0')}`,
    targetRunId,
    comparedRunIds: [...comparedRunIds],
    decision,
    comment,
    authorName: String(input.authorName || '').trim() || '익명',
    createdAt: now.toISOString(),
    analysisType,
    processMode: String(input.processMode || 'GOAL_RECOMMENDATION'),
    constraints: clone(Array.isArray(input.constraints) ? input.constraints : []),
    goals: clone(Array.isArray(input.goals) ? input.goals : []),
    queryText: String(input.queryText || '').trim(),
    evidenceKinds: clone(Array.isArray(input.evidenceKinds) ? input.evidenceKinds : []),
    limitations: clone(Array.isArray(input.limitations) ? input.limitations : []),
    runSnapshots,
  });
}

function createExperimentRecord(input, runs, now = new Date()) {
  const catalog = Array.isArray(runs) ? runs : [];
  const runMap = new Map(catalog.map((run) => [run.runId, run]));
  const candidates = Array.isArray(input.candidates) ? input.candidates : [];
  if (!candidates.length) fail('후보를 1개 이상 선택해 주세요.', 'candidates');
  if (input.selectionMode === 'SINGLE_ADOPT') {
    if (candidates.filter((candidate) => candidate.decision === 'ADOPT').length !== 1) fail('채택할 Run을 1개 선택해 주세요.', 'candidates');
    if (candidates.length > 3) fail('추가 후보는 최대 2개까지 선택할 수 있습니다.', 'candidates');
    if (candidates.some((candidate) => candidate.decision !== 'ADOPT' && !['HOLD', 'REJECT'].includes(candidate.decision))) {
      fail('추가 후보는 보류 또는 반려로 판단해 주세요.', 'candidates');
    }
  } else if (candidates.length > 3) fail('후보는 최대 3개까지 기록할 수 있습니다.', 'candidates');
  const runIds = candidates.map((candidate) => String(candidate.runId || '').trim());
  if (new Set(runIds).size !== runIds.length) fail('후보 Run을 중복 선택할 수 없습니다.', 'candidates');
  if (runIds.some((runId) => !runMap.has(runId))) fail('존재하지 않는 후보 Run이 포함되어 있습니다.', 'candidates');
  if (candidates.some((candidate) => !EXPERIMENT_DECISIONS.includes(candidate.decision))) {
    fail('후보별 판단을 선택해 주세요.', 'candidates');
  }
  const overallComment = String(input.overallComment || '').trim();
  if (!overallComment) fail('공통 실험 코멘트를 입력해 주세요.', 'overallComment');

  sequence += 1;
  const stamp = now.toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  const orderedCandidates = input.selectionMode === 'SINGLE_ADOPT' ? [...candidates].sort((a, b) => Number(b.decision === 'ADOPT') - Number(a.decision === 'ADOPT')) : candidates;
  const snapshots = orderedCandidates.map((candidate) => {
    const run = runMap.get(String(candidate.runId));
    return {
      runId: run.runId,
      decision: candidate.decision,
      note: String(candidate.note || '').trim(),
      conditions: {
        pressure: run.pressure,
        sourcePower: run.sourcePower,
        biasPower: run.biasPower,
      },
      metrics: clone(run.metrics || {}),
      objectiveEvaluations: clone(Array.isArray(candidate.objectiveEvaluations) ? candidate.objectiveEvaluations : []),
    };
  });
  const id = `EXP-${stamp}-${String(sequence).padStart(3, '0')}`;
  return Object.freeze({
    id,
    reviewId: id,
    version: 2,
    createdAt: now.toISOString(),
    question: String(input.question || '').trim(),
    objectives: clone(Array.isArray(input.objectives) ? input.objectives : []),
    overallComment,
    authorName: String(input.authorName || '').trim() || '익명',
    candidates: snapshots,
    targetRunId: snapshots[0].runId,
    comparedRunIds: snapshots.slice(1).map((candidate) => candidate.runId),
    decision: snapshots[0].decision,
    comment: overallComment,
    analysisType: 'REVERSE',
    processMode: 'GOAL_RECOMMENDATION',
    goals: clone(Array.isArray(input.objectives) ? input.objectives : []),
    queryText: String(input.question || '').trim(),
  });
}

function load(storage) {
  try {
    const raw = storage && storage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function save(storage, records) {
  if (!storage || typeof storage.setItem !== 'function') throw new Error('로컬 저장소를 사용할 수 없습니다.');
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(Array.isArray(records) ? records : []));
    return records;
  } catch (error) {
    const wrapped = new Error('브라우저 로컬 저장소에 기록하지 못했습니다. 다시 시도해 주세요.');
    wrapped.cause = error;
    throw wrapped;
  }
}

function add(storage, record) {
  const records = load(storage);
  const next = [...records, clone(record)];
  save(storage, next);
  return next;
}

function saveExperimentRecord(storage, record) {
  if (!record || record.version !== 2 || !Array.isArray(record.candidates)) {
    fail('유효한 실험 기록이 아닙니다.', 'record');
  }
  return add(storage, record);
}

function reset(storage) {
  try {
    if (storage && typeof storage.removeItem === 'function') storage.removeItem(STORAGE_KEY);
  } catch (error) {
    // Reset is best-effort in browsers that block storage.
  }
  return [];
}

function filter(records, filters = {}) {
  const author = String(filters.author || '').trim().toLocaleLowerCase('ko-KR');
  const runId = String(filters.runId || '').trim().toLocaleUpperCase('en-US');
  return (Array.isArray(records) ? records : []).filter((record) => {
    if (filters.decision && (record.version === 2 ? !(record.candidates || []).some((candidate)=>candidate.decision===filters.decision) : record.decision !== filters.decision)) return false;
    if (author && !String(record.authorName || '').toLocaleLowerCase('ko-KR').includes(author)) return false;
    if (filters.processMode && record.processMode !== filters.processMode) return false;
    if (filters.metric && !(record.goals || record.objectives || []).some((goal) => goal.metric === filters.metric)) return false;
    const recordRunIds = record.version === 2 ? (record.candidates || []).map((candidate) => candidate.runId) : [record.targetRunId, ...(record.comparedRunIds || [])];
    if (runId && !recordRunIds.includes(runId)) return false;
    return true;
  });
}

export { STORAGE_KEY, DECISIONS, EXPERIMENT_DECISIONS, createRecord, createExperimentRecord, load, save, add, saveExperimentRecord, reset, filter };
