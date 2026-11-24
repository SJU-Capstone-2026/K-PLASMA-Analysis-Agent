import pytest
from pydantic import ValidationError

from kplasma_agent.v2_local_llm.core.bindings import BlockedInput, resolve_inputs
from kplasma_agent.v2_local_llm.core.contracts import PlanDraft, StepResult
from kplasma_agent.v2_local_llm.core.plan_validation import InvalidPlan, validate_plan
from .plan_review_cases import constraint, interval, plan, result_ref, search


def draft(*steps):
    return PlanDraft.model_validate({
        "schema_version": 2, "request_mode": "data_request", "base_revision": None,
        "requirements": [{"id": "req", "text": "비교", "sources": [
            {"message_key": "question", "quote": "비교"}
        ], "handled_by": [step["id"] for step in steps]}],
        "steps": [{**step, "requirement_ids": ["req"]} for step in steps],
    })


def comparison():
    return {"id": "compare", "kind": "tool", "tool": "compare_runs",
            "inputs": {"runs": {"kind": "context_ref", "key": "selected_runs"}, "fields": ["ionFlux"]}}


@pytest.mark.parametrize("extra", [
    {"id": "choose", "kind": "await_input", "confirmation": "run_selection", "depends_on": ["search"],
     "inputs": {"target_step_id": "search", "field": "runs", "selection_count": 2}},
    {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["search"],
     "inputs": {"mode": "results"}},
])
def test_standalone_sorted_search_does_not_require_a_new_selection_or_interpretation(extra):
    question = "압력이 7 mTorr 이상인 실제 Run을 찾아서 평균 이온 에너지가 높은 순으로 보여줘."
    lookup = search([constraint("pressure", "gte", 7, "mTorr", "압력이 7 mTorr 이상")],
                    goals=[{"field": "meanIonEnergy", "direction": "maximize"}])
    candidate = plan(question, [lookup, extra])
    output = validate_plan(candidate, messages={"question": question}, context_keys=set())
    assert [step.id for step in output.steps] == ["search"]
    assert output.requirements[0].handled_by == ["search"]
    assert output.steps[0].inputs.constraints == candidate.steps[0].inputs.constraints
    assert output.steps[0].inputs.goals == candidate.steps[0].inputs.goals
    with_followup = question + " 결과가 의미하는 바를 설명해줘."
    assert len(validate_plan(candidate, messages={"question": with_followup}, context_keys=set()).steps) == 2


@pytest.mark.parametrize(("value", "unit", "expected"), [
    (7.5, "10¹⁸ m⁻²s⁻¹", (7.5e20, "m⁻²s⁻¹")),
    (750, "10¹⁸ m⁻²s⁻¹", (750, "10¹⁸ m⁻²s⁻¹")),
])
def test_standalone_search_preserves_explicit_flux_exponent(value, unit, expected):
    quote = "이온 플럭스가 7.5e20 m^-2 s^-1 이상이고"
    question = f"{quote} 평균 이온 에너지가 100 eV 이상 120 eV 이하인 실제 Run을 찾아서 플럭스가 높은 순으로 보여줘."
    lookup = search([constraint("ionFlux", "gte", value, unit, quote)],
                    goals=[{"field": "ionFlux", "direction": "maximize"}])
    candidate = plan(question, [lookup])
    output = validate_plan(candidate, messages={"question": question}, context_keys=set())
    binding = output.steps[0].inputs.constraints[0].value
    assert (binding.value, binding.unit) == expected
    assert binding.source.quote == quote
    assert candidate.steps[0].inputs.constraints[0].value.value == value


def test_search_excludes_explicit_endpoints_without_extra_explanation():
    question = ("평균 이온 에너지가 100 eV보다 크고 120 eV보다 작은 실제 Run만 찾아줘. "
                "100 eV와 120 eV는 둘 다 제외해줘.")
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["search"],
               "inputs": {"mode": "results"}}
    candidate = plan(question, [search([interval(100, 120, question)]), explain])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    lookup, = accepted.steps
    assert [(c.operator, c.value.value) for c in lookup.inputs.constraints] == [("gt", 100), ("lt", 120)]
    assert accepted.requirements[0].handled_by == ["search"]
    other = question.replace("100 eV와 120 eV는", "99 eV와 120 eV는")
    changed = plan(other, [search([interval(100, 120, other)])])
    assert validate_plan(changed, messages={"question": other}, context_keys=set()).steps[0].inputs.constraints[0].operator == "between"


