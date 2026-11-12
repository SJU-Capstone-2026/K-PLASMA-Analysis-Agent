import type { RunRef } from './index.js';

type Json = null | string | number | boolean | Json[] | { [key: string]: Json };
type ExecutionStatus = 'COMPLETE' | 'PARTIAL' | 'FAILED';
type ReviewStatus = 'PASS' | 'ISSUE' | 'UNAVAILABLE' | 'SKIPPED';
type StepStatus = 'verified' | 'empty' | 'partial' | 'blocked' | 'failed' | 'skipped';

export interface V3StepResult {
  executionId: string;
  stepId: string;
  status: StepStatus;
  outputs: Record<string, Json>;
  runRefs: RunRef[];
  groupId: string | null;
  reason: string | null;
}

export interface V3Review {
  status: ReviewStatus;
  answers: {
    name: 'request_coverage' | 'evidence_alignment' | 'interpretation_scope';
    choice: string;
    probabilities: Record<string, number>;
    confidence: number | null;
  }[];
  reason: string | null;
}

export interface GraphV3AnswerSnapshotV1 {
  implementationId: 'v3';
  graphVersion: 'v3';
  executionMode: StoredV3Options;
  decisionEvidence?: V3DecisionEvidence[];
  schemaVersion: 1;
  intent: 'COMPOSITE_ANSWER' | 'GENERAL_ANSWER';
  question: string;
  confirmedContext: Record<string, Json>;
  planRevision: number | null;
  stepResults: V3StepResult[];
  evidence: { id: string; executionId: string; field: string; value: Json; unit: string | null; runRef: RunRef | null }[];
  draft: Record<string, Json> | null;
  answer: string;
  executionStatus: ExecutionStatus;
  hasIncompleteWork?: boolean;
  review: V3Review;
  budget: {
    replans_used: number;
    answer_rewrites_used: number;
    partial_finalizations_used: number;
    model_requests_used: number;
    tool_invocations_used: number;
    active_elapsed_seconds: number;
  };
}

const record = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);
const string = (v: unknown): v is string => typeof v === 'string';
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const nullableString = (v: unknown) => v === null || string(v);
const runRef = (v: unknown) => record(v) && string(v.runId) && string(v.runVersionId);
const oneOf = (v: unknown, values: string[]) => string(v) && values.includes(v);
const json = (v: unknown): v is Json => v === null || string(v) || finite(v) || typeof v === 'boolean'
  || (Array.isArray(v) ? v.every(json) : record(v) && Object.values(v).every(json));
const jsonRecord = (v: unknown) => record(v) && Object.values(v).every(json);

export function isGraphV3AnswerSnapshot(value: unknown): value is GraphV3AnswerSnapshotV1 {
  if (!record(value) || value.implementationId !== 'v3' || value.graphVersion !== 'v3' || value.schemaVersion !== 1
      || !isStoredV3Options(value.executionMode)
      || !(value.decisionEvidence === undefined || Array.isArray(value.decisionEvidence) && value.decisionEvidence.every(isV3DecisionEvidence))
      || !oneOf(value.intent, ['COMPOSITE_ANSWER', 'GENERAL_ANSWER'])
      || !string(value.question) || !string(value.answer) || !jsonRecord(value.confirmedContext)
      || !(value.planRevision === null || finite(value.planRevision) && Number.isInteger(value.planRevision)
        && value.planRevision >= 1)
      || !(value.draft === null || jsonRecord(value.draft))
      || !(value.hasIncompleteWork === undefined || typeof value.hasIncompleteWork === 'boolean')
      || !oneOf(value.executionStatus, ['COMPLETE', 'PARTIAL', 'FAILED'])) return false;
  const { stepResults, evidence, review, budget } = value;
  return Array.isArray(stepResults) && stepResults.every(s => record(s)
      && string(s.executionId) && string(s.stepId) && jsonRecord(s.outputs)
      && oneOf(s.status, ['verified', 'empty', 'partial', 'blocked', 'failed', 'skipped'])
      && Array.isArray(s.runRefs) && s.runRefs.every(runRef) && nullableString(s.groupId) && nullableString(s.reason))
    && Array.isArray(evidence) && evidence.every(e => record(e)
      && string(e.id) && string(e.executionId) && string(e.field)
      && json(e.value) && nullableString(e.unit) && (e.runRef === null || runRef(e.runRef)))
    && record(review) && oneOf(review.status, ['PASS', 'ISSUE', 'UNAVAILABLE', 'SKIPPED'])
    && nullableString(review.reason) && Array.isArray(review.answers) && review.answers.every(a => record(a)
      && oneOf(a.name, ['request_coverage', 'evidence_alignment', 'interpretation_scope']) && string(a.choice)
      && record(a.probabilities) && Object.values(a.probabilities).every(p => finite(p) && p >= 0 && p <= 1)
      && (a.confidence === null || finite(a.confidence) && a.confidence >= 0 && a.confidence <= 1))
    && record(budget) && finite(budget.active_elapsed_seconds) && budget.active_elapsed_seconds >= 0
    && Object.entries({replans_used: 2, answer_rewrites_used: 1, partial_finalizations_used: 1,
      model_requests_used: 13, tool_invocations_used: 12}).every(([key, limit]) => {
      const n = budget[key];
      return finite(n) && Number.isInteger(n) && n >= 0 && n <= limit;
    });
}


