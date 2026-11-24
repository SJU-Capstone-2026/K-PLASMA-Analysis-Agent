import json

from kplasma_agent.v2_local_llm.core.d1_context import project_check
from kplasma_agent.v2_local_llm.core.d1_input import prepare_d1_input
from kplasma_agent.v2_local_llm.core.d1_plan_view import OMISSION_QUESTION
from kplasma_agent.v2_local_llm.core.decisions import native_request
from kplasma_agent.v2_local_llm.core.plan_checks import review_questions
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context

from .plan_review_cases import interval, plan, search


def request(question, steps, name, *, flash):
    context = build_plan_review_context(plan(question, steps), 1, question, [], {}, {})
    view, choices = prepare_d1_input(context, review_questions(context), role="plan_review", profile="en-compact-no-view")
    view[OMISSION_QUESTION] = question
    body = native_request({"input": [{"role": "user", "content": [{"type": "input_json", "data": view}]}],
                           "questions": choices})
    state, check, _ = project_check(body["state"], name, body["questions"][name], flash=flash)
    return json.loads(state), check


def test_flash_range_exposes_actual_inclusion_and_full_request_only_for_one_search():
    question = "평균 이온 에너지가 40 eV보다 크고 70 eV보다 작은 실제 Run만 찾아줘. 두 끝값을 제외해줘."
    first = search([interval(40, 70, question.split(".")[0])])
    legacy, legacy_check = request(question, [first], "filter.search.meanIonEnergy", flash=False)
    wire, check = request(question, [first], "filter.search.meanIonEnergy", flash=True)
    assert wire["question"] == question
    assert (wire["executed_lower_bound"]["operator"], wire["executed_upper_bound"]["operator"]) == (">=", "<=")
    assert "question" not in legacy and check["criteria"] == legacy_check["criteria"]

    second = search([interval(90, 100, question)], id="search2")
    hold, hold_check = request(question, [first, second], "filter.search.meanIonEnergy", flash=True)
    original, original_check = request(question, [first, second], "filter.search.meanIonEnergy", flash=False)
    assert (hold, hold_check) == (original, original_check)

    first["inputs"]["constraints"][0]["min"]["unit"] = None
    automatic, automatic_check = request(question, [first], "filter.search.meanIonEnergy", flash=True)
    inferred, inferred_check = request(question, [first], "filter.search.meanIonEnergy", flash=False)
    assert (automatic, automatic_check) == (inferred, inferred_check)


def test_flash_confirmation_view_contains_observed_dialogs_instead_of_complete_plan():
    question = "평균 이온 에너지가 40–70 eV인 실제 Run을 찾아줘."
    steps = [search([interval(40, 70, question)])]
    name = "request.confirmation_coverage"
    raw, old_check = request(question, steps, name, flash=False)
    wire, check = request(question, steps, name, flash=True)
    assert wire == {"question": question, "planned_confirmations": []}
    assert "plan" in raw and list(check["criteria"]) == list(old_check["criteria"])