def test_grouped_search_uses_the_exact_second_range_quote_and_sort():
    question = ("평균 이온 에너지가 100–110 eV인 후보와 120–130 eV인 후보를 각각 찾아줘. "
                "두 그룹을 따로 보여주고 각 그룹 안에서는 이온 플럭스가 높은 순으로 정렬해줘.")
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["first", "second"],
               "inputs": {"mode": "results"}}
    candidate = plan(question, [search([interval(100, 110, "평균 이온 에너지가 100–110 eV")], id="first"),
                                search([interval(120, 130, "평균 이온 에너지가 120–130 eV")], id="second"), explain])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    assert [step.id for step in accepted.steps] == ["first", "second"]
    for step in accepted.steps:
        goal, = step.inputs.goals
        assert (goal.field, goal.direction) == ("ionFlux", "maximize")
    bound, = accepted.steps[1].inputs.constraints
    assert bound.min.source.quote == bound.max.source.quote == "120–130 eV"


@pytest.mark.parametrize("mode", ["empty_lookup", "run_refs_as_bias", "lookup_candidates"])
def test_selected_distribution_comparison_keeps_its_confirmed_runs(mode):
    question = ("선택한 바이어스 전력 200 W인 두 Run의 IAD 최대 강도와 피크 입사각을 비교해줘. "
                "원본 데이터가 없으면 그 이유를 명확히 알려줘.")
    lookup = {"id": "lookup", "kind": "tool", "tool": "forward_lookup", "inputs": {}}
    compare = comparison()
    if mode == "run_refs_as_bias":
        lookup["inputs"]["bias_power"] = {"kind": "context_ref", "key": "selected_runs"}
    if mode == "lookup_candidates":
        lookup["inputs"]["bias_power"] = constraint("biasPower", "eq", 200, "W", "바이어스 전력 200 W")["value"]
        compare["inputs"]["runs"] = result_ref("lookup")
    compare.update(depends_on=["lookup"], required_prior_outputs=[
        {"step_id": "lookup", "field": "candidates", "value_type": "run_refs"},
    ])
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["compare"],
               "inputs": {"mode": "results"}}
    candidate = plan(question, [lookup, compare, explain])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys={"selected_runs"},
                             selected_run_keys={"R1", "R2"})
    assert [step.id for step in accepted.steps] == ["compare", "explain"]
    assert accepted.steps[0].inputs.fields == ["iad.maximum", "iad.peakAngle"]
    assert accepted.steps[0].depends_on == accepted.steps[0].required_prior_outputs == []
    assert accepted.requirements[0].handled_by == ["compare", "explain"]


def test_distribution_comparison_uses_the_registered_features_for_the_candidate_group():
    question = ("압력이 9 mTorr 이상인 실제 Run 중 이온 플럭스가 60 × 10¹⁸ m⁻²s⁻¹ 이상인 전체 Run의 IAD를 비교해줘. "
                "데이터가 없는 Run도 누락 이유를 보여줘.")
    compare = comparison()
    compare["inputs"].update(runs=result_ref("search"), fields=["iad.maximum"], plot_ids=["iad"])
    compare["depends_on"] = ["search"]
    candidate = plan(question, [search([constraint("pressure", "gte", 9, "mTorr", "압력이 9 mTorr 이상")]), compare])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    assert accepted.steps[1].inputs.fields == ["iad.maximum", "iad.peakAngle"]
    assert accepted.steps[1].inputs.runs.model_dump() == result_ref("search")


def test_explanation_of_one_exact_run_uses_a_forward_lookup():
    question = ("이온 플럭스가 무엇인지 짧게 설명하고, 압력 9 mTorr, 소스 전력 400 W, "
                "바이어스 전력 700 W인 실제 Run의 이온 플럭스와 평균 이온 에너지를 근거로 결과를 설명해줘.")
    lookup = search([constraint("pressure", "eq", 9, "mTorr", "9 mTorr"),
                     constraint("sourcePower", "eq", 400, "W", "400 W"),
                     constraint("biasPower", "eq", 700, "W", "700 W")])
    compare = comparison()
    compare["depends_on"] = ["search"]
    compare["inputs"]["runs"] = result_ref("search")
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["search", "compare"],
               "inputs": {"mode": "results"}}
    candidate = plan(question, [lookup, compare, explain])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    forward, answer = accepted.steps
    assert forward.tool == "forward_lookup" and answer.depends_on == [forward.id]
    assert (forward.inputs.pressure.value, forward.inputs.source_power.value, forward.inputs.bias_power.value) == (9, 400, 700)
    assert accepted.requirements[0].handled_by == ["search", "explain"]


