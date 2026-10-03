import {readFile,readdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {basename,join} from 'node:path';
import {digest} from './compare-runs.mjs';
import {repo} from './runtime.mjs';

/** Re-execute the 97 external behavioral assertions against the NEW ESM library.
 * Structure's 5 source-regex checks are replaced by concrete React browser assertions.
 * No assertion error payload is printed: it can contain actual physical values.
 */
export async function comparePrototypeAssertions(reference) {
  const results=[];
  const requireOriginal=createRequire(join(reference.testsRoot,'loader.cjs'));
  for(const file of (await readdir(reference.testsRoot)).filter(file=>file.endsWith('.test.js')).sort()) {
    if(file==='structure.test.js')continue;
    const callbacks=[];
    const source=await readFile(join(reference.testsRoot,file),'utf8');
    const modules={};
    for(const match of source.matchAll(/require\(['"](\.\.\/prototype\/assets\/[^'"]+)['"]\)/g)) {
      const name=basename(match[1]).replace(/\.js$/,'');
      modules[match[1]]=['mock-data','analysis-data'].includes(name)?requireOriginal(match[1]):await import(join(repo,'agent/src/fallback',`${name}.js`));
      if(name==='view-models'){
        const model=modules[match[1]];
        // New library deliberately receives Runs from its caller instead of closing over a bundled dataset.
        // The original assertions retain their expected values; only this dependency argument is supplied.
        const dataName=file==='engine.test.js'?'mock-data':'analysis-data';
        const supplied=requireOriginal(`../prototype/assets/${dataName}.js`).runs;
        modules[match[1]]={...model,buildForwardViewModel:(result,runs)=>model.buildForwardViewModel(result,runs??supplied)};
      }
    }
    const requireReplacement=name=>name==='node:test'?((name,callback)=>callbacks.push({name,callback})):(Object.hasOwn(modules,name)?modules[name]:requireOriginal(name));
    new Function('require','__dirname',source)(requireReplacement,reference.testsRoot);
    for(const [index,item] of callbacks.entries()) {
      const id=`P-${file.replace('.test.js','')}-${String(index+1).padStart(2,'0')}`;
      try {await item.callback();results.push({id,name:item.name,status:'PASS',assertion:`scripts/reference/compare-tests.mjs#${id}`});}
      catch(error){results.push({id,name:item.name,status:'FAIL',assertion:`scripts/reference/compare-tests.mjs#${id}`,errorDigest:digest(String(error))});}
    }
  }
  if(results.length!==97)throw new Error(`Expected 97 portable original assertions, found ${results.length}; update mapping explicitly.`);
  return results;
}
