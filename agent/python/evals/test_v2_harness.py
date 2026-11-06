from collections import Counter

import pytest

from .run_v2 import jobs
from .v2_cases import CASES
from .v2_harness import score_case


class MatchingPlanReview:
    """Explicit scripted response; these tests isolate execution and answer review."""

    def review_plan(self, context):
        from kplasma_agent.v2.plan_review import PLAN_REVIEW_QUESTIONS, PlanReviewCheck, review_result
        checks = [PlanReviewCheck(name=name, choice="match", probabilities={"match": 1.0, "mismatch": 0.0, "unclear": 0.0},
                                  confidence=1.0) for name in PLAN_REVIEW_QUESTIONS]
        return review_result(context, "PASS", checks=checks).model_dump(mode="json"), {}


def test_evaluation_matrix_has_24_cases_and_eight_repeated_three_times():
    matrix = list(jobs(24, None, 3))
    counts = Counter((model, effort, case.id) for model, effort, case, _ in matrix)
    assert len(CASES) == 24
    assert len(matrix) == 160
    assert Counter(counts.values()) == {1: 64, 3: 32}


def test_final_review_does_not_make_a_wrong_search_pass():
    case = next(c for c in CASES if c.id == "flux-over-20")
    plan = {"request_mode": "data_request", "steps": [{"kind": "tool", "tool": "reverse_search"}]}
    snapshot = {
        "answer": "후보: SYN-B, SYN-D", "executionStatus": "COMPLETE", "review": {"status": "PASS"},
        "stepResults": [{"outputs": {"toolResult": {
            "kind": "reverse_search", "commonRunIds": ["SYN-B", "SYN-D"],
        }}}],
    }
    steps = {"search": {"inputs": {"constraints": [{"metric": "ionFlux", "operator": "gte", "value": 20}]}}}
    failure = score_case(case, plan, snapshot, steps, False)
    assert "candidate groups differ" in failure["execution"]
    assert "missing ionFlux gt 20" in failure["execution"]


@pytest.mark.parametrize("plan_review_enabled", [True, False])
def test_completed_search_preserves_measurements_and_skips_writer_without_interpretation(plan_review_enabled):
    from kplasma_agent.v2.composition import collect_search_evidence
    from kplasma_agent.v2.contracts import StepResult

    from .v2_harness import evaluate_case

    case = next(c for c in CASES if c.id == "flux-over-20")

    class Model(MatchingPlanReview):
        def submit_plan(self, payload):
            assert payload["base_revision"] is None
            source = {"message_key": "question", "quote": case.question}
            return {"schema_version": 1, "request_mode": "data_request", "base_revision": None,
                    "interpretation_requested": False,
                    "requirements": [{"id": "r", "text": case.question, "sources": [source],
                                      "handled_by": ["search"]}],
                    "steps": [{"id": "search", "kind": "tool", "tool": "reverse_search", "requirement_ids": ["r"],
                               "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt", "value": {
                                   "kind": "literal", "value": 20, "unit": None, "source": source}}]}}]}, {}

    row = evaluate_case(case, Model(), plan_review_enabled=plan_review_enabled)
    assert row["pass"], row["failures"]
    snapshot = row["snapshot"]
    assert snapshot["executionStatus"] == "COMPLETE"
    assert snapshot["draft"] is None
    assert snapshot["review"]["status"] == "SKIPPED"
    assert snapshot["budget"]["tool_invocations_used"] == 1
    assert [attempt["kind"] for attempt in row["model_attempts"]] == (
        ["PLAN_INITIAL", "PLAN_REVIEW"] if plan_review_enabled else ["PLAN_INITIAL"])
    assert row["plan_review_enabled"] is plan_review_enabled
    assert row["stage_metrics"]["PLAN_INITIAL"]["calls"] == 1
    assert row["stage_metrics"]["PLAN_INITIAL"]["seconds"] >= 0
    assert row["plan_reviews"][0]["status"] == ("PASS" if plan_review_enabled else "SKIPPED")
    assert len(row["accepted_plans"]) == 1
    search, = collect_search_evidence([StepResult.model_validate(step) for step in snapshot["stepResults"]])
    rule, = search["constraints"]
    assert (rule["metric"], rule["operator"], rule["value"]) == ("ionFlux", "gt", 20)
    candidate, = search["candidates"]
    assert candidate["runRef"]["runId"] == "SYN-D"
    measurement, = candidate["measurements"]
    assert measurement["value"] == 40 and measurement["unit"] == rule["unit"]
    assert measurement["satisfied"] is True


