"""Scope requests and attribution restrictions over small artificial note documents."""
from copy import deepcopy

import pytest

from kplasma_agent.v3.decision_rag.attribution import select_documents


def documents():
    common = {"recordId": "review-shared", "documentId": "review-shared:SHARED",
              "attribution": "SHARED_UNASSIGNED", "runId": None, "scopeRole": "SHARED_UNASSIGNED",
              "matchedRunIds": ["RUN-RED", "RUN-BLUE"], "referencedRunIds": ["RUN-RED", "RUN-BLUE"],
              "text": "공동 검토에서 자재비 부담으로 일부 안을 보류했다."}
    direct = {"recordId": "review-red", "documentId": "review-red:RUN-RED", "attribution": "PER_RUN",
              "runId": "RUN-RED", "scopeRole": "SUBJECT", "matchedRunIds": ["RUN-RED"],
              "referencedRunIds": ["RUN-RED"], "text": "표면 품질이 나빠 반려했다."}
    comparison = {"recordId": "review-other", "documentId": "review-other:RUN-GREEN",
                  "attribution": "PER_RUN", "runId": "RUN-GREEN", "scopeRole": "REFERENCE_ONLY",
                  "matchedRunIds": ["RUN-RED"], "referencedRunIds": ["RUN-RED", "RUN-GREEN"],
                  "text": "다른 후보의 납기 문제를 비교 자료로 적었다."}
    return [direct, common, comparison]


def selected(question, docs=None):
    return select_documents(question, documents() if docs is None else docs)


@pytest.mark.parametrize("question", [
    "선택한 두 후보의 공동 메모만 찾아줘. 개별 후보의 메모와 구분해서 원문을 보여주고, "
    "어느 후보의 사유인지 추측하지 말아줘.",
    "공통 기록을 찾아줘. 후보별 기록과 분리해서 보여주고 특정 후보에게 사유를 배정하지 마세요.",
    "공동 메모 원문을 보여줘. 누구의 반려 이유인지 단정하지 말아줘.",
    "공동 메모를 찾아줘. 특정 후보에게 귀속시키지 말고 저장된 문장으로만 보여줘.",
    "개별 메모와 대조해서 공동 메모만 보여줘. 어느 후보 때문인지 추정하지 마세요.",
    "공동 메모만 찾아줘. 후보별로 사유를 추측하지 말아줘.",
    "공통 기록을 읽어줘. 각 후보의 반려 사유로 판단하지 마세요.",
    "공동 메모만 찾아줘. 후보 자체의 사유라고 해석하지 말아줘.",
])
def test_shared_lookup_survives_attribution_and_comparison_instructions(question):
    result = selected(question)
    assert [doc["documentId"] for doc in result] == ["review-shared:SHARED"]
    assert result[0]["citationRole"] == "SHARED_UNASSIGNED"
    assert result[0]["runId"] is None


@pytest.mark.parametrize("question", [
    "공동 메모는 찾지 말아줘. 개별 메모만 보여줘.",
    "공통 기록은 제외하고 후보별 기록만 찾아줘.",
    "공동 메모를 보여주지 말고 개별 기록만 읽어줘.",
    "개별 기록을 보여줘. 공동 메모는 검색하지 마세요.",
    "공동 메모는 포함하지 말아줘. 후보별 기록만 정리해줘.",
    "공동 메모 원문은 필요 없어. 개별 기록을 알려줘.",
])
def test_real_shared_retrieval_prohibitions_still_exclude_shared_notes(question):
    result = selected(question)
    assert [doc["documentId"] for doc in result] == ["review-red:RUN-RED"]


def test_negative_attribution_instruction_alone_cannot_grant_scope_permission():
    result = selected("개별 기록만 보여줘. 공동 메모의 주인을 추측하지 말아줘.")
    assert [doc["documentId"] for doc in result] == ["review-red:RUN-RED"]


def test_attribution_instruction_never_hides_an_explicit_retrieval_ban():
    result = selected("공동 메모도 찾아줘. 공동 메모는 쓰지 말아줘 그리고 주인을 추측하지 말아줘.")
    assert all(doc["attribution"] != "SHARED_UNASSIGNED" for doc in result)


