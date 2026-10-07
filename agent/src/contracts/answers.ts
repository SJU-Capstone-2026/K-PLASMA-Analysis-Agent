import type { RunRef, Snapshot } from './index.js';

export type ToolName = 'forward_lookup' | 'reverse_search' | 'compare_runs' | 'generate_answer';
export type ConditionId = 'pressure' | 'sourcePower' | 'biasPower';
export type OutputMetric = 'meanIonEnergy' | 'ionFlux' | 'iedWidth';
export interface ToolSelection {call_id:string;name:ToolName;arguments:Snapshot}
export interface ReferenceOrigin {ref:RunRef;kind:'run_tag'|'candidate_group';turnId:string;groupId:string|null}
export interface ComparisonReferenceEntry {key:string;ref:RunRef;origin:{kind:'run_tag'|'candidate_group'|'hitl';turnId:string|null;groupId:string|null;pendingInputId:string|null}}
export interface ComparisonReferenceSnapshot {entries:ComparisonReferenceEntry[];baselineKey:string|null}
export type UnavailableReason = 'MISSING_VALUE'|'MISSING_BASELINE'|'MISSING_TARGET'|'MISSING_BOTH'|'ZERO_BASELINE'|'INVALID_VALUE'|'UNIT_NOT_COMPARABLE'|'NUMERIC_OVERFLOW'|'INSUFFICIENT_DATA';
export interface ScalarDatum {value:number|null;unit:string;status:'AVAILABLE'|'UNAVAILABLE';reason:UnavailableReason|null;sourceValue:{value:number|null;unit:string}|null}
export interface ComparisonRun {key:string;ref:RunRef;conditions:Record<ConditionId,ScalarDatum>;metrics:Partial<Record<OutputMetric,ScalarDatum>>;quality:{convergenceStatus:string;qualityStatus:string;catalogStatus:string}}
export interface ComparisonDifference {id:string;kind:'absolute_difference'|'baseline_delta'|'adjacent_delta';leftKey:string;rightKey:string;metric:OutputMetric;difference:ScalarDatum;percentChange:ScalarDatum|null;direction:'increase'|'decrease'|'unchanged'|'not_applicable'|'unavailable'}
export interface MetricSummary {id:string;metric:OutputMetric;availableCount:number;minimum:ScalarDatum;minimumKeys:string[];maximum:ScalarDatum;maximumKeys:string[];range:ScalarDatum}
export interface TrendGroup {id:string;metric:OutputMetric;axis:ConditionId;fixedConditions:Partial<Record<ConditionId,ScalarDatum>>;orderedKeys:string[];comparisonIds:string[];direction:'increasing'|'decreasing'|'constant'|'non_monotonic'|'insufficient_data'|'unavailable'}
export interface ComparisonObservation {id:string;source:{kind:'run'|'comparison'|'summary'|'trend';key:string;metric:OutputMetric};text:string}
export interface ComparisonResultV2 {kind:'compare_runs';resultStatus:'COMPARISON_READY'|'COMPARISON_PARTIAL'|'NO_COMPARABLE_DATA';mode:'values'|'pair'|'overview'|'baseline'|'trend';metricIds:OutputMetric[];baselineKey:string|null;trendAxis:ConditionId|null;runs:ComparisonRun[];comparisons:ComparisonDifference[];summaries:MetricSummary[];trends:TrendGroup[];observations:ComparisonObservation[];usedRunRefs:RunRef[];numericPolicyVersion:'v1';aggregationPolicyVersion:'multi-run-1'}
export interface ComparisonAnswer {kind:'comparison_answer';status:'COMPLETE';knowledgeBasis:'VERIFIED_RUNS_AND_LLM_GENERAL_KNOWLEDGE';observationIds:string[];interpretations:{text:string;observationIds:string[];assumptions:string[]}[];limitations:string[]}
export interface GeneralAnswerResult {kind:'generate_answer';resultStatus:'ANSWER_READY';markdown:string;knowledgeBasis:'LLM_GENERAL_KNOWLEDGE';usedRunRefs:[]}
export interface AnswerSnapshotV2 {implementationId:'v1';graphVersion:'v1';schemaVersion:2;kind:ToolName;summary:string;originalQuestion:string;toolSelection:ToolSelection;resolvedInputs:Snapshot;result:ComparisonResultV2|GeneralAnswerResult|Snapshot;answer:ComparisonAnswer|null;contextProvenance:Snapshot;inputHistory:Snapshot[];usedRunRefs:RunRef[];versions:Snapshot}
export interface RunOption {key:string;ref:RunRef;conditions:Record<ConditionId,ScalarDatum>;selectable:boolean;unavailableReason:string|null}
export interface RunOptions {requestId:string;requestRevision:number;pendingInputId:string;options:RunOption[]}
