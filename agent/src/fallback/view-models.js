/* eslint-disable @typescript-eslint/no-unused-vars -- Preserve original omission destructuring and storage catch bindings. */
// v12.3.1: preserved pure implementation; only IIFE/module boundaries changed.
import * as analyzer from './engine.js';
import * as analysisTools from './analysis-engine.js';
const catalog = { runs: [] };


const METRIC_META = {
  pressure: { label: 'Pressure', unit: 'mTorr', digits: 0 },
  sourcePower: { label: 'Source Power', unit: 'W', digits: 0 },
  biasPower: { label: 'Bias Power', unit: 'W', digits: 0 },
  ionFlux: { label: 'Ion Flux', unit: '10¹⁸ m⁻²s⁻¹', digits: 0 },
  meanIonEnergy: { label: 'Mean Ion Energy', unit: 'eV', digits: 0 },
  iedWidth: { label: 'IED Width', unit: 'eV', digits: 0 },
};

const CONCEPT_EXPLANATIONS = Object.freeze({
  meanIonEnergy: Object.freeze({
    key: 'meanIonEnergy',
    eyebrow: 'BASIC CONCEPT',
    title: '평균 이온 에너지는 이온이 표면에 도달할 때 가진 평균적인 충돌 에너지입니다.',
    lead: '쉽게 말하면, 표면에 도착하는 이온 하나하나가 얼마나 강하게 부딪히는지를 나타내는 값입니다.',
    sections: Object.freeze([
      Object.freeze({ title: 'Flux와는 다른 값입니다', text: 'Ion Flux는 일정 시간 동안 표면에 도착하는 이온의 양을 뜻하고, 평균 이온 에너지는 각 이온이 가진 충돌 세기를 뜻합니다. 이온이 많이 와도 한 개의 충돌 에너지는 낮을 수 있습니다.' }),
      Object.freeze({ title: '공정 결과에 영향을 줍니다', text: '에너지가 높아지면 표면 반응이나 물리적 제거가 강해질 수 있지만, 너무 높으면 손상이나 선택성 저하가 커질 수 있습니다.' }),
      Object.freeze({ title: '주로 Bias와 쉬스의 영향을 받습니다', text: '평균 이온 에너지는 바이어스 전력과 전극 앞 쉬스 전위의 영향을 크게 받습니다. 소스 전력과 압력도 플라즈마 상태를 통해 간접적으로 영향을 줄 수 있습니다.' }),
    ]),
    practice: 'Flux는 “얼마나 많이 오는가”, 평균 이온 에너지는 “하나가 얼마나 세게 부딪히는가”로 구분하면 쉽습니다.',
  }),
  ionFlux: Object.freeze({
    key: 'ionFlux', eyebrow: 'BASIC CONCEPT',
    title: 'Ion Flux는 단위 면적과 시간당 표면에 도착하는 이온의 양입니다.',
    lead: '공정 표면으로 공급되는 이온의 수를 나타내므로 반응량과 처리 속도를 이해할 때 먼저 확인하는 값입니다.',
    sections: Object.freeze([
      Object.freeze({ title: '이온의 양을 나타냅니다', text: 'Flux가 높다는 것은 같은 시간에 더 많은 이온이 표면에 도착한다는 뜻입니다. 각 이온의 충돌 세기를 의미하는 에너지와는 구분해야 합니다.' }),
      Object.freeze({ title: '공정 속도와 연결될 수 있습니다', text: '다른 조건이 비슷하면 더 많은 이온 공급은 식각이나 표면 반응 증가와 연결될 수 있습니다. 다만 실제 Etch Rate는 재료와 표면 반응에도 영향을 받습니다.' }),
      Object.freeze({ title: '소스 전력과 밀도의 영향을 받습니다', text: '소스 전력이 입자 생성을 늘리면 플라즈마 밀도와 Flux가 함께 증가할 수 있지만, 압력과 장비 형상에 따라 변화 폭은 달라집니다.' }),
    ]),
    practice: 'Flux는 이온의 “양”, Mean Ion Energy는 이온 한 개의 “충돌 세기”로 읽으면 됩니다.',
  }),
  pressure: Object.freeze({
    key: 'pressure', eyebrow: 'PROCESS PRINCIPLE',
    title: '압력은 입자 충돌 빈도와 표면까지 이동하는 방식을 바꾸는 공정 조건입니다.',
    lead: '압력을 낮추면 평균 자유 행로가 길어져 이온이 이동 중 충돌할 가능성이 줄어드는 방향으로 작용합니다.',
    sections: Object.freeze([
      Object.freeze({ title: '방향성이 좋아질 수 있습니다', text: '충돌이 줄면 이온의 진행 방향이 덜 흐트러져 기판에 더 수직으로 도달할 가능성이 커집니다.' }),
      Object.freeze({ title: '에너지 분포가 달라질 수 있습니다', text: '쉬스 안에서 충돌이 줄어들면 이온이 얻은 에너지를 유지하기 쉬워지고, 에너지 분포가 더 좁아질 수 있습니다.' }),
      Object.freeze({ title: '밀도와 Flux는 함께 확인해야 합니다', text: '너무 낮은 압력에서는 방전 유지와 입자 생성이 어려워질 수 있으므로 방향성만 보고 조건을 결정하면 안 됩니다.' }),
    ]),
    practice: '낮은 압력은 방향성과 에너지 유지에 유리할 수 있지만, 밀도와 방전 안정성을 함께 확인해야 합니다.',
  }),
  plasma: Object.freeze({
    key: 'plasma', eyebrow: 'BASIC CONCEPT',
    title: '플라즈마는 전자와 이온, 중성 입자가 함께 존재하는 활성화된 기체 상태입니다.',
    lead: '공정에서는 전기 에너지를 기체에 전달해 반응성이 높은 입자를 만들고, 이 입자들이 표면 반응을 일으키도록 사용합니다.',
    sections: Object.freeze([
      Object.freeze({ title: '전자와 이온이 함께 있습니다', text: '자유 전자는 기체 입자와 충돌해 이온과 활성종을 만들고, 만들어진 이온은 전기장에 의해 기판 쪽으로 이동할 수 있습니다.' }),
      Object.freeze({ title: '입자의 양과 에너지는 별개입니다', text: '플라즈마 밀도와 Flux는 공급되는 입자의 양에 가깝고, 평균 이온 에너지는 표면에 충돌하는 세기에 가깝습니다.' }),
      Object.freeze({ title: '중간 과정은 직접 보기 어렵습니다', text: '입력 조건과 최종 성능 사이에 밀도, 온도, 쉬스, 표면 반응이 있어 결과만으로 하나의 원인을 확정하기 어렵습니다.' }),
    ]),
    practice: '입력 조건 → 플라즈마 상태 → 표면 상호작용 → 공정 결과의 연결로 나누어 보면 블랙박스를 이해하기 쉽습니다.',
  }),
});

