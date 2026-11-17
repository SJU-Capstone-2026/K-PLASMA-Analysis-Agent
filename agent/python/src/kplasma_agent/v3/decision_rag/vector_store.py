"""Per-memo vector store for the rules3-kosr engine: each distinct memo text is embedded once.

The PR #36 LocalIndex caches one matrix per (records, scope, model) bundle, so any added memo or a
different Run scope re-embeds every memo. This index instead keeps one vector per
(encoder metadata, normalized memo text) in a local SQLite file and embeds only texts it has not
seen. Each text is encoded alone: the int8 ONNX encoders quantize per batch, so a batched vector
would depend on whichever other memos shared the batch.

The server still pins the record inventory and verifies citations; this store only replaces how
vectors are produced and kept. Search ranking is inherited unchanged from LocalIndex.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np  # type: ignore[import-not-found]

from .embedding import normalized_text
from .index import RETRIEVAL_POLICY, LocalIndex, RagIndexError

VECTOR_STORE_POLICY = "per-text-sqlite-1"
_SCHEMA = """create table if not exists vectors (
    encoder_key text not null, text_sha256 text not null, dimension integer not null,
    vector blob not null, vector_sha256 text not null, primary key (encoder_key, text_sha256))"""


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class IncrementalIndex(LocalIndex):
    # LocalIndex.__init__ is replaced on purpose; search() is reused as is.
    def __init__(self, corpus, encoder, directory: Path):  # noqa: D401
        self.encoder = encoder
        self.documents = tuple(d for d in corpus.documents if d["text"].strip())
        self.positions = {d["documentId"]: i for i, d in enumerate(self.documents)}
        dimension = int(encoder.metadata["dimension"])
        encoder_key = _sha(json.dumps(encoder.metadata, sort_keys=True, ensure_ascii=False).encode())
        keys = [_sha(normalized_text(d["text"]).encode("utf-8")) for d in self.documents]
        Path(directory).mkdir(parents=True, exist_ok=True)
        found: dict[str, np.ndarray] = {}
        # sqlite3's own context manager only commits; closing() releases the file handle as well.
        with closing(sqlite3.connect(Path(directory) / "decision-vectors.sqlite3")) as db, db:
            db.execute(_SCHEMA)
            for key in dict.fromkeys(keys):
                row = db.execute("select dimension, vector, vector_sha256 from vectors "
                                 "where encoder_key=? and text_sha256=?", (encoder_key, key)).fetchone()
                if row is None:
                    continue
                if row[0] != dimension or _sha(row[1]) != row[2]:
                    raise RagIndexError("저장된 메모 벡터의 형식 또는 해시가 일치하지 않습니다.")
                found[key] = np.frombuffer(row[1], dtype=np.float32)
            missing = [i for i, key in enumerate(keys) if key not in found]
            first = list({keys[i]: i for i in reversed(missing)}.values())  # one document per new text
            for i in first:
                vector = encoder.encode([self.documents[i]["text"]], kind="passage")[0].astype(np.float32)
                blob = vector.tobytes()
                db.execute("insert or ignore into vectors values (?, ?, ?, ?, ?)",
                           (encoder_key, keys[i], dimension, blob, _sha(blob)))
                found[keys[i]] = vector
        self.vectors = (np.vstack([found[key] for key in keys]) if keys
                        else np.empty((0, dimension), dtype=np.float32))
        if self.vectors.shape != (len(self.documents), dimension) or not np.isfinite(self.vectors).all():
            raise RagIndexError("검색 색인의 벡터 형식이 올바르지 않습니다.")
        self.fingerprint = _sha(json.dumps({"store": VECTOR_STORE_POLICY, "encoder": encoder_key,
                                            "texts": keys}, sort_keys=True).encode())
        self.stats = {"documents": len(self.documents), "uniqueTexts": len(set(keys)), "dimension": dimension,
                      "indexFingerprint": self.fingerprint, "corpusFingerprint": corpus.fingerprint,
                      "local": True, "retrievalPolicy": RETRIEVAL_POLICY, "vectorStore": VECTOR_STORE_POLICY,
                      "newlyEmbedded": len(first)}
