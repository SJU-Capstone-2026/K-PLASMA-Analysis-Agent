// v12.3.1: preserved pure implementation; only IIFE/module boundaries changed.


const CONDITION_KEYS = ['pressure', 'sourcePower', 'biasPower'];
const CONDITION_META = {
  pressure: { label: 'Pressure', unit: 'mTorr' },
  sourcePower: { label: 'Source Power', unit: 'W' },
  biasPower: { label: 'Bias Power', unit: 'W' },
};

function round(value, digits = 1) {
  const factor = 10 ** digits;
  return Math.round((value + Number.EPSILON) * factor) / factor;
}

function finite(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function buildMetricChange(before, after, unit, digits = 1) {
  if (!finite(before) || !finite(after)) {
    return {
      before: finite(before) ? before : null,
      after: finite(after) ? after : null,
      delta: null,
      percentChange: null,
      percentLabel: '데이터 없음',
      unit,
      available: false,
    };
  }

  const delta = after - before;
  const percentChange = before === 0 ? null : round((delta / Math.abs(before)) * 100, digits);
  return {
    before,
    after,
    delta: round(delta, 6),
    percentChange,
    percentLabel: percentChange === null
      ? '계산 불가'
      : `${percentChange > 0 ? '+' : ''}${percentChange.toFixed(digits)}%`,
    unit,
    available: true,
  };
}

function resolvePair(comparison, runs) {
  if (comparison.beforeRunId && comparison.afterRunId) {
    return {
      before: runs.find((run) => run.runId === comparison.beforeRunId) || null,
      after: runs.find((run) => run.runId === comparison.afterRunId) || null,
    };
  }

  const changedKey = comparison.changedCondition;
  const fixedKeys = CONDITION_KEYS.filter((key) => key !== changedKey);
  const matchesFixed = (run) => fixedKeys.every((key) => Number(run[key]) === Number(comparison[key]));
  return {
    before: runs.find((run) => matchesFixed(run) && Number(run[changedKey]) === Number(comparison.fromValue)) || null,
    after: runs.find((run) => matchesFixed(run) && Number(run[changedKey]) === Number(comparison.toValue)) || null,
  };
}

function graphAvailability(before, after) {
  const both = (check) => Boolean(check(before) && check(after));
  return [
    { id: 'ied', label: 'IED 분포', available: both((run) => run.iedDistribution && run.iedDistribution.length > 0) },
    { id: 'current', label: 'RF 전류', available: both((run) => run.analysis.current && run.analysis.current.points.length > 0) },
    { id: 'potential', label: '전위 파형', available: both((run) => run.analysis.potential && run.analysis.potential.points.length > 0) },
    { id: 'density', label: '쉬스 밀도', available: both((run) => run.analysis.density && run.analysis.density.rows.length > 0) },
    { id: 'convergence', label: '수렴 잔차', available: both((run) => run.analysis.residualTrace && run.analysis.residualTrace.length > 0) },
  ];
}

function buildControlledExplanation(request, runs, manualEntries = []) {
  const comparison = request && request.comparison ? request.comparison : {};
  const { before, after } = resolvePair(comparison, Array.isArray(runs) ? runs : []);
  if (!before || !after) {
    return {
      status: 'NO_PAIR',
      intent: 'CHANGE_EXPLANATION',
      message: '요청 조건과 일치하는 실제 Run 두 개를 찾지 못했습니다.',
      runPair: { before, after },
    };
  }

  const changedConditions = CONDITION_KEYS.filter((key) => before[key] !== after[key]);
  if (changedConditions.length !== 1) {
    return {
      status: 'NOT_CONTROLLED',
      intent: 'CHANGE_EXPLANATION',
      message: '하나의 공정 변수만 다른 Run을 선택해야 변화 설명을 만들 수 있습니다.',
      changedConditions,
      runPair: { before, after },
    };
  }

  const observations = [
    {
      key: 'ionFlux',
      label: 'Ion Flux',
      ...buildMetricChange(before.metrics.ionFlux, after.metrics.ionFlux, '10¹⁸ m⁻²s⁻¹'),
    },
    {
      key: 'meanIonEnergy',
      label: 'Mean Ion Energy',
      ...buildMetricChange(before.metrics.meanIonEnergy, after.metrics.meanIonEnergy, 'eV'),
    },
  ];

  const supportingMetrics = [
    {
      key: 'electronDensity',
      label: 'Electron Density',
      ...buildMetricChange(before.analysis.electronDensity, after.analysis.electronDensity, 'cm⁻³'),
    },
    {
      key: 'electronTemperature',
      label: 'Electron Temperature',
      ...buildMetricChange(before.analysis.electronTemperature, after.analysis.electronTemperature, 'eV'),
    },
  ];

  const flux = observations[0];
  const energy = observations[1];
  const electronDensity = supportingMetrics[0];
  const changedKey = changedConditions[0];
  const changedLabel = CONDITION_META[changedKey].label;
  const manualAvailable = Array.isArray(manualEntries) && manualEntries.length > 0;
  const claims = [
    {
      kind: 'OBSERVED',
      causal: false,
      text: `Ion Flux는 ${flux.before}에서 ${flux.after}로 ${flux.percentLabel} 변했고, 평균 이온 에너지는 ${energy.before}에서 ${energy.after} eV로 ${energy.percentLabel} 변했습니다.`,
    },
    {
      kind: 'MANUAL',
      causal: false,
      text: manualAvailable
        ? '제공 매뉴얼은 solver.log와 parameter.log에서 밀도·전자 온도·이온 플럭스·평균 이온 에너지를 확인할 수 있다고 설명합니다.'
        : '현재 연결된 문서 근거가 없어 이 비교에는 실제 Run 출력만 사용했습니다.',
      evidenceIds: manualAvailable ? manualEntries.map((entry) => entry.id) : [],
    },
    {
      kind: 'INTERPRETATION',
      causal: false,
      text: electronDensity.available
        ? `전자 밀도도 ${electronDensity.percentLabel} 변해 Ion Flux와 같은 방향의 변화가 관찰됩니다. ${changedLabel} 변화와 입자 플럭스 변화가 연관됐을 가능성과 일치합니다.`
        : '관련 전자 밀도 데이터가 없어 변화 경로를 추가로 해석하지 않습니다.',
    },
    {
      kind: 'LIMITATION',
      causal: false,
      text: '두 실제 Run의 통제 비교는 관찰된 연관성을 보여주지만 전체 물리 원인이나 다른 조건에서의 동일한 경향을 확정하지 않습니다.',
    },
  ];

  return {
    status: 'READY',
    intent: 'CHANGE_EXPLANATION',
    question: request.originalText || '',
    changedCondition: changedConditions[0],
    runPair: { before, after },
    conditionRows: CONDITION_KEYS.map((key) => ({
      key,
      label: CONDITION_META[key].label,
      unit: CONDITION_META[key].unit,
      before: before[key],
      after: after[key],
      changed: before[key] !== after[key],
    })),
    observations,
    supportingMetrics,
    claims,
    graphOptions: graphAvailability(before, after),
    manualEvidence: manualAvailable ? manualEntries.slice() : [],
    sourceFiles: [before, after].flatMap((run) => run.sourceFiles.map((file) => ({ ...file, runId: run.runId }))),
    quality: [before, after].map((run) => ({
      runId: run.runId,
      qualityStatus: run.qualityStatus,
      convergenceStatus: run.convergenceStatus,
      strictConvergence: run.analysis.strictConvergence,
      finalResidualMax: run.analysis.finalResidualMax,
    })),
  };
}

export { buildMetricChange, buildControlledExplanation };
