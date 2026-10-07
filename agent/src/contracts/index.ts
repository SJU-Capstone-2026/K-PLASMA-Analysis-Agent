/** Wire contracts: finite binary64 numbers, ISO 8601 timestamps, immutable version references. */
export interface RunRef { runId: string; runVersionId: string }
export interface RunDeleteRequest { runIds: string[] }
export interface RunDeleteResult { deletedRunIds: string[]; cleanupPending: boolean }
export type Pair = [number, number];
export type DensityRow = [number, number[], number[]];
export interface Conditions { pressure: number; sourcePower: number; biasPower: number }
export interface Metrics { ionFlux: number; meanIonEnergy: number; iedWidth: number | null }
export interface Units { pressure: string; sourcePower: string; biasPower: string; ionFlux: string; meanIonEnergy: string; iedWidth: string }
export interface AnalysisScalars {
  hasDistribution: boolean; strictConvergence: boolean; finalResidualMax: number;
  electronTemperature: number; ionTemperature: number; gasTemperature: number;
  absorbedPower: number; alpha: number; plasmaResistance: number; plasmaReactance: number;
  dcOffset: number | null; peakToPeak: number | null; currentDensityPeak: number;
  electronDensity: number; ionDensity: number; metastableDensity: number; neutralDensity: number;
  ionFluxRaw: number; metastableFluxRaw: number; neutralFluxRaw: number;
}
export interface IedPoint { energy: number; intensity: number }
export interface Iead { angles: number[]; energies: number[]; values: number[]; sourceShape: Pair; angleRange: Pair }
export interface Waveform { points: Pair[]; phaseRange: Pair; sourceCount: number }
export interface Density { rows: DensityRow[]; sourceShape: Pair }
export interface Analysis extends AnalysisScalars {
  residualTrace: Pair[]; iad: Pair[] | null; iead: Iead | null;
  current: Waveform | null; potential: Waveform | null; density: Density | null;
}
export type JobStatus = 'QUEUED' | 'PROCESSING' | 'READY' | 'DUPLICATE' | 'INCOMPLETE' | 'PARSE_FAILED' | 'INTERRUPTED';
export interface RunSummary extends RunRef, Conditions {
  metrics: Metrics; units: Units; analysis: AnalysisScalars;
  convergenceStatus: string; qualityStatus: string; catalogStatus: JobStatus;
  registeredAt: string; presentationScore: number; note: string;
}
export interface SourceFile { name: string; type: string; size: string; status: string; path: string }
export interface FullRun extends RunSummary { analysis: Analysis; iedDistribution: IedPoint[]; sourceFiles: SourceFile[] }
/** Project explicitly: even accidental runtime properties cannot leak graph arrays into search. */
export function toRunSummary(full: FullRun): RunSummary {
  const { runId, runVersionId, pressure, sourcePower, biasPower, metrics, units,
    convergenceStatus, qualityStatus, catalogStatus, registeredAt, presentationScore, note } = full;
  const { hasDistribution, strictConvergence, finalResidualMax, electronTemperature, ionTemperature,
    gasTemperature, absorbedPower, alpha, plasmaResistance, plasmaReactance, dcOffset, peakToPeak,
    currentDensityPeak, electronDensity, ionDensity, metastableDensity, neutralDensity,
    ionFluxRaw, metastableFluxRaw, neutralFluxRaw } = full.analysis;
  return { runId, runVersionId, pressure, sourcePower, biasPower, metrics: { ...metrics }, units: { ...units },
    convergenceStatus, qualityStatus, catalogStatus, registeredAt, presentationScore, note,
    analysis: { hasDistribution, strictConvergence, finalResidualMax, electronTemperature, ionTemperature,
      gasTemperature, absorbedPower, alpha, plasmaResistance, plasmaReactance, dcOffset, peakToPeak,
      currentDensityPeak, electronDensity, ionDensity, metastableDensity, neutralDensity,
      ionFluxRaw, metastableFluxRaw, neutralFluxRaw } };
}
/** Compact original engine objects; physical Run/analysis/graph payloads are forbidden in persisted snapshots. */
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type Snapshot = { [key: string]: JsonValue };
export type Intent = 'FORWARD_LOOKUP' | 'REVERSE_SEARCH' | 'RUN_COMPARISON' | 'GENERAL_ANSWER' | 'CHANGE_EXPLANATION' | 'CONCEPT_EXPLANATION' | 'RECORD_REUSE' | 'CLARIFICATION' | 'UNSUPPORTED';
export interface AgentRequest { text: string; baseline?: RunRef; candidateReferences: RunRef[]; clarification?: Snapshot }
export interface AgentResponse { intent: Intent; status: string; candidates: RunRef[]; explanation: Snapshot | null; answerSnapshot: Snapshot; usedRunRefs: RunRef[] }
export interface AgentContext {
  latestCandidateReferences?: RunRef[];
  candidateRunsLatest: RunSummary[]; referenceRunsByVersion: ReadonlyMap<string, FullRun>;
  decisionRecords: DecisionRecord[]; hydrateFullRun(ref: RunRef): Promise<FullRun>;
}
export interface StateToken { workspaceEpoch: number; conversationEpoch: number; revision: number }
export interface TurnUiSnapshot {
  collapsed: boolean; openRunIds: string[]; runDetailTabs: Record<string, string>;
  activeCandidateGroup: string; continuedRunId: string | null; lookupExpanded: boolean; selectedCandidateRunId: string | null;
}
export interface TurnSnapshot { id: string; askedAt: string; question: string; intent: Intent; context: RunRef | null; answerRunRefs: RunRef[]; answerSnapshot: Snapshot; ui: TurnUiSnapshot }
export type ReferenceState = { kind: '단일 Run' | '후보 집합'; runs: RunRef[] } | null;
export interface ReferenceWrite { stateToken: StateToken; candidateReference: ReferenceState; activeRun: RunRef | null }
export interface Conversation { version: 1; activeRun: RunRef | null; turns: TurnSnapshot[] }
export interface WorkspaceView { stateToken: StateToken; conversation: Conversation; candidateReference: ReferenceState; activeAgentRequest?:AgentRequestView|null; failedAgentRequest?:AgentRequestView|null }
export type Decision = 'ADOPT' | 'HOLD' | 'REJECT';
export type ExperimentDecision = Decision | 'ALTERNATIVE' | 'COMPARISON';
export interface RunSnapshot extends RunRef { conditions: Conditions; metrics: Metrics; supportingMetrics: { electronDensity: number; electronTemperature: number } }
export interface CandidateSnapshot extends RunRef { decision: ExperimentDecision; note: string; conditions: Conditions; metrics: Metrics; objectiveEvaluations: Snapshot[] }
export interface ReviewRecord {
  reviewId: string; version?: never; targetRunId: string; comparedRunIds: string[];
  targetRunRef: RunRef; comparedRunRefs: RunRef[]; decision: Decision; comment: string; authorName: string; createdAt: string;
  analysisType: 'FORWARD' | 'REVERSE' | 'EXPLANATION'; processMode: string;
  constraints: Snapshot[]; goals: Snapshot[]; queryText: string; evidenceKinds: string[]; limitations: string[]; runSnapshots: RunSnapshot[];
}
export interface ExperimentRecord {
  id: string; reviewId: string; version: 2; createdAt: string; question: string; objectives: Snapshot[];
  overallComment: string; authorName: string; candidates: CandidateSnapshot[];
  targetRunId: string; comparedRunIds: string[]; targetRunRef: RunRef; comparedRunRefs: RunRef[];
  decision: ExperimentDecision; comment: string; analysisType: 'REVERSE'; processMode: 'GOAL_RECOMMENDATION'; goals: Snapshot[]; queryText: string;
}
export type DecisionRecord = ReviewRecord | ExperimentRecord;
export interface DecisionWrite { workspaceEpoch: number; record: DecisionRecord; runRefs: RunRef[] }
export interface ApiError { code: string; message: string; field?: string; details?: Snapshot; requestId: string }
export interface ManifestFile { path: string; kind: string; size: number; sha256: string }
/** Client intake maps multipart parts only; hashes, sizes and classification are computed by the server. */
export interface UploadEntry { partName: string; relativePath: string }
export interface UploadManifest { mode: 'FOLDER' | 'ZIP'; entries: UploadEntry[] }
export interface JobView { jobId: string; runId: string | null; runVersionId: string | null; status: JobStatus; reason: string | null; errors: ApiError[] }
export interface BatchView { batchId: string; status: JobStatus | 'SUCCESS' | 'PARTIAL_SUCCESS' | 'FAILED'; receivedBytes: number; totalBytes: number; processedRuns: number; totalRuns: number; jobs: JobView[] }
export interface CatalogView { runs: RunSummary[]; jobs: JobView[]; sourceFilesByVersion: Record<string, SourceFile[]> }

