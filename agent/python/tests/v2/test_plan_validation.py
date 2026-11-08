import pytest

from kplasma_agent.v2.bindings import BlockedInput, resolve_inputs
from kplasma_agent.v2.contracts import PlanDraft, StepResult
from kplasma_agent.v2.plan_validation import InvalidPlan, validate_plan


def draft(*steps):
    return PlanDraft.model_validate({
        "schema_version": 1, "request_mode": "data_request", "base_revision": None,
        "requirements": [{"id": "req", "text": "비교", "sources": [
            {"message_key": "question", "quote": "비교"}
        ], "handled_by": [step["id"] for step in steps]}],
        "steps": [{**step, "requirement_ids": ["req"]} for step in steps],
    })


def comparison():
    return {"id": "compare", "kind": "tool", "tool": "compare_runs",
            "inputs": {"runs": {"kind": "context_ref", "key": "selected_runs"}, "fields": ["ionFlux"]}}


def derive(field="ionFlux"):
    return {"id": "derive", "kind": "derive", "operation": "max", "depends_on": ["compare"],
            "inputs": {"values": {"kind": "result_ref", "step_id": "compare", "field": field,
                                  "scope": {"kind": "context_selection", "key": "selected_runs"}}}}


def difference_ref(field, key="selected_runs", kind="context_selection"):
    return {"kind": "result_ref", "step_id": "compare", "field": field, "scope": {"kind": kind, "key": key}}


@pytest.mark.parametrize("values, requires", [
    ([difference_ref("potential.maximum")], []),
    ([difference_ref("potential.minimum", "R1"), difference_ref("potential.minimum", "R2")], []),
    ([difference_ref("potential.maximum"), difference_ref("potential.minimum")], [
        {"step_id": "compare", "field": f"potential.{extreme}", "count": 2,
         "unit": "V", "value_type": "quantities"} for extreme in ("maximum", "minimum")
    ]),
])
def test_compare_uses_its_builtin_difference_without_a_duplicate_derive(values, requires):
    compare = comparison()
    compare["inputs"]["fields"] = ["potential.maximum", "potential.minimum", "potential.peakToPeak"]
    subtract = {**derive(), "operation": "difference", "inputs": {"values": values, "direction": "absolute"},
                "requires": requires}
    plan = draft(compare, subtract)
    compare_req = plan.requirements[0].model_copy(update={"handled_by": ["compare"]})
    delta_req = compare_req.model_copy(update={"id": "delta", "handled_by": ["derive"]})
    derive_step = plan.steps[1].model_copy(update={"requirement_ids": ["delta"]})
    accepted = validate_plan(plan.model_copy(update={"requirements": [compare_req, delta_req],
                                                     "steps": [plan.steps[0], derive_step]}),
                             messages={"question": "비교해줘"}, context_keys={"selected_runs", "R1", "R2"},
                             selected_run_keys={"R1", "R2"})
    assert [step.id for step in accepted.steps] == ["compare"]
    assert [requirement.handled_by for requirement in accepted.requirements] == [["compare"], ["compare"]]
    assert accepted.steps[0].requirement_ids == ["req", "delta"]
    assert accepted.steps[0].inputs.fields == compare["inputs"]["fields"]


def test_preserves_comparison_difference_when_used_in_a_following_search():
    subtract = {**derive(), "operation": "difference", "inputs": {
        "values": difference_ref("ionFlux"), "direction": "absolute"}}
    search = {"id": "search", "kind": "tool", "tool": "reverse_search", "depends_on": ["derive"],
              "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt", "value": {
                  "kind": "result_ref", "step_id": "derive", "field": "value", "scope": {"kind": "scalar"},
              }}]}}
    accepted = validate_plan(draft(comparison(), subtract, search), messages={"question": "비교해줘"},
                             context_keys={"selected_runs", "R1", "R2"}, selected_run_keys={"R1", "R2"})
    assert [step.id for step in accepted.steps] == ["compare", "derive", "search"]


@pytest.mark.parametrize("direction, selected_run_keys", [
    ("first_minus_second", {"R1", "R2"}),
    ("absolute", {"R1", "R2", "R3"}),
])
def test_preserves_a_difference_the_comparison_does_not_provide(direction, selected_run_keys):
    subtract = {**derive(), "operation": "difference", "inputs": {
        "values": [difference_ref("ionFlux", key, "confirmed_run") for key in ("R1", "R2")],
        "direction": direction}}
    accepted = validate_plan(draft(comparison(), subtract), messages={"question": "비교해줘"},
                             context_keys={"selected_runs", *selected_run_keys}, selected_run_keys=selected_run_keys)
    assert [step.id for step in accepted.steps] == ["compare", "derive"]


