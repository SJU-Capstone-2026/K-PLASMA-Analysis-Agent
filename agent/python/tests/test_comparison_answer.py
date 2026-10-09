import pytest
from fixtures import run
from test_multi_run_compare import selected
from kplasma_agent.domain.compare import compare_selected
from kplasma_agent.explanations.answers import validate_answer, comparison_draft_model
from kplasma_agent.domain.common import DomainError


def test_numeric_observations_are_code_owned_and_unknown_ids_or_percent_restatement_are_rejected():
    result = compare_selected(
        {"metrics": ["ionFlux"], "baseline_key": "R1"}, selected(run("A", flux=2), run("B", flux=4))
    )
    observation = next(o for o in result["observations"] if o["source"]["kind"] == "comparison")
    assert "100 %" in observation["text"]
    draft = {
        "observationIds": [observation["id"]],
        "interpretations": [
            {
                "text": "플럭스가 증가한 가능한 이유는 입자 생성과 손실의 균형 변화입니다.",
                "observationIds": [observation["id"]],
                "assumptions": ["인과는 확정할 수 없습니다."],
            }
        ],
        "limitations": [],
    }
    assert validate_answer(draft, result)["status"] == "COMPLETE"
    for text in ("200% 증가했습니다.", "압력 8 mTorr에서 경향이 다릅니다."):
        draft["interpretations"][0]["text"] = text
        with pytest.raises(DomainError, match="ANSWER_NUMERIC_RESTATEMENT"):
            validate_answer(draft, result)
    draft["interpretations"] = []
    draft["observationIds"] = ["obs:other-comparison"]
    with pytest.raises(DomainError, match="ANSWER_OBSERVATION_MISMATCH"):
        validate_answer(draft, result)


def test_provider_schema_limits_both_observation_lists_to_the_frozen_result():
    from kplasma_agent.model_client import strict_schema

    result = compare_selected({}, selected(run("A"), run("B")))
    ids = [o["id"] for o in result["observations"]]
    assert ids == [f"O{i + 1}" for i in range(len(ids))]
    schema = strict_schema(comparison_draft_model(result))
    assert schema["properties"]["observationIds"]["items"]["enum"] == ids
    assert schema["$defs"]["ScopedInterpretation"]["properties"]["observationIds"]["items"]["enum"] == ids
    assert schema["$defs"]["ScopedInterpretation"]["properties"]["observationIds"]["minItems"] == 1


def test_process_conditions_have_citable_observations_without_changing_requested_metrics():
    result = compare_selected(
        {"metrics": ["ionFlux"]},
        selected(run("A", pressure=4, source=100, bias=200), run("B", pressure=6, source=300, bias=200)),
    )
    conditions = [o for o in result["observations"] if o["source"]["metric"] in ("pressure", "sourcePower", "biasPower")]
    assert len(conditions) == 6
    assert result["metricIds"] == ["ionFlux"]
    assert conditions[0]["source"] == {"kind": "run", "key": "R1", "metric": "pressure"}
    assert "4 mTorr" in conditions[0]["text"]
    draft = {"observationIds": ["O1"], "interpretations": [{
        "text": "압력과 소스 전력이 함께 달라 단일 조건의 인과 효과를 확정할 수 없습니다.",
        "observationIds": [o["id"] for o in conditions], "assumptions": [],
    }], "limitations": []}
    assert validate_answer(draft, result)["status"] == "COMPLETE"


@pytest.mark.parametrize("extended", [False, True])
def test_condition_evidence_cannot_reference_unknown_runs_or_summary_sources(extended):
    from pydantic import ValidationError
    from kplasma_agent.answer_contracts import ComparisonResultV2, ComparisonResultV3

    result = compare_selected(
        {"comparison_fields": ["ionFlux"]} if extended else {"metrics": ["ionFlux"]},
        selected(run("A"), run("B")),
    )
    contract = ComparisonResultV3 if extended else ComparisonResultV2
    condition = next(o for o in result["observations"] if o["source"]["metric"] == "pressure")
    condition["source"]["key"] = "unknown-run"
    with pytest.raises(ValidationError, match="observation metric mismatch"):
        contract.model_validate(result)
    condition["source"].update(key="R1", kind="summary")
    with pytest.raises(ValidationError, match="observation metric mismatch"):
        contract.model_validate(result)


def test_bounded_evidence_keeps_complete_condition_citations_for_each_retained_run():
    from kplasma_agent.explanations.answers import answer_evidence

    result = compare_selected({"metrics": ["ionFlux"]}, selected(*(run(f"ARTIFICIAL-{i}") for i in range(150))))
    evidence = answer_evidence(result)
    assert len(evidence["observations"]) <= 80
    assert 0 < len(evidence["runs"]) < 150
    for row in evidence["runs"]:
        fields = {o["source"]["metric"] for o in evidence["observations"]
                  if o["source"]["kind"] == "run" and o["source"]["key"] == row["key"]}
        assert fields == {"ionFlux", "pressure", "sourcePower", "biasPower"}


