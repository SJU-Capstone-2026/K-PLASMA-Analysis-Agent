"""Opt-in Decisions evaluation against fixed, labelled plan pairs."""

import argparse
import atexit
from collections import Counter
import json
from pathlib import Path
from time import monotonic

import httpx

from kplasma_agent import tracing
from kplasma_agent.config import Settings
from kplasma_agent.v2.budget import check_payload
from kplasma_agent.v2.contracts import PlanDraft
from kplasma_agent.v2.model_gateway import V2ModelGateway, V2Settings
from kplasma_agent.v2.plan_review import build_plan_review_context
from kplasma_agent.v2.plan_validation import validate_plan
from .plan_review_cases import cases


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
        {"case": case.id, "bad": bad, "repeat": repeat, "question": case.question}
        for case, bad, repeat in matrix], ensure_ascii=False, indent=2))
    if not args.live:
        print(f"Planned {len(matrix)} fixed-plan Decisions requests; no API calls. Use --live to run.")
        return
    base = Settings.from_env(args.env_file)
    if not base.api_key:
        parser.error("OPENAI_API_KEY is required for --live")
    tracing.initialize(base)
    atexit.register(tracing.shutdown)
    rows = []
    with httpx.Client(timeout=base.timeout) as client, (args.output / "results.jsonl").open("w") as output:
        models = V2ModelGateway(V2Settings.from_env(base), client, check_payload)
        for case, bad, repeat in matrix:
            proposed = case.bad if bad else case.good
            plan = validate_plan(PlanDraft.model_validate(proposed.model_dump(mode="json")),
                messages={"question": case.question}, context_keys=set(case.context),
                selected_run_keys={e["key"] for e in case.context.get("comparison_entries", [])})
            payload = build_plan_review_context(plan, 1, case.question, [], case.context, {})
            start = monotonic()
            with tracing.span("eval.decisions", session_id=f"decisions:{args.output.name}:{case.id}:{bad}:{repeat}",
                              attributes={"evaluation.case_id": case.id, "evaluation.expected_bad": bad}):
                result, usage = models.review_plan(payload)
            row = {"case": case.id, "bad": bad, "repeat": repeat, "question": case.question,
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
