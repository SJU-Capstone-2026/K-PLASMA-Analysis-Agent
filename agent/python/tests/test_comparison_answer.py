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
