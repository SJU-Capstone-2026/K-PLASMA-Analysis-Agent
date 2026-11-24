"""Opt-in Decisions evaluation against fixed, labelled plan pairs."""

import argparse
import atexit
from collections import Counter
import json
from pathlib import Path
from time import monotonic

from .plan_review_cases import cases
from .v2_harness import GRAPH_VERSIONS, live_configuration, open_gateway, runtime_for_version


def jobs(bank, repeats):
    repeated = [case for case in bank if case.repeated]
    for repeat in range(repeats):
        for case in repeated:
            for bad in (False, True):
                yield case, bad, repeat + 1
    for case in bank:
        if not case.repeated:
            for bad in (False, True):
                yield case, bad, 1


def grade(bad, status):
    if status == "UNAVAILABLE":
        return "api_error"
    if status == "UNCLEAR":
        return "unclear"
    if status == ("ISSUE" if bad else "PASS"):
        return "correct"
    return "false_accept" if bad else "false_reject"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--graph-version", choices=GRAPH_VERSIONS, default="v2")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    bank = [c for c in cases() if not args.case or c.id in args.case]
    if not bank or args.repeats < 1:
        parser.error("choose at least one known case and a positive repetition count")
    args.output.mkdir(parents=True, exist_ok=True)
    matrix = list(jobs(bank, args.repeats))
    (args.output / "jobs.json").write_text(json.dumps([
        {"graphVersion": args.graph_version, "evaluationMode": "real_model" if args.live else "offline_preflight",
         "case": case.id, "bad": bad, "repeat": repeat, "question": case.question}
        for case, bad, repeat in matrix], ensure_ascii=False, indent=2))
    if not args.live:
        print(f"Planned {len(matrix)} fixed-plan Decisions requests; no API calls. Use --live to run.")
        return
    try:
        base, configured = live_configuration(args.graph_version, args.env_file)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    runtime = runtime_for_version(args.graph_version)
    tracing = runtime.tracing
    tracing.initialize(base)
    atexit.register(tracing.shutdown)
    rows = []
    with open_gateway(args.graph_version, base, configured) as models, (args.output / "results.jsonl").open("w") as output:
        for case, bad, repeat in matrix:
            proposed = case.bad if bad else case.good
            plan = runtime.validation.validate_plan(runtime.contracts.PlanDraft.model_validate(proposed.model_dump(mode="json")),
                messages={"question": case.question}, context_keys=set(case.context),
                selected_run_keys={e["key"] for e in case.context.get("comparison_entries", [])})
            payload = runtime.review.build_plan_review_context(plan, 1, case.question, [], case.context, {})
            start = monotonic()
            with tracing.span("eval.decisions", session_id=f"decisions:{args.output.name}:{case.id}:{bad}:{repeat}",
                              attributes={"evaluation.case_id": case.id, "evaluation.expected_bad": bad}):
                result, usage = models.review_plan(payload)
            row = {"graphVersion": args.graph_version, "evaluationMode": "real_model",
                   "case": case.id, "bad": bad, "repeat": repeat, "question": case.question,
                   "grade": grade(bad, result["status"]), "seconds": monotonic() - start,
                   "input": payload, "review": result, "usage": usage}
            rows.append(row)
            output.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            output.flush()
            print(json.dumps({key: row[key] for key in ("case", "bad", "repeat", "grade", "seconds")}), flush=True)
    summary = {"requests": len(rows), "grades": dict(Counter(row["grade"] for row in rows)),
               "mean_seconds": sum(row["seconds"] for row in rows) / len(rows)}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
