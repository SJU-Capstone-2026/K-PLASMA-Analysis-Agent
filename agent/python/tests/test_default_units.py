"""Graph unit defaults use artificial data and preserve original numeric magnitudes."""

from copy import deepcopy
import pytest
from langgraph.types import Command
from test_search_units import invoke, operation, SearchBackend
from test_graph_v1 import Model


@pytest.mark.parametrize("claimed", [None, "eV"])
def test_omitted_range_unit_executes_and_records_the_applied_default(claimed):
    inputs = {
        "constraints": [
            {"metric": "meanIonEnergy", "operator": "between", "min": 30, "max": 40, "unit": claimed}
        ],
        "goals": [{"metric": "ionFlux", "direction": "maximize"}],
    }
    _, _, state = invoke(
        Model([operation("reverse_search", inputs)]),
        SearchBackend(),
        "Ion Flux 높게, Mean Ion Energy 30–40에 가깝게 후보를 찾아줘",
    )
    assert "__interrupt__" not in state
    snapshot = state["answer"]["answerSnapshot"]
    assert snapshot["unitAssumptions"] == [{"metric": "meanIonEnergy", "unit": "eV"}]
    assert snapshot["resolvedInputs"]["constraints"][0]["min"] == 30
    assert len(snapshot["result"]["candidates"]) == 1


def test_flux_default_keeps_scaled_flux_and_power_filters_in_reverse_search():
    inputs = {
        "constraints": [
            {"metric": "ionFlux", "operator": "gte", "value": 5},
            {"metric": "sourcePower", "operator": "gte", "value": 300},
        ]
    }
    _, _, state = invoke(
        Model([operation("reverse_search", inputs)]),
        SearchBackend(),
        "이온플러스 5 이상, 소스 300 이상 후보 찾아줘",
    )
    assert "__interrupt__" not in state
    snapshot = state["answer"]["answerSnapshot"]
    assert snapshot["unitAssumptions"] == [
        {"metric": "ionFlux", "unit": "10¹⁸ m⁻²s⁻¹"},
        {"metric": "sourcePower", "unit": "W"},
    ]
    assert snapshot["result"]["constraints"][0]["value"] == 5
    assert len(snapshot["result"]["candidates"]) == 1


def test_missing_forward_condition_resume_keeps_unit_notice_and_zero():
    inputs = {"conditions": {"pressure": {"value": 8}, "sourcePower": {"value": 300}}}
    graph, config, state = invoke(
        Model([operation("forward_lookup", inputs)]), SearchBackend(), "압력8 소스300 결과 조회"
    )
    assert state["pending"]["reason"] == "MISSING_CONDITIONS"
    state = graph.invoke(Command(resume={"conditions": {"biasPower": {"value": 0}}}), config)
    snapshot = state["answer"]["answerSnapshot"]
    assert snapshot["result"]["resultStatus"] == "EXACT"
    assert snapshot["unitAssumptions"] == [
        {"metric": "pressure", "unit": "mTorr"},
        {"metric": "sourcePower", "unit": "W"},
        {"metric": "biasPower", "unit": "W"},
    ]
    assert snapshot["result"]["requestedConditions"]["biasPower"] == 0


def test_explicit_converted_units_take_priority_and_have_no_default_notice():
    inputs = {
        "conditions": {
            "pressure": {"value": 0.008, "unit": "Torr"},
            "sourcePower": {"value": 300, "unit": "W"},
            "biasPower": {"value": 0, "unit": "W"},
        }
    }
    _, _, state = invoke(
        Model([operation("forward_lookup", inputs)]),
        SearchBackend(),
        "압력 .008 Torr 소스 300 W 바이어스 0 W 조회",
    )
    assert state["answer"]["answerSnapshot"]["unitAssumptions"] == []
    assert state["result"]["resultStatus"] == "EXACT"


@pytest.mark.parametrize("written,claimed", [("", "keV"), (" psi", None), (" 쥴", None), (" W", "W")])
def test_default_policy_never_swallows_unknown_or_incompatible_explicit_units(written, claimed):
    inputs = {"constraints": [{"metric": "meanIonEnergy", "operator": "lte", "value": 40, "unit": claimed}]}
    backend = SearchBackend()
    _, _, state = invoke(
        Model([operation("reverse_search", inputs)]),
        backend,
        f"평균 이온 에너지 40{written} 이하 후보 찾아줘",
    )
    assert "__interrupt__" in state and backend.context_reads == 0


def test_default_notice_is_part_of_the_saved_answer_not_live_interpretation():
    inputs = {
        "conditions": {"pressure": {"value": 8}, "sourcePower": {"value": 300}, "biasPower": {"value": 0}}
    }
    _, _, state = invoke(
        Model([operation("forward_lookup", inputs)]), SearchBackend(), "압력 8 소스 300 바이어스 0 조회"
    )
    saved = deepcopy(state["answer"]["answerSnapshot"])
    state["inputs"]["conditions"]["pressure"]["unit"] = "Torr"
    assert saved["unitAssumptions"][0] == {"metric": "pressure", "unit": "mTorr"}
    assert saved["resolvedInputs"]["conditions"]["pressure"]["unit"] == "mTorr"


def test_unit_defaults_never_authorize_a_condition_absent_from_the_question():
    backend = SearchBackend()
    inputs = {
        "constraints": [
            {"metric": "meanIonEnergy", "operator": "lte", "value": 40},
            {"metric": "pressure", "operator": "gte", "value": 8},
        ]
    }
    _, _, state = invoke(
        Model([operation("reverse_search", inputs)]), backend, "평균 이온 에너지 40 이하 후보 찾아줘"
    )
    assert "__interrupt__" in state and backend.context_reads == 0


def test_rejected_numeric_proposal_cannot_become_trusted_context_on_retry():
    backend = SearchBackend()
    inputs = {
        "constraints": [
            {"metric": "meanIonEnergy", "operator": "lte", "value": 40},
            {"metric": "pressure", "operator": "gte", "value": 8},
        ]
    }
    graph, config, state = invoke(
        Model([operation("reverse_search", inputs)] * 2), backend, "평균 이온 에너지 40 이하 후보 찾아줘"
    )
    assert "__interrupt__" in state
    state = graph.invoke(Command(resume={"text": "같은 조건으로"}), config)
    assert "__interrupt__" in state and backend.context_reads == 0
