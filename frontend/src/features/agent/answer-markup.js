// v12.3.1 pure presentation functions. No state, storage, engine or global event handlers.
import {viewModels} from 'agent';
import {compactNumber} from '../../prototype/charts';
function renderMemoryAnswer(answer, turn) {
    if (answer.notice) return `<p>${escapeHtml(answer.notice)}</p>`;
    if (answer.pendingThreshold) return `<section class="memory-answer"><h3>비용 반려 기록이 몇 건 이상이면 제외할까요?</h3><p>기준을 정하기 전에는 후보를 제외하지 않습니다.</p><div class="form-actions">${[1,2].map((n)=>`<button class="button button--secondary" data-action="memory-threshold" data-turn-id="${turn.id}" data-count="${n}">${n}건 이상</button>`).join('')}<input type="number" min="1" step="1" aria-label="직접 입력 제외 건수" id="threshold-${turn.id}" placeholder="직접 입력"><button class="button button--primary" data-action="memory-threshold" data-turn-id="${turn.id}">적용</button></div></section>`;
    const result = answer.memoryResult;
    const remainingWithRecords = result.remaining.filter((summary) => summary.entries.length);
    const remainingWithoutRecords = result.remaining.length - remainingWithRecords.length;
    const summary = `<div class="memory-result-summary" aria-label="기록 필터 결과"><div><strong>${result.remaining.length}</strong><span>남은 후보</span></div><div><strong>${remainingWithRecords.length}</strong><span>관련 기록 있음</span></div><div><strong>${remainingWithoutRecords}</strong><span>관련 기록 없음</span></div><div class="is-excluded"><strong>${result.excluded.length}</strong><span>제외된 후보</span></div></div>`;
    const relevantRows = remainingWithRecords.length
      ? `<section class="memory-result-group"><h4>기록을 확인한 남은 후보</h4>${remainingWithRecords.map((item)=>renderMemoryRow(item,turn,false)).join('')}</section>`
      : '';
    const excludedRows = result.excluded.length
      ? `<section class="memory-result-group memory-result-group--excluded"><h4>제외된 후보</h4>${result.excluded.map((item)=>renderMemoryRow(item,turn,true)).join('')}</section>`
      : '';
    const empty = !result.remaining.length ? '<div class="memory-empty"><strong>남은 후보가 없습니다.</strong><p>제외 조건을 해제하거나 검색 조건을 바꿔 주세요.</p></div>' : '';
    return `<section class="memory-answer"><header class="memory-result-intro"><div><span>과거 판단 기록</span><h3>${escapeHtml(answer.summary)}</h3><p>저장된 판단과 코멘트를 현재 후보에 적용한 결과입니다.</p></div><div class="memory-result-flags"><span>${escapeHtml(answer.reference.kind)}</span><span>현재 탐색만</span></div></header>${answer.nestedAnswer ? renderReverseAgentAnswer(answer.nestedAnswer,turn) : ''}<div class="memory-filter-result">${summary}${empty}${relevantRows}${excludedRows}<div class="form-actions">${!answer.nestedAnswer && result.remaining.length?`<button class="button button--primary button--small" data-action="open-experiment-record" data-turn-id="${turn.id}">실험 기록하기</button>`:''}${answer.canUndo?`<button class="button button--secondary button--small" data-action="memory-undo" data-turn-id="${turn.id}">제외 취소</button>`:''}</div><p class="memory-scope-note">원본 Run과 과거 기록은 변경되지 않습니다.</p></div></section>`;
  }

function renderMemoryRow(s,turn,excluded) {
    return `<div class="memory-row ${excluded?'is-excluded':''}"><div class="memory-row-main"><span class="memory-row-status">${excluded?'제외':'유지'}</span><div><strong>${escapeHtml(s.runId)}</strong><p>${escapeHtml(s.status)}${s.mixed?' · 채택·반려 이력이 함께 있습니다. 당시 조건을 확인하세요.':''}</p></div></div><div class="memory-row-actions">${s.entries.length?`<button class="button button--ghost button--small" data-action="memory-evidence" data-turn-id="${turn.id}" data-run-id="${s.runId}">기록 보기 (${s.entries.length})</button>`:''}<button class="button button--ghost button--small" data-action="open-run-detail" data-turn-id="${turn.id}" data-run-id="${s.runId}">Run 상세</button></div></div>`;
  }

