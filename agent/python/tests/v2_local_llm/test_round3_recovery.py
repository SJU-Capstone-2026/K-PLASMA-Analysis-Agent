"""Regression cases use artificial outputs and never call a model provider."""

from copy import deepcopy
import warnings

import pytest
from pydantic import ValidationError

from .fixtures import run
from kplasma_agent.v2_local_llm.graph import build_v2_local_llm_graph
from kplasma_agent.v2_local_llm.model_client import ModelError
from kplasma_agent.v2_local_llm.core.composition import collect_evidence, collect_numeric_values
from kplasma_agent.v2_local_llm.core.contracts import ChoiceResultRef, PlanDraft, ResultRef, StepResult
from kplasma_agent.v2_local_llm.core.plan_validation import InvalidPlan, validate_plan
from .test_graph import GeneralModel, Journal
from .test_plan_validation import comparison, draft


def test_result_reference_schema_rejects_an_option_name_as_an_output():
    with pytest.raises(ValidationError):
        ResultRef.model_validate({"kind": "result_ref", "step_id": "axis", "field": "trend_axis",
                                  "scope": {"kind": "scalar"}})


def test_choice_reference_schema_and_producer_checks_agree():
    assert ChoiceResultRef.model_json_schema()["properties"]["field"]["const"] == "value"
    search = {"id": "search", "kind": "tool", "tool": "reverse_search", "inputs": {"constraints": []}}
    compare = comparison()
    compare.update(depends_on=["search"])
    compare["inputs"]["runs"] = {"kind": "result_ref", "step_id": "search", "field": "selection",
                                  "scope": {"kind": "candidate_group"}}
    with pytest.raises(InvalidPlan) as caught:
        validate_plan(draft(search, compare), messages={"question": "비교"}, context_keys=set())
    assert caught.value.details["actual"] == "selection"
    assert caught.value.details["allowed"] == ["candidates"]


def test_axis_confirmation_is_connected_to_the_comparison_by_code():
    axis = {"id": "axis", "kind": "await_input", "confirmation": "trend_axis",
            "inputs": {"target_step_id": "compare", "field": "trend_axis"}}
    compare = comparison()
    accepted = validate_plan(draft(axis, compare), messages={"question": "비교"}, context_keys={"selected_runs"})
    step = accepted.steps[-1]
    assert step.depends_on == ["axis"]
    assert step.inputs.trend_axis.field == "value"
    assert step.inputs.trend_axis.step_id == "axis"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert PlanDraft.model_validate(accepted.model_dump(mode="json")) == accepted


def test_axis_confirmation_cannot_replace_an_explicit_conflicting_axis():
    axis = {"id": "axis", "kind": "await_input", "confirmation": "trend_axis",
            "inputs": {"target_step_id": "compare", "field": "trend_axis"}}
    compare = comparison()
    compare["inputs"]["trend_axis"] = {"kind": "literal", "value": "pressure", "unit": None,
                                          "source": {"message_key": "question", "quote": "비교"}}
    with pytest.raises(InvalidPlan, match="conflicts"):
        validate_plan(draft(axis, compare), messages={"question": "비교"}, context_keys={"selected_runs"})


@pytest.mark.parametrize("kind", ["forward_lookup", "reverse_search"])
def test_lookup_measurements_are_citable_without_changing_data_only_evidence(kind):
    sample = run("artificial", energy=150, flux=42, width=None)
    ref = {key: sample[key] for key in ("runId", "runVersionId")}
    raw = {"kind": kind, "candidates": [sample]} if kind == "forward_lookup" else {
        "kind": kind, "commonRunRefs": [ref], "runsByVersion": {ref["runVersionId"]: sample}}
    result = StepResult(executionId="execution-1", stepId="lookup", status="verified",
                        outputs={"toolResult": raw, "candidates": [ref]})
    assert [item.field for item in collect_evidence([result])] == ["candidates"]
    evidence = collect_evidence([result], search_measurements=True)
    flux, = [item for item in evidence if item.field == "ionFlux"]
    assert flux.value == 42 and flux.runRef.runVersionId == ref["runVersionId"]
    assert collect_numeric_values([result], evidence)[flux.id] == {"value": "42 10¹⁸ m⁻²s⁻¹"}
    assert not any(item.field == "iedWidth" for item in evidence)


class RecordingModel(GeneralModel):
    def __init__(self):
        self.plans = []
        self.compositions = []

    def submit_plan(self, context):
        self.plans.append(deepcopy(context))
        return super().submit_plan(context)

    def compose(self, context):
        self.compositions.append(deepcopy(context))
        return super().compose(context)


def invoke(models):
    return build_v2_local_llm_graph(models, Journal(), None).invoke({
        "request_id": "artificial-request", "question": "IED 설명", "context": {}, "input_history": []})


