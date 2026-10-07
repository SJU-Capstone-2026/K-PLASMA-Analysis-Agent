from collections import Counter

from .cases import CASES
from .judge import judge


def test_suite_has_141_distinct_synthetic_questions_and_required_balance():
    assert len(CASES) == len({case.question for case in CASES}) == 141
    assert dict(Counter(case.category for case in CASES)) == {
        "forward": 30,
        "reverse": 46,
        "compare": 25,
        "change": 20,
        "concept": 20,
    }


def test_intended_answers_match_their_explicit_mandatory_contracts():
    failures = []
    for case in CASES:
        response = {"name": case.kind, "call_id": "test", "arguments": case.expected_inputs}
        result = judge(case, response)
        if not result["passed"]:
            failures.append((case.id, result))
    assert not failures, failures


def test_wrong_kind_or_numeric_slot_cannot_pass_by_asking_any_question():
    case = CASES[0]
    assert not judge(case, {"name": "forward_lookup", "call_id": "test", "arguments": {}})["passed"]
    swapped = {
        "name": "forward_lookup",
        "call_id": "test",
        "arguments": {
            "conditions": {
                "pressure": {"value": 100, "unit": "mTorr"},
                "sourcePower": {"value": 300, "unit": "W"},
                "biasPower": {"value": 10, "unit": "W"},
            }
        },
    }
    assert not judge(case, swapped)["passed"]
    assert judge(case, swapped)["groundingError"] == "UNGROUNDED_NUMBER"


def test_context_policy_rejected_by_execution_guard_is_not_counted_as_dispatch():
    case = next(case for case in CASES if case.id == "reverse-37")
    response = {
        "name": "reverse_search",
        "call_id": "test",
        "arguments": {"context_rules": ["selected_run_conditions", "energy_slightly_higher"]},
    }
    result = judge(case, response)
    assert not result["passed"]
    assert not result["criticalWrongDispatch"]


def test_unknown_unit_requires_input_even_if_model_says_resolved():
    from dataclasses import replace

    case = replace(
        CASES[0],
        question="압력 10 Pa 소스 300 W 바이어스 100 W 결과 조회",
        expected_inputs={
            "conditions": {
                "pressure": {"value": 10, "unit": "Pa"},
                "sourcePower": {"value": 300, "unit": "W"},
                "biasPower": {"value": 100, "unit": "W"},
            }
        },
        clarification=True,
    )
    response = {"name": "forward_lookup", "call_id": "test", "arguments": case.expected_inputs}
    assert judge(case, response)["passed"]


def test_comparison_never_infers_references_from_raw_run_names():
    case = next(case for case in CASES if case.id == "compare-25")
    response = {"name": "compare_runs", "call_id": "test", "arguments": {}}
    assert judge(case, response)["passed"]
    assert not judge(case, response)["criticalWrongDispatch"]