function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  }

function signedPercent(metric) {
    if (!metric || metric.percentChange === null) return metric ? metric.percentLabel : 'N/A';
    return `${metric.percentChange > 0 ? '+' : ''}${metric.percentChange.toFixed(1)}%`;
  }

function signedDelta(metric) {
    if (!metric || metric.delta === null || !Number.isFinite(metric.delta)) return 'Δ 계산 불가';
    return `Δ ${metric.delta > 0 ? '+' : ''}${compactNumber(metric.delta)} ${metric.unit || ''}`.trim();
  }

function claimLabel(kind) {
    return {
      OBSERVED: '관찰됨', MANUAL: '문서 근거', INTERPRETATION: '가능한 해석', LIMITATION: '확인 불가',
    }[kind] || kind;
  }

function renderClaim(claim) {
    return `<div class="agent-claim agent-claim--${claim.kind.toLowerCase()}"><span>${claimLabel(claim.kind)}</span><p>${escapeHtml(claim.text)}</p></div>`;
  }

function renderRunActions(turn, runId, variant = 'candidate', runVersionId = null) {
    const versionAttribute = runVersionId ? ` data-run-version-id="${escapeHtml(runVersionId)}"` : '';
    runId = escapeHtml(runId);
    if (variant === 'forward') {
      return `<div class="agent-run-actions agent-run-actions--forward"><div><strong>이 결과에서 더 확인할까요?</strong><span>이 Run을 기준으로 목표 탐색이나 원인 질문을 이어갈 수 있습니다.</span></div><button type="button" data-action="continue-with-run" data-turn-id="${turn.id}" data-run-id="${runId}"${versionAttribute}>이 Run을 기준으로 질문</button><button type="button" data-action="open-run-detail" data-turn-id="${turn.id}" data-run-id="${runId}"${versionAttribute}>상세 데이터</button></div>`;
    }
    return `<div class="agent-run-actions"><button type="button" data-action="continue-with-run" data-turn-id="${turn.id}" data-run-id="${runId}"${versionAttribute}>이 Run으로 이어서 질문</button><button type="button" data-action="open-run-detail" data-turn-id="${turn.id}" data-run-id="${runId}"${versionAttribute}>실험 자세히 보기</button></div>`;
  }

function renderExplanationAnswer(answer) {
    const result = answer.explanation;
    const flux = result.observations.find((item) => item.key === 'ionFlux');
    const energy = result.observations.find((item) => item.key === 'meanIonEnergy');
    const density = result.supportingMetrics.find((item) => item.key === 'electronDensity');
    const conclusion = answer.conclusion || {
      title: '소스 전력 변화가 입자 밀도와 Flux에 더 직접적으로 반영된 것으로 보입니다.',
      detail: '일반적으로 소스 전력은 입자 생성과 Flux에 영향을 주지만, 평균 이온 에너지는 바이어스와 쉬스 전위의 영향도 함께 받습니다.',
      evidence: density ? `이번 비교에서도 전자 밀도 ${signedPercent(density)}와 Ion Flux ${signedPercent(flux)}가 같은 방향으로 변했고, Mean Ion Energy는 ${signedPercent(energy)}로 다르게 반응했습니다.` : '',
      limit: '관찰된 연관성이며, 이 데이터만으로 전체 물리 원인으로 확정할 수는 없습니다.',
    };
    const narrative = answer.narrative && answer.narrative.length ? answer.narrative : [
      { kind: 'principle', title: '왜 이런 차이가 생기나요?', text: conclusion.detail },
      { kind: 'evidence', title: '이번 비교에서는', text: conclusion.evidence },
      { kind: 'boundary', title: '해석할 때 주의할 점', text: conclusion.limit },
    ];
    const detailMetrics = [...result.observations, ...result.supportingMetrics];
    return `<article class="agent-llm-answer agent-explanation-answer"><p class="agent-llm-kicker">가능한 해석</p><h3>${escapeHtml(conclusion.title || '비교 결과를 해석했습니다.')}</h3><p class="agent-llm-intro">일반적인 플라즈마 원리와 이번 실제 Run에서 확인된 변화를 함께 보면 다음처럼 해석할 수 있습니다.</p>
      <ol class="agent-llm-list">${narrative.map((item) => `<li class="is-${item.kind}"><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.text || '')}</p></li>`).join('')}</ol>
      <details class="agent-evidence-details"><summary><span><strong>실제 비교 근거 보기</strong><small>조건표 · 실제 변화량 · 중간 지표</small></span><i aria-hidden="true">⌄</i></summary><div class="agent-evidence-details-body">
        <div class="agent-condition-table" role="table" aria-label="비교 조건"><div role="row"><span role="columnheader">조건</span><span role="columnheader">${result.runPair.before.runId}</span><span role="columnheader">${result.runPair.after.runId}</span><span role="columnheader">상태</span></div>${result.conditionRows.map((row) => `<div role="row" class="${row.changed ? 'is-changed' : ''}"><strong role="cell">${row.label}</strong><span role="cell">${row.before} ${row.unit}</span><span role="cell">${row.after} ${row.unit}</span><em role="cell">${row.changed ? '변경' : '고정'}</em></div>`).join('')}</div>
        <div class="agent-evidence-metrics" role="table" aria-label="관찰된 변화와 중간 지표">${detailMetrics.map((metric) => `<div role="row"><strong role="cell">${metric.label}</strong><span role="cell">${compactNumber(metric.before)} → ${compactNumber(metric.after)} ${metric.unit}</span><b role="cell">${signedDelta(metric)}</b><em role="cell">${signedPercent(metric)}</em></div>`).join('')}</div>
        ${result.claims.filter((claim) => claim.kind === 'MANUAL').map(renderClaim).join('')}
      </div></details></article>`;
  }

