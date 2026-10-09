from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
import pytest
from kplasma_agent.graphs.v1 import build_graph
from kplasma_agent.config import Settings


class Backend:
    def __init__(self):
        self.context_reads = 0
        self.stages = []

    def context(self, refs=None):
        self.context_reads += 1
        return {"runs": [], "referencedRuns": [], "context": {}}

    def stage(self, value, **kwargs):
        self.stages.append(value)

    def attempt(self, stage):
        pass


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def select_tool(self, instructions, payload):
        self.calls.append("ToolSelection")
        fixture = next(self.responses)["operations"][0]
        return {"name": fixture["kind"], "arguments": fixture["inputs"], "call_id": "test-call"}, {
            "model": "test",
            "responseItems": [],
        }


@pytest.mark.parametrize("unit", ["와트", "W"])
@pytest.mark.parametrize("written_unit", ["와트", "왓트", "왛트", "오ㅏ트"])
def test_forward_lookup_with_watt_names_matches_the_same_saved_run(unit, written_unit):
    from fixtures import run

    saved_run = run("SYNTHETIC-WATT", pressure=8, source=300, bias=600)

    class SavedBackend(Backend):
        def context(self, refs=None):
            self.context_reads += 1
            return {"runs": [saved_run], "referencedRuns": [], "context": {}}

    conditions = {
        "pressure": {"value": 8, "unit": "mTorr"},
        "sourcePower": {"value": 300, "unit": unit},
        "biasPower": {"value": 600, "unit": unit},
    }
    model = Model(
        [
            {
                "status": "resolved",
                "operations": [
                    {"kind": "forward_lookup", "inputs": {"conditions": conditions}},
                ],
            }
        ]
    )
    backend = SavedBackend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    result = graph.invoke(
        {
            "question": f"압력8mTorr 소스300{written_unit} 바이어스600{written_unit} 조회해줘",
            "request_id": "watts",
            "context": {},
            "input_history": [],
        },
        {"configurable": {"thread_id": "watts"}},
    )
    assert "__interrupt__" not in result
    assert result["verified"] and result["result"]["resultStatus"] == "EXACT"
    assert result["result"]["requestedConditions"] == {"pressure": 8, "sourcePower": 300, "biasPower": 600}
    assert result["result"]["usedRunRefs"] == [
        {"runId": "SYNTHETIC-WATT", "runVersionId": "synthetic-SYNTHETIC-WATT-v1"}
    ]
    assert result["result"]["defaultedUnits"] == []
    assert backend.context_reads == 1 and model.calls == ["ToolSelection"]


def test_missing_forward_slot_interrupts_and_structured_resume_skips_llm():
    model = Model(
        [
            {
                "status": "resolved",
                "operations": [
                    {
                        "kind": "forward_lookup",
                        "inputs": {
                            "conditions": {
                                "pressure": {"value": 10, "unit": "mTorr"},
                                "sourcePower": {"value": 300, "unit": "W"},
                            }
                        },
                    }
                ],
            }
        ]
    )
    backend = Backend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "missing"}}
    result = graph.invoke(
        {
            "question": "압력10 mTorr 소스300 W 조회",
            "request_id": "missing",
            "context": {},
            "input_history": [],
        },
        config,
        durability="sync",
    )
    assert "__interrupt__" in result
    assert "바이어스" in result["pending"]["message"]
    result = graph.invoke(
        Command(resume={"conditions": {"biasPower": {"value": 100, "unit": "W"}}}), config, durability="sync"
    )
    assert result["answer"]["status"] == "NO_DATA"
    assert model.calls == ["ToolSelection"]


