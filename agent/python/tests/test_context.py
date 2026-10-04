import copy

import pytest

from fixtures import run
from kplasma_agent.domain import DomainError, apply_context_rules, lookup_forward, search_reverse


def test_energy_policy_is_computed_from_exact_version_and_consumed():
    inputs = {"context_rules": ["energy_slightly_higher"]}
    source = run("A", energy=20.24)
    before = copy.deepcopy((inputs, source))
    applied = apply_context_rules("reverse_search", inputs, "에너지를 조금 더 높인 후보를 찾아줘", source)
    assert applied["inputs"]["constraints"] == [
        {"metric": "meanIonEnergy", "operator": "between", "min": 25.2, "max": 40.2, "unit": "eV"}
    ]
    assert applied["inputs"]["context_rules"] == []
    assert applied["usedRunRefs"] == [{"runId": "A", "runVersionId": "synthetic-A-v1"}]
    assert applied["appliedRules"][0]["generatedFields"] == ["constraints.0.min", "constraints.0.max"]
    assert (inputs, source) == before
    assert search_reverse(applied["inputs"], [run("B", energy=30)])["resultStatus"] == "MATCH"


def test_flux_policy_is_normalized_once_and_preserves_other_explicit_constraint():
    source = run("A", flux=2e18, width=5)
    source["units"]["ionFlux"] = "m⁻²s⁻¹"
    applied = apply_context_rules(
        "reverse_search",
        {
            "constraints": [{"metric": "pressure", "operator": "lt", "value": 10}],
            "context_rules": ["flux_maintained_and_width_lower"],
        },
        "플럭스는 유지하면서 IED 폭은 좁게 찾아줘",
        source,
    )
    constraints = applied["inputs"]["constraints"]
    assert constraints[0] == {"metric": "pressure", "operator": "lt", "value": 10}
    assert constraints[1] == {
        "metric": "ionFlux",
        "operator": "between",
        "min": 1.9,
        "max": 2.1,
        "unit": "10¹⁸ m⁻²s⁻¹",
    }
    assert constraints[2] == {"metric": "iedWidth", "operator": "lte", "value": 5, "unit": "eV"}


def test_selected_conditions_require_explicit_reference_and_actual_result_intent():
    applied = apply_context_rules(
        "forward_lookup",
        {"context_rules": ["selected_run_conditions"]},
        "선택한 Run의 전체 결과를 보여줘",
        run(),
    )
    assert applied["inputs"]["conditions"] == {
        "pressure": {"value": 10, "unit": "mTorr"},
        "sourcePower": {"value": 300, "unit": "W"},
        "biasPower": {"value": 100, "unit": "W"},
    }
    assert lookup_forward(applied["inputs"], [run()])["resultStatus"] == "EXACT"


@pytest.mark.parametrize(
    "rule,kind,question",
    [
        ("energy_slightly_higher", "reverse_search", "에너지가 비슷한 Run을 찾아줘"),
        ("energy_slightly_higher", "reverse_search", "에너지를 조금 더 높이지 말고 낮춰줘"),
        ("energy_slightly_higher", "reverse_search", "플럭스를 조금 높여줘"),
        ("flux_maintained_and_width_lower", "reverse_search", "플럭스가 비슷한 Run을 찾아줘"),
        ("flux_maintained_and_width_lower", "reverse_search", "플럭스는 유지하면서 폭은 넓혀줘"),
        ("selected_run_conditions", "forward_lookup", "결과를 보여줘"),
        ("selected_run_conditions", "forward_lookup", "선택한 Run의 개념이 뭐야"),
    ],
)
def test_unmatched_ambiguous_or_negated_phrase_never_generates_numbers(rule, kind, question):
    with pytest.raises(DomainError, match="CONTEXT_RULE_NOT_GROUNDED"):
        apply_context_rules(kind, {"context_rules": [rule]}, question, run())


@pytest.mark.parametrize(
    "rule,question",
    [
        ("energy_slightly_higher", "Find runs with slightly higher energy"),
        ("energy_slightly_higher", "Increase the mean ion energy a little"),
        ("flux_maintained_and_width_lower", "Keep ion flux and lower IED width"),
    ],
)
def test_exact_english_continuations_are_supported(rule, question):
    assert apply_context_rules("reverse_search", {"context_rules": [rule]}, question, run())["appliedRules"]


