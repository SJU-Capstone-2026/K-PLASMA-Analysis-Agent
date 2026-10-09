import pytest
from kplasma_agent.explanations.engine import build_change_evidence, validate_explanation, ExplanationError


def comparison():
    return {
        "resultStatus": "COMPARISON_READY",
        "conditions": [
            {"field": "pressure", "baseline": 10, "target": 10, "delta": 0, "status": "AVAILABLE"}
        ],
        "metrics": [
            {
                "metric": "ionFlux",
                "baseline": 2,
                "target": 3,
                "delta": 1,
                "percentChange": 50,
                "status": "AVAILABLE",
            }
        ],
    }


def test_evidence_excludes_values_and_references_real_observations():
    packet = build_change_evidence(comparison())
    assert packet["observations"][-1] == {
        "id": "metric_ionFlux",
        "subject": "ionFlux",
        "direction": "increased",
        "available": True,
    }
    assert "baseline" not in str(packet) and "percentChange" not in str(packet)
    draft = {
        "status": "answered",
        "interpretations": [
            {
                "text": "여러 요인이 관여했을 가능성이 있습니다.",
                "observation_refs": ["metric_ionFlux"],
                "assumptions": [],
            }
        ],
        "limitations": ["원인을 확정할 수 없습니다."],
        "suggested_checks": [],
    }
    assert validate_explanation("explain_change", draft, packet)["status"] == "answered"


@pytest.mark.parametrize(
    "text", ["플럭스가 50% 늘었습니다.", "플럭스가 두 배입니다.", "https://invented.example/paper"]
)
def test_narrative_cannot_invent_numbers_or_citations(text):
    with pytest.raises(ExplanationError):
        validate_explanation(
            "explain_concept",
            {
                "status": "answered",
                "sections": [{"topic_refs": ["ionFlux"], "text": text}],
                "limitations": ["일반 지식입니다."],
            },
            {"topics": ["ionFlux"]},
        )


def test_unknown_observation_is_rejected():
    with pytest.raises(ExplanationError):
        validate_explanation(
            "explain_change",
            {
                "status": "answered",
                "interpretations": [
                    {"text": "가능한 해석입니다.", "observation_refs": ["invented"], "assumptions": []}
                ],
                "limitations": ["한계"],
                "suggested_checks": [],
            },
            build_change_evidence(comparison()),
        )


@pytest.mark.parametrize("text", [
    "제공된 관찰에서는 플럭스와 에너지가 다른 방향으로 변했습니다.",
    "change_evidence는 관찰 방향만 제공하며 인과 증거가 아닙니다.",
    "주어진 측정 데이터가 없어서 해당 Run의 차이는 판단할 수 없습니다.",
    "The provided observations suggest an increase in ion flux.",
])
def test_concept_cannot_claim_or_require_observations_that_were_not_provided(text):
    with pytest.raises(ExplanationError, match="EXPLANATION_FABRICATED_OBSERVATION"):
        validate_explanation("explain_concept", {
            "status": "answered", "sections": [{"topic_refs": ["ionFlux"], "text": text}],
            "limitations": ["일반 지식에 따른 설명입니다."],
        }, {"topics": ["ionFlux"], "aspect": "definition"})


def test_general_concept_definition_and_conditional_relationship_remain_allowed():
    draft = {"status": "answered", "sections": [{"topic_refs": ["ionFlux", "sourcePower"],
        "text": "이온 플럭스는 단위 면적당 단위 시간에 도달하는 이온 수입니다. 소스 전력이 높아지면 이온 생성이 달라질 수 있지만 관계는 운전 조건에 따라 달라집니다."}],
        "limitations": ["일반 지식에 따른 설명이며 구체적인 공정의 변화를 예측하지 않습니다."]}
    assert validate_explanation("explain_concept", draft, {"topics": ["ionFlux", "sourcePower"], "aspect": "relationship"})["status"] == "answered"


def change_draft(text):
    return {
        "status": "answered",
        "interpretations": [{"text": text, "observation_refs": ["metric_ionFlux"], "assumptions": []}],
        "limitations": ["가능한 해석이며 원인을 단정할 수 없습니다."],
        "suggested_checks": [],
    }


