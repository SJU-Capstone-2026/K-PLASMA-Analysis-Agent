"""Artificial proof-state contrasts; no model, network, or physical data fixtures."""
import pytest

from kplasma_agent.v3.decision_rag.evidence_selection import _request_analysis_text, assess_requested_evidence
from kplasma_agent.v3.decision_rag.support import _active_request, supports_requested_evidence


def supported(question, note):
    return assess_requested_evidence(question, {
        "text": note, "attribution": "PER_RUN", "citationRole": "PER_RUN",
        "runId": "RUN-ARTIFICIAL", "decision": "REJECT",
    }).supported


PROOF_QUERY = (
    "압력 상승이 IED 폭 증가를 일으킨 인과관계를 검증 완료한 기록을 찾아줘. "
    "비용 반려나 성능 미달 메모는 그 증거로 쓰지 말아줘."
)


@pytest.mark.parametrize("note", [
    "성능이 부족하여 반려했다.",
    "비용이 높아서 반려했다.",
    "압력 상승과 IED 폭 증가의 인과관계는 아직 검증하지 못했다.",
    "압력 상승과 IED 폭 증가의 인과관계 검증 자료를 기다린다.",
    "압력 상승과 IED 폭 증가의 인과관계는 추정이며 검증 완료 여부는 불명확하다.",
    "가격 협상은 확인 완료했다. 압력 상승과 IED 폭 증가의 인과관계는 미검증이다.",
    "압력 상승과 IED 폭 증가의 인과관계에 관한 문서 분석을 완료했다.",
    "압력 상승과 IED 폭 증가의 인과관계는 다음 달에 검증할 예정이다.",
])
def test_verified_causality_does_not_accept_related_or_unverified_notes(note):
    assert not supported(PROOF_QUERY, note)


@pytest.mark.parametrize("question,note", [
    (PROOF_QUERY, "압력 상승 때문에 IED 폭이 증가한 인과관계를 검증 완료했다."),
    ("압력 증가와 IED 폭 확대 사이 인과관계를 입증한 메모만 보여줘.",
     "압력 증가가 IED 폭 확대를 유발한 인과관계를 실험으로 입증했다."),
    ("물리 원인을 검증한 기록을 찾아줘.", "물리 원인 검증을 완료했다."),
    ("물리 원인을 검증 완료한 기록을 찾아줘.", "물리 원인 검증은 완료했다."),
    (PROOF_QUERY, "압력 상승으로 인해 IED 폭이 증가한 인과관계를 검증 완료했다."),
    (PROOF_QUERY, "IED 폭 증가의 원인은 압력 상승이라는 인과관계를 검증 완료했다."),
    (PROOF_QUERY, "압력 상승이 IED 폭 증가의 원인이라는 인과관계를 검증 완료했다."),
    (PROOF_QUERY, "IED 폭 증가를 압력 상승이 일으킨 인과관계를 검증 완료했다."),
    ("압력과 이온 에너지 분포 폭 사이 인과관계를 검증한 기록을 찾아줘.",
     "압력과 IED 폭 사이 인과관계를 검증 완료했다."),
    ("압력 상승이 IED 폭 증가를 일으킨 인과관계를 검증 완료한 기록을 찾아줘.",
     "압력 상승이 IED 폭 증가를 일으킨 인과관계를 조사했다. 해당 인과관계의 검증을 완료했다."),
])
def test_explicit_completed_proof_is_still_retrievable(question, note):
    assert supported(question, note)


@pytest.mark.parametrize("note", [
    "압력 상승이 IED 폭 감소를 일으킨 인과관계를 검증 완료했다.",
    "압력 감소가 IED 폭 증가를 일으킨 인과관계를 검증 완료했다.",
    "IED 폭 증가가 압력 상승을 일으킨 인과관계를 검증 완료했다.",
    "압력 상승의 원인은 IED 폭 증가라는 인과관계를 검증 완료했다.",
    "표면 오염과 막 두께 사이 인과관계를 검증 완료했다.",
    "압력 상승으로 IED 폭이 증가했다는 관찰이다. 견적 검토는 확인 완료했다.",
])
def test_completed_proof_must_belong_to_requested_relation(note):
    assert not supported(PROOF_QUERY, note)


def test_ied_width_name_does_not_also_establish_a_separate_mean_energy_claim():
    question = "평균 에너지 및 이온 에너지 분포 폭 변화의 인과관계를 검증 완료한 기록을 찾아줘."
    assert not supported(question, "이온 에너지 분포 폭 변화의 인과관계를 검증 완료했다.")
    assert supported(question, "평균 에너지 및 이온 에너지 분포 폭 변화의 인과관계를 검증 완료했다.")


