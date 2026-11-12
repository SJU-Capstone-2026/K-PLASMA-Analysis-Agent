"""Local dense and lexical retrieval; scope filtering precedes both rankings."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from collections import Counter

import numpy as np  # type: ignore[import-not-found]

from .embedding import file_sha256

RETRIEVAL_POLICY = "scoped-dense-lexical-recall-2"
_RUN_ID = re.compile(r"RUN-[A-Z0-9-]+", re.IGNORECASE)
_WORDS = re.compile(r"[a-z0-9]+|[가-힣]+", re.IGNORECASE)
_FILLER = re.compile(
    r"찾아(?:줘|주세요|줄래)?|보여(?:줘|주세요|줄래)?|알려(?:줘|주세요|줄래)?|"
    r"부탁(?:해|합니다)?|선택한|해당|이전|과거|판단|검토|기록|메모|근거|관련|내용|"
    r"저장된|기재된|적힌|적혀|있는|어떤|무엇|대해|대해서|해주세요|합니다|됐는지|했는지"
)


def lexical_terms(text):
    """Character grams support Korean inflections without a separate tokenizer.

    Run identifiers never influence relevance. Common retrieval instructions do
    not count as topical matches; the original text remains untouched.
    """
    clean = _FILLER.sub(" ", _RUN_ID.sub(" ", text)).lower()
    terms = []
    for word in _WORDS.findall(clean):
        if word.isascii():
            if len(word) > 1:
                terms.append(word)
            continue
        for size in (2, 3):
            terms.extend(word[i:i + size] for i in range(max(0, len(word) - size + 1)))
    return Counter(terms)


def lexical_scores(question, documents):
    """BM25 over the permitted candidates only, never outside the Run scope."""
    query = lexical_terms(question)
    counts = [lexical_terms(d["text"]) for d in documents]
    lengths = [sum(value.values()) for value in counts]
    average = max(1.0, sum(lengths) / max(1, len(lengths)))
    frequencies = Counter(term for value in counts for term in value if term in query)
    scores = []
    for value, length in zip(counts, lengths, strict=True):
        score = 0.0
        for term in query:
            frequency = value[term]
            if frequency:
                inverse = math.log(1 + (len(counts) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
                score += inverse * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average))
        scores.append(score)
    return scores


class RagIndexError(ValueError):
    code = "RAG_INDEX_INVALID"


class LocalIndex:
    def __init__(self, corpus, encoder, directory: Path):
        self.encoder = encoder
        self.documents = tuple(d for d in corpus.documents if d["text"].strip())
        self.positions = {d["documentId"]: i for i, d in enumerate(self.documents)}
        config = {"schema": "local-dense-v1", "corpus": corpus.fingerprint, "encoder": encoder.metadata,
                  "documentIds": list(self.positions)}
        serialized = json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        cache = Path(directory) / self.fingerprint
        cache.mkdir(parents=True, exist_ok=True)
        vector_path, meta_path = cache / "vectors.npy", cache / "index.json"
        if vector_path.exists() or meta_path.exists():
            if not vector_path.is_file() or not meta_path.is_file():
                raise RagIndexError("완료되지 않은 별도 색인입니다. 원본 자료는 변경되지 않았습니다.")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("config") != config or meta.get("sha256") != file_sha256(vector_path):
                raise RagIndexError("검색 색인의 버전 또는 해시가 일치하지 않습니다.")
            self.vectors = np.load(vector_path, allow_pickle=False)
        else:
            self.vectors = encoder.encode([d["text"] for d in self.documents], kind="passage")
            with vector_path.open("xb") as output:
                np.save(output, self.vectors, allow_pickle=False)
            with meta_path.open("x", encoding="utf-8") as output:
                json.dump({"config": config, "sha256": file_sha256(vector_path)}, output, ensure_ascii=False)
        expected = (len(self.documents), encoder.metadata["dimension"])
        if self.vectors.shape != expected or self.vectors.dtype != np.float32 or not np.isfinite(self.vectors).all():
            raise RagIndexError("검색 색인의 벡터 형식이 올바르지 않습니다.")
        self.stats = {"documents": len(self.documents), "uniqueTexts": len({d["text"] for d in self.documents}),
                      "dimension": encoder.metadata["dimension"], "indexFingerprint": self.fingerprint,
                      "corpusFingerprint": corpus.fingerprint, "local": True,
                      "retrievalPolicy": RETRIEVAL_POLICY}

    def search(self, question, scoped_documents, *, top_k=5, min_score=0.78, relative_margin=0.08):
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
            raise RagIndexError("결과 개수는 1~20 사이의 정수여야 합니다.")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in (min_score, relative_margin)) or not -1 <= min_score <= 1 or relative_margin < 0:
            raise RagIndexError("검색 점수 설정이 올바르지 않습니다.")
        candidates = [d for d in scoped_documents if d["documentId"] in self.positions]
        if not candidates:
            return []
        vector = self.encoder.encode([question], kind="query")[0]
        indexes = [self.positions[d["documentId"]] for d in candidates]
        scores = self.vectors[indexes] @ vector
        lexical = lexical_scores(question, candidates)
        # Both candidate lists remain subject to the absolute semantic floor.
        # A topical lexical match can rescue a record cut by the relative margin.
        floor = max(float(min_score), float(scores.max()) - relative_margin)
        eligible = [i for i, score in enumerate(scores)
                    if score >= min_score and (score >= floor or lexical[i] > 0)]
        # Lexical matches recover eligible tails; preserve the calibrated dense
        # order instead of promoting a literal match over a semantic first hit.
        ranked = sorted(eligible, key=lambda i: (-float(scores[i]), -lexical[i], candidates[i]["documentId"]))
        return [{**candidates[i], "score": float(scores[i])} for i in ranked[:top_k]]
