/* eslint-disable @typescript-eslint/no-explicit-any -- Original polymorphic JS query/result boundary; public executeFallback remains contract typed. */
import type { RunSummary, DecisionRecord } from '../contracts/index.js';
import * as reuseModule from './record-reuse.js';
import * as agentModule from './agent-engine.js';
import * as engineModule from './engine.js';
import * as viewModelsModule from './view-models.js';
import { compactAgentAnswer } from './answer-snapshot.js';
const reuse: any = reuseModule;
const agent: any = agentModule;
const engine: any = engineModule;
const viewModels: any = viewModelsModule;
// Pure orchestration extracted from executeMemoryQuestion in app.js.
export function executeMemoryQuestion(text: string, runs: RunSummary[], records: DecisionRecord[], candidateReference: any, activeRunId: string | null, thresholdOverride?: number | null, suppliedReference?: any, undo = false, latestCandidateReference?: any): any {
  const parsed = reuse.parse(text);
  if (!parsed) return null;
  if (parsed.exclude && !/(비용|원가|가격)/.test(text)) {
    return {intent:'RECORD_REUSE',runIds:[],summary:'기록 조건 확인 필요',notice:'현재 시연에서는 비용 사유가 명확한 반려 기록만 자동 제외합니다. 다른 사유는 기록 원문을 확인해 주세요.'};
  }
  const numeric = /(?:flux|플럭스|에너지|energy|압력|pressure|source(?:\s*power)?|소스(?:\s*전력)?|bias(?:\s*power)?|바이어스)\s*(?:가|는|이)?\s*\d/i.test(text);
  const mentionedCandidateSet = !numeric && /(?:이\s*)?후보(?:들|군)/.test(text) ? latestCandidateReference : null;
  const reference = suppliedReference || mentionedCandidateSet || candidateReference || (activeRunId ? {ids:[activeRunId],kind:'단일 Run'} : null);
  const threshold = thresholdOverride === undefined ? parsed.threshold : thresholdOverride;
  const scopeIds = numeric ? runs.map((r: any)=>r.runId) : reference ? reference.ids : [];
  const base = {intent:'RECORD_REUSE',analysisLabel:'과거 기록 활용',runIds:[],summary:'과거 판단 기록을 확인했습니다.',reference:reference || {kind:'전체 실제 Run 검색',ids:[]},memoryRequest:{text,reference,threshold},numeric};
  if (parsed.exclude && threshold !== null && (!Number.isInteger(threshold) || threshold<1)) {
    return {...base,notice:'제외 기준은 1건 이상의 정수로 입력해 주세요. 후보를 제외하지 않았습니다.'};
  }
  if (!numeric && !scopeIds.length) {
    return {...base,notice:'먼저 후보 탐색을 실행하거나 결과의 전체 후보를 질문 대상으로 선택해 주세요.'};
  }
  if (parsed.exclude && threshold === null && !undo) {
    return {...base,pendingThreshold:true,summary:'제외할 기록 건수를 선택해 주세요.'};
  }
  const filtered = reuse.filter(records,scopeIds,undo || !parsed.exclude ? Infinity : threshold);
  let nestedAnswer: any = null;
  if (numeric) {
    const clean = text.replace(/(?:[,，]?\s*(?:비용|원가|가격)\s*(?:때문|으로|반려)[\s\S]*)$/,'').replace(/찾되|하되/g,'찾아줘').replace(/(?<!ion\s)\bflux\b/ig,'Ion Flux') + ' 실제 Run 찾아줘';
    const request = agent.classifyRequest(clean);
    if (request.intent !== 'REVERSE_SEARCH') { return {...base,notice:'수치 조건을 해석하지 못했습니다. 예: Flux가 500 이상인 후보를 찾되, 비용 때문에 반려된 건 제외해줘.'}; }
    const validation = engine.validateQuery({...request.query,confirmed:true});
    if (!validation.ok) { return {...base,notice:'수치 조건을 확인해 주세요. 기록 조건은 적용하지 않았습니다.'}; }
    request.query = {...validation.normalizedQuery,confirmed:true};
    const eligible = new Set(filtered.remaining.map((r: any)=>r.runId));
    const result = engine.searchReverse(request.query,runs.filter((r: any)=>eligible.has(r.runId)));
    nestedAnswer = compactAgentAnswer(viewModels.buildAgentAnswerModel(request,result),request,result,null);
    // Report exclusions only among Runs satisfying the numeric search, before ranking.
    const constraintOnly = {...request.query,goals:[],objectives:[],processMode:'CONSTRAINT_LOOKUP'};
    const unfiltered = engine.searchReverse(constraintOnly,runs);
    const validIds = new Set((unfiltered.allMatches || []).map((r: any)=>r.runId));
    filtered.excluded = filtered.excluded.filter((r: any)=>validIds.has(r.runId));
    const shown = new Set(nestedAnswer.constraintLookup ? nestedAnswer.constraintLookup.matches.map((r: any)=>r.runId) : nestedAnswer.runIds);
    filtered.remaining = filtered.remaining.filter((r: any)=>shown.has(r.runId));
  }
  const resultSummary = undo
    ? '제외 조건을 해제했습니다.'
    : parsed.exclude
      ? filtered.excluded.length
        ? `비용 반려 ${threshold}건 이상이 확인된 후보 ${filtered.excluded.length}개를 제외했습니다.`
        : `비용 반려 ${threshold}건 이상이 확인된 후보는 없습니다.`
      : '이 Run의 과거 판단과 사유입니다.';
  return {...base,nestedAnswer,memoryResult:filtered,runIds:filtered.remaining.map((r: any)=>r.runId),canUndo:parsed.exclude && !undo,summary:resultSummary};
}