@pytest.mark.parametrize("question,note,expected", [
    ("압력과 IED 폭의 인과관계가 미검증이라고 적힌 메모를 찾아줘.",
     "압력과 IED 폭의 인과관계는 미검증이다.", True),
    ("압력과 IED 폭의 인과관계가 미검증이라고 적힌 메모를 찾아줘.",
     "압력과 IED 폭의 인과관계를 검증 완료했다.", False),
    ("물리 원인 자료를 기다리는 보류 메모를 찾아줘.",
     "물리 원인 자료를 기다리며 검토를 보류한다.", True),
    ("압력과 IED 폭 인과관계의 검증 여부와 한계를 보여줘.",
     "압력과 IED 폭 인과관계의 분석 자료가 아직 없어 확인할 수 없다.", True),
    ("압력과 IED 폭 인과관계의 검증 완료 여부를 보여줘.",
     "압력과 IED 폭 인과관계는 아직 검증하지 않았다.", True),
    ("비용 반려 메모와 물리 원인 검증 완료 기록을 각각 찾아줘.",
     "비용이 높아서 반려했다.", True),
    ("비용 반려 메모와 물리 원인 검증 완료 기록을 각각 찾아줘.",
     "물리 원인 검증을 완료했다.", True),
    ("비용 반려 메모와 물리 원인 검증 완료 기록을 찾아줘.",
     "비용이 높아서 반려했다.", True),
    ("비용 반려 메모와 물리 원인 검증 완료 기록을 찾아줘.",
     "물리 원인 검증을 완료했다.", True),
    ("비용 반려와 물리 원인 검증 완료를 하나의 기록에서 동시에 확인해줘.",
     "비용이 높아서 반려했다.", False),
    ("비용 반려와 물리 원인 검증 완료를 하나의 기록에서 동시에 확인해줘.",
     "비용이 높아 반려했다. 물리 원인 검증을 완료했다.", True),
])
def test_negative_pending_and_collection_requests_keep_their_own_meaning(question, note, expected):
    assert supported(question, note) is expected


@pytest.mark.parametrize("excluded", [
    "단순 비용 반려는 근거로 사용하지 말아줘.",
    "성능 미달 메모를 검증 근거로 취급하지 마.",
    "원인 자료 대기 기록은 포함하지 말아줘.",
    "관련 단어만 있는 메모는 가져오지 말아줘.",
])
def test_excluded_examples_do_not_become_requested_topics(excluded):
    primary = "물리 원인을 검증 완료한 기록을 찾아줘."
    assert _active_request(primary + " " + excluded) == _active_request(primary)


def test_same_sentence_prohibition_retains_the_positive_request():
    question = "물리 원인을 입증한 기록을 찾아줘, 단순 성능 메모는 인용하지 말아줘."
    assert supported(question, "물리 원인을 입증했다.")
    assert not supported(question, "성능이 미달하여 반려했다.")


def test_coordinated_prohibition_without_comma_retains_positive_request():
    question = "물리 원인을 입증한 기록을 찾아주고 성능 메모는 인용하지 말아줘."
    assert supported(question, "물리 원인을 입증했다.")
    assert not supported(question, "성능이 미달하여 반려했다.")


@pytest.mark.parametrize("excluded", [
    "비용 문제가 없다는 기록이나 원가가 미확정인 기록, 보류 기록은 가져오지 말아줘.",
    "성능 미달 메모, 원인 자료 대기 메모, 미검증 기록은 인용하지 마세요.",
    "보류 기록, 원가 미확정 기록, 비용과 무관한 기록은 제외해줘.",
])
def test_final_prohibition_applies_to_the_whole_object_list(excluded):
    primary = "비용 부담이 확정된 반려 메모만 찾아줘."
    assert _active_request(primary + " " + excluded) == _active_request(primary)
    assert supported(primary + " " + excluded, "비용이 높아서 반려했다.")
    assert not supported(primary + " " + excluded, "원가가 높은지 확인 중이며 반려 사유는 미정이다.")


@pytest.mark.parametrize("question", [
    "물리 원인을 입증한 기록을 찾아줘, 성능 미달 기록, 비용 반려 기록은 쓰지 말아줘.",
    "물리 원인을 입증한 기록을 찾아주고 성능 미달 기록, 비용 반려 기록은 쓰지 말아줘.",
    "성능 미달 기록, 비용 반려 기록은 쓰지 말아줘, 물리 원인을 입증한 기록을 찾아줘.",
])
def test_action_boundaries_preserve_positive_request_beside_a_prohibited_list(question):
    assert supported(question, "물리 원인을 입증했다.")
    assert not supported(question, "비용이 높아서 반려했다.")


def test_object_comma_is_not_a_new_instruction():
    assert _active_request("성능 미달 기록, 비용 반려 기록은 가져오지 말아줘.") == ""
    assert _active_request("성능 미달 기록은, 근거로 쓰지 말아줘.") == ""


def test_positive_object_list_keeps_all_requested_states():
    active = _active_request("원가가 미확정인 기록, 보류 기록을 각각 찾아줘.")
    assert "미확정" in active and "보류" in active


