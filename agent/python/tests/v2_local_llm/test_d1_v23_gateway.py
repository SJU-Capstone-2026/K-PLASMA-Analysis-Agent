"""The actual gateway counts and sends the same projected d1 request."""

from copy import deepcopy
import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.model_gateway import (
    V2LocalLLMModelGateway,
    V2LocalLLMSettings,
    review_plan,
)
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context
from .plan_review_cases import compare, literal, plan, result_ref, search
from .test_d1_input import without_citation_text
from .test_plan_review import example_context


def native_answer(request):
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "answers": {
                name: {
                    "type": "choice",
                    "choice": "match",
                    "confidence": 1.0,
                    "probabilities": {key: float(key == "match") for key in q["criteria"]},
                }
                for name, q in body["questions"].items()
            },
            "usage": {"input_tokens": 100},
        },
    )


def test_final_plan_review_counts_exact_wire_and_preserves_original_snapshot():
    original = example_context()
    snapshot = deepcopy(original)
    counted = []
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return native_answer(request)

    def guard(body, role):
        assert role == "plan_review"
        counted.append(deepcopy(body))

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        settings = V2LocalLLMSettings.from_env(Settings())
        gateway = V2LocalLLMModelGateway(settings, client, guard)
        result, usage = gateway.review_plan(original)
    assert original == snapshot
    assert len(counted) == len(sent) == 1
    state = json.loads(sent[0]["state"])
    assert "execution_view" not in state
    assert "plan_digest" not in state and "input_digest" not in state
    assert without_citation_text(state["plan"]) == without_citation_text(example_context("s_search")["plan"])
    assert snapshot["question"] not in sent[0]["state"]
    assert state == counted[0]["input"]
    qs = {q["name"]: q for q in counted[0]["questions"]}
    for name, native in sent[0]["questions"].items():
        assert native["instructions"] == qs[name]["instructions"]
        assert native["criteria"] == {x["value"]: x["description"] for x in qs[name]["choices"]}
    assert result["status"] == "PASS" and result["plan_digest"] == snapshot["plan_digest"]
    assert result["input_digest"] == snapshot["input_digest"]
    assert usage == {"input_tokens": 100}


def test_module_level_plan_review_uses_same_final_profile():
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return native_answer(request)

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        result, _ = review_plan(client, V2LocalLLMSettings.from_env(Settings()), example_context())
    assert result["status"] == "PASS"
    state = json.loads(sent[0]["state"])
    assert "execution_view" not in state
    assert without_citation_text(state["plan"]) == without_citation_text(example_context("s_search")["plan"])


@pytest.mark.parametrize(("retry_choice", "status"), [
    ("match", "PASS"), ("missing", "ISSUE"), ("unexpected", "ISSUE"), ("direction_changed", "ISSUE"),
])
def test_unclear_ordering_rechecks_only_the_same_plan_with_the_original_question(retry_choice, status):
    original = example_context()
    snapshot = deepcopy(original)
    sent = []
    counted = []
    name = "ordering.s_search"

    def transport(request):
        sent.append(json.loads(request.content))
        choice = "unclear" if len(sent) == 1 else retry_choice
        data = native_answer(request).json()
        row = data["answers"][name]
        row.update(choice=choice, probabilities={key: float(key == choice) for key in row["probabilities"]})
        return httpx.Response(200, json=data)

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        settings = V2LocalLLMSettings.from_env(Settings())
        result, usage = review_plan(client, settings, original, input_guard=lambda body, _: counted.append(body))

    first, retry = sent
    first_view, retry_view = (json.loads(item["state"]) for item in (first, retry))
    assert original == snapshot and original["question"] not in first["state"]
    assert retry_view == {**first_view, "question": original["question"]}
    criteria = first["questions"][name]["criteria"]
    assert list(criteria) == ["match", "direction_changed", "missing", "unexpected", "unclear"]
    retry_criteria = {key: description for key, description in criteria.items() if key != "unclear"}
    assert retry["questions"] == {name: {**first["questions"][name], "criteria": retry_criteria}}
    assert list(retry["questions"][name]["criteria"]) == list(retry_criteria)
    assert [item["input"] for item in counted] == [first_view, retry_view]
    assert [item["name"] for item in counted[1]["questions"]] == [name]
    assert result["status"] == status and result["plan_digest"] == original["plan_digest"]
    assert {row["name"]: row["choice"] for row in result["checks"]} == {
        spec["name"]: retry_choice if spec["kind"] == "ordering" else "match" for spec in original["check_specs"]
    }
    ordering = next(row for row in result["checks"] if row["kind"] == "ordering")
    assert ordering["probabilities"] == {key: float(key == retry_choice) for key in retry_criteria}
    assert usage == {"input_tokens": 200}


