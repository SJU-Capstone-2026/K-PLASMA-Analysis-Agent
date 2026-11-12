"""Retrieval-augmented, extractive answers with immutable record citations.

No LLM or network client is instantiated here. The writer uses retrieved text
verbatim and whole-record policy counts; it never invents physics or reasons.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import policy
from .attribution import annotate_documents, select_documents
from .evidence_selection import EVIDENCE_SELECTION_POLICY, assess_requested_evidence
from .facets import FACET_POLICY, select_by_facets
from .index import LocalIndex
from .support import SUPPORT_POLICY


class RagServiceError(ValueError):
    code = "INVALID_RAG_REQUEST"


class RagService:
    def __init__(self, corpus, encoder, index_dir: Path, *, min_score=0.78, relative_margin=0.08,
                 reranker=None, min_rerank_score=None, strict_support=True, experimental_facets=False,
                 include_rules=True):
        if not math.isfinite(min_score) or not math.isfinite(relative_margin):
            raise RagServiceError("검색 점수 설정이 올바르지 않습니다.")
        self.corpus, self.encoder = corpus, encoder
        self.index = LocalIndex(corpus, encoder, index_dir)
        self.index_stats = self.index.stats
        self.min_score, self.relative_margin = min_score, relative_margin
        if min_rerank_score is not None and (isinstance(min_rerank_score, bool)
                or not isinstance(min_rerank_score, (float, int)) or not math.isfinite(min_rerank_score)):
            raise RagServiceError("재정렬 점수 설정이 올바르지 않습니다.")
        self.reranker = reranker
        self.min_rerank_score = float(min_rerank_score) if min_rerank_score is not None else None
        self.strict_support = strict_support
        if not isinstance(experimental_facets, bool):
            raise RagServiceError("실험용 조건 검사 설정이 올바르지 않습니다.")
        self.experimental_facets = experimental_facets
        self.include_rules = include_rules

    def ask(self, question, run_ids, top_k=5, mode="semantic", version_scope="history", run_refs=None):
        if not isinstance(question, str) or not question.strip() or len(question) > 4000:
            raise RagServiceError("질문을 1~4000자로 입력해 주세요.")
        if mode not in {"semantic", "records", "exclude", "auto"}:
            raise RagServiceError("지원하지 않는 질문 모드입니다.")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
            raise RagServiceError("결과 개수는 1~20 사이의 정수여야 합니다.")
        if not isinstance(run_ids, (list, tuple)) or any(not isinstance(r, str) or not r for r in run_ids):
            raise RagServiceError("조회할 Run 범위를 명시해 주세요.")
        run_ids = list(dict.fromkeys(run_ids))
        if len(run_ids) > 150:
            raise RagServiceError("한 번에 최대 150개 Run을 조회할 수 있습니다.")
        synthetic = bool(self.corpus.manifest.get("synthetic", True))
        response = {"schemaVersion": "decision-rag.v1", "synthetic": synthetic,
                    "offline": not bool(self.corpus.manifest.get("appImportReady", False)),
                    "generation": "extractive-local-v1", "question": question, "mode": mode,
                    "status": "ANSWERED", "answer": "", "citations": [], "rules": {},
                    "retrieval": {"totalInScope": 0, "returned": 0, "model": self.encoder.metadata["model"],
                                  "minScore": self.min_score, "relativeMargin": self.relative_margin,
                                  "versionScope": version_scope, "similarityIsProbability": False},
                    "limits": ["모의 판단 기록이며 실제 사용자의 검토나 비용 측정이 아닙니다." if synthetic else
                               "저장된 사용자 판단 기록이며 물리 인과나 비용 측정을 대신하지 않습니다.",
                               "수치 검색·시뮬레이션·비교를 새로 실행하지 않습니다.",
                               "의미 검색은 기존 자동 제외 정책을 변경하지 않습니다."]}
        if not run_ids:
            response.update(status="ASK_SCOPE", answer="조회할 Run을 먼저 선택해 주세요. 전체 기록으로 범위를 넓히지 않습니다.")
            return response
        scoped = self.corpus.scoped_documents(run_ids, version_scope=version_scope, run_refs=run_refs)
        parsed = policy.parse_request(question)
        if mode == "auto":
            mode = "exclude" if parsed and parsed["exclude"] else "semantic"
            response["mode"] = mode
        threshold = parsed["threshold"] if parsed else None
        if not self.include_rules and mode != "semantic":
            raise RagServiceError("V3_FEATURE_DISABLED")
        summaries = [policy.summarize(self.corpus.records, run) for run in run_ids] if self.include_rules else []
        if mode == "semantic":
            action = "PROPOSED_RAG_RETRIEVAL"
        elif mode == "records":
            action = "VIEW_RECORDS"
        elif parsed is None:
            action = "RECORD_REQUEST_NOT_RECOGNIZED"
        elif not parsed["exclude"]:
            action = "VIEW_RECORDS"
            mode = "records"
            response["mode"] = mode
        elif not policy.mentions_cost(question):
            action = "UNSUPPORTED_EXCLUSION_REASON"
        elif threshold is None:
            action = "ASK_THRESHOLD"
        elif not policy.valid_threshold(threshold):
            action = "INVALID_THRESHOLD"
        else:
            action = "APPLY_EXISTING_COST_RULE"
        excluded = [s["runId"] for s in summaries if action == "APPLY_EXISTING_COST_RULE" and s["count"] >= threshold]
        response["rules"] = {"policy": policy.RECORD_POLICY_VERSION, "action": action, "threshold": threshold,
                             "aggregationScope": "ALL_RECORDS_FOR_RUN_ID_INCLUDING_HISTORY",
                             "perRun": [{k: s[k] for k in ("runId", "count", "status", "mixed")} |
                                        {"costRejectionRecordIds": sorted({e["recordId"] for e in s["entries"]
                                          if e["reason"] == "COST" and e["decision"] == "REJECT"})} for s in summaries],
                             "excludedRunIds": excluded, "remainingRunIds": [r for r in run_ids if r not in excluded],
                             "completeAggregation": True}
        response["retrieval"]["totalInScope"] = len(scoped)
        blocked = {"ASK_THRESHOLD": "비용 반려 몇 건 이상을 제외할지 기준을 알려주세요.",
                   "INVALID_THRESHOLD": "제외 기준은 1 이상의 정수여야 합니다. 후보를 제외하지 않았습니다.",
                   "UNSUPPORTED_EXCLUSION_REASON": "현재 자동 제외는 비용 사유만 지원합니다. 후보를 제외하지 않았습니다.",
                   "RECORD_REQUEST_NOT_RECOGNIZED": "비용 반려 N건 이상 제외처럼 기록 요청과 기준을 명시해 주세요."}
        if action in blocked:
            response.update(status=action, answer=blocked[action])
            return response
        if mode == "records":
            hits = sorted(annotate_documents(scoped),
                          key=lambda d: (d.get("createdAt", ""), d["documentId"]), reverse=True)[:top_k]
            response["retrieval"]["strategy"] = "SCOPED_RECORD_LIST"
        elif action == "APPLY_EXISTING_COST_RULE":
            eligible = {(s["runId"], e["recordId"]) for s in summaries for e in s["entries"]
                        if e["reason"] == "COST" and e["decision"] == "REJECT"}
            hits = [d for d in annotate_documents(scoped) if d.get("scopeRole") != "REFERENCE_ONLY"
                    and (d.get("runId"), d["recordId"]) in eligible][:top_k]
            response["retrieval"]["strategy"] = "COMPLETE_RULE_AGGREGATION_WITH_PROOF"
        else:
            selected_docs = select_documents(question, scoped, selected_run_ids=run_ids)
            facet_selection = (select_by_facets(question, selected_docs)
                               if self.experimental_facets and self.strict_support and len(selected_docs) >= 30 else None)
            if facet_selection is not None:
                eligible_docs = facet_selection.documents
            else:
                assessments = [assess_requested_evidence(question, doc) for doc in selected_docs] if self.strict_support else []
                eligible_docs = ([doc for doc, assessment in zip(selected_docs, assessments, strict=True)
                                  if assessment.supported] if self.strict_support else selected_docs)
            response["retrieval"]["searchableInScope"] = len(eligible_docs)
            hits = self.index.search(question, eligible_docs, top_k=20 if self.reranker else top_k,
                                     min_score=self.min_score, relative_margin=self.relative_margin)
            response["retrieval"]["strategy"] = "LOCAL_DENSE_LEXICAL_RECALL"
            response["retrieval"]["strictExplicitSupport"] = self.strict_support
            response["retrieval"]["supportPolicy"] = SUPPORT_POLICY if self.strict_support else "disabled"
            response["retrieval"]["selectionPolicy"] = EVIDENCE_SELECTION_POLICY if self.strict_support else "disabled"
            response["retrieval"]["rejectedByExplicitSelection"] = len(selected_docs) - len(eligible_docs)
            if facet_selection is not None:
                response["retrieval"]["selectionPolicy"] = FACET_POLICY
                response["retrieval"]["requiredFacetCount"] = len(facet_selection.required_facets)
            if self.reranker is not None:
                scores = self.reranker.score(question, [doc["text"] for doc in hits])
                if len(scores) != len(hits) or not all(math.isfinite(float(value)) for value in scores):
                    raise RagServiceError("재정렬 모델에서 유효한 점수를 얻지 못했습니다.")
                pairs = [(doc, float(score)) for doc, score in zip(hits, scores, strict=True)
                         if self.min_rerank_score is None or float(score) >= self.min_rerank_score]
                best = max((score for _doc, score in pairs), default=-math.inf)
                if best >= 0:
                    pairs = [(doc, score) for doc, score in pairs if score >= best - 6.0]
                    pairs.sort(key=lambda pair: (-pair[1], -pair[0]["score"], pair[0]["documentId"]))
                else:
                    # Negative logits are uncalibrated; retain semantic coverage.
                    pairs.sort(key=lambda pair: (-pair[0]["score"], pair[0]["documentId"]))
                hits = [doc for doc, _score in pairs[:top_k]]
                response["retrieval"].update(strategy="LOCAL_HYBRID_CROSS_ENCODER",
                    reranker=self.reranker.metadata, minRerankScore=self.min_rerank_score,
                    rerankScoreIsProbability=False, positiveRerankMargin=6.0)
        for i, doc in enumerate(hits):
            attribution = doc.get("citationRole", "REFERENCE_ONLY" if doc.get("scopeRole") == "REFERENCE_ONLY"
                                  else doc["attribution"])
            response["citations"].append({"citationId": f"S{i + 1}", "documentId": doc["documentId"],
                "recordId": doc["recordId"], "runId": doc.get("runId"),
                "offlineRunVersionId": doc.get("offlineRunVersionId"), "attribution": attribution,
                "sourceAttribution": doc["attribution"], "matchedRunIds": doc.get("matchedRunIds", []),
                "quote": doc["text"][:2000], "score": doc.get("score"), "decision": doc.get("decision"),
                "createdAt": doc.get("createdAt"), "sourceNoteSha256": doc["sourceNoteSha256"],
                "sourceRecordSha256": doc["sourceRecordSha256"], "synthetic": synthetic})
        response["retrieval"]["returned"] = len(response["citations"])
        if action == "APPLY_EXISTING_COST_RULE":
            answer = [f"비용 반려 {threshold}건 이상 기준으로 제외 {len(excluded)}개, 유지 {len(run_ids) - len(excluded)}개입니다.",
                      "건수는 검색 상위 결과가 아닌 전체 저장 기록의 고유 ID로 계산했습니다."]
        elif not hits:
            response["status"] = "NO_EVIDENCE"
            answer = ["선택한 범위와 검색 기준에서 답변을 뒷받침할 메모를 찾지 못했습니다.",
                      "관련 기록이 없거나 검색에서 놓쳤을 수 있으므로 반려 이유를 새로 만들지 않습니다."]
        elif mode == "records":
            answer = [f"선택한 범위의 메모 {len(scoped)}개 중 {len(hits)}개를 표시합니다."]
        else:
            answer = [f"선택한 범위에서 관련 메모 {len(hits)}개를 찾았습니다. 아래는 " +
                      ("모의 판단 기록" if synthetic else "저장된 판단 기록") + "의 원문 근거입니다."]
        if hits:
            labels = {"PER_RUN": "후보별 메모", "SHARED_UNASSIGNED": "공통 메모 · 개별 귀속 불명", "REFERENCE_ONLY": "비교 참조 기록"}
            for citation in response["citations"]:
                answer.append(f"[{citation['citationId']}] {labels[citation['attribution']]}: “{citation['quote']}”")
            if any(c["attribution"] != "PER_RUN" for c in response["citations"]):
                answer.append("공동·비교 메모를 이 Run의 개별 반려 사유로 확정하지 않습니다. "
                              "아래 비용 반려 건수는 보존한 기존 문구 분류 규칙으로 별도 집계한 값입니다.")
        for summary in summaries:
            answer.append(f"{summary['runId']}: 기존 규칙의 비용 반려 {summary['count']}건" +
                          (" · 채택과 반려 이력 공존" if summary["mixed"] else ""))
        if mode == "exclude" and policy.has_numeric_condition(question):
            answer.append("현재 선택된 Run의 기록 단계만 검토했습니다. 질문의 수치 검색과 후속 비교는 실행하지 않았습니다.")
        response["answer"] = "\n\n".join(answer)
        return response
