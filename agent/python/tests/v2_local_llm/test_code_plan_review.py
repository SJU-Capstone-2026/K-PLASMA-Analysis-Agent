import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import REVIEW_MODELS, Settings
from kplasma_agent.v2_local_llm.core.model_gateway import V2LocalLLMSettings, review_plan
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context, matches_review_context, PlanReviewResult
from kplasma_agent.v2_local_llm.graph import build_v2_local_llm_graph

from .plan_review_cases import compare, interval, plan, result_ref, search, selected_context
from .test_d1_v23_gateway import native_answer
from .test_plan_review_graph import Models, journal


SEARCH = "평균 이온 에너지가 150–160 eV인 실제 Run을 찾아줘."
COMPARE = "선택한 두 Run의 압력을 비교해줘."


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
