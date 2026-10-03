// v12.3.1: preserved pure implementation; only IIFE/module boundaries changed.
import * as data from './defaults.js';

const CONDITION_KEYS = ['pressure', 'sourcePower', 'biasPower'];
const OUTPUT_METRICS = ['ionFlux', 'meanIonEnergy', 'iedWidth'];
const SUPPORTED_METRICS = [...CONDITION_KEYS, ...OUTPUT_METRICS];
const EXPECTED_UNITS = {
  pressure: 'mTorr',
  sourcePower: 'W',
  biasPower: 'W',
  ionFlux: '10¹⁸ m⁻²s⁻¹',
  meanIonEnergy: 'eV',
  iedWidth: 'eV',
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function metricValue(run, metric) {
  return CONDITION_KEYS.includes(metric) ? run[metric] : run.metrics[metric];
}

function baseReverseQuery(text) {
  return {
    id: `QUERY-${Date.now()}`,
    originalText: text || '',
    analysisType: 'REVERSE',
    processMode: 'RUN_SEARCH',
    originalValues: {},
    normalizedConditions: {},
    constraints: [],
    goals: [],
    confirmed: false,
    modified: false,
  };
}

function parseProcessConditions(text) {
  const raw = String(text || '');
  const conditions = {};
  const originalValues = {};
  const pressure = raw.match(/(?:pressure|압력)\s*(?:[:=은는이가을를]?\s*)?(\d+(?:\.\d+)?)\s*(mTorr|Torr)?/i);
  if (pressure) {
    const originalValue = Number(pressure[1]);
    const originalUnit = pressure[2] || 'mTorr';
    const normalizedValue = /^torr$/i.test(originalUnit) ? originalValue * 1000 : originalValue;
    conditions.pressure = normalizedValue;
    originalValues.pressure = {
      value: originalValue,
      unit: originalUnit,
      normalizedValue,
      normalizedUnit: 'mTorr',
    };
  }
  [
    ['sourcePower', /(?:source\s*power|source|소스(?:\s*(?:power|파워|전력))?)\s*(?:[:=은는이가을를]?\s*)?(\d+(?:\.\d+)?)/i],
    ['biasPower', /(?:bias\s*power|bias|바이어스(?:\s*(?:power|파워|전력))?)\s*(?:[:=은는이가을를]?\s*)?(\d+(?:\.\d+)?)/i],
  ].forEach(([key, pattern]) => {
    const match = raw.match(pattern);
    if (!match) return;
    conditions[key] = Number(match[1]);
    originalValues[key] = { value: Number(match[1]), unit: 'W', normalizedValue: Number(match[1]), normalizedUnit: 'W' };
  });
  return { conditions, originalValues };
}

function buildForwardRequest(inputConditions, originalText, originalValues = {}) {
  const conditions = Object.fromEntries(CONDITION_KEYS.flatMap((key) => {
    const value = Number(inputConditions && inputConditions[key]);
    return Number.isFinite(value) ? [[key, value]] : [];
  }));
  return {
    id: `QUERY-${Date.now()}`,
    originalText: String(originalText || '').trim(),
    analysisType: 'FORWARD',
    processMode: 'CONDITION_LOOKUP',
    conditions,
    originalValues: clone(originalValues),
    missingConditions: CONDITION_KEYS.filter((key) => !Number.isFinite(conditions[key])),
    constraints: Object.entries(conditions).map(([metric, value]) => ({
      metric, operator: 'EQUAL', value, unit: EXPECTED_UNITS[metric],
    })),
    goals: [],
    confirmed: false,
    modified: false,
  };
}

function classifyAnalysisRequest(text) {
  const raw = String(text || '').trim();
  const parsedConditions = parseProcessConditions(raw);
  const conditions = parsedConditions.conditions;
  const goalIntent = /(최대(?:화)?|최소(?:화)?|높(?:은|게|이고|이면서)?|낮(?:은|게|이고|이면서)?|좁(?:은|게)?|넓(?:은|게)?|목표|후보|추천|탐색|찾(?:아|기|아줘)?)/i.test(raw);
  const forwardIntent = /(정방향|결과|조회|확인|what\s*happens|forward)/i.test(raw);

  if (!goalIntent && (forwardIntent || Object.keys(conditions).length > 0)) {
    return buildForwardRequest(conditions, raw, parsedConditions.originalValues);
  }

  const query = classifyQuery(raw, 'reverse-balanced');
  query.originalText = raw;
  Object.entries(conditions).forEach(([metric, value]) => {
    const existing = query.constraints.find((constraint) => constraint.metric === metric);
    const operator = metric === 'pressure' && /(이하|미만|상한|최대)/.test(raw) ? 'MAX' : 'EQUAL';
    if (existing) {
      existing.value = value;
      existing.operator = operator;
    } else {
      query.constraints.push({ metric, operator, value, unit: EXPECTED_UNITS[metric] });
    }
    query.originalValues[metric] = {
      ...(parsedConditions.originalValues[metric] || { value, unit: EXPECTED_UNITS[metric] }),
      operator,
    };
  });
  return query;
}

function classifyQuery(text, presetId) {
  const preset = data && data.queryPresets.find((item) => item.id === presetId);
  if (preset && preset.query) {
    const query = clone(preset.query);
    query.originalText = text || query.originalText;
    if (query.analysisType === 'REVERSE') query.processMode = 'RUN_SEARCH';
    query.confirmed = false;
    query.modified = false;
    return query;
  }

  const raw = String(text || '').trim();
  const lower = raw.toLowerCase();
  const forwardIntent = /(정방향|결과|예측|what happens|forward)/i.test(raw) && !/(최대|최소|추천|탐색)/.test(raw);
  if (forwardIntent) {
    return {
      id: `QUERY-${Date.now()}`,
      originalText: raw,
      analysisType: 'FORWARD',
      processMode: 'CONDITION_LOOKUP',
      originalValues: {},
      normalizedConditions: {},
      constraints: [],
      goals: [],
      confirmed: false,
      modified: false,
    };
  }

  const query = baseReverseQuery(raw);
  const pressure = lower.match(/(?:pressure|압력)[^\d]*(\d+(?:\.\d+)?)\s*(mtorr|torr)?/i);
  if (pressure) {
    const value = Number(pressure[1]);
    const unit = pressure[2] || 'mTorr';
    query.originalValues.pressure = { value, unit, operator: 'MAX' };
    query.normalizedConditions.pressureMax = value;
    query.constraints.push({ metric: 'pressure', operator: 'MAX', value, unit });
  }
  if (/(flux|플럭스)/i.test(raw)) query.goals.push({ metric: 'ionFlux', direction: 'MAX', unit: EXPECTED_UNITS.ionFlux, label: 'Ion Flux 최대화' });
  if (/(ied width|폭)/i.test(raw)) query.goals.push({ metric: 'iedWidth', direction: 'MIN', unit: 'eV', label: 'IED Width 최소화' });
  query.processMode = 'RUN_SEARCH';
  return query;
}

function validateQuery(input) {
  const query = clone(input || {});
  const errors = [];
  const warnings = [];

  if (!['REVERSE', 'FORWARD'].includes(query.analysisType)) {
    errors.push({ field: 'analysisType', code: 'UNSUPPORTED_ANALYSIS', message: '분석 유형을 확인해 주세요.' });
  }

  const constraints = Array.isArray(query.constraints) ? query.constraints : [];
  const goals = Array.isArray(query.goals) ? query.goals : [];
  const objectives = Array.isArray(query.objectives) ? query.objectives : [];
  query.constraints = constraints;
  query.goals = goals;
  query.objectives = objectives;

  constraints.forEach((constraint, index) => {
    const field = `constraints.${index}`;
    if (!SUPPORTED_METRICS.includes(constraint.metric)) {
      errors.push({ field: `${field}.metric`, code: 'UNSUPPORTED_METRIC', message: '지원하지 않는 제약 지표입니다.' });
      return;
    }
    if (constraint.unit !== EXPECTED_UNITS[constraint.metric]) {
      errors.push({ field: `${field}.unit`, code: 'INVALID_UNIT', message: `${constraint.metric} 단위는 ${EXPECTED_UNITS[constraint.metric]}여야 합니다.` });
    }
    if (constraint.operator === 'RANGE' && Number(constraint.min) > Number(constraint.max)) {
      errors.push({ field: `${field}.range`, code: 'INVERTED_RANGE', message: '최솟값은 최댓값보다 클 수 없습니다.' });
    }
    if (constraint.operator !== 'RANGE' && !Number.isFinite(Number(constraint.value))) {
      errors.push({ field: `${field}.value`, code: 'INVALID_NUMBER', message: '숫자 값을 입력해 주세요.' });
    }
  });

  goals.forEach((goal, index) => {
    const field = `goals.${index}`;
    if (!OUTPUT_METRICS.includes(goal.metric)) {
      errors.push({ field: `${field}.metric`, code: 'UNSUPPORTED_METRIC', message: '지원하지 않는 목표 지표입니다.' });
      return;
    }
    if (goal.unit !== EXPECTED_UNITS[goal.metric]) {
      errors.push({ field: `${field}.unit`, code: 'INVALID_UNIT', message: `${goal.metric} 단위는 ${EXPECTED_UNITS[goal.metric]}여야 합니다.` });
    }
    if (goal.direction === 'TARGET_RANGE' && Number(goal.min) > Number(goal.max)) {
      errors.push({ field: `${field}.range`, code: 'INVERTED_RANGE', message: '목표 범위의 최솟값은 최댓값보다 클 수 없습니다.' });
    }
  });

  objectives.forEach((objective, index) => {
    const field = `objectives.${index}`;
    if (!OUTPUT_METRICS.includes(objective.metric)) {
      errors.push({ field: `${field}.metric`, code: 'UNSUPPORTED_METRIC', message: '지원하지 않는 목표 지표입니다.' });
      return;
    }
    if (!['MIN', 'MAX', 'RANGE'].includes(objective.operator)) {
      errors.push({ field: `${field}.operator`, code: 'UNSUPPORTED_OPERATOR', message: '지원하지 않는 목표 연산자입니다.' });
    }
    if (objective.unit !== EXPECTED_UNITS[objective.metric]) {
      errors.push({ field: `${field}.unit`, code: 'INVALID_UNIT', message: `${objective.metric} 단위는 ${EXPECTED_UNITS[objective.metric]}여야 합니다.` });
    }
    if (objective.operator === 'RANGE') {
      if (!Number.isFinite(Number(objective.min)) || !Number.isFinite(Number(objective.max)) || Number(objective.min) > Number(objective.max)) {
        errors.push({ field: `${field}.range`, code: 'INVERTED_RANGE', message: '목표 범위의 최솟값은 최댓값보다 클 수 없습니다.' });
      }
    } else if (!Number.isFinite(Number(objective.value))) {
      errors.push({ field: `${field}.value`, code: 'INVALID_NUMBER', message: '숫자 값을 입력해 주세요.' });
    }
  });

  if (query.analysisType === 'REVERSE') query.processMode = 'RUN_SEARCH';
  if (query.modified) {
    query.confirmed = false;
    warnings.push({ field: 'confirmed', code: 'RECONFIRM_REQUIRED', message: '수정한 구조화 조건을 다시 확인해 주세요.' });
  }

  query.normalizedConditions = query.normalizedConditions || {};
  constraints.forEach((constraint) => {
    if (constraint.metric === 'pressure' && constraint.operator === 'MAX') query.normalizedConditions.pressureMax = Number(constraint.value);
  });

  return { ok: errors.length === 0, errors, warnings, normalizedQuery: query };
}

function isUsableRun(run) {
  return run && run.qualityStatus === 'VERIFIED' && run.convergenceStatus === 'CONVERGED' && run.catalogStatus === 'READY';
}

function checkRule(value, rule) {
  if (rule.operator === 'MAX') return value <= Number(rule.value);
  if (rule.operator === 'MIN') return value >= Number(rule.value);
  if (rule.operator === 'EQUAL') return value === Number(rule.value);
  if (rule.operator === 'RANGE') return value >= Number(rule.min) && value <= Number(rule.max);
  return false;
}

function constraintViolations(run, query) {
  const rules = [...query.constraints];
  query.goals.filter((goal) => goal.direction === 'TARGET_RANGE').forEach((goal) => {
    rules.push({ ...goal, operator: 'RANGE' });
  });
  return rules.flatMap((rule) => {
    const actual = metricValue(run, rule.metric);
    if (checkRule(actual, rule)) return [];
    const nearest = rule.operator === 'RANGE'
      ? (actual < rule.min ? Number(rule.min) : Number(rule.max))
      : Number(rule.value);
    return [{
      metric: rule.metric,
      actual,
      required: rule.operator === 'RANGE' ? `${rule.min}–${rule.max}` : `${rule.operator} ${rule.value}`,
      delta: Math.round((actual - nearest) * 1000) / 1000,
      unit: rule.unit,
    }];
  });
}

function rankForGoal(runs, goal) {
  const sorted = [...runs].sort((a, b) => {
    const av = metricValue(a, goal.metric);
    const bv = metricValue(b, goal.metric);
    const presentationDelta = (Number(b.presentationScore) || 0) - (Number(a.presentationScore) || 0);
    if (goal.direction === 'MAX') return bv - av || presentationDelta;
    if (goal.direction === 'MIN') return av - bv || presentationDelta;
    // A target range is pass/fail evidence, not a claim that its midpoint is physically optimal.
    return presentationDelta;
  });
  return sorted;
}

function safePercent(delta, denominator) {
  const base = Math.abs(Number(denominator));
  return Number.isFinite(delta) && base > 0 ? (delta / base) * 100 : null;
}

function stableDelta(value) {
  return Number.isFinite(value) ? Math.round(value * 1e6) / 1e6 : value;
}

function evaluateObjective(run, objective, baselineRun = null) {
  const actual = metricValue(run, objective.metric);
  const baselineValue = baselineRun ? metricValue(baselineRun, objective.metric) : null;
  const baselineDelta = Number.isFinite(actual) && Number.isFinite(baselineValue) ? actual - baselineValue : null;
  const baselinePercentDelta = baselineDelta === null ? null : safePercent(baselineDelta, baselineValue);
  let satisfied = false;
  let boundaryDelta = null;
  let percentDelta = null;
  let rangeStatus = null;
  let targetLabel = '';

  if (objective.operator === 'MIN') {
    const boundary = Number(objective.value);
    satisfied = Number.isFinite(actual) && actual >= boundary;
    boundaryDelta = Number.isFinite(actual) ? stableDelta(actual - boundary) : null;
    percentDelta = boundaryDelta === null ? null : safePercent(boundaryDelta, boundary);
    targetLabel = `≥ ${boundary}`;
  } else if (objective.operator === 'MAX') {
    const boundary = Number(objective.value);
    satisfied = Number.isFinite(actual) && actual <= boundary;
    boundaryDelta = Number.isFinite(actual) ? stableDelta(boundary - actual) : null;
    percentDelta = boundaryDelta === null ? null : safePercent(boundaryDelta, boundary);
    targetLabel = `≤ ${boundary}`;
  } else if (objective.operator === 'RANGE') {
    const min = Number(objective.min);
    const max = Number(objective.max);
    targetLabel = `${min}–${max}`;
    satisfied = Number.isFinite(actual) && actual >= min && actual <= max;
    if (satisfied) {
      rangeStatus = 'IN_RANGE';
    } else if (Number.isFinite(actual)) {
      const boundary = actual < min ? min : max;
      boundaryDelta = stableDelta(-Math.abs(actual - boundary));
      percentDelta = safePercent(boundaryDelta, boundary);
      rangeStatus = actual < min ? 'BELOW_RANGE' : 'ABOVE_RANGE';
    } else {
      rangeStatus = 'UNAVAILABLE';
    }
  }

  return {
    objectiveId: objective.id,
    metric: objective.metric,
    operator: objective.operator,
    unit: objective.unit,
    actual,
    satisfied,
    targetLabel,
    boundaryDelta,
    percentDelta,
    rangeStatus,
    baselineDelta,
    baselinePercentDelta,
  };
}

function objectiveDistance(evaluation, objective) {
  if (objective.operator === 'RANGE') {
    if (!Number.isFinite(evaluation.actual)) return Infinity;
    const midpoint = (Number(objective.min) + Number(objective.max)) / 2;
    return evaluation.satisfied ? Math.abs(evaluation.actual - midpoint) : Math.abs(evaluation.boundaryDelta);
  }
  if (!Number.isFinite(evaluation.actual)) return Infinity;
  return objective.operator === 'MIN' ? -evaluation.actual : evaluation.actual;
}

function rankForObjective(entries, objective) {
  return [...entries].sort((a, b) => {
    const ae = a.evaluations.find((item) => item.objectiveId === objective.id);
    const be = b.evaluations.find((item) => item.objectiveId === objective.id);
    if (ae.satisfied !== be.satisfied) return ae.satisfied ? -1 : 1;
    const delta = objectiveDistance(ae, objective) - objectiveDistance(be, objective);
    return delta || (Number(b.run.presentationScore) || 0) - (Number(a.run.presentationScore) || 0) || a.run.runId.localeCompare(b.run.runId);
  });
}

function objectiveCloseness(evaluation, objective) {
  if (!evaluation || !Number.isFinite(evaluation.actual)) return 0;
  const reference = objective.operator === 'RANGE'
    ? (Number(objective.min) + Number(objective.max)) / 2
    : Number(objective.value);
  if (!Number.isFinite(reference)) return 0;
  if (reference === 0) return evaluation.actual === 0 ? 100 : 0;
  return Math.max(0, 100 - (Math.abs(evaluation.actual - reference) / Math.abs(reference)) * 100);
}

function entryCloseness(entry, objectives) {
  if (!objectives.length) return 0;
  return objectives.reduce((sum, objective) => {
    const evaluation = entry.evaluations.find((item) => item.objectiveId === objective.id);
    return sum + objectiveCloseness(evaluation, objective);
  }, 0) / objectives.length;
}

function compareGoalRuns(a, b, goals) {
  for (const goal of goals) {
    const av = metricValue(a, goal.metric);
    const bv = metricValue(b, goal.metric);
    const delta = goal.direction === 'MIN' ? av - bv : bv - av;
    if (delta) return delta;
  }
  return 0;
}

function rankCombinedEntries(entries, goals, objectives) {
  return [...entries].sort((a, b) => {
    const goalDelta = compareGoalRuns(a.run, b.run, goals);
    if (goalDelta) return goalDelta;
    const closenessDelta = entryCloseness(b, objectives) - entryCloseness(a, objectives);
    return closenessDelta
      || (Number(b.run.presentationScore) || 0) - (Number(a.run.presentationScore) || 0)
      || a.run.runId.localeCompare(b.run.runId);
  });
}

function searchReverse(input, runs) {
  const validation = validateQuery(input);
  if (!validation.ok) return { status: 'INVALID', errors: validation.errors, goalResults: [], nearMatches: [], representativeCandidates: [] };
  const query = validation.normalizedQuery;
  const usable = runs.filter(isUsableRun);
  const matches = usable.filter((run) => constraintViolations(run, query).length === 0);

  const nearMatches = matches.length === 0
    ? usable
      .map((run) => ({ run, violations: constraintViolations(run, query) }))
      .filter((item) => item.violations.length > 0)
      .sort((a, b) => a.violations.reduce((sum, v) => sum + Math.abs(v.delta), 0) - b.violations.reduce((sum, v) => sum + Math.abs(v.delta), 0))
      .slice(0, 3)
    : [];

  const explicitObjectives = query.objectives || [];
  const goals = query.goals || [];
  const baselineRun = input.baselineRunId ? runs.find((run) => run.runId === input.baselineRunId) || null : null;
  const allEntries = usable.map((run) => ({
    run,
    evaluations: explicitObjectives.map((objective) => evaluateObjective(run, objective, baselineRun)),
  }));
  const matchIds = new Set(matches.map((run) => run.runId));
  const combinedCandidates = rankCombinedEntries(
    allEntries.filter((entry) => matchIds.has(entry.run.runId)),
    goals,
    explicitObjectives,
  );
  const objectiveResults = explicitObjectives.map((objective) => ({
    objective,
    candidates: rankForObjective(
      allEntries.filter((entry) => {
        const evaluation = entry.evaluations.find((item) => item.objectiveId === objective.id);
        return evaluation && evaluation.satisfied;
      }),
      objective,
    ),
  }));
  const goalResults = goals.map((goal) => ({ goal, candidates: rankForGoal(usable, goal) }));
  const representativeCandidates = combinedCandidates.map((entry) => entry.run);

  return {
    status: representativeCandidates.length ? 'MATCH' : 'NO_MATCH',
    processMode: 'RUN_SEARCH',
    totalCount: representativeCandidates.length,
    allMatches: representativeCandidates,
    objectives: explicitObjectives,
    goals,
    objectiveResults,
    goalResults,
    commonCandidates: combinedCandidates,
    commonRunIds: representativeCandidates.map((run) => run.runId),
    nearMatches,
    representativeCandidates,
    commonRecommendation: representativeCandidates[0] || null,
  };
}

function conditionDeltas(run, conditions) {
  return Object.fromEntries(CONDITION_KEYS.map((key) => [key, run[key] - Number(conditions[key])]));
}

function searchForward(conditions, runs) {
  const requestedConditions = Object.fromEntries(CONDITION_KEYS.map((key) => [key, Number(conditions[key])]));
  const usable = runs.filter(isUsableRun);
  const exact = usable.find((run) => CONDITION_KEYS.every((key) => run[key] === Number(conditions[key])));
  if (exact) return { status: 'EXACT', run: exact, deltas: conditionDeltas(exact, conditions), requestedConditions };
  if (usable.length === 0) return { status: 'NO_DATA', run: null, deltas: null, requestedConditions };

  const scales = { pressure: 10, sourcePower: 500, biasPower: 1000 };
  const ranked = usable.map((run) => ({
    run,
    distance: CONDITION_KEYS.reduce((sum, key) => sum + Math.pow((run[key] - Number(conditions[key])) / scales[key], 2), 0),
  })).sort((a, b) => a.distance - b.distance);
  return { status: 'NEAREST_ONLY', run: ranked[0].run, deltas: conditionDeltas(ranked[0].run, conditions), requestedConditions };
}

function buildControlledComparison(targetRun, runs) {
  return runs
    .filter((run) => isUsableRun(run) && run.runId !== targetRun.runId)
    .filter((run) => CONDITION_KEYS.filter((key) => run[key] !== targetRun[key]).length === 1)
    .sort((a, b) => {
      const aDelta = CONDITION_KEYS.reduce((sum, key) => sum + Math.abs(a[key] - targetRun[key]), 0);
      const bDelta = CONDITION_KEYS.reduce((sum, key) => sum + Math.abs(b[key] - targetRun[key]), 0);
      return aDelta - bDelta;
    })
    .slice(0, 4);
}

export { buildForwardRequest, classifyAnalysisRequest, classifyQuery, validateQuery, evaluateObjective, searchReverse, searchForward, buildControlledComparison };