function renderConceptAnswer(answer) {
    const concept = answer.concept;
    if (!concept) return '<div class="agent-empty-result"><strong>개념 설명을 준비하지 못했습니다.</strong><p>질문을 조금 더 구체적으로 입력해 주세요.</p></div>';
    return `<article class="agent-llm-answer agent-concept-answer"><p class="agent-llm-kicker">${escapeHtml(concept.eyebrow || '기본 개념')}</p><h3>${escapeHtml(concept.title)}</h3><p class="agent-llm-intro">${escapeHtml(concept.lead)}</p>
      <ol class="agent-llm-list">${concept.sections.map((section) => `<li><strong>${escapeHtml(section.title)}</strong><p>${escapeHtml(section.text)}</p></li>`).join('')}</ol>
      <p class="agent-llm-takeaway"><strong>쉽게 기억하면:</strong> ${escapeHtml(concept.practice)}</p>
      <p class="agent-concept-source">${escapeHtml(concept.sourceNote)}</p></article>`;
  }

function renderForwardAgentAnswer(answer, turn) {
    const run = answer.runSummary;
    if (!run) return `<div class="agent-empty-result"><strong>일치하는 실제 Run이 없습니다.</strong><p>조건을 바꿔 다시 질문해 주세요.</p></div>`;
    const match = answer.conditionMatch || (answer.status === 'EXACT'
      ? { isExact: true, label: '3개 공정 조건 정확히 일치', summary: '요청한 조건 그대로 저장된 실제 Run' }
      : { isExact: false, label: '정확히 일치하는 Run 없음', summary: '가장 가까운 실제 Run은 참고용으로만 표시' });
    const originalPressure = answer.originalValues && answer.originalValues.pressure;
    const pressureWasNormalized = originalPressure
      && String(originalPressure.unit || '').toLowerCase() === 'torr'
      && Number(originalPressure.normalizedValue) !== Number(originalPressure.value);
    const normalizationNotice = pressureWasNormalized
      ? `<div class="agent-normalization-note"><strong>단위 변환 확인</strong><span>요청 압력 ${compactNumber(originalPressure.value)} Torr를 ${Number(originalPressure.normalizedValue).toLocaleString('ko-KR')} mTorr로 변환해 조회했습니다. 8 mTorr로 해석하지 않았습니다.</span></div>`
      : '';
    return `<div class="agent-compact-answer"><div class="agent-forward-conclusion ${match.isExact ? '' : 'is-reference'}"><div><span>${match.isExact ? '조회 결과' : '정확 일치 없음'}</span><h3>${escapeHtml(run.runId)}</h3><p>${escapeHtml(match.summary || '')}</p></div><div class="agent-condition-verdict"><strong>${escapeHtml(match.label || '')}</strong><small>${match.isExact ? '예측이 아닌 저장된 실제 결과' : '결과가 아닌 참고 후보'}</small></div></div>
      ${normalizationNotice}
      <div class="agent-condition-summary"><div><span>Pressure</span><strong>${run.pressure}</strong><small>mTorr</small></div><div><span>Source Power</span><strong>${run.sourcePower}</strong><small>W</small></div><div><span>Bias Power</span><strong>${run.biasPower}</strong><small>W</small></div></div>
      <div class="agent-delta-grid agent-delta-grid--three"><article><div><span>Ion Flux</span><em class="evidence-kind evidence-kind--observed">관찰됨</em></div><strong>${compactNumber(run.metrics.ionFlux)}</strong><small>10¹⁸ m⁻²s⁻¹</small></article><article><div><span>Mean Ion Energy</span><em class="evidence-kind evidence-kind--observed">관찰됨</em></div><strong>${compactNumber(run.metrics.meanIonEnergy)}</strong><small>eV</small></article><article><div><span>IED Width</span><em class="evidence-kind evidence-kind--observed">관찰됨</em></div><strong>${compactNumber(run.metrics.iedWidth)}</strong><small>eV</small></article></div>${renderRunActions(turn, run.runId, 'forward', run.runVersionId)}</div>`;
  }

