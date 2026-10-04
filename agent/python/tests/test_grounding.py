import pytest

from kplasma_agent.domain import DomainError
from kplasma_agent.domain.grounding import validate_grounding


def forward(pressure=10, source=300, bias=100, pressure_unit="mTorr"):
    return {
        "kind": "forward_lookup",
        "inputs": {
            "conditions": {
                "pressure": {"value": pressure, "unit": pressure_unit},
                "sourcePower": {"value": source, "unit": "W"},
                "biasPower": {"value": bias, "unit": "W"},
            }
        },
    }


def reverse(operator="between", *, soft=False):
    rule = {"metric": "meanIonEnergy", "min": 30, "max": 40, "unit": "eV"}
    if soft:
        return {"kind": "reverse_search", "inputs": {"goals": [{**rule, "direction": "target_range"}]}}
    return {"kind": "reverse_search", "inputs": {"constraints": [{**rule, "operator": operator}]}}


@pytest.mark.parametrize(
    "question",
    [
        "압력10mTorr 소스300W 바이어스100W 결과 보여줘",
        "압력은 10 mTorr이고 소스 전력은 300 W, 바이어스는 100 W에서 조회",
        "pressure 10 mTorr, source power 300 W, bias power 100 W: results",
        "10 mTorr 압력, 300 W 소스, 100 W 바이어스에서 결과 조회",
    ],
)
def test_common_korean_and_english_numbers_bind_to_their_metric(question):
    assert validate_grounding(forward(), question, [])


@pytest.mark.parametrize(
    "proposed", [forward(pressure=100, bias=10), forward(pressure=11), forward(source=100, bias=300)]
)
def test_numbers_present_elsewhere_do_not_ground_a_swapped_metric(proposed):
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(proposed, "압력10 소스300 바이어스100", [])


def test_unit_conversion_is_not_performed_by_model():
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(forward(), "압력0.01Torr 소스300W 바이어스100W", [])
    assert validate_grounding(
        forward(pressure=0.01, pressure_unit="Torr"), "압력0.01Torr 소스300W 바이어스100W", []
    )
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(forward(pressure=0.01), "압력0.01Torr 소스300W 바이어스100W", [])


@pytest.mark.parametrize(
    "question",
    [
        "에너지30~40eV 범위 Run 찾아줘",
        "mean ion energy between 30 and 40 eV",
        "에너지30에서40eV 범위",
        "에너지30-40eV 범위",
    ],
)
def test_range_endpoints_are_grounded_together(question):
    assert validate_grounding(reverse(), question, [])


def test_hard_soft_and_strict_bounds_cannot_be_silently_changed():
    assert validate_grounding(reverse(soft=True), "에너지30~40eV에 가깝게 찾아줘", [])
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(reverse(), "에너지30~40eV에 가깝게 찾아줘", [])
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(reverse(soft=True), "에너지30~40eV 범위 안에서", [])
    op = {
        "kind": "reverse_search",
        "inputs": {"constraints": [{"metric": "pressure", "operator": "lt", "value": 10}]},
    }
    assert validate_grounding(op, "압력10미만", [])
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(op, "압력10이하", [])


def test_run_id_numbers_never_ground_scalar_claim():
    op = {"kind": "forward_lookup", "inputs": {"conditions": {"pressure": {"value": 10}}}}
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(op, "Run-10과 같은 압력에서 결과 보여줘", [])
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(op, "Run10 결과 보여줘", [])


def test_prior_exact_fields_and_single_missing_slot_reply_are_grounded():
    prior = forward()
    del prior["inputs"]["conditions"]["biasPower"]
    assert validate_grounding(
        forward(),
        "압력10 소스300 조회",
        [{"text": "100 W"}],
        {"status": "needs_input", "operations": [prior]},
    )
    assert validate_grounding(forward(), "계속해줘", [], {"status": "resolved", "operations": [forward()]})


def test_structured_reply_is_bound_to_its_field_and_not_reused_for_another():
    question = "압력10 소스300 조회"
    history = [{"conditions": {"biasPower": {"value": 100, "unit": "W"}}}]
    assert validate_grounding(forward(), question, history)
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(forward(pressure=100), question, history)


def test_latest_explicit_correction_does_not_allow_old_values():
    history = [{"text": "압력은20으로 바꿔"}]
    assert validate_grounding(
        forward(pressure=20),
        "압력10 소스300 바이어스100",
        history,
        {"status": "resolved", "operations": [forward()]},
    )
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(
            forward(),
            "압력10 소스300 바이어스100",
            history,
            {"status": "resolved", "operations": [forward()]},
        )


