"""Local v2.2 planner naming, compatibility and unchanged dependency checks."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.bindings import resolve_inputs
from kplasma_agent.v2_local_llm.core.contracts import PlanDraft, StepResult
from kplasma_agent.v2_local_llm.core.model_gateway import (
    PLAN_INSTRUCTIONS, call_submit_plan, submit_plan_tool_schema,
)
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context
from kplasma_agent.v2_local_llm.core.plan_validation import InvalidPlan, validate_plan
from kplasma_agent.v2_local_llm.model_client import ModelError


QUESTION = "인공 질문: 이온 플럭스 1 이상인 후보를 모두 찾아 비교해줘."


def plan_input(key="required_prior_outputs"):
    return {
        "schema_version": 2, "request_mode": "data_request", "base_revision": None,
        "requirements": [{"id": "r1", "text": QUESTION,
                          "sources": [{"message_key": "question", "quote": QUESTION}],
                          "handled_by": ["search", "compare"]}],
        "steps": [
            {"id": "search", "kind": "tool", "tool": "reverse_search", "requirement_ids": ["r1"],
             key: [], "inputs": {"constraints": [{"field": "ionFlux", "operator": "gte", "value": {
                 "kind": "literal", "value": 1, "unit": None,
                 "source": {"message_key": "question", "quote": "1"}}}]}},
            {"id": "compare", "kind": "tool", "tool": "compare_runs", "requirement_ids": ["r1"],
             "depends_on": ["search"], key: [{"step_id": "search", "field": "candidates",
                                              "count": None, "value_type": "run_refs", "unit": None}],
             "inputs": {"runs": {"kind": "result_ref", "step_id": "search", "field": "candidates",
                                 "scope": {"kind": "candidate_group"}}, "fields": ["ionFlux"]}},
        ],
    }


def validate(raw):
    return validate_plan(PlanDraft.model_validate(raw), messages={"question": QUESTION}, context_keys=set())


def test_native_schema_publishes_only_the_clear_prior_output_name():
    schema = submit_plan_tool_schema()["parameters"]
    for name in ["ForwardStep", "ReverseStep", "CompareStep", "DeriveStep", "AwaitInputStep", "ExplainStep"]:
        properties = schema["$defs"][name]["properties"]
        assert "required_prior_outputs" in properties
        assert "requires" not in properties
        assert "선행" in json.dumps(properties["required_prior_outputs"], ensure_ascii=False)
        assert "required_prior_outputs" in schema["$defs"][name]["required"]
    for field in ["step_id", "field", "count", "value_type", "unit"]:
        assert '"description"' in json.dumps(schema["$defs"]["OutputRequirement"]["properties"][field])
    assert "자기" in schema["$defs"]["OutputRequirement"]["properties"]["step_id"]["description"]


def test_exported_local_plan_schema_matches_the_runtime_contract():
    path = Path(__file__).resolve().parents[4] / "docs/contracts/agent-v2-local-llm.plan.schema.json"
    assert json.loads(path.read_text()) == PlanDraft.model_json_schema()


def test_legacy_plan_is_read_without_mutation_and_new_plans_write_only_the_new_name():
    legacy = plan_input("requires")
    before = deepcopy(legacy)
    converted = PlanDraft.model_validate(legacy).model_dump(mode="json")
    assert legacy == before
    assert all("requires" not in step and "required_prior_outputs" in step for step in converted["steps"])
    assert PlanDraft.model_validate(converted) == PlanDraft.model_validate(legacy)
    assert converted["steps"][1]["required_prior_outputs"] == legacy["steps"][1]["requires"]


def test_supplying_both_field_names_is_rejected_instead_of_merged():
    raw = plan_input()
    raw["steps"][0]["requires"] = []
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PlanDraft.model_validate(raw)


@pytest.mark.parametrize("current, legacy", [([], []), (None, []), ([], None)])
def test_native_parser_rejects_both_names_even_when_one_is_null(current, legacy):
    raw = plan_input()
    raw["steps"][0].update(required_prior_outputs=current, requires=legacy)
    planner = SimpleNamespace(_tool_request=lambda *_: ({"output": [{
        "type": "function_call", "name": "submit_plan", "call_id": "synthetic",
        "arguments": json.dumps(raw)}]}, None))
    with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID") as failed:
        call_submit_plan(planner, PLAN_INSTRUCTIONS, "인공 입력", submit_plan_tool_schema())
    assert any(item["type"] == "extra_forbidden" and item["path"].endswith("/requires")
               for item in failed.value.response["validation_error"]["errors"])


@pytest.mark.parametrize("key", ["required_prior_outputs", "requires"])
@pytest.mark.parametrize("location", ["plan", "inputs", "requirement"])
def test_native_parser_does_not_erase_misplaced_null_guard_fields(key, location):
    raw = plan_input()
    target = {"plan": raw, "inputs": raw["steps"][0]["inputs"],
              "requirement": raw["requirements"][0]}[location]
    target[key] = None
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PlanDraft.model_validate(raw)
    planner = SimpleNamespace(_tool_request=lambda *_: ({"output": [{
        "type": "function_call", "name": "submit_plan", "call_id": "synthetic",
        "arguments": json.dumps(raw)}]}, None))
    with pytest.raises(ModelError) as failed:
        call_submit_plan(planner, PLAN_INSTRUCTIONS, "인공 입력", submit_plan_tool_schema())
    assert any(item["type"] == "extra_forbidden" and item["path"].endswith("/" + key)
               for item in failed.value.response["validation_error"]["errors"])


@pytest.mark.parametrize("key", ["required_prior_outputs", "requires"])
def test_native_parser_normalizes_a_lone_null_guard_only_on_a_step(key):
    raw = plan_input(key)
    raw["steps"][0][key] = None
    planner = SimpleNamespace(_tool_request=lambda *_: ({"output": [{
        "type": "function_call", "name": "submit_plan", "call_id": "synthetic",
        "arguments": json.dumps(raw)}]}, None))
    parsed, _ = call_submit_plan(planner, PLAN_INSTRUCTIONS, "인공 입력", submit_plan_tool_schema())
    assert parsed["steps"][0]["required_prior_outputs"] == []


def test_legacy_guard_errors_use_the_new_path_and_keep_the_original_arguments():
    raw = plan_input("requires")
    raw["steps"][1]["requires"][0]["count"] = 0
    arguments = json.dumps(raw)
    planner = SimpleNamespace(_tool_request=lambda *_: ({"output": [{
        "type": "function_call", "name": "submit_plan", "call_id": "synthetic",
        "arguments": arguments}]}, None))
    with pytest.raises(ModelError) as failed:
        call_submit_plan(planner, PLAN_INSTRUCTIONS, "인공 입력", submit_plan_tool_schema())
    errors = failed.value.response["validation_error"]["errors"]
    paths = [item["path"] for item in errors if item["path"].endswith("/0/count")]
    assert paths and all("/required_prior_outputs/" in path for path in paths)
    assert failed.value.response["output"][0]["arguments"] == arguments


@pytest.mark.parametrize("producer", ["search", "compare", "missing"])
def test_self_future_and_missing_references_still_fail_before_execution(producer):
    raw = plan_input()
    raw["steps"][0]["required_prior_outputs"] = [{"step_id": producer, "field": "candidates"}]
    with pytest.raises(InvalidPlan, match="non-predecessor"):
        validate(raw)


def test_predecessor_output_is_checked_and_bound_without_changing_execution_rules():
    accepted = validate(plan_input())
    assert [step.id for step in accepted.steps] == ["search", "compare"]
    refs = [{"runId": "SYN-A", "runVersionId": "fixed-a"},
            {"runId": "SYN-B", "runVersionId": "fixed-b"}]
    result = StepResult(executionId="search-execution", stepId="search", status="verified",
                        outputs={"candidates": refs}, runRefs=refs)
    assert resolve_inputs(accepted.steps[1], {}, {"search": result})["runs"] == refs


def test_predecessor_must_really_produce_the_named_field():
    raw = plan_input()
    raw["steps"][1]["required_prior_outputs"][0]["field"] = "ionFlux"
    with pytest.raises(InvalidPlan, match="does not produce"):
        validate(raw)


def test_native_parser_preserves_bad_prior_outputs_for_the_existing_validator():
    raw = plan_input()
    raw["steps"][0]["required_prior_outputs"] = [{"step_id": "search", "field": "candidates"}]
    planner = SimpleNamespace(_tool_request=lambda *_: ({"output": [{
        "type": "function_call", "name": "submit_plan", "call_id": "synthetic",
        "arguments": json.dumps(raw)}]}, None))
    parsed, _ = call_submit_plan(planner, PLAN_INSTRUCTIONS, "인공 입력", submit_plan_tool_schema())
    assert parsed["steps"][0]["required_prior_outputs"]
    with pytest.raises(InvalidPlan, match="non-predecessor"):
        validate(parsed)


def test_decisions_context_uses_the_same_name_and_keeps_original_guard_checks():
    context = build_plan_review_context(validate(plan_input()), 1, QUESTION, [], {}, {})
    spec = next(x for x in context["check_specs"] if x["name"] == "execution_guards.compare")
    assert ["steps", 1, "required_prior_outputs"] in spec["paths"]
    assert "required_prior_outputs" in context["execution_view"][1]
    assert "requires" not in context["execution_view"][1]


def test_plan_guidance_distinguishes_prerequisites_order_and_input_bindings():
    assert '"requires"' not in PLAN_INSTRUCTIONS
    assert "required_prior_outputs" in PLAN_INSTRUCTIONS
    assert "자기 자신" in PLAN_INSTRUCTIONS
    assert "depends_on" in PLAN_INSTRUCTIONS and "inputs" in PLAN_INSTRUCTIONS
    assert "조회 결과를 표시할 지표 목록" in PLAN_INSTRUCTIONS
    assert Settings().versions()["planProtocol"] == "native-submit-plan-chat-v2"