@pytest.mark.parametrize(("question", "supplied", "expected"), [
    ("선택한 두 Run의 전극 전위 최댓값과 최솟값을 공정 조건에 따른 경향으로 비교해줘. "
     "경향을 볼 공정 조건 축은 내가 직접 선택하게 해줘.", ["potential.peakToPeak"],
     ["potential.maximum", "potential.minimum"]),
    ("선택한 압력 8 mTorr인 두 Run의 IAD 최대 강도와 피크 입사각을 비교해줘. "
     "원본 데이터가 없으면 그 이유를 명확히 알려줘.", ["iad.maximum", "iead.peakAngle"],
     ["iad.maximum", "iad.peakAngle"]),
])
def test_selected_comparison_uses_explicitly_named_outputs(question, supplied, expected):
    step = comparison()
    step["inputs"]["fields"] = supplied
    candidate = plan(question, [step])
    output = validate_plan(candidate, messages={"question": question}, context_keys={"selected_runs"},
                           selected_run_keys={"R1", "R2"})
    assert output.steps[0].inputs.fields == expected
    assert candidate.steps[0].inputs.fields == supplied
    qualified = question + " 다른 분포도 함께 넣어줘."
    assert validate_plan(candidate, messages={"question": qualified}, context_keys={"selected_runs"},
                         selected_run_keys={"R1", "R2"}).steps[0].inputs.fields == supplied


def test_comparison_normalizes_repeated_output_fields_before_tool_validation():
    step = comparison()
    step["inputs"]["fields"] = ["ionFlux", "meanIonEnergy", "ionFlux"]
    accepted = validate_plan(draft(step), messages={"question": "비교해줘"}, context_keys={"selected_runs"})
    assert accepted.steps[0].inputs.fields == ["ionFlux", "meanIonEnergy"]


def test_explanation_can_use_the_comparison_of_an_explicitly_named_causal_condition():
    question = "선택한 두 Run의 플럭스를 비교하고, 압력만이 원인인지 설명해줘."
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer",
               "depends_on": ["compare"], "inputs": {"mode": "results"}}
    accepted = validate_plan(draft(comparison(), explain), messages={"question": question},
                             context_keys={"selected_runs"}, selected_run_keys={"R1", "R2"})
    assert accepted.steps[0].inputs.fields == ["ionFlux", "pressure"]
    assert accepted.steps[1].id == "explain"


def test_baseline_choice_precedes_the_comparison_it_configures():
    choice = {
        "id": "choose", "kind": "await_input", "confirmation": "baseline", "depends_on": ["compare"],
        "required_prior_outputs": [{"step_id": "compare", "field": "ionFlux", "value_type": "quantities"}],
        "inputs": {"target_step_id": "compare", "field": "baseline"},
    }
    accepted = validate_plan(draft(comparison(), choice), messages={"question": "비교해줘"},
                             context_keys={"selected_runs"})
    choose, compare = accepted.steps
    assert choose.id == "choose" and choose.depends_on == [] and choose.required_prior_outputs == []
    assert compare.depends_on == ["choose"] and compare.inputs.baseline.step_id == "choose"


@pytest.mark.parametrize("provided_field", [None, "selection"])
def test_baseline_reference_does_not_require_a_numeric_output_from_selection(provided_field):
    compare = comparison()
    compare["depends_on"] = ["choose"]
    if provided_field:
        compare["inputs"]["baseline"] = {"kind": "result_ref", "step_id": "choose", "field": provided_field,
                                         "scope": {"kind": "scalar"}}
    compare["required_prior_outputs"] = [{"step_id": "choose", "field": "value", "count": 1,
                                           "value_type": "quantity", "unit": "eV"}]
    choose = {"id": "choose", "kind": "await_input", "confirmation": "baseline",
              "inputs": {"target_step_id": "compare", "field": "baseline"}}
    accepted = validate_plan(draft(choose, compare), messages={"question": "비교해줘"},
                             context_keys={"selected_runs"})
    assert accepted.steps[1].required_prior_outputs == []
    assert accepted.steps[1].inputs.baseline.step_id == "choose"


@pytest.mark.parametrize("message_key", ["question", "input_0"])
def test_plan_validation_restores_original_quote_spans_without_changing_the_draft(message_key):
    original = "압력 7.25 mTorr인 Run의 결과와 선택한 Run을 비교해줘."
    quote = "압력 7.25  mTorr인 Run  의 결과와 선택한 Run   을 비교해줘."
    candidate = plan(quote, [search([constraint("pressure", "eq", 7.25, "mTorr", "7.25   mTorr")])])
    candidate.requirements[0].sources[0].message_key = message_key
    candidate.steps[0].inputs.constraints[0].value.source.message_key = message_key
    submitted = candidate.model_dump(mode="json")

    accepted = validate_plan(candidate, messages={message_key: original}, context_keys=set())

    assert accepted.requirements[0].sources[0].model_dump() == {"message_key": message_key, "quote": original}
    accepted_filter = accepted.steps[0].inputs.constraints[0]
    assert accepted_filter.value.source.model_dump() == {"message_key": message_key, "quote": "7.25 mTorr"}
    assert (accepted_filter.operator, accepted_filter.value.value, accepted_filter.value.unit) == ("eq", 7.25, "mTorr")
    assert candidate.model_dump(mode="json") == submitted