/** Durable v1 request metadata; a completed answer is saved by the server exactly once. */
export type AgentOperationKind = 'forward_lookup' | 'reverse_search' | 'compare_runs' | 'generate_answer' | 'explain_change' | 'explain_concept';
export type AgentRequestStatus = 'QUEUED' | 'RUNNING' | 'NEEDS_INPUT' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
export interface AgentPendingInput { id: string; message: string; type?:'text'|'run_selection'|'comparison_options'; fields?: string[]; options?: {label:string;input:Snapshot}[]; minSelections?:number;baselineRequired?:boolean;optionsUrl?:string;allowedRunKeys?:string[];allowedTrendAxes?:import('./answers.js').ConditionId[] }
export interface AgentRequestView {
  requestId:string; requestRevision:number; status:AgentRequestStatus; stage:string; graphVersion:'v1'; question:string;
  pendingInput:AgentPendingInput|null; error:{code:string;message:string}|null; partialResult:Snapshot|null;
  turnId:string|null; answerSnapshot:Snapshot|null; inputEvents:Snapshot[]; explanationComplete?:boolean;
}
export interface AgentSubmission {text:string;stateToken:StateToken;selectedRunRef?:RunRef;baseline?:RunRef;candidateReferences?:RunRef[];attachedRunRefs?:RunRef[];referenceOrigins?:import('./answers.js').ReferenceOrigin[]}
export interface AgentResume {expectedRequestRevision:number;pendingInputId:string;input:Snapshot}
export function isV1AnswerSnapshot(snapshot:Snapshot):boolean {return snapshot.implementationId==='v1'&&(snapshot.schemaVersion===1||snapshot.schemaVersion===2);}
export type * from './answers.js';
export {queryDefaultUnits} from './answers.js';
