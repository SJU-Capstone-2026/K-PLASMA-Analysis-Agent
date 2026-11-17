"""Compare cost-regex-1 (V1/V2 port), cost-regex-2 (PR #36) and cost-regex-3 on saved judgment memos.

Usage (repository root):
    PYTHONPATH=agent/python/src:agent/python python -m evals.v3_decision_engines.cost_rules MEMOS.json OUT.json
No model or network call is made. Only aggregated counts are printed.
"""
import json
import sys
from collections import Counter

from kplasma_agent.domain import decision_records as r1
from kplasma_agent.v3.decision_rag import policy


def main():
    memos, out_path = sys.argv[1:3]
    records = json.load(open(memos, encoding="utf-8"))["records"]
    runs = list(dict.fromkeys([r["targetRunId"] for r in records if r.get("targetRunId")] +
                              [c["runId"] for r in records for c in r.get("candidates") or []]))
    v3 = policy.COST_REGEX_3
    entries, rows = [], []
    for run in runs:
        e1 = {e["recordId"]: e["reason"] for e in r1.evidence(records, run)}
        e3 = {e["recordId"]: e["reason"] for e in policy.evidence(records, run, v3)}
        for e in policy.evidence(records, run):
            entries.append({"runId": run, "recordId": e["recordId"], "decision": e["decision"], "note": e["note"],
                            "r1": e1.get(e["recordId"]), "r2": e["reason"], "r3": e3[e["recordId"]]})
        rows.append({"runId": run, "c1": r1.summarize(records, run)["count"],
                     "c2": policy.summarize(records, run)["count"], "c3": policy.summarize(records, run, v3)["count"]})

    def changed(a, b):
        return Counter((e[a], e[b], e["decision"], e["note"]) for e in entries if e[a] != e[b])

    result = {"records": len(records), "runs": len(runs), "entries": len(entries),
              "reasons": {k: dict(Counter(e[k] for e in entries)) for k in ("r1", "r2", "r3")},
              "entryDiffs": {f"{a}-{b}": sum(changed(a, b).values()) for a, b in (("r1", "r2"), ("r1", "r3"), ("r2", "r3"))},
              "runCountDiffs": {f"{a}-{b}": sum(r[a] != r[b] for r in rows)
                                for a, b in (("c1", "c2"), ("c1", "c3"), ("c2", "c3"))},
              "excludedAtThreshold": {t: {k: sum(r[k] >= t for r in rows) for k in ("c1", "c2", "c3")} for t in (1, 2, 3)},
              "changedNotes": {f"{a}-{b}": [{"from": x, "to": y, "decision": d, "note": n, "count": c}
                                            for (x, y, d, n), c in changed(a, b).most_common()]
                               for a, b in (("r1", "r2"), ("r2", "r3"))}}
    json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: result[k] for k in ("records", "runs", "entries", "entryDiffs", "runCountDiffs",
                                              "excludedAtThreshold")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
