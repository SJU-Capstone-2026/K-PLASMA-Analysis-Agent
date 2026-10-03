import {createHash} from 'node:crypto';

export const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
function instant(value) {
  const match=/^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d)$/.exec(value);
  if(!match)return null;
  const seconds=Date.parse(`${match[1]}${match[3]}`);
  return Number.isFinite(seconds)?`${seconds}:${(match[2]??'').padEnd(9,'0')}`:null;
}
/** Strict physical comparison. Only new immutable identity and equivalent ISO offset notation differ. */
export function compareRuns(expected, actual) {
  const failures = [];
  let assertions = 0;
  function compare(left, right, path) {
    assertions++;
    if (path.endsWith('.registeredAt') && typeof left === 'string' && typeof right === 'string') {
      if (!instant(left) || instant(left) !== instant(right)) failures.push(path);
    } else if (Array.isArray(left)) {
      if (!Array.isArray(right) || left.length !== right.length) {failures.push(path); return;}
      left.forEach((value,index)=>compare(value,right[index],`${path}[${index}]`));
    } else if (left && typeof left === 'object') {
      if (!right || typeof right !== 'object' || Array.isArray(right)) {failures.push(path); return;}
      if (JSON.stringify(Object.keys(left).sort()) !== JSON.stringify(Object.keys(right).sort())) failures.push(`${path}.keys`);
      for (const key of Object.keys(left)) compare(left[key],right[key],`${path}.${key}`);
    } else if (left !== right) failures.push(path);
  }
  if (actual.length !== expected.length || new Set(actual.map(run=>run.runId)).size !== actual.length) failures.push('runs.identity/count');
  const byId = new Map(actual.map(run=>[run.runId,run]));
  for (const run of expected) {
    const found = byId.get(run.runId);
    if (!found || typeof found.runVersionId !== 'string' || !found.runVersionId) {failures.push('runs.version');continue;}
    const {runVersionId: _identity, ...physical} = found;
    compare(run,physical,run.runId);
  }
  // Paths only, never source values. Persist even these reports in the ignored verification directory.
  return {runCount:expected.length,assertions,mismatches:failures.length,failures};
}
