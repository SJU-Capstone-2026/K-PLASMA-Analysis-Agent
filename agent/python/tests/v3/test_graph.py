import pytest

from kplasma_agent.v3.graph import build_v3_graph
from kplasma_agent.v3.core.composition import (
    assemble_answer, collect_comparison_coverage, collect_evidence, collect_numeric_values, collect_search_evidence,
)
from kplasma_agent.v3.core.contracts import StepResult


@pytest.mark.parametrize("token, expected_error", [
    ("{{value:compare:O1}}", None),
    ("{{value:compare:O2}}", "not cited"),
    ("{{value:compare:O1|unknown}}", "unavailable"),
    ("{{value:compare:O1", "invalid value reference"),
])
def test_numeric_answer_references_use_saved_values_and_units(token, expected_error):
    result = StepResult(executionId="compare", stepId="compare", status="verified", outputs={"toolResult": {
        "kind": "compare_runs",
        "observations": [
            {"id": "O1", "text": "최솟값 절대 차이", "source": {"kind": "comparison", "key": "minimum"}},
            {"id": "O2", "text": "최댓값 절대 차이", "source": {"kind": "comparison", "key": "maximum"}},
        ],
        "comparisons": [
            {"id": "minimum", "difference": {"status": "AVAILABLE", "value": 430.8701, "unit": "V"}},
            {"id": "maximum", "difference": {"status": "AVAILABLE", "value": 0.271, "unit": "V"}},
        ],
    }})
    draft = {"fact_ids": ["compare:O1"], "limitations": [], "interpretations": [{
        "id": "difference", "text": f"최솟값 차이는 {token}입니다.", "evidence_ids": ["compare:O1"],
        "assumptions": ["200 W 조건을 비교합니다."],
    }]}
    evidence = collect_evidence([result])
    numeric_values = collect_numeric_values([result], evidence)
    if expected_error:
        with pytest.raises(ValueError, match=expected_error):
            assemble_answer(draft, "data_request", evidence, numeric_values=numeric_values)
        return
    rendered, saved = assemble_answer(draft, "data_request", evidence, numeric_values=numeric_values)
    assert "최솟값 차이는 430.87 V입니다." in rendered
    assert "200 W 조건을 비교합니다." in rendered
    assert saved["interpretations"][0]["text"] == "최솟값 차이는 430.87 V입니다."


def test_exact_forward_lookup_projects_conditions_and_measurements_as_evidence():
    run = {"runId": "example", "runVersionId": "version", "pressure": 8,
           "sourcePower": 300, "biasPower": 600, "metrics": {"meanIonEnergy": 150},
           "units": {"pressure": "mTorr", "sourcePower": "W", "biasPower": "W", "meanIonEnergy": "eV"}}
    result = StepResult(executionId="saved", stepId="lookup", status="verified", outputs={"toolResult": {
        "kind": "forward_lookup", "resultStatus": "EXACT",
        "requestedConditions": {"pressure": 8, "sourcePower": 300, "biasPower": 600},
        "candidates": [run],
    }})
    evidence, = collect_search_evidence([result])
    assert evidence["resultStatus"] == "EXACT"
    assert evidence["requestedConditions"]["pressure"] == {"value": 8, "unit": "mTorr"}
    candidate, = evidence["candidates"]
    assert candidate["runRef"]["runVersionId"] == "version"
    assert {"metric": "meanIonEnergy", "value": 150, "unit": "eV", "reason": None} in candidate["measurements"]


def test_comparison_coverage_distinguishes_zero_angle_from_missing_output():
    result = StepResult(executionId="comparison", stepId="compare", status="partial", outputs={"toolResult": {
        "kind": "compare_runs", "metricIds": ["iead.peakAngle", "iead.maximum"], "plotIds": ["iead"],
        "runs": [
            {"metrics": {"iead.peakAngle": {"status": "AVAILABLE", "value": 0},
                         "iead.maximum": {"status": "UNAVAILABLE", "sourceValue": {"value": 0}}}},
            {"metrics": {"iead.peakAngle": {"status": "UNAVAILABLE", "value": None},
                         "iead.maximum": {"status": "UNAVAILABLE", "value": None}}},
        ],
        "outputs": [
            {"outputId": "iead", "status": "AVAILABLE", "reason": None},
            {"outputId": "iead", "status": "UNAVAILABLE", "reason": "BIAS_OFF"},
        ],
    }})
    assert collect_comparison_coverage([result]) == [{
        "executionId": "comparison", "runCount": 2,
        "availableRunValues": {"iead.peakAngle": 1, "iead.maximum": 0}, "rawRunValues": {"iead.maximum": 1},
        "plotOutputs": {"iead": {"AVAILABLE": 1, "BIAS_OFF": 1}},
    }]