def test_overclaim_review_uses_only_visible_interpretations_and_rewrites_without_reexecution():
    from dataclasses import replace

    from .v2_harness import evaluate_case

    case = replace(next(c for c in CASES if c.id == "compare-flux"),
                   question="선택한 두 Run의 이온 플럭스를 비교하고 차이의 의미를 설명해줘.")

    class Model(MatchingPlanReview):
        def submit_plan(self, payload):
            return {"schema_version": 1, "request_mode": "data_request", "base_revision": None,
                    "interpretation_requested": True,
                    "requirements": [{"id": "r", "text": case.question, "handled_by": ["compare"],
                                      "sources": [{"message_key": "question", "quote": case.question}]}],
                    "steps": [{"id": "compare", "kind": "tool", "tool": "compare_runs",
                               "requirement_ids": ["r"], "inputs": {"fields": ["ionFlux"],
                               "runs": {"kind": "context_ref", "key": "selected_runs"}}}]}, {}

        def compose(self, payload):
            evidence = [row["id"] for row in payload["evidence"] if row["field"] == "ionFlux"]
            text = ("관측된 차이만으로 원인을 단정할 수 없습니다." if payload["feedback"] == "overclaim"
                    else "압력 차이가 플럭스 차이의 유일한 원인임이 입증됐습니다.")
            return {"fact_ids": evidence, "interpretations": [{"id": "i", "text": text,
                    "evidence_ids": evidence, "assumptions": [f"기준 플럭스는 {{{{value:{evidence[0]}}}}}입니다."]}],
                    "limitations": []}, {}

        def review(self, payload):
            assert set(payload) == {"interpretations", "evidence"}
            item, = payload["interpretations"]
            assert {row["id"] for row in payload["evidence"]} == set(item["evidence_ids"])
            assert all(row["field"] == "ionFlux" for row in payload["evidence"])
            assert "{{value:" not in item["assumptions"][0]
            assert payload["evidence"][0]["unit"] in item["assumptions"][0]
            overclaim = "유일한 원인" in item["text"]
            choice = "overclaim" if overclaim else "within_evidence"
            return {"status": "ISSUE" if overclaim else "PASS", "answers": [{
                "name": "interpretation_scope", "choice": choice,
                "probabilities": {choice: 1.0}, "confidence": 1.0,
            }]}, {}

    row = evaluate_case(case, Model())
    assert row["pass"], row["failures"]
    answer = row["snapshot"]
    assert answer["review"]["status"] == "PASS"
    assert answer["draft"]["interpretations"][0]["text"] == "관측된 차이만으로 원인을 단정할 수 없습니다."
    assert answer["draft"]["interpretations"][0]["assumptions"][0] in answer["answer"]
    assert answer["budget"]["tool_invocations_used"] == 1
    assert answer["budget"]["replans_used"] == 0
    assert [attempt["kind"] for attempt in row["model_attempts"]] == [
        "PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE", "REVIEW", "ANSWER_REWRITE", "REVIEW"]


@pytest.mark.parametrize("selection_count", [None, 2, 3])
def test_search_candidates_are_saved_before_requesting_comparison_selection(selection_count):
    from langgraph.checkpoint.memory import InMemorySaver
    from kplasma_agent.graphs.v2 import build_v2_graph

    from .v2_cases import runs
    from .v2_harness import EvaluationJournal

    class Model(MatchingPlanReview):
        def submit_plan(self, payload):
            question = payload["messages"]["question"]
            source = {"message_key": "question", "quote": question}
            return {
                "schema_version": 1, "request_mode": "data_request", "base_revision": None,
                "requirements": [{"id": "r", "text": question, "sources": [source],
                                  "handled_by": ["search", "choose", "compare"]}],
                "steps": [
                    {"id": "search", "kind": "tool", "tool": "reverse_search", "requirement_ids": ["r"],
                     "inputs": {"constraints": [{"field": "ionFlux", "operator": "gte", "value": {
                         "kind": "literal", "value": 20, "unit": None, "source": source,
                     }}]}},
                    {"id": "choose", "kind": "await_input", "confirmation": "run_selection",
                     "requirement_ids": ["r"], "depends_on": ["search"],
                     "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": selection_count, "candidates": {
                         "kind": "result_ref", "step_id": "search", "field": "candidates",
                         "scope": {"kind": "candidate_group"},
                     }}},
                    {"id": "compare", "kind": "tool", "tool": "compare_runs",
                     "requirement_ids": ["r"], "depends_on": ["choose"],
                     "inputs": {"fields": ["pressure"], "runs": {
                         "kind": "result_ref", "step_id": "choose", "field": "selection",
                         "scope": {"kind": "scalar"},
                     }}},
                ],
            }, {}

    journal = EvaluationJournal(runs())
    graph = build_v2_graph(Model(), journal, InMemorySaver())
    state = graph.invoke(
        {"request_id": "req", "question": "플럭스 20 이상인 후보 찾아줘. 그중 괜찮은 것끼리 압력 비교해줘.",
         "context": {}, "input_history": []},
        {"configurable": {"thread_id": "req"}},
    )
    pending = state["__interrupt__"][0].value
    assert pending["type"] == "run_selection"
    assert pending["minSelections"] == (selection_count or 2)
    assert pending.get("maxSelections") == selection_count
    assert "검색 결과" in pending["message"]
    execution, = journal.steps
    assert pending["sourceExecutionId"] == execution
    assert {ref["runId"] for ref in journal.steps[execution]["result"]["outputs"]["candidates"]} == {
        "SYN-B", "SYN-C", "SYN-D",
    }