function metricValue(run, metric) {
  return ['pressure', 'sourcePower', 'biasPower'].includes(metric) ? run[metric] : run.metrics[metric];
}

function displayValue(value, digits = 0) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'N/A';
  return Number(value).toLocaleString('ko-KR', { maximumFractionDigits: digits });
}

function metricRow(run, metric) {
  const meta = METRIC_META[metric];
  return { metric, label: meta.label, value: displayValue(metricValue(run, metric), meta.digits), unit: meta.unit };
}

function constraintTargetLabel(constraint) {
  if (constraint.operator === 'RANGE') return `${displayValue(constraint.min, 2)}–${displayValue(constraint.max, 2)} ${constraint.unit}`;
  const operator = { MIN: '≥', MAX: '≤', EQUAL: '=' }[constraint.operator] || constraint.operator;
  return `${operator} ${displayValue(constraint.value, 2)} ${constraint.unit}`;
}

function constraintSatisfied(actual, constraint) {
  if (!Number.isFinite(actual)) return false;
  if (constraint.operator === 'RANGE') return actual >= Number(constraint.min) && actual <= Number(constraint.max);
  if (constraint.operator === 'MIN') return actual >= Number(constraint.value);
  if (constraint.operator === 'MAX') return actual <= Number(constraint.value);
  if (constraint.operator === 'EQUAL') return actual === Number(constraint.value);
  return false;
}

function buildConstraintLookupModel(result, constraints = []) {
  const matches = result && Array.isArray(result.allMatches) ? result.allMatches : [];
  return {
    totalCount: Number(result && result.totalCount) || 0,
    constraints: constraints.map((constraint) => ({
      ...constraint,
      label: `${METRIC_META[constraint.metric].label} ${constraintTargetLabel(constraint)}`,
    })),
    matches: matches.map((run) => ({
      runId: run.runId,
      dataOrigin: 'ACTUAL',
      qualityLabel: run.qualityStatus === 'VERIFIED' ? '검증됨' : '확인 필요',
      convergenceLabel: run.convergenceStatus === 'CONVERGED' ? '수렴 완료' : '수렴 확인 필요',
      conditions: ['pressure', 'sourcePower', 'biasPower'].map((metric) => metricRow(run, metric)),
      metrics: ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => metricRow(run, metric)),
      constraintRows: constraints.map((constraint) => {
        const actual = Number(metricValue(run, constraint.metric));
        return {
          metric: constraint.metric,
          label: METRIC_META[constraint.metric].label,
          actual,
          actualLabel: displayValue(actual, 2),
          unit: constraint.unit,
          targetLabel: constraintTargetLabel(constraint),
          satisfied: constraintSatisfied(actual, constraint),
        };
      }),
      satisfactionLabel: '필수 조건 모두 충족',
      objectiveRows: [],
      actions: [
        { id: 'continue-with-run', label: '이 Run으로 이어서 질문', runId: run.runId },
        { id: 'open-run-detail', label: '실험 자세히 보기', runId: run.runId },
      ],
    })),
  };
}

function buildConstraintLookupDisplayModel(lookup, expanded = false, initialLimit = 6) {
  const matches = lookup && Array.isArray(lookup.matches) ? lookup.matches : [];
  const safeLimit = Math.max(1, Number(initialLimit) || 6);
  const visibleMatches = expanded ? matches : matches.slice(0, safeLimit);
  return {
    visibleMatches,
    totalCount: matches.length,
    hiddenCount: Math.max(0, matches.length - visibleMatches.length),
    expanded: Boolean(expanded),
    canToggle: matches.length > safeLimit,
  };
}

function candidateModel(run, commonId) {
  const actualRun = analysisTools && analysisTools.isActualResultRun(run);
  return {
    runId: run.runId,
    dataOrigin: actualRun ? 'ACTUAL' : 'MOCK',
    score: actualRun ? '실제값' : (Number.isFinite(run.presentationScore) ? `${run.presentationScore}%` : '실험값'),
    scoreValue: actualRun ? null : (Number.isFinite(run.presentationScore) ? run.presentationScore : null),
    isRecommended: run.runId === commonId,
    recommendationLabel: run.runId === commonId ? '균형 추천' : '대안 후보',
    note: run.note,
    qualityLabel: run.qualityStatus === 'VERIFIED' ? '검증됨' : '확인 필요',
    convergenceLabel: run.convergenceStatus === 'CONVERGED' ? '수렴 완료' : '수렴 확인 필요',
    conditions: ['pressure', 'sourcePower', 'biasPower'].map((metric) => metricRow(run, metric)),
    metrics: ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => metricRow(run, metric)),
    sourceRun: run,
  };
}

