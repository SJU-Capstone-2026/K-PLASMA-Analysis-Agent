import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import REVIEW_MODELS, Settings
from kplasma_agent.v2_local_llm.core.code_plan_checks import code_plan_checks
from kplasma_agent.v2_local_llm.core.model_gateway import V2LocalLLMSettings, review_plan
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context, matches_review_context, PlanReviewResult
from kplasma_agent.v2_local_llm.graph import build_v2_local_llm_graph

from .plan_review_cases import compare, interval, plan, result_ref, search, selected_context
from .test_d1_v23_gateway import native_answer
from .test_plan_review_graph import Models, journal


SEARCH = "평균 이온 에너지가 150–160 eV인 실제 Run을 찾아줘."
COMPARE = "선택한 두 Run의 압력을 비교해줘."


def test_explicit_shared_order_applies_to_both_independent_searches():
    question = ("압력이 5–9 mTorr인 후보와 10–13 mTorr인 후보를 각각 찾아줘. "
                "각 그룹을 따로 보여주고 두 그룹 안에서는 이온 플럭스가 높은 순으로 정렬해줘.")
    draft = plan(question, [
        search([], goals=[{"field": "ionFlux", "direction": "maximize"}]), search([], id="other"),
    ]).model_dump(mode="json")
    checks = code_plan_checks(question, draft, {}, [])
    assert {name: check["choice"] for name, check in checks.items()} == {
        "ordering.search": "match", "ordering.other": "missing",
    }
    assert code_plan_checks(question + " 첫 그룹은 반대로 해줘.", draft, {}, []) == {}


def test_flash_accepts_the_typed_candidate_input_of_an_unguarded_run_choice():
    question = ("평균 이온 에너지가 90–99 eV인 실제 Run을 찾아줘. 그중 정확히 두 개는 내가 직접 고를 테니 "
                "선택창을 띄우고, 선택한 두 개의 플럭스와 평균 이온 에너지만 비교해줘.")
    choose = {"id": "choose", "kind": "await_input", "confirmation": "run_selection", "depends_on": ["search"],
              "required_prior_outputs": [{"step_id": "search", "field": "candidates", "value_type": "run_refs"}],
              "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2,
                         "candidates": result_ref("search")}}
    draft = plan(question, [search([]), choose, compare(result_ref("choose", "selection", "scalar"),
                                                        depends=["choose"])]).model_dump(mode="json")
    checks = code_plan_checks(question, draft, {}, [], flash=True)
    assert checks["execution_guards.choose"]["choice"] == "match"
    draft["steps"][1]["required_prior_outputs"][0]["count"] = 2
    assert "execution_guards.choose" not in code_plan_checks(question, draft, {}, [], flash=True)


def test_flash_uses_verified_link_from_search_candidates_to_the_requested_run_choice():
    question = ("압력이 9 mTorr 이상인 실제 Run에서 정확히 두 개를 내가 고를게. "
                "먼저 선택하게 해주고 고른 두 개의 압력을 비교해줘.")
    choose = {"id": "choose", "kind": "await_input", "confirmation": "run_selection", "depends_on": ["search"],
              "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2,
                         "candidates": result_ref("search")}}
    draft = plan(question, [search([]), choose, compare(result_ref("choose", "selection", "scalar"),
                                                        depends=["choose"])]).model_dump(mode="json")
    assert code_plan_checks(question, draft, {}, [], flash=True)["selection_targets.choose"]["choice"] == "match"
    draft["steps"][1]["inputs"]["selection_count"] = 3
    assert "selection_targets.choose" not in code_plan_checks(question, draft, {}, [], flash=True)


@pytest.mark.parametrize(("operation", "operator", "group", "verdict"), [
    ("min", "lt", "selected_runs", "match"), ("max", "lt", "selected_runs", "direction_changed"),
    ("min", "gt", "selected_runs", "direction_changed"), ("min", "lt", "R1", "target_changed"),
])
def test_selected_group_operation_checks_the_aggregation_source_and_search_direction(operation, operator, group, verdict):
    question = ("선택한 두 Run의 이온 플럭스를 비교하고, 두 Run 모두보다 플럭스가 낮고 "
                "압력이 7 mTorr 이상인 Run을 찾아줘.")
    calculation = {"id": "threshold", "kind": "derive", "operation": operation, "depends_on": ["compare"],
                   "inputs": {"values": {"kind": "result_ref", "step_id": "compare", "field": "ionFlux",
                                         "scope": {"kind": "context_selection", "key": "selected_runs"}}}}
    comparator = compare({"kind": "context_ref", "key": group})
    comparator["inputs"]["fields"] = ["ionFlux"]
    search_step = search([{"field": "ionFlux", "operator": operator,
                           "value": result_ref("threshold", "value", "scalar")}])
    search_step["depends_on"] = ["threshold"]
    draft = plan(question, [comparator, calculation, search_step]).model_dump(mode="json")
    check = code_plan_checks(question, draft, selected_context(), [], flash=True)["operation.threshold"]
    assert check["choice"] == verdict
    assert "operation.threshold" not in code_plan_checks(question, draft, selected_context(),
                                                         [{"text": "다른 기준"}], flash=True)