@pytest.mark.parametrize("presentation", [
    "후보별 메모와 구분해서 원문을 보여주고, 어느 후보의 비용 사유인지 추측하지 말아줘.",
    "원문을 보여주고, 공동 가격 사유를 특정 후보에게 배정하지 마세요.",
    "원문과 출처를 정리해줘. 비용 사유의 주인을 단정하지 말아줘.",
])
def test_attribution_and_presentation_are_not_alternative_factual_requests(presentation):
    question = "함께 검토한 후보 중 비용 문제로 일부를 반려했다는 공동 메모만 찾아줘. " + presentation
    def assessment(note):
        return assess_requested_evidence(question, {
            "text": note, "attribution": "SHARED_UNASSIGNED", "citationRole": "SHARED_UNASSIGNED",
            "runId": None, "decision": None,
        }).supported
    assert assessment("비용 문제로 공동 검토 후보의 일부를 반려했다.")
    assert not assessment("가격이 적정한 후보와 추가 확인할 후보를 함께 검토했다.")


def test_scope_only_original_text_lookup_is_still_allowed():
    question = "공동 메모의 원문을 보여줘. 후보별 메모와 구분해서 정리해줘."
    assert _request_analysis_text(_active_request(question)).strip()
    assert supported(question, "가격이 적정한 후보와 추가 확인할 후보를 함께 검토했다.")


def test_factual_statement_about_attribution_is_not_dropped_as_an_instruction():
    query = "비용 사유의 주인을 추측하지 말라는 문장이 적힌 메모를 찾아줘."
    assert "추측하지 말라는" in _request_analysis_text(_active_request(query))


def test_declined_topic_does_not_add_a_mandatory_proof_requirement():
    question = "비용 반려 메모를 찾아줘. 물리 원인 검증 여부는 필요 없어."
    assert supported(question, "비용이 높아 반려했다.")
    assert not supported(question, "물리 원인 검증을 완료했다.")


def test_factual_negation_is_not_a_prohibited_action():
    question = "물리 원인을 검증하지 않았다는 메모를 찾아줘."
    assert "검증하지 않았다는" in _active_request(question)
    assert supported(question, "물리 원인을 아직 검증하지 않았다.")


def test_literal_string_request_does_not_claim_that_literal_is_verified():
    question = "'물리 원인 검증 완료'라는 문자열이 들어 있는 메모를 찾아줘."
    assert supported(question, "물리 원인 검증 완료라고 잘못 적었으며 실제 검증은 하지 않았다.")


@pytest.mark.parametrize("note,expected", [
    ("압력과 IED 폭 인과관계를 검증 완료했다.", True),
    ("압력과 IED 폭 인과관계는 미검증이다.", True),
    ("비용이 높아서 반려했다.", False),
])
def test_requested_proof_state_collection_keeps_shared_relation(note, expected):
    question = "압력과 IED 폭 인과관계의 검증 완료 기록과 미검증 기록을 각각 찾아줘."
    assert supported(question, note) is expected


def test_empty_positive_request_does_not_make_all_notes_eligible():
    assert not supports_requested_evidence("성능 메모는 가져오지 말아줘.", "성능이 부족하다.")
    assert not supported("성능 메모는 가져오지 말아줘.", "성능이 부족하다.")


def test_real_search_pipeline_keeps_completed_proof_and_discards_distractors(tmp_path):
    from uuid import UUID

    from kplasma_agent.v3.decision_rag.runtime import DecisionRecordEngine

    np = pytest.importorskip("numpy")

    class ArtificialEncoder:
        metadata = {"model": "ARTIFICIAL_PROOF_UNIT_TEST", "dimension": 3, "local": True}

        def encode(self, texts, *, kind="query"):
            return np.asarray([[1, 0, 0] for _ in texts], dtype=np.float32).reshape((-1, 3))

    ref = {"runId": "RUN-ARTIFICIAL", "runVersionId": str(UUID(int=101))}
    notes = {
        "verified": "압력 상승이 IED 폭 증가를 일으킨 인과관계를 검증 완료했다.",
        "performance": "성능이 미달하여 반려했다.",
        "pending": "압력 상승과 IED 폭 증가의 인과관계 검증 자료를 기다린다.",
        "wrong-event": "압력 감소가 IED 폭 증가를 일으킨 인과관계를 검증 완료했다.",
        "cost": "비용이 높아서 반려했다.",
    }
    records = [{"reviewId": identifier, "targetRunId": ref["runId"], "targetRunRef": ref,
                "comparedRunRefs": [], "decision": "REJECT", "comment": note,
                "createdAt": "2026-01-01T00:00:00Z", "runSnapshots": [ref]}
               for identifier, note in notes.items()]
    engine = DecisionRecordEngine({"rulesEnabled": False, "ragEnabled": True},
                                  encoder=ArtificialEncoder(), index_dir=tmp_path, synthetic=True)
    outputs = engine.execute("search", PROOF_QUERY, [ref], records)
    citations = outputs["decisionEvidence"]["citations"]
    assert [citation["recordId"] for citation in citations] == ["verified"]
    assert citations[0]["quote"] == notes["verified"]
    assert outputs["candidates"] == [ref]
    assert outputs["callCounts"] == {"rules": 0, "rag": 1}

    without_proof = engine.execute("search", PROOF_QUERY, [ref], records[1:])
    assert without_proof["decisionEvidence"]["status"] == "NO_EVIDENCE"
    assert without_proof["decisionEvidence"]["citations"] == []
    assert without_proof["candidates"] == [ref]