function signedLabel(value, digits = 2, suffix = '') {
  if (!Number.isFinite(value)) return 'N/A';
  const formatted = Math.abs(value).toLocaleString('ko-KR', { maximumFractionDigits: digits });
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${formatted}${suffix}`;
}

function buildCandidateFitModel(run, objectives = [], baselineRun = null) {
  const evaluations = (objectives || []).map((objective) => analyzer.evaluateObjective(run, objective, baselineRun));
  const objectiveRows = evaluations.map((evaluation, index) => {
    const meta = METRIC_META[evaluation.metric];
    const objective = objectives[index] || {};
    const percentDeltaLabel = evaluation.percentDelta === null
      ? null
      : signedLabel(evaluation.percentDelta, 1, '%');
    const differenceLabel = evaluation.rangeStatus === 'IN_RANGE'
      ? '범위 안'
      : evaluation.boundaryDelta === null
        ? '비교 불가'
        : `${signedLabel(evaluation.boundaryDelta, 2, ` ${evaluation.unit}`)}${percentDeltaLabel ? ` (${percentDeltaLabel})` : ''}`;
    const referenceValue = objective.operator === 'RANGE'
      ? (Number(objective.min) + Number(objective.max)) / 2
      : Number(objective.value);
    const referenceDeltaPercent = Number.isFinite(referenceValue) && Number.isFinite(evaluation.actual)
      ? referenceValue === 0
        ? (evaluation.actual === 0 ? 0 : 100)
        : (Math.abs(evaluation.actual - referenceValue) / Math.abs(referenceValue)) * 100
      : null;
    const matchPercent = referenceDeltaPercent === null
      ? 0
      : Math.round(Math.max(0, 100 - referenceDeltaPercent));
    const referenceLabel = objective.operator === 'RANGE'
      ? `범위 중앙값 ${displayValue(referenceValue, 2)} ${evaluation.unit}`
      : `검색 기준 ${displayValue(referenceValue, 2)} ${evaluation.unit}`;
    return {
      ...evaluation,
      label: meta.label,
      actualLabel: displayValue(evaluation.actual, 2),
      targetLabel: `${evaluation.targetLabel} ${evaluation.unit}`,
      percentDeltaLabel,
      differenceLabel,
      matchPercent,
      referenceValue,
      referenceLabel,
    };
  });
  const baselineRows = baselineRun ? ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => {
    const actual = metricValue(run, metric);
    const baseline = metricValue(baselineRun, metric);
    const delta = Number.isFinite(actual) && Number.isFinite(baseline) ? actual - baseline : null;
    const percent = delta !== null && baseline !== 0 ? (delta / Math.abs(baseline)) * 100 : null;
    return {
      metric,
      label: METRIC_META[metric].label,
      baseline,
      actual,
      delta,
      deltaLabel: delta === null ? '비교 불가' : signedLabel(delta, 2, ` ${METRIC_META[metric].unit}`),
      percentLabel: percent === null ? null : signedLabel(percent, 1, '%'),
    };
  }) : [];
  const satisfiedCount = objectiveRows.filter((row) => row.satisfied).length;
  const objectiveCount = objectiveRows.length;
  const matchPercent = objectiveCount
    ? Math.round(objectiveRows.reduce((sum, row) => sum + row.matchPercent, 0) / objectiveCount)
    : 0;
  const matchSummary = satisfiedCount === objectiveCount && objectiveCount > 0
    ? `${objectiveCount}개 목표 모두 기준 충족`
    : satisfiedCount === 0
      ? `미충족 목표 ${objectiveCount}개 · 수치 차이 기반`
      : `목표 ${satisfiedCount}개 충족 · 미충족 목표 ${objectiveCount - satisfiedCount}개`;
  return {
    runId: run.runId,
    dataOrigin: 'ACTUAL',
    conditions: ['pressure', 'sourcePower', 'biasPower'].map((metric) => metricRow(run, metric)),
    metrics: ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => metricRow(run, metric)),
    qualityLabel: run.qualityStatus === 'VERIFIED' ? '검증됨' : '확인 필요',
    convergenceLabel: run.convergenceStatus === 'CONVERGED' ? '수렴 완료' : '수렴 확인 필요',
    satisfiedCount,
    objectiveCount,
    matchPercent,
    satisfactionLabel: `검색값 근접도 ${matchPercent}%`,
    matchSummary,
    objectiveRows,
    baselineRunId: baselineRun ? baselineRun.runId : null,
    baselineRows,
    actions: [
      { id: 'continue-with-run', label: '이 Run으로 이어서 질문', runId: run.runId },
      { id: 'open-run-detail', label: '실험 자세히 보기', runId: run.runId },
    ],
  };
}

function buildReverseGroupsModel(result, baselineRun = null) {
  const objectives = result && Array.isArray(result.objectives) ? result.objectives : [];
  const goals = result && Array.isArray(result.goals) ? result.goals : [];
  const normalizeEntry = (entry) => entry && entry.run ? entry.run : entry;
  const commonEntries = result && Array.isArray(result.commonCandidates)
    ? result.commonCandidates
    : ((result && result.representativeCandidates) || []);
  const commonCandidates = commonEntries.map((entry) => buildCandidateFitModel(normalizeEntry(entry), objectives, baselineRun));
  const goalSortLabel = (goal) => `${METRIC_META[goal.metric].label} ${goal.direction === 'MIN' ? '낮은순' : '높은순'}`;
  const primarySortLabel = goals.length
    ? goals.map(goalSortLabel).join(' → ')
    : objectives.length ? '검색값 근접도 높은순' : 'Run ID순';
  const groups = [{
    id: 'results',
    label: `조건 일치 결과 ${commonCandidates.length}`,
    candidates: commonCandidates,
    sortLabel: primarySortLabel,
  }];
  const objectiveMetrics = new Set((result && result.objectiveResults ? result.objectiveResults : []).map((group) => group.objective.metric));
  (result && result.goalResults ? result.goalResults : [])
    .filter((group) => !objectiveMetrics.has(group.goal.metric))
    .forEach((group) => {
      const meta = METRIC_META[group.goal.metric];
      const candidates = (group.candidates || []).map((entry) => buildCandidateFitModel(normalizeEntry(entry), objectives, baselineRun));
      groups.push({
        id: group.goal.metric,
        label: `${goalSortLabel(group.goal)} ${candidates.length}`,
        sortLabel: goalSortLabel(group.goal),
        goal: group.goal,
        candidates,
      });
    });
  (result && result.objectiveResults ? result.objectiveResults : []).forEach((group) => {
    const meta = METRIC_META[group.objective.metric];
    const candidates = (group.candidates || []).map((entry) => buildCandidateFitModel(normalizeEntry(entry), objectives, baselineRun));
    groups.push({
      id: group.objective.metric,
      label: `${meta.label} 조건 ${candidates.length}`,
      sortLabel: '검색값 근접도 높은순',
      objective: group.objective,
      candidates,
    });
  });
  return {
    activeGroupId: 'results',
    groups,
    objectives,
    viewportCardCount: 6,
    scrollsInternally: true,
    conflictSummary: commonCandidates.length === 0
      ? '모든 필수 조건을 동시에 만족하는 실제 Run이 없습니다. 조건별 결과를 확인하거나 범위를 조정해 주세요.'
      : null,
  };
}

function graphModel(id, label, series, unavailableReason) {
  const values = Array.isArray(series) ? series : series ? [series] : [];
  return {
    id,
    label,
    available: values.length > 0,
    reason: values.length ? null : unavailableReason,
    series: values,
  };
}

function buildRunDetailModel(run) {
  if (!run) return null;
  const analysis = run.analysis || {};
  const unavailable = run.biasPower === 0
    ? 'Bias-off Run에는 해당 쉬스 분포 출력이 저장되지 않았습니다.'
    : '원본 결과 파일에 해당 출력이 없습니다.';
  return {
    runId: run.runId,
    conditions: ['pressure', 'sourcePower', 'biasPower'].map((metric) => metricRow(run, metric)),
    metrics: ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => metricRow(run, metric)),
    quality: {
      qualityStatus: run.qualityStatus,
      qualityLabel: run.qualityStatus === 'VERIFIED' ? '검증됨' : '확인 필요',
      convergenceStatus: run.convergenceStatus,
      convergenceLabel: run.convergenceStatus === 'CONVERGED' ? '수렴 완료' : '수렴 확인 필요',
      finalResidualMax: analysis.finalResidualMax,
    },
    graphs: [
      graphModel('ied', 'Ion Energy Distribution', (run.iedDistribution || []).map((point) => [point.energy, point.intensity]), unavailable),
      graphModel('iad', 'Ion Angle Distribution', analysis.iad, unavailable),
      graphModel('iead', 'Ion Energy-Angle Distribution', analysis.iead, unavailable),
      graphModel('current', 'RF Current', analysis.current && analysis.current.points, unavailable),
      graphModel('potential', 'Electrode Potential', analysis.potential && analysis.potential.points, unavailable),
      graphModel('density', 'Plasma Density', analysis.density, unavailable),
      graphModel('residual', 'Residual Convergence', analysis.residualTrace, '수렴 잔차 로그가 없습니다.'),
    ],
    sourceFiles: (run.sourceFiles || []).map((file) => ({ ...file })),
  };
}

function buildCandidateTableRows(candidates) {
  return (candidates || []).map((candidate) => ({
    runId: candidate.runId,
    dataOrigin: candidate.dataOrigin,
    isRecommended: candidate.isRecommended,
    recommendationLabel: candidate.recommendationLabel,
    conditions: Object.fromEntries(candidate.conditions.map((item) => [item.metric, { value: item.value, unit: item.unit }])),
    metrics: Object.fromEntries(candidate.metrics.map((item) => [item.metric, { value: item.value, unit: item.unit }])),
  }));
}

function normalizeCandidateView(view) {
  return view === 'table' ? 'table' : 'cards';
}

function buildReverseViewModel(result, query) {
  if (!result || result.status !== 'MATCH') {
    return {
      status: result ? result.status : 'INVALID',
      kpis: [], tabs: [], candidates: [], nearMatches: result && result.nearMatches ? result.nearMatches : [],
    };
  }

  const common = result.commonRecommendation || result.representativeCandidates[0];
  const representatives = result.representativeCandidates || [];
  const allCandidateRuns = analysisTools
    ? analysisTools.collectReverseCandidates(result)
    : representatives;
  const tabs = [
    { id: 'common', label: '공통 후보', count: representatives.length, runIds: representatives.map((run) => run.runId) },
    ...result.goalResults.map((group) => ({
      id: group.goal.metric,
      label: `${METRIC_META[group.goal.metric].label} 후보`,
      count: group.candidates.length,
      runIds: group.candidates.map((run) => run.runId),
    })),
  ];

  return {
    status: 'MATCH',
    queryText: query.originalText,
    totalCount: result.totalCount,
    commonRunId: common ? common.runId : null,
    kpis: common ? [
      { id: 'ionFlux', label: '추천 Ion Flux', value: displayValue(common.metrics.ionFlux), unit: METRIC_META.ionFlux.unit, hint: '실측 결과' },
      { id: 'iedWidth', label: '추천 IED Width', value: displayValue(common.metrics.iedWidth), unit: 'eV', hint: '낮을수록 좁은 분포' },
      { id: 'commonCount', label: '공통 후보', value: String(representatives.length), unit: 'Runs', hint: '세 목표 교집합' },
      analysisTools && analysisTools.isActualResultRun(common)
        ? { id: 'fit', label: '데이터 정책', value: 'Actual', unit: 'only', hint: '예측·보간 없음' }
        : { id: 'fit', label: '조건 적합도', value: `${common.presentationScore}%`, unit: '설명용', hint: '물리 예측 점수 아님' },
    ] : [],
    tabs,
    candidates: allCandidateRuns.map((run) => candidateModel(run, common && common.runId)),
    caveat: analysisTools && analysisTools.isActualResultRun(common)
      ? '모든 후보는 원본 결과 파일의 실제 결과이며, 예측·보간 또는 생성된 통합 점수를 사용하지 않습니다.'
      : '적합도는 후보 설명을 위한 UI 점수이며 물리 예측값이나 통합 순위가 아닙니다.',
  };
}

function buildTargetDelta(run, goal) {
  const actual = metricValue(run, goal.metric);
  const meta = METRIC_META[goal.metric];
  if (goal.direction === 'TARGET_RANGE') {
    const inRange = actual >= Number(goal.min) && actual <= Number(goal.max);
    const delta = inRange ? 0 : actual < goal.min ? actual - goal.min : actual - goal.max;
    return {
      metric: goal.metric, label: meta.label, actual: displayValue(actual), unit: meta.unit,
      target: `${goal.min}–${goal.max} ${meta.unit}`, delta: displayValue(delta), status: inRange ? 'IN_RANGE' : 'OUT_OF_RANGE',
    };
  }
  return {
    metric: goal.metric, label: meta.label, actual: displayValue(actual), unit: meta.unit,
    target: goal.direction === 'MAX' ? '높을수록 우선' : '낮을수록 우선', delta: '방향 기준', status: 'DIRECTIONAL',
  };
}

function comparisonModel(target, comparison) {
  const conditionKeys = ['pressure', 'sourcePower', 'biasPower'];
  const changed = conditionKeys.find((key) => target[key] !== comparison[key]);
  const meta = METRIC_META[changed];
  return {
    runId: comparison.runId,
    changedCondition: changed,
    changeLabel: meta.label,
    from: displayValue(target[changed]),
    to: displayValue(comparison[changed]),
    delta: `${comparison[changed] - target[changed] > 0 ? '+' : ''}${displayValue(comparison[changed] - target[changed])} ${meta.unit}`,
    metrics: ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => metricRow(comparison, metric)),
  };
}

function buildEvidenceViewModel(run, query, comparisonRuns) {
  if (!run) return null;
  return {
    runId: run.runId,
    title: `${run.runId} Evidence Card`,
    summary: run.note || '검증된 실제 시뮬레이션 Run',
    conditions: ['pressure', 'sourcePower', 'biasPower'].map((metric) => metricRow(run, metric)),
    metrics: ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => metricRow(run, metric)),
    trustRows: [
      { id: 'convergence', label: '수렴 상태', value: run.convergenceStatus === 'CONVERGED' ? '수렴 완료' : run.convergenceStatus, tone: run.convergenceStatus === 'CONVERGED' ? 'success' : 'warning' },
      { id: 'quality', label: '품질 상태', value: run.qualityStatus === 'VERIFIED' ? '검증됨' : run.qualityStatus, tone: run.qualityStatus === 'VERIFIED' ? 'success' : 'warning' },
      { id: 'registeredAt', label: '등록 시각', value: new Date(run.registeredAt).toLocaleString('ko-KR'), tone: 'neutral' },
    ],
    sourceFiles: run.sourceFiles.map((file) => ({ ...file, statusLabel: file.status === 'PARSED' ? '파싱 완료' : '파싱 실패' })),
    targetDeltas: (query && Array.isArray(query.goals) ? query.goals : []).map((goal) => buildTargetDelta(run, goal)),
    comparisons: (comparisonRuns || []).map((comparison) => comparisonModel(run, comparison)),
    chart: {
      title: 'Ion Energy Distribution',
      xLabel: 'Ion Energy (eV)',
      yLabel: 'Normalized intensity',
      points: run.iedDistribution.map((point) => ({ x: point.energy, y: point.intensity })),
    },
  };
}

function archiveRun(runId, runs) {
  const run = (runs || []).find((item) => item.runId === runId);
  if (!run) return { runId, available: false, statusLabel: '사용할 수 없는 Run', conditions: [], metrics: [] };
  return {
    runId,
    available: true,
    statusLabel: run.qualityStatus === 'VERIFIED' ? '검증됨' : '확인 필요',
    conditions: ['pressure', 'sourcePower', 'biasPower'].map((metric) => metricRow(run, metric)),
    metrics: ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => metricRow(run, metric)),
  };
}

function buildArchiveDetail(record, runs) {
  const decisionLabels = { ADOPT: '채택', HOLD: '보류', REJECT: '제외' };
  if (record && record.version === 2) {
    return {
      reviewId: record.id || record.reviewId,
      version: 2,
      question: record.question,
      objectives: record.objectives || [],
      comment: record.overallComment,
      authorName: record.authorName || '익명',
      createdAt: new Date(record.createdAt).toLocaleString('ko-KR'),
      candidates: (record.candidates || []).map((candidate) => ({
        ...candidate,
        decisionLabel: ({ ADOPT: '채택', HOLD: '보류', REJECT: '반려', ALTERNATIVE: '대안', COMPARISON: '비교군' })[candidate.decision] || candidate.decision,
        current: archiveRun(candidate.runId, runs),
      })),
    };
  }
  return {
    reviewId: record.reviewId,
    target: archiveRun(record.targetRunId, runs),
    comparisons: (record.comparedRunIds || []).map((runId) => archiveRun(runId, runs)),
    decision: record.decision,
    decisionLabel: decisionLabels[record.decision] || record.decision,
    comment: record.comment,
    authorName: record.authorName || '익명',
    createdAt: new Date(record.createdAt).toLocaleString('ko-KR'),
    analysisType: record.analysisType,
    processMode: record.processMode,
    queryText: record.queryText,
    constraints: record.constraints || [],
    goals: record.goals || [],
    evidenceKinds: record.evidenceKinds || [],
    limitations: record.limitations || [],
  };
}

function buildExperimentRecordModel(turn, runs) {
  if (turn && turn.answerSnapshot && turn.answerSnapshot.nestedAnswer) turn = {...turn,answerSnapshot:turn.answerSnapshot.nestedAnswer};
  if (turn && turn.answerSnapshot && turn.answerSnapshot.memoryResult) turn = {...turn,answerSnapshot:{intent:'REVERSE_SEARCH',candidateGroups:{groups:[{candidates:turn.answerSnapshot.memoryResult.remaining.map((s)=>(runs || []).find((r)=>r.runId===s.runId)).filter(Boolean).map((r)=>({...buildCandidateFitModel(r),satisfactionLabel:'과거 기록 기준 검토 · 수치 순위 없음'}))}]}}};
  if (!turn || !turn.answerSnapshot || turn.answerSnapshot.intent !== 'REVERSE_SEARCH') return null;
  const groups = turn.answerSnapshot.candidateGroups && turn.answerSnapshot.candidateGroups.groups || [];
  const lookupMatches = turn.answerSnapshot.constraintLookup && turn.answerSnapshot.constraintLookup.matches || [];
  const candidates = [];
  const seen = new Set();
  const candidateSets = groups.length ? groups.map((group) => group.candidates || []) : [lookupMatches];
  candidateSets.forEach((groupCandidates) => groupCandidates.forEach((candidate) => {
    if (seen.has(candidate.runId)) return;
    const run = (runs || []).find((item) => item.runId === candidate.runId);
    if (!run) return;
    seen.add(candidate.runId);
    candidates.push({
      runId: candidate.runId,
      conditions: candidate.conditions,
      metrics: candidate.metrics,
      satisfactionLabel: candidate.satisfactionLabel || '필수 조건 모두 충족',
      objectiveEvaluations: (candidate.objectiveRows || []).map((row) => ({
        objectiveId: row.objectiveId,
        metric: row.metric,
        actual: row.actual,
        satisfied: row.satisfied,
        targetLabel: row.targetLabel,
        differenceLabel: row.differenceLabel,
      })),
    });
  }));
  return {
    turnId: turn.id,
    question: turn.question,
    objectives: turn.answerSnapshot.objectives || [],
    candidates: candidates.slice(0, 9),
    recommendedRunIds: candidates.slice(0, Math.min(3, candidates.length)).map((candidate) => candidate.runId),
  };
}

function buildExperimentRecordWorkflowModel(model, draft = {}) {
  const candidates = model && Array.isArray(model.candidates) ? model.candidates : [];
  const candidateIds = new Set(candidates.map((candidate) => candidate.runId));
  const adoptedRunId = candidateIds.has(draft.adoptedRunId) ? draft.adoptedRunId : null;
  const selectedRunIds = [...new Set(Array.isArray(draft.selectedRunIds) ? draft.selectedRunIds : [])]
    .filter((runId) => candidateIds.has(runId) && runId !== adoptedRunId)
    .slice(0, 2);
  const decisions = draft.decisions && typeof draft.decisions === 'object' ? draft.decisions : {};
  const notes = draft.notes && typeof draft.notes === 'object' ? draft.notes : {};
  const selectedCandidates = [adoptedRunId, ...selectedRunIds]
    .map((runId) => candidates.find((candidate) => candidate.runId === runId))
    .filter(Boolean);
  return {
    step: draft.step === 2 && adoptedRunId ? 2 : 1,
    view: draft.view === 'table' ? 'table' : 'card',
    adoptedRunId,
    selectedRunIds,
    candidateStates: candidates.map((candidate) => ({
      ...candidate,
      isAdopted: candidate.runId === adoptedRunId,
      isSelected: selectedRunIds.includes(candidate.runId),
    })),
    judgements: selectedCandidates.map((candidate) => {
      const isAdopted = candidate.runId === adoptedRunId;
      const allowedDecisions = isAdopted ? ['ADOPT'] : ['HOLD', 'REJECT'];
      const requestedDecision = decisions[candidate.runId];
      return {
        ...candidate,
        isAdopted,
        decisionLocked: isAdopted,
        allowedDecisions,
        decision: isAdopted ? 'ADOPT' : allowedDecisions.includes(requestedDecision) ? requestedDecision : '',
        note: String(notes[candidate.runId] || ''),
      };
    }),
  };
}

function buildForwardViewModel(result, runsOverride) {
  if (!result || !result.run) {
    return { status: result ? result.status : 'NO_DATA', notice: '사용 가능한 실제 Run이 없습니다.', conditions: [], metrics: [], comparisons: [] };
  }
  const run = result.run;
  const requested = result.requestedConditions || {
    pressure: run.pressure - (result.deltas ? result.deltas.pressure : 0),
    sourcePower: run.sourcePower - (result.deltas ? result.deltas.sourcePower : 0),
    biasPower: run.biasPower - (result.deltas ? result.deltas.biasPower : 0),
  };
  const comparisons = analyzer ? analyzer.buildControlledComparison(run, runsOverride || catalog.runs) : [];
  return {
    status: result.status,
    statusLabel: result.status === 'EXACT' ? '정확히 일치하는 실제 Run' : '가장 가까운 실제 Run',
    notice: result.status === 'EXACT'
      ? '입력 조건과 정확히 일치하는 검증 Run입니다.'
      : '요청 조건의 결과를 예측하지 않고, 데이터베이스에서 가장 가까운 실제 Run을 표시합니다.',
    runId: run.runId,
    conditions: ['pressure', 'sourcePower', 'biasPower'].map((metric) => metricRow(run, metric)),
    requestedConditions: ['pressure', 'sourcePower', 'biasPower'].map((metric) => ({
      metric, label: METRIC_META[metric].label, value: displayValue(requested[metric]), unit: METRIC_META[metric].unit,
    })),
    conditionDeltas: ['pressure', 'sourcePower', 'biasPower'].map((metric) => ({
      metric,
      label: METRIC_META[metric].label,
      delta: `${result.deltas[metric] > 0 ? '+' : ''}${displayValue(result.deltas[metric])}`,
      unit: METRIC_META[metric].unit,
    })),
    metrics: ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => ({ ...metricRow(run, metric), source: 'ACTUAL_RUN' })),
    chart: { title: 'Ion Energy Distribution', points: run.iedDistribution.map((point) => ({ x: point.energy, y: point.intensity })) },
    evidenceState: {
      quality: run.qualityStatus === 'VERIFIED' ? '검증됨' : run.qualityStatus,
      convergence: run.convergenceStatus === 'CONVERGED' ? '수렴 완료' : run.convergenceStatus,
      sourceFileCount: run.sourceFiles.length,
    },
    sourceFiles: run.sourceFiles,
    comparisons: comparisons.map((comparison) => comparisonModel(run, comparison)),
    sourceRun: run,
  };
}

const AGENT_LABELS = Object.freeze({
  FORWARD_LOOKUP: '조건 조회',
  REVERSE_SEARCH: '후보 탐색',
  CHANGE_EXPLANATION: '변화 설명',
  CONCEPT_EXPLANATION: '개념 설명',
  CLARIFICATION: '추가 확인',
  UNSUPPORTED: '지원 범위 안내',
});

const EVIDENCE_STATES = Object.freeze([
  Object.freeze({ kind: 'OBSERVED', label: '관찰됨', tone: 'observed' }),
  Object.freeze({ kind: 'MANUAL', label: '문서 근거', tone: 'manual' }),
  Object.freeze({ kind: 'INTERPRETATION', label: '가능한 해석', tone: 'interpretation' }),
  Object.freeze({ kind: 'LIMITATION', label: '확인 불가', tone: 'limitation' }),
]);

function buildAgentAnswerModel(request, result) {
  const intent = request && request.intent ? request.intent : 'UNSUPPORTED';
  const base = {
    intent,
    analysisLabel: AGENT_LABELS[intent] || AGENT_LABELS.UNSUPPORTED,
    question: request && request.originalText ? request.originalText : '',
    verifiedOnly: true,
    evidenceStates: EVIDENCE_STATES.map((state) => ({ ...state })),
    sections: [],
    actions: [],
    runIds: [],
    sourceResult: result || null,
  };

  if (intent === 'UNSUPPORTED') {
    return {
      ...base,
      status: 'UNSUPPORTED',
      summary: request.message,
      suggestions: request.suggestions || [],
      actions: (request.suggestions || []).map((suggestion) => ({
        id: 'use-suggestion', label: suggestion.label, text: suggestion.text, intent: suggestion.intent,
      })),
    };
  }

  if (intent === 'CLARIFICATION') {
    return {
      ...base,
      status: 'NEEDS_INPUT',
      summary: request.message,
      missingConditions: request.missingConditions || [],
      clarificationContext: request.context || '',
    };
  }

  if (intent === 'CONCEPT_EXPLANATION') {
    const concept = CONCEPT_EXPLANATIONS[request.concept] || CONCEPT_EXPLANATIONS.plasma;
    return {
      ...base,
      verifiedOnly: false,
      status: 'READY',
      summary: concept.title,
      concept: {
        ...concept,
        sections: concept.sections.map((section) => ({ ...section })),
        sourceNote: '일반적인 플라즈마 공정 원리를 설명한 내용입니다. 특정 장비의 실제 거동은 Run 데이터와 함께 확인해야 합니다.',
      },
    };
  }

  if (intent === 'FORWARD_LOOKUP') {
    const run = result && result.run;
    const deltas = result && result.deltas ? result.deltas : {};
    const conditionRows = ['pressure', 'sourcePower', 'biasPower'].map((metric) => ({
      metric,
      label: METRIC_META[metric].label,
      delta: Number(deltas[metric]),
      exact: Number(deltas[metric]) === 0,
      unit: METRIC_META[metric].unit,
    }));
    const exactCount = conditionRows.filter((row) => row.exact).length;
    const conditionMatch = run ? {
      isExact: exactCount === conditionRows.length,
      label: exactCount === conditionRows.length
        ? '3개 공정 조건 정확히 일치'
        : '정확히 일치하는 Run 없음',
      summary: exactCount === conditionRows.length
        ? '요청한 조건 그대로 저장된 실제 Run'
        : '가장 가까운 실제 Run은 참고용으로만 표시',
      rows: conditionRows,
    } : null;
    return {
      ...base,
      status: result ? result.status : 'NO_DATA',
      summary: result && result.status === 'NEAREST_ONLY'
        ? '요청 조건을 예측하지 않고 가장 가까운 실제 Run을 찾았습니다.'
        : '입력 조건과 일치하는 실제 Run을 찾았습니다.',
      runIds: run ? [run.runId] : [],
      run,
      conditionMatch,
      sections: run ? [
        { id: 'conditions', number: '01', title: '조회 조건', data: request.query.conditions },
        { id: 'result', number: '02', title: '실제 Run 결과', data: run.metrics },
      ] : [],
      actions: run ? [
        { id: 'continue-with-run', label: '이 Run으로 이어서 질문', runId: run.runId },
        { id: 'open-run-detail', label: '실험 자세히 보기', runId: run.runId },
      ] : [],
    };
  }

  if (intent === 'REVERSE_SEARCH') {
    const candidates = result && result.status === 'MATCH'
      ? (result.representativeCandidates || result.allMatches || [])
      : [];
    const baselineRun = request.query && request.query.baselineRunId
      ? candidates.find((run) => run.runId === request.query.baselineRunId) || null
      : null;
    const candidateGroups = buildReverseGroupsModel(result, baselineRun);
    return {
      ...base,
      status: result ? result.status : 'NO_DATA',
      processMode: request.query.processMode,
      summary: candidates.length
        ? `조건을 만족하는 실제 Run ${candidates.length}개를 찾았습니다.`
        : '조건을 만족하는 실제 Run이 없습니다.',
      runIds: candidates.map((run) => run.runId),
      candidates,
      constraints: request.query.constraints || [],
      goals: request.query.goals || [],
      objectives: result && result.objectives ? result.objectives : [],
      candidateGroups,
      constraintLookup: null,
      sections: [
        { id: 'request', number: '01', title: '검색 조건과 정렬', data: request.query },
        { id: 'candidates', number: '02', title: '실제 Run 결과', data: candidates },
      ],
      actions: candidates.length ? [{ id: 'open-experiment-record', label: '실험 기록하기' }] : [],
    };
  }

  if (!result || result.status !== 'READY') {
    return {
      ...base,
      status: result ? result.status : 'NO_DATA',
      summary: result && result.message ? result.message : '비교 가능한 실제 Run이 없습니다.',
    };
  }

  const claimsByKind = (kind) => result.claims.filter((claim) => claim.kind === kind);
  const fluxChange = result.observations.find((item) => item.key === 'ionFlux');
  const energyChange = result.observations.find((item) => item.key === 'meanIonEnergy');
  const densityChange = result.supportingMetrics.find((item) => item.key === 'electronDensity');
  const headlinePercent = (metric) => {
    const value = Number(metric && metric.percentChange);
    if (!Number.isFinite(value)) return '비교 불가';
    return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(1)}%`;
  };
  const conclusion = {
    title: '소스 전력 변화가 입자 밀도와 Flux에 더 직접적으로 반영된 것으로 보입니다.',
    detail: densityChange && densityChange.available
      ? '일반적으로 소스 전력은 플라즈마 안에서 전자와 이온이 만들어지는 정도에 영향을 주기 때문에 입자 밀도와 Ion Flux가 함께 변하기 쉽습니다. 반면 평균 이온 에너지는 소스 전력만이 아니라 바이어스와 쉬스 전위의 영향도 크게 받아 Flux와 같은 비율이나 방향으로 움직이지 않을 수 있습니다.'
      : '일반적으로 소스 전력은 입자 생성과 Flux에 영향을 주지만, 평균 이온 에너지는 바이어스와 쉬스 전위의 영향도 함께 받습니다.',
    evidence: densityChange && densityChange.available
      ? `이번 비교에서도 전자 밀도 ${headlinePercent(densityChange)}와 Ion Flux ${headlinePercent(fluxChange)}가 같은 방향으로 변했고, Mean Ion Energy는 ${headlinePercent(energyChange)}로 다르게 반응했습니다.`
      : `이번 비교에서 Ion Flux는 ${headlinePercent(fluxChange)}, Mean Ion Energy는 ${headlinePercent(energyChange)} 변했습니다.`,
    limit: '관찰된 연관성이며, 이 데이터만으로 전체 물리 원인으로 확정할 수는 없습니다.',
  };
  return {
    ...base,
    status: result.status,
    summary: '한 조건만 다른 실제 Run을 비교해 관찰, 근거, 해석과 한계를 분리했습니다.',
    runIds: [result.runPair.before.runId, result.runPair.after.runId],
    runPair: result.runPair,
    conclusion,
    narrative: [
      { kind: 'principle', title: '왜 이런 차이가 생기나요?', text: conclusion.detail },
      { kind: 'evidence', title: '이번 비교에서는', text: conclusion.evidence },
      { kind: 'boundary', title: '해석할 때 주의할 점', text: conclusion.limit },
    ],
    sections: [
      { id: 'comparison', number: '01', title: '비교 조건 확인', data: result.conditionRows },
      { id: 'observations', number: '02', title: '관찰된 변화', data: result.observations },
      {
        id: 'evidence', number: '03', title: '변화 근거 연결',
        data: { metrics: result.supportingMetrics, claims: [...claimsByKind('OBSERVED'), ...claimsByKind('MANUAL')] },
      },
      {
        id: 'interpretation', number: '04', title: '가능한 해석과 한계',
        data: [...claimsByKind('INTERPRETATION'), ...claimsByKind('LIMITATION')],
      },
    ],
    explanation: result,
    actions: [],
  };
}

