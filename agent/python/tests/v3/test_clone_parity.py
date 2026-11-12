"""Compare the independently built graphs with identical scripted model responses."""

import copy
import importlib
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


def builders():
    return [importlib.import_module("kplasma_agent.graphs.v2").build_v2_graph,
            importlib.import_module("kplasma_agent.v3.graph").build_v3_graph]


def normalized(answer):
    value = copy.deepcopy(answer)
    snapshot = value.get("answerSnapshot", value)
    snapshot["implementationId"] = snapshot["graphVersion"] = "normalized"
    snapshot["budget"]["active_elapsed_seconds"] = 0
    return value


def test_concept_answer_and_model_call_sequence_match_v2():
    clone = Path(__file__).resolve().parents[2] / "src/kplasma_agent/v3/graph.py"
    assert clone.is_file(), "the v3 graph must be a separate implementation"
    fixture = importlib.import_module("v2.test_graph")
    outputs, calls = [], []
    for builder in builders():
        journal = fixture.Journal()
        graph = builder(fixture.GeneralModel(), journal, None)
        result = graph.invoke({"request_id": "same-question", "question": "IED가 뭐야?",
                               "context": {}, "input_history": []})
        answer = copy.deepcopy(result["answer"])
        snapshot = answer["answerSnapshot"]
        assert snapshot["implementationId"] in {"v2", "v3"}
        snapshot["implementationId"] = snapshot["graphVersion"] = "normalized"
        snapshot["budget"]["active_elapsed_seconds"] = 0
        outputs.append(answer)
        calls.append(journal.calls)
    assert outputs[0] == outputs[1]
    assert calls == [["PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE"]] * 2


@pytest.mark.parametrize("mode", ["data", "semantic_replan", "review_unavailable"])
def test_data_and_review_recovery_match_v2(mode):
    fixture = importlib.import_module("v2.test_plan_review_graph")
    outputs, calls = [], []
    for builder in builders():
        if mode == "semantic_replan":
            models = fixture.Models([fixture.example_plan().model_dump(mode="json"), fixture.correct_plan()],
                                    ("mismatch", "match"))
        else:
            models = fixture.Models(choices=("outage",) if mode == "review_unavailable" else ("match",))
        port = fixture.journal()
        result = builder(models, port, None).invoke({"request_id": "same-question", "question": fixture.QUESTION,
                                                    "context": {}, "input_history": []}, {"recursion_limit": 100})
        outputs.append(normalized(result["answer"]))
        calls.append([row["kind"] for row in port.models.values()])
    assert outputs[0] == outputs[1]
    assert calls[0] == calls[1]
    snapshot = outputs[1]["answerSnapshot"]
    assert snapshot["executionStatus"] == ("FAILED" if mode == "review_unavailable" else "COMPLETE")
    assert snapshot["budget"]["replans_used"] == (1 if mode == "semantic_replan" else 0)


def test_hitl_checkpoint_and_resume_match_v2():
    fixture = importlib.import_module("v2.test_plan_review_graph")
    outputs, pending_values, calls = [], [], []
    for builder in builders():
        port = fixture.journal()
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
        graph = builder(models, port, saver)
        config = {"configurable": {"thread_id": "same-selection"}, "recursion_limit": 100}
        state = graph.invoke({"request_id": "same-question", "question": fixture.QUESTION,
                              "context": {}, "input_history": []}, config)
        pending_values.append(state["__interrupt__"][0].value)
        assert len(models.reviews) == 1
        entries = [{"key": f"R{i + 1}", "ref": {"runId": run["runId"], "runVersionId": run["runVersionId"]}}
                   for i, run in enumerate(port.source[:2])]
        resumed = builder(models, port, saver).invoke(Command(resume={"type": "run_selection",
            "comparisonReference": {"entries": entries, "baselineKey": None}}), config)
        outputs.append(normalized(resumed["answer"]))
        calls.append([row["kind"] for row in port.models.values()])
        assert len(models.reviews) == 1
    assert pending_values[0] == pending_values[1]
    assert outputs[0] == outputs[1]
    assert calls[0] == calls[1]
    assert outputs[1]["answerSnapshot"]["executionStatus"] == "COMPLETE"


def test_overclaim_answer_rewrite_matches_v2():
    outputs, calls = [], []
    for name in ("v2", "v3"):
        fixture = importlib.import_module(f"{name}.test_streaming_graph")
        port = fixture.DurablePort([fixture.run("A", pressure=8), fixture.run("B", pressure=12)])
        models = fixture.StreamingModels(port, interpretation=True, review_choices=("overclaim", "within_evidence"))
        outputs.append(normalized(fixture.invoke(models, port)))
        calls.append(port.model_reservations)
    assert outputs[0] == outputs[1]
    assert calls[0] == calls[1]
    assert outputs[1]["budget"]["answer_rewrites_used"] == 1
