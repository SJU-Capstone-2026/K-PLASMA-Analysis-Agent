"""Artificial selection-flow regressions; scripted providers make no API calls."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from evals.v2_cases import runs
from evals.v2_harness import EvaluationJournal
from kplasma_agent.v3.core.contracts import PlanDraft
from kplasma_agent.v3.core.plan_validation import InvalidPlan, validate_plan
from kplasma_agent.v3.graph import build_v3_graph
from .runtime_helpers import matching_plan_review


QUESTION = "실험 목록에서 내가 두 개를 고른 뒤 이온 플럭스를 비교해줘."
SEARCH_QUESTION = "이온 플럭스가 99999보다 큰 검색 결과에서 내가 두 개를 고른 뒤 플럭스를 비교해줘."


def selection_plan(candidates=None, *, search=False):
    question = SEARCH_QUESTION if search else QUESTION
    steps = [{"id": "choose", "kind": "await_input", "confirmation": "run_selection",
              "depends_on": ["search"] if search else [],
              "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2,
                         "candidates": candidates}},
             {"id": "compare", "kind": "tool", "tool": "compare_runs", "depends_on": ["choose"],
              "inputs": {"runs": {"kind": "result_ref", "step_id": "choose", "field": "selection",
                                  "scope": {"kind": "scalar"}}, "fields": ["ionFlux"]}}]
    if search:
        steps.insert(0, {"id": "search", "kind": "tool", "tool": "reverse_search", "inputs": {
            "constraints": [{"field": "ionFlux", "operator": "gt", "value": {
                "kind": "literal", "value": 99999, "unit": None,
                "source": {"message_key": "question", "quote": "99999보다 큰"}}}]}})
    return PlanDraft.model_validate({"schema_version": 2, "request_mode": "data_request",
        "base_revision": None, "requirements": [{"id": "request", "text": question,
            "sources": [{"message_key": "question", "quote": question}],
            "handled_by": [step["id"] for step in steps]}],
        "steps": [{**step, "requirement_ids": ["request"]} for step in steps]})


@pytest.mark.parametrize("key", ["comparison_entries", "selected_runs", "candidateReferences"])
def test_prior_context_is_not_a_registered_catalog_or_server_bound_candidate_source(key):
    plan = selection_plan({"kind": "context_ref", "key": key})
    with pytest.raises(InvalidPlan, match="registered Run catalog"):
        validate_plan(plan, messages={"question": QUESTION}, context_keys={key})


def test_selection_can_use_the_catalog_or_a_provenanced_search_group():
    for plan in [selection_plan(), selection_plan({"kind": "result_ref", "step_id": "search",
            "field": "candidates", "scope": {"kind": "candidate_group"}}, search=True)]:
        accepted = validate_plan(plan, messages={"question": plan.requirements[0].text}, context_keys=set())
        assert accepted.steps[-1].inputs.runs.step_id == "choose"


class SelectionModels:
    settings = SimpleNamespace(plan_review_enabled=True)

    def __init__(self, *, invalid_first=False, search=False):
        self.invalid_first, self.search, self.calls = invalid_first, search, []

    def submit_plan(self, context):
        self.calls.append(deepcopy(context))
        source = {"kind": "context_ref", "key": "comparison_entries"} if (
            self.invalid_first and len(self.calls) == 1) else None
        if self.search:
            source = {"kind": "result_ref", "step_id": "search", "field": "candidates",
                      "scope": {"kind": "candidate_group"}}
        plan = selection_plan(source, search=self.search).model_dump(mode="json")
        plan["base_revision"] = context["base_revision"]
        return plan, {}

    def review_plan(self, context):
        return matching_plan_review(context)

    def compose(self, context):
        raise AssertionError("A numeric comparison needs no model-written interpretation")


@pytest.mark.parametrize("invalid_first", [False, True])
def test_catalog_picker_interrupts_before_comparison_then_uses_only_confirmed_runs(invalid_first):
    port = EvaluationJournal(runs())
    models = SelectionModels(invalid_first=invalid_first)
    graph = build_v3_graph(models, port, InMemorySaver())
    config = {"configurable": {"thread_id": "synthetic-catalog"}, "recursion_limit": 80}
    state = graph.invoke({"request_id": "synthetic-catalog", "question": QUESTION,
                          "context": {}, "input_history": [], "plan_review_enabled": True}, config)
    assert state["plan_review_enabled"] is True and state["plan_review"]["status"] == "PASS"
    pending = state["__interrupt__"][0].value
    assert pending["type"] == "run_selection" and pending["minSelections"] == pending["maxSelections"] == 2
    assert "sourceExecutionId" not in pending
    assert not port.steps, "The picker must open before any comparison reserves a tool"
    if invalid_first:
        assert state["replans"] == 1
        assert "registered Run catalog" in models.calls[1]["feedback"]
    entries = [{"key": f"R{i}", "ref": {key: row[key] for key in ("runId", "runVersionId")}}
               for i, row in enumerate(port.source[:2], 1)]
    resumed = graph.invoke(Command(resume={"type": "run_selection",
        "comparisonReference": {"entries": entries, "baselineKey": None}}), config)
    snapshot = resumed["answer"]["answerSnapshot"]
    assert snapshot["executionStatus"] == "COMPLETE" and not snapshot["hasIncompleteWork"]
    assert snapshot["budget"]["replans_used"] == int(invalid_first)
    assert len(port.steps) == 1
    saved = next(iter(port.steps.values()))
    assert saved["inputs"]["runs"] == [entry["ref"] for entry in entries]


def test_explicit_search_scope_is_not_replaced_by_the_whole_catalog():
    port = EvaluationJournal(runs())
    graph = build_v3_graph(SelectionModels(search=True), port, InMemorySaver())
    state = graph.invoke({"request_id": "synthetic-empty-search", "question": SEARCH_QUESTION,
                          "context": {}, "input_history": [], "plan_review_enabled": True},
                         {"configurable": {"thread_id": "synthetic-empty-search"}, "recursion_limit": 80})
    assert not state.get("__interrupt__")
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "PARTIAL"
    assert state["answer"]["answerSnapshot"]["hasIncompleteWork"] is True
    assert "비교에 필요한 수의 Run을 확보하지 못했습니다" in state["answer"]["answerSnapshot"]["answer"]
    assert len(port.steps) == 1 and next(iter(port.steps.values()))["result"]["status"] == "empty"
    assert not any(step["stepId"] == "compare" for step in state["answer"]["answerSnapshot"]["stepResults"])
