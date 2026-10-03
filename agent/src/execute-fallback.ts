import type { AgentContext, AgentRequest, AgentResponse, FullRun, Intent, RunRef, RunSummary, Snapshot, Conditions, JsonValue } from './contracts/index.js';
import * as engineModule from './fallback/engine.js';
import * as explanationModule from './fallback/explanation-engine.js';
import * as viewModelsModule from './fallback/view-models.js';
import { entries } from './fallback/manual-evidence.js';
import { contextualAgentRequest } from './fallback/contextual-request.js';
import { compactAgentAnswer } from './fallback/answer-snapshot.js';
import { executeMemoryQuestion } from './fallback/memory-request.js';
// Legacy algorithms accept their original query/result shapes inside this typed boundary.
const engine = engineModule;
const explanation = explanationModule;
const viewModels = viewModelsModule;
const keys = ['pressure', 'sourcePower', 'biasPower'] as const;
const asRef = (run: RunRef): RunRef => ({ runId: run.runId, runVersionId: run.runVersionId });

/** Latest summaries are searchable; explicitly referenced versions are resolved separately. */
export async function executeFallback(input: AgentRequest, context: AgentContext): Promise<AgentResponse> {
  const loaded = new Map<string, FullRun>(context.referenceRunsByVersion);
  async function hydrate(reference: RunRef): Promise<FullRun> {
    const run = loaded.get(reference.runVersionId) ?? await context.hydrateFullRun(reference);
    if (run.runId !== reference.runId || run.runVersionId !== reference.runVersionId) {
      throw new Error('Hydrated Run does not match its requested version reference.');
    }
    loaded.set(reference.runVersionId, run);
    return run;
  }
  const baseline = input.baseline ? await hydrate(input.baseline) : null;
  const references = await Promise.all(input.candidateReferences.map(hydrate));
  // Preserve original Run-ID matching in explicit references while keeping latest search independent.
  const explicit = [baseline, ...references].filter((run): run is FullRun => run !== null);
  const byId = new Map<string, RunSummary>();
  for (const run of [...explicit, ...context.candidateRunsLatest]) if (!byId.has(run.runId)) byId.set(run.runId, run);
  const reference = input.candidateReferences.length
    ? { kind: input.candidateReferences.length === 1 ? '단일 Run' : '후보 집합', ids: input.candidateReferences.map(r => r.runId) }
    : baseline ? { kind: '단일 Run', ids: [baseline.runId] } : null;
  const options = input.clarification ?? {};
  const memoryAnswer: Snapshot | null = executeMemoryQuestion(input.text, context.candidateRunsLatest, context.decisionRecords, reference, baseline?.runId ?? null,
    typeof options.threshold === 'number' || options.threshold === null ? options.threshold : undefined, undefined, options.undo === true);
  if (memoryAnswer) return response('RECORD_REUSE', typeof memoryAnswer.status === 'string' ? memoryAnswer.status : (memoryAnswer.notice || memoryAnswer.pendingThreshold ? 'NEEDS_INPUT' : 'READY'), memoryAnswer);

  const request = contextualAgentRequest(input.text, baseline, context.candidateRunsLatest, options);
  let result: unknown = null;
  if (request.intent === 'FORWARD_LOOKUP') {
    const forward = engine.searchForward(request.query.conditions, request.contextRunId && baseline ? [baseline] : context.candidateRunsLatest);
    // Snapshot needs source-file count, but no full data is persisted.
    result = forward.run ? { ...forward, run: await hydrate(asRef(forward.run)) } : forward;
  } else if (request.intent === 'REVERSE_SEARCH') {
    request.query.confirmed = true;
    const validation = engine.validateQuery(request.query);
    if (validation.ok) {
      request.query = { ...validation.normalizedQuery, confirmed: true };
      result = engine.searchReverse(request.query, context.candidateRunsLatest);
    } else result = { status: 'INVALID', errors: validation.errors, objectives: request.query.objectives || [] };
  } else if (request.intent === 'CHANGE_EXPLANATION') {
    const comparison = request.comparison as Comparison;
    const runs = [...byId.values()];
    let pair: (RunSummary | undefined)[];
    if (comparison.beforeRunId && comparison.afterRunId) {
      pair = [byId.get(comparison.beforeRunId), byId.get(comparison.afterRunId)];
    } else {
      const changed = comparison.changedCondition;
      const fixed = keys.filter(key => key !== changed);
      const matches = (run: RunSummary) => fixed.every(key => Number(run[key]) === Number(comparison[key]));
      pair = [runs.find(run => matches(run) && Number(changed ? run[changed] : undefined) === Number(comparison.fromValue)),
        runs.find(run => matches(run) && Number(changed ? run[changed] : undefined) === Number(comparison.toValue))];
    }
    const fullPair = await Promise.all(pair.filter((run): run is RunSummary => Boolean(run)).map(run => hydrate(asRef(run))));
    result = explanation.buildControlledExplanation(request, fullPair, [...entries]);
  }
  const fullAnswer = viewModels.buildAgentAnswerModel(request, result);
  const snapshot = compactAgentAnswer(fullAnswer, request, result, baseline);
  return response(request.intent, fullAnswer.status, snapshot, request.intent === 'REVERSE_SEARCH' || (request.intent === 'FORWARD_LOOKUP' && !request.contextRunId));

  function response(intent: Intent, status: string, answerSnapshot: Snapshot, searchedLatest = false): AgentResponse {
    const candidateIds = stringIds(answerSnapshot.runIds);
    const nested = object(answerSnapshot.nestedAnswer);
    const groups = object(answerSnapshot.candidateGroups) ?? object(nested?.candidateGroups);
    const memory = object(answerSnapshot.memoryResult);
    const ids = [...candidateIds,
      ...objects(groups?.groups).flatMap(group => objects(group.candidates).flatMap(run => typeof run.runId === 'string' ? [run.runId] : [])),
      ...objects(memory?.excluded).flatMap(run => typeof run.runId === 'string' ? [run.runId] : [])];
    // Numeric record search always resolves latest results; scoped record reuse resolves explicit versions.
    const versionSource = searchedLatest || (intent === 'RECORD_REUSE' && answerSnapshot.numeric) ? new Map(context.candidateRunsLatest.map(r => [r.runId, r])) : byId;
    const resolved = (id: string) => versionSource.get(id);
    const candidates = candidateIds.map(resolved).filter((r): r is RunSummary => Boolean(r)).map(asRef);
    // Pending/notice answers retain selected context even when no result IDs exist.
    // Resolve this context from explicit versions, independently of latest searched candidates.
    const contextIds = new Set(stringIds(object(answerSnapshot.reference)?.ids));
    const contextRefs = references.filter(run => contextIds.has(run.runId)).map(asRef);
    const used = [...(baseline ? [asRef(baseline)] : []), ...contextRefs,
      ...ids.map(resolved).filter((r): r is RunSummary => Boolean(r)).map(asRef)];
    const usedRunRefs = [...new Map(used.map(r => [r.runVersionId, r])).values()];
    return { intent, status, candidates, explanation: object(answerSnapshot.explanation) ?? null, answerSnapshot, usedRunRefs };
  }
}

type Comparison = Partial<Conditions> & { beforeRunId?: string; afterRunId?: string; changedCondition?: keyof Conditions; fromValue?: number; toValue?: number };
function object(value: JsonValue | undefined): Snapshot | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value : undefined;
}
function objects(value: JsonValue | undefined): Snapshot[] {
  return Array.isArray(value) ? value.map(object).filter((entry): entry is Snapshot => entry !== undefined) : [];
}
function stringIds(value: JsonValue | undefined): string[] {
  return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : [];
}
