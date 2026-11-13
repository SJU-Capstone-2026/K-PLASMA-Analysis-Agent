import {spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

test('memory calibration requires an existing explicit profile before starting any services',()=>{
 const script=fileURLToPath(new URL('./measure-local-llm.mjs',import.meta.url));
 for(const args of [[],['--env-file','/nonexistent/private.env'],['--skip-privacy'],
  ['--env-file',fileURLToPath(new URL('.',import.meta.url))]]){
  const result=spawnSync(process.execPath,['--',script,...args],{encoding:'utf8'});
  assert.equal(result.status,2);
  assert.match(result.stderr,/Usage:/);
  assert.equal(result.stdout,'');
 }
});