function renderCandidateCard(candidate, turn) {
    const conditions = Object.fromEntries(candidate.conditions.map((item) => [item.metric, item]));
    const metrics = Object.fromEntries(candidate.metrics.map((item) => [item.metric, item]));
    const rows = candidate.objectiveRows || [];
    const scores = rows.map((row) => Number.isFinite(row.matchPercent)
      ? row.matchPercent
      : candidate.savedEvaluationsOnly ? null : row.satisfied ? 100 : Math.round(Math.max(0, 100 - Math.abs(Number(row.percentDelta) || 100))));
    const matchPercent = Number.isFinite(candidate.matchPercent)
      ? candidate.matchPercent
      : candidate.savedEvaluationsOnly ? null : scores.length ? Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length) : 0;
    const matchSummary = candidate.matchSummary || `${candidate.satisfiedCount || 0}개 목표 충족 · 저장된 이전 대화`;
    const scoreSummary = rows.length
      ? `<div class="agent-fit-score"><span>검색값 근접도</span><strong>${candidate.proximityUnavailable ? '비가용' : `${matchPercent}%`}</strong><small>${escapeHtml(matchSummary)}</small></div>`
      : '<div class="agent-fit-score agent-fit-score--direction"><span>정렬 기준</span><strong>목표 방향</strong><small>실제 측정값 순서</small></div>';
    const scoreMeter = rows.length && !candidate.proximityUnavailable
      ? `<div class="agent-match-meter" aria-label="검색값 근접도 ${matchPercent}%"><i style="width:${matchPercent}%"></i></div>`
      : '';
    return `<article class="agent-fit-card ${turn.ui.selectedCandidateRunId === candidate.runId ? 'is-selected' : ''}"><div class="agent-fit-card-selectable" data-action="select-candidate-card" data-turn-id="${turn.id}" data-run-id="${escapeHtml(candidate.runId)}"${candidate.runVersionId ? ` data-run-version-id="${escapeHtml(candidate.runVersionId)}"` : ''} role="button" tabindex="0" aria-pressed="${turn.ui.selectedCandidateRunId === candidate.runId}"><header><div><span>검증된 실제 Run</span><strong>${escapeHtml(candidate.runId)}</strong></div>${scoreSummary}</header>${scoreMeter}<p class="agent-card-conditions">${conditions.pressure.value} mTorr · Source ${conditions.sourcePower.value} W · Bias ${conditions.biasPower.value} W</p>
      <div class="agent-card-metrics"><span><small>Ion Flux</small><strong>${metrics.ionFlux.value}</strong></span><span><small>Mean Energy</small><strong>${metrics.meanIonEnergy.value} eV</strong></span><span><small>IED Width</small><strong>${metrics.iedWidth.value} eV</strong></span></div>
      <div class="agent-fit-rows">${rows.map((row, index) => `<div class="${row.satisfied ? 'is-satisfied' : 'is-missed'}"><span>${row.label}</span><strong>${row.actualLabel} ${row.unit}</strong><small>목표 ${escapeHtml(row.targetLabel)}</small><b><span title="${escapeHtml(row.referenceLabel || '검색 기준 대비')}">${candidate.proximityUnavailable || scores[index] === null ? '근접도 비가용' : `${scores[index]}% 근접`}</span><span>${escapeHtml(row.differenceLabel)}</span></b></div>`).join('')}</div>
      ${candidate.baselineRows.length ? `<div class="agent-baseline-delta">${renderRunChip(candidate.baselineRunId || turn.contextRunId || 'Run')}${candidate.baselineRows.map((row) => `<small>${row.label} <b>${escapeHtml(row.deltaLabel)}${row.percentLabel ? ` (${escapeHtml(row.percentLabel)})` : ''}</b></small>`).join('')}</div>` : ''}</div>
      ${renderRunActions(turn, candidate.runId, 'candidate', candidate.runVersionId)}</article>`;
  }

