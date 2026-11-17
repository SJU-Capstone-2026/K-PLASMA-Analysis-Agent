"""Embedding candidate comparison: (A) dense ranking of distinct memo texts, (B) the real V3 RagService pipeline."""
import json
import math
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from .encoders import CandidateEncoder
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
    GRID = [(round(float(m), 2), r) for m in np.arange(0.0, 0.96, 0.01)
            for r in (0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 2.0)]


    def dense_metrics(enc):
        """(A) Rank the distinct memo texts by embedding similarity only."""
        texts = [t for t in gold["texts"] if t["text"].strip()]
        ids = [t["id"] for t in texts]
        vecs = enc.encode([t["text"] for t in texts], kind="passage")
        rows = {}
        for q in queries:
            scores = vecs @ enc.encode([q["query"]], kind="query")[0]
            order = [ids[i] for i in np.argsort(-scores, kind="stable")]
            r = rel[q["id"]]
            if not r:
                rows[q["id"]] = {"top1": float(scores.max())}
                continue
            gains = [1.0 if d in r else 0.0 for d in order[:5]]
            idcg = sum(1 / math.log2(i + 2) for i in range(min(5, len(r))))
            first = next(i for i, d in enumerate(order) if d in r)
            rows[q["id"]] = {"ndcg5": sum(g / math.log2(i + 2) for i, g in enumerate(gains)) / idcg,
                             "p5": sum(gains) / min(5, len(r)), "mrr": 1 / (first + 1),
                             "r10": len(set(order[:10]) & r) / len(r), "top1": float(scores.max())}
        return rows


    refs = []
    for rec in records:
        for ref in [rec.get("targetRunRef"), *(rec.get("comparedRunRefs") or []), *(rec.get("candidates") or [])]:
            if ref and ref.get("runVersionId"):
                item = {"runId": ref["runId"], "runVersionId": ref["runVersionId"]}
                if item not in refs:
                    refs.append(item)
    corpus = live_corpus(records, refs, synthetic=True)
    run_ids = sorted(corpus.run_versions)


    def replay(entry, m, r, k=5):
        """Same selection as LocalIndex.search, over documents the real pipeline passed to it."""
        qvec, docs, lex, vectors = entry
        if not docs:
            return []
        scores = vectors @ qvec
        floor = max(m, float(scores.max()) - r)
        eligible = [i for i, s in enumerate(scores) if s >= m and (s >= floor or lex[i] > 0)]
        ranked = sorted(eligible, key=lambda i: (-float(scores[i]), -lex[i], docs[i]["documentId"]))
        return [docs[i] for i in ranked[:k]]


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
                "emptyWhenNoAnswer": sum(x["ok"] for x in n) / len(n) if n else None,
                "avgReturned": sum(x["returned"] for x in a) / len(a)}


    def pipeline(enc, tmp):
        """(B) Real RagService: scope, explicit-support selection, dense+lexical search."""
        svc = RagService(corpus, enc, Path(tmp), min_score=-1.0, relative_margin=2.0, include_rules=False)
        captured = {}
        real_search = svc.index.search

        def spy(question, docs, **kw):
            captured[question] = docs
            return real_search(question, docs, **kw)

        svc.index.search = spy
        for q in queries:
            svc.ask(q["query"], run_ids, top_k=5, mode="semantic")
        svc.index.search = real_search
        data = {}
        for q in queries:
            docs = [d for d in captured.get(q["query"], []) if d["documentId"] in svc.index.positions]
            vecs = svc.index.vectors[[svc.index.positions[d["documentId"]] for d in docs]] if docs else None
            data[q["id"]] = (enc.encode([q["query"]], kind="query")[0], docs,
                             lexical_scores(q["query"], docs) if docs else [], vecs)

        def evaluate(m, r, split):
            return [per_query(q, replay(data[q["id"]], m, r)) for q in queries if split is None or q["split"] == split]

        def key(g):
            s = summarize(evaluate(*g, "dev"))
            return (s["objective"], s["precision"], g[0])

        best = max(GRID, key=key)
        svc.min_score, svc.relative_margin = best
        for q in queries:  # the real service reproduces the replayed selection
            real = [c["documentId"] for c in svc.ask(q["query"], run_ids, top_k=5, mode="semantic")["citations"]]
            assert real == [d["documentId"] for d in replay(data[q["id"]], *best)], q["id"]
        def key_test(g):
            s = summarize(evaluate(*g, "test"))
            return (s["objective"], s["precision"], g[0])

        swapped = max(GRID, key=key_test)  # tune on test, evaluate on dev
        both = {q["id"]: per_query(q, replay(data[q["id"]], *(best if q["split"] == "test" else swapped)))
                for q in queries}
        return {"swapped": {"minScore": swapped[0], "relativeMargin": swapped[1],
                            "dev": summarize(evaluate(*swapped, "dev"))},
                "crossFitPerQuery": both, "crossFit": summarize(list(both.values())),
                "tuned": {"minScore": best[0], "relativeMargin": best[1],
                          "dev": summarize(evaluate(*best, "dev")), "test": summarize(evaluate(*best, "test")),
                          "perQuery": {q["id"]: per_query(q, replay(data[q["id"]], *best)) for q in queries}},
                "current_0.78_0.08": {"dev": summarize(evaluate(0.78, 0.08, "dev")),
                                      "test": summarize(evaluate(0.78, 0.08, "test"))},
                "searchableDocsPerQuery": {q["id"]: len(data[q["id"]][1]) for q in queries},
                "indexDocs": svc.index.stats["documents"]}


    results = {}
    for name in ("e5-small", "e5-base", "ko-sroberta"):
        t0 = time.perf_counter()
        enc = CandidateEncoder(name)
        load = time.perf_counter() - t0
        with tempfile.TemporaryDirectory() as tmp:
            t0 = time.perf_counter()
            B = pipeline(enc, tmp)
            pipe = time.perf_counter() - t0
        A = dense_metrics(enc)
        lat = []
        for q in queries:
            enc._cache.clear()
            t0 = time.perf_counter()
            enc.encode([q["query"]], kind="query")
            lat.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        enc._cache.clear()
        enc.encode([t["text"] for t in gold["texts"] if t["text"].strip()], kind="passage")
        index_s = time.perf_counter() - t0
        ans = [v for v in A.values() if "ndcg5" in v]
        results[name] = {"metadata": enc.metadata, "loadSeconds": load, "pipelineSeconds": pipe,
                         "queryEncodeMsMedian": 1000 * float(np.median(lat)), "index101TextsSeconds": index_s,
                         "dense": {k: sum(v[k] for v in ans) / len(ans) for k in ("ndcg5", "p5", "mrr", "r10")},
                         "denseTop1Answerable": float(np.mean([v["top1"] for v in ans])),
                         "denseTop1NoAnswer": float(np.mean([v["top1"] for v in A.values() if "ndcg5" not in v])),
                         "densePerQuery": A, "pipeline": B}
        print(name, "dense", {k: round(v, 3) for k, v in results[name]["dense"].items()},
              "top1 ans/no", round(results[name]["denseTop1Answerable"], 3), round(results[name]["denseTop1NoAnswer"], 3),
              "q ms", round(results[name]["queryEncodeMsMedian"], 1), "index s", round(index_s, 2))
        print("  tuned", B["tuned"]["minScore"], B["tuned"]["relativeMargin"],
              "\n  dev ", {k: round(v, 3) for k, v in B["tuned"]["dev"].items()},
              "\n  test", {k: round(v, 3) for k, v in B["tuned"]["test"].items()},
              "\n  0.78/0.08 test", {k: round(v, 3) for k, v in B["current_0.78_0.08"]["test"].items()})
        print("  swapped", B["swapped"]["minScore"], B["swapped"]["relativeMargin"], "dev",
              {k: round(v, 3) for k, v in B["swapped"]["dev"].items()},
              "\n  crossfit(all 40)", {k: round(v, 3) for k, v in B["crossFit"].items()})
    names = list(results)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pa, pb = results[a]["pipeline"]["crossFitPerQuery"], results[b]["pipeline"]["crossFitPerQuery"]
            win = sum(pa[q]["score"] > pb[q]["score"] for q in pa)
            loss = sum(pa[q]["score"] < pb[q]["score"] for q in pa)
            print(f"paired {a} vs {b}: {a} better {win}, worse {loss}, tie {len(pa) - win - loss}")
    print("searchable docs per query (e5-small):", results["e5-small"]["pipeline"]["searchableDocsPerQuery"])
    json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
