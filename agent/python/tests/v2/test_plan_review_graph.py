from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.python.evals.v2_cases import runs
from agent.python.evals.v2_harness import EvaluationJournal
from kplasma_agent.graphs.v2 import build_v2_graph
from kplasma_agent.v2.plan_review import parse_plan_review, review_result
from .test_plan_review import QUESTION, answers, example_plan


def correct_plan():
    plan = example_plan().model_dump(mode="json")
    value = plan["steps"][0]["inputs"]["constraints"][0]["value"]
    plan["steps"][0]["inputs"]["constraints"] = [{"field": "meanIonEnergy", "operator": "between",
        "value": None, "min": {**value, "value": 150}, "max": {**value, "value": 160}}]
    return plan


def journal():
    source = runs()
    source[0]["metrics"]["meanIonEnergy"] = 155
    return EvaluationJournal(source)


class Models:
    def __init__(self, plans=None, choices=("match",), enabled=True):
        self.plans = plans or [correct_plan()]
        self.choices = choices
        self.settings = SimpleNamespace(plan_review_enabled=enabled)
        self.plan_inputs = []
        self.reviews = []

    def submit_plan(self, context):
        plan = deepcopy(self.plans[min(len(self.plan_inputs), len(self.plans) - 1)])
        self.plan_inputs.append(deepcopy(context))
        plan["base_revision"] = context["base_revision"]
        return plan, {}

    def review_plan(self, context):
        choice = self.choices[min(len(self.reviews), len(self.choices) - 1)]
        self.reviews.append(deepcopy(context))
        if choice == "outage":
            return review_result(context, "UNAVAILABLE", reason="DECISIONS_TIMEOUT").model_dump(mode="json"), None
        result = parse_plan_review({"answers": answers("missing" if choice == "mismatch" else choice, context)}, context).model_dump(mode="json")
        return result, {}

    def compose(self, context):
        raise AssertionError("data-only results must not invoke the writer")


def invoke(models, port=None):
    port = port or journal()
    state = build_v2_graph(models, port, None).invoke({"request_id": "test", "question": QUESTION,
        "context": {}, "input_history": []}, {"recursion_limit": 100})
    return state, port


def test_normal_plan_passes_one_review_then_executes_without_writer():
    state, port = invoke(Models())
    assert [v["kind"] for v in port.models.values()] == ["PLAN_INITIAL", "PLAN_REVIEW"]
    assert state["plan_review"]["status"] == "PASS"
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "COMPLETE"
    assert len(port.steps) == 1 and state.get("replans", 0) == 0


@pytest.mark.parametrize("choice", ["mismatch", "unclear"])
def test_rejected_plan_is_never_executed_and_corrected_plan_is_reviewed(choice):
    models = Models([example_plan().model_dump(mode="json"), correct_plan()], (choice, "match"))
    state, port = invoke(models)
    assert state["replans"] == 1 and len(models.reviews) == 2
    assert list(port.steps) == ["execution-2-search"]
    constraints = next(iter(port.steps.values()))["inputs"]["constraints"]
    assert constraints == [{"metric": "meanIonEnergy", "operator": "between", "min": 150.0, "max": 160.0,
                            "unit": "eV"}]
    assert models.plan_inputs[1]["plan_review_feedback"]["failed_checks"]
    assert models.plan_inputs[1]["previous_plan"]["steps"][0]["inputs"]["constraints"][0]["operator"] == "gt"


def test_semantics_and_code_errors_share_the_two_replan_limit():
    invalid = example_plan().model_dump(mode="json")
    invalid["steps"][0]["inputs"]["constraints"][0]["value"]["unit"] = "unknown-unit"
    models = Models([invalid, example_plan().model_dump(mode="json"), correct_plan()], ("mismatch", "match"))
    state, port = invoke(models)
    assert state["replans"] == 2 and len(models.reviews) == 2
    assert len(port.steps) == 1 and state["answer"]["answerSnapshot"]["executionStatus"] == "COMPLETE"


