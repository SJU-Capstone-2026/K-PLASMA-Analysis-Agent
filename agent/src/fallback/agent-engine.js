/* eslint-disable @typescript-eslint/no-unused-vars -- Preserve original omission destructuring and storage catch bindings. */
// v12.3.1: preserved pure implementation; only IIFE/module boundaries changed.
import * as engine from './engine.js';


const DEMO_COMPARISON = Object.freeze({
  pressure: 6,
  biasPower: 600,
  changedCondition: 'sourcePower',
  fromValue: 300,
  toValue: 500,
});

const SUGGESTIONS = Object.freeze([
  Object.freeze({
    intent: 'FORWARD_LOOKUP',
    label: '조건 조회',
    text: '압력 8 mTorr, 소스 300 W, 바이어스 600 W 결과를 보여줘',
  }),
  Object.freeze({
    intent: 'REVERSE_SEARCH',
    label: '조건 일치 조회',
    text: 'Ion Flux가 400 이상이고 Mean Ion Energy가 140–180 eV인 실제 Run을 모두 보여줘',
  }),
  Object.freeze({
    intent: 'REVERSE_SEARCH',
    label: '후보 탐색',
    text: 'Ion Flux는 높게, Mean Ion Energy는 150–160 eV에 가깝게 후보를 찾아줘',
  }),
  Object.freeze({
    intent: 'CHANGE_EXPLANATION',
    label: '변화 설명',
    text: '소스 전력을 올렸는데 플럭스는 많이 변하고 평균 이온 에너지는 적게 변한 이유를 분석해줘',
  }),
  Object.freeze({
    intent: 'CONCEPT_EXPLANATION',
    label: '개념 설명',
    text: '평균 이온 에너지가 뭐야?',
  }),
]);

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function supportedScope(text, reason = 'OUT_OF_SCOPE') {
  return {
    intent: 'UNSUPPORTED',
    label: '지원 범위 안내',
    originalText: String(text || '').trim(),
    reason,
    message: reason === 'EMPTY'
      ? '질문을 입력하거나 아래 예시를 선택해 주세요.'
      : '이 프로토타입은 실제 Run의 조건 조회, 후보 탐색, 통제 비교와 플라즈마 기본 개념 설명을 지원합니다.',
    suggestions: clone(SUGGESTIONS),
  };
}

function isChangeExplanation(raw) {
  const change = /(올렸|내렸|바꿨|변했|변화|차이|달라|영향|비교)/i.test(raw);
  const explanation = /(왜|이유|원인|설명|분석)/i.test(raw);
  const condition = /(source|소스|bias|바이어스|pressure|압력)/i.test(raw);
  return change && explanation && condition;
}

function shouldExplainActiveRun(text) {
  const raw = String(text || '').trim();
  const asksWhy = /(?:왜|이유|설명|원인)/i.test(raw);
  const refersToObservedResult = /(?:결과|변화|달라|이렇게|이런|관찰)/i.test(raw);
  return asksWhy && refersToObservedResult;
}

function isDomainQuestion(raw) {
  return /(plasma|플라즈마|pressure|압력|source|소스|bias|바이어스|flux|플럭스|energy|에너지|ied|run|후보|결과|조회)/i.test(raw);
}

function conceptFromQuestion(raw) {
  const asksForExplanation = /(뭐야|무엇|뜻|개념|의미|설명|왜\s*중요|어떤\s*영향|영향이|역할|왜)/i.test(raw);
  if (!asksForExplanation || /\d/.test(raw)) return null;
  if (/(mean\s*ion\s*energy|평균\s*이온\s*에너지|평균\s*에너지|이온\s*에너지)/i.test(raw)) return 'meanIonEnergy';
  if (/(ion\s*flux|이온\s*플럭스|플럭스)/i.test(raw)) return 'ionFlux';
  if (/(pressure|압력)/i.test(raw)) return 'pressure';
  if (/(plasma|플라즈마)/i.test(raw)) return 'plasma';
  return null;
}

const CONDITION_LABELS = {
  pressure: '압력', sourcePower: '소스 전력', biasPower: '바이어스 전력', changeValues: '변경 전·후값', numericRange: '수치 또는 범위 조건',
};

const CONDITION_PATTERNS = {
  pressure: '(?:pressure|압력)',
  sourcePower: '(?:source(?:\\s*power)?|소스(?:\\s*(?:전력|파워))?)',
  biasPower: '(?:bias(?:\\s*power)?|바이어스(?:\\s*(?:전력|파워))?)',
};

const OBJECTIVE_METRICS = Object.freeze([
  Object.freeze({
    metric: 'ionFlux',
    pattern: '(?:ion\\s*flux|이온\\s*플럭스|플럭스)',
    unit: '10¹⁸ m⁻²s⁻¹',
    label: 'Ion Flux',
  }),
  Object.freeze({
    metric: 'meanIonEnergy',
    pattern: '(?:mean\\s*ion\\s*energy|평균\\s*이온\\s*에너지|평균\\s*에너지)',
    unit: 'eV',
    label: 'Mean Ion Energy',
  }),
  Object.freeze({
    metric: 'iedWidth',
    pattern: '(?:ied\\s*width|에너지\\s*분포\\s*폭|분포\\s*폭)',
    unit: 'eV',
    label: 'IED Width',
  }),
]);

