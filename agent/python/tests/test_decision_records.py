"""Parity with prototype v12.3.1 record-reuse.js (P-record-reuse-01..06) and memory-request parsing."""

import math
from copy import deepcopy

import pytest
from kplasma_agent.domain import DomainError
from kplasma_agent.domain.decision_records import (
    classify,
    evidence,
    filter_runs,
    has_numeric_condition,
    mentions_candidate_group,
    mentions_cost,
    parse_request,
    summarize,
    valid_threshold,
)


def exp(record_id, *candidates, overall="", question="Flux 500 이상 후보 검토", demo=False):
    record = {
        "version": 2,
        "reviewId": record_id,
        "id": record_id,
        "decision": "ADOPT",
        "question": question,
        "overallComment": overall,
        "createdAt": "2026-09-20T00:00:00Z",
        "candidates": [
            {"runId": run_id, "runVersionId": f"{run_id}-v1", "decision": decision, "note": note,
             "conditions": {"pressure": 6}}
            for run_id, decision, note in candidates
        ],
    }
    if demo:
        record["isDemo"] = True
    return record


def rev(record_id, run_id, decision, comment, query="실제 출력 검토"):
    return {
        "reviewId": record_id,
        "targetRunId": run_id,
        "targetRunRef": {"runId": run_id, "runVersionId": f"{run_id}-v2"},
        "decision": decision,
        "comment": comment,
        "queryText": query,
        "createdAt": "2026-09-21T00:00:00Z",
        "runSnapshots": [{"runId": run_id, "conditions": {"pressure": 8}}],
    }


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        (None, "MISSING"),
        ("", "MISSING"),
        (" \t\n", "MISSING"),
        ("﻿", "MISSING"),  # JavaScript trim() removes the BOM; Python strip() does not.
        ("비용이 높아 예산 초과", "COST"),
        ("예산 초과", "COST"),
        ("원가 부담이 큼", "COST"),
        ("비용 문제가 없음. 성능 때문에 반려", "NO_COST"),
        ("가격 적정", "NO_COST"),
        ("비용과는 무관", "NO_COST"),
        ("비용이 높지만 성능이 우수", "UNCLEAR"),
        ("비용 문제는 해결됨", "UNCLEAR"),
        ("비용 때문인지 확인 필요", "UNCLEAR"),
        ("비용 부담?", "UNCLEAR"),
        ("균일도 미달", "OTHER"),
        ("성능 때문에 반려", "OTHER"),
        ("검토 완료", "UNCLEAR"),
        ("비용\n높음", "UNCLEAR"),
        ("비용 높음", "UNCLEAR"),  # JavaScript `.` stops at line separators.
        ("비용\u0085높음", "COST"),  # but not at NEL.
    ],
)
def test_classify_matches_prototype_order(note, expected):
    assert classify(note) == expected


def test_only_explicit_per_run_cost_rejection_counts_and_adoption_conflict_is_kept():
    records = [
        exp("EXP-1", ("A", "ADOPT", "목표 충족"), ("B", "REJECT", "비용이 높아 예산 초과"), ("C", "REJECT", ""),
            overall="비용이 높음"),
        exp("EXP-2", ("B", "ADOPT", "이번에는 채택")),
    ]
    b, c = summarize(records, "B"), summarize(records, "C")
    assert (b["count"], b["status"], b["mixed"]) == (1, "비용 반려 1건", True)
    # A shared comment cannot be attributed when the record has several candidates.
    assert (c["count"], c["status"], c["entries"][0]["note"]) == (0, "반려 사유 미기록", "")
    assert summarize(records, "A")["status"] == "사유 확인 필요"
    assert summarize(records, "Z") == {"runId": "Z", "count": 0, "status": "관련 기록 없음", "entries": [], "mixed": False}


def test_negation_ambiguity_and_other_reasons_are_not_cost_evidence():
    statuses = {
        note: summarize([exp("E", ("A", "ADOPT", "ok"), ("B", "REJECT", note))], "B")
        for note in ["비용 문제 없음", "비용이 높지만 해결 가능", "성능 때문에 반려"]
    }
    assert [(s["count"], s["status"]) for s in statuses.values()] == [
        (0, "비용 문제 없음 기록"), (0, "사유 확인 필요"), (0, "비용 반려 근거 없음")
    ]


def test_single_candidate_shared_comment_and_review_records_are_attributed():
    records = [
        exp("EXP-1", ("A", "REJECT", ""), overall="비용 검토 시연 · 비용이 높아 예산 초과", demo=True),
        rev("REV-1", "A", "REJECT", "비용 과다"),
    ]
    entries = evidence(records, "A")
    assert [(e["recordId"], e["reason"], e["runVersionId"], e["demo"]) for e in entries] == [
        ("EXP-1", "COST", "A-v1", True), ("REV-1", "COST", "A-v2", False)
    ]
    assert entries[1]["conditions"] == {"pressure": 8}
    assert entries[1]["question"] == "실제 출력 검토"
    assert summarize(records, "A")["status"] == "비용 반려 2건"


def test_review_comparison_runs_are_not_evidence():
    record = {**rev("REV-1", "A", "REJECT", "비용 과다"), "comparedRunIds": ["B"]}
    assert evidence([record], "B") == []


