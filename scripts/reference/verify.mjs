import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {execFileSync,spawnSync} from 'node:child_process';
import {join} from 'node:path';
import {once} from 'node:events';
import {loadReference,sha256} from './load.mjs';
import {compareRuns} from './compare-runs.mjs';
import {comparePrototypeAssertions} from './compare-tests.mjs';
import {repo,startBackend,command,createZip,upload,get,terminalBatch,syntheticFolder} from './runtime.mjs';
import {serveReference} from './server.mjs';
import {recordBrowserEvidence} from './browser-evidence.mjs';
import {syntheticFailureDiagnostics} from './browser-diagnostics.mjs';

const actual=process.argv.includes('--reference');
// Explicit reference commands fail before provisioning or returning a misleading green skip.
const reference=actual?await loadReference(process.env.KPLASMA_REFERENCE_ROOT):null;
const output=join(repo,'backend/.runtime/verification',`${actual?'reference':'synthetic'}-${Date.now()}`);
await mkdir(output,{recursive:true});
let backend,prototype,executionComplete=false;
let summary={mode:actual?'external-reference':'artificial-only',status:'FAIL',sourceVersion:reference?.version??null,sourceGitCommit:null,sourceGitCommitReason:'Original delivered package has no Git history.',appCommit:execFileSync('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8'}).trim(),appDirty:!!execFileSync('git',['status','--porcelain'],{cwd:repo,encoding:'utf8'}).trim(),parserVersion:'v12.3.1',node:process.version,java:spawnSync(process.env.JAVA_HOME?join(process.env.JAVA_HOME,'bin/java'):'java',['-version'],{encoding:'utf8'}).stderr.trim(),locale:'ko-KR',timezone:'Asia/Seoul',widths:[390,800,1008,1440],dataArtifacts:'Ignored local output only; never upload to CI.',deferred:['D1','D2','D3','D4','D5']};
try {
  let expected;
  if(reference){const require=createRequire(join(reference.testsRoot,'verify.cjs'));expected=require(join(reference.prototypeRoot,'assets/analysis-data.js')).runs;summary.referenceManifestSha256=await sha256(join(reference.root,'manifest.json'));summary.referenceFiles=Object.keys(reference.manifest.files).length;}
  const instants=reference?[...new Set(expected.map(run=>new Date(run.registeredAt).toISOString()))]:['2026-09-17T00:20:00.000Z'];
  if(instants.length!==1)throw new Error('Reference registration times differ: one frozen Clock cannot reproduce them.');
  summary.frozenInstant=instants[0];
  backend=await startBackend(output,instants[0]);
  let folder;
  if(reference){
    folder=reference.rawRoot;summary.portableAssertions=await comparePrototypeAssertions(reference);
    await writeFile(join(output,'prototype-assertions.json'),JSON.stringify(summary.portableAssertions,null,2));
    prototype=await serveReference(reference);
  } else folder=await syntheticFolder(output);
  // Both transports register against actual HTTP worker + PostgreSQL, including real physical payloads in reference mode.
  const folderAccepted=await upload(backend.url,folder,'FOLDER');
  const folderBatch=await terminalBatch(backend.url,folderAccepted.batchId);
  if(folderBatch.status!=='SUCCESS')throw new Error('Folder registration did not finish SUCCESS.');
  const firstSummaries=await get(backend.url,'/api/runs');
  const first=await Promise.all(firstSummaries.map(run=>get(backend.url,`/api/run-versions/${run.runVersionId}`)));
  if(reference){summary.folder=compareRuns(expected,first);console.log(`Folder: Runs=${summary.folder.runCount}, assertions=${summary.folder.assertions}, mismatches=${summary.folder.mismatches}.`);if(summary.folder.mismatches)throw new Error('Folder physical parity failed.');}
  else if(first.length!==3)throw new Error('Expected three artificial Runs.');
  const zip=join(output,'sources.zip');await createZip(folder,zip);
  if(reference){
    // An independent empty DB forces ZIP intake to parse/publish all 150 rather than reuse folder versions.
    await backend.close();backend=await startBackend(join(output,'zip-runtime'),instants[0]);
  }
  const zipAccepted=await upload(backend.url,folder,'ZIP',zip);const zipBatch=await terminalBatch(backend.url,zipAccepted.batchId);
  const wanted=reference?'READY':'DUPLICATE';
  if(zipBatch.status!=='SUCCESS'||zipBatch.jobs.some(job=>job.status!==wanted))throw new Error(`ZIP did not resolve every Run as ${wanted}.`);
  const zipSummaries=await get(backend.url,'/api/runs');const zipFull=await Promise.all(zipSummaries.map(run=>get(backend.url,`/api/run-versions/${run.runVersionId}`)));
  if(reference){summary.zip=compareRuns(expected,zipFull);console.log(`ZIP: Runs=${summary.zip.runCount}, assertions=${summary.zip.assertions}, mismatches=${summary.zip.mismatches}.`);if(summary.zip.mismatches)throw new Error('ZIP physical parity failed.');}
  if(!reference&&JSON.stringify(first.map(run=>run.runVersionId).sort())!==JSON.stringify(zipFull.map(run=>run.runVersionId).sort()))throw new Error('Duplicate ZIP changed immutable versions.');
  summary.upload={folderJobs:folderBatch.jobs.length,zipJobs:zipBatch.jobs.length,zipJobStatus:wanted,independentActualDatabases:!!reference,duplicateVersionsStable:!reference};
  // API-produced summary/catalog projections must agree with full immutable versions, without graph leakage into summaries.
  const catalog=await get(backend.url,'/api/catalog');
  for(const full of zipFull){const {iedDistribution,sourceFiles,analysis,...scalar}=full;const {residualTrace,iad,iead,current,potential,density,...analysisScalars}=analysis;
    if(JSON.stringify({...scalar,analysis:analysisScalars})!==JSON.stringify(zipSummaries.find(run=>run.runId===full.runId)))throw new Error('Summary projection differs from full version.');
    if(JSON.stringify(catalog.sourceFilesByVersion[full.runVersionId])!==JSON.stringify(sourceFiles))throw new Error('Catalog metadata differs from immutable version.');}
  summary.projections={summaries:zipFull.length,catalogFiles:zipFull.reduce((count,run)=>count+run.sourceFiles.length,0)};
  summary.physicalCounts={runs:zipFull.length,biasOn:zipFull.filter(run=>run.analysis.hasDistribution).length,biasOff:zipFull.filter(run=>!run.analysis.hasDistribution).length,strictTrue:zipFull.filter(run=>run.analysis.strictConvergence).length};
  const env={...process.env,KPLASMA_E2E_API:backend.url,KPLASMA_E2E_PORT:String(await (await import('./runtime.mjs')).freePort()),KPLASMA_E2E_REFERENCE:actual?'true':'false',KPLASMA_PROTOTYPE_URL:prototype?.url??'',KPLASMA_E2E_OUTPUT:join(output,'browser'),KPLASMA_E2E_SYNTHETIC_FOLDER:reference?'':folder,KPLASMA_E2E_INSTANT:instants[0]};
  summary.browserAttempts=[];
  for(let attempt=1;;attempt++){
    const directory=attempt===1?'browser':`browser-attempt-${attempt}`;
    env.KPLASMA_E2E_OUTPUT=join(output,directory);summary.browserDirectory=directory;
    try{await command(join(repo,'node_modules/.bin/playwright'),['test','--config','playwright.config.ts'],{cwd:join(repo,'frontend'),env,log:join(output,attempt===1?'browser.log':`browser-attempt-${attempt}.log`)});summary.browserAttempts.push({attempt,directory,status:'PASS'});break;}
    catch(error){
      summary.browserAttempts.push({attempt,directory,status:'FAIL'});
      for(const diagnostic of await syntheticFailureDiagnostics(output,{mode:summary.mode,directory,logFile:attempt===1?'browser.log':`browser-attempt-${attempt}.log`}))console.error(diagnostic);
      if(process.env.KPLASMA_VERIFY_DEBUG_HOLD!=='true'||attempt>=3)throw error;
      // Explicit local diagnosis option. Keep this isolated DB/API alive, with no repeat imports.
      const safeEnv=Object.fromEntries(Object.entries(env).filter(([key])=>key.startsWith('KPLASMA_E2E_')||['KPLASMA_PROTOTYPE_URL','KPLASMA_BROWSER_EXECUTABLE'].includes(key)));
      await writeFile(join(output,'browser-env.json'),JSON.stringify(safeEnv,null,2),{mode:0o600});
      console.log(`Browser failure; isolated API retained. Local env: ${join(output,'browser-env.json')}. Send Enter to retry corrected browser suite, or stop to clean up.`);
      const [input]=await once(process.stdin,'data');if(String(input).trim()==='stop')throw error;
    }
  }
  summary.browser='PASS';
  if(reference){await command(join(repo,'node_modules/.bin/vitest'),['run','tests/reference-parity.test.ts'],{cwd:join(repo,'agent'),env:{...process.env,KPLASMA_REFERENCE_EXPLICIT:'true'},log:join(output,'fallback-parity.log')});
    if(summary.portableAssertions.some(result=>result.status!=='PASS'))throw new Error('One or more migrated original library assertions failed; inspect per-ID status.');}
  executionComplete=true;
} catch(error){summary.error=String(error.message);process.exitCode=1;}
finally {
  await prototype?.close();await backend?.close();
  const evidenceValid=await recordBrowserEvidence(summary,output);
  if(executionComplete&&evidenceValid&&!summary.error)summary.status='PASS_WITH_DEFERRED';
  else {summary.status='FAIL';process.exitCode=1;}
  await writeFile(join(output,'summary.json'),JSON.stringify(summary,null,2));
  console.log(`${summary.mode}: ${summary.status}. Local ignored evidence: ${output}`);
  if(summary.error)console.error(summary.error);
}
