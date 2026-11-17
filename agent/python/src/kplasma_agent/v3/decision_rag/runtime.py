"""V3-owned retrieval and cost-rule tool over a fenced, immutable record inventory."""
from pathlib import Path
import os

from ..domain.common import DomainError
from ..runtime import normalize_mode, require_action
from . import policy
from .live_corpus import digest, live_corpus


def retrieval_profile():
    return {"policy": "chat-rag-4.balanced-recall.e5-small-614241f",
            "embedding": "intfloat/multilingual-e5-small@614241f622f53c4eeff9890bdc4f31cfecc418b3",
            "minScore": 0.78, "relativeMargin": 0.08, "topK": 5,
            "rerankerEnabled": False, "experimentalFacets": False}


def disabled_rules(refs):
    return {"policy": "disabled", "action": "DISABLED", "threshold": None, "perRun": [],
            "excludedRunIds": [], "remainingRunIds": list(dict.fromkeys(ref["runId"] for ref in refs)),
            "completeAggregation": False}


def citation(document, index):
    return {"citationId": f"S{index}", "documentId": document["documentId"],
            "recordId": document["recordId"], "subjectRunId": document.get("runId"),
            "recordRunVersionId": document.get("offlineRunVersionId"),
            "attribution": document["attribution"], "quote": document["text"][:2000],
            "score": document.get("score"), "decision": document.get("decision"),
            "createdAt": document.get("createdAt"), "sourceNoteSha256": document["sourceNoteSha256"],
            "sourceRecordSha256": document["sourceRecordSha256"]}


