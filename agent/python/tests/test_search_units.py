"""Unit spelling and clarification contracts, using artificial Run values only."""

from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from fixtures import run
from kplasma_agent.config import Settings
from kplasma_agent.domain import DomainError, lookup_forward, search_reverse
from kplasma_agent.domain.grounding import validate_grounding
from kplasma_agent.graphs.v1 import build_graph
from kplasma_agent.metric_registry import normalize_value
from test_graph_v1 import Backend, Model


class SearchBackend(Backend):
    def context(self, refs=None, **kwargs):
        self.context_reads += 1
        return {
            "runs": [run("SYNTHETIC-UNITS", energy=35, flux=7, pressure=8, source=300, bias=0)],
            "referencedRuns": [], "context": {},
        }


def operation(kind, inputs):
    return {"status": "resolved", "operations": [{"kind": kind, "inputs": inputs}]}


def invoke(model, backend, question):
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "search-units"}}
    state = graph.invoke(
        {"question": question, "request_id": "search-units", "context": {}, "input_history": []},
        config,
    )
    return graph, config, state


@pytest.mark.parametrize("metric", ["meanIonEnergy", "iedWidth"])
@pytest.mark.parametrize("unit", ["e볼트", "전자볼트", "전자 볼트", "electron volt", "electronvolts", "EV"])
def test_energy_unit_words_normalize_without_changing_magnitude(metric, unit):
    assert normalize_value(metric, 35, unit) == 35


@pytest.mark.parametrize("written", ["e볼트", "전자볼트", "전자 볼트", "electronvolts"])
@pytest.mark.parametrize("returned", ["eV", "e볼트"])
def test_reverse_energy_unit_words_match_symbol_results(written, returned):
    rule = {"metric": "meanIonEnergy", "operator": "between", "min": 30, "max": 40, "unit": returned}
    inputs = {"constraints": [rule], "goals": [{"metric": "ionFlux", "direction": "maximize"}]}
    backend = SearchBackend()
    _, _, state = invoke(
        Model([operation("reverse_search", inputs)]), backend,
        f"Ion Flux는 높게, Mean Ion Energy는 30–40 {written}에 가깝게 후보를 찾아줘",
    )
    expected = search_reverse(
        {**inputs, "constraints": [{**rule, "unit": "eV"}]}, backend.context()["runs"],
    )
    assert "__interrupt__" not in state
    assert state["verified"] and state["result"] == expected


@pytest.mark.parametrize("claimed_unit", [None, "eV"])
@pytest.mark.parametrize("section", ["constraints", "goals"])
def test_reverse_numeric_range_without_unit_asks_even_when_model_guesses(claimed_unit, section):
    range_rule = {"metric": "meanIonEnergy", "min": 30, "max": 40}
    if claimed_unit:
        range_rule["unit"] = claimed_unit
    range_rule.update({"operator": "between"} if section == "constraints" else {"direction": "target_range"})
    inputs = {section: [range_rule]}
    inputs.setdefault("goals", []).append({"metric": "ionFlux", "direction": "maximize"})
    question = "Ion Flux는 높게, Mean Ion Energy는 30–40에 가깝게 후보를 찾아줘"
    if section == "goals":
        question += ", 범위 밖도 허용"
    backend = SearchBackend()
    _, _, state = invoke(Model([operation("reverse_search", inputs)]), backend, question)
    assert "__interrupt__" in state
    assert state["pending"]["reason"] == "MISSING_UNIT"
    assert "평균 이온 에너지" in state["pending"]["message"]
    assert backend.context_reads == 0


@pytest.mark.parametrize("metric", ["pressure", "sourcePower", "biasPower"])
@pytest.mark.parametrize("guess", [False, True])
def test_forward_numeric_conditions_require_explicit_units_including_zero(metric, guess):
    quantities = {"pressure": (8, "mTorr"), "sourcePower": (300, "W"), "biasPower": (0, "W")}
    conditions = {key: {"value": value, "unit": unit} for key, (value, unit) in quantities.items()}
    if not guess:
        del conditions[metric]["unit"]
    labels = {"pressure": "압력", "sourcePower": "소스", "biasPower": "바이어스"}
    question = " ".join(
        f"{labels[key]} {value}{'' if key == metric else unit}" for key, (value, unit) in quantities.items()
    ) + " 조회"
    backend = SearchBackend()
    _, _, state = invoke(Model([operation("forward_lookup", {"conditions": conditions})]), backend, question)
    assert "__interrupt__" in state
    assert state["pending"]["reason"] == "MISSING_UNIT"
    assert state["pending"]["fields"] == [metric]
    assert backend.context_reads == 0


def test_unit_only_reply_resumes_reverse_range_without_losing_flux_sort():
    rule = {"metric": "meanIonEnergy", "operator": "between", "min": 30, "max": 40}
    inputs = {"constraints": [rule], "goals": [{"metric": "ionFlux", "direction": "maximize"}]}
    completed = deepcopy(inputs)
    completed["constraints"][0]["unit"] = "eV"
    backend = SearchBackend()
    graph, config, state = invoke(
        Model([operation("reverse_search", inputs), operation("reverse_search", completed)]), backend,
        "Ion Flux는 높게, Mean Ion Energy는 30–40에 가깝게 후보를 찾아줘",
    )
    assert "__interrupt__" in state
    state = graph.invoke(Command(resume={"text": "e볼트"}), config)
    assert "__interrupt__" not in state
    assert state["verified"] and len(state["result"]["candidates"]) == 1
    assert state["result"]["constraints"][0]["unit"] == "eV"
    assert state["result"]["goals"][0]["direction"] == "maximize"


