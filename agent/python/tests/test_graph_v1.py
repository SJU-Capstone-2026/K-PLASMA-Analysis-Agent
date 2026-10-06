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

    def generate(self, instructions, payload, cls):
        self.calls.append(cls.__name__)
        return next(self.responses), {"model": "test"}


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
    model = Model([{"status": "resolved", "operations": [
        {"kind": "forward_lookup", "inputs": {"conditions": conditions}},
    ]}])
    backend = SavedBackend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    result = graph.invoke(
        {"question": f"압력8mTorr 소스300{written_unit} 바이어스600{written_unit} 조회해줘", "request_id": "watts",
         "context": {}, "input_history": []},
        {"configurable": {"thread_id": "watts"}},
    )
    assert "__interrupt__" not in result
    assert result["verified"] and result["result"]["resultStatus"] == "EXACT"
    assert result["result"]["requestedConditions"] == {"pressure": 8, "sourcePower": 300, "biasPower": 600}
    assert result["result"]["usedRunRefs"] == [{"runId": "SYNTHETIC-WATT", "runVersionId": "synthetic-SYNTHETIC-WATT-v1"}]
    assert result["result"]["defaultedUnits"] == []
    assert backend.context_reads == 1 and model.calls == ["Interpretation"]


def test_concept_graph_answers_without_reading_any_run():
    model = Model(
        [
            {
                "status": "resolved",
                "operations": [
                    {"kind": "explain_concept", "inputs": {"topics": ["ionFlux"], "aspect": "definition"}}
                ],
            },
            {
                "status": "answered",
                "sections": [
                    {
                        "topic_refs": ["ionFlux"],
                        "text": "이온 플럭스는 표면에 도달하는 이온의 양을 나타냅니다.",
                    }
                ],
                "limitations": ["일반 지식입니다."],
            },
        ]
    )
    backend = Backend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    result = graph.invoke(
        {"question": "이온 플럭스가 뭐야?", "request_id": "test", "context": {}, "input_history": []},
        {"configurable": {"thread_id": "test"}},
        durability="sync",
    )
    assert result["answer"]["intent"] == "CONCEPT_EXPLANATION"
    assert result["answer"]["usedRunRefs"] == []
    assert result["answer"]["answerSnapshot"]["result"]["resultStatus"] == "CONCEPT_READY"
    assert backend.context_reads == 0


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
    assert model.calls == ["Interpretation"]


def test_text_resume_tells_interpreter_which_missing_field_was_asked():
    class SlotModel:
        def generate(self, instructions, payload, cls):
            conditions = {
                "pressure": {"value": 2, "unit": "mTorr"},
                "sourcePower": {"value": 100, "unit": "W"},
            }
            if payload.get("input_history"):
                assert payload["pending_question"]["fields"] == ["biasPower"]
                assert payload["latest_reply"] == {"text": "0 W"}
                conditions["biasPower"] = {"value": 0, "unit": "W"}
            return {
                "status": "resolved",
                "operations": [{"kind": "forward_lookup", "inputs": {"conditions": conditions}}],
            }, {}

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


def test_unresolved_items_block_execution_even_when_model_says_resolved():
    model = Model(
        [
            {
                "status": "resolved",
                "operations": [
                    {
                        "kind": "compare_runs",
                        "inputs": {
                            "baseline": {"kind": "run_id", "run_id": "RUN-A"},
                            "target": {"kind": "run_id", "run_id": "RUN-B"},
                        },
                    }
                ],
                "unresolved": [
                    {
                        "reason": "multiple_targets",
                        "description": "추가 대상 RUN-C와 RUN-D 중 이번 비교 대상을 선택해 주세요.",
                    }
                ],
            }
        ]
    )
    backend = Backend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    result = graph.invoke(
        {
            "request_id": "multi",
            "question": "RUN-A를 기준으로 RUN-B, RUN-C, RUN-D를 비교해줘",
            "context": {},
            "input_history": [],
        },
        {"configurable": {"thread_id": "multi"}},
    )
    assert "__interrupt__" in result
    assert backend.context_reads == 0
    assert result["pending"]["reason"] == "AMBIGUOUS_INPUT"


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


def test_unordered_pair_requires_baseline_then_accepts_explicit_role():
    model = Model(
        [
            {
                "status": "resolved",
                "operations": [
                    {
                        "kind": "compare_runs",
                        "inputs": {
                            "baseline": {"kind": "run_id", "run_id": "RUN-A"},
                            "target": {"kind": "run_id", "run_id": "RUN-B"},
                        },
                    }
                ],
            }
        ]
    )
    backend = Backend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "roles"}}
    result = graph.invoke(
        {"request_id": "roles", "question": "RUN-A와 RUN-B 비교해줘", "context": {}, "input_history": []},
        config,
    )
    assert result["pending"]["reason"] == "AMBIGUOUS_RUN_ROLES"
    assert backend.context_reads == 0
    result = graph.invoke(Command(resume={"baseline": {"kind": "run_id", "run_id": "RUN-A"}}), config)
    assert result["pending"]["reason"] == "RUN_NOT_FOUND"
    assert backend.context_reads == 1


