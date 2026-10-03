import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {platform,arch,release} from 'node:os';
import {fileURLToPath} from 'node:url';

const groups={'agent-engine':18,'agent-view-models':10,analysis:9,'candidate-fit-view-models':6,'conversation-store':5,'decision-memory':10,engine:21,'explanation-engine':5,'multi-objective-search':4,'record-reuse':6,'record-selection':3,structure:5};
export const expectedAssertionIds=Object.entries(groups).flatMap(([name,count])=>Array.from({length:count},(_,index)=>`P-${name}-${String(index+1).padStart(2,'0')}`));
const structureIds=expectedAssertionIds.filter(id=>id.startsWith('P-structure-'));


export async function browserEvidence(output,directory='browser') {
  const report=JSON.parse(await readFile(join(output,directory,'results.json'),'utf8'));
  const specs=[];const walk=suite=>{specs.push(...(suite.specs??[]));for(const child of suite.suites??[])walk(child);};
  for(const suite of report.suites)walk(suite);
  const decoded=[];
  for(const spec of specs)for(const test of spec.tests)for(const result of test.results)for(const attachment of result.attachments??[]){
    if(['environment','layout-boundary','source-details-residual','source-details-parity','D1-deferred','memory-container-boundaries'].includes(attachment.name)&&attachment.body)decoded.push({name:attachment.name,...JSON.parse(Buffer.from(attachment.body,'base64').toString())});
  }
  const structure=Array.from({length:5},(_,index)=>{
    const id=`P-structure-${String(index+1).padStart(2,'0')}`;
    const cases=specs.filter(spec=>index===1?spec.title.includes('P-structure-02 real memory container boundaries and reduced motion'):index===4?spec.title.includes(id):/P-structure-01\/(?:02\/)?03\/04/.test(spec.title));
    const states=cases.flatMap(spec=>spec.tests.map(test=>test.status));
    const status=states.some(state=>state==='unexpected')?'FAIL':states.length&&states.every(state=>state==='expected')?'PASS':'UNVERIFIED';
    return {id,status,assertion:index===4?'frontend/e2e/reference-parity.spec.ts#P-structure-05':`frontend/e2e/core-flows.spec.ts#${id}`,caseCount:cases.length,externalOnlySkipped:states.length>0&&states.every(state=>state==='skipped')};
  });
  return {counts:report.stats,structureAssertions:structure,environment:{os:platform(),architecture:arch(),release:release(),playwright:JSON.parse(await readFile(new URL('../../node_modules/@playwright/test/package.json',import.meta.url),'utf8')).version,browser:decoded.find(item=>item.browser)?.browser??null,fontFamily:decoded.find(item=>item.fontFamily)?.fontFamily??null,locale:decoded.find(item=>item.locale)?.locale??null,timezone:decoded.find(item=>item.timezone)?.timezone??null,deviceScaleFactor:decoded.find(item=>item.deviceScaleFactor)?.deviceScaleFactor??null,apiMocking:decoded.find(item=>Object.hasOwn(item,'apiMocking'))?.apiMocking},disclosed:decoded.filter(item=>item.name!=='environment')};
}
/** Required evidence is part of the verdict, including when extraction itself fails. */
export async function recordBrowserEvidence(summary,output) {
  const errors=[];
  try{summary.browserEvidence=await browserEvidence(output,summary.browserDirectory);}
  catch(error){summary.browserEvidence={status:'UNVERIFIED',reason:'Required browser report absent or malformed.',errorCode:error.code??error.name,structureAssertions:structureIds.map(id=>({id,status:'UNVERIFIED',caseCount:0}))};errors.push('Required browser report could not be extracted.');}
  const supplied=summary.portableAssertions??[];
  if(!Array.isArray(supplied))errors.push('Portable assertion list is malformed.');
  const raw=[...(Array.isArray(supplied)?supplied:[]),...summary.browserEvidence.structureAssertions];
  if(raw.some(item=>!item||typeof item!=='object'))errors.push('Assertion entry is malformed.');
  const input=raw.filter(item=>item&&typeof item==='object');
  const actual=summary.mode==='external-reference';
  const allowed=actual?expectedAssertionIds:structureIds;
  const unexpected=input.filter(item=>!allowed.includes(item.id));
  if(unexpected.length)errors.push('Unexpected assertion IDs present.');
  const duplicates=allowed.filter(id=>input.filter(item=>item.id===id).length>1);
  if(duplicates.length)errors.push(`Duplicate assertion IDs: ${duplicates.join(', ')}.`);
  // Keep every expected ID diagnostic even for an absent/unreadable report; invalid supplied entries are retained separately.
  summary.prototypeAssertions=(actual?expectedAssertionIds:structureIds).map(id=>input.find(item=>item.id===id)??{id,status:'UNVERIFIED',reason:'Required assertion missing.'});
  summary.assertionDiagnostics={unexpected,duplicates};
  for(const item of summary.prototypeAssertions){
    if(!['PASS','FAIL','UNVERIFIED'].includes(item.status))errors.push(`Invalid status for ${item.id}.`);
    const externalSkip=!actual&&item.id==='P-structure-05'&&item.status==='UNVERIFIED'&&summary.browserEvidence.structureAssertions.find(x=>x.id===item.id)?.externalOnlySkipped===true;
    if(item.status!=='PASS'&&!externalSkip)errors.push(`Required assertion ${item.id}: ${item.status}.`);
  }
  const env=summary.browserEvidence.environment??{};
  for(const key of ['expected','skipped','unexpected','flaky'])if(!Number.isInteger(summary.browserEvidence.counts?.[key])||summary.browserEvidence.counts[key]<0)errors.push(`Required browser report count missing: ${key}.`);
  for(const key of ['os','architecture','release','playwright','browser','fontFamily','locale','timezone'])if(typeof env[key]!=='string'||!env[key].trim())errors.push(`Required browser metadata missing: ${key}.`);
  for(const key of ['node','java','locale','timezone'])if(typeof summary[key]!=='string'||!summary[key].trim())errors.push(`Required runtime metadata missing: ${key}.`);
  if(env.deviceScaleFactor!==1||env.apiMocking!==false)errors.push('Required browser scale/unmocked metadata missing.');
  if((summary.browserEvidence.counts?.unexpected??0)>0||(summary.browserEvidence.counts?.flaky??0)>0)errors.push('Browser report contains unexpected or flaky cases.');
  summary.evidenceValidation={status:errors.length?'FAIL':'PASS',errors};
  if(errors.length){summary.status='FAIL';summary.error??='Mandatory browser/assertion evidence validation failed.';}
  return errors.length===0;
}
// Validate retained evidence without repeating imports/browser execution. An earlier failure is never promoted here.
if(process.argv[1]===fileURLToPath(import.meta.url)){
  const output=process.argv[2];if(!output)throw new Error('Pass the ignored verification output directory.');
  const summary=JSON.parse(await readFile(join(output,'summary.json'),'utf8'));
  const valid=await recordBrowserEvidence(summary,output);
  await writeFile(join(output,'summary.json'),JSON.stringify(summary,null,2));
  console.log(`Evidence ${valid?'PASS':'FAIL'}: ${summary.prototypeAssertions.length} diagnostic assertion statuses (no data values).`);
  if(!valid)process.exitCode=1;
}
