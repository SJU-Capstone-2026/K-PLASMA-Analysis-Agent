import pytest

from kplasma_agent.v3.core.bindings import BlockedInput, resolve_inputs
from kplasma_agent.v3.core.composition import collect_search_evidence
from kplasma_agent.v3.core.contracts import DeriveStep, ReverseStep, StepResult


def test_verified_result_with_one_missing_value_blocks_downstream():
    compare = StepResult(executionId="e", stepId="compare", status="partial", outputs={
        "ionFlux": [{"value": 12, "field": "ionFlux", "unit": "10¹⁸ m⁻²s⁻¹"}, None]
    })
    step = DeriveStep.model_validate({
        "id": "max", "kind": "derive", "operation": "max",
        "inputs": {"values": {"kind": "result_ref", "step_id": "compare", "field": "ionFlux",
                              "scope": {"kind": "context_selection", "key": "selected_runs"}}},
        "requires": [{"step_id": "compare", "field": "ionFlux", "count": 2}],
    })
    with pytest.raises(BlockedInput, match="ionFlux"):
        resolve_inputs(step, {"selected_runs": []}, {"compare": compare})


def test_search_binds_the_verified_unrounded_value_and_strict_boundary():
    step = ReverseStep.model_validate({
        "id": "search", "kind": "tool", "tool": "reverse_search",
        "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt", "value": {
            "kind": "result_ref", "step_id": "max", "field": "value", "scope": {"kind": "scalar"},
        }}]},
    })
    derived = StepResult(executionId="e", stepId="max", status="verified", outputs={
        "value": {"value": 18.000001, "field": "ionFlux", "unit": "10¹⁸ m⁻²s⁻¹"}
    })
    inputs = resolve_inputs(step, {}, {"max": derived})
    assert inputs["constraints"][0]["operator"] == "gt"
    assert inputs["constraints"][0]["value"] == 18.000001


def test_numeric_search_range_filters_and_keeps_both_measurements():
    def energy(value):
        return {"kind": "literal", "value": value, "unit": "eV",
                "source": {"message_key": "question", "quote": "150–160 eV"}}

    step = ReverseStep.model_validate({
        "id": "search", "kind": "tool", "tool": "reverse_search",
        "inputs": {"constraints": [], "goals": [
            {"field": "ionFlux", "direction": "maximize"},
            {"field": "meanIonEnergy", "direction": "target_range", "min": energy(150), "max": energy(160)},
        ]},
    })
    inputs = resolve_inputs(step, {}, {})
    assert inputs["constraints"] == [
        {"metric": "meanIonEnergy", "operator": "between", "min": 150, "max": 160, "unit": "eV"},
    ]
    assert inputs["goals"] == [{"metric": "ionFlux", "direction": "maximize"}]
    ref = {"runId": "R1", "runVersionId": "v1"}
    flux_unit = "10¹⁸ m⁻²s⁻¹"
    step_result = StepResult(executionId="e", stepId="search", status="verified", outputs={"toolResult": {
        "kind": "reverse_search",
        "constraints": inputs["constraints"],
        "goals": [{**inputs["goals"][0], "unit": flux_unit}],
        "commonRunRefs": [ref],
        "runsByVersion": {"v1": {**ref, "metrics": {"meanIonEnergy": 155, "ionFlux": 23},
                                 "units": {"meanIonEnergy": "eV", "ionFlux": flux_unit}}},
    }})
    readings = collect_search_evidence([step_result])[0]["candidates"][0]["measurements"]
    assert [(row["metric"], row["value"], row["unit"]) for row in readings] == [
        ("meanIonEnergy", 155, "eV"), ("ionFlux", 23, flux_unit),
    ]