def test_comparison_followup_preserves_previous_metric_subset():
    from fixtures import run

    baseline, target = run("A"), run("B")
    context = {
        "comparisonContext": {
            "result": {
                "baseline": {"runId": "A", "runVersionId": baseline["runVersionId"]},
                "target": {"runId": "B", "runVersionId": target["runVersionId"]},
                "metrics": [{"metric": "ionFlux"}],
            }
        }
    }

    class Catalog(Backend):
        def context(self, refs=None):
            return {"runs": [baseline, target], "referencedRuns": [], "context": context}

    model = Model(
        [
            {
                "status": "resolved",
                "operations": [
                    {
                        "kind": "compare_runs",
                        "inputs": {
                            "baseline": {"kind": "comparison_baseline"},
                            "target": {"kind": "comparison_target"},
                        },
                    }
                ],
            }
        ]
    )
    graph = build_graph(model, Catalog(), Settings(), InMemorySaver())
    result = graph.invoke(
        {
            "request_id": "followup",
            "question": "아까 비교 다시 보여줘",
            "context": context,
            "input_history": [],
        },
        {"configurable": {"thread_id": "followup"}},
    )
    assert [row["metric"] for row in result["answer"]["answerSnapshot"]["result"]["metrics"]] == ["ionFlux"]


def test_concept_invalid_scope_asks_without_generating_explanation():
    for topics, aspect in [
        (["ionFlux", "meanIonEnergy"], None),
        (["ionFlux", "meanIonEnergy", "pressure"], "definition"),
        (["ionFlux"], "difference"),
        (["ionFlux", "ionFlux"], "relationship"),
    ]:
        model = Model(
            [
                {
                    "status": "resolved",
                    "operations": [
                        {
                            "kind": "explain_concept",
                            "inputs": {
                                "topics": topics,
                                "aspect": aspect,
                            },
                        }
                    ],
                }
            ]
        )
        graph = build_graph(model, Backend(), Settings(), InMemorySaver())
        result = graph.invoke(
            {"request_id": "scope", "question": "개념 설명해줘", "context": {}, "input_history": []},
            {"configurable": {"thread_id": "scope"}},
        )
        assert result["pending"]["reason"] == "AMBIGUOUS_CONCEPT_SCOPE"
        assert model.calls == ["Interpretation"]


def test_invalid_structured_reply_preserves_pending_and_allows_correction():
    model = Model(
        [
            {
                "status": "resolved",
                "operations": [
                    {
                        "kind": "forward_lookup",
                        "inputs": {"conditions": {"pressure": {"value": 10, "unit": "mTorr"},
                                                  "sourcePower": {"value": 300, "unit": "W"}}},
                    }
                ],
            }
        ]
    )
    graph = build_graph(model, Backend(), Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "bad-reply"}}
    result = graph.invoke(
        {"request_id": "bad-reply", "question": "압력10mTorr 소스300W 결과", "context": {}, "input_history": []},
        config,
    )
    previous_id = result["pending"]["id"]
    result = graph.invoke(Command(resume={"conditions": {"biasPower": {"value": "oops"}}}), config)
    assert result["pending"]["id"] != previous_id
    assert result["pending"]["fields"] == ["biasPower"]
    assert len(result["input_history"]) == 1
    result = graph.invoke(Command(resume={"conditions": {"biasPower": {"value": 0, "unit": "W"}}}), config)
    assert result["answer"]["status"] == "NO_DATA"
    assert model.calls == ["Interpretation"]


def test_bare_run_id_answers_the_pending_baseline_question():
    operation = {
        "kind": "compare_runs",
        "inputs": {
            "baseline": {"kind": "run_id", "run_id": "RUN-A"},
            "target": {"kind": "run_id", "run_id": "RUN-B"},
        },
    }
    model = Model(
        [{"status": "resolved", "operations": [operation]}, {"status": "resolved", "operations": [operation]}]
    )
    backend = Backend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "bare-baseline"}}
    graph.invoke(
        {
            "request_id": "bare-baseline",
            "question": "RUN-A와 RUN-B 비교해줘",
            "context": {},
            "input_history": [],
        },
        config,
    )
    result = graph.invoke(Command(resume={"text": "RUN-A"}), config)
    assert result["pending"]["reason"] == "RUN_NOT_FOUND"
    assert backend.context_reads == 1


def test_operation_selection_cannot_clear_ungrounded_numeric_proposal():
    bad = {
        "kind": "forward_lookup",
        "inputs": {
            "conditions": {
                "pressure": {"value": 999},
                "sourcePower": {"value": 300},
                "biasPower": {"value": 100},
            }
        },
    }
    model = Model([{"status": "resolved", "operations": [bad, bad]}])
    backend = Backend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "unsafe-selection"}}
    result = graph.invoke(
        {
            "request_id": "unsafe-selection",
            "question": "압력10 소스300 바이어스100 조회",
            "context": {},
            "input_history": [],
        },
        config,
    )
    assert result["pending"]["reason"] == "OPERATION_SELECTION"
    result = graph.invoke(Command(resume={"operation_index": 0}), config)
    assert "__interrupt__" in result
    assert "answer" not in result
    assert backend.context_reads == 0
