"""Compare the PR #36 bundle cache (LocalIndex) with the per-memo store (IncrementalIndex).

Usage (repository root, V3 RAG environment, ko-sroberta files in .local/models):
    python -m evals.v3_decision_engines.vector_store MEMOS.json GOLD.json QUESTIONS12.json OUT.json [--sizes 300,3000]

Parts
  1. Determinism: does an existing memo's vector change when other memos are added?
  2. Cost: memos embedded and seconds per step of one neutral workload, at several corpus sizes.
     Scaled corpora give every memo a unique text so de-duplication cannot favour either method.
  3. Quality guard: same thresholds, both methods, on Claude's 40-question gold set and on the
     six RAG questions of the PR #36 evaluation (no gold there: only agreement is reported).
No model API is called. Memo texts are synthetic.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from kplasma_agent.v3.decision_engines import KOSR_MIN_SCORE, KOSR_RELATIVE_MARGIN
from kplasma_agent.v3.decision_rag.embedding import KO_SROBERTA, LocalEncoder
from kplasma_agent.v3.decision_rag.index import LocalIndex
from kplasma_agent.v3.decision_rag.live_corpus import live_corpus
from kplasma_agent.v3.decision_rag.service import RagService
from kplasma_agent.v3.decision_rag.vector_store import IncrementalIndex

METHODS = {"bundle (PR #36)": LocalIndex, "per-memo (rules3-kosr)": IncrementalIndex}


class CountingEncoder:
    """Counts passage texts actually sent to the model. The in-memory cache is cleared per request."""

    def __init__(self, encoder):
        self.inner, self.metadata, self.passages = encoder, encoder.metadata, 0

    def encode(self, texts, *, kind="query", **kw):
        texts = list(texts)
        if kind == "passage":
            self.passages += len({t for t in texts})
        return self.inner.encode(texts, kind=kind, **kw)

    def new_request(self):
        self.inner._cache.clear()


def refs_of(records):
    seen, refs = set(), []
    for rec in records:
        for ref in [rec.get("targetRunRef"), *(rec.get("comparedRunRefs") or []), *(rec.get("candidates") or [])]:
            if ref and ref.get("runVersionId") and ref["runId"] not in seen:
                seen.add(ref["runId"])
                refs.append({"runId": ref["runId"], "runVersionId": ref["runVersionId"]})
    return refs


def scaled(records, size):
    """Repeat the synthetic records with a unique suffix on every memo and unique record ids."""
    out = []
    for n in range(size):
        base = json.loads(json.dumps(records[n % len(records)]))
        tag = f" (모의 기록 {n})"
        for key in ("reviewId", "id"):
            if base.get(key):
                base[key] = f"{base[key]}#{n}"
        if base.get("comment"):
            base["comment"] += tag
        if base.get("overallComment"):
            base["overallComment"] += tag
        for cand in base.get("candidates") or []:
            if cand.get("note"):
                cand["note"] += tag
        out.append(base)
    return out


def new_record(i, ref):
    return {"reviewId": f"ART-NEW-{i}", "targetRunId": ref["runId"], "targetRunRef": ref, "comparedRunRefs": [],
            "decision": "REJECT", "comment": f"새로 추가한 모의 메모 {i}: 비용 부담으로 반려했다.",
            "createdAt": "2026-11-17T00:00:00Z", "runSnapshots": [ref]}


def determinism(records, encoder):
    rows = {}
    refs = refs_of(records)
    extra = records + [new_record(i, refs[i % len(refs)]) for i in range(7)]
    for name, factory in METHODS.items():
        with tempfile.TemporaryDirectory() as tmp:
            encoder.new_request()
            before = factory(live_corpus(records, refs, synthetic=True), encoder, Path(tmp))
            encoder.new_request()
            after = factory(live_corpus(extra, refs, synthetic=True), encoder, Path(tmp))
        common = [d["documentId"] for d in before.documents]
        a = before.vectors[[before.positions[i] for i in common]]
        b = after.vectors[[after.positions[i] for i in common]]
        rows[name] = {"maxAbsDiff": float(np.abs(a - b).max()), "minCosine": float((a * b).sum(1).min())}
    return rows


def workload(records, encoder, steps_out):
    refs = refs_of(records)
    half = refs[: max(1, len(refs) // 2)]
    steps = [("cold start, all Runs", records, refs), ("same request again", records, refs),
             ("different Run scope", records, half),
             ("+1 new memo", records + [new_record(0, refs[0])], refs),
             ("+10 new memos", records + [new_record(i, refs[i % len(refs)]) for i in range(11)], refs)]
    for name, factory in METHODS.items():
        with tempfile.TemporaryDirectory() as tmp:
            for label, recs, scope in steps:
                encoder.new_request()
                encoder.passages = 0
                start = time.perf_counter()
                factory(live_corpus(recs, scope, synthetic=True), encoder, Path(tmp))
                steps_out.append({"memos": len(records), "method": name, "step": label,
                                  "embedded": encoder.passages, "seconds": time.perf_counter() - start})
                print(f"  {len(records):6d} {name:24s} {label:22s} embedded {encoder.passages:6d} "
                      f"{steps_out[-1]['seconds']:8.2f}s", flush=True)


def quality(records, encoder, gold, questions):
    text_id = {t["text"]: t["id"] for t in gold["texts"]}
    labels = {k: set(v) for k, v in gold["labels"].items()}
    refs = refs_of(records)
    run_ids = [r["runId"] for r in refs]
    known = set(run_ids)
    rag12 = [c for c in questions["cases"] if c["category"].startswith(("rag_", "no_evidence"))]
    out = {}
    for name, factory in METHODS.items():
        with tempfile.TemporaryDirectory() as tmp:
            encoder.new_request()
            svc = RagService(live_corpus(records, refs, synthetic=True), encoder, Path(tmp),
                             min_score=KOSR_MIN_SCORE, relative_margin=KOSR_RELATIVE_MARGIN,
                             include_rules=False, index_factory=factory)
            gold_rows, pr36 = [], {}
            for q in gold["queries"]:
                got = [text_id[c["quote"]] for c in svc.ask(q["query"], run_ids, top_k=5, mode="semantic")["citations"]]
                rel = labels[q["label"]] if q["label"] else set()
                if rel:
                    hit = float(any(g in rel for g in got))
                    prec = sum(g in rel for g in got) / len(got) if got else 0.0
                    gold_rows.append({"id": q["id"], "answerable": True, "hit": hit, "prec": prec, "got": got})
                else:
                    gold_rows.append({"id": q["id"], "answerable": False, "ok": float(not got), "got": got})
            for case in rag12:
                scope = [r for r in case["attachedRunIds"] if r in known]
                if not scope:
                    pr36[case["id"]] = {"skipped": "attached Run not in memo inventory"}
                    continue
                res = svc.ask(case["question"], scope, top_k=5, mode="semantic")
                pr36[case["id"]] = {"status": res["status"], "documents": [c["documentId"] for c in res["citations"]]}
        a = [r for r in gold_rows if r["answerable"]]
        n = [r for r in gold_rows if not r["answerable"]]
        out[name] = {"gold40": {"hit5": sum(r["hit"] for r in a) / len(a), "precision": sum(r["prec"] for r in a) / len(a),
                                "emptyWhenNoAnswer": f"{int(sum(r['ok'] for r in n))}/{len(n)}"},
                     "goldPerQuery": {r["id"]: r["got"] for r in gold_rows}, "pr36Rag": pr36}
    names = list(METHODS)
    g0, g1 = out[names[0]]["goldPerQuery"], out[names[1]]["goldPerQuery"]
    p0, p1 = out[names[0]]["pr36Rag"], out[names[1]]["pr36Rag"]
    out["agreement"] = {
        "gold40SameResults": sum(g0[k] == g1[k] for k in g0), "gold40Total": len(g0),
        "pr36SameResults": sum(p0[k] == p1[k] for k in p0), "pr36Total": len(p0)}
    return out


def main():
    memos, gold_path, questions_path, out_path = sys.argv[1:5]
    sizes = [300, 3000]
    if "--sizes" in sys.argv:
        sizes = [int(v) for v in sys.argv[sys.argv.index("--sizes") + 1].split(",")]
    records = json.load(open(memos, encoding="utf-8"))["records"]
    gold = json.load(open(gold_path, encoding="utf-8"))
    questions = json.load(open(questions_path, encoding="utf-8"))
    encoder = CountingEncoder(LocalEncoder(Path(".local/models/ko-sroberta-multitask"), spec=KO_SROBERTA))
    result = {"model": KO_SROBERTA.model_id, "thresholds": [KOSR_MIN_SCORE, KOSR_RELATIVE_MARGIN]}
    result["determinism"] = determinism(records, encoder)
    print("determinism", json.dumps(result["determinism"], ensure_ascii=False), flush=True)
    result["quality"] = quality(records, encoder, gold, questions)
    for name in METHODS:
        print("quality", name, result["quality"][name]["gold40"], flush=True)
    print("agreement", result["quality"]["agreement"], flush=True)
    result["workload"] = []
    for size in sizes:
        workload(scaled(records, size), encoder, result["workload"])
    json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
