"""Local CI uses frozen outputs; cross-version imports are initial-copy evidence only."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


SCENARIOS = ("concept", "data", "semantic_replan", "review_unavailable", "hitl", "rewrite")
NAMESPACE = "kplasma_agent.v2_local_llm"


def normalize_identity(answer):
    result = deepcopy(answer)
    snapshot = result.get("answerSnapshot", result)
    snapshot["implementationId"] = snapshot["graphVersion"] = "baseline"
    return result


def run_scenario(version, scenario, monkeypatch):
    namespace = {"v2": "kplasma_agent", "v3": "kplasma_agent.v3", "local": NAMESPACE}[version]
    graph_module = importlib.import_module(namespace + (".graphs.v2" if version == "v2" else ".graph"))
    builder = getattr(graph_module, {"v2": "build_v2_graph", "v3": "build_v3_graph",
                                    "local": "build_v2_local_llm_graph"}[version])
    helpers = {"v2": "v2", "v3": "v3", "local": "v2_local_llm"}[version]
    monkeypatch.setattr(graph_module, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    if scenario == "concept":
        fixture = importlib.import_module(helpers + ".test_graph")
        journal = fixture.Journal()
        result = builder(fixture.GeneralModel(), journal, None).invoke({
            "request_id": "same-question", "question": "IED가 뭐야?", "context": {}, "input_history": []})
        return {"answer": normalize_identity(result["answer"]), "calls": journal.calls}
    if scenario == "rewrite":
        fixture = importlib.import_module(helpers + ".test_streaming_graph")
        port = fixture.DurablePort([fixture.run("A", pressure=8), fixture.run("B", pressure=12)])
        models = fixture.StreamingModels(port, interpretation=True, review_choices=("overclaim", "within_evidence"))
        return {"answer": normalize_identity(fixture.invoke(models, port)), "calls": port.model_reservations}
    fixture = importlib.import_module(helpers + ".test_plan_review_graph")
    if scenario == "semantic_replan":
        models = fixture.Models([fixture.example_plan().model_dump(mode="json"), fixture.correct_plan()],
                                ("mismatch", "match"))
    else:
        models = fixture.Models(choices=("outage",) if scenario == "review_unavailable" else ("match",))
    port = fixture.journal()
    if scenario != "hitl":
        result = builder(models, port, None).invoke({"request_id": "same-question", "question": fixture.QUESTION,
            "context": {}, "input_history": []}, {"recursion_limit": 100})
        return {"answer": normalize_identity(result["answer"]),
                "calls": [row["kind"] for row in port.models.values()]}
    port.source[1]["metrics"]["meanIonEnergy"] = 156
    plan = fixture.correct_plan()
    plan["steps"].extend([
        {"id": "choose", "kind": "await_input", "confirmation": "run_selection", "depends_on": ["search"],
         "requirement_ids": ["r"], "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2,
            "candidates": {"kind": "result_ref", "step_id": "search", "field": "candidates",
                           "scope": {"kind": "candidate_group"}}}},
        {"id": "compare", "kind": "tool", "tool": "compare_runs", "depends_on": ["choose"],
         "requirement_ids": ["r"], "inputs": {"fields": ["pressure"], "runs": {"kind": "result_ref",
            "step_id": "choose", "field": "selection", "scope": {"kind": "scalar"}}}},
    ])
    plan["requirements"][0]["handled_by"] = ["search", "choose", "compare"]
    models = fixture.Models([plan])
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "same-selection"}, "recursion_limit": 100}
    state = builder(models, port, saver).invoke({"request_id": "same-question", "question": fixture.QUESTION,
                                               "context": {}, "input_history": []}, config)
    entries = [{"key": f"R{i + 1}", "ref": {"runId": run["runId"], "runVersionId": run["runVersionId"]}}
               for i, run in enumerate(port.source[:2])]
    resumed = builder(models, port, saver).invoke(Command(resume={"type": "run_selection",
        "comparisonReference": {"entries": entries, "baselineKey": None}}), config)
    return {"answer": normalize_identity(resumed["answer"]), "pending": state["__interrupt__"][0].value,
            "calls": [row["kind"] for row in port.models.values()], "review_calls": len(models.reviews)}


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_local_output_matches_frozen_source_not_live_v2(scenario, monkeypatch):
    expected = json.loads(Path(__file__).with_name("clone-outputs.json").read_text())
    assert run_scenario("local", scenario, monkeypatch) == expected[scenario]


@pytest.mark.initial_clone
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_initial_three_namespaces_match_the_frozen_source(scenario, monkeypatch):
    expected = json.loads(Path(__file__).with_name("clone-outputs.json").read_text())[scenario]
    for version in ("v2", "v3", "local"):
        assert run_scenario(version, scenario, monkeypatch) == expected


@pytest.mark.initial_clone
def test_three_runtimes_share_no_schema_function_or_mutable_registry(monkeypatch):
    gateways = [importlib.import_module(name) for name in (
        "kplasma_agent.v2.model_gateway", "kplasma_agent.v3.core.model_gateway", NAMESPACE + ".core.model_gateway")]
    for name in ("PlanDraft", "submit_plan_tool_schema", "QUESTIONS"):
        values = [getattr(module, name) for module in gateways]
        assert len({id(value) for value in values}) == 3
    originals = [deepcopy(module.QUESTIONS) for module in gateways[:2]]
    monkeypatch.setitem(gateways[2].QUESTIONS, "local_only", ("synthetic mutation", {"x": "x"}))
    assert [module.QUESTIONS for module in gateways[:2]] == originals
    previous = [module.submit_plan_tool_schema() for module in gateways[:2]]
    monkeypatch.setattr(gateways[2], "submit_plan_tool_schema", lambda: {"local_only": True})
    assert [module.submit_plan_tool_schema() for module in gateways[:2]] == previous