def test_list_threshold_replans_before_execution_or_user_data_prompt():
    from .test_plan_validation import comparison, derive, draft
    question = "선택한 두 Run의 플럭스를 비교하고 두 Run 모두보다 높은 플럭스의 Run을 찾아줘."
    search = {"id": "search", "kind": "tool", "tool": "reverse_search", "depends_on": ["derive"],
              "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt", "value": {
                  "kind": "result_ref", "step_id": "derive", "field": "value", "scope": {"kind": "scalar"}}}]}}
    good = draft(comparison(), derive(), search).model_dump(mode="json")
    bad = deepcopy(good)
    bad["steps"].pop(1)
    bad["requirements"][0]["handled_by"] = ["compare", "search"]
    bad["steps"][-1]["depends_on"] = ["compare"]
    bad["steps"][-1]["inputs"]["constraints"][0]["value"] = {
        "kind": "result_ref", "step_id": "compare", "field": "ionFlux",
        "scope": {"kind": "context_selection", "key": "selected_runs"},
    }
    port = journal()
    models = Models([bad, good])
    entries = [{"key": f"R{i+1}", "ref": {"runId": run["runId"], "runVersionId": run["runVersionId"]}}
               for i, run in enumerate(port.source[:2])]
    state = build_v2_graph(models, port, None).invoke({"request_id": "test", "question": question,
        "context": {"comparisonReference": {"entries": entries}}, "input_history": []}, {"recursion_limit": 100})
    assert not state.get("__interrupt__") and state["replans"] == 1
    assert "single quantity" in models.plan_inputs[1]["feedback"]
    assert [row["kind"] for row in port.models.values()] == ["PLAN_INITIAL", "REPLAN", "PLAN_REVIEW"]
    assert len(models.reviews) == 1
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "COMPLETE"


@pytest.mark.parametrize("choice", ["mismatch", "unclear", "outage"])
def test_unapproved_or_unavailable_review_never_reserves_a_tool(choice):
    state, port = invoke(Models(choices=(choice,)))
    assert not port.steps
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "FAILED"
    assert state["replans"] == (0 if choice == "outage" else 2)
    assert "확인된 결과를 표시합니다" not in state["answer"]["answerSnapshot"]["answer"]


def test_disabled_review_is_explicitly_skipped_not_reported_as_pass():
    state, port = invoke(Models(enabled=False))
    assert state["plan_review"]["status"] == "SKIPPED"
    assert [v["kind"] for v in port.models.values()] == ["PLAN_INITIAL"]


def test_unknown_saved_review_does_not_retry_or_run_tools():
    class Unknown(EvaluationJournal):
        def reserve_model(self, kind, key):
            if kind == "PLAN_REVIEW":
                return {"attemptId": "unknown", "callAllowed": False, "outcome": None}
            return super().reserve_model(kind, key)

    models = Models()
    state, port = invoke(models, Unknown(runs()))
    assert not port.steps and not models.reviews
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "FAILED"


@pytest.mark.parametrize("tamper", ["verdict", "digest", "revision"])
def test_stored_pass_must_match_checks_and_the_actual_plan(tamper):
    class Tampered(Models):
        def review_plan(self, context):
            data, usage = super().review_plan(context)
            if tamper == "verdict":
                data["checks"][0]["choice"] = "mismatch"
            elif tamper == "digest":
                data["plan_digest"] = "another-plan"
            else:
                data["plan_revision"] += 1
            return data, usage

    state, port = invoke(Tampered())
    assert not port.steps
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "FAILED"


