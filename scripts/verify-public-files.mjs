import {execFileSync} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(fileURLToPath(new URL('..',import.meta.url)));
const files=[...new Set(execFileSync('git',['ls-files','--cached','--others','--exclude-standard','-z'],{cwd:root,encoding:'utf8'}).split('\0').filter(Boolean))];
const denied=/(^|\/)(?:\.runtime|storage|\.local-data|data|datasets|results|backups|node_modules|playwright-report|test-results|\.idea)(\/|$)|(^|\/)analysis-data\.js$|K-PLASMA\(0D\)-RESULTS-DATA/;
const failures=[];
for(const file of files) {
  const fieldDocumentation=file==='docs/data/parser-field-map.md';
  if((denied.test(file)&&!fieldDocumentation)||(/(^|\/)\.env(?:\.|$)/.test(file)&&!file.endsWith('.example'))) {failures.push(`${file}: prohibited public path`);continue;}
  if(!/\.(?:js|ts|tsx|json|java|py|md|yml|yaml|toml|env|html|xml)$/.test(file))continue;
  const text=await readFile(resolve(root,file),'utf8');
  // Full actual analysis payload signatures; artificial small fixtures and field definitions remain allowed.
  if((text.match(/RUN-P\d{2}-S\d{3}-B\d{4}/g)??[]).length>100 && /iedDistribution|residualTrace/.test(text))failures.push(`${file}: possible actual Run payload`);
  if(/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/.test(text))failures.push(`${file}: private key`);
}
if(failures.length){console.error(failures.join('\n'));process.exitCode=1;}
else console.log(`Public tracked-file guard PASS (${files.length} files; heuristic guard, also review git diff).`);
