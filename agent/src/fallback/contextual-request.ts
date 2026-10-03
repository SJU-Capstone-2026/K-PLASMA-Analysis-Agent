/* eslint-disable @typescript-eslint/no-explicit-any -- Original polymorphic JS query/result boundary; public executeFallback remains contract typed. */
import type { RunSummary } from '../contracts/index.js';
import * as engineModule from './engine.js';
import * as agentModule from './agent-engine.js';
const engine: any = engineModule;
const agent: any = agentModule;
// Extracted from app.js; preserve ordering of contextual rules before classifier.
export function contextualAgentRequest(text: string, activeRun: RunSummary | null, runs: RunSummary[], options: any = {}): any {
  const raw = String(text || '').trim();
  if (activeRun && /(?:이\s*run|해당\s*run|전체\s*결과|분포\s*(?:보여|조회))/i.test(raw)) {
    const query = engine.buildForwardRequest({
      pressure: activeRun.pressure,
      sourcePower: activeRun.sourcePower,
      biasPower: activeRun.biasPower,
    }, raw);
    return { intent: 'FORWARD_LOOKUP', label: '조건 조회', originalText: raw, query, contextRunId: activeRun.runId };
  }
  if (activeRun && /(?:energy|에너지).*(?:조금|좀).*(?:높|올)|(?:조금|좀).*(?:높|올).*(?:energy|에너지)/i.test(raw)) {
    const min = Math.round((activeRun.metrics.meanIonEnergy + 5) * 10) / 10;
    const max = Math.round((activeRun.metrics.meanIonEnergy + 20) * 10) / 10;
    return {
      intent: 'REVERSE_SEARCH',
      label: '후보 탐색',
      originalText: raw,
      contextRunId: activeRun.runId,
      interpretationNote: `“조금 더 높은”을 기준 Run 대비 +5~20 eV (${min}–${max} eV)로 해석했습니다.`,
      query: {
        id: `QUERY-CONTEXT-${Date.now()}`,
        originalText: raw,
        analysisType: 'REVERSE',
        processMode: 'GOAL_RECOMMENDATION',
        constraints: [{
          metric: 'meanIonEnergy', operator: 'RANGE', min, max, unit: 'eV',
        }],
        goals: [],
        objectives: [{
          id: 'objective-1-meanIonEnergy', metric: 'meanIonEnergy', operator: 'RANGE', min, max,
          unit: 'eV', label: `Mean Ion Energy ${min}–${max} eV`,
        }],
        baselineRunId: activeRun.runId,
        confirmed: true,
        modified: false,
      },
    };
  }
  if (activeRun && /flux|플럭스/i.test(raw) && /유지/i.test(raw) && /ied|폭/i.test(raw) && /낮|좁/i.test(raw)) {
    const flux = activeRun.metrics.ionFlux;
    return {
      intent: 'REVERSE_SEARCH', label: '후보 탐색', originalText: raw, contextRunId: activeRun.runId,
      interpretationNote: '“Flux 유지”를 기준 Run의 ±5%, “IED Width 낮게”를 기준값 이하로 해석했습니다.',
      query: {
        id: `QUERY-CONTEXT-${Date.now()}`, originalText: raw, analysisType: 'REVERSE', processMode: 'GOAL_RECOMMENDATION',
        constraints: [], goals: [], baselineRunId: activeRun.runId, confirmed: true, modified: false,
        objectives: [
          { id: 'objective-1-ionFlux', metric: 'ionFlux', operator: 'RANGE', min: flux * 0.95, max: flux * 1.05, unit: '10¹⁸ m⁻²s⁻¹', label: 'Ion Flux 기준 대비 ±5%' },
          { id: 'objective-2-iedWidth', metric: 'iedWidth', operator: 'MAX', value: activeRun.metrics.iedWidth, unit: 'eV', label: 'IED Width 기준값 이하' },
        ],
      },
    };
  }
  if (activeRun && agent.shouldExplainActiveRun(raw)) {
    const comparisonRuns = runs
      .filter((run) => run.runId !== activeRun.runId
        && run.pressure === activeRun.pressure
        && run.biasPower === activeRun.biasPower)
      .sort((a, b) => {
        const aLower = a.sourcePower < activeRun.sourcePower ? 0 : 1;
        const bLower = b.sourcePower < activeRun.sourcePower ? 0 : 1;
        return aLower - bLower || Math.abs(activeRun.sourcePower - a.sourcePower) - Math.abs(activeRun.sourcePower - b.sourcePower);
      });
    if (comparisonRuns[0]) {
      return {
        intent: 'CHANGE_EXPLANATION',
        label: '변화 설명',
        originalText: raw,
        contextRunId: activeRun.runId,
        comparison: { beforeRunId: comparisonRuns[0].runId, afterRunId: activeRun.runId },
      };
    }
  }
  return agent.classifyRequest(raw, options);
}
