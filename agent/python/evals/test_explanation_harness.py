import json

from .explanation_cases import EXPLANATION_CASES
from .run_explanations import _attempt
from kplasma_agent.config import Settings


def test_forty_distinct_qualitative_packets_never_contain_measurements_or_ids():
    assert len(EXPLANATION_CASES) == 40
    assert len({json.dumps(case.evidence, sort_keys=True) for case in EXPLANATION_CASES}) == 40

    def no_number(value):
        if type(value) in (int, float):
            return False
        if isinstance(value, list):
            return all(no_number(item) for item in value)
        if isinstance(value, dict):
            return not {"runId", "runVersionId", "baseline", "target", "delta", "percentChange"} & set(
                value
            ) and all(no_number(item) for item in value.values())
        return True

    assert all(no_number(case.evidence) for case in EXPLANATION_CASES)
    assert {
        case.evidence.get("comparisonMode") for case in EXPLANATION_CASES if case.kind == "explain_change"
    } == {
        "single_condition_changed",
        "multiple_conditions_changed",
        "no_condition_changed",
        "conditions_incomplete",
    }


def test_unavailable_or_unchanged_evidence_bypasses_model_and_stays_limited():
    bypasses = [case for case in EXPLANATION_CASES if case.bypass_generation]
    assert len(bypasses) == 3
    for case in bypasses:
        result = _attempt(case, 1, Settings(api_key=""))
        assert result["passed"] and result["limited"]
        assert result["apiCalls"] == 0
        assert result["attempts"] == []
