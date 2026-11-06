from copy import deepcopy

from kplasma_agent.domain.reverse import search_reverse
from kplasma_agent.v2.bindings import resolve_inputs
from kplasma_agent.v2.plan_validation import validate_plan

from .v2_cases import runs


def test_review_bank_has_thirteen_valid_pairs_including_combined_hitl_regression():
    from .plan_review_cases import cases
    from .run_plan_review import jobs

    bank = cases()
    assert len(bank) == 13 and len({c.id for c in bank}) == 13
    assert len(list(jobs(bank, 3))) == 78
    for case in bank:
        for plan in (case.good, case.bad):
            validate_plan(plan, messages={"question": case.question}, context_keys=set(case.context),
                          selected_run_keys={e["key"] for e in case.context.get("comparison_entries", [])})
        assert case.good.model_dump() != case.bad.model_dump()


def test_empty_real_results_do_not_hide_the_range_vs_equality_bug():
    from .plan_review_cases import cases

    case = next(c for c in cases() if c.id == "P03")
    probe = deepcopy(runs()[0])
    probe["metrics"]["meanIonEnergy"] = 9999.5
    groups = []
    for plan in (case.good, case.bad):
        inputs = resolve_inputs(plan.steps[0], {}, {})
        groups.append(search_reverse(inputs, [probe])["commonRunIds"])
    assert groups == [["SYN-A"], []]


def test_grader_uses_human_labels_not_the_decisions_verdict_as_ground_truth():
    from .run_plan_review import grade

    assert grade(False, "PASS") == "correct"
    assert grade(True, "PASS") == "false_accept"
    assert grade(False, "ISSUE") == "false_reject"
    assert grade(True, "ISSUE") == "correct"
    assert grade(True, "UNCLEAR") == "unclear"
    assert grade(False, "UNAVAILABLE") == "api_error"


def test_execution_view_retains_operations_preconditions_and_confirmations():
    from .plan_review_cases import cases
    from kplasma_agent.v2.plan_review import execution_view
    bank = {case.id: case for case in cases()}
    maximum = execution_view(bank["P01"].good)[1]
    assert maximum["action"] == "max"
    assert maximum["requires"][0]["count"] == 2
    choice = execution_view(bank["P09"].good)[1]
    assert choice["action"] == "run_selection"


def test_program_effects_describe_execution_not_the_copied_user_request():
    from .plan_review_cases import cases
    from kplasma_agent.v2.plan_review import program_effects
    bank = {case.id: case for case in cases()}
    good = program_effects(bank["P01"].good)
    bad = program_effects(bank["P01"].bad)
    assert "max(" in good[1]
    assert "150 eV <= meanIonEnergy <= 160 eV" in good[2]
    assert "meanIonEnergy > 0 eV" in bad[2]
    assert "AND" in good[2]
    assert "exactly 2" in program_effects(bank["P09"].good)[1]
    assert "8 mTorr" in program_effects(bank["P06"].good)[0]
    assert "context:selected_runs" in program_effects(bank["P11"].good)[0]
    assert "ALL user-confirmed Runs" in program_effects(bank["P13"].good)[-1]