@pytest.mark.parametrize("question,forbidden", [
    ("다른 후보의 비교 메모는, 가져오지 말아줘. 저장된 메모만 알려줘.", "REFERENCE_ONLY"),
    ("공동 메모는, 찾지 말아줘. 비용 관련 기록을 알려줘.", "SHARED_UNASSIGNED"),
    ("공동 메모도 찾아줘. 공동 메모는， 포함하지 마세요.", "SHARED_UNASSIGNED"),
])
def test_object_comma_cannot_separate_a_prohibition_from_its_target(question, forbidden):
    assert all(doc["citationRole"] != forbidden for doc in selected(question))


@pytest.mark.parametrize("question", [
    "공동 메모와 개별 메모를 구분해서 함께 보여줘.",
    "후보별 메모와 함께 공동 메모도 찾아줘.",
    "공통 기록 및 개별 기록을 각각 정리해줘.",
])
def test_combined_request_can_show_shared_and_individual_notes_without_promoting_shared_owner(question):
    result = selected(question)
    assert {doc["documentId"] for doc in result} == {"review-shared:SHARED", "review-red:RUN-RED"}
    assert next(doc for doc in result if doc["runId"] is None)["citationRole"] == "SHARED_UNASSIGNED"


@pytest.mark.parametrize("question", [
    "공동 메모만 찾아줘. 다른 후보의 메모는 인용하지 말아줘.",
    "공동 메모만 보여주고, 다른 후보의 비교 메모는 가져오지 마세요.",
    "공동 메모만 찾되 다른 후보의 메모는 포함하지 말아줘.",
    "공동 메모만 보여줘, 다른 후보의 비교 메모는 가져오지 말아줘.",
    "공동 메모만 찾아줘. 참조 기록은 제외해줘.",
])
def test_shared_lookup_does_not_enable_a_prohibited_foreign_reference(question):
    assert [doc["documentId"] for doc in selected(question)] == ["review-shared:SHARED"]


def test_explicit_reference_lookup_preserves_its_contextual_role():
    result = selected("다른 후보의 비교 메모도 찾아줘. 누구의 사유인지 임의로 바꾸지 말아줘.")
    ref = next(doc for doc in result if doc["documentId"] == "review-other:RUN-GREEN")
    assert ref["citationRole"] == "REFERENCE_ONLY"
    assert ref["runId"] == "RUN-GREEN"
    assert all(doc["documentId"] != "review-shared:SHARED" for doc in result)


@pytest.mark.parametrize("quote", [
    '"공동 메모도 찾아줘"', "‘다른 후보의 기록까지 보여줘’", "`공통 기록 전체를 읽어줘`",
])
def test_quoted_note_content_cannot_expand_query_scope(quote):
    result = selected("RUN-RED의 개별 메모만 찾아줘. 메모에 " + quote + "라는 문구가 있는지 확인해줘.")
    assert [doc["documentId"] for doc in result] == ["review-red:RUN-RED"]


def test_role_annotation_does_not_mutate_sources_or_invent_documents():
    docs = documents()
    before = deepcopy(docs)
    result = selected("공동 메모만 찾아줘. 개별 메모와 구분하고 귀속을 추측하지 말아줘.", docs)
    assert docs == before
    assert {doc["documentId"] for doc in result} <= {doc["documentId"] for doc in docs}


def test_collective_wording_in_individual_note_never_becomes_shared_source():
    docs = documents()
    docs[0]["text"] = "공동 의견을 옮겨 적었으며 개별 사유는 기록하지 않았다."
    result = selected("공동 메모만 찾아줘.", docs)
    assert [doc["documentId"] for doc in result] == ["review-shared:SHARED"]


