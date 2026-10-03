import {readFile,open,stat} from 'node:fs/promises';
import {join,basename} from 'node:path';

const MAX_CASES=5;
// Only summaries from the runner's artificial fixture are eligible for CI stdout.
// Never print attachments, response bodies, child stdout, code frames, or full logs.
function safe(value,limit=600) {
  return String(value??'').replace(/\u001b\[[0-9;]*m/g,'').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g,'')
    .replace(/\bBearer\s+\S+/gi,'Bearer <redacted>')
    .replace(/(["']?\b(?:password|token|secret|authorization)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,}]+)/gi,'$1<redacted>')
    .replace(/https?:\/\/\S+/g,'<URL>').replace(/(?:[A-Za-z]:)?\/(?:Users|home|private|tmp)\/[^\s)]+/g,'<path>')
    .replace(/\r?\n/g,' ').slice(0,limit);
}
function summary(error) {
  const message=String(error?.message??error?.value??'Failure without an error message.').replace(/\u001b\[[0-9;]*m/g,'');
  // Playwright appends call logs/source frames after the assertion header.
  const header=message.split(/\r?\n/).filter(line=>line.trim()).slice(0,6).filter(line=>!/^\s*(?:Call log:|\d+\s*\||>|at\s)/.test(line));
  return safe(header.join(' / '));
}
export async function syntheticFailureDiagnostics(output,{mode,directory='browser',logFile='browser.log'}={}) {
  if(mode!=='artificial-only')return [];
  const lines=[];
  try{
    const path=join(output,directory,'results.json');
    if((await stat(path)).size>8*1024*1024)throw new Error('Report exceeds diagnostic read bound.');
    const report=JSON.parse(await readFile(path,'utf8'));
    const walk=suite=>{
      for(const spec of suite.specs??[])for(const test of spec.tests??[]){
        if(test.status!=='unexpected'||lines.length>=MAX_CASES)continue;
        const result=(test.results??[]).findLast(result=>['failed','timedOut','interrupted'].includes(result.status))??test.results?.at(-1);
        const error=result?.errors?.[0]??result?.error;
        const location=`${safe(basename(spec.file??suite.file??'unknown'),120)}:${Number(spec.line)||0}:${Number(spec.column)||0}`;
        lines.push(`[synthetic browser failure] ${safe(spec.title,180)} at ${location}: ${summary(error)}`);
      }
      for(const child of suite.suites??[])walk(child);
    };
    for(const suite of report.suites??[])walk(suite);
    for(const error of report.errors??[])if(lines.length<MAX_CASES)lines.push(`[synthetic browser startup failure] ${summary(error)}`);
  }catch {/* No report, malformed or oversize: bounded log header fallback below. */}
  if(!lines.length){
    let file;
    try{
      file=await open(join(output,logFile),'r');const bytes=Buffer.alloc(16384);const {bytesRead}=await file.read(bytes,0,bytes.length,0);
      const error=bytes.subarray(0,bytesRead).toString('utf8').split(/\r?\n/).find(line=>/^\s*(?:Error|TimeoutError):/.test(line.replace(/\u001b\[[0-9;]*m/g,'')));
      lines.push(error?`[synthetic browser startup failure] ${safe(error)}`:'[synthetic browser failure] No case report or bounded error header available.');
    }catch {lines.push('[synthetic browser failure] No case report or bounded error header available.');}
    finally{await file?.close();}
  }
  return lines.map(line=>line.slice(0,800));
}
