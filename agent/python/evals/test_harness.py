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
        status = "unsupported" if case.unsupported else "needs_input" if case.clarification else "resolved"
        response = {
            "status": status,
            "operations": [] if case.unsupported else [{"kind": case.kind, "inputs": case.expected_inputs}],
        }
        if case.clarification:
            response["unresolved"] = [
                {"reason": "MISSING_INPUT", "description": "Clarification required by synthetic case."}
            ]
        result = judge(case, response)
        if not result["passed"]:
            failures.append((case.id, result))
    assert not failures, failures


def test_wrong_kind_or_numeric_slot_cannot_pass_by_asking_any_question():
    case = CASES[0]
    wrong = {
        "status": "needs_input",
        "operations": [{"kind": "forward_lookup", "inputs": {}}],
        "unresolved": [{"reason": "UNKNOWN", "description": "Ask again"}],
    }
    assert not judge(case, wrong)["passed"]
    swapped = {
        "status": "resolved",
        "operations": [
            {
                "kind": "forward_lookup",
                "inputs": {
                    "conditions": {
                        "pressure": {"value": 100, "unit": "mTorr"},
                        "sourcePower": {"value": 300, "unit": "W"},
                        "biasPower": {"value": 10, "unit": "W"},
                    }
                },
            }
        ],
    }
    assert not judge(case, swapped)["passed"]
    assert judge(case, swapped)["groundingError"] == "UNGROUNDED_NUMBER"


def test_context_policy_rejected_by_execution_guard_is_not_counted_as_dispatch():
    case = next(case for case in CASES if case.id == "reverse-37")
    response = {
        "status": "resolved",
        "operations": [
            {
                "kind": "reverse_search",
                "inputs": {"context_rules": ["selected_run_conditions", "energy_slightly_higher"]},
            }
        ],
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
    response = {
        "status": "resolved",
        "operations": [{"kind": "forward_lookup", "inputs": case.expected_inputs}],
    }
    assert judge(case, response)["passed"]


def test_unresolved_subset_needs_scope_confirmation_even_when_model_says_resolved():
    case = next(case for case in CASES if case.id == "compare-25")
    response = {
        "status": "resolved",
        "operations": [
            {
                "kind": "compare_runs",
                "inputs": {
                    "baseline": {"kind": "run_id", "run_id": "RUN-A"},
                    "target": {"kind": "run_id", "run_id": "RUN-B"},
                },
            }
        ],
        "unresolved": [{"reason": "multiple_targets", "description": "RUN-C and RUN-D remain."}],
    }
    assert judge(case, response)["passed"]
    assert not judge(case, response)["criticalWrongDispatch"]
