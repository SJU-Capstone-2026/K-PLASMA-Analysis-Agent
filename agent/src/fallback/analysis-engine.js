// v12.3.1: preserved pure implementation; only IIFE/module boundaries changed.


const CONDITION_KEYS = ['pressure', 'sourcePower', 'biasPower'];

const METRICS = Object.freeze({
  meanIonEnergy: { label: '평균 이온 에너지', unit: 'eV', path: ['metrics', 'meanIonEnergy'], digits: 1 },
  ionFlux: { label: 'Ar+ 플럭스', unit: '10¹⁸ m⁻²s⁻¹', path: ['metrics', 'ionFlux'], digits: 1 },
  iedWidth: { label: 'IED Width', unit: 'eV', path: ['metrics', 'iedWidth'], digits: 1 },
  electronDensity: { label: '전자 밀도', unit: '#/cm³', path: ['analysis', 'electronDensity'], digits: 2, scientific: true },
  electronTemperature: { label: '전자 온도', unit: 'eV', path: ['analysis', 'electronTemperature'], digits: 2 },
  dcOffset: { label: 'DC offset', unit: 'V', path: ['analysis', 'dcOffset'], digits: 1 },
  peakToPeak: { label: 'Peak-to-peak', unit: 'V', path: ['analysis', 'peakToPeak'], digits: 1 },
});

function getRunById(runs, runId) {
  return (runs || []).find((run) => run.runId === runId) || null;
}

function getRunByConditions(runs, conditions) {
  return (runs || []).find((run) => CONDITION_KEYS.every((key) => run[key] === Number(conditions[key]))) || null;
}