/** Request-local feature selection. Required only for graph v3. */
export interface V3Options { rulesEnabled: boolean; ragEnabled: boolean }
export interface StoredV3Options extends V3Options { configDigest: string }
export interface V3DecisionEvidenceCitation {
  citationId:string; documentId:string; recordId:string;
  subjectRunId:string|null; recordRunVersionId:string|null;
  attribution:'PER_RUN'|'SHARED_UNASSIGNED'|'REFERENCE_ONLY';
  quote:string; score:number|null; decision:string|null; createdAt:string|null;
  sourceNoteSha256:string; sourceRecordSha256:string;
}
export interface V3DecisionEvidenceRules {
  policy:string; action:string; threshold:number|null;
  perRun:{runId:string;count:number;status:string;mixed:boolean;costRejectionRecordIds:string[]}[];
  excludedRunIds:string[]; remainingRunIds:string[]; completeAggregation:boolean;
}
/** Immutable source snapshots. Rendering never performs a fresh search. */
export interface V3DecisionEvidence {
  schemaVersion:1; kind:'decision_rag'; status:string; synthetic:boolean; answer:string;
  scopeRunRefs:RunRef[]; citations:V3DecisionEvidenceCitation[]; rules:V3DecisionEvidenceRules;
  retrieval:{totalInScope:number;returned:number;model?:string;strategy?:string;minScore?:number;relativeMargin?:number};
  snapshotFingerprint:string; limitations:string[];
}
const strings = (value:unknown):value is string[] => Array.isArray(value) && value.every(string);
export function isStoredV3Options(value:unknown):value is StoredV3Options {
  return record(value) && typeof value.rulesEnabled==='boolean' && typeof value.ragEnabled==='boolean'
    && typeof value.configDigest==='string' && /^[a-f0-9]{64}$/.test(value.configDigest);
}
export function isV3DecisionEvidence(value:unknown):value is V3DecisionEvidence {
  if(!record(value)||value.kind!=='decision_rag'||value.schemaVersion!==1||!string(value.status)
    ||typeof value.synthetic!=='boolean'||!string(value.answer)||!string(value.snapshotFingerprint)
    ||!strings(value.limitations)||!Array.isArray(value.scopeRunRefs)||!value.scopeRunRefs.every(runRef)) return false;
  if(!Array.isArray(value.citations)||!value.citations.every(c=>record(c)
    &&['citationId','documentId','recordId','quote','sourceNoteSha256','sourceRecordSha256'].every(key=>string(c[key]))
    &&nullableString(c.subjectRunId)&&nullableString(c.recordRunVersionId)&&nullableString(c.decision)&&nullableString(c.createdAt)
    &&(c.score===null||finite(c.score))&&oneOf(c.attribution,['PER_RUN','SHARED_UNASSIGNED','REFERENCE_ONLY'])))return false;
  const rules=value.rules,retrieval=value.retrieval;
  if(!record(rules)||!record(retrieval))return false;
  const disabledRules=rules.policy==='disabled'&&rules.action==='DISABLED'&&rules.completeAggregation===false
    &&rules.threshold===null&&Array.isArray(rules.perRun)&&rules.perRun.length===0
    &&Array.isArray(rules.excludedRunIds)&&rules.excludedRunIds.length===0;
  const activeRules=oneOf(rules.policy,['cost-regex-1','cost-regex-2'])&&rules.action==='APPLY_EXISTING_COST_RULE'
    &&rules.completeAggregation===true&&finite(rules.threshold)&&Number.isInteger(rules.threshold)&&rules.threshold>=1;
  const retrievalValid=activeRules
    ? retrieval.strategy==='COMPLETE_RULE_AGGREGATION_WITH_PROOF'&&(retrieval.model===undefined||string(retrieval.model))
    : string(retrieval.model);
  return (disabledRules||activeRules)&&retrievalValid
    &&(rules.threshold===null||finite(rules.threshold))&&strings(rules.excludedRunIds)&&strings(rules.remainingRunIds)
    &&Array.isArray(rules.perRun)&&rules.perRun.every(row=>record(row)&&string(row.runId)&&finite(row.count)
      &&Number.isInteger(row.count)&&row.count>=0&&string(row.status)&&typeof row.mixed==='boolean'&&strings(row.costRejectionRecordIds))
    &&record(retrieval)&&finite(retrieval.totalInScope)&&retrieval.totalInScope>=0
    &&finite(retrieval.returned)&&retrieval.returned>=0;
}
