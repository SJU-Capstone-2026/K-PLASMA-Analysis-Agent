import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {platform,arch,release} from 'node:os';
import {fileURLToPath} from 'node:url';

export async function browserEvidence(output,directory='browser') {
  const report=JSON.parse(await readFile(join(output,directory,'results.json'),'utf8'));
  const specs=[];const walk=suite=>{specs.push(...(suite.specs??[]));for(const child of suite.suites??[])walk(child);};
  for(const suite of report.suites)walk(suite);
  const decoded=[];
  for(const spec of specs)for(const test of spec.tests)for(const result of test.results)for(const attachment of result.attachments??[]){
    if(['environment','layout-boundary','source-details-residual','D1-deferred'].includes(attachment.name)&&attachment.body)decoded.push({name:attachment.name,...JSON.parse(Buffer.from(attachment.body,'base64').toString())});
  }
  const structure=Array.from({length:5},(_,index)=>{
    const id=`P-structure-${String(index+1).padStart(2,'0')}`;
    const cases=specs.filter(spec=>index===4?spec.title.includes(id):spec.title.includes('P-structure-01/02/03/04'));
    const states=cases.flatMap(spec=>spec.tests.map(test=>test.status));
    const status=states.some(state=>state==='unexpected')?'FAIL':states.length&&states.every(state=>state==='expected')?'PASS':'UNVERIFIED';
    return {id,status,assertion:index===4?'frontend/e2e/reference-parity.spec.ts#P-structure-05':`frontend/e2e/core-flows.spec.ts#${id}`,caseCount:cases.length};
  });
  return {counts:report.stats,structureAssertions:structure,environment:{os:platform(),architecture:arch(),release:release(),playwright:JSON.parse(await readFile(new URL('../../node_modules/@playwright/test/package.json',import.meta.url),'utf8')).version,browser:decoded.find(item=>item.browser)?.browser??null,fontFamily:decoded.find(item=>item.fontFamily)?.fontFamily??null},disclosed:decoded.filter(item=>item.name!=='environment')};
}
// Allows metadata extraction from retained evidence without repeating imports or browser execution.
if(process.argv[1]===fileURLToPath(import.meta.url)){
  const output=process.argv[2];if(!output)throw new Error('Pass the ignored verification output directory.');
  const summary=JSON.parse(await readFile(join(output,'summary.json'),'utf8'));const evidence=await browserEvidence(output,summary.browserDirectory);
  summary.browserEvidence=evidence;
  summary.prototypeAssertions=[...(summary.portableAssertions??[]),...evidence.structureAssertions];
  await writeFile(join(output,'summary.json'),JSON.stringify(summary,null,2));
  console.log(`Recorded browser metadata and ${summary.prototypeAssertions.length} assertion statuses (no data values).`);
}