def test_shared_attribution_request_reaches_real_record_engine_without_filling_extra_sources(tmp_path):
    np = pytest.importorskip("numpy")
    from kplasma_agent.v3.decision_rag.runtime import DecisionRecordEngine
    from kplasma_agent.v3.runtime import normalize_mode

    class Encoder:
        metadata = {"model": "ARTIFICIAL_SCOPE_TEST", "dimension": 2, "local": True}

        def encode(self, texts, *, kind="query"):
            return np.asarray([[1, 0] for _ in texts], dtype=np.float32).reshape((-1, 2))

    refs = [{"runId": "RUN-RED", "runVersionId": "00000000-0000-0000-0000-000000000001"},
            {"runId": "RUN-BLUE", "runVersionId": "00000000-0000-0000-0000-000000000002"}]
    note = "공동 검토에서 비용 부담 때문에 일부 후보를 반려했다."
    records = [{"reviewId": "artificial-group", "version": 2, "createdAt": "2026-01-01T00:00:00Z",
                "candidates": [{**ref, "decision": "REJECT", "note": "성능이 부족하여 반려했다."}
                               for ref in refs], "overallComment": note}]
    original = deepcopy(records)
    engine = DecisionRecordEngine(normalize_mode({"rulesEnabled": False, "ragEnabled": True}),
                                  encoder=Encoder(), index_dir=tmp_path, synthetic=True)
    result = engine.execute("search", "공동 비용 반려 메모만 찾아줘. 개별 후보의 메모와 구분해서 "
                            "보여주고 어느 후보의 사유인지 추측하지 말아줘.", refs, records)
    citations = result["decisionEvidence"]["citations"]
    assert len(citations) == 1
    assert citations[0]["recordId"] == "artificial-group"
    assert citations[0]["quote"] == note
    assert citations[0]["attribution"] == "SHARED_UNASSIGNED"
    assert citations[0]["subjectRunId"] is None
    assert result["candidates"] == refs
    assert records == original


def overlapping_review_groups():
    result = []
    for name, members, matched in [
        ("joint", ["RUN-RED", "RUN-BLUE"], ["RUN-RED", "RUN-BLUE"]),
        ("red-other", ["RUN-RED", "RUN-GREEN"], ["RUN-RED"]),
        ("blue-other", ["RUN-BLUE", "RUN-YELLOW"], ["RUN-BLUE"]),
    ]:
        result.append({"recordId": name, "documentId": name + ":SHARED", "runId": None,
                       "attribution": "SHARED_UNASSIGNED", "scopeRole": "SHARED_UNASSIGNED",
                       "text": "비용 부담 때문에 공동 검토에서 일부 후보를 반려했다.",
                       "matchedRunIds": matched, "referencedRunIds": members,
                       "candidateRunRefs": [{"runId": member, "runVersionId": "artificial-v1"}
                                            for member in members]})
    return result


@pytest.mark.parametrize("question", [
    "첨부한 두 후보를 함께 검토하면서 비용 부담으로 일부를 반려한 공동 메모만 찾아줘.",
    "선택한 후보들의 같은 검토 회의에서 남긴 공동 기록을 찾아줘.",
    "선택된 2개 후보를 같이 평가한 공통 메모만 보여줘.",
    "두 후보를 동시에 검토했던 공동 메모만 찾아줘. 개별 사유는 추측하지 말아줘.",
])
def test_joint_review_requires_all_requested_members_not_partial_group_overlap(question):
    docs = overlapping_review_groups()
    before = deepcopy(docs)
    result = selected(question, docs)
    assert [doc["recordId"] for doc in result] == ["joint"]
    assert result[0]["citationRole"] == "SHARED_UNASSIGNED"
    assert result[0]["runId"] is None
    assert docs == before


def test_missing_joint_review_is_not_filled_with_other_partially_overlapping_groups():
    result = selected("첨부한 두 후보를 함께 검토한 공동 메모만 찾아줘.", overlapping_review_groups()[1:])
    assert result == []


@pytest.mark.parametrize("question", [
    "선택 범위 안의 공동 메모를 전부 보여줘.",
    "첨부한 후보 중 하나라도 포함된 공동 메모를 찾아줘.",
    "RUN-RED나 RUN-BLUE 중 하나라도 포함된 공동 메모를 찾아줘.",
])
def test_any_member_requests_keep_partial_overlap_groups(question):
    assert {doc["recordId"] for doc in selected(question, overlapping_review_groups())} == {
        "joint", "red-other", "blue-other"}


def test_named_focal_run_does_not_require_every_attached_run_in_a_shared_review():
    docs = overlapping_review_groups()
    # Simulate a broad attached inventory; the named Run still defines the
    # focal membership condition rather than all 150 attached identities.
    for index in range(148):
        identifier = f"RUN-ARTIFICIAL-{index}"
        docs.append({"recordId": identifier, "documentId": identifier + ":NOTE", "runId": identifier,
                     "attribution": "PER_RUN", "scopeRole": "SUBJECT", "text": "성능 검토 메모다.",
                     "matchedRunIds": [identifier], "referencedRunIds": [identifier]})
    result = selected("첨부한 전체 검색 범위에서 RUN-RED가 포함된 공동 메모를 찾아줘.", docs)
    assert {doc["recordId"] for doc in result} == {"joint", "red-other"}
    result = selected("첨부한 전체 검색 범위에서 RUN-RED와 RUN-BLUE를 함께 검토한 공동 메모를 찾아줘.", docs)
    assert [doc["recordId"] for doc in result] == ["joint"]