class Journal:
    def __init__(self):
        self.calls = []

    def reserve_model(self, kind, key):
        self.calls.append(kind)
        return {"attemptId": key, "callAllowed": True, "outcome": None}

    def complete_model(self, attempt_id, outcome):
        return {"outcome": outcome}

    def accept_plan(self, plan):
        return {"revision": 1, "plan": plan.model_dump(mode="json")}


class GeneralModel:
    def review_plan(self, payload):
        from v3.runtime_helpers import matching_plan_review
        return matching_plan_review(payload)

    def submit_plan(self, context):
        from v3.runtime_helpers import add_explanation
        return add_explanation({"schema_version": 2, "request_mode": "general_only", "base_revision": None,
                "requirements": [], "steps": []}, context["messages"]["question"]), {}

    def compose(self, context):
        return {"paragraphs": ["이온 에너지 분포입니다."], "sources": []}, {}


def test_general_path_reviews_explicit_explanation_and_has_two_generation_calls():
    journal = Journal()
    graph = build_v3_graph(GeneralModel(), journal, None)
    result = graph.invoke({"request_id": "req", "question": "IED가 뭐야?", "context": {}, "input_history": []})
    assert journal.calls == ["PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE"]
    answer = result["answer"]["answerSnapshot"]
    assert answer["answer"] == "이온 에너지 분포입니다."
    assert answer["review"]["status"] == "SKIPPED"


@pytest.mark.parametrize(("needs_selection", "interpretation_requested", "expected_calls", "expected_status"), [
    (True, False, ["PLAN_INITIAL", "PLAN_REVIEW"], "PARTIAL"),
    (False, False, ["PLAN_INITIAL", "PLAN_REVIEW"], "COMPLETE"),
    (False, True, ["PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE", "REVIEW"], "COMPLETE"),
])
def test_data_answer_uses_writer_only_for_interpretation(needs_selection, interpretation_requested,
                                                        expected_calls, expected_status):
    from v3.runtime_helpers import ScriptedGateway

    class SearchJournal(Journal):
        def start_step(self, revision, step_id, inputs):
            return {"executionId": "saved-search", "callAllowed": True}

        def load_context(self, execution_id):
            return []

        def save_result(self, result):
            return {"result": result.model_dump(mode="json")}

    class SearchModel(ScriptedGateway):
        def submit_plan(self, payload):
            question = payload["messages"]["question"]
            plan = {"schema_version": 2, "request_mode": "data_request", "base_revision": None,
                    "requirements": [{"id": "request", "sources": [{"message_key": "question", "quote": question}],
                                      "text": question, "handled_by": ["choose" if needs_selection else "search"]}],
                    "steps": [
                        {"id": "search", "kind": "tool", "tool": "reverse_search", "requirement_ids": ["request"],
                         "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt", "value": {
                             "kind": "literal", "value": 100, "unit": None,
                             "source": {"message_key": "question", "quote": question},
                         }}]}},
                        *([{"id": "choose", "kind": "await_input", "confirmation": "run_selection",
                         "requirement_ids": ["request"], "depends_on": ["search"],
                         "inputs": {"target_step_id": "choose", "field": "selected_runs",
                                    "candidates": {"kind": "result_ref", "step_id": "search", "field": "candidates",
                                                   "scope": {"kind": "candidate_group"}}}}] if needs_selection else []),
                    ]}
            if interpretation_requested:
                from v3.runtime_helpers import add_explanation
                add_explanation(plan, question, "results")
            return plan, {}

        def compose(self, payload):
            fact_ids = [item["id"] for item in payload["evidence"]]
            return {"fact_ids": fact_ids, "limitations": [], "interpretations": [{
                "id": "meaning", "text": "이 검색으로는 후보의 특성을 비교할 수 없습니다.",
                "evidence_ids": fact_ids, "assumptions": [],
            }]}, {}

    journal = SearchJournal()
    graph = build_v3_graph(SearchModel(None, None, None), journal, None)
    result = graph.invoke({"request_id": "req", "question": "이온 플럭스 100보다 큰 후보 중 두 Run을 선택할게.",
                           "context": {}, "input_history": []})
    assert not result.get("__interrupt__")
    snapshot = result["answer"]["answerSnapshot"]
    assert journal.calls == expected_calls
    assert snapshot["executionStatus"] == expected_status
    assert snapshot["stepResults"][0]["status"] == "empty"
    assert snapshot["hasIncompleteWork"] is needs_selection
    if needs_selection:
        assert "비교에 필요한 수의 Run을 확보하지 못했습니다" in snapshot["answer"]
    elif not interpretation_requested:
        assert snapshot["draft"] is None
        assert "조건에 맞는 후보가 없습니다." in snapshot["answer"]
    if interpretation_requested:
        assert snapshot["review"]["status"] == "PASS"
    else:
        assert snapshot["review"]["status"] == "SKIPPED"
