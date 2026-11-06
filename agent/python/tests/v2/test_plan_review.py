from copy import deepcopy
import math

import pytest

from kplasma_agent.v2.contracts import PlanDraft


QUESTION = "평균 이온 에너지가 150–160 eV인 실제 Run을 찾아줘."


def example_plan():
    return PlanDraft.model_validate({
        "schema_version": 1, "request_mode": "data_request", "base_revision": None,
        "requirements": [{"id": "r", "text": QUESTION,
                          "sources": [{"message_key": "question", "quote": "150–160 eV"}],
                          "handled_by": ["search"]}],
        "steps": [{"id": "search", "kind": "tool", "tool": "reverse_search", "requirement_ids": ["r"],
                   "inputs": {"constraints": [{"field": "meanIonEnergy", "operator": "gt", "value": {
                       "kind": "literal", "value": 0, "unit": "eV",
                       "source": {"message_key": "question", "quote": "150–160 eV"}}}]}}],
    })


def example_context():
    from kplasma_agent.v2.plan_review import build_plan_review_context
    return build_plan_review_context(example_plan(), 1, QUESTION, [], {
        "selected_runs": [{"runId": "SYN-A", "runVersionId": "fixed-a"}],
        "R1": {"runId": "SYN-A", "runVersionId": "fixed-a"},
    }, {})


def answers(choice="match"):
    return [{"name": name, "type": "choice", "choice": choice,
             "probabilities": [{"value": value, "probability": 0.05 if value == choice else 0.475}
                               for value in ("match", "mismatch", "unclear")], "confidence": 0.05}
            for name in ("request_coverage", "condition_preservation", "target_operation_alignment")]


def test_review_preserves_original_and_executable_inputs_even_if_requirement_prose_is_correct():
    context = example_context()
    assert context["question"] == QUESTION
    assert context["plan"]["requirements"][0]["text"] == QUESTION
    value = context["plan"]["steps"][0]["inputs"]["constraints"][0]["value"]
    assert value["value"] == 0
    assert value["source"]["quote"] == "150–160 eV"
    assert context["confirmed_context"]["R1"]["runVersionId"] == "fixed-a"
    assert context["policy_context"]["default_units"]["ionFlux"] == "10¹⁸ m⁻²s⁻¹"
    assert set(context["tool_contracts"]) == {
        "forward_lookup", "reverse_search", "compare_runs", "derive", "await_input", "bindings",
    }
    assert "iead.peakEnergy" in context["tool_contracts"]["compare_runs"]["fields"]


def test_plan_and_meaning_changes_invalidate_review_identity_without_mutating_input():
    from kplasma_agent.v2.plan_review import build_plan_review_context
    context = example_context()
    changed = example_plan().model_dump(mode="json")
    changed["steps"][0]["inputs"]["constraints"][0]["value"]["value"] = 150
    revised = build_plan_review_context(PlanDraft.model_validate(changed), 2, QUESTION, [], {}, {})
    assert revised["plan_digest"] != context["plan_digest"]
    assert example_plan().steps[0].inputs.constraints[0].value.value == 0
    corrected_question = build_plan_review_context(example_plan(), 1, "150 eV 이상으로 바꿔줘", [],
                                                 context["confirmed_context"], {})
    assert corrected_question["input_digest"] != context["input_digest"]


def test_completed_steps_do_not_send_waveforms_or_candidate_inventories():
    from kplasma_agent.v2.plan_review import build_plan_review_context
    context = build_plan_review_context(example_plan(), 1, QUESTION, [], {}, {
        "compare": {"status": "verified", "executionId": "saved", "outputs": {"waveform": [1, 2, 3]},
                    "runRefs": [{"runId": "SYN-A", "runVersionId": "fixed-a"}]},
    })
    assert context["completed_steps"] == {"compare": {"status": "verified", "execution_id": "saved"}}