def test_average_search_does_not_require_a_reference_run_for_its_numeric_threshold():
    question = ("선택한 두 Run의 이온 플럭스 평균을 계산하고, 그 평균보다 플럭스가 높은 Run을 찾아줘.")
    calculation = {"id": "threshold", "kind": "derive", "operation": "mean", "depends_on": ["compare"],
                   "inputs": {"values": {"kind": "result_ref", "step_id": "compare", "field": "ionFlux",
                                         "scope": {"kind": "context_selection", "key": "selected_runs"}}}}
    comparator = compare({"kind": "context_ref", "key": "selected_runs"})
    comparator["inputs"]["fields"] = ["ionFlux"]
    search_step = search([{"field": "ionFlux", "operator": "gt", "value": result_ref("threshold", "value", "scalar")}])
    search_step["depends_on"] = ["threshold"]
    draft = plan(question, [comparator, calculation, search_step]).model_dump(mode="json")
    assert code_plan_checks(question, draft, selected_context(), [], flash=True)["baseline.compare"]["choice"] == "match"
    explicit_baseline = question + " 비교 기준 Run은 내가 정할게."
    assert "baseline.compare" not in code_plan_checks(explicit_baseline, draft, selected_context(), [], flash=True)


@pytest.mark.parametrize(("question", "local_names"), [
    (SEARCH + " " + COMPARE, {"ordering.search", "targets.compare"}),
    (SEARCH + " 선택한 두 Run의 압력을 비교해줘. 어제 Run도 넣어줘.", set()),
])
def test_gateway_routes_only_unresolved_checks_to_d1(question, local_names):
    draft = plan(question, [
        search([interval(150, 160, question)]),
        compare({"kind": "context_ref", "key": "selected_runs"}),
    ])
    context = build_plan_review_context(draft, 1, question, [], selected_context(), {})
    sent = []

    def transport(request):
        sent.append(set(json.loads(request.content)["questions"]))
        return native_answer(request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        result, _ = review_plan(client, V2LocalLLMSettings.from_env(Settings()), context)

    verdict = PlanReviewResult.model_validate(result)
    wire_expected = {"request.filter_coverage", "request.confirmation_coverage",
                     "filter.s_search.meanIonEnergy", "outputs.s_compare", "baseline.s_compare",
                     "trend_axis.s_compare"}
    if not local_names:
        wire_expected.update({"ordering.s_search", "targets.s_compare"})
    assert sent == [wire_expected]
    assert {row.name for row in verdict.checks if not row.probabilities} == local_names
    assert verdict.status == "PASS"
    assert matches_review_context(verdict, context)


def test_direct_review_retains_code_errors_without_asking_d1_to_score_them():
    draft = plan(SEARCH, [search([interval(150, 160, SEARCH)],
                                 goals=[{"field": "ionFlux", "direction": "maximize"}])])
    context = build_plan_review_context(draft, 1, SEARCH, [], {}, {})
    sent = []

    def transport(request):
        sent.extend(json.loads(request.content)["questions"])
        return native_answer(request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        result, _ = review_plan(client, V2LocalLLMSettings.from_env(Settings()), context)

    verdict = PlanReviewResult.model_validate(result)
    issue, = [check for check in verdict.checks if check.issue]
    assert "ordering.s_search" not in sent
    assert verdict.status == "ISSUE" and issue.choice == "unexpected"
    assert issue.probabilities == {} and issue.issue["code_check"]["allowed"] == []
    assert matches_review_context(verdict, context)


def test_graph_sends_both_code_findings_with_the_rejected_plan_in_one_replan():
    question = ("평균 이온 에너지가 150–160 eV인 실제 Run을 찾아서 이온 플럭스가 높은 순으로 보여줘. "
                + COMPARE)
    draft = plan(question, [
        search([interval(150, 160, question)]),
        compare({"kind": "context_ref", "key": "R1"}),
    ]).model_dump(mode="json")
    models = Models([draft])
    port = journal()
    build_v2_local_llm_graph(models, port, None).invoke({
        "request_id": "test", "question": question, "context": {"comparisonReference": {"entries": selected_context()["comparison_entries"]}},
        "input_history": [],
    }, {"recursion_limit": 100})

    assert len(models.plan_inputs) > 1
    replan = models.plan_inputs[1]
    assert replan["rejected_plan"]["steps"] == draft["steps"]
    findings = replan["validation_error"]["errors"]
    assert {finding["path"]: finding["allowed"] for finding in findings} == {
        "/steps/0/inputs/goals": [{"field": "ionFlux", "direction": "maximize"}],
        "/steps/1/inputs/runs": {"kind": "context_ref", "key": "selected_runs"},
    }
    assert models.reviews == []


def test_flash_checks_an_unsolicited_choice_and_comparison_in_a_plain_lookup():
    choose = {"id": "choose", "kind": "await_input", "confirmation": "run_selection",
              "inputs": {"target_step_id": "compare", "field": "runs", "candidates": result_ref("search")}}
    draft = plan(SEARCH, [search([interval(150, 160, SEARCH)]), choose, compare(result_ref("search"))])
    context = build_plan_review_context(draft, 1, SEARCH, [], {}, {})
    sent = set()

    def transport(request):
        sent.update(json.loads(request.content)["questions"])
        return native_answer(request)

    settings = Settings(d1_model=REVIEW_MODELS["q4"][0], d1_precision="q4")
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        result, _ = review_plan(client, V2LocalLLMSettings.from_env(settings), context)

    verdict = PlanReviewResult.model_validate(result)
    issues = {item.name: item.choice for item in verdict.checks if item.issue is not None}
    assert issues == {"request.confirmation_coverage": "unexpected", "targets.compare": "unexpected"}
    assert "request.confirmation_coverage" not in sent and "targets.s_compare" not in sent
    assert matches_review_context(verdict, context, flash=True)


def test_flash_flags_a_physical_unit_on_prior_run_references():
    question = "내가 두 Run을 고른 뒤 압력을 비교해줘."
    choose = {"id": "choose", "kind": "await_input", "confirmation": "run_selection",
              "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2}}
    compare_step = compare(result_ref("choose", "selection", "scalar"), depends=["choose"])
    compare_step["required_prior_outputs"] = [
        {"step_id": "choose", "field": "selection", "unit": "mTorr", "value_type": "quantities"}
    ]
    context = build_plan_review_context(plan(question, [choose, compare_step]), 1, question, [], {}, {})
    settings = Settings(d1_model=REVIEW_MODELS["q4"][0], d1_precision="q4")
    with httpx.Client(transport=httpx.MockTransport(native_answer)) as client:
        result, _ = review_plan(client, V2LocalLLMSettings.from_env(settings), context)

    verdict = PlanReviewResult.model_validate(result)
    finding, = [item for item in verdict.checks if item.issue is not None]
    assert (finding.name, finding.choice, finding.probabilities) == ("execution_guards.compare", "unexpected", {})
    assert finding.issue["code_check"]["allowed"][0]["unit"] is None
    assert matches_review_context(verdict, context, flash=True)


def test_flash_uses_the_requested_baseline_choice_for_a_fixed_comparison():
    question = ("선택한 두 Run의 전류 밀도 최댓값과 최솟값을 기준 대비 비교하고 싶어. "
                "기준 Run은 내가 고를 테니 먼저 선택하게 해줘.")
    pick = {"id": "pick", "kind": "await_input", "confirmation": "baseline",
            "inputs": {"target_step_id": "compare", "field": "baseline"}}
    comparison = compare({"kind": "context_ref", "key": "selected_runs"},
                         ["current.maximum", "current.minimum"], ["pick"])
    comparison["inputs"]["baseline"] = result_ref("pick", "value", "scalar")
    draft = plan(question, [pick, comparison]).model_dump(mode="json")
    assert code_plan_checks(question, draft, selected_context(), [], flash=True)["baseline.compare"]["choice"] == "match"
    draft["steps"][1]["inputs"]["baseline"] = None
    assert "baseline.compare" not in code_plan_checks(question, draft, selected_context(), [], flash=True)