def test_code_replan_receives_the_rejected_plan_and_validation_error():
    class Models(RecordingModel):
        def submit_plan(self, context):
            plan, usage = super().submit_plan(context)
            if len(self.plans) == 1:
                plan["steps"][0]["requirement_ids"] = ["missing"]
                self.rejected = deepcopy(plan)
            return plan, usage

    models = Models()
    answer = invoke(models)["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == "COMPLETE"
    assert models.plans[1]["previous_plan"] is None
    assert models.plans[1]["rejected_plan"] == models.rejected
    assert models.plans[1]["validation_error"]["message"]


def test_answer_rewrite_receives_the_rejected_draft():
    class Models(RecordingModel):
        def compose(self, context):
            good, usage = super().compose(context)
            return ({"paragraphs": [], "sources": []} if len(self.compositions) == 1 else good), usage

    models = Models()
    answer = invoke(models)["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == "COMPLETE"
    assert models.compositions[1]["rejected_draft"] == {"paragraphs": [], "sources": []}
    assert models.compositions[1]["validation_error"]["errors"][0]["path"] == "/paragraphs"


def test_failed_explanation_is_marked_as_incomplete():
    class Models(RecordingModel):
        def compose(self, context):
            super().compose(context)
            return {"paragraphs": [], "sources": []}, {}

    answer = invoke(Models())["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == "FAILED"
    assert answer["hasIncompleteWork"] is True


@pytest.mark.parametrize(("code", "status", "always_fail", "calls", "execution"), [
    ("MODEL_OUTPUT_INVALID", "completed", False, 2, "COMPLETE"),
    ("MODEL_OUTPUT_INVALID", "completed", True, 2, "FAILED"),
    ("MODEL_OUTPUT_INVALID", None, True, 1, "FAILED"),
    ("MODEL_TIMEOUT", "completed", True, 1, "FAILED"),
])
def test_completed_but_invalid_answer_uses_only_one_existing_rewrite(code, status, always_fail, calls, execution):
    details = {"code": "INVALID_ANSWER", "errors": [{"path": "/interpretations/0/evidence_ids", "type": "too_short"}]}

    class Models(RecordingModel):
        def compose(self, context):
            result = super().compose(context)
            if always_fail or len(self.compositions) == 1:
                raise ModelError(code, usage={"status": status} if status else None,
                                 response={"validation_error": details} if status else None)
            return result

    models = Models()
    answer = invoke(models)["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == execution
    assert len(models.compositions) == calls
    assert answer["budget"]["answer_rewrites_used"] == calls - 1
    if calls == 2:
        assert models.compositions[1]["validation_error"] == details


@pytest.mark.parametrize("always_fail", [False, True])
def test_truncated_plan_recovery_uses_the_existing_replan_budget(always_fail):
    class Models(RecordingModel):
        def submit_plan(self, context):
            plan, usage = super().submit_plan(context)
            if always_fail or len(self.plans) == 1:
                raise ModelError("MODEL_OUTPUT_TRUNCATED", usage={"outputTokens": 6000}, response={
                    "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [{"type": "function_call", "arguments": '{"steps":' + ' ' * 3000}]})
            return plan, usage

    models = Models()
    answer = invoke(models)["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == ("FAILED" if always_fail else "COMPLETE")
    assert len(models.plans) == (3 if always_fail else 2)
    assert answer["budget"]["replans_used"] == (2 if always_fail else 1)
    failure = models.plans[1]["generation_failure"]
    assert failure["code"] == "MODEL_OUTPUT_TRUNCATED"
    assert failure["trailing_whitespace_chars"] == 3000
    assert len(failure["partial_arguments_tail"]) <= 500


def test_reference_formula_uses_existing_general_answer_after_plan_review():
    model = RecordingModel()
    journal = Journal()
    result = build_v2_local_llm_graph(model, journal, None).invoke({
        "request_id": "formula", "question": "이온 플럭스의 정의와 기본 공식을 짧게 설명해줘.",
        "context": {}, "input_history": [],
    })
    assert journal.calls == ["PLAN_INITIAL", "PLAN_REVIEW"]
    assert model.compositions == []
    answer = result["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == "COMPLETE"
    assert "Γᵢ = nᵢ uᵢ" in answer["answer"]


def test_source_unit_limitation_uses_only_completed_comparison_evidence():
    from kplasma_agent.v2_local_llm.core.composition import assemble_answer, reference_answer

    question = ("평균 이온 에너지가 100–120 eV인 모든 실제 Run의 IEAD 최대 강도와 피크 에너지·각도를 비교하고, "
                "원본 강도 단위가 지정되지 않은 점이 해석에 주는 한계를 설명해줘.")
    assert reference_answer(question, "data_request", []) is None
    metrics = ["iead.maximum", "iead.peakEnergy", "iead.peakAngle"]
    result = StepResult(executionId="compare", stepId="compare", status="partial", outputs={"toolResult": {
        "kind": "compare_runs", "runs": [{"metrics": {"iead.maximum": {"reason": "UNIT_NOT_COMPARABLE",
                                                                      "sourceValue": {"value": 3}}}}],
        "observations": [{"id": field, "text": field, "source": {"kind": "summary", "metric": field}}
                         for field in metrics],
    }})
    answer = reference_answer(question, "data_request", [result])
    rendered, _ = assemble_answer(answer, "data_request", collect_evidence([result]))
    assert answer["fact_ids"] == [f"compare:{metric}" for metric in metrics]
    assert "원본에 강도 수치는 있지만 물리 단위가 지정되지 않아" in rendered
    result.outputs["toolResult"]["runs"][0]["metrics"]["iead.maximum"]["reason"] = "INSUFFICIENT_DATA"
    assert reference_answer(question, "data_request", [result]) is None