function renderReverseAgentAnswer(answer, turn) {
    if (answer.status !== 'MATCH' && !(answer.showIndependentGroups && answer.candidateGroups?.groups.some(group => group.candidates.length))) {
      return `<div class="agent-compact-answer"><div class="agent-result-intro"><div><span>검색 결과</span><h3>필수 조건을 만족하는 실제 Run이 없습니다</h3><p>필수 조건은 후보 순위보다 먼저 적용됩니다.</p></div><div class="agent-result-flags"><span>0개 일치</span><span>조건 우회 없음</span></div></div>
        <div class="agent-search-summary agent-search-summary--constraints"><div class="agent-objectives">${(answer.constraints || []).map((constraint, index) => {
          const metricLabel = viewModels.METRIC_META && viewModels.METRIC_META[constraint.metric]
            ? viewModels.METRIC_META[constraint.metric].label
            : constraint.metric;
          const target = viewModels.constraintTargetLabel ? viewModels.constraintTargetLabel(constraint) : constraint.label || '';
          return `<span><b>필수 ${index + 1}</b>${escapeHtml(`${metricLabel} ${target}`.trim())}</span>`;
        }).join('')}</div><p class="agent-similarity-note"><strong>처리 결과</strong><span>조건을 벗어난 Run은 후보로 표시하지 않았습니다.</span></p></div>
        <div class="agent-empty-result"><strong>일치 결과 0개</strong><p>필수 조건을 완화하거나 다른 목표로 다시 질문해 주세요.</p></div></div>`;
    }
    const model = answer.candidateGroups || { groups: [], activeGroupId: 'results', conflictSummary: null, viewportCardCount: 6 };
    const activeId = turn.ui.activeCandidateGroup || model.activeGroupId;
    const active = model.groups.find((group) => group.id === activeId) || model.groups[0];
    if (!active) return `<div class="agent-empty-result"><strong>조건을 만족하는 후보가 없습니다.</strong><p>목표 범위를 완화해 다시 질문해 주세요.</p></div>`;
    const visibleObjectives = (answer.objectives || []).filter((objective) => !(answer.constraints || []).some((constraint) => constraint.metric === objective.metric));
    const currentSortNote = answer.showCurrentSortNote === false ? '' : `<p class="agent-similarity-note"><strong>현재 정렬</strong><span>${escapeHtml(active.sortLabel || '검색값 근접도 높은순')} · 결과를 임의로 3개로 줄이지 않습니다.</span></p>`;
    return `<div class="agent-compact-answer">${answer.interpretationNote ? `<div class="agent-interpretation-note"><strong>조건 해석</strong><p>${escapeHtml(answer.interpretationNote)}</p></div>` : ''}<div class="agent-result-intro"><div><span>실제 Run 탐색</span><h3>${model.groups[0].candidates.length ? `조건 일치 결과 ${model.groups[0].candidates.length}개` : '조건 일치 결과 없음'}</h3><p>수치 조건으로 조회한 뒤 요청한 방향으로 정렬했습니다.</p></div><div class="agent-result-flags"><span>실제 데이터</span><span>전체 결과</span></div></div>
      <div class="agent-search-summary"><div class="agent-objectives">${[
        ...(answer.constraints || []).map((constraint) => ({ kind: '검색 조건', label: `${viewModels.METRIC_META[constraint.metric] ? viewModels.METRIC_META[constraint.metric].label : constraint.metric} ${viewModels.constraintTargetLabel(constraint)}` })),
        ...(answer.goals || []).map((goal) => ({ kind: '정렬', label: `${viewModels.METRIC_META[goal.metric] ? viewModels.METRIC_META[goal.metric].label : goal.metric} ${goal.direction === 'MIN' ? '낮은순' : goal.direction === 'TARGET_RANGE' ? '범위 근접순' : '높은순'}` })),
        ...visibleObjectives.map((objective) => ({ kind: '검색 조건', label: objective.label })),
      ].map((item) => `<span><b>${item.kind}</b>${escapeHtml(item.label)}</span>`).join('')}</div>${currentSortNote}</div>
      <div class="agent-candidate-tabs" role="tablist" aria-label="목표별 실제 후보">${model.groups.map((group) => `<button type="button" role="tab" aria-selected="${group.id === active.id}" aria-controls="candidate-panel-${turn.id}" class="${group.id === active.id ? 'is-active' : ''}" data-action="candidate-group" data-turn-id="${turn.id}" data-group-id="${group.id}">${escapeHtml(group.label)}</button>`).join('')}</div>${active.notice ? `<p class="agent-interpretation-note">${escapeHtml(active.notice)}</p>` : ''}
      <div id="candidate-panel-${turn.id}" class="agent-fit-grid agent-fit-grid--scroll" role="tabpanel" tabindex="0" aria-label="${escapeHtml(active.label)}. 한 화면에 최대 ${model.viewportCardCount || 6}개 카드 표시">${active.candidates.length ? active.candidates.map((candidate) => renderCandidateCard(candidate, turn)).join('') : `<div class="agent-conflict"><strong>조건 일치 결과가 없습니다</strong><p>${escapeHtml(model.conflictSummary || '조건별 결과를 확인하거나 검색 범위를 조정해 주세요.')}</p></div>`}</div>
      <div class="agent-result-footer"><p>${active.candidates.length}개 결과 전체 · 한 화면 최대 ${model.viewportCardCount || 6}개 · 내부 스크롤</p><div class="agent-result-footer-actions">${active.candidates.length > 1 ? `<button class="button button--secondary button--small" type="button" data-action="reference-candidate-group" data-turn-id="${turn.id}">전체 후보 기준 질문</button>` : ''}${model.groups[0].candidates.length ? `<button class="button button--primary button--small" type="button" data-action="open-experiment-record" data-turn-id="${turn.id}">실험 기록하기</button>` : ''}</div></div></div>`;
  }

