import type {V3DecisionEvidence,V3DecisionEvidenceCitation} from 'agent';
import './v3-records.css';
const roles:Record<V3DecisionEvidenceCitation['attribution'],string>={PER_RUN:'개별 Run 메모',SHARED_UNASSIGNED:'공동 메모 · 귀속 미확정',REFERENCE_ONLY:'비교 참조 · 대상 판단 아님'};
const decisions:Record<string,string>={ADOPT:'채택',HOLD:'보류',REJECT:'반려',ALTERNATIVE:'대안',COMPARISON:'비교'};
const statuses:Record<string,string>={NO_EVIDENCE:'관련 근거 없음',ASK_SCOPE:'확인할 Run 선택 필요',ASK_THRESHOLD:'제외 기준 입력 필요',INVALID_THRESHOLD:'제외 기준 확인 필요',UNAVAILABLE:'기록 검색을 완료하지 못했습니다',UNSUPPORTED_EXCLUSION_REASON:'지원하는 제외 기준을 확인해 주세요',RECORD_REQUEST_NOT_RECOGNIZED:'질문을 확인해 주세요'};

export function V3DecisionEvidenceCard({evidence}:{evidence:V3DecisionEvidence}){
 const rule=evidence.rules.action==='APPLY_EXISTING_COST_RULE';
 const excluded=new Set(evidence.rules.excludedRunIds);
 return <section className="v3-decision-evidence" aria-label={rule?'판단 기록 규칙 근거':'과거 판단 기록 검색 근거'} data-evidence-fingerprint={evidence.snapshotFingerprint}>
  <header><h3>{rule?'판단 기록 · 비용 반려 규칙':'과거 판단 기록 · RAG'}</h3><span className="v3-decision-evidence__badge">{evidence.synthetic?'모의 판단 기록':'저장된 판단 기록'}</span></header>
  {evidence.synthetic&&<p className="v3-decision-evidence__hint">실제 Run 수치에 연결한 모의 판단 이력입니다. 실제 사용자의 검토나 비용 측정 결과가 아닙니다.</p>}
  {statuses[evidence.status]&&<p className="v3-decision-evidence__warning" role="status">{statuses[evidence.status]}</p>}
  <div className="v3-decision-evidence__answer">{evidence.answer}</div>
  {rule&&evidence.rules.perRun.length>0&&<><div className="v3-decision-evidence__table" role="region" aria-label="비용 반려 전체 기록 집계" tabIndex={0}><table>
   <thead><tr><th>Run</th><th>비용 반려</th><th>기록 상태</th><th>이번 확인</th></tr></thead>
   <tbody>{evidence.rules.perRun.map(row=><tr key={row.runId}><td>{row.runId}</td><td>{row.count}건</td><td>{row.status}{row.mixed?' · 채택·반려 공존':''}</td><td>{excluded.has(row.runId)?'제외':'유지'}</td></tr>)}</tbody>
  </table></div><p className="v3-decision-evidence__hint">선택한 Run의 전체 판단 기록에 비용 반려 규칙을 적용한 결과입니다.</p></>}
  {!rule&&<p className="v3-decision-evidence__hint">선택 범위 {evidence.retrieval.totalInScope}개 문서 중 {evidence.retrieval.returned}개 인용</p>}
  {evidence.citations.map((citation,index)=><article className="v3-decision-evidence__source" key={`${citation.documentId}:${index}`}>
   <header><strong>[{citation.citationId}] {citation.subjectRunId??'후보 공동 기록'}</strong><span>{roles[citation.attribution]}</span></header>
   <p className="v3-decision-evidence__hint">{citation.decision?decisions[citation.decision]??citation.decision:'판단 미기록'}{citation.createdAt?` · ${citation.createdAt}`:''}</p>
   <blockquote>{citation.quote}</blockquote>
   {citation.attribution!=='PER_RUN'&&<p className="v3-decision-evidence__warning">이 문장을 현재 Run의 개별 반려 사유로 그대로 옮길 수 없습니다.</p>}
   <details><summary>저장된 원문 출처 정보</summary><dl><dt>기록 ID</dt><dd>{citation.recordId}</dd><dt>문서 ID</dt><dd>{citation.documentId}</dd><dt>기록 당시 Run 버전</dt><dd>{citation.recordRunVersionId??'공동 기록 · 개별 버전 없음'}</dd><dt>원문 해시</dt><dd>{citation.sourceNoteSha256}</dd><dt>기록 해시</dt><dd>{citation.sourceRecordSha256}</dd></dl></details>
  </article>)}
  {evidence.citations.length===0&&<p className="v3-decision-evidence__hint">이 답변에 인용할 판단 기록이 없습니다.</p>}
  {evidence.limitations.length>0&&<ul className="v3-decision-evidence__limitations" aria-label="판단 기록 해석의 한계">{evidence.limitations.map((text,index)=><li key={index}>{text}</li>)}</ul>}
 </section>;
}
