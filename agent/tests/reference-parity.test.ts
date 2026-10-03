/* eslint-disable @typescript-eslint/no-explicit-any -- VM executes untyped external original functions; no external values become fixtures. */
import { beforeAll, describe, expect, it } from 'vitest';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { executeFallback, toRunSummary, type AgentContext, type FullRun } from '../src';
// This package is intentionally external. Its values never become fixtures or logged assertion diffs.
import { loadReference } from '../../scripts/reference/load.mjs';
const root = process.env.KPLASMA_REFERENCE_ROOT;
const explicitlyRequested = process.env.KPLASMA_REFERENCE_EXPLICIT === 'true';
if (!root && explicitlyRequested) throw new Error('Set KPLASMA_REFERENCE_ROOT to the external v12.3.1 reference package before running tests/reference-parity.test.ts.');
const digest = (value: unknown) => createHash('sha256').update(JSON.stringify(value)).digest('hex');
let original: any;
let ctx: AgentContext;
let runs: FullRun[];
const request = (text: string) => ({ text, candidateReferences: [] });

describe.skipIf(!root)('external v12.3.1 parity (hashes only)', () => {
  beforeAll(async () => {
    const reference = await loadReference(root);
    original = vm.createContext({ console });
    const assets = join(reference.prototypeRoot, 'assets');
    for (const name of ['mock-data', 'analysis-data', 'engine', 'agent-engine', 'analysis-engine', 'explanation-engine', 'manual-evidence', 'view-models', 'record-reuse']) {
      vm.runInContext(await readFile(join(assets, `${name}.js`), 'utf8'), original, { filename: `${name}.js` });
    }
    runs = original.KPlasmaAnalysisData.runs.map((run: any, index: number) => ({ ...run, runVersionId: `reference-version-${index}` }));
    ctx = { candidateRunsLatest: runs.map(toRunSummary), referenceRunsByVersion: new Map(), decisionRecords: [],
      hydrateFullRun: async ref => { const run = runs.find(run => run.runVersionId === ref.runVersionId); if (!run) throw new Error('Missing reference version'); return run; } };
    const app = await readFile(join(assets, 'app.js'), 'utf8');
    // Execute the untouched original app's PURE functions, with its original dependency names.
    const contextual = app.slice(app.indexOf('  function contextualAgentRequest'), app.indexOf('  function executeAgentRequest'));
    const memory = app.slice(app.indexOf('  function executeMemoryQuestion'), app.indexOf('  function renderMemoryAnswer'));
    vm.runInContext(`const engine=KPlasmaEngine, agent=KPlasmaAgent, analysisData=KPlasmaAnalysisData, viewModels=KPlasmaViewModels, reuse=KPlasmaRecordReuse;
      let candidateReference=null; const state={conversation:{activeRunId:null},decisionRecords:[]};
      const getRun=id=>analysisData.runs.find(r=>r.runId===id)||null;
      const latestCandidateReference=()=>candidateReference;
      let memoryAnswer=null; const appendMemoryAnswer=(text,answer)=>{memoryAnswer=answer;};
      ${contextual}\n${memory}
      function originalAnswer(text, options={}) {
        memoryAnswer=null;
        if(executeMemoryQuestion(text,options.threshold,undefined,options.undo)) return memoryAnswer;
        const req=contextualAgentRequest(text,options); const baseline=getRun((req.query&&req.query.baselineRunId)||state.conversation.activeRunId);
        let result=null;
        if(req.intent==='FORWARD_LOOKUP') result=engine.searchForward(req.query.conditions,analysisData.runs);
        else if(req.intent==='REVERSE_SEARCH') {
          req.query.confirmed=true; const validation=engine.validateQuery(req.query);
          if(validation.ok) { req.query={...validation.normalizedQuery,confirmed:true}; result=engine.searchReverse(req.query,analysisData.runs); }
          else result={status:'INVALID',errors:validation.errors,objectives:req.query.objectives||[]};
        } else if(req.intent==='CHANGE_EXPLANATION') result=KPlasmaExplanation.buildControlledExplanation(req,analysisData.runs,KPlasmaManualEvidence.entries);
        return compactAgentAnswer(viewModels.buildAgentAnswerModel(req,result),req,result,baseline);
      }`, original);
  }, 120_000);

  async function parity(text: string, baseline?: FullRun, options: any = {}, candidates: FullRun[] = []) {
    original.currentText = text; original.currentOptions = options; original.currentBaseline = baseline?.runId ?? null;
    original.currentCandidates = candidates.map(r => r.runId);
    vm.runInContext(`state.conversation.activeRunId=currentBaseline; candidateReference=currentCandidates.length ? {kind:currentCandidates.length===1?'단일 Run':'후보 집합',ids:currentCandidates}:null;`, original);
    const expected = vm.runInContext('originalAnswer(currentText,currentOptions)', original);
    const actual = await executeFallback({ ...request(text), baseline: baseline ? { runId: baseline.runId, runVersionId: baseline.runVersionId } : undefined,
      candidateReferences: candidates.map(r => ({ runId: r.runId, runVersionId: r.runVersionId })), clarification: options }, ctx);
    // R15 identity-only migration metadata is compared separately; physical and behavioral fields remain exact.
    const physicalSnapshot = JSON.parse(JSON.stringify(actual.answerSnapshot));
    delete physicalSnapshot.candidateRunRefs;
    delete physicalSnapshot.excludedRunRefs;
    if (physicalSnapshot.memoryRequest) delete physicalSnapshot.memoryRequest.referenceRunRefs;
    expect(digest(actual.answerSnapshot.candidateRunRefs)).toBe(digest(actual.candidates));
    if (expected.memoryResult) {
      const excludedIds = expected.memoryResult.excluded.map((run: any) => run.runId);
      const metadata = actual.answerSnapshot.excludedRunRefs as {runId: string; runVersionId: string}[];
      expect(digest(metadata.map(ref => ref.runId))).toBe(digest(excludedIds));
      expect(digest(metadata)).toBe(digest(excludedIds.map((id: string) => { const run = runs.find(run => run.runId === id)!; return {runId: id, runVersionId: run.runVersionId}; })));
    }
    expect(digest(physicalSnapshot)).toBe(digest(expected));
    expect(actual.intent).toBe(expected.intent);
    if (expected.status) expect(actual.status).toBe(expected.status);
    expect(digest(actual.candidates.map(r => r.runId))).toBe(digest(expected.runIds));
  }

  it('matches every exact forward Run and nearest off-grid lookup', async () => {
    expect(runs.length).toBe(150);
    for (const run of runs) await parity(`Pressure ${run.pressure} Source ${run.sourcePower} Bias ${run.biasPower} 결과 보여줘`);
    await parity('Pressure 3 Source 250 Bias 500 결과 보여줘');
  });
  it('matches numeric search ordering, all candidates, unsupported, clarification and concepts', async () => {
    for (const text of ['Ion Flux가 400 이상이고 Mean Ion Energy가 140–180 eV인 실제 Run을 모두 보여줘',
      'Ion Flux는 높게, Mean Ion Energy는 150–160 eV에 가깝게 후보를 찾아줘',
      'Mean Ion Energy 140–180 eV 후보 찾아줘', 'Mean Ion Energy 180–140 eV 후보 찾아줘',
      'Ion Flux가 999999 이상인 후보 찾아줘', 'Pressure 6 결과 보여줘', 'Ion Flux란 무엇인가요?', '오늘 날씨 알려줘']) await parity(text);
  });
  it('matches active-run contextual energy, flux-width, full-results and controlled explanation evidence', async () => {
    const baseline = runs.find(r => r.pressure === 6 && r.sourcePower === 400 && r.biasPower === 600)!;
    for (const text of ['Energy를 조금 더 높여줘', 'Flux 유지하면서 IED 폭을 낮춰줘', '이 Run 전체 결과 보여줘', '왜 이런 결과인가요?']) await parity(text, baseline);
    await parity('Source power 변화 이유 설명', undefined, { comparison: { beforeRunId: runs[0].runId, afterRunId: 'MISSING' } });
    await parity('Source power 변화 이유 설명', undefined, { comparison: { beforeRunId: runs[0].runId, afterRunId: runs.at(-1)!.runId } });
  });
  it('matches record reuse scope, threshold prompt, numeric filtering and undo', async () => {
    for (const text of ['이 후보들 중 비용 반려 1건 이상 제외해줘', '비용 반려가 많은 후보 제외해줘', '이 후보들의 과거 기록 보여줘',
      '성능 때문에 반려된 후보 제외해줘', 'Flux가 500 이상인 후보를 찾되, 비용 때문에 반려된 건 제외해줘']) await parity(text, undefined, {}, runs.slice(0, 8));
    await parity('이 후보들 중 비용 반려 1건 이상 제외해줘', undefined, { undo: true }, runs.slice(0, 8));
  });
});