@pytest.mark.parametrize(
    "text",
    [
        "이번 비교에서 이온 플럭스가 감소한 것은 이온화 변화 때문일 수 있습니다.",
        "이온 플럭스의 감소는 입자 손실과 관련됐을 가능성이 있습니다.",
        "관찰된 ion flux decreased because of a possible loss mechanism.",
    ],
)
def test_opposite_observed_direction_is_rejected_even_with_valid_reference(text):
    with pytest.raises(ExplanationError, match="EXPLANATION_DIRECTION_CONTRADICTION"):
        validate_explanation("explain_change", change_draft(text), build_change_evidence(comparison()))


def test_unchanged_observation_cannot_be_described_as_an_increase():
    source = comparison()
    source["metrics"][0]["delta"] = 0
    with pytest.raises(ExplanationError, match="EXPLANATION_DIRECTION_CONTRADICTION"):
        validate_explanation(
            "explain_change",
            change_draft("이온 플럭스가 증가한 이유는 추가 확인이 필요합니다."),
            build_change_evidence(source),
        )


@pytest.mark.parametrize(
    "text",
    [
        "이온 플럭스의 증가는 이온화 효율 변화와 관련됐을 수 있습니다.",
        "입자 손실이 커지면 이온 플럭스가 감소할 수 있습니다. 이번 증가는 다른 영향도 확인해야 합니다.",
        "이온 플럭스가 감소하는 경우도 있지만, 현재 변화의 원인을 확정할 수 없습니다.",
    ],
)
def test_qualified_general_knowledge_and_matching_direction_remain_allowed(text):
    assert (
        validate_explanation("explain_change", change_draft(text), build_change_evidence(comparison()))[
            "status"
        ]
        == "answered"
    )


@pytest.mark.parametrize(
    "text",
    [
        "소스 전력이 확실한 원인입니다.",
        "입자 손실이 원인이라고 단정합니다.",
        "바이어스가 유일한 원인입니다.",
        "The cause is definitely source power.",
    ],
)
def test_causal_certainty_variants_are_rejected(text):
    with pytest.raises(ExplanationError, match="EXPLANATION_CAUSAL_CLAIM"):
        validate_explanation("explain_change", change_draft(text), build_change_evidence(comparison()))


@pytest.mark.parametrize(
    "text",
    [
        "소스 전력이 원인이라고 단정할 수 없습니다.",
        "확실한 원인이라고 볼 수 없습니다.",
        "소스 전력이 영향을 주었을 가능성이 있지만 확실하지 않습니다.",
    ],
)
def test_explicitly_negated_causal_certainty_is_allowed(text):
    assert (
        validate_explanation("explain_change", change_draft(text), build_change_evidence(comparison()))[
            "status"
        ]
        == "answered"
    )


def test_insufficient_knowledge_cannot_suggest_unvalidated_checks():
    draft = {
        "status": "insufficient_knowledge",
        "interpretations": [],
        "limitations": ["설명할 지식이 부족합니다."],
        "suggested_checks": ["전압을 확인하세요."],
    }
    with pytest.raises(ExplanationError, match="EXPLANATION_STATUS_MISMATCH"):
        validate_explanation("explain_change", draft, build_change_evidence(comparison()))


@pytest.mark.parametrize("duplicate", ["text", "reference", "assumption"])
def test_duplicate_change_entries_are_rejected(duplicate):
    draft = change_draft("가능한 해석입니다.")
    if duplicate == "text":
        draft["interpretations"].append({**draft["interpretations"][0], "text": " 가능한   해석입니다. "})
    elif duplicate == "reference":
        draft["interpretations"][0]["observation_refs"] *= 2
    else:
        draft["interpretations"][0]["assumptions"] = ["다른 조건 영향", "다른 조건 영향"]
    with pytest.raises(ExplanationError, match="EXPLANATION_DUPLICATE"):
        validate_explanation("explain_change", draft, build_change_evidence(comparison()))


@pytest.mark.parametrize("duplicate", ["section", "topic"])
def test_duplicate_concept_sections_and_topic_refs_are_rejected(duplicate):
    draft = {
        "status": "answered",
        "sections": [{"topic_refs": ["ionFlux"], "text": "입자 유량을 나타냅니다."}],
        "limitations": ["일반 지식입니다."],
    }
    if duplicate == "section":
        draft["sections"] *= 2
    else:
        draft["sections"][0]["topic_refs"] *= 2
    with pytest.raises(ExplanationError, match="EXPLANATION_DUPLICATE"):
        validate_explanation("explain_concept", draft, {"topics": ["ionFlux"]})