function metricValue(run, metric) {
  const definition = METRICS[metric];
  if (!run || !definition) return null;
  const value = definition.path.reduce((current, key) => current && current[key], run);
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function getFixedValues(runs, fixedKey) {
  if (!CONDITION_KEYS.includes(fixedKey)) return [];
  return [...new Set((runs || []).map((run) => run[fixedKey]).filter(Number.isFinite))].sort((a, b) => a - b);
}

function buildConditionGrid(runs, fixedKey, fixedValue, metric) {
  if (!CONDITION_KEYS.includes(fixedKey)) throw new Error('고정 변수는 pressure, sourcePower, biasPower 중 하나여야 합니다.');
  const axisMap = {
    pressure: ['sourcePower', 'biasPower'],
    sourcePower: ['pressure', 'biasPower'],
    biasPower: ['pressure', 'sourcePower'],
  };
  const [rowKey, columnKey] = axisMap[fixedKey];
  const numericFixedValue = Number(fixedValue);
  const matching = (runs || []).filter((run) => run[fixedKey] === numericFixedValue);
  const rows = [...new Set((runs || []).map((run) => run[rowKey]))].sort((a, b) => a - b);
  const columns = [...new Set((runs || []).map((run) => run[columnKey]))].sort((a, b) => a - b);
  const cells = [];

  rows.forEach((rowValue) => {
    columns.forEach((columnValue) => {
      const conditions = { [fixedKey]: numericFixedValue, [rowKey]: rowValue, [columnKey]: columnValue };
      const run = getRunByConditions(matching, conditions);
      cells.push({ rowValue, columnValue, run, value: metricValue(run, metric), ...conditions });
    });
  });

  const values = cells.map((cell) => cell.value).filter((value) => value !== null);
  return {
    fixedKey,
    fixedValue: numericFixedValue,
    metric,
    rowKey,
    columnKey,
    rows,
    columns,
    cells,
    range: values.length ? { min: Math.min(...values), max: Math.max(...values) } : { min: null, max: null },
  };
}

function buildReverseSeed(run) {
  if (!run) return null;
  const energy = run.metrics.meanIonEnergy;
  return {
    id: `QUERY-FROM-${run.runId}`,
    originalText: `${run.runId} 실제 결과를 기준으로 Ion Flux 최대화, Mean Ion Energy 목표 범위 탐색`,
    analysisType: 'REVERSE',
    processMode: 'GOAL_RECOMMENDATION',
    originalValues: {
      pressure: { operator: 'MAX', value: run.pressure, unit: 'mTorr', label: `${run.pressure} mTorr 이하` },
      meanIonEnergy: { operator: 'RANGE', min: Math.floor(energy * 0.9), max: Math.ceil(energy * 1.1), unit: 'eV' },
      baseline: { runId: run.runId, pressure: run.pressure, sourcePower: run.sourcePower, biasPower: run.biasPower },
    },
    normalizedConditions: { pressureMax: run.pressure },
    constraints: [{ metric: 'pressure', operator: 'MAX', value: run.pressure, unit: 'mTorr' }],
    goals: [
      { metric: 'ionFlux', direction: 'MAX', unit: '10¹⁸ m⁻²s⁻¹', label: 'Ion Flux 최대화' },
      { metric: 'meanIonEnergy', direction: 'TARGET_RANGE', min: Math.floor(energy * 0.9), max: Math.ceil(energy * 1.1), unit: 'eV', label: 'Mean Ion Energy 목표 범위' },
      ...(run.metrics.iedWidth === null ? [] : [{ metric: 'iedWidth', direction: 'MIN', unit: 'eV', label: 'IED Width 최소화' }]),
    ],
    baselineRunId: run.runId,
    confirmed: false,
    modified: true,
  };
}

function formatMetric(value, metric) {
  const definition = METRICS[metric];
  if (value === null || !definition) return 'N/A';
  if (definition.scientific) return value.toExponential(2);
  return value.toLocaleString('ko-KR', { maximumFractionDigits: definition.digits });
}

function isActualResultRun(run) {
  return Boolean(run && run.analysis && Object.prototype.hasOwnProperty.call(run.analysis, 'hasDistribution'));
}

function collectReverseCandidates(result) {
  const candidates = [
    ...((result && result.representativeCandidates) || []),
    ...((result && result.goalResults) || []).flatMap((group) => group.candidates || []),
  ];
  const seen = new Set();
  return candidates.filter((run) => {
    if (!run || seen.has(run.runId)) return false;
    seen.add(run.runId);
    return true;
  });
}

function reconcileComparisonSelection(candidateRunIds, selectedRunIds, maxCount = 3, defaultCount = 2) {
  const candidates = [...new Set(candidateRunIds || [])];
  const candidateSet = new Set(candidates);
  const selected = [...new Set(selectedRunIds || [])]
    .filter((runId) => candidateSet.has(runId))
    .slice(0, maxCount);
  return selected.length ? selected : candidates.slice(0, Math.min(defaultCount, maxCount));
}

function linePointsForMetric(run, metric) {
  if (!run) return [];
  if (metric === 'ied') return (run.iedDistribution || []).map((point) => [Number(point.energy), Number(point.intensity)]);
  if (metric === 'iad') return run.analysis && Array.isArray(run.analysis.iad) ? run.analysis.iad : [];
  const output = run.analysis && run.analysis[metric];
  return output && Array.isArray(output.points) ? output.points : [];
}

function buildLineComparison(selectedRuns, metric, normalize = false) {
  return (selectedRuns || []).map((run) => {
    const runId = run && run.runId;
    const rawPoints = linePointsForMetric(run, metric)
      .map((point) => [Number(point[0]), Number(point[1])])
      .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]));
    const scale = normalize ? Math.max(...rawPoints.map((point) => Math.abs(point[1])), 0) : 1;
    const points = normalize && scale > 0
      ? rawPoints.map((point) => [point[0], point[1] / scale])
      : rawPoints;
    return { runId, available: points.length > 0, points };
  });
}

export {
    CONDITION_KEYS, METRICS, getRunById, getRunByConditions, metricValue,
    getFixedValues, buildConditionGrid, buildReverseSeed, formatMetric,
    isActualResultRun, collectReverseCandidates, reconcileComparisonSelection, buildLineComparison,
  };
