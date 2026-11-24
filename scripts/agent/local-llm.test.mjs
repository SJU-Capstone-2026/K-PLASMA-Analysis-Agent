import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {copyFileSync,existsSync,mkdirSync,mkdtempSync,readFileSync,realpathSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const launcher=fileURLToPath(new URL('./local-llm.mjs',import.meta.url));

function invoke(script,args=[]){return spawnSync(process.execPath,['--',script,...args],{encoding:'utf8'});}

function fixture(t,{ready=false,invalid=false}={}){
 const root=mkdtempSync(join(tmpdir(),'kplasma-local-launch-'));
 t.after(()=>rmSync(root,{recursive:true,force:true}));
 mkdirSync(join(root,'scripts/agent'),{recursive:true});
 mkdirSync(join(root,'agent/python/.venv/bin'),{recursive:true});
 const script=join(root,'scripts/agent/local-llm.mjs');
 copyFileSync(launcher,script);
 const envFile=join(root,"local-$(literal)' profile.env");
 writeFileSync(envFile,'AGENT_V2_LOCAL_LLM_PLAN_REVIEW_ENABLED=true\n');
 const marker=join(root,'started.json');
 writeFileSync(join(root,'agent/python/.venv/bin/python'),`#!${process.execPath}
import {writeFileSync} from 'node:fs';
const args=process.argv.slice(2);
if(args.includes('--check')){
 console.error('private-provider-body-MUST-NOT-APPEAR');
 console.log(${invalid?JSON.stringify('provider token=private-MUST-NOT-APPEAR'):JSON.stringify(JSON.stringify({ready,blockers:ready?[]:['LOCAL_PRIVACY_UNVERIFIED']}))});
 process.exit(${ready?0:2});
}
writeFileSync(${JSON.stringify(marker)},JSON.stringify({args,pythonPath:process.env.PYTHONPATH}));
`,{mode:0o700});
 return {root,script,envFile,marker};
}

test('launcher requires an explicit local profile before starting a worker',()=>{
 const result=invoke(launcher,['start']);
 assert.equal(result.status,2);
 assert.deepEqual(JSON.parse(result.stdout).blockers,['LOCAL_ENV_FILE_REQUIRED']);
});

test('pending readiness cannot launch a worker or expose provider diagnostics',t=>{
 const f=fixture(t);
 const result=invoke(f.script,['start','--env-file',f.envFile]);
 assert.equal(result.status,2);
 assert.equal(existsSync(f.marker),false);
 assert.deepEqual(JSON.parse(result.stdout).blockers,['LOCAL_PRIVACY_UNVERIFIED']);
 assert.doesNotMatch(result.stdout+result.stderr,/MUST-NOT-APPEAR/);
});

test('only the private worker is launched after the authoritative readiness check',t=>{
 const f=fixture(t,{ready:true});
 const result=invoke(f.script,['start','--env-file',f.envFile]);
 assert.equal(result.status,0,result.stderr);
 const started=JSON.parse(readFileSync(f.marker,'utf8'));
 assert.deepEqual(started.args,['-m','kplasma_agent.v2_local_llm.worker','--env-file',resolve(f.envFile)]);
 assert.equal(started.pythonPath,join(realpathSync(f.root),'agent/python/src'));
});

test('status keeps guard errors redacted and never promotes malformed evidence',t=>{
 const f=fixture(t,{invalid:true});
 const result=invoke(f.script,['status','--env-file',f.envFile]);
 assert.equal(result.status,2);
 const status=JSON.parse(result.stdout);
 assert.equal(status.ready,false);
 assert.deepEqual(status.blockers,['LOCAL_READINESS_CHECK_INVALID']);
 assert.doesNotMatch(result.stdout+result.stderr,/MUST-NOT-APPEAR/);
 assert.equal(existsSync(f.marker),false);
});

test('smoke runs the synthetic probe module and does not start a worker',t=>{
 const f=fixture(t);
 const result=invoke(f.script,['smoke','--env-file',f.envFile]);
 assert.equal(result.status,0,result.stderr);
 const started=JSON.parse(readFileSync(f.marker,'utf8'));
 assert.deepEqual(started.args,['-m','evals.local_llm_smoke','--env-file',resolve(f.envFile),'--live']);
});

test('smoke resolves the real evaluator and refuses disabled review without contacting models',t=>{
 const python=fileURLToPath(new URL('../../agent/python/.venv/bin/python',import.meta.url));
 if(!existsSync(python)){t.skip('Python environment is not installed');return;}
 const temporary=mkdtempSync(join(tmpdir(),'kplasma-smoke-profile-'));
 t.after(()=>rmSync(temporary,{recursive:true,force:true}));
 const envFile=join(temporary,'local.env');
 writeFileSync(envFile,'AGENT_V2_LOCAL_LLM_PLAN_REVIEW_ENABLED=false\n');
 const result=invoke(launcher,['smoke','--env-file',envFile]);
 assert.equal(result.status,2,result.stderr);
 assert.equal(JSON.parse(result.stdout).code,'SMOKE_PLAN_REVIEW_REQUIRED');
});

test('unknown options fail before any child process starts',t=>{
 const f=fixture(t,{ready:true});
 const result=invoke(f.script,['start','--env-file',f.envFile,'--skip-privacy']);
 assert.equal(result.status,2);
 assert.deepEqual(JSON.parse(result.stdout).blockers,['LOCAL_CLI_USAGE']);
 assert.equal(existsSync(f.marker),false);
});