class DecisionRecordEngine:
    def __init__(self, execution_mode=None, *, encoder=None, index_dir=None, synthetic=None,
                 record_policy=policy.RECORD_POLICY_VERSION, encoder_spec=None,
                 model_dir_env="AGENT_V3_RAG_MODEL_DIR", min_score=0.78, relative_margin=0.08, profile=None,
                 index_factory=None):
        self.execution_mode = normalize_mode(execution_mode)
        # Only the cost_exclusion count uses this version.
        self.record_policy = policy.require_version(record_policy)
        # Retrieval settings; the defaults are the PR #36 E5 profile. The thresholds belong to
        # the encoder because similarity scales differ between embedding models.
        self.encoder_spec, self.model_dir_env = encoder_spec, model_dir_env
        self.min_score, self.relative_margin = min_score, relative_margin
        self.profile = profile or retrieval_profile()
        self.index_factory = index_factory  # None keeps the PR #36 bundle cache (LocalIndex)
        self.encoder = encoder
        self.index_dir = Path(index_dir) if index_dir is not None else None
        self.synthetic = (os.getenv("AGENT_V3_RAG_SYNTHETIC", "false").lower() == "true"
                          if synthetic is None else synthetic)

    def execute(self, action, question, refs, records, threshold=None):
        # Check the request-frozen capability before reading notes, building an index or calling either strategy.
        require_action(self.execution_mode, action)
        refs = [dict(ref) for ref in refs]
        run_ids = list(dict.fromkeys(ref["runId"] for ref in refs))
        if not refs or len({(ref["runId"], ref["runVersionId"]) for ref in refs}) != len(refs):
            raise DomainError("INVALID_DECISION_SCOPE")
        corpus = live_corpus(records, refs, synthetic=self.synthetic)
        rules = disabled_rules(refs)
        retrieval = {"strategy": "DISABLED", "returned": 0,
                     "totalInScope": len(corpus.scoped_documents(run_ids)), "similarityIsProbability": False}
        if action == "cost_exclusion":
            parsed = policy.parse_request(question)
            if (parsed is None or not parsed["exclude"] or not policy.mentions_cost(question)
                    or not policy.valid_threshold(threshold) or threshold != parsed["threshold"]):
                raise DomainError("INVALID_RECORD_RULE_REQUEST")
            summaries = [policy.summarize(records, run_id, self.record_policy) for run_id in run_ids]
            excluded = [summary["runId"] for summary in summaries if summary["count"] >= threshold]
            rules = {"policy": self.record_policy, "action": "APPLY_EXISTING_COST_RULE",
                     "threshold": threshold, "aggregationScope": "ALL_RECORDS_FOR_RUN_ID_INCLUDING_HISTORY",
                     "perRun": [{key: summary[key] for key in ("runId", "count", "status", "mixed")} |
                                {"costRejectionRecordIds": sorted({entry["recordId"] for entry in summary["entries"]
                                    if entry["reason"] == "COST" and entry["decision"] == "REJECT"})}
                                for summary in summaries],
                     "excludedRunIds": excluded, "remainingRunIds": [r for r in run_ids if r not in excluded],
                     "completeAggregation": True}
            eligible = {(summary["runId"], entry["recordId"]) for summary in summaries for entry in summary["entries"]
                        if entry["reason"] == "COST" and entry["decision"] == "REJECT"}
            documents = [doc for doc in corpus.documents if doc["attribution"] == "PER_RUN"
                         and (doc["runId"], doc["recordId"]) in eligible][:5]
            citations = [citation(doc, index) for index, doc in enumerate(documents, 1)]
            answer = (f"비용 반려 {threshold}건 이상 기준으로 제외 {len(excluded)}개, 유지 {len(run_ids)-len(excluded)}개입니다. "
                      "건수는 검색 상위 결과가 아닌 전체 저장 기록의 고유 ID로 계산했습니다.")
            status = "ANSWERED"
            retrieval.update(strategy="COMPLETE_RULE_AGGREGATION_WITH_PROOF", returned=len(citations))
            counts = {"rules": 1, "rag": 0}
        else:
            # Optional heavy dependencies and model files are touched only after the RAG gate succeeds.
            from .embedding import E5_SMALL, LocalEncoder
            from .service import RagService
            if self.encoder is None:
                model_dir = os.getenv(self.model_dir_env, "")
                if not model_dir:
                    raise DomainError("DECISION_RAG_NOT_CONFIGURED")
                self.encoder = LocalEncoder(Path(model_dir), spec=self.encoder_spec or E5_SMALL)
            directory = self.index_dir or Path(os.getenv("AGENT_V3_RAG_CACHE_DIR", ""))
            if self.index_dir is None and not os.getenv("AGENT_V3_RAG_CACHE_DIR"):
                raise DomainError("DECISION_RAG_NOT_CONFIGURED")
            service = RagService(corpus, self.encoder, directory, min_score=self.min_score,
                                 relative_margin=self.relative_margin,
                                 include_rules=False, experimental_facets=False,
                                 **({"index_factory": self.index_factory} if self.index_factory else {}))
            raw = service.ask(question, run_ids, top_k=5, mode="semantic", version_scope="history")
            citations = [{"citationId": row["citationId"], "documentId": row["documentId"],
                          "recordId": row["recordId"], "subjectRunId": row["runId"],
                          "recordRunVersionId": row["offlineRunVersionId"],
                          **{key: row[key] for key in ("attribution", "quote", "score", "decision", "createdAt",
                                                    "sourceNoteSha256", "sourceRecordSha256")}}
                         for row in raw["citations"]]
            answer, status = raw["answer"], raw["status"]
            retrieval = {**raw["retrieval"], "profile": self.profile}
            counts = {"rules": 0, "rag": 1}
        evidence = {"schemaVersion": 1, "kind": "decision_rag", "status": status, "synthetic": self.synthetic,
                    "answer": answer, "scopeRunRefs": refs, "citations": citations, "rules": rules,
                    "retrieval": retrieval, "snapshotFingerprint": digest(records),
                    "limitations": ["판단 메모는 물리 인과나 비용 측정을 대신하지 않습니다.",
                                    "공동·비교 메모를 개별 Run의 반려 사유로 옮기지 않습니다.",
                                    "검색 근거가 없어도 전체 DB에 기록이 없다고 확정하지 않습니다."]}
        remaining = rules["remainingRunIds"]
        return {"candidates": [ref for ref in refs if ref["runId"] in remaining],
                "decisionEvidence": evidence, "rules": rules, "retrieval": retrieval, "callCounts": counts}
