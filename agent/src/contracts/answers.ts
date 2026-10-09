import type { RunRef, Snapshot } from './index.js';

export type ToolName = 'forward_lookup' | 'reverse_search' | 'compare_runs' | 'generate_answer';
export type ConditionId = 'pressure' | 'sourcePower' | 'biasPower';
export type PlotId = 'ied'|'iad'|'iead'|'current'|'potential'|'density'|'residual';
export type ComparisonField = OutputMetric|ConditionId|`${'current'|'potential'}.${'maximum'|'minimum'|'peakToPeak'|'halfPeakToPeak'|'maximumPhase'|'minimumPhase'}`|'ied.maximum'|'ied.peakEnergy'|'iad.maximum'|'iad.peakAngle'|'iead.maximum'|'iead.peakEnergy'|'iead.peakAngle'|'density.maximum'|'density.maximumPhase'|'density.maximumDistance'|'residual.maximum'|'residual.maximumIteration'|'residual.final'|'residual.finalIteration';
export type OutputMetric = 'meanIonEnergy' | 'ionFlux' | 'iedWidth';
export interface UnitAssumption {metric:ConditionId|OutputMetric;unit:string}
export const queryDefaultUnits:Record<ConditionId|OutputMetric,string>={pressure:'mTorr',sourcePower:'W',biasPower:'W',meanIonEnergy:'eV',ionFlux:'10¹⁸ m⁻²s⁻¹',iedWidth:'eV'};
export interface ToolSelection {call_id:string;name:ToolName;arguments:Snapshot}
export interface ReferenceOrigin {ref:RunRef;kind:'run_tag'|'candidate_group';turnId:string;groupId:string|null}
export interface ComparisonReferenceEntry {key:string;ref:RunRef;origin:{kind:'run_tag'|'candidate_group'|'hitl';turnId:string|null;groupId:string|null;pendingInputId:string|null}}
export interface ComparisonReferenceSnapshot {entries:ComparisonReferenceEntry[];baselineKey:string|null}
export type UnavailableReason = 'MISSING_VALUE'|'MISSING_BASELINE'|'MISSING_TARGET'|'MISSING_BOTH'|'ZERO_BASELINE'|'INVALID_VALUE'|'UNIT_NOT_COMPARABLE'|'NUMERIC_OVERFLOW'|'INSUFFICIENT_DATA';
export interface ScalarDatum {value:number|null;unit:string;status:'AVAILABLE'|'UNAVAILABLE';reason:UnavailableReason|null;sourceValue:{value:number|null;unit:string}|null}
export interface ComparisonRun {key:string;ref:RunRef;conditions:Record<ConditionId,ScalarDatum>;metrics:Partial<Record<ComparisonField,ScalarDatum>>;quality:{convergenceStatus:string;qualityStatus:string;catalogStatus:string}}
export interface ComparisonDifference {id:string;kind:'absolute_difference'|'baseline_delta'|'adjacent_delta';leftKey:string;rightKey:string;metric:ComparisonField;difference:ScalarDatum;percentChange:ScalarDatum|null;direction:'increase'|'decrease'|'unchanged'|'not_applicable'|'unavailable'}
export interface MetricSummary {id:string;metric:ComparisonField;availableCount:number;minimum:ScalarDatum;minimumKeys:string[];maximum:ScalarDatum;maximumKeys:string[];range:ScalarDatum}
export interface TrendGroup {id:string;metric:ComparisonField;axis:ConditionId;fixedConditions:Partial<Record<ConditionId,ScalarDatum>>;orderedKeys:string[];comparisonIds:string[];direction:'increasing'|'decreasing'|'constant'|'non_monotonic'|'insufficient_data'|'unavailable'}
export interface ComparisonObservation {id:string;source:{kind:'run'|'comparison'|'summary'|'trend';key:string;metric:ComparisonField};text:string}
export interface ComparisonResultV2 {kind:'compare_runs';resultStatus:'COMPARISON_READY'|'COMPARISON_PARTIAL'|'NO_COMPARABLE_DATA';mode:'values'|'pair'|'overview'|'baseline'|'trend';metricIds:ComparisonField[];baselineKey:string|null;trendAxis:ConditionId|null;runs:ComparisonRun[];comparisons:ComparisonDifference[];summaries:MetricSummary[];trends:TrendGroup[];observations:ComparisonObservation[];usedRunRefs:RunRef[];numericPolicyVersion:'v1';aggregationPolicyVersion:'multi-run-1'}
export interface ComparisonAnswer {kind:'comparison_answer';status:'COMPLETE';knowledgeBasis:'VERIFIED_RUNS_AND_LLM_GENERAL_KNOWLEDGE';observationIds:string[];interpretations:{text:string;observationIds:string[];assumptions:string[]}[];limitations:string[]}
export interface GeneralAnswerResult {kind:'generate_answer';resultStatus:'ANSWER_READY';markdown:string;knowledgeBasis:'LLM_GENERAL_KNOWLEDGE';usedRunRefs:[]}
export interface AnswerSnapshotV2 {implementationId:'v1';graphVersion:'v1';schemaVersion:2;kind:ToolName;summary:string;originalQuestion:string;toolSelection:ToolSelection;resolvedInputs:Snapshot;result:ComparisonResultV2|GeneralAnswerResult|Snapshot;answer:ComparisonAnswer|null;contextProvenance:Snapshot;unitAssumptions?:UnitAssumption[];inputHistory:Snapshot[];usedRunRefs:RunRef[];versions:Snapshot}
export interface RunOption {key:string;ref:RunRef;conditions:Record<ConditionId,ScalarDatum>;selectable:boolean;unavailableReason:string|null}
export interface RunOptions {requestId:string;requestRevision:number;pendingInputId:string;options:RunOption[]}

export interface OutputMetadata {ref:RunRef;outputId:PlotId;status:'AVAILABLE'|'UNAVAILABLE';reason:string|null;sourceIntegrity:string|null;featurePolicyVersion:string;xUnit:string;yUnit:string;valueUnit:string;sourceCount:number;extrema:Record<string,{value:number;x:number;y:number|null;count:number}>}
export interface RunOutput {metadata:OutputMetadata;features:Partial<Record<ComparisonField,ScalarDatum>>;display:{kind:'line'|'grid';samples:{x:number;y:number}[];rows:{x:number;coordinates:number[];values:number[]}[]}|null}
export interface ComparisonResultV3 extends ComparisonResultV2 {plotIds:PlotId[];outputs:OutputMetadata[];featurePolicyVersion:string}
export interface AnswerSnapshotV3 extends Omit<AnswerSnapshotV2,'schemaVersion'|'result'> {schemaVersion:3;result:ComparisonResultV3}