def test_text_resume_tells_interpreter_which_missing_field_was_asked():
    class SlotModel:
        def select_tool(self, instructions, payload):
            conditions = {
                "pressure": {"value": 2, "unit": "mTorr"},
                "sourcePower": {"value": 100, "unit": "W"},
            }
            if payload.get("input_history"):
                assert payload["pending_question"]["fields"] == ["biasPower"]
                assert payload["latest_reply"] == {"text": "0 W"}
                conditions["biasPower"] = {"value": 0, "unit": "W"}
            return {"name": "forward_lookup", "arguments": {"conditions": conditions}, "call_id": "slot"}, {}

    graph = build_graph(SlotModel(), Backend(), Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "text-slot"}}
    graph.invoke(
        {
            "question": "압력 2 mTorr 소스 100 W 결과",
            "request_id": "text-slot",
            "context": {},
            "input_history": [],
        },
        config,
    )
    result = graph.invoke(Command(resume={"text": "0 W"}), config)
    assert result["answer"]["status"] == "NO_DATA"


def test_versionless_id_uses_unique_captured_version_and_asks_on_ambiguity():
    from kplasma_agent.graphs.v1 import _resolve

    old = {"runId": "A", "runVersionId": "old"}
    latest = {"runId": "A", "runVersionId": "new"}
    manifest = {"runs": [latest], "referencedRuns": [old]}
    selector = {"kind": "run_id", "run_id": "A"}
    assert _resolve(selector, manifest, {"activeRun": old}) == old
    assert _resolve(selector, manifest, {"activeRun": old, "selectedRunRef": latest}) is None
    assert _resolve(selector, manifest, {}) == latest


def test_excluded_runs_are_evidence_inventory_but_never_candidate_choices():
    from fixtures import run

    usable = run("A")
    excluded = run("B")
    excluded["qualityStatus"] = "UNVERIFIED"

    class Catalog(Backend):
        def context(self, refs=None):
            return {"runs": [usable, excluded], "referencedRuns": [], "context": {}}

    model = Model(
        [
            {
                "status": "resolved",
                "operations": [
                    {
                        "kind": "forward_lookup",
                        "inputs": {
                            "conditions": {
                                "pressure": {"value": 10, "unit": "mTorr"},
                                "sourcePower": {"value": 300, "unit": "W"},
                                "biasPower": {"value": 100, "unit": "W"},
                            }
                        },
                    }
                ],
            }
        ]
    )
    graph = build_graph(model, Catalog(), Settings(), InMemorySaver())
    result = graph.invoke(
        {
            "question": "압력10mTorr 소스300W 바이어스100W 결과",
            "request_id": "exclusions",
            "context": {},
            "input_history": [],
        },
        {"configurable": {"thread_id": "exclusions"}},
    )["answer"]
    assert {r["runId"] for r in result["usedRunRefs"]} == {"A", "B"}
    assert [r["runId"] for r in result["candidates"]] == ["A"]


def test_invalid_structured_reply_preserves_pending_and_allows_correction():
    model = Model(
        [
            {
                "status": "resolved",
                "operations": [
                    {
                        "kind": "forward_lookup",
                        "inputs": {
                            "conditions": {
                                "pressure": {"value": 10, "unit": "mTorr"},
                                "sourcePower": {"value": 300, "unit": "W"},
                            }
                        },
                    }
                ],
            }
        ]
    )
    graph = build_graph(model, Backend(), Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "bad-reply"}}
    result = graph.invoke(
        {
            "request_id": "bad-reply",
            "question": "압력10mTorr 소스300W 결과",
            "context": {},
            "input_history": [],
        },
        config,
    )
    previous_id = result["pending"]["id"]
    result = graph.invoke(Command(resume={"conditions": {"biasPower": {"value": "oops"}}}), config)
    assert result["pending"]["id"] != previous_id
    assert result["pending"]["fields"] == ["biasPower"]
    assert len(result["input_history"]) == 1
    result = graph.invoke(Command(resume={"conditions": {"biasPower": {"value": 0, "unit": "W"}}}), config)
    assert result["answer"]["status"] == "NO_DATA"
    assert model.calls == ["ToolSelection"]
