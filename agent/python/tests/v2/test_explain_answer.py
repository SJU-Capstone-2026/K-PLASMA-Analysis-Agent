import pytest

from kplasma_agent.v2.contracts import PlanDraft
from kplasma_agent.v2.model_gateway import submit_plan_tool_schema
from kplasma_agent.v2.plan_validation import InvalidPlan, validate_plan


def explanation(mode="concept", depends=()):
    return {"id": "explain", "kind": "tool", "tool": "explain_answer",
            "requirement_ids": ["explanation"], "depends_on": list(depends), "inputs": {"mode": mode}}


def plan(*steps, mode="general_only"):
    return PlanDraft.model_validate({
        "schema_version": 2, "request_mode": mode, "base_revision": None,
        "requirements": [{"id": "explanation", "text": "설명", "sources": [
            {"message_key": "question", "quote": "설명"}], "handled_by": ["explain"]}],
        "steps": list(steps),
    })


def validate(value):
    return validate_plan(value, messages={"question": "설명해줘"}, context_keys={"selected_runs"})


def comparison():
    return {"id": "compare", "kind": "tool", "tool": "compare_runs", "requirement_ids": ["explanation"],
            "inputs": {"runs": {"kind": "context_ref", "key": "selected_runs"}, "fields": ["ionFlux"]}}


def test_schema_exposes_explanation_and_removes_interpretation_boolean():
    schema = submit_plan_tool_schema()["parameters"]
    assert schema["properties"]["schema_version"]["const"] == 2
    assert "interpretation_requested" not in schema["properties"]
    assert schema["$defs"]["ExplainInputs"]["properties"]["mode"]["enum"] == ["concept", "results"]


def test_concept_requirement_has_a_real_explanation_handler():
    accepted = validate(plan(explanation()))
    assert accepted.steps[0].tool == "explain_answer"
    assert accepted.requirements[0].handled_by == [accepted.steps[0].id]


@pytest.mark.parametrize("kind", ["concept", "results"])
def test_data_request_can_end_in_either_explanation_kind(kind):
    accepted = validate(plan(comparison(), explanation(kind, ["compare"]), mode="data_request"))
    assert accepted.steps[-1].inputs.mode == kind


def test_concept_request_cannot_omit_explanation():
    with pytest.raises(InvalidPlan, match="explain_answer"):
        validate(plan())


def test_results_explanation_cannot_bypass_actual_data():
    with pytest.raises(InvalidPlan):
        validate(plan(explanation("results"), mode="data_request"))


def test_explanation_must_be_unique_terminal_and_unconditional():
    other = {**explanation(), "id": "other"}
    for steps in ((explanation(), other), (explanation(), comparison()),
                  (comparison(), explanation("results")),):
        with pytest.raises(InvalidPlan, match="explain_answer"):
            validate(plan(*steps, mode="data_request"))
    conditional = {**explanation(), "run_if": [{"step_id": "compare", "field": "status",
                                              "operator": "eq", "value": "verified"}]}
    with pytest.raises(InvalidPlan, match="explain_answer"):
        validate(plan(comparison(), conditional, mode="data_request"))


def test_mixed_concept_explanation_keeps_data_and_does_not_enter_result_review():
    from runtime_v2_worker import ScriptedGateway, add_explanation
    from .test_graph import Journal
    from kplasma_agent.graphs.v2 import build_v2_graph

    class Port(Journal):
        def start_step(self, revision, step_id, inputs):
            assert step_id == "search"
            return {"executionId": "search-result", "callAllowed": True}

        def load_context(self, execution_id):
            return []

        def save_result(self, result):
            return {"result": result.model_dump(mode="json")}

    class Model(ScriptedGateway):
        def submit_plan(self, payload):
            question = payload["messages"]["question"]
            source = {"message_key": "question", "quote": question}
            value = {"schema_version": 2, "request_mode": "data_request", "base_revision": None,
                     "requirements": [{"id": "search", "text": question, "sources": [source],
                                       "handled_by": ["search"]}],
                     "steps": [{"id": "search", "kind": "tool", "tool": "reverse_search",
                                "requirement_ids": ["search"], "inputs": {"constraints": [{
                                    "field": "ionFlux", "operator": "gt", "value": {"kind": "literal",
                                    "value": 100, "unit": None, "source": source}}]}}]}
            return add_explanation(value, question, "concept"), {}

        def compose(self, payload):
            assert payload["mode"] == "general_only" and payload["request_mode"] == "data_request"
            assert [r["id"] for r in payload["requirements"]] == ["explanation"]
            assert payload["evidence"] == payload["search_evidence"] == payload["comparison_coverage"] == []
            return {"paragraphs": ["이온 플럭스는 단위 면적·시간당 입자 수입니다."], "sources": []}, {}

    port = Port()
    state = build_v2_graph(Model(None, None, None), port, None).invoke({
        "request_id": "mixed", "question": "플럭스 100 넘는 후보를 찾고 개념을 설명해줘.",
        "context": {}, "input_history": []})
    answer = state["answer"]["answerSnapshot"]
    assert port.calls == ["PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE"]
    assert answer["intent"] == "COMPOSITE_ANSWER" and answer["executionStatus"] == "COMPLETE"
    assert answer["draft"]["paragraphs"]
    assert "조건에 맞는 후보가 없습니다" in answer["answer"]
    assert answer["review"]["status"] == "SKIPPED"