@pytest.mark.parametrize(("original", "quote"), [
    ("Run의 지표 폭을 확인해줘.", "Run 의 지표 폭 을 확인해줘."),
    ("Run 의 지표를 확인해줘.", "Run의 지표를 확인해줘."),
    ("전력과 압력도 비교해줘.", "전력 과 압력 도 비교해줘."),
    ("기준표에서부터는 7.25 mTorr로 조회해줘.", "기준표 에서  부터 는 7.25 mTorr 로 조회해줘."),
    ("(기준값)만큼이나 높아?", "(기준값) 만큼이나 높아?"),
])
def test_plan_validation_restores_spacing_before_korean_particles(original, quote):
    candidate = plan(quote, [search([])])

    accepted = validate_plan(candidate, messages={"question": original}, context_keys=set())

    assert accepted.requirements[0].sources[0].quote == original


@pytest.mark.parametrize(("original", "quote"), [
    ("압력 7.25 mTorr", "압력 7 .25  mTorr"),
    ("출력 150 W까지", "출력 1 50 W 까지"),
    ("압력 17 mTorr", "7  mTorr"),
    ("압력 1.7 mTorr", "7  mTorr"),
    ("출력 -17 W", "17  W"),
    ("압력 7.25 mTorr", "압력  7"),
    ("압력 7.25 mTorr", "7.25  m Torr"),
    ("압력 7.25 mTorr", "압력  7.25 Torr"),
    ("압력 7.25 mTorr 이상", "압력 7.25  mTorr 초과"),
    ("Run의 표, Run의 표", "Run  의 표"),
    ("Run의 Run의 Run의", "Run  의 Run  의"),
    ("Run의사결정", "Run  의"),
    ("폭을 비교, 폭을 비교", "폭 을 비교"),
    ("압력을 비교", "압 력을 비교"),
    ("압력\n7.25 mTorr", "압력 7.25  mTorr"),
])
def test_plan_validation_rejects_changed_or_ambiguous_quotes(original, quote):
    candidate = plan(original, [search([constraint("pressure", "eq", 7.25, "mTorr", quote)])])
    with pytest.raises(InvalidPlan, match="unrecognized original text at question"):
        validate_plan(candidate, messages={"question": original}, context_keys=set())


def test_plan_validation_cannot_restore_quote_from_a_different_message():
    candidate = plan("Run  의 표", [search([])])
    candidate.requirements[0].sources[0].message_key = "input_0"
    with pytest.raises(InvalidPlan, match="unrecognized original text at input_0"):
        validate_plan(candidate, messages={"question": "Run의 표", "input_0": "선택 확인"}, context_keys=set())


@pytest.mark.parametrize("scope", [
    {"kind": "context_selection", "key": "selected_runs"},
    {"kind": "confirmed_selection", "step_id": "choose"},
])
def test_search_threshold_rejects_quantity_lists_before_tools_run(scope):
    search = {"id": "search", "kind": "tool", "tool": "reverse_search", "depends_on": ["compare"],
              "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt", "value": {
                  "kind": "result_ref", "step_id": "compare", "field": "ionFlux", "scope": scope}}]}}
    # context_selection is structurally valid today but has list cardinality.
    if scope["kind"] == "confirmed_selection":
        choose = {"id": "choose", "kind": "await_input", "confirmation": "run_selection",
                  "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2}}
        compared = comparison()
        compared["depends_on"] = ["choose"]
        plan = draft(choose, compared, search)
    else:
        plan = draft(comparison(), search)
    with pytest.raises(InvalidPlan, match="single quantity"):
        validate_plan(plan, messages={"question": "비교해줘"}, context_keys={"selected_runs"})


def test_single_confirmed_run_measurement_is_a_valid_numeric_threshold():
    search = {"id": "search", "kind": "tool", "tool": "reverse_search", "depends_on": ["compare"],
              "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt", "value": {
                  "kind": "result_ref", "step_id": "compare", "field": "ionFlux",
                  "scope": {"kind": "confirmed_run", "key": "R1"}}}]}}
    accepted = validate_plan(draft(comparison(), search), messages={"question": "비교해줘"},
                             context_keys={"selected_runs", "R1"}, selected_run_keys={"R1"})
    assert [step.id for step in accepted.steps] == ["compare", "search"]