def test_repair_feedback_identifies_empty_text_missing_evidence_and_unknown_ids():
    from kplasma_agent.explanations.answers import comparison_repair_feedback

    result = compare_selected({}, selected(run("A"), run("B")))
    draft = {
        "observationIds": ["unknown"],
        "interpretations": [
            {"text": "조건에 대한 설명", "observationIds": [], "assumptions": []},
            {"text": " ", "observationIds": ["O1"], "assumptions": ["최대 RF 위상은 0.25 RF cycle입니다."]},
        ],
        "limitations": [],
    }
    feedback = comparison_repair_feedback(draft, result)
    assert feedback == {
        "interpretationsMissingEvidence": [1],
        "interpretationsWithBlankText": [2],
        "unknownObservationIds": ["unknown"],
        "numericRestatementFields": ["interpretations[1].assumptions[0]"],
        "rejectedDraft": draft,
    }


@pytest.mark.parametrize("error_code", ["ANSWER_OBSERVATION_MISMATCH", "ANSWER_NUMERIC_RESTATEMENT"])
def test_graph_repairs_condition_citations_without_repeating_data_lookup(error_code):
    from test_comparison_recovery import Backend, Model, claim
    from kplasma_agent.config import Settings
    from kplasma_agent.graphs.v1 import build_graph

    class RepairingModel(Model):
        def generate(self, prompt, payload, cls, **kwargs):
            self.answer_calls += 1
            if self.answer_calls == 1:
                ids = [] if error_code == "ANSWER_OBSERVATION_MISMATCH" else ["O1"]
                text = "압력 조건은 같습니다." if not ids else "압력은 4 mTorr입니다."
            else:
                assert payload["repair_error"] == error_code
                feedback = payload["repair_feedback"]
                assert feedback["rejectedDraft"]["interpretations"][0]["text"]
                if error_code == "ANSWER_OBSERVATION_MISMATCH":
                    assert feedback["interpretationsMissingEvidence"] == [1]
                else:
                    assert feedback["numericRestatementFields"] == ["interpretations[0].text"]
                ids = [o["id"] for o in payload["evidence"]["observations"]
                       if o["source"]["metric"] == "pressure"]
                assert len(ids) == 2
                text = "압력 조건은 같습니다."
            return {"observationIds": ["O1"], "interpretations": [{
                "text": text, "observationIds": ids, "assumptions": [],
            }], "limitations": []}, {}

    backend, model = Backend(), RepairingModel()
    request = claim()
    state = build_graph(model, backend, Settings(), None).invoke({
        "request_id": request["request"]["requestId"],
        "question": request["request"]["question"], "context": request["context"], "input_history": [],
    })
    assert model.answer_calls == 2
    assert model.selection_calls == backend.reads == 1
    assert state["answer"]["answerSnapshot"]["answer"]["status"] == "COMPLETE"
    assert state["result"]["metricIds"] == ["ionFlux"]


@pytest.mark.parametrize(
    "text",
    [
        "R1을 기준으로 보면 플럭스가 더 큽니다.",
        "R2를 기준 Run으로 해석했습니다.",
        "Relative to baseline R1, flux rises.",
    ],
)
def test_answer_cannot_invent_a_baseline_in_an_unbased_pair(text):
    result = compare_selected({"metrics": ["ionFlux"]}, selected(run("A", flux=2), run("B", flux=4)))
    draft = {
        "observationIds": ["O1"],
        "interpretations": [{"text": text, "observationIds": ["O1"], "assumptions": []}],
        "limitations": [],
    }
    with pytest.raises(DomainError, match="ANSWER_BASELINE_MISMATCH"):
        validate_answer(draft, result)


def test_many_runs_keep_complete_saved_values_but_bound_model_evidence():
    import copy
    import json
    from kplasma_agent.explanations.answers import answer_evidence

    result = compare_selected(
        {"metrics": ["ionFlux", "meanIonEnergy", "iedWidth"]},
        selected(*(run(f"ARTIFICIAL-{i}") for i in range(150))),
    )
    # A full source manifest belongs in the saved result, not the model context.
    result["outputs"] = [
        {"ref":row["ref"], "outputId":"current", "sourceCount":1001,
         "status":"AVAILABLE", "reason":None, "extrema":{},
         "sourceIntegrity":"synthetic-only-" * 100}
        for row in result["runs"]
    ]
    before = copy.deepcopy(result)
    evidence = answer_evidence(result)
    assert result == before
    assert len(result["runs"]) == len(evidence["selection"]) == 150
    assert len(json.dumps(evidence, ensure_ascii=False)) <= 60000
    assert len(evidence["observations"]) <= 80
    assert "outputs" not in evidence and "sourceIntegrity" not in str(evidence)
    allowed = {item["id"] for item in result["observations"]}
    assert all(item["id"] in allowed for item in evidence["observations"])
    assert evidence["omittedEvidence"]["observationCount"] > 0