function renderAgentAnswer(answer, turn) {
    if (answer.intent === 'RECORD_REUSE') return renderMemoryAnswer(answer,turn);
    if (answer.intent === 'CHANGE_EXPLANATION' && answer.status === 'READY') return renderExplanationAnswer(answer);
    if (answer.intent === 'CONCEPT_EXPLANATION' && answer.status === 'READY') return renderConceptAnswer(answer);
    if (answer.intent === 'FORWARD_LOOKUP') return renderForwardAgentAnswer(answer, turn);
    if (answer.intent === 'REVERSE_SEARCH') return renderReverseAgentAnswer(answer, turn);
    if (answer.intent === 'CLARIFICATION') {
      const labels = { pressure: '압력', sourcePower: '소스 전력', biasPower: '바이어스 전력', changeValues: '변경 전·후값', numericRange: '수치 또는 범위 조건' };
      return `<div class="agent-scope-message agent-clarification"><span class="evidence-kind evidence-kind--interpretation">추가 확인</span><h3>실제 Run을 찾으려면 조건이 더 필요합니다</h3><p>${escapeHtml(answer.summary)}</p><div>${(answer.missingConditions || []).map((key) => `<span class="clarification-chip">${labels[key] || escapeHtml(key)}</span>`).join('')}</div></div>`;
    }
    return `<div class="agent-scope-message"><span class="evidence-kind evidence-kind--limitation">지원 범위 안내</span><h3>이 질문은 현재 프로토타입에서 답하지 않습니다</h3><p>${escapeHtml(answer.summary)}</p><div>${(answer.suggestions || []).map((item) => `<button type="button" data-action="agent-use-suggestion" data-prompt="${escapeHtml(item.text)}">${escapeHtml(item.label)} 예시</button>`).join('')}</div></div>`;
  }

function renderRunChip(runId) {
    return `<span class="run-context-chip"><i aria-hidden="true"></i><strong>${escapeHtml(runId)}</strong></span>`;
  }
export {renderAgentAnswer};