@pytest.mark.parametrize(("field", "scope"), [
    ("ionFlux", {"kind": "context_selection", "key": "selected_runs"}), ("value", {"kind": "scalar"}),
])
def test_explicit_selected_group_threshold_repairs_an_older_comparison_reference(field, scope):
    question = ("선택한 두 Run의 이온 플럭스를 비교한 뒤, 두 Run 모두보다 플럭스가 높고 "
                "압력이 7 mTorr 이상인 Run을 찾아줘.")
    step = {"id": "search", "kind": "tool", "tool": "reverse_search", "depends_on": ["compare"],
            "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt", "value": {
                "kind": "result_ref", "step_id": "compare", "field": field, "scope": scope,
            }}]}}
    if field == "value":
        step["required_prior_outputs"] = [{"step_id": "compare", "field": field, "value_type": "quantity"}]
    accepted = validate_plan(draft(comparison(), step), messages={"question": question},
                             context_keys={"selected_runs"}, selected_run_keys={"R1", "R2"})
    compare, calculated, search_step = accepted.steps
    assert calculated.operation == "max" and calculated.depends_on == [compare.id]
    assert search_step.inputs.constraints[0].value.step_id == calculated.id
    assert search_step.inputs.constraints[0].value.scope.kind == "scalar"
    assert search_step.required_prior_outputs == []


def test_explicit_two_run_min_uses_the_selected_group_without_nested_operands():
    question = ("선택한 두 Run의 이온 플럭스를 비교한 뒤, 두 Run 모두보다 플럭스가 낮고 "
                "압력이 7 mTorr 이상인 실제 Run을 찾아줘.")
    producer = comparison()
    aggregation = {"id": "aggregate", "kind": "derive", "operation": "mean", "depends_on": ["compare"],
                   "inputs": {"values": [difference_ref("ionFlux")]},
                   "required_prior_outputs": [{"step_id": "compare", "field": "ionFlux", "value_type": "quantities"}]}
    lookup = search([{"field": "ionFlux", "operator": "lt", "value": result_ref("aggregate", "value", "scalar")}])
    lookup["depends_on"] = ["aggregate"]
    candidate = plan(question, [producer, aggregation, lookup])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys={"selected_runs"},
                             selected_run_keys={"R1", "R2"})
    step = accepted.steps[1]
    assert step.operation == "min"
    assert step.inputs.values.model_dump() == difference_ref("ionFlux")
    assert step.required_prior_outputs == []


@pytest.mark.parametrize("operand", [
    {"kind": "context_ref", "key": "selected_runs"},
    {"kind": "result_ref", "step_id": "average", "field": "value", "scope": {"kind": "scalar"}},
])
def test_explicit_selected_average_supplies_comparison_values_to_a_dangling_calculation(operand):
    question = ("선택한 두 Run의 이온 플럭스 평균을 계산하고, 그 평균보다 플럭스가 낮은 Run을 찾아줘.")
    average = {"id": "average", "kind": "derive", "operation": "mean", "inputs": {"values": [operand]}}
    search_step = {"id": "search", "kind": "tool", "tool": "reverse_search", "depends_on": ["average"],
                   "required_prior_outputs": [{"step_id": "average", "field": "value", "count": 1,
                                               "value_type": "quantity"}],
                   "inputs": {"constraints": [{"field": "ionFlux", "operator": "lt", "value": {
                       "kind": "result_ref", "step_id": "average", "field": "value", "scope": {"kind": "scalar"},
                   }}]}}
    candidate = draft(average, search_step)
    candidate.requirements[0].sources[0].quote = question
    accepted = validate_plan(candidate, messages={"question": question},
                             context_keys={"selected_runs"}, selected_run_keys={"R1", "R2"})
    compare, calculated, search_step = accepted.steps
    assert compare.inputs.runs.key == "selected_runs" and compare.inputs.fields == ["ionFlux"]
    assert calculated.id == "average" and calculated.inputs.values.step_id == compare.id
    assert calculated.inputs.values.scope.key == "selected_runs"
    assert search_step.required_prior_outputs == [] and search_step.inputs.constraints[0].value.step_id == "average"


def derive(field="ionFlux"):
    return {"id": "derive", "kind": "derive", "operation": "max", "depends_on": ["compare"],
            "inputs": {"values": {"kind": "result_ref", "step_id": "compare", "field": field,
                                  "scope": {"kind": "context_selection", "key": "selected_runs"}}}}


def difference_ref(field, key="selected_runs", kind="context_selection"):
    return {"kind": "result_ref", "step_id": "compare", "field": field, "scope": {"kind": kind, "key": key}}