function buildEvidenceWorkspaceModel(answer, activeTab = 'summary') {
  const allowed = ['summary', 'graphs', 'sources', 'manual'];
  const selected = allowed.includes(activeTab) ? activeTab : 'summary';
  const explanation = answer && answer.explanation ? answer.explanation : {};
  return {
    activeTab: selected,
    tabs: [
      { id: 'summary', label: '비교 요약' },
      { id: 'graphs', label: '관련 그래프' },
      { id: 'sources', label: '출처와 품질' },
      { id: 'manual', label: '문서 근거' },
    ].map((tab) => ({ ...tab, active: tab.id === selected })),
    runIds: answer && answer.runIds ? answer.runIds : [],
    runPair: answer && answer.runPair ? answer.runPair : { before: null, after: null },
    conditions: explanation.conditionRows || [],
    observations: explanation.observations || [],
    supportingMetrics: explanation.supportingMetrics || [],
    graphOptions: explanation.graphOptions || [],
    sourceFiles: explanation.sourceFiles || [],
    quality: explanation.quality || [],
    manualEvidence: explanation.manualEvidence || [],
    claims: explanation.claims || [],
  };
}

function buildCatalogRows(runs, filters = {}) {
  const search = String(filters.search || '').trim().toLocaleUpperCase('en-US');
  return (runs || [])
    .filter((run) => !filters.status || run.catalogStatus === filters.status)
    .filter((run) => !filters.quality || run.qualityStatus === filters.quality)
    .filter((run) => !search || run.runId.includes(search) || run.sourceFiles.some((file) => file.name.toLocaleUpperCase('en-US').includes(search)))
    .map((run) => ({
      runId: run.runId,
      conditions: ['pressure', 'sourcePower', 'biasPower'].map((metric) => metricRow(run, metric)),
      metrics: ['ionFlux', 'meanIonEnergy', 'iedWidth'].map((metric) => metricRow(run, metric)),
      convergenceStatus: run.convergenceStatus,
      convergenceLabel: run.convergenceStatus === 'CONVERGED' ? '수렴 완료' : run.convergenceStatus === 'FAILED' ? '수렴 실패' : '확인 불가',
      qualityStatus: run.qualityStatus,
      qualityLabel: run.qualityStatus === 'VERIFIED' ? '검증됨' : run.qualityStatus === 'REJECTED' ? '제외됨' : '미검증',
      parsingStatus: run.catalogStatus,
      parsingLabel: run.catalogStatus === 'READY' ? '파싱 완료' : run.catalogStatus === 'INCOMPLETE' ? '필수 파일 누락' : '파싱 실패',
      sourceFileCount: run.sourceFiles.length,
      registeredAt: new Date(run.registeredAt).toLocaleString('ko-KR'),
      note: run.note,
      sourceRun: run,
    }));
}