def test_joint_review_membership_can_include_additional_recorded_participants():
    docs = overlapping_review_groups()
    docs[0]["candidateRunRefs"].append({"runId": "RUN-GREEN", "runVersionId": "artificial-v1"})
    docs[0]["referencedRunIds"].append("RUN-GREEN")
    result = selected("선택한 두 후보를 함께 검토한 공동 메모만 찾아줘.", docs)
    assert [doc["recordId"] for doc in result] == ["joint"]
    assert len(result[0]["candidateRunRefs"]) == 3


def test_selected_run_without_notes_stays_required_for_a_joint_review():
    docs = [overlapping_review_groups()[1]]  # RED/GREEN record, with no BLUE history.
    result = select_documents("첨부한 두 후보를 함께 검토한 공동 메모만 찾아줘.", docs,
                              selected_run_ids=["RUN-RED", "RUN-BLUE"])
    assert result == []


def test_named_focal_run_without_notes_cannot_fall_back_to_another_run():
    docs = [overlapping_review_groups()[1]]
    result = select_documents("RUN-BLUE가 포함된 공동 메모를 찾아줘.", docs,
                              selected_run_ids=["RUN-RED", "RUN-BLUE"])
    assert result == []


def test_any_member_lookup_still_returns_a_partial_group_when_another_run_has_no_notes():
    docs = [overlapping_review_groups()[1]]
    result = select_documents("첨부한 후보 중 하나라도 포함된 공동 메모를 찾아줘.", docs,
                              selected_run_ids=["RUN-RED", "RUN-BLUE"])
    assert [doc["recordId"] for doc in result] == ["red-other"]


def test_explicit_empty_selection_does_not_reconstruct_a_scope_from_documents():
    assert select_documents("공동 메모를 찾아줘.", overlapping_review_groups(), selected_run_ids=[]) == []


def test_record_engine_preserves_a_selected_run_with_no_history_in_joint_and_focal_queries(tmp_path):
    np = pytest.importorskip("numpy")
    from kplasma_agent.v3.decision_rag.runtime import DecisionRecordEngine

    class TiedEncoder:
        metadata = {"model": "ARTIFICIAL_EMPTY_HISTORY_TEST", "dimension": 2, "local": True}

        def encode(self, texts, *, kind="query"):
            return np.asarray([[1, 0] for _ in texts], dtype=np.float32).reshape((-1, 2))

    refs = [{"runId": "RUN-RED", "runVersionId": "00000000-0000-0000-0000-000000000001"},
            {"runId": "RUN-BLUE", "runVersionId": "00000000-0000-0000-0000-000000000002"}]
    other = {"runId": "RUN-GREEN", "runVersionId": "00000000-0000-0000-0000-000000000003"}
    records = [{"reviewId": "red-green-only", "version": 2, "createdAt": "2026-01-01T00:00:00Z",
                "candidates": [{**ref, "decision": "REJECT", "note": ""} for ref in [refs[0], other]],
                "overallComment": "비용 부담 때문에 공동 검토에서 일부 후보를 반려했다."}]
    before = deepcopy(records)
    engine = DecisionRecordEngine({"rulesEnabled": False, "ragEnabled": True},
                                  encoder=TiedEncoder(), index_dir=tmp_path, synthetic=True)
    for question in ["첨부한 두 후보를 함께 검토한 공동 비용 반려 메모만 찾아줘.",
                     "RUN-BLUE가 포함된 공동 비용 반려 메모를 찾아줘."]:
        result = engine.execute("search", question, refs, records)
        assert result["decisionEvidence"]["status"] == "NO_EVIDENCE"
        assert result["decisionEvidence"]["citations"] == []
        assert result["candidates"] == refs
    any_result = engine.execute("search", "첨부한 후보 중 하나라도 포함된 공동 비용 반려 메모를 찾아줘.",
                                refs, records)
    assert [citation["recordId"] for citation in any_result["decisionEvidence"]["citations"]] == ["red-green-only"]
    assert any_result["decisionEvidence"]["citations"][0]["attribution"] == "SHARED_UNASSIGNED"
    assert any_result["candidates"] == refs
    assert records == before