@pytest.mark.parametrize("values, prior_outputs", [
    ([difference_ref("potential.maximum")], []),
    ([difference_ref("potential.minimum", "R1"), difference_ref("potential.minimum", "R2")], []),
    ([difference_ref("potential.maximum"), difference_ref("potential.minimum")], [
        {"step_id": "compare", "field": f"potential.{extreme}", "count": 2,
         "unit": "V", "value_type": "quantities"} for extreme in ("maximum", "minimum")
    ]),
])
def test_compare_uses_its_builtin_difference_without_a_duplicate_derive(values, prior_outputs):
    compare = comparison()
    compare["inputs"]["fields"] = ["potential.maximum", "potential.minimum", "potential.peakToPeak"]
    subtract = {**derive(), "operation": "difference", "inputs": {"values": values, "direction": "absolute"},
                "required_prior_outputs": prior_outputs}
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
    with pytest.raises(ValidationError, match="field"):
        validate_plan(draft(search, confirm, invalid), messages={"question": "후보 중 두 Run 비교"}, context_keys=set())


def test_search_with_simultaneous_conditions_does_not_require_explanation():
    question = "압력이 9 mTorr 이하이면서 바이어스 전력이 500 W 이상인 실제 Run을 모두 찾아줘."
    lookup = search([constraint("pressure", "lte", 9, "mTorr", "압력이 9 mTorr 이하"),
                     constraint("biasPower", "gte", 500, "W", "바이어스 전력이 500 W 이상")])
    extra = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["search"],
             "inputs": {"mode": "results"}}
    candidate = plan(question, [lookup, extra])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    assert [step.id for step in accepted.steps] == ["search"]
    assert accepted.steps[0].inputs.constraints == candidate.steps[0].inputs.constraints


def test_iead_unit_limitation_uses_the_actual_comparison_and_exact_source():
    phrase = "원본 강도 단위가 지정되지 않은 점이 해석에 주는 한계를 설명해줘"
    question = f"평균 이온 에너지가 100–120 eV인 모든 실제 Run의 IEAD 최대 강도와 피크 에너지·각도를 비교하고, {phrase}."
    compare = comparison()
    compare["inputs"].update(runs=result_ref("search"), fields=["iead.maximum"], plot_ids=["iead"])
    compare["depends_on"] = ["search"]
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["compare"],
               "inputs": {"mode": "concept"}, "required_prior_outputs": [{"step_id": "compare", "field": "iead.maximum"}]}
    candidate = plan(question, [search([interval(100, 120, "100–120 eV")]), compare, explain])
    candidate.steps[-1].requirement_ids = ["limitation"]
    candidate.requirements[0].handled_by.remove("explain")
    original = candidate.requirements[0]
    candidate.requirements.append(original.model_copy(update={
        "id": "limitation", "handled_by": ["explain"], "sources": [original.sources[0].model_copy(
            update={"quote": phrase.replace("한계를", "한계")})],
    }))
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    assert accepted.steps[-1].inputs.mode == "results"
    assert accepted.steps[-1].required_prior_outputs == []
    assert accepted.requirements[-1].sources[0].quote == phrase


def test_baseline_choice_guard_can_use_the_name_of_the_confirmed_input():
    compared = comparison()
    compared["depends_on"] = ["choose"]
    compared["required_prior_outputs"] = [{"step_id": "choose", "field": "baseline"}]
    choice = {"id": "choose", "kind": "await_input", "confirmation": "baseline",
              "inputs": {"target_step_id": "compare", "field": "baseline"}}
    accepted = validate_plan(draft(choice, compared), messages={"question": "비교해줘"}, context_keys={"selected_runs"})
    assert accepted.steps[-1].required_prior_outputs == []
    assert accepted.steps[-1].inputs.baseline.field == "value"


def test_explicit_sort_uses_search_order_without_a_redundant_candidate_comparison():
    question = "평균 이온 에너지가 100–120 eV인 실제 Run만 찾아서 이온 플럭스가 높은 순으로 보여줘."
    compare = comparison()
    compare["depends_on"] = ["search"]
    compare["inputs"]["runs"] = result_ref("search")
    candidate = plan(question, [search([interval(100, 120, "100–120 eV")]), compare])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    lookup, = accepted.steps
    goal, = lookup.inputs.goals
    assert (goal.field, goal.direction) == ("ionFlux", "maximize")
    assert lookup.inputs.constraints == candidate.steps[0].inputs.constraints
    combined = question + " 그리고 찾은 Run의 플럭스를 비교해줘."
    assert len(validate_plan(candidate, messages={"question": combined}, context_keys=set()).steps) == 2


