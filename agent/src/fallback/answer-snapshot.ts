/* eslint-disable @typescript-eslint/no-explicit-any -- Original polymorphic JS query/result boundary; public executeFallback remains contract typed. */
import * as viewModelsModule from './view-models.js';
const viewModels: any = viewModelsModule;
// Original compactAgentAnswer projection intentionally excludes graphs and full Runs.
function compactRun(run: any) {
  if (!run) return null;
  return {
    runId: run.runId,
    pressure: run.pressure,
    sourcePower: run.sourcePower,
    biasPower: run.biasPower,
    metrics: { ...run.metrics },
    qualityStatus: run.qualityStatus,
    convergenceStatus: run.convergenceStatus,
    sourceFileCount: (run.sourceFiles || []).length,
  };
}

export function compactAgentAnswer(answer: any, request: any, result: any, baselineRun: any) {
  const base = {
    intent: answer.intent,
    analysisLabel: answer.analysisLabel,
    status: answer.status,
    summary: answer.summary,
    verifiedOnly: true,
    runIds: [...(answer.runIds || [])],
    actions: JSON.parse(JSON.stringify(answer.actions || [])),
    interpretationNote: request.interpretationNote || null,
  };
  if (request.intent === 'FORWARD_LOOKUP') {
    return {
      ...base,
      runSummary: compactRun(result && result.run),
      requestedConditions: result && result.requestedConditions,
      originalValues: JSON.parse(JSON.stringify(request.query.originalValues || {})),
      deltas: result && result.deltas,
      conditionMatch: answer.conditionMatch ? JSON.parse(JSON.stringify(answer.conditionMatch)) : null,
    };
  }
  if (request.intent === 'REVERSE_SEARCH') {
    return {
      ...base,
      processMode: request.query.processMode,
      constraints: JSON.parse(JSON.stringify(request.query.constraints || [])),
      goals: JSON.parse(JSON.stringify(request.query.goals || [])),
      objectives: JSON.parse(JSON.stringify((result && result.objectives) || request.query.objectives || [])),
      constraintLookup: null,
      candidateGroups: viewModels.buildReverseGroupsModel(result, baselineRun),
    };
  }
  if (request.intent === 'CHANGE_EXPLANATION' && result && result.status === 'READY') {
    return {
      ...base,
      explanation: {
        runPair: { before: { runId: result.runPair.before.runId }, after: { runId: result.runPair.after.runId } },
        conditionRows: JSON.parse(JSON.stringify(result.conditionRows || [])),
        observations: JSON.parse(JSON.stringify(result.observations || [])),
        supportingMetrics: JSON.parse(JSON.stringify(result.supportingMetrics || [])),
        claims: JSON.parse(JSON.stringify(result.claims || [])),
      },
      conclusion: answer.conclusion ? JSON.parse(JSON.stringify(answer.conclusion)) : null,
      narrative: JSON.parse(JSON.stringify(answer.narrative || [])),
    };
  }
  if (request.intent === 'CONCEPT_EXPLANATION') {
    return {
      ...base,
      verifiedOnly: false,
      concept: answer.concept ? JSON.parse(JSON.stringify(answer.concept)) : null,
    };
  }
  return { ...base, missingConditions: answer.missingConditions || [], suggestions: answer.suggestions || [] };
}