def test_user_selection_reuses_approved_plan_without_another_meaning_review():
    port = journal()
    port.source[1]["metrics"]["meanIonEnergy"] = 156
    plan = correct_plan()
    plan["steps"] += [
        {"id": "choose", "kind": "await_input", "confirmation": "run_selection", "depends_on": ["search"],
         "requirement_ids": ["r"], "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2,
            "candidates": {"kind": "result_ref", "step_id": "search", "field": "candidates", "scope": {"kind": "candidate_group"}}}},
        {"id": "compare", "kind": "tool", "tool": "compare_runs", "depends_on": ["choose"], "requirement_ids": ["r"],
         "inputs": {"fields": ["pressure"], "runs": {"kind": "result_ref", "step_id": "choose", "field": "selection",
                                                  "scope": {"kind": "scalar"}}}},
    ]
    plan["requirements"][0]["handled_by"] = ["search", "choose", "compare"]
    models = Models([plan])
    graph = build_v2_graph(models, port, InMemorySaver())
    config = {"configurable": {"thread_id": "selection"}, "recursion_limit": 100}
    state = graph.invoke({"request_id": "test", "question": QUESTION, "context": {}, "input_history": []}, config)
    assert state.get("__interrupt__") and len(models.reviews) == 1
    entries = [{"key": f"R{i+1}", "ref": {"runId": run["runId"], "runVersionId": run["runVersionId"]}}
               for i, run in enumerate(port.source[:2])]
    state = graph.invoke(Command(resume={"type": "run_selection", "comparisonReference": {
        "entries": entries, "baselineKey": None}}), config)
    assert len(models.reviews) == 1
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "COMPLETE"


def test_targets_supplied_outside_a_planned_confirmation_require_a_new_review():
    question = "선택한 두 Run의 압력을 비교해줘."
    plan = {"schema_version": 1, "request_mode": "data_request", "base_revision": None,
            "requirements": [{"id": "r", "text": question, "handled_by": ["compare"],
                              "sources": [{"message_key": "question", "quote": question}]}],
            "steps": [{"id": "compare", "kind": "tool", "tool": "compare_runs", "requirement_ids": ["r"],
                       "inputs": {"runs": {"kind": "context_ref", "key": "selected_runs"}, "fields": ["pressure"]}}]}
    models = Models([plan])
    port = journal()
    graph = build_v2_graph(models, port, InMemorySaver())
    config = {"configurable": {"thread_id": "unplanned-selection"}, "recursion_limit": 100}
    state = graph.invoke({"request_id": "test", "question": question, "context": {}, "input_history": []}, config)
    assert state.get("__interrupt__") and len(models.reviews) == 1
    entries = [{"key": f"R{i+1}", "ref": {"runId": run["runId"], "runVersionId": run["runVersionId"]}}
               for i, run in enumerate(port.source[:2])]
    state = graph.invoke(Command(resume={"type": "run_selection", "comparisonReference": {
        "entries": entries, "baselineKey": None}}), config)
    assert state["replans"] == 1 and len(models.reviews) == 2
    assert models.reviews[1]["confirmed_context"]["selected_runs"] == [e["ref"] for e in entries]
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "COMPLETE"


def test_replan_receives_and_durably_stores_condition_evidence():
    from .test_condition_review import reply

    class Precise(Models):
        def review_plan(self, context):
            bad = not self.reviews
            self.reviews.append(deepcopy(context))
            response = reply(context, 'filter.search.meanIonEnergy' if bad else None)
            return parse_plan_review(response, context).model_dump(mode='json'), {}

    models = Precise([example_plan().model_dump(mode='json'), correct_plan()])
    state, port = invoke(models)
    issue, = models.plan_inputs[1]['plan_review_feedback']['issues']
    assert issue['condition_id'] == 'filter.search.meanIonEnergy'
    assert issue['issue_type'] == 'value_changed'
    assert issue['sources'][0]['quote'] == QUESTION
    assert issue['plan_values'][0]['value']['value']['value'] == 0
    saved = next(m['outcome']['data'] for m in port.models.values() if m['kind'] == 'PLAN_REVIEW')
    assert next(c['issue'] for c in saved['checks'] if c['issue']) == issue
    assert state['replans'] == 1 and list(port.steps) == ['execution-2-search']


def test_truncated_stored_pass_cannot_open_execution_even_if_internally_consistent():
    class Partial(Models):
        def review_plan(self, context):
            data, usage = super().review_plan(context)
            data['checks'] = data['checks'][:2]
            data['expected_check_names'] = data['expected_check_names'][:2]
            return data, usage

    state, port = invoke(Partial())
    assert not port.steps
    assert state['failure'] == 'PLAN_REVIEW_UNAVAILABLE'
