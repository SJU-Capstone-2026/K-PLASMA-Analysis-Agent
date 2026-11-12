"""Opt-in model comparison. Live artifacts must stay outside the source tree."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

import httpx

from kplasma_agent.config import Settings
from kplasma_agent.v2.model_gateway import V2ModelGateway, V2Settings
from kplasma_agent.v2.budget import check_payload

from .v2_cases import CASES
from .v2_harness import evaluate_case

SETTINGS = (("gpt-5.6-luna", "none"), ("gpt-5.6-luna", "low"),
            ("gpt-6-luna", "none"), ("gpt-6-luna", "low"))


def jobs(limit, only, repeat):
    for model, effort in SETTINGS:
        for case in [c for c in CASES if not only or c.id == only][:limit]:
            attempts = repeat if case.repeated else 1
            for trial in range(1, attempts + 1):
                yield model, effort, case, trial


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--limit", type=int, default=len(CASES))
    parser.add_argument("--case")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--plan-review", choices=("on", "off"), default="on")
    args = parser.parse_args()
    if args.live and args.plan_review != "on":
        parser.error("live evaluation requires plan review; --plan-review off is not allowed")
    output = args.output.resolve()
    repo = Path(__file__).resolve().parents[3]
    if output.is_relative_to(repo):
        parser.error("output must be outside the repository")
    matrix = list(jobs(args.limit, args.case, args.repeat))
    if not matrix:
        parser.error("no evaluation cases match")
    output.mkdir(parents=True, exist_ok=True)
    (output / "matrix.json").write_text(json.dumps([
        {"model": model, "effort": effort, "case": case.id, "trial": trial}
        for model, effort, case, trial in matrix
    ], indent=2), encoding="utf-8")
    print(f"{len(matrix)} evaluation requests -> {output}", flush=True)
    if not args.live:
        return
    base = Settings.from_env(args.env_file)
    if not base.api_key:
        parser.error("live mode requires OPENAI_API_KEY")
    configured = V2Settings.from_env(base)
    if not configured.plan_review_enabled:
        parser.error("live evaluation requires AGENT_V2_PLAN_REVIEW_ENABLED=true")
    check_payload({}, "plan")

    def run(job):
        model, effort, case, trial = job
        v2 = replace(configured, planner=replace(base, model=model, reasoning_effort=effort),
                     plan_review_enabled=True)
        with httpx.Client(timeout=base.timeout, transport=httpx.HTTPTransport(retries=0)) as client:
            gateway = V2ModelGateway(v2, client, check_payload)
            row = evaluate_case(case, gateway, plan_review_enabled=True)
        return {**row, "model": model, "effort": effort, "trial": trial}

    with ThreadPoolExecutor(max_workers=args.workers) as pool, (output / "results.jsonl").open("w") as file:
        for i, row in enumerate(pool.map(run, matrix), start=1):
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            file.flush()
            print(f"{i}/{len(matrix)} {row['model']}/{row['effort']} {row['case']} #{row['trial']} "
                  f"{'PASS' if row['pass'] else 'FAIL'}", flush=True)


if __name__ == "__main__":
    main()
