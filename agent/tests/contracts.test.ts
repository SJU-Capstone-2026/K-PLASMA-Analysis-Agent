import { describe, expect, it } from 'vitest';
import type { UploadManifest, AgentResponse, TurnSnapshot, BatchView, CatalogView, ReferenceWrite, ExperimentRecord } from '../src/contracts';
import { toRunSummary } from '../src/contracts';
import wire from './support/contract-wire.json';
import { syntheticRun } from './support/synthetic-runs';

describe('Run wire boundary', () => {
  it('keeps version identity and scalar analysis while excluding graph payloads', () => {
    const full = syntheticRun();
    const summary = toRunSummary(full);
    expect(summary.runVersionId).toBe(full.runVersionId);
    expect(summary.analysis.electronDensity).toBe(19);
    expect(summary.analysis).not.toHaveProperty('residualTrace');
    expect(summary.analysis).not.toHaveProperty('density');
    expect(summary).not.toHaveProperty('iedDistribution');
    expect(summary).not.toHaveProperty('sourceFiles');
  });
  it('matches the shared artificial Java wire input for both availability states', () => {
    expect(syntheticRun()).toEqual(wire.on);
    expect(syntheticRun(false)).toEqual(wire.off);
    expect(toRunSummary(syntheticRun())).toEqual(wire.summaryOn);
    expect(toRunSummary(syntheticRun(false))).toEqual(wire.summaryOff);
  });
  it('preserves normal bias-off nulls without substituting zero', () => {
    const full = syntheticRun(false);
    expect(full.metrics.iedWidth).toBeNull();
    expect(toRunSummary(full).analysis.dcOffset).toBeNull();
    expect(full.analysis.density).toBeNull();
    expect(full.iedDistribution).toEqual([]);
  });
});

describe('intake, clarification and reprocess wire boundaries', () => {
  it('maps separate multipart names to same-basename folder paths and a single ZIP part without client hashes', () => {
    const folder: UploadManifest = { mode: 'FOLDER', entries: [
      { partName: 'file0', relativePath: 'artificial/IED/Ar+.txt' },
      { partName: 'file1', relativePath: 'artificial/IAD/Ar+.txt' },
    ] };
    const archive: UploadManifest = { mode: 'ZIP', entries: [{ partName: 'archive', relativePath: 'artificial.zip' }] };
    expect(folder).toEqual(wire.folderUpload);
    expect(archive).toEqual(wire.archiveUpload);
    expect(folder.entries[0].relativePath).not.toBe(folder.entries[1].relativePath);
  });
  it('preserves CLARIFICATION in both an agent response and its persisted turn', () => {
    const response: AgentResponse = { ...wire.clarificationResponse, intent: 'CLARIFICATION' };
    const turn: TurnSnapshot = { ...wire.clarificationTurn, intent: 'CLARIFICATION' };
    expect(response).toEqual(wire.clarificationResponse);
    expect(turn).toEqual(wire.clarificationTurn);
  });
  it('represents reprocessing as a batch with nested jobs and progress', () => {
    const batch: BatchView = { ...wire.reprocessBatch, status: 'QUEUED', jobs: wire.reprocessBatch.jobs.map(job => ({ ...job, status: 'QUEUED' })) };
    expect(batch.batchId).toBe('00000000-0000-4000-8000-000000000002');
    expect(batch.jobs[0].jobId).toBe('00000000-0000-4000-8000-000000000003');
    expect(batch).toEqual(wire.reprocessBatch);
  });
});

it('keeps catalog presentation files keyed by immutable version without hydrating graph arrays', () => {
  const catalog: CatalogView = { runs: wire.catalog.runs.map(run => ({ ...run, catalogStatus: 'READY' })), jobs: [], sourceFilesByVersion: wire.catalog.sourceFilesByVersion };
  expect(catalog).toEqual(wire.catalog);
  expect(Object.values(catalog.sourceFilesByVersion)[0]).toHaveLength(1);
  expect(catalog.runs[0]).not.toHaveProperty('iedDistribution');
});


it('preserves independent nullable context writes and a complete ordinary EXP wire record', () => {
  const reference: ReferenceWrite = wire.referenceWrite;
  const experiment: ExperimentRecord = {
    ...wire.experimentRecord, version: 2, analysisType: 'REVERSE', processMode: 'GOAL_RECOMMENDATION', decision: 'ADOPT',
    candidates: wire.experimentRecord.candidates.map(candidate => ({ ...candidate, decision: 'ADOPT' })),
  };
  expect(reference).toEqual(wire.referenceWrite);
  expect(reference.candidateReference).toBeNull();
  expect(reference.activeRun?.runVersionId).toBe(wire.on.runVersionId);
  expect(experiment).toEqual(wire.experimentRecord);
  expect(experiment.candidates).toHaveLength(1);
  expect(experiment.candidates[0].decision).toBe('ADOPT');
  expect(experiment.overallComment).toBe('artificial common comment');
});

it('distinguishes persisted graph v1 answers from legacy snapshots without changing either', async () => {
  const {isV1AnswerSnapshot} = await import('../src/contracts');
  const current = {implementationId:'v1',schemaVersion:1,kind:'compare_runs',result:{metrics:[{baseline:0,target:3,delta:3,percentChange:null,reason:'ZERO_BASELINE'}]}};
  const before = structuredClone(current);
  expect(isV1AnswerSnapshot(current)).toBe(true);
  expect(isV1AnswerSnapshot({intent:'CHANGE_EXPLANATION'})).toBe(false);
  expect(isV1AnswerSnapshot({...current,schemaVersion:2})).toBe(false);
  expect(current).toEqual(before);
});