def test_rejected_prior_guess_cannot_be_laundered_as_context():
    prior = {
        "status": "needs_input",
        "operations": [forward()],
        "unresolved": [{"reason": "UNGROUNDED_NUMBER"}],
    }
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(forward(), "아까 질문 그대로", [], prior)


def test_no_numeric_concept_or_context_policy_passes_without_creating_slots():
    assert validate_grounding(
        {"kind": "explain_concept", "inputs": {"topics": ["ionFlux"]}}, "플럭스 뭐야", []
    )
    assert validate_grounding(
        {"kind": "reverse_search", "inputs": {"context_rules": ["energy_slightly_higher"]}},
        "에너지 좀 높여줘",
        [],
    )


def test_explicit_run_id_and_version_must_be_copied_or_inherited():
    op = {
        "kind": "compare_runs",
        "inputs": {
            "baseline": {"kind": "run_id", "run_id": "RUN-10"},
            "target": {"kind": "run_id", "run_id": "RUN-20"},
        },
    }
    assert validate_grounding(op, "RUN-10 기준 RUN-20 비교해줘", [])
    op["inputs"]["target"]["run_version_id"] = "invented-version"
    with pytest.raises(DomainError, match="UNGROUNDED_RUN_REFERENCE"):
        validate_grounding(op, "RUN-10 기준 RUN-20 비교해줘", [])


def test_explicit_baseline_role_and_goal_direction_cannot_be_reversed():
    swapped = {
        "kind": "compare_runs",
        "inputs": {
            "baseline": {"kind": "run_id", "run_id": "RUN-20"},
            "target": {"kind": "run_id", "run_id": "RUN-10"},
        },
    }
    with pytest.raises(DomainError, match="UNGROUNDED_RUN_REFERENCE"):
        validate_grounding(swapped, "RUN-10을 기준으로 RUN-20과 비교해줘", [])
    wrong_goal = {
        "kind": "reverse_search",
        "inputs": {"goals": [{"metric": "ionFlux", "direction": "minimize"}]},
    }
    with pytest.raises(DomainError, match="UNGROUNDED_GOAL"):
        validate_grounding(wrong_goal, "이온 플럭스가 가장 높은 후보를 찾아줘", [])


def test_ambiguous_latest_numeric_clause_cannot_reuse_stale_accepted_value():
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(
            forward(),
            "압력10 소스300 바이어스100",
            [{"text": "압력은20 아니면30으로"}],
            {"status": "resolved", "operations": [forward()]},
        )


def test_plain_numeric_comparison_cannot_silently_add_causal_explanation():
    operation = {
        "kind": "explain_change",
        "inputs": {
            "baseline": {"kind": "run_id", "run_id": "RUN-A"},
            "target": {"kind": "run_id", "run_id": "RUN-B"},
            "metrics": ["meanIonEnergy"],
        },
    }
    with pytest.raises(DomainError, match="UNGROUNDED_OPERATION"):
        validate_grounding(operation, "RUN-A 기준 RUN-B의 에너지 차이를 수치로 보여줘", [])
    assert validate_grounding(operation, "RUN-A 기준 RUN-B 에너지 차이를 계산하고 물리적으로 해석해줘", [])
    operation["kind"] = "compare_runs"
    with pytest.raises(DomainError, match="UNGROUNDED_OPERATION"):
        validate_grounding(operation, "RUN-A 기준 RUN-B 에너지가 왜 달라졌는지 설명해줘", [])
    assert validate_grounding(operation, "RUN-A 기준 RUN-B 차이만 계산하고 원인 설명은 빼줘", [])


def test_comparison_context_metrics_cannot_silently_expand_or_change_order():
    from kplasma_agent.domain.grounding import validate_comparison_metrics

    inputs = {
        "baseline": {"kind": "comparison_baseline"},
        "target": {"kind": "comparison_target"},
        "metrics": ["ionFlux", "meanIonEnergy"],
    }
    with pytest.raises(DomainError, match="UNGROUNDED_METRICS"):
        validate_comparison_metrics(inputs, "그 비교의 원인을 설명해줘", [], ["ionFlux"])
    with pytest.raises(DomainError, match="UNGROUNDED_METRICS"):
        validate_comparison_metrics(inputs, "그 비교를 다시 보여줘", [], ["meanIonEnergy", "ionFlux"])
    assert validate_comparison_metrics(inputs, "에너지도 비교해줘", [], ["ionFlux"])
    inputs["metrics"] = ["meanIonEnergy"]
    assert validate_comparison_metrics(inputs, "에너지만 비교해줘", [], ["ionFlux"])
    assert validate_comparison_metrics(inputs, "계속해줘", [{"metrics": ["meanIonEnergy"]}], ["ionFlux"])


