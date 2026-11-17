"""Per-memo vector store (rules3-kosr): embed each memo text once, never depend on batch neighbours.

Records and encoders below are artificial; no model file is loaded.
"""
import hashlib
import os
import sqlite3
from uuid import UUID

import pytest

np = pytest.importorskip("numpy")

from kplasma_agent.v3 import decision_engines  # noqa: E402
from kplasma_agent.v3.decision_rag.index import LocalIndex, RagIndexError  # noqa: E402
from kplasma_agent.v3.decision_rag.live_corpus import live_corpus  # noqa: E402
from kplasma_agent.v3.decision_rag.vector_store import IncrementalIndex  # noqa: E402

A = {"runId": "RUN-VS-A", "runVersionId": str(UUID(int=21))}
B = {"runId": "RUN-VS-B", "runVersionId": str(UUID(int=22))}


class Encoder:
    """Deterministic per text; records every passage batch it receives."""

    def __init__(self, model="ARTIFICIAL_VS_TEST"):
        self.metadata = {"model": model, "dimension": 4, "local": True}
        self.batches = []

    def encode(self, texts, *, kind="query"):
        texts = list(texts)
        if kind == "passage":
            self.batches.append(texts)
        rows = []
        for text in texts:
            digest = hashlib.sha256((kind + text).encode()).digest()
            vector = np.frombuffer(digest[:16], dtype=np.uint8).astype(np.float32)[:4] + 1
            rows.append(vector / np.linalg.norm(vector))
        return np.asarray(rows, dtype=np.float32).reshape((-1, 4))

    def passages(self):
        return sum(len(batch) for batch in self.batches)


def record(identifier, ref, note):
    return {"reviewId": identifier, "targetRunId": ref["runId"], "targetRunRef": ref, "comparedRunRefs": [],
            "decision": "REJECT", "comment": note, "createdAt": "2026-01-01T00:00:00Z", "runSnapshots": [ref]}


RECORDS = [record("r1", A, "비용이 높아 반려했다."), record("r2", B, "성능 미달로 반려했다."),
           record("r3", A, "비용이 높아 반려했다.")]  # same text as r1


def build(records, encoder, directory, scope=(A, B)):
    return IncrementalIndex(live_corpus(records, list(scope), synthetic=True), encoder, directory)


def test_each_distinct_text_is_embedded_once_and_alone(tmp_path):
    encoder = Encoder()
    index = build(RECORDS, encoder, tmp_path)
    assert index.stats["newlyEmbedded"] == 2 and encoder.passages() == 2
    assert all(len(batch) == 1 for batch in encoder.batches)  # never batched with other memos
    assert index.vectors.shape == (3, 4)


def test_only_new_memos_are_embedded_and_scope_changes_reuse_vectors(tmp_path):
    encoder = Encoder()
    first = build(RECORDS, encoder, tmp_path)
    assert build(RECORDS, encoder, tmp_path, scope=(A,)).stats["newlyEmbedded"] == 0
    grown = build(RECORDS + [record("r4", B, "새로 추가한 메모")], encoder, tmp_path)
    assert grown.stats["newlyEmbedded"] == 1
    old = [d["documentId"] for d in first.documents]
    assert np.array_equal(first.vectors, grown.vectors[[grown.positions[i] for i in old]])


def test_vectors_are_kept_per_encoder(tmp_path):
    build(RECORDS, Encoder("MODEL-ONE"), tmp_path)
    other = Encoder("MODEL-TWO")
    assert build(RECORDS, other, tmp_path).stats["newlyEmbedded"] == 2


def test_search_matches_the_pr36_index_for_identical_vectors(tmp_path):
    encoder = Encoder()
    corpus = live_corpus(RECORDS, [A, B], synthetic=True)
    ours, theirs = IncrementalIndex(corpus, encoder, tmp_path / "a"), LocalIndex(corpus, encoder, tmp_path / "b")
    assert np.array_equal(ours.vectors, theirs.vectors)
    for question in ("비용 때문에 반려된 메모", "성능 문제"):
        assert ([d["documentId"] for d in ours.search(question, list(corpus.documents), min_score=-1.0)] ==
                [d["documentId"] for d in theirs.search(question, list(corpus.documents), min_score=-1.0)])


def test_tampered_vector_is_rejected(tmp_path):
    build(RECORDS, Encoder(), tmp_path)
    path = tmp_path / "decision-vectors.sqlite3"
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("update vectors set vector=zeroblob(16)")
    connection.close()
    with pytest.raises(RagIndexError):
        build(RECORDS, Encoder(), tmp_path)


def test_store_file_is_released_after_building(tmp_path):
    build(RECORDS, Encoder(), tmp_path)
    os.remove(tmp_path / "decision-vectors.sqlite3")  # fails on Windows if a connection were left open


def test_kosr_engine_uses_the_per_memo_store_and_rag4_does_not():
    mode = {"rulesEnabled": False, "ragEnabled": True}
    assert decision_engines.create_engine("rules3-kosr", mode).index_factory is not None
    assert decision_engines.create_engine("rag4", mode).index_factory is None
    assert decision_engines.engine_profile("rules3-kosr")["vectorStore"] == "per-text-sqlite-1"
    assert "vectorStore" not in decision_engines.engine_profile("rag4")
