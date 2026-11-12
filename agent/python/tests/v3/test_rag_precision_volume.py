"""Volume regressions with artificial notes and tied vectors, not an accuracy benchmark."""
from copy import deepcopy
import hashlib
import random
from uuid import UUID

import pytest

from kplasma_agent.v3.decision_rag.live_corpus import live_corpus
from kplasma_agent.v3.decision_rag.runtime import DecisionRecordEngine


SELECTED = {"runId": "RUN-ARTIFICIAL-SELECTED", "runVersionId": str(UUID(int=301))}
COMPARISON = {"runId": "RUN-ARTIFICIAL-COMPARISON", "runVersionId": str(UUID(int=302))}


def artificial_inventory():
    """Record construction labels define the gold; no product classifier is used."""
    confirmed_notes = [
        "비용이 높아서 이 후보를 반려했다.",
        "원가가 예산 상한을 초과하여 반려했다.",
        "가격 부담 때문에 이 후보를 선정하지 않았다.",
    ]
    records = []
    expected = {}
    for index in range(100):
        identifier = str(UUID(int=1000 + index))
        common = {"reviewId": identifier, "createdAt": "2026-01-01T00:00:00Z"}
        suffix = f"\n인공 검토 식별 번호 {index}."
        if index < len(confirmed_notes):
            note = confirmed_notes[index] + suffix
            expected[identifier] = note
            records.append({**common, "targetRunId": SELECTED["runId"], "targetRunRef": SELECTED,
                            "comparedRunRefs": [], "decision": "REJECT", "comment": note})
            continue
        kind = (index - len(confirmed_notes)) % 6
        if kind == 4:
            # One shared document, with no individual candidate notes to
            # turn a collective reason into a reason for the selected Run.
            records.append({**common, "version": 2,
                            "candidates": [{**ref, "decision": "REJECT", "note": ""}
                                           for ref in (SELECTED, COMPARISON)],
                            "overallComment": "비용이 높아서 공동 검토에서 일부 후보를 반려했다." + suffix})
        elif kind == 5:
            # A genuine cost rejection, but only a comparison reference for
            # this selection: its own target must never become SELECTED.
            records.append({**common, "targetRunId": COMPARISON["runId"], "targetRunRef": COMPARISON,
                            "comparedRunRefs": [SELECTED], "decision": "REJECT",
                            "comment": "비용이 높아 다른 후보를 반려했다." + suffix})
        else:
            note, decision = [
                ("비용 문제가 없으며 성능 미달 때문에 반려했다.", "REJECT"),
                ("원가가 높은지 확인 중이며 반려 사유는 미정이다.", "REJECT"),
                ("비용 부담을 협의하며 판단을 보류한다.", "HOLD"),
                ("성능 부족이 반려 사유이며 비용은 적정하다.", "REJECT"),
            ][kind]
            records.append({**common, "targetRunId": SELECTED["runId"], "targetRunRef": SELECTED,
                            "comparedRunRefs": [], "decision": decision, "comment": note + suffix})
    random.Random(431).shuffle(records)
    return records, expected


@pytest.fixture
def volume_case(tmp_path):
    np = pytest.importorskip("numpy")

    class TiedEncoder:
        metadata = {"model": "ARTIFICIAL_TIED_VOLUME_TEST", "dimension": 3, "local": True}

        def encode(self, texts, *, kind="query"):
            # All 100 documents and both questions receive the same similarity.
            # Neither a favorable vector nor a fixed result count finds the gold.
            return np.asarray([[1, 0, 0] for _ in texts], dtype=np.float32).reshape((-1, 3))

    records, expected = artificial_inventory()
    corpus = live_corpus(records, [SELECTED], synthetic=True)
    assert len(corpus.documents) == 100
    assert len(corpus.scoped_documents([SELECTED["runId"]])) == 100
    assert len(expected) == 3
    engine = DecisionRecordEngine({"rulesEnabled": False, "ragEnabled": True},
                                  encoder=TiedEncoder(), index_dir=tmp_path, synthetic=True)
    return engine, records, expected


def test_one_hundred_tied_documents_return_only_the_three_supported_cost_rejections(volume_case):
    engine, records, expected = volume_case
    before = deepcopy(records)
    query = ("선택한 Run에서 비용 부담이 확정된 반려 기록의 후보별 메모만 찾아줘. "
             "비용 문제가 없다는 기록이나 원가가 미확정인 기록, 보류 기록은 가져오지 말아줘.")
    result = engine.execute("search", query, [SELECTED], records)
    citations = result["decisionEvidence"]["citations"]
    assert len(citations) == len(expected)
    assert {citation["recordId"] for citation in citations} == set(expected)
    assert result["retrieval"]["totalInScope"] == 100
    assert result["retrieval"]["searchableInScope"] == len(expected)
    assert result["retrieval"]["returned"] == len(expected)
    for citation in citations:
        note = expected[citation["recordId"]]
        assert citation["quote"] == note
        assert citation["sourceNoteSha256"] == hashlib.sha256(note.encode()).hexdigest()
        assert citation["attribution"] == "PER_RUN"
        assert citation["subjectRunId"] == SELECTED["runId"]
        assert citation["recordRunVersionId"] == SELECTED["runVersionId"]
    assert result["candidates"] == [SELECTED]
    assert result["callCounts"] == {"rules": 0, "rag": 1}
    assert records == before


def test_same_hundred_document_scope_returns_nothing_when_the_requested_proof_is_absent(volume_case):
    engine, records, _ = volume_case
    before = deepcopy(records)
    query = "압력 상승이 IED 폭 증가를 일으킨 인과관계를 검증 완료한 기록만 찾아줘."
    result = engine.execute("search", query, [SELECTED], records)
    assert result["retrieval"]["totalInScope"] == 100
    assert result["retrieval"]["searchableInScope"] == 0
    assert result["retrieval"]["returned"] == 0
    assert result["decisionEvidence"]["status"] == "NO_EVIDENCE"
    assert result["decisionEvidence"]["citations"] == []
    assert result["candidates"] == [SELECTED]
    assert records == before
