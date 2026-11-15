"""Explicit-support filter modes x embedding candidates on the real V3 RagService pipeline.

a = strict  : unsupported memos are removed before dense search (current PR #36 behaviour)
b = off     : no explicit-support filter (pure dense + lexical)
c = soft    : unsupported memos stay, but their dense score is lowered by a tuned penalty
Every mode keeps scope/ownership selection (select_documents) and the same index.search rules.
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

from .encoders import CandidateEncoder
from kplasma_agent.v3.decision_rag.evidence_selection import assess_requested_evidence
from kplasma_agent.v3.decision_rag.index import lexical_scores
from kplasma_agent.v3.decision_rag.live_corpus import live_corpus
from kplasma_agent.v3.decision_rag.service import RagService


def main():
    memos, gold_path, out_path = sys.argv[1:4]
    records = json.load(open(memos, encoding="utf-8"))["records"]
    gold = json.load(open(gold_path, encoding="utf-8"))
    text_id = {t["text"]: t["id"] for t in gold["texts"]}
    labels = {k: set(v) for k, v in gold["labels"].items()}
    queries = gold["queries"]
    rel = {q["id"]: labels[q["label"]] if q["label"] else set() for q in queries}
    MS = [round(float(m), 2) for m in np.arange(0.0, 0.96, 0.01)]
    RS = (0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 2.0)
    PENALTIES = {"a": [None], "b": [0.0], "c": [0.02, 0.05, 0.10, 0.15, 0.20, 0.30]}

    refs = []
    for rec in records:
        for ref in [rec.get("targetRunRef"), *(rec.get("comparedRunRefs") or []), *(rec.get("candidates") or [])]:
            if ref and ref.get("runVersionId"):
                item = {"runId": ref["runId"], "runVersionId": ref["runVersionId"]}
                if item not in refs:
                    refs.append(item)
    corpus = live_corpus(records, refs, synthetic=True)
    run_ids = sorted(corpus.run_versions)


    def select(entry, mode, m, r, p, k=5):
        """index.search selection; mode a drops unsupported docs, c lowers their dense score by p."""
        qvec, docs, lex, vectors, supported = entry
        keep = [i for i in range(len(docs)) if mode != "a" or supported[i]]
        if not keep:
            return []
        scores = vectors[keep] @ qvec
        if mode == "c":
            scores = scores - np.asarray([0.0 if supported[i] else p for i in keep], dtype=np.float32)
        lx = [lex[i] for i in keep]
        floor = max(m, float(scores.max()) - r)
        eligible = [j for j, s in enumerate(scores) if s >= m and (s >= floor or lx[j] > 0)]
        ranked = sorted(eligible, key=lambda j: (-float(scores[j]), -lx[j], docs[keep[j]]["documentId"]))
        return [docs[keep[j]] for j in ranked[:k]]


    def per_query(q, hits):
        got = [text_id[h["text"]] for h in hits]
        r = rel[q["id"]]
        if not r:
            return {"answerable": False, "returned": len(got), "ok": float(not got), "score": float(not got)}
        hit = float(any(g in r for g in got))
        prec = (sum(g in r for g in got) / len(got)) if got else 0.0
        return {"answerable": True, "returned": len(got), "hit": hit, "prec": prec, "score": 0.5 * hit + 0.5 * prec}


    def summarize(rows):
        a = [x for x in rows if x["answerable"]]
        n = [x for x in rows if not x["answerable"]]
        return {"objective": sum(x["score"] for x in rows) / len(rows),
                "hit5": sum(x["hit"] for x in a) / len(a), "precision": sum(x["prec"] for x in a) / len(a),
                "emptyOk": sum(x["ok"] for x in n), "noAnswer": len(n),
                "avgReturned": sum(x["returned"] for x in a) / len(a)}


    def collect(enc, tmp):
        """Capture, per query, the documents the real pipeline passes to explicit-support assessment."""
        loose = RagService(corpus, enc, Path(tmp), min_score=-1.0, relative_margin=2.0,
                           include_rules=False, strict_support=False)
        strict = RagService(corpus, enc, Path(tmp), min_score=-1.0, relative_margin=2.0, include_rules=False)
        data, strict_seen = {}, {}
        for svc, store in ((loose, data), (strict, strict_seen)):
            real = svc.index.search

            def spy(question, docs, _store=store, _real=real, **kw):
                _store[question] = docs
                return _real(question, docs, **kw)

            svc.index.search = spy
            for q in queries:
                svc.ask(q["query"], run_ids, top_k=5, mode="semantic")
            svc.index.search = real
        entries = {}
        for q in queries:
            docs = [d for d in data.get(q["query"], []) if d["documentId"] in loose.index.positions]
            supported = [assess_requested_evidence(q["query"], d).supported for d in docs]
            # Mode a must equal what the real strict service searched.
            assert [d["documentId"] for d, s in zip(docs, supported) if s] == \
                [d["documentId"] for d in strict_seen.get(q["query"], []) if d["documentId"] in loose.index.positions], q["id"]
            vecs = loose.index.vectors[[loose.index.positions[d["documentId"]] for d in docs]] if docs else None
            entries[q["id"]] = (enc.encode([q["query"]], kind="query")[0], docs,
                                lexical_scores(q["query"], docs) if docs else [], vecs, supported)
        return entries, strict


    def tune(entries, mode, split):
        best, best_key = None, None
        for p in PENALTIES[mode]:
            for m in MS:
                for r in RS:
                    s = summarize([per_query(q, select(entries[q["id"]], mode, m, r, p))
                                   for q in queries if q["split"] == split])
                    key = (s["objective"], s["precision"], m)
                    if best_key is None or key > best_key:
                        best, best_key = (m, r, p), key
        return best


    results = {}
    for name in ("e5-small", "e5-base", "ko-sroberta"):
        enc = CandidateEncoder(name)
        with tempfile.TemporaryDirectory() as tmp:
            entries, strict_svc = collect(enc, tmp)
            for mode in "abc":
                on_dev, on_test = tune(entries, mode, "dev"), tune(entries, mode, "test")
                if mode == "a":  # the real strict service reproduces the replayed selection
                    strict_svc.min_score, strict_svc.relative_margin = on_dev[:2]
                    for q in queries:
                        got = [c["documentId"] for c in strict_svc.ask(q["query"], run_ids, top_k=5, mode="semantic")["citations"]]
                        assert got == [d["documentId"] for d in select(entries[q["id"]], "a", *on_dev)], q["id"]
                cross = {q["id"]: per_query(q, select(entries[q["id"]], mode, *(on_dev if q["split"] == "test" else on_test)))
                         for q in queries}
                results[f"{name}/{mode}"] = {"devTuned": on_dev, "testTuned": on_test, "crossFit": summarize(list(cross.values())),
                                             "perQuery": cross}
                s = results[f"{name}/{mode}"]["crossFit"]
                print(f"{name:12s} {mode}  obj {s['objective']:.3f}  hit {s['hit5']:.3f}  prec {s['precision']:.3f}  "
                      f"empty {s['emptyOk']}/{s['noAnswer']}  ret {s['avgReturned']:.2f}  params dev->test {on_dev} test->dev {on_test}")

    base = results["e5-small/a"]["perQuery"]
    print("\npaired vs e5-small/a (current PR #36 search): better / worse / tie")
    for key, value in results.items():
        pq = value["perQuery"]
        print(f"  {key:16s} {sum(pq[q]['score'] > base[q]['score'] for q in pq):2d} / "
              f"{sum(pq[q]['score'] < base[q]['score'] for q in pq):2d} / {sum(pq[q]['score'] == base[q]['score'] for q in pq):2d}")
    print("\nper-query cross-fit score (Q: a b c per model)")
    for q in queries:
        row = "  ".join(" ".join(f"{results[f'{n}/{m}']['perQuery'][q['id']]['score']:.1f}" for m in "abc")
                        for n in ("e5-small", "e5-base", "ko-sroberta"))
        print(f"{q['id']} {q['split']:4s} {row}  {q['query']}")
    json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