def test_another_run_mention_cannot_become_evidence():
    records = [
        exp("E1", ("A", "ADOPT", ""), ("B", "REJECT", "RUN-P04-S500-B0600보다 비용이 높음")),
        exp("E2", ("RUN-P04-S500-B0600", "REJECT", "RUN-P04-S500-B0600 비용 초과")),
    ]
    assert evidence(records, "B")[0]["reason"] == "UNCLEAR"
    assert evidence(records, "RUN-P04-S500-B0600")[0]["reason"] == "COST"


def test_rejections_are_counted_per_distinct_record():
    records = [exp("E1", ("A", "REJECT", "비용 초과")), exp("E1", ("A", "REJECT", "비용 초과")),
               exp("E2", ("A", "REJECT", "예산 초과"))]
    assert summarize(records, "A")["count"] == 2


def test_javascript_truthiness_for_fallback_fields():
    record = exp("E1", ("A", "REJECT", "비용 초과"), question="")
    record["queryText"] = "이전 질문"
    record["runSnapshots"] = [{"runId": "A", "conditions": {"pressure": 9}}]
    record["candidates"][0]["conditions"] = {}
    entry = evidence([record], "A")[0]
    # An empty object is truthy in JavaScript, so the snapshot is not used.
    assert (entry["question"], entry["conditions"]) == ("이전 질문", {})


def test_exclusion_threshold_order_and_undo_leave_records_untouched():
    records = [
        exp("E1", ("A", "REJECT", "비용 초과")),
        exp("E2", ("A", "REJECT", "예산 초과")),
        exp("E3", ("B", "REJECT", "비용이 높음")),
    ]
    original = deepcopy(records)
    one = filter_runs(records, ["C", "A", "B", "A"])
    assert [s["runId"] for s in one["remaining"]] == ["C"]
    assert [s["runId"] for s in one["excluded"]] == ["A", "B"]
    two = filter_runs(records, ["C", "A", "B"], 2)
    assert ([s["runId"] for s in two["remaining"]], [s["runId"] for s in two["excluded"]]) == (["C", "B"], ["A"])
    undo = filter_runs(records, ["C", "A", "B"], math.inf)
    assert ([s["runId"] for s in undo["remaining"]], undo["excluded"]) == (["C", "A", "B"], [])
    assert filter_runs(records, []) == {"remaining": [], "excluded": []}
    assert records == original


@pytest.mark.parametrize("threshold", [0, -1, 1.5, True, "2", math.nan, -math.inf, None])
def test_invalid_thresholds_are_rejected(threshold):
    assert not valid_threshold(threshold)
    with pytest.raises(DomainError) as error:
        filter_runs([], ["A"], threshold)
    assert error.value.code == "INVALID_THRESHOLD"


def test_valid_thresholds():
    assert all(valid_threshold(value) for value in (1, 2, 2.0, 10**400))
    assert not valid_threshold(math.inf)  # Undo only; never a user-supplied threshold.


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("이 후보들 중 비용 반려 1건 이상 제외해줘", {"exclude": True, "threshold": 1}),
        ("비용 반려가 2건 이상인 후보 빼줘", {"exclude": True, "threshold": 2}),
        ("비용 반려 +3 건 이상 제외", {"exclude": True, "threshold": 3}),
        ("비용 반려 1.0건 이상 제외", {"exclude": True, "threshold": 1}),
        ("비용 반려 1.5건 이상 제외", {"exclude": True, "threshold": 1.5}),
        ("비용 반려 0건 이상 제외", {"exclude": True, "threshold": 0}),
        ("비용 반려가 많은 후보 제외해줘", {"exclude": True, "threshold": None}),
        ("반려가 많은 기록 보여줘", {"exclude": False, "threshold": 1}),
        ("이 후보들의 과거 기록 보여줘", {"exclude": False, "threshold": 1}),
        ("이 Run이 이전에 왜 그런 이유로 빠졌어?", {"exclude": False, "threshold": 1}),
        ("성능 때문에 반려된 후보 제외해줘", {"exclude": True, "threshold": 1}),
        ("Flux가 500 이상인 후보를 찾되, 비용 때문에 반려된 건 제외해줘", {"exclude": True, "threshold": 1}),
        ("두 번 이상 반려된 후보 제외", {"exclude": True, "threshold": 1}),
        ("이온 플럭스 높은 후보 찾아줘", None),
        ("이전\n이유", None),
    ],
)
def test_parse_request(text, expected):
    assert parse_request(text) == expected


def test_parse_request_overflowing_threshold_is_invalid():
    parsed = parse_request("비용 반려 " + "9" * 400 + "건 이상 제외")
    assert parsed["threshold"] == math.inf and not valid_threshold(parsed["threshold"])


def test_request_detectors():
    assert mentions_cost("원가 때문에 반려된 건 빼줘") and not mentions_cost("성능 때문에 반려된 건 빼줘")
    for text in ["Flux가 500 이상", "FLUX 5", "압력 6", "소스 전력 400", "source power 300", "바이어스는 0"]:
        assert has_numeric_condition(text), text
    # JavaScript /i without `u` does not fold non-ASCII letters such as U+017F into "s".
    for text in ["플럭스 높은 순", "Run 3개", "ſource 300"]:
        assert not has_numeric_condition(text), text
    assert mentions_candidate_group("이 후보들 중") and mentions_candidate_group("후보군")
    assert not mentions_candidate_group("후보 하나")