def test_missing_reference_quality_or_values_never_guess():
    with pytest.raises(DomainError, match="CONTEXT_REFERENCE_REQUIRED"):
        apply_context_rules(
            "reverse_search", {"context_rules": ["energy_slightly_higher"]}, "에너지 조금 높여줘"
        )
    source = run()
    source["qualityStatus"] = "UNVERIFIED"
    with pytest.raises(DomainError, match="DATA_NOT_COMPARABLE"):
        apply_context_rules(
            "reverse_search", {"context_rules": ["energy_slightly_higher"]}, "에너지 조금 높여줘", source
        )
    with pytest.raises(DomainError, match="CONTEXT_DATA_UNAVAILABLE"):
        apply_context_rules(
            "reverse_search",
            {"context_rules": ["flux_maintained_and_width_lower"]},
            "플럭스 유지하고 폭 낮춰줘",
            run(width=None),
        )


def test_explicit_conflicts_are_not_overwritten_and_identical_bounds_deduplicate():
    query = {
        "context_rules": ["energy_slightly_higher"],
        "constraints": [{"metric": "meanIonEnergy", "operator": "lte", "value": 10}],
    }
    before = copy.deepcopy(query)
    with pytest.raises(DomainError, match="CONTEXT_RULE_CONFLICT"):
        apply_context_rules("reverse_search", query, "에너지 조금 높여줘", run())
    assert query == before
    query["constraints"] = [{"metric": "meanIonEnergy", "operator": "between", "min": 25, "max": 40}]
    result = apply_context_rules("reverse_search", query, "에너지 조금 높여줘", run())
    assert len(result["inputs"]["constraints"]) == 1
    with pytest.raises(DomainError, match="CONTEXT_RULE_CONFLICT"):
        apply_context_rules(
            "forward_lookup",
            {"conditions": {"pressure": {"value": 20}}, "context_rules": ["selected_run_conditions"]},
            "이 Run 결과 보여줘",
            run(),
        )


def test_zero_is_not_missing_but_overflow_cannot_form_a_policy():
    result = apply_context_rules(
        "reverse_search",
        {"context_rules": ["flux_maintained_and_width_lower"]},
        "플럭스 유지하고 폭 낮춰줘",
        run(flux=0, width=0),
    )
    assert result["inputs"]["constraints"][0]["min"] == 0
    assert result["inputs"]["constraints"][1]["value"] == 0
    with pytest.raises(DomainError, match="NUMERIC_OVERFLOW"):
        apply_context_rules(
            "reverse_search",
            {"context_rules": ["energy_slightly_higher"]},
            "에너지 조금 높여줘",
            run(energy=1e308),
        )


def test_no_rules_does_not_fill_any_missing_numeric_slot():
    result = apply_context_rules(
        "forward_lookup", {"conditions": {"pressure": {"value": 10}}}, "압력 10에서 결과 보여줘", run()
    )
    assert result["inputs"]["conditions"] == {"pressure": {"value": 10}}
    assert result["appliedRules"] == []
    assert result["usedRunRefs"] == []


def test_rule_kind_and_duplicate_policy_conflicts_require_clarification():
    with pytest.raises(DomainError, match="CONTEXT_RULE_CONFLICT"):
        apply_context_rules(
            "forward_lookup", {"context_rules": ["energy_slightly_higher"]}, "에너지 조금 높여줘", run()
        )
    with pytest.raises(DomainError, match="CONTEXT_RULE_CONFLICT"):
        apply_context_rules(
            "reverse_search",
            {"context_rules": ["energy_slightly_higher", "energy_slightly_higher"]},
            "에너지 조금 높여줘",
            run(),
        )


def test_policy_does_not_silently_gain_an_additional_same_metric_ranking_goal():
    with pytest.raises(DomainError, match="CONTEXT_RULE_CONFLICT"):
        apply_context_rules(
            "reverse_search",
            {
                "context_rules": ["flux_maintained_and_width_lower"],
                "goals": [{"metric": "iedWidth", "direction": "minimize"}],
            },
            "플럭스 유지하고 폭 낮춰줘",
            run(),
        )
