// Opt-in, read-only comparison with the external v12.3.1 scalar search engine.
// External Run values stay in process memory; stdout contains aggregate counts only.
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
const repository=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const source=process.env.KPLASMA_PROTOTYPE_ROOT;
if(!source)throw new Error('Set KPLASMA_PROTOTYPE_ROOT to the external v12.3.1 prototype directory.');
const sandbox=vm.createContext({});
const hashes={};
for(const name of ['mock-data','analysis-data','engine']){
 const bytes=await readFile(join(source,'assets',`${name}.js`));
 hashes[name]=createHash('sha256').update(bytes).digest('hex');
 vm.runInContext(bytes.toString('utf8'),sandbox,{timeout:10000});
}
const engine=sandbox.KPlasmaEngine;
const keys=['runId','pressure','sourcePower','biasPower','metrics','qualityStatus','convergenceStatus','catalogStatus','presentationScore'];
const runs=sandbox.KPlasmaAnalysisData.runs.map((r,i)=>({...Object.fromEntries(keys.map(k=>[k,r[k]])),runVersionId:`reference-${i}`}));
const conditions=['pressure','sourcePower','biasPower'];
const forward=runs.map(r=>Object.fromEntries(conditions.map(k=>[k,r[k]])));
forward.push({pressure:3,sourcePower:250,biasPower:500});
const units={pressure:'mTorr',sourcePower:'W',biasPower:'W',meanIonEnergy:'eV',ionFlux:'10¹⁸ m⁻²s⁻¹',iedWidth:'eV'};
const output=['meanIonEnergy','ionFlux','iedWidth'];
const reverse=[];
for(const metric of output)for(const direction of ['MAX','MIN'])reverse.push({constraints:[],goals:[{metric,direction,unit:units[metric]}]});
for(const metric of [...conditions,...output]){
 const values=runs.filter(r=>r.qualityStatus==='VERIFIED'&&r.convergenceStatus==='CONVERGED'&&r.catalogStatus==='READY').map(r=>conditions.includes(metric)?r[metric]:r.metrics[metric]).filter(Number.isFinite).sort((a,b)=>a-b);
 for(const operator of ['MIN','MAX'])reverse.push({constraints:[{metric,operator,value:values[Math.floor(values.length/2)],unit:units[metric]}],goals:[{metric:'ionFlux',direction:'MAX',unit:units.ionFlux}]});
 reverse.push({constraints:[{metric,operator:'RANGE',min:values[Math.floor(values.length/4)],max:values[Math.floor(values.length*3/4)],unit:units[metric]}],goals:[]});
}
reverse.push({constraints:[{metric:'ionFlux',operator:'MIN',value:Number.MAX_SAFE_INTEGER,unit:units.ionFlux}],goals:[]});
const expectedForward=forward.map(c=>{const r=engine.searchForward(c,runs);return {status:r.status,runId:r.run?.runId??null,deltas:r.deltas,metrics:r.run?.metrics??null};});
const expectedReverse=reverse.map(query=>{
 const objectives=query.constraints.filter(c=>output.includes(c.metric)).map((c,i)=>({...c,id:`objective-${i+1}`}));
 const r=engine.searchReverse({...query,objectives,analysisType:'REVERSE',confirmed:true},runs);
 if(r.status==='INVALID')throw new Error('Reference query schema invalid.');
 return {status:r.status,common:r.commonRunIds,goals:r.goalResults.map(g=>g.candidates.map(r=>r.runId)),near:r.nearMatches.map(e=>e.run.runId)};
});
const child=spawnSync(process.env.KPLASMA_PYTHON??join(repository,'agent/python/.venv/bin/python'),[join(repository,'scripts/agent/reference-parity.py')],{
 cwd:repository,env:{...process.env,PYTHONPATH:join(repository,'agent/python/src')},
 input:JSON.stringify({runs,forward,reverse,expectedForward,expectedReverse,hashes}),encoding:'utf8',maxBuffer:16*1024*1024,
});
if(child.status!==0){console.error('External scalar comparison failed; no private payload emitted.');process.exitCode=1;}
if(child.stdout)console.log(child.stdout.trim());