def test_review_contract_explains_nullable_range_operands_and_comparison_inputs():
    tools = example_context()["tool_contracts"]
    assert "min" in tools["reverse_search"]["condition_inputs"]["between"]
    assert "max" in tools["reverse_search"]["condition_inputs"]["between"]
    assert "value:null" in tools["reverse_search"]["condition_inputs"]["between"]
    assert "candidate_group" in tools["compare_runs"]["input_semantics"]["runs"]
    assert "plot_ids" in tools["compare_runs"]["input_semantics"]


def test_execution_view_is_derived_from_actual_inputs_not_requirement_prose():
    context = example_context()
    view, = context["execution_view"]
    assert view["action"] == "reverse_search"
    rule, = view["inputs"]["constraints"]
    assert rule["operator"] == "gt" and rule["value"]["value"] == 0
    assert "150–160" in context["plan"]["requirements"][0]["text"]


def test_target_range_review_effect_matches_the_executed_inclusive_filter():
    from kplasma_agent.v2.bindings import resolve_inputs
    from kplasma_agent.v2.plan_review import build_plan_review_context

    raw = example_plan().model_dump(mode="json")
    literal = raw["steps"][0]["inputs"]["constraints"][0]["value"]
    bounds = {"field": "meanIonEnergy", "min": {**literal, "value": 150},
              "max": {**literal, "value": 160}}
    ranking = {"field": "ionFlux", "direction": "maximize"}
    raw["steps"][0]["inputs"] = {"constraints": [], "goals": [
        {**bounds, "direction": "target_range"}, ranking,
    ]}
    range_goal = PlanDraft.model_validate(raw)
    raw["steps"][0]["inputs"] = {"constraints": [{**bounds, "operator": "between"}],
                                  "goals": [ranking]}
    explicit_filter = PlanDraft.model_validate(raw)
    assert resolve_inputs(range_goal.steps[0], {}, {}) == resolve_inputs(explicit_filter.steps[0], {}, {})

    contexts = [build_plan_review_context(plan, 1, QUESTION, [], {}, {})
                for plan in (range_goal, explicit_filter)]
    assert contexts[0]["program_effects"] == contexts[1]["program_effects"]
    effect, = contexts[0]["program_effects"]
    assert "150 eV <= meanIonEnergy <= 160 eV" in effect
    assert "no numeric filter" not in effect
    assert "rank by" in effect and "maximize" in effect
    assert "target_range" not in effect
    assert "target_range" in contexts[0]["tool_contracts"]["reverse_search"]["condition_inputs"]


@pytest.mark.parametrize("choice,status", [("match", "PASS"), ("mismatch", "ISSUE"), ("unclear", "UNCLEAR")])
def test_choice_drives_verdict_even_when_confidence_is_low_and_answers_arrive_out_of_order(choice, status):
    from kplasma_agent.v2.plan_review import parse_plan_review, plan_review_feedback
    rows = answers()
    rows[1] = answers(choice)[1]
    result = parse_plan_review({"answers": list(reversed(rows))}, example_context())
    assert result.status == status
    assert result.checks[1].choice == choice
    assert result.checks[1].confidence == 0.05
    if choice != "match":
        assert plan_review_feedback(result)["failed_checks"] == {"condition_preservation": choice}


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "choice", "nan", "missing_probability", "duplicate_probability"])
def test_malformed_decisions_cannot_approve_execution(corruption):
    from kplasma_agent.v2.plan_review import parse_plan_review
    rows = deepcopy(answers())
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate":
        rows[1] = rows[0]
    elif corruption == "choice":
        rows[0]["choice"] = "approved"
    elif corruption == "nan":
        rows[0]["probabilities"][0]["probability"] = math.nan
    elif corruption == "missing_probability":
        rows[0]["probabilities"].pop()
    else:
        rows[0]["probabilities"][1] = rows[0]["probabilities"][0]
    with pytest.raises(ValueError):
        parse_plan_review({"answers": rows}, example_context())