def test_preserves_dependency_order_and_rejects_an_unrequested_field():
    kwargs = {"messages": {"question": "비교해줘"}, "context_keys": {"selected_runs", "R1"}}
    assert [s.id for s in validate_plan(draft(derive(), comparison()), **kwargs).steps] == ["compare", "derive"]
    with pytest.raises(InvalidPlan, match="iedWidth"):
        validate_plan(draft(comparison(), derive("iedWidth")), **kwargs)


def test_rejects_cycles_and_unknown_context_keys():
    kwargs = {"messages": {"question": "비교해줘"}, "context_keys": {"selected_runs", "R1"}}
    with pytest.raises(InvalidPlan, match="cycle"):
        validate_plan(draft({**comparison(), "depends_on": ["derive"]}, derive()), **kwargs)
    with pytest.raises(InvalidPlan, match="selected_runs"):
        validate_plan(draft(comparison()), messages=kwargs["messages"], context_keys=set())


def test_reverse_search_rejects_unsupported_literal_unit_before_execution():
    quote = {"message_key": "question", "quote": "적어도 1"}
    search = {"id": "search", "kind": "tool", "tool": "reverse_search", "inputs": {"constraints": [{
        "field": "ionFlux", "operator": "gte",
        "value": {"kind": "literal", "value": 1, "unit": "ions/(area·time)", "source": quote},
    }]}}
    with pytest.raises(InvalidPlan, match="ionFlux has an invalid value or unit"):
        validate_plan(draft(search), messages={"question": "플럭스가 적어도 1인 Run을 찾아 비교해줘"},
                      context_keys=set())


def test_planned_candidate_group_uses_every_saved_candidate_without_phrase_matching():
    search = {"id": "search", "kind": "tool", "tool": "reverse_search", "inputs": {"constraints": []}}
    candidates = {"kind": "result_ref", "step_id": "search", "field": "candidates",
                  "scope": {"kind": "candidate_group"}}
    compare = {**comparison(), "depends_on": ["search"], "inputs": {"runs": candidates, "fields": ["pressure"]}}
    plan = draft(search, compare)
    for question in ("이온 플럭스가 50 이상인 실험들 압력 비교해줘",
                     "플럭스 50 넘는 Run끼리 압력 비교해 줘",
                     "플럭스가 적어도 50인 경우에는 압력이 어떻게 다른지 비교해 볼래?"):
        accepted = validate_plan(plan, messages={"question": question}, context_keys=set())
    refs = [{"runId": f"run-{i}", "runVersionId": f"version-{i}"} for i in range(3)]
    result = StepResult(executionId="saved-search", stepId="search", status="verified", outputs={"candidates": refs})
    inputs = resolve_inputs(accepted.steps[-1], {}, {"search": result})
    assert inputs["runs"] == refs
    assert inputs["candidateExecutionId"] == "saved-search"
    for insufficient in ([], refs[:1]):
        with pytest.raises(BlockedInput, match="INSUFFICIENT_CANDIDATES"):
            resolve_inputs(accepted.steps[-1], {}, {"search": result.model_copy(
                update={"outputs": {"candidates": insufficient}},
            )})

    confirm = {"id": "confirm", "kind": "await_input", "confirmation": "run_selection",
               "depends_on": ["search"], "inputs": {"target_step_id": "compare", "field": "runs",
                                                     "candidates": candidates}}
    confirmed = {"kind": "result_ref", "step_id": "confirm", "field": "selection", "scope": {"kind": "scalar"}}
    compare = {**compare, "depends_on": ["confirm"], "inputs": {"runs": confirmed, "fields": ["pressure"]}}
    validate_plan(draft(search, confirm, compare), messages={"question": "후보 중 두 Run 비교"}, context_keys=set())
    invalid = {**compare, "inputs": {**compare["inputs"], "runs": {**confirmed, "field": "runs"}}}
    with pytest.raises(InvalidPlan, match="selection field"):
        validate_plan(draft(search, confirm, invalid), messages={"question": "후보 중 두 Run 비교"}, context_keys=set())