function nextMetricIndex(raw, start) {
  return OBJECTIVE_METRICS.reduce((nearest, definition) => {
    const pattern = new RegExp(definition.pattern, 'ig');
    let match = pattern.exec(raw);
    while (match && match.index < start) match = pattern.exec(raw);
    return match && match.index < nearest ? match.index : nearest;
  }, raw.length);
}

function extractObjectives(text) {
  const raw = String(text || '');
  const found = OBJECTIVE_METRICS.flatMap((definition) => {
    const match = new RegExp(definition.pattern, 'i').exec(raw);
    if (!match) return [];
    const start = match.index + match[0].length;
    const segment = raw.slice(start, nextMetricIndex(raw, start));
    const range = segment.match(/(\d+(?:\.\d+)?)\s*(?:-|–|—|~|〜|to)\s*(\d+(?:\.\d+)?)/i);
    const scalar = segment.match(/(\d+(?:\.\d+)?)/);
    let objective = null;
    if (range) {
      objective = {
        metric: definition.metric,
        operator: 'RANGE',
        min: Number(range[1]),
        max: Number(range[2]),
        unit: definition.unit,
        label: `${definition.label} ${Number(range[1])}–${Number(range[2])} ${definition.unit}`,
      };
    } else if (scalar && /(?:이상|최소|하한|at\s*least|>=)/i.test(segment)) {
      objective = {
        metric: definition.metric,
        operator: 'MIN',
        value: Number(scalar[1]),
        unit: definition.unit,
        label: `${definition.label} ≥ ${Number(scalar[1])} ${definition.unit}`,
      };
    } else if (scalar && /(?:이하|최대|상한|at\s*most|<=)/i.test(segment)) {
      objective = {
        metric: definition.metric,
        operator: 'MAX',
        value: Number(scalar[1]),
        unit: definition.unit,
        label: `${definition.label} ≤ ${Number(scalar[1])} ${definition.unit}`,
      };
    }
    return objective ? [{ ...objective, sourceIndex: match.index }] : [];
  }).sort((a, b) => a.sourceIndex - b.sourceIndex);

  return found.map(({ sourceIndex, ...objective }, index) => ({
    id: `objective-${index + 1}-${objective.metric}`,
    ...objective,
  }));
}

function clarification(raw, missingConditions, context = '조건 조회') {
  const labels = missingConditions.map((key) => CONDITION_LABELS[key] || key);
  return {
    intent: 'CLARIFICATION',
    label: '추가 확인',
    originalText: raw,
    context,
    missingConditions: [...missingConditions],
    message: `${labels.join(' · ')} 값을 더 알려주세요. 값을 추정하지 않고 실제 Run을 찾겠습니다.`,
  };
}

function fixedValue(raw, key) {
  if (key === 'pressure') {
    const pressure = raw.match(new RegExp(`${CONDITION_PATTERNS.pressure}[^\\d]{0,20}(\\d+(?:\\.\\d+)?)\\s*(mTorr|Torr)?`, 'i'));
    if (!pressure) return null;
    return /^torr$/i.test(pressure[2] || 'mTorr') ? Number(pressure[1]) * 1000 : Number(pressure[1]);
  }
  const match = raw.match(new RegExp(`${CONDITION_PATTERNS[key]}[^\\d]{0,20}(\\d+(?:\\.\\d+)?)`, 'i'));
  return match ? Number(match[1]) : null;
}

function objectiveAsConstraint(objective) {
  const { id, label, ...constraint } = objective;
  return constraint;
}

function changedRange(raw, key) {
  const match = raw.match(new RegExp(`${CONDITION_PATTERNS[key]}[^\\d]{0,24}(\\d+(?:\\.\\d+)?)\\s*(?:mTorr|W)?\\s*(?:에서|부터|→|->|to)\\s*(\\d+(?:\\.\\d+)?)`, 'i'));
  return match ? { changedCondition: key, fromValue: Number(match[1]), toValue: Number(match[2]) } : null;
}

function parseExplanationComparison(raw, options) {
  if (options.comparison) return { comparison: clone(options.comparison), missingConditions: [] };
  const ranges = Object.keys(CONDITION_PATTERNS).map((key) => changedRange(raw, key)).filter(Boolean);
  if (ranges.length === 0) {
    return /\d/.test(raw)
      ? { comparison: null, missingConditions: ['changeValues'] }
      : { comparison: clone(DEMO_COMPARISON), missingConditions: [] };
  }
  if (ranges.length > 1) return { comparison: null, missingConditions: ['changeValues'] };

  const range = ranges[0];
  const fixedKeys = Object.keys(CONDITION_PATTERNS).filter((key) => key !== range.changedCondition);
  const comparison = {
    changedCondition: range.changedCondition,
    fromValue: range.fromValue,
    toValue: range.toValue,
  };
  const missingConditions = [];
  fixedKeys.forEach((key) => {
    const value = fixedValue(raw, key);
    if (value === null) missingConditions.push(key);
    else comparison[key] = value;
  });
  return { comparison: missingConditions.length ? null : comparison, missingConditions };
}

