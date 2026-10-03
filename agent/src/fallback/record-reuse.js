// v12.3.1: preserved pure implementation; only IIFE/module boundaries changed.

function classify(note) {
  const text = String(note || '').trim();
  if (!text) return 'MISSING';
  if (/(비용|원가|가격).{0,15}(없|않|아니|아님|무관|괜찮|적정)/.test(text)) return 'NO_COST';
  if (/(해결|해소|지만|그러나|다만|반면)/.test(text)) return 'UNCLEAR';
  if (/(비용|원가|가격).{0,15}(높|비싸|초과|부담|때문|문제|과다)|예산.{0,8}초과/.test(text) && !/(불명|확인|추정|모르|\?)/.test(text)) return 'COST';
  if (/(성능|균일도|에너지|플럭스).{0,12}(때문|미달|문제|부족)/.test(text)) return 'OTHER';
  return 'UNCLEAR';
}
function evidence(records, runId) {
  return records.flatMap((record) => {
    const candidates = record.version === 2 ? record.candidates || [] : [{runId:record.targetRunId,decision:record.decision,note:record.comment}];
    const candidate = candidates.find((item) => item.runId === runId);
    if (!candidate) return [];
    // Shared comments are only attributable when the record has one candidate.
    const note = candidate.note || (candidates.length === 1 ? record.overallComment : '') || '';
    const foreignRun = (note.match(/RUN-[A-Z0-9-]+/g) || []).some((id)=>id!==runId);
    const snapshot = (record.runSnapshots || []).find((r)=>r.runId===runId);
    return [{recordId:record.reviewId || record.id,runId,decision:candidate.decision,note,sharedComment:record.overallComment || '',reason:foreignRun?'UNCLEAR':classify(note),createdAt:record.createdAt,question:record.question || record.queryText || '',conditions:candidate.conditions || snapshot?.conditions || {},demo:Boolean(record.isDemo)}];
  });
}
function summarize(records, runId) {
  const entries = evidence(records,runId);
  const count = new Set(entries.filter((e) => e.decision === 'REJECT' && e.reason === 'COST').map((e) => e.recordId)).size;
  const status = !entries.length ? '관련 기록 없음' : count ? `비용 반려 ${count}건` : entries.some((e)=>e.reason==='NO_COST') ? '비용 문제 없음 기록' : entries.some((e)=>e.decision==='REJECT' && e.reason==='MISSING') ? '반려 사유 미기록' : entries.some((e)=>e.reason==='UNCLEAR') ? '사유 확인 필요' : '비용 반려 근거 없음';
  return {runId,count,status,entries,mixed:entries.some((e)=>e.decision==='ADOPT') && entries.some((e)=>e.decision==='REJECT')};
}
function filter(records, ids, threshold=1) {
  if (threshold !== Infinity && (!Number.isInteger(threshold) || threshold < 1)) throw new Error('제외 기준은 1 이상의 정수여야 합니다.');
  const summaries = [...new Set(ids)].map((id)=>summarize(records,id));
  return {remaining:summaries.filter((s)=>s.count<threshold),excluded:summaries.filter((s)=>s.count>=threshold)};
}
function parse(text) {
  if (!/(반려|과거 기록|이전.*이유)/.test(text)) return null;
  const exclude = /제외|빼/.test(text);
  const number = text.match(/([+-]?\d+(?:\.\d+)?)\s*건\s*이상/);
  return {exclude,threshold:number ? Number(number[1]) : /많/.test(text) && exclude ? null : 1};
}
export {classify,evidence,summarize,filter,parse};
