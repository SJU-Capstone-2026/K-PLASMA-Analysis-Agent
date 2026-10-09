import pytest
from pydantic import ValidationError

from kplasma_agent.contracts import Interpretation, normalize_interpretation


def envelope(kind, inputs):
    return {"status": "resolved", "operations": [{"kind": kind, "inputs": inputs}]}


@pytest.mark.parametrize(
    "kind,inputs",
    [
        ("forward_lookup", {"conditions": {"pressure": {"value": 10, "unit": "mTorr"}}}),
        (
            "reverse_search",
            {
                "constraints": [{"metric": "pressure", "operator": "lt", "value": 10}],
                "goals": [{"metric": "ionFlux", "direction": "maximize"}],
            },
        ),
        ("compare_runs", {"baseline": {"kind": "reference_run"}, "target": {"kind": "selected_run"}}),
        (
            "explain_change",
            {"baseline": {"kind": "comparison_baseline"}, "target": {"kind": "comparison_target"}},
        ),
        ("explain_concept", {"topics": ["ionFlux"], "aspect": "definition"}),
    ],
)
def test_five_operations_and_missing_slots_validate(kind, inputs):
    assert normalize_interpretation(envelope(kind, inputs)).operations[0].kind == kind


@pytest.mark.parametrize("value", [True, "10", float("nan"), float("inf")])
def test_non_finite_and_coercible_numbers_rejected(value):
    with pytest.raises(ValidationError):
        Interpretation.model_validate(
            envelope("forward_lookup", {"conditions": {"pressure": {"value": value}}})
        )


def test_unknown_fields_and_run_payload_rejected():
    with pytest.raises(ValidationError):
        Interpretation.model_validate(
            envelope("compare_runs", {"baseline": {"kind": "reference_run", "run_id": "A"}})
        )
    with pytest.raises(ValidationError):
        Interpretation.model_validate(
            {**envelope("explain_concept", {"topics": ["plasma"]}), "source_phrases": {}}
        )


@pytest.mark.parametrize(
    "inputs",
    [
        {"constraints": [{"metric": "pressure", "operator": "between", "min": 11, "max": 1}]},
        {"constraints": [{"metric": "pressure", "operator": "lt", "value": 10, "min": 3}]},
        {"goals": [{"metric": "ionFlux", "direction": "maximize", "min": 3}]},
    ],
)
def test_ambiguous_bounds_rejected(inputs):
    with pytest.raises(ValidationError):
        Interpretation.model_validate(envelope("reverse_search", inputs))


@pytest.mark.parametrize("metrics", [[], ["ionFlux", "ionFlux"], ["electronDensity"]])
def test_invalid_compare_metric_selection_rejected(metrics):
    with pytest.raises(ValidationError):
        Interpretation.model_validate(envelope("compare_runs", {"metrics": metrics}))


@pytest.mark.parametrize(
    "kind,rule", [("forward_lookup", "energy_slightly_higher"), ("reverse_search", "selected_run_conditions")]
)
def test_context_rule_enum_is_scoped_to_its_operation(kind, rule):
    with pytest.raises(ValidationError):
        Interpretation.model_validate(envelope(kind, {"context_rules": [rule]}))