function enrichReverseQuery(query, raw) {
  const mentionsPressure = /(?:pressure|압력)[^\d]*(\d+(?:\.\d+)?)/i.test(raw);
  const mentionsFlux = /(ion\s*flux|이온\s*플럭스|flux|플럭스)/i.test(raw);
  const mentionsWidth = /(ied\s*width|에너지\s*분포\s*폭|분포\s*폭|폭)/i.test(raw);
  const mentionsEnergy = /(mean\s*ion\s*energy|평균\s*이온\s*에너지)/i.test(raw);
  const energyMaximum = raw.match(/(?:mean\s*ion\s*energy|평균\s*이온\s*에너지)[^\d]*(\d+(?:\.\d+)?)\s*(?:eV)?\s*(?:이하|미만|상한)/i);

  query.constraints = [];
  query.goals = [];
  query.originalValues = {};
  query.normalizedConditions = {};
  const numericRules = extractObjectives(raw);
  query.objectives = numericRules;

  if (mentionsPressure) {
    const value = fixedValue(raw, 'pressure');
    const pressureText = raw.match(/(?:pressure|압력).{0,32}/i);
    const operator = pressureText && /(이하|미만|상한|at\s*most)/i.test(pressureText[0]) ? 'MAX' : 'EQUAL';
    query.constraints.push({ metric: 'pressure', operator, value, unit: 'mTorr' });
    query.originalValues.pressure = { operator, value, unit: 'mTorr', label: `Pressure ${value} mTorr${operator === 'MAX' ? ' 이하' : ''}` };
    query.normalizedConditions[operator === 'MAX' ? 'pressureMax' : 'pressure'] = value;
  }

  if (mentionsFlux) {
    const direction = /(낮|최소|minimi)/i.test(raw) ? 'MIN' : 'MAX';
    query.goals.push({ metric: 'ionFlux', direction, unit: '10¹⁸ m⁻²s⁻¹', label: `Ion Flux ${direction === 'MIN' ? '최소화' : '최대화'}` });
  }
  if (mentionsWidth) {
    const direction = /(넓|최대|maximi)/i.test(raw) ? 'MAX' : 'MIN';
    query.goals.push({ metric: 'iedWidth', direction, unit: 'eV', label: `IED Width ${direction === 'MAX' ? '최대화' : '최소화'}` });
  }

  if (!energyMaximum && mentionsEnergy) {
    const direction = /(높|최대|maximi)/i.test(raw) ? 'MAX' : 'MIN';
    query.goals.push({ metric: 'meanIonEnergy', direction, unit: 'eV', label: `Mean Ion Energy ${direction === 'MAX' ? '최대화' : '최소화'}` });
  }
  numericRules.forEach((rule) => {
    query.constraints = query.constraints.filter((constraint) => constraint.metric !== rule.metric);
    query.constraints.push(objectiveAsConstraint(rule));
    query.originalValues[rule.metric] = objectiveAsConstraint(rule);
  });
  const numericMetrics = new Set(numericRules.map((rule) => rule.metric));
  query.goals = query.goals.filter((goal) => !numericMetrics.has(goal.metric));
  query.processMode = 'RUN_SEARCH';
  return query;
}

function classifyRequest(text, options = {}) {
  const raw = String(text || '').trim();
  if (!raw) return supportedScope(raw, 'EMPTY');

  if (isChangeExplanation(raw)) {
    const parsed = parseExplanationComparison(raw, options);
    if (parsed.missingConditions.length) return clarification(raw, parsed.missingConditions, '변화 설명');
    return {
      intent: 'CHANGE_EXPLANATION',
      label: '변화 설명',
      originalText: raw,
      comparison: parsed.comparison,
    };
  }

  const concept = conceptFromQuestion(raw);
  if (concept) {
    return {
      intent: 'CONCEPT_EXPLANATION',
      label: '개념 설명',
      originalText: raw,
      concept,
    };
  }

  if (!isDomainQuestion(raw)) return supportedScope(raw);

  const query = engine.classifyAnalysisRequest(raw);
  if (query.analysisType === 'FORWARD') {
    if (query.missingConditions && query.missingConditions.length) {
      return clarification(raw, query.missingConditions, '조건 조회');
    }
    return { intent: 'FORWARD_LOOKUP', label: '조건 조회', originalText: raw, query };
  }

  const reverseIntent = /(후보|추천|탐색|찾|최대|최소|높|낮|이하|이상|범위)/i.test(raw);
  if (query.analysisType === 'REVERSE' && reverseIntent) {
    enrichReverseQuery(query, raw);
    if (!query.constraints.length) {
      return clarification(raw, ['numericRange'], '실제 Run 탐색');
    }
    return {
      intent: 'REVERSE_SEARCH',
      label: '실제 Run 탐색',
      originalText: raw,
      query,
    };
  }

  return supportedScope(raw);
}

export {
    DEMO_COMPARISON,
    SUGGESTIONS,
    classifyRequest,
    supportedScope,
    extractObjectives,
    shouldExplainActiveRun,
  };