function buildReferenceDisplayModel(reference, visibleLimit = 6) {
  const ids = [...new Set((reference && Array.isArray(reference.ids) ? reference.ids : [])
    .filter((runId) => typeof runId === 'string' && runId.trim())
    .map((runId) => runId.trim()))];
  if (!ids.length) return null;
  const safeLimit = Number.isInteger(visibleLimit) && visibleLimit > 0 ? visibleLimit : 6;
  const items = ids.map((runId) => ({ runId }));
  return {
    kind: ids.length === 1 ? '단일 Run' : '후보 집합',
    count: ids.length,
    items,
    visibleItems: items.slice(0, safeLimit),
    hiddenItems: items.slice(safeLimit),
    remainingCount: Math.max(0, items.length - safeLimit),
  };
}

function toggleCandidateSelection(selectedRunId, runId) {
  const nextRunId = typeof runId === 'string' ? runId.trim() : '';
  if (!nextRunId) return selectedRunId || null;
  return selectedRunId === nextRunId ? null : nextRunId;
}

export {
    constraintTargetLabel,
    METRIC_META,
    buildReverseViewModel,
    buildCandidateFitModel,
    buildConstraintLookupModel,
    buildConstraintLookupDisplayModel,
    buildReverseGroupsModel,
    buildRunDetailModel,
    buildCandidateTableRows,
    normalizeCandidateView,
    buildEvidenceViewModel,
    buildArchiveDetail,
    buildExperimentRecordModel,
    buildExperimentRecordWorkflowModel,
    buildForwardViewModel,
    buildAgentAnswerModel,
    buildEvidenceWorkspaceModel,
    buildCatalogRows,
    buildReferenceDisplayModel,
    toggleCandidateSelection,
  };