def test_iead_group_comparison_uses_the_named_family_and_features():
    question = "평균 이온 에너지가 100–120 eV인 모든 실제 Run의 IEAD 최대 강도와 피크 에너지·각도를 비교해줘."
    compare = comparison()
    compare["depends_on"] = ["search"]
    compare["inputs"].update(runs=result_ref("search"), fields=["iad.maximum", "iad.peakAngle"], plot_ids=["iead"])
    accepted = validate_plan(plan(question, [search([interval(100, 120, "100–120 eV")]), compare]),
                             messages={"question": question}, context_keys=set())
    assert accepted.steps[1].inputs.fields == ["iead.maximum", "iead.peakEnergy", "iead.peakAngle"]
    assert accepted.steps[1].inputs.runs.model_dump() == result_ref("search")


def test_candidate_comparison_keeps_structured_results_and_explicit_explanations():
    question = "이온 플럭스가 60 × 10¹⁸ m⁻²s⁻¹ 이상인 실제 Run을 모두 찾아서, 찾은 전체 Run의 압력을 비교해줘."
    find = search([constraint("ionFlux", "gte", 60, "10¹⁸ m⁻²s⁻¹", "이온 플럭스가 60 × 10¹⁸ m⁻²s⁻¹ 이상")])
    compare = {**comparison(), "depends_on": ["search"],
               "inputs": {"runs": result_ref("search"), "fields": ["pressure"]}}
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["compare"],
               "inputs": {"mode": "results"}}
    candidate = plan(question, [find, compare, explain])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    assert [step.id for step in accepted.steps] == ["search", "compare"]
    assert accepted.requirements[0].handled_by == ["search", "compare"]
    extended = question + " 결과가 의미하는 바도 알려줘."
    assert len(validate_plan(candidate, messages={"question": extended}, context_keys=set()).steps) == 3


def test_selected_threshold_search_does_not_request_a_separate_explanation():
    question = ("선택한 두 Run의 이온 플럭스를 비교한 뒤, 두 Run 모두보다 플럭스가 낮고 "
                "압력이 7 mTorr 이상인 실제 Run을 찾아줘.")
    aggregation = {**derive(), "operation": "min"}
    find = search([{"field": "ionFlux", "operator": "lt", "value": result_ref("derive", "value", "scalar")},
                   constraint("pressure", "gte", 7, "mTorr", "압력이 7 mTorr 이상")])
    find["depends_on"] = ["compare", "derive"]
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer",
               "depends_on": ["compare", "search"], "inputs": {"mode": "results"}}
    candidate = plan(question, [comparison(), aggregation, find, explain])
    opts = {"context_keys": {"selected_runs"}, "selected_run_keys": {"R1", "R2"}}
    accepted = validate_plan(candidate, messages={"question": question}, **opts)
    assert [s.id for s in accepted.steps] == ["compare", "derive", "search"]
    assert accepted.steps[-1].inputs.constraints == candidate.steps[2].inputs.constraints
    extended = question + " 결과가 이유를 뒷받침하는지도 알려줘."
    assert len(validate_plan(candidate, messages={"question": extended}, **opts).steps) == 4


def test_comparison_uses_the_selected_run_list_when_an_implicit_guard_claims_it_is_numeric():
    question = ("압력이 7 mTorr 이상인 실제 Run을 찾아줘. 그 중 정확히 두 개를 내가 고를 테니 선택창을 띄우고, "
                "선택한 두 개의 이온 플럭스를 비교해줘.")
    find = search([constraint("pressure", "gte", 7, "mTorr", "압력이 7 mTorr 이상")])
    choice = {"id": "choose", "kind": "await_input", "confirmation": "run_selection", "depends_on": ["search"],
              "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2,
                         "candidates": result_ref("search")}}
    compare = {**comparison(), "depends_on": ["choose"],
               "inputs": {"runs": result_ref("choose", "selection", "scalar"), "fields": ["ionFlux"]},
               "required_prior_outputs": [{"step_id": "choose", "field": "selection", "count": 2,
                                           "value_type": "quantity"}]}
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["compare"],
               "inputs": {"mode": "results"}}
    accepted = validate_plan(plan(question, [find, choice, compare, explain]), messages={"question": question},
                             context_keys=set())
    assert [step.id for step in accepted.steps] == ["search", "choose", "compare"]
    assert accepted.steps[1].inputs.selection_count == 2
    guard, = accepted.steps[-1].required_prior_outputs
    assert guard.value_type == "run_refs" and guard.count == 2


