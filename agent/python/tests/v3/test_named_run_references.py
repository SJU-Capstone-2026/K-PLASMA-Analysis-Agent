"""Name-only questions use exact server-attested references; no live models or data."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from kplasma_agent.v3.core.bindings import BlockedInput, resolve_inputs
from kplasma_agent.v3.core.contracts import DecisionRecordStep
from kplasma_agent.v3.graph import _binding_context, build_v3_graph
from kplasma_agent.v3.named_runs import named_run_context
from kplasma_agent.v3.runtime import normalize_mode
from v3.runtime_helpers import matching_plan_review


NAME = "RUN-SYNTHETIC-A"
OTHER = "RUN-SYNTHETIC-OTHER"
REF = {"runId": NAME, "runVersionId": str(UUID(int=17))}
OTHER_REF = {"runId": OTHER, "runVersionId": str(UUID(int=18))}
QUESTION = NAME + " 의 과거 판단기록좀 보여줘"
MODE = normalize_mode({"rulesEnabled": True, "ragEnabled": True})


def context(*refs, spelling=None):
    return {"namedRunReferences": list(refs), "namedRunBindings": [
        {"name": ref["runId"], "ref": ref, "source": {
            "message_key": "question", "quote": spelling or ref["runId"]}}
        for ref in refs], "unresolvedRunNames": []}


def record_step(key="named:" + NAME, question=QUESTION):
    return DecisionRecordStep.model_validate({"id": "records", "kind": "tool", "tool": "decision_records",
        "requirement_ids": ["r"], "inputs": {"action": "search", "query": question,
            "source": {"message_key": "question", "quote": question},
            "runs": {"kind": "context_ref", "key": key}, "threshold": None}})


def test_names_are_available_without_attached_selection_and_do_not_replace_old_scope():
    previous = {"key": "R1", "ref": OTHER_REF}
    raw = {**context(REF), "activeRun": OTHER_REF,
           "comparisonReference": {"entries": [previous]},
           "v2ConfirmedInputs": {"named:" + NAME: OTHER_REF, "named_runs": [OTHER_REF]}}
    bound = _binding_context(raw, QUESTION)
    assert bound["selected_runs"] == [OTHER_REF]
    assert bound["activeRun"] == OTHER_REF
    assert bound["named:" + NAME] == REF
    assert bound["named_runs"] == [REF]
    assert bound["comparison_entries"] == [previous, {"key": "named:" + NAME, "ref": REF}]
    assert resolve_inputs(record_step(), bound, {})["runs"] == [REF]


def test_multiple_named_runs_can_be_read_as_a_group_or_one_exact_subset():
    question = f"{NAME}, {OTHER} 기록을 확인하고 {NAME}의 원문을 보여줘"
    bound = _binding_context(context(REF, OTHER_REF), question)
    assert resolve_inputs(record_step("named_runs", question), bound, {})["runs"] == [REF, OTHER_REF]
    assert resolve_inputs(record_step(question=question), bound, {})["runs"] == [REF]
    assert bound["selected_runs"] == []


def test_typed_case_and_punctuation_preserve_the_original_source_and_canonical_name():
    typed = NAME.lower()
    question = f"`{typed}`의 판단 기록 보여줘."
    values = named_run_context(context(REF, spelling=typed), question)
    assert values["named:" + NAME] == REF
    assert values["named_run_bindings"][0]["source"]["quote"] == typed


@pytest.mark.parametrize("mutation", ["other_ref", "wrong_name", "wrong_quote", "missing_binding"])
def test_unattested_or_mismatched_name_bindings_are_rejected(mutation):
    raw = deepcopy(context(REF))
    if mutation == "other_ref":
        raw["namedRunBindings"][0]["ref"] = OTHER_REF
    elif mutation == "wrong_name":
        raw["namedRunBindings"][0]["name"] = OTHER
    elif mutation == "wrong_quote":
        raw["namedRunBindings"][0]["source"]["quote"] = "not in the question"
    else:
        raw["namedRunBindings"] = []
    with pytest.raises(ValueError, match="INVALID_NAMED_RUN_CONTEXT"):
        named_run_context(raw, QUESTION)


def test_merely_adding_an_alias_does_not_authorize_an_unattested_run():
    with pytest.raises(BlockedInput):
        resolve_inputs(record_step(), {"named:" + NAME: REF}, {})


class NoCalls:
    execution_mode = MODE
    settings = SimpleNamespace(plan_review_enabled=True)
    def __getattr__(self, name):
        raise AssertionError("Unknown name must not invoke " + name)


@pytest.mark.parametrize("raw", [
    {"unresolvedRunNames": [NAME], "activeRun": OTHER_REF},
    {**context(REF), "unresolvedRunNames": [OTHER]},
])
def test_unknown_or_ambiguous_name_gets_specific_guidance_without_any_model_or_tool(raw):
    graph = build_v3_graph(NoCalls(), SimpleNamespace(progress=None), InMemorySaver())
    state = graph.invoke({"request_id": "unknown", "question": QUESTION,
        "context": raw, "input_history": [], "execution_mode": MODE, "plan_review_enabled": True},
        {"configurable": {"thread_id": "unknown"}})
    answer = state["answer"]["answerSnapshot"]
    assert "등록된 실험과 버전으로 확정하지 못했습니다" in answer["answer"]
    assert "첨부해 주세요" in answer["answer"]
    assert answer["stepResults"] == []
    assert answer["budget"]["model_requests_used"] == 0
    assert answer["budget"]["tool_invocations_used"] == 0
    assert answer["executionStatus"] == "FAILED"


def test_exact_user_question_runs_real_record_engine_after_name_binding(tmp_path, monkeypatch):
    from kplasma_agent.v3.decision_rag import runtime
    np = pytest.importorskip("numpy")
    class Encoder:
        metadata = {"model": "ARTIFICIAL_NAME_BINDING_TEST", "dimension": 3, "local": True}
        def encode(self, texts, *, kind="query"):
            return np.asarray([[1, 0, 0] for _ in texts], dtype=np.float32).reshape((-1, 3))
    engine = runtime.DecisionRecordEngine(MODE, encoder=Encoder(), index_dir=tmp_path, synthetic=True)
    monkeypatch.setattr(runtime, "DecisionRecordEngine", lambda mode: engine)
    class Models:
        execution_mode = MODE
        settings = SimpleNamespace(plan_review_enabled=True)
        def submit_plan(self, payload):
            assert "named:" + NAME in payload["context_keys"]
            assert payload["named_run_bindings"][0]["name"] == NAME
            assert payload["named_run_bindings"][0]["ref"] == REF
            return {"schema_version": 2, "request_mode": "data_request", "base_revision": None,
                "requirements": [{"id": "r", "text": QUESTION,
                    "sources": [{"message_key": "question", "quote": QUESTION}], "handled_by": ["records"]}],
                "steps": [record_step().model_dump(mode="json")]}, {}
        def review_plan(self, payload):
            assert payload["confirmed_context"]["selected_runs"] == []
            assert payload["confirmed_context"]["named:" + NAME] == REF
            return matching_plan_review(payload)
    class Port:
        progress = None
        def __init__(self): self.calls = []
        def reserve_model(self, kind, key): return {"attemptId": key, "callAllowed": True, "outcome": None}
        def complete_model(self, key, data): return {"outcome": data}
        def accept_plan(self, draft): return {"plan": draft.model_dump(mode="json"), "revision": 1}
        def start_step(self, revision, identifier, inputs):
            self.calls.append(inputs)
            return {"executionId": "named-records", "callAllowed": True}
        def decision_records(self, execution):
            return [{"reviewId": key, "targetRunId": ref["runId"], "targetRunRef": ref,
                "comparedRunRefs": [], "decision": "REJECT", "comment": "인공 비용 검토 메모",
                "createdAt": "2026-01-01T00:00:00Z", "runSnapshots": [ref]}
                for key, ref in (("own", REF), ("unrelated", OTHER_REF))]
        def save_result(self, result): return {"result": result.model_dump(mode="json")}
    port = Port()
    state = build_v3_graph(Models(), port, InMemorySaver()).invoke({"request_id": "named-record",
        "question": QUESTION, "context": context(REF), "input_history": [],
        "execution_mode": MODE, "plan_review_enabled": True},
        {"configurable": {"thread_id": "named-record"}, "recursion_limit": 80})
    answer = state["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == "COMPLETE"
    assert state["plan_review_enabled"] is True
    assert port.calls[0]["runs"] == [REF]
    assert answer["budget"]["replans_used"] == 0
    assert answer["budget"]["tool_invocations_used"] == 1
    assert [c["recordId"] for c in answer["decisionEvidence"][0]["citations"]] == ["own"]
