import type { RunRef } from './index.js';

export type GraphVersion = 'v1' | 'v2';
type Json = null | string | number | boolean | Json[] | { [key: string]: Json };
type ExecutionStatus = 'COMPLETE' | 'PARTIAL' | 'FAILED';
type ReviewStatus = 'PASS' | 'ISSUE' | 'UNAVAILABLE' | 'SKIPPED';
type StepStatus = 'verified' | 'empty' | 'partial' | 'blocked' | 'failed' | 'skipped';

export interface V2StepResult {
  executionId: string;
  stepId: string;
  status: StepStatus;
  outputs: Record<string, Json>;
  runRefs: RunRef[];
  groupId: string | null;
  reason: string | null;
}

export interface V2Review {
  status: ReviewStatus;
  answers: {
    name: 'request_coverage' | 'evidence_alignment' | 'interpretation_scope';
    choice: string;
    probabilities: Record<string, number>;
    confidence: number | null;
  }[];
  reason: string | null;
}

export interface GraphV2AnswerSnapshotV1 {
  implementationId: 'v2';
  graphVersion: 'v2';
  schemaVersion: 1;
  intent: 'COMPOSITE_ANSWER' | 'GENERAL_ANSWER';
  question: string;
  confirmedContext: Record<string, Json>;
  planRevision: number | null;
  stepResults: V2StepResult[];
  evidence: { id: string; executionId: string; field: string; value: Json; unit: string | null; runRef: RunRef | null }[];
  draft: Record<string, Json> | null;
  answer: string;
  executionStatus: ExecutionStatus;
  hasIncompleteWork?: boolean;
  review: V2Review;
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

export function isGraphV2AnswerSnapshot(value: unknown): value is GraphV2AnswerSnapshotV1 {
  if (!record(value) || value.implementationId !== 'v2' || value.graphVersion !== 'v2' || value.schemaVersion !== 1
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