def test_exact_forward_lookup_explanation_does_not_need_a_redundant_run_list_guard():
    question = ("이온 플럭스가 무엇인지 짧게 설명하고, 압력 9 mTorr, 소스 전력 400 W, "
                "바이어스 전력 700 W인 실제 Run의 이온 플럭스와 평균 이온 에너지를 근거로 결과를 설명해줘.")
    forward = {"id": "lookup", "kind": "tool", "tool": "forward_lookup", "inputs": {
        "pressure": constraint("pressure", "eq", 9, "mTorr", "9 mTorr")["value"],
        "source_power": constraint("sourcePower", "eq", 400, "W", "400 W")["value"],
        "bias_power": constraint("biasPower", "eq", 700, "W", "700 W")["value"],
    }}
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["lookup"],
               "inputs": {"mode": "results"}, "required_prior_outputs": [
                   {"step_id": "lookup", "field": "candidates", "value_type": "run_refs"},
               ]}
    candidate = plan(question, [forward, explain])
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    assert [step.id for step in accepted.steps] == ["lookup", "explain"]
    assert accepted.steps[-1].required_prior_outputs == []
    assert accepted.steps[-1].depends_on == ["lookup"]
    conditional = question + " 찾은 결과가 세 개일 때만 설명해줘."
    with pytest.raises(InvalidPlan, match="last, unconditional"):
        validate_plan(candidate, messages={"question": conditional}, context_keys=set())


@pytest.mark.parametrize("lookup_kind", ["one_per_selected_run", "redundant_filter"])
def test_selected_distribution_comparison_ignores_queries_that_replace_confirmed_runs(lookup_kind):
    question = ("선택한 바이어스 전력 200 W인 두 Run의 IAD 최대 강도와 피크 입사각을 비교해줘. "
                "원본 데이터가 없으면 그 이유를 명확히 알려줘.")
    compare = comparison()
    compare["inputs"]["fields"] = ["iad.maximum", "iad.peakAngle"]
    if lookup_kind == "one_per_selected_run":
        lookups = [{"id": f"lookup_{key}", "kind": "tool", "tool": "forward_lookup",
                    "inputs": dict.fromkeys(("pressure", "source_power", "bias_power"),
                                            {"kind": "context_ref", "key": key})}
                   for key in ("R1", "R2")]
    else:
        find = search([constraint("biasPower", "eq", 200, "W", "바이어스 전력 200 W")])
        lookups = [find]
        compare["inputs"]["runs"] = result_ref("search")
        compare["required_prior_outputs"] = [{"step_id": "search", "field": "candidates", "value_type": "run_refs"}]
    compare["depends_on"] = [step["id"] for step in lookups]
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer",
               "inputs": {"mode": "results"}, "depends_on": [*compare["depends_on"], "compare"]}
    accepted = validate_plan(plan(question, [*lookups, compare, explain]), messages={"question": question},
                             context_keys={"selected_runs", "R1", "R2"}, selected_run_keys={"R1", "R2"})
    verified, explanation = accepted.steps
    assert verified.id == "compare" and verified.inputs.runs.key == "selected_runs"
    assert verified.depends_on == verified.required_prior_outputs == []
    assert explanation.depends_on == ["compare"]


def test_one_result_explanation_carries_both_concept_and_lookup_evidence_requirements():
    concept = "이온 플럭스가 무엇인지 짧게 설명하고"
    results = ("압력 9 mTorr, 소스 전력 400 W, 바이어스 전력 700 W인 실제 Run의 이온 플럭스와 "
               "평균 이온 에너지를 근거로 결과를 설명해줘")
    question = f"{concept}, {results}."
    forward = {"id": "lookup", "kind": "tool", "tool": "forward_lookup", "inputs": {
        "pressure": constraint("pressure", "eq", 9, "mTorr", "9 mTorr")["value"],
        "source_power": constraint("sourcePower", "eq", 400, "W", "400 W")["value"],
        "bias_power": constraint("biasPower", "eq", 700, "W", "700 W")["value"],
    }}
    explain = {"id": "explain", "kind": "tool", "tool": "explain_answer", "depends_on": ["lookup"],
               "inputs": {"mode": "results"}, "required_prior_outputs": [
                   {"step_id": "lookup", "field": "value", "value_type": "quantities"},
               ]}
    definition = {"id": "definition", "kind": "tool", "tool": "explain_answer", "inputs": {"mode": "concept"}}
    candidate = plan(question, [definition, forward, explain])
    candidate.steps[0].requirement_ids = ["concept"]
    candidate.requirements[0].handled_by.remove("definition")
    requirement = candidate.requirements[0]
    candidate.requirements.append(requirement.model_copy(update={"id": "concept", "handled_by": ["definition"],
        "sources": [requirement.sources[0].model_copy(update={"quote": concept})]}))
    accepted = validate_plan(candidate, messages={"question": question}, context_keys=set())
    assert [step.id for step in accepted.steps] == ["lookup", "explain"]
    assert accepted.steps[-1].required_prior_outputs == []
    assert accepted.steps[-1].requirement_ids == ["r", "concept"]
    assert accepted.requirements[-1].handled_by == ["explain"]
    assert accepted.requirements[-1].sources[0].quote == concept