def test_review_names_cover_all_steps_and_feedback_uses_original_ids():
    question = "압력 8 mTorr인 Run의 조회, 후보 비교 및 설명 요청에 s_forward_2라는 메모가 있습니다."
    pressure = literal(8, "mTorr", question)
    first = {"id": "s_forward_2", "kind": "tool", "tool": "forward_lookup", "inputs": {"pressure": pressure}}
    second = {**first, "id": "lookup"}
    candidates = search([], id="s_forward")
    confirm = {"id": "pick", "kind": "await_input", "confirmation": "run_selection",
               "depends_on": ["s_forward"], "inputs": {"target_step_id": "compare", "field": "runs",
               "candidates": result_ref("s_forward")}}
    selected = result_ref("s_forward")
    selected["scope"] = {"kind": "confirmed_selection", "step_id": "pick"}
    comparison = compare(selected, depends=["s_forward", "pick"])
    derived = {"id": "calc", "kind": "derive", "operation": "max", "depends_on": ["compare", "lookup"],
               "required_prior_outputs": [{"step_id": "compare", "field": "pressure"}],
               "run_if": [{"step_id": "lookup", "field": "candidate_count", "operator": "gte", "value": 1}],
               "inputs": {"values": result_ref("compare", "pressure", "context_selection")}}
    derived["inputs"]["values"]["scope"]["key"] = "selected_runs"
    explanation = {"id": "explanation", "kind": "tool", "tool": "explain_answer",
                   "inputs": {"mode": "results"}}
    steps = [first, second, candidates, confirm, comparison, derived]
    explanation["depends_on"] = [step["id"] for step in steps]
    original = build_plan_review_context(plan(question, [*steps, explanation]), 1, question, [], {},
                                         {"s_forward_2": {"status": "verified", "executionId": "run-1"}})
    saved = deepcopy(original)

    def transport(request):
        body = json.loads(request.content)
        state = json.loads(body["state"])
        expected_ids = ["s_forward", "s_forward_2", "s_search", "s_confirm", "s_compare", "s_derive", "s_explain"]
        assert [step["id"] for step in state["plan"]["steps"]] == expected_ids
        assert without_citation_text(state["plan"]["requirements"]) == [{"id": "r", "handled_by": expected_ids}]
        assert state["completed_steps"] == {"s_forward": {"status": "verified", "execution_id": "run-1"}}
        assert question not in body["state"]
        _, lookup, _, confirmation, comparison, calculation, explanation = state["plan"]["steps"]
        assert without_citation_text(lookup["inputs"]["pressure"]) == without_citation_text(pressure)
        assert confirmation["inputs"]["target_step_id"] == "s_compare"
        assert confirmation["inputs"]["candidates"]["step_id"] == "s_search"
        assert comparison["depends_on"] == ["s_search", "s_confirm"]
        assert comparison["inputs"]["runs"]["scope"]["step_id"] == "s_confirm"
        assert calculation["inputs"]["values"]["step_id"] == "s_compare"
        assert calculation["required_prior_outputs"][0]["step_id"] == "s_compare"
        assert calculation["run_if"][0]["step_id"] == "s_forward_2"
        assert explanation["depends_on"] == expected_ids[:-1]
        result = native_answer(request).json()
        name = "filter.s_forward_2.pressure"
        row = result["answers"][name]
        row.update(choice="missing", probabilities={key: float(key == "missing") for key in row["probabilities"]})
        return httpx.Response(200, json=result)

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        settings = V2LocalLLMSettings.from_env(Settings())
        gateway = V2LocalLLMModelGateway(settings, client, lambda *_: None)
        result, _ = gateway.review_plan(original)

    assert original == saved
    assert result["status"] == "ISSUE" and result["plan_digest"] == saved["plan_digest"]
    issue = next(check["issue"] for check in result["checks"] if check["issue"])
    assert issue["condition_id"] == "filter.lookup.pressure"
    assert issue["step_ids"] == ["lookup"]