def test_comparison_all_metrics_explicit_and_original_defaults_remain_allowed():
    from kplasma_agent.domain.grounding import validate_comparison_metrics

    inputs = {
        "baseline": {"kind": "comparison_baseline"},
        "target": {"kind": "comparison_target"},
        "metrics": ["meanIonEnergy", "ionFlux", "iedWidth"],
    }
    assert validate_comparison_metrics(inputs, "모든 지표를 비교해줘", [], ["ionFlux"])
    assert validate_comparison_metrics(inputs, "계속해줘", [], inputs["metrics"])
    inputs["baseline"] = {"kind": "run_id", "run_id": "RUN-A"}
    inputs["target"] = {"kind": "run_id", "run_id": "RUN-B"}
    assert validate_comparison_metrics(inputs, "RUN-A 기준 RUN-B 비교", [], ["ionFlux"])


def test_omitted_explicit_pressure_constraint_cannot_execute_unbounded_search():
    operation = {
        "kind": "reverse_search",
        "inputs": {"constraints": [], "goals": [{"metric": "ionFlux", "direction": "maximize"}]},
    }
    with pytest.raises(DomainError, match="UNGROUNDED_OMISSION"):
        validate_grounding(operation, "압력 10 이하에서 플럭스가 가장 높은 후보 찾아줘", [])
    operation["inputs"]["constraints"] = [{"metric": "pressure", "operator": "lte", "value": 10}]
    assert validate_grounding(operation, "압력 10 이하에서 플럭스가 가장 높은 후보 찾아줘", [])


def test_omitted_explicit_forward_field_and_soft_goal_are_rejected():
    partial = forward()
    del partial["inputs"]["conditions"]["biasPower"]
    with pytest.raises(DomainError, match="UNGROUNDED_OMISSION"):
        validate_grounding(partial, "압력10 소스300 바이어스100 조회", [])
    with pytest.raises(DomainError, match="UNGROUNDED_OMISSION"):
        validate_grounding({"kind": "reverse_search", "inputs": {}}, "에너지30~40eV에 가깝게 찾아줘", [])
    assert validate_grounding(
        {"kind": "explain_concept", "inputs": {"topics": ["pressure"]}},
        "압력이 10일 때 압력이 무슨 뜻인지 설명해줘",
        [],
    )


def test_completeness_respects_latest_correction_and_accepted_prior():
    prior = {
        "kind": "reverse_search",
        "inputs": {"constraints": [{"metric": "pressure", "operator": "lte", "value": 10}]},
    }
    updated = {
        "kind": "reverse_search",
        "inputs": {"constraints": [{"metric": "pressure", "operator": "lte", "value": 20}]},
    }
    assert validate_grounding(
        updated, "압력10이하", [{"text": "압력20이하로 수정"}], {"status": "resolved", "operations": [prior]}
    )
    with pytest.raises(DomainError, match="UNGROUNDED_OMISSION"):
        validate_grounding(
            {"kind": "reverse_search", "inputs": {}},
            "계속",
            [],
            {"status": "resolved", "operations": [prior]},
        )


@pytest.mark.parametrize("bad", ["oops", "100", True, float("nan"), float("inf")])
def test_invalid_structured_history_is_not_numeric_evidence(bad):
    history = [
        {"conditions": {"biasPower": {"value": bad}}},
        {"conditions": {"biasPower": {"value": 100, "unit": "W"}}},
    ]
    assert validate_grounding(forward(), "압력10 소스300 조회", history)
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(forward(), "압력10 소스300 조회", history[:1])


@pytest.mark.parametrize("bad", ["invalid", [10], True])
def test_malformed_structured_history_container_does_not_block_later_correction(bad):
    history = [{"conditions": bad}, {"conditions": {"biasPower": {"value": 100}}}]
    assert validate_grounding(forward(), "압력10 소스300 조회", history)