@pytest.mark.parametrize("output_field, search_first", [("baseline", False), ("selection", False), (None, True)])
def test_baseline_picker_waits_then_compares_against_the_chosen_run(output_field, search_first):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from kplasma_agent.domain.common import run_ref
    from kplasma_agent.graphs.v2 import build_v2_graph

    from .v2_cases import runs
    from .v2_harness import EvaluationJournal

    class Model(MatchingPlanReview):
        def submit_plan(self, payload):
            question = payload["messages"]["question"]
            source = {"message_key": "question", "quote": question}
            selected = {"kind": "context_ref", "key": "selected_runs"}
            candidates = {"kind": "result_ref", "step_id": "search", "field": "candidates",
                          "scope": {"kind": "candidate_group"}}
            search = {"id": "search", "kind": "tool", "tool": "reverse_search", "inputs": {"constraints": [{
                "field": "ionFlux", "operator": "gte",
                "value": {"kind": "literal", "value": 20, "unit": None, "source": source},
            }]}}
            choose = {"id": "choose", "kind": "await_input", "confirmation": "baseline", "inputs": {
                "target_step_id": "compare", "field": "baseline", "candidates": candidates if search_first else selected,
            }}
            compare = {"id": "compare", "kind": "tool", "tool": "compare_runs", "inputs": {
                "fields": ["pressure"], "runs": candidates if search_first else selected,
                "baseline": {"kind": "result_ref", "step_id": "choose", "field": output_field,
                             "scope": {"kind": "scalar"}} if output_field else None,
            }}
            steps = [search, choose, compare] if search_first else [choose, {**compare, "depends_on": ["choose"]}]
            return {"schema_version": 1, "request_mode": "data_request", "base_revision": None,
                    "requirements": [{"id": "r", "text": question, "sources": [source],
                                      "handled_by": [step["id"] for step in steps]}],
                    "steps": [{**step, "requirement_ids": ["r"]} for step in steps]}, {}

    source = runs()
    entries = [{"key": f"R{i}", "ref": run_ref(run)} for i, run in enumerate(source[:2], 1)]
    journal = EvaluationJournal(source)
    graph = build_v2_graph(Model(), journal, InMemorySaver())
    config = {"configurable": {"thread_id": "baseline"}, "recursion_limit": 80}
    question = ("플럭스 20 이상인 모든 Run의 압력을 비교해줘. 기준 Run은 내가 고를게." if search_first
                else "선택한 두 Run의 압력을 기준 대비 비교하고 싶어. 기준 Run은 내가 고를게.")
    paused = graph.invoke({"request_id": "baseline", "question": question,
                           "context": {"comparisonReference": {"entries": entries}}, "input_history": []}, config)
    pending, = paused.get("__interrupt__", ())
    assert pending.value["type"] == "comparison_options"
    assert pending.value["fields"] == ["baselineKey"]
    assert pending.value["allowedRunKeys"] == (["R1", "R2", "R3"] if search_first else ["R1", "R2"])
    assert pending.value["options"][1]["label"] == ("R2 · SYN-C" if search_first else "R2 · SYN-B")
    assert len(journal.steps) == int(search_first)

    resumed = graph.invoke(Command(resume={"type": "comparison_options", "baselineKey": "R2"}), config)
    snapshot = resumed["answer"]["answerSnapshot"]
    comparison = snapshot["stepResults"][-1]["outputs"]["toolResult"]
    assert snapshot["executionStatus"] == "COMPLETE"
    assert snapshot["budget"]["replans_used"] == 0
    assert len(journal.models) == 2
    assert comparison["baselineKey"] == "R2"
    assert comparison["comparisons"][0]["kind"] == "baseline_delta"
    assert comparison["comparisons"][0]["difference"]["value"] == -2
