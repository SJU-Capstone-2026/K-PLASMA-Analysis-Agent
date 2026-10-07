from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from fixtures import run
from kplasma_agent.config import Settings
from kplasma_agent.graphs.v1 import build_graph


class Model:
    def __init__(self, name, args):
        self.name, self.args, self.calls, self.payloads = name, args, [], []

    def select_tool(self, prompt, payload):
        self.calls.append("select")
        self.payloads.append(payload)
        return {"name": self.name, "arguments": self.args, "call_id": "call_synthetic"}, {"responseItems": []}

    def answer(self, prompt, payload, **kwargs):
        self.calls.append("general")
        self.payloads.append(payload)
        return "이온 에너지는 개별 이온의 에너지이며 평균 이온 에너지는 분포의 평균입니다.", {}

    def generate(self, prompt, payload, cls, **kwargs):
        self.calls.append("compare")
        self.payloads.append(payload)
        return {
            "observationIds": [payload["evidence"]["observations"][0]["id"]],
            "interpretations": [],
            "limitations": [],
        }, {}


class Backend:
    def __init__(self):
        self.refs = []

    def stage(self, *args, **kwargs):
        pass

    def attempt(self, *args):
        pass

    def context(self, refs=None, **kwargs):
        assert kwargs.get("references_only")
        self.refs = refs
        return {"runs": [], "referencedRuns": [run("A"), run("B", flux=4)]}


def test_independent_lookup_and_comparison_require_scope_before_any_data_read():
    model = Model("forward_lookup", {"conditions": {"pressure": {"value": 8, "unit": "mTorr"}}})
    backend = Backend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "mixed"}}
    result = graph.invoke(
        {"request_id": "mixed", "question": "압력 8 mTorr 결과를 조회하고 아까 두 실험을 비교해줘", "context": {}}, config
    )
    assert result["pending"]["reason"] == "MIXED_REQUEST"
    assert backend.refs == [] and model.calls == ["select"]
    result = graph.invoke(Command(resume={"text": "먼저 실험 비교를 해줘"}), config)
    assert result["pending"]["reason"] == "MIXED_REQUEST"  # mismatched selection remains blocked
    model.name, model.args = "compare_runs", {}
    result = graph.invoke(Command(resume={"text": "먼저 실험 비교를 해줘"}), config)
    assert result["pending"]["type"] == "run_selection" and backend.refs == []


def test_general_preserves_original_question_and_has_no_experiment_dependency():
    question = "평균 이온 에너지가 뭐야? 이온 에너지랑 다른건가?"
    model, backend = Model("generate_answer", {}), Backend()
    result = build_graph(model, backend, Settings(), InMemorySaver()).invoke(
        {
            "request_id": "general",
            "question": question,
            "context": {"activeRun": {"runId": "old", "runVersionId": "old"}},
        },
        {"configurable": {"thread_id": "general"}},
    )
    snapshot = result["answer"]["answerSnapshot"]
    assert snapshot["schemaVersion"] == 2 and snapshot["usedRunRefs"] == []
    assert snapshot["originalQuestion"] == question and snapshot["answer"] is None
    assert model.payloads[-1]["originalQuestion"] == question
    assert backend.refs == [] and model.calls == ["select", "general"]


def test_unreferenced_comparison_interrupts_then_selection_skips_routing_llm():
    question = "방금거랑 아까 압력 8 mTorr일 때 플럭스 경향 차이 분석해줘"
    model, backend = Model("compare_runs", {"metrics": ["ionFlux"]}), Backend()
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": "compare"}}
    first = graph.invoke(
        {"request_id": "compare", "question": question, "context": {"candidateReferences": [{}] * 150}},
        config,
    )
    assert first["pending"]["type"] == "run_selection" and model.calls == ["select"]
    entries = [
        {
            "key": f"R{i + 1}",
            "ref": {k: r[k] for k in ("runId", "runVersionId")},
            "origin": {
                "kind": "hitl",
                "turnId": None,
                "groupId": None,
                "pendingInputId": first["pending"]["id"],
            },
        }
        for i, r in enumerate([run("A"), run("B")])
    ]
    result = graph.invoke(
        Command(
            resume={
                "type": "run_selection",
                "runKeys": ["R1", "R2"],
                "baselineKey": None,
                "comparisonReference": {"entries": entries, "baselineKey": None},
            }
        ),
        config,
    )
    assert result["verified"] and model.calls == ["select", "compare"]
    assert backend.refs == [e["ref"] for e in entries]
    assert model.payloads[-1]["originalQuestion"] == question


def test_unrecognized_aliases_still_preserve_explicit_baseline_requirement():
    model = Model("compare_runs", {"ref_keys": ["R1", "R2"], "baseline_key": "R1"})
    result = build_graph(model, Backend(), Settings(), InMemorySaver()).invoke(
        {
            "request_id": "unknown-keys",
            "question": "아까 실험을 기준으로 방금 실험을 비교해줘",
            "context": {},
        },
        {"configurable": {"thread_id": "unknown-keys"}},
    )
    assert result["pending"]["type"] == "run_selection"
    assert result["pending"]["baselineRequired"] is True


def test_named_comparison_metric_is_not_silently_replaced():
    from kplasma_agent.domain.grounding import validate_native_comparison_metrics
    from kplasma_agent.domain.common import DomainError
    import pytest

    with pytest.raises(DomainError, match="UNGROUNDED_METRICS"):
        validate_native_comparison_metrics({"metrics": ["ionFlux"]}, "평균 이온 에너지 차이를 알려줘", [])
    assert validate_native_comparison_metrics(
        {"metrics": ["meanIonEnergy"]}, "평균 이온 에너지 차이를 알려줘", []
    )
