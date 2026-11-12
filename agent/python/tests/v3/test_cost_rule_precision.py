"""Artificial policy contrasts and complete-record aggregation; no model/network."""
import json
from pathlib import Path
from uuid import UUID

import pytest

from kplasma_agent.v3.decision_rag import policy


CASES = json.loads((Path(__file__).resolve().parents[4] /
    "backend/src/test/resources/v3-cost-policy-cases.json").read_text(encoding="utf-8"))["cases"]
REF_A = {"runId": "RUN-ART-A", "runVersionId": str(UUID(int=1))}
REF_B = {"runId": "RUN-ART-B", "runVersionId": str(UUID(int=2))}


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_cost_clause_contract_shared_with_java(case):
    assert policy.classify(case["note"]) == case["expected"]


def record(identifier, note, *, decision="REJECT", ref=REF_A):
    return {"reviewId": identifier, "targetRunId": ref["runId"], "targetRunRef": ref,
            "decision": decision, "comment": note}


def test_cost_policy_version_describes_changed_semantics():
    assert policy.RECORD_POLICY_VERSION == "cost-regex-2"


def test_only_distinct_saved_cost_rejections_count_despite_record_keeping_contrasts():
    first = record("ART-COST-1", "비용 초과를 두 번 적었지만 하나의 심사에서 반려했다.")
    older = record("ART-COST-2", "가격이 비싸서 반려했지만 작성 회의는 네 번이었다.",
                   ref={**REF_A, "runVersionId": str(UUID(int=3))})
    records = [first, first, older,
               record("ART-UNCLEAR", "원가 때문인지는 확인이 필요하다."),
               record("ART-RESOLVED", "비용 문제는 해결됐지만 성능 부족으로 반려했다."),
               record("ART-ADOPT", "비용이 높지만 예외로 채택했다.", decision="ADOPT")]
    summary = policy.summarize(records, REF_A["runId"])
    assert summary["count"] == 2
    assert summary["mixed"] is True
    assert {entry["recordId"] for entry in summary["entries"]
            if entry["reason"] == "COST" and entry["decision"] == "REJECT"} == {"ART-COST-1", "ART-COST-2"}
    assert policy.filter_runs(records, [REF_A["runId"], REF_B["runId"]], 2)["excluded"] == [summary]


def test_shared_and_foreign_prose_never_become_individual_cost_counts():
    shared = {"reviewId": "ART-SHARED", "version": 2, "overallComment": "비용이 높아 반려했다.",
              "candidates": [{**ref, "decision": "REJECT", "note": ""} for ref in [REF_A, REF_B]]}
    foreign = record("ART-FOREIGN", REF_B["runId"] + "의 가격이 비싸서 반려했다.")
    individual = {"reviewId": "ART-INDIVIDUAL", "version": 2, "overallComment": "공통 검토",
                  "candidates": [{**REF_A, "decision": "REJECT", "note": "가격이 비싸서 반려했다."},
                                 {**REF_B, "decision": "ADOPT", "note": "비용과 무관하다."}]}
    assert policy.summarize([shared, foreign], REF_A["runId"])["count"] == 0
    entries = policy.evidence([shared, foreign], REF_A["runId"])
    assert entries[0]["reason"] == "MISSING"
    assert entries[1]["reason"] == "UNCLEAR"
    assert policy.summarize([shared, foreign, individual], REF_A["runId"])["count"] == 1
    assert policy.summarize([shared, individual], REF_B["runId"])["count"] == 0


def test_single_candidate_overall_note_keeps_its_original_attribution():
    only = {"reviewId": "ART-ONE", "version": 2, "overallComment": "원가 부담으로 반려했다.",
            "candidates": [{**REF_A, "decision": "REJECT", "note": ""}]}
    before = json.dumps(only, ensure_ascii=False, sort_keys=True)
    assert policy.summarize([only], REF_A["runId"])["count"] == 1
    assert json.dumps(only, ensure_ascii=False, sort_keys=True) == before
