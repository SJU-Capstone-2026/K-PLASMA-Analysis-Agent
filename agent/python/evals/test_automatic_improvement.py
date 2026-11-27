"""Test first-plan provenance and separation from eventual recovery."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from .automatic_improvement import first_plan_grade, grade_plan, summarize, verify_graph_review


def reference_case(question, steps, selected=(), *, general=False):
    quote = {"message_key": "question", "quote": question}
    plan = {
        "schema_version": 2,
        "request_mode": "general_only" if general else "data_request",
        "base_revision": None,
        "requirements": [{"id": "req", "text": question, "sources": [quote],
                          "handled_by": [step["id"] for step in steps]}],
        "steps": [{**step, "requirement_ids": ["req"]} for step in steps],
    }
    return {"question": question, "selected": list(selected), "referencePlan": plan, "expected": {"general": general}}


def literal(value, unit, quote):
    return {"kind": "literal", "value": value, "unit": unit,
            "source": {"message_key": "question", "quote": quote}}


def ref(step_id, field, kind="scalar", **scope):
    return {"kind": "result_ref", "step_id": step_id, "field": field, "scope": {"kind": kind, **scope}}


def search(step_id, metric, operator, value, *, dependencies=()):
    return {"id": step_id, "kind": "tool", "tool": "reverse_search", "depends_on": list(dependencies),
            "inputs": {"constraints": [{"field": metric, "operator": operator, "value": value}]}}


def compare(step_id, source, fields, *, dependencies=()):
    return {"id": step_id, "kind": "tool", "tool": "compare_runs", "depends_on": list(dependencies),
            "inputs": {"runs": source, "fields": fields}}


@pytest.fixture
def whole_group():
    return reference_case("압력 8 mTorr 이상인 후보 전체의 플럭스를 비교해줘.", [
        search("find", "pressure", "gte", literal(8, "mTorr", "8 mTorr 이상")),
        compare("compare", ref("find", "candidates", "candidate_group"), ["ionFlux"], dependencies=("find",)),
    ], ("ART-A", "ART-B"))


def test_good_plan_ids_and_independent_order_can_change():
    case = reference_case("압력 8 mTorr와 10 mTorr의 후보를 따로 찾아줘.", [
        search("low", "pressure", "eq", literal(8, "mTorr", "8 mTorr")),
        search("high", "pressure", "eq", literal(10, "mTorr", "10 mTorr")),
    ])
    candidate = deepcopy(case["referencePlan"])
    candidate["requirements"][0]["handled_by"] = ["x1", "x2"]
    for new_id, step in zip(["x1", "x2"], candidate["steps"], strict=True):
        step["id"] = new_id
    candidate["steps"].reverse()
    assert grade_plan(case, candidate)["pass"]


def test_same_tools_wrong_comparison_source_is_a_first_plan_failure(whole_group):
    candidate = deepcopy(whole_group["referencePlan"])
    candidate["steps"][1]["inputs"]["runs"] = {"kind": "context_ref", "key": "selected_runs"}
    grade = grade_plan(whole_group, candidate)
    assert not grade["pass"]
    assert {item["check"] for item in grade["failures"]} == {"runs"}


def test_exact_total_candidate_gate_is_rejected(whole_group):
    candidate = deepcopy(whole_group["referencePlan"])
    candidate["steps"][1]["requires"] = [{"step_id": "find", "field": "candidates", "count": 2}]
    grade = grade_plan(whole_group, candidate)
    assert not grade["pass"]
    assert [failure["check"] for failure in grade["failures"]] == ["unexpected_execution_gate"]


def test_literal_number_does_not_satisfy_calculated_threshold():
    case = reference_case("선택한 두 Run의 플럭스 평균보다 높은 후보를 찾아줘.", [
        compare("read", {"kind": "context_ref", "key": "selected_runs"}, ["ionFlux"]),
        {"id": "mean", "kind": "derive", "operation": "mean", "depends_on": ["read"],
         "inputs": {"values": ref("read", "ionFlux", "context_selection", key="selected_runs")}},
        search("find", "ionFlux", "gt", ref("mean", "value"), dependencies=("mean",)),
    ], ("ART-A", "ART-B"))
    candidate = deepcopy(case["referencePlan"])
    candidate["steps"][-1]["inputs"]["constraints"][0]["value"] = literal(
        120, "10¹⁸ m⁻²s⁻¹", case["question"])
    grade = grade_plan(case, candidate)
    assert not grade["pass"]
    assert "referencedFilters" in [entry["check"] for entry in grade["failures"]]


def test_replans_and_final_completion_do_not_change_first_plan_score(whole_group):
    candidate = deepcopy(whole_group["referencePlan"])
    candidate["steps"][1]["inputs"]["runs"] = {"kind": "context_ref", "key": "selected_runs"}
    attempts = [
        {"id": "first", "kind": "PLAN_INITIAL", "outcome": {"data": candidate}},
        {"id": "repair", "kind": "REPLAN", "outcome": {"data": whole_group["referencePlan"]}},
    ]
    grade = first_plan_grade(whole_group, attempts)
    stats = summarize([{
        "steps": 2,
        "firstPlan": grade,
        "grade": {"pass": True, "answerReviewRequired": False},
        "recovery": {"decisionsReplanRecovered": True, "category": "passed_after_decisions_replan",
                     "decisionsCaughtIssue": True},
    }])
    assert grade["attemptId"] == "first"
    assert stats["firstPlanPass"] == 0
    assert stats["finalDeterministicPass"] == stats["wrongFirstPlanThenDecisionsReplanPass"] == 1


def test_review_enabled_in_actual_graph_checkpoint():
    case = reference_case("이온 플럭스의 정의를 설명해줘.", [
        {"id": "explain", "kind": "tool", "tool": "explain_answer", "inputs": {"mode": "concept"}},
    ], general=True)
    assert verify_graph_review(SimpleNamespace(plan_review_enabled=True), [case])
    with pytest.raises(ValueError, match="disabled"):
        verify_graph_review(SimpleNamespace(plan_review_enabled=False), [case])