def test_multiple_missing_units_are_answered_one_at_a_time_without_losing_values():
    conditions = {"pressure": {"value": 8}, "sourcePower": {"value": 300}, "biasPower": {"value": 0}}
    responses = [operation("forward_lookup", {"conditions": deepcopy(conditions)})]
    for metric, unit in (("pressure", "mTorr"), ("sourcePower", "W"), ("biasPower", "W")):
        conditions[metric]["unit"] = unit
        responses.append(operation("forward_lookup", {"conditions": deepcopy(conditions)}))
    backend = SearchBackend()
    graph, config, state = invoke(Model(responses), backend, "압력 8 소스 300 바이어스 0 조회")
    for metric, reply in (("pressure", "밀리토르"), ("sourcePower", "왓트"), ("biasPower", "와트")):
        assert state["pending"]["reason"] == "MISSING_UNIT"
        assert state["pending"]["fields"] == [metric]
        assert backend.context_reads == 0
        state = graph.invoke(Command(resume={"text": reply}), config)
    assert "__interrupt__" not in state
    assert state["result"]["resultStatus"] == "EXACT"
    assert state["result"]["requestedConditions"] == {"pressure": 8, "sourcePower": 300, "biasPower": 0}


def test_high_low_sorting_needs_no_unit_or_clarification():
    inputs = {"goals": [{"metric": "ionFlux", "direction": "maximize"},
                        {"metric": "iedWidth", "direction": "minimize"}]}
    _, _, state = invoke(Model([operation("reverse_search", inputs)]), SearchBackend(), "플럭스 높게 폭 낮게")
    assert "__interrupt__" not in state and state["verified"]


def test_search_tools_reject_missing_numeric_units_before_execution():
    with pytest.raises(DomainError, match="MISSING_UNIT"):
        lookup_forward({"conditions": {"pressure": {"value": 8}, "sourcePower": {"value": 300, "unit": "W"},
                                       "biasPower": {"value": 0, "unit": "W"}}}, [])
    with pytest.raises(DomainError, match="MISSING_UNIT"):
        search_reverse({"constraints": [{"metric": "meanIonEnergy", "operator": "lte", "value": 40}]}, [])


@pytest.mark.parametrize("metric,word,unit", [
    ("pressure", "킬로 토르", "Torr"), ("meanIonEnergy", "킬로 전자 볼트", "eV"),
    ("meanIonEnergy", "킬로 e볼트", "eV"), ("sourcePower", "킬로 와트", "W"),
])
def test_written_unit_prefix_is_never_dropped(metric, word, unit):
    proposed = {"kind": "reverse_search", "inputs": {
        "constraints": [{"metric": metric, "operator": "lte", "value": 30, "unit": unit}],
    }}
    labels = {"pressure": "압력", "meanIonEnergy": "에너지", "sourcePower": "소스"}
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(proposed, f"{labels[metric]} 30 {word} 이하 후보", [])


def test_structured_resume_can_fill_one_of_multiple_missing_units():
    conditions = {"pressure": {"value": 8}, "sourcePower": {"value": 300},
                  "biasPower": {"value": 0, "unit": "W"}}
    graph, config, state = invoke(
        Model([operation("forward_lookup", {"conditions": conditions})]), SearchBackend(),
        "압력8 소스300 바이어스0W 조회",
    )
    assert state["pending"]["fields"] == ["pressure"]
    state = graph.invoke(Command(resume={"conditions": {"pressure": {"value": 8, "unit": "mTorr"}}}), config)
    assert state["pending"]["reason"] == "MISSING_UNIT" and state["pending"]["fields"] == ["sourcePower"]
    state = graph.invoke(Command(resume={"conditions": {"sourcePower": {"value": 300, "unit": "W"}}}), config)
    assert state["result"]["resultStatus"] == "EXACT"


@pytest.mark.parametrize("section", ["constraints", "goals"])
def test_reverse_scalar_conditions_including_flux_and_zero_require_units(section):
    if section == "goals":
        rule = {"metric": "iedWidth", "direction": "target_range", "min": 0, "max": 5}
        question = "IED 폭 0~5 근처 후보, 범위 밖도 허용"
    else:
        rule = {"metric": "ionFlux", "operator": "gte", "value": 5}
        question = "이온 플럭스 5 이상 후보"
    backend = SearchBackend()
    _, _, state = invoke(Model([operation("reverse_search", {section: [rule]})]), backend, question)
    assert state["pending"]["reason"] == "MISSING_UNIT" and backend.context_reads == 0


def test_unit_only_reply_survives_worker_reconstruction():
    from test_worker import Backend as DurableBackend
    from kplasma_agent.worker import run_claim

    class DurableSearchBackend(DurableBackend):
        def context(self, refs=None, **kwargs):
            return SearchBackend().context()

    rule = {"metric": "meanIonEnergy", "operator": "between", "min": 30, "max": 40}
    inputs = {"constraints": [rule], "goals": [{"metric": "ionFlux", "direction": "maximize"}]}
    completed = deepcopy(inputs)
    completed["constraints"][0]["unit"] = "eV"
    model = Model([operation("reverse_search", inputs), operation("reverse_search", completed)])
    backend = DurableSearchBackend()
    claim = {"request": {"requestId": "durable-unit", "question": "플럭스 높게 에너지30~40 근처 후보"},
             "context": {}, "inputEvents": []}
    run_claim(claim, backend, model, Settings())
    assert backend.pending["reason"] == "MISSING_UNIT" and backend.answer is None
    claim["inputEvents"] = [{"input": {"text": "e볼트"}}]
    run_claim(claim, backend, model, Settings())
    assert not backend.errors and backend.answer["status"] == "MATCH"
    assert backend.answer["answerSnapshot"]["resolvedInputs"]["constraints"][0]["min"] == 30
