"""Opt-in model comparison. Live artifacts must stay outside the source tree."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

from .v2_cases import CASES
from .v2_harness import GRAPH_VERSIONS, evaluate_case, live_configuration, open_gateway

SETTINGS = (("gpt-5.6-luna", "none"), ("gpt-5.6-luna", "low"),
            ("gpt-6-luna", "none"), ("gpt-6-luna", "low"))


def jobs(limit, only, repeat, *, graph_version="v2"):
    if graph_version not in GRAPH_VERSIONS:
        raise ValueError("unsupported graph version")
    matrix = (("mlx-community/Qwen3.5-9B-4bit", "none"),) if graph_version == "v2_localLLM" else SETTINGS
    for model, effort in matrix:
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
    parser.add_argument("--graph-version", choices=GRAPH_VERSIONS, default="v2")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--plan-review", choices=("on", "off"), default="on")
    args = parser.parse_args()
    args.workers = args.workers if args.workers is not None else (1 if args.graph_version == "v2_localLLM" else 4)
    if args.workers < 1 or args.graph_version == "v2_localLLM" and args.workers != 1:
        parser.error("local evaluation requires concurrency 1; workers must be positive")
    if args.graph_version == "v2_localLLM" and args.plan_review != "on":
        parser.error("local evaluation requires plan review")
    if args.live and args.plan_review != "on":
        parser.error("live evaluation requires plan review; --plan-review off is not allowed")
    output = args.output.resolve()
    repo = Path(__file__).resolve().parents[3]
    if output.is_relative_to(repo):
        parser.error("output must be outside the repository")
    matrix = list(jobs(args.limit, args.case, args.repeat, graph_version=args.graph_version))
    if not matrix:
        parser.error("no evaluation cases match")
    output.mkdir(parents=True, exist_ok=True)
    (output / "matrix.json").write_text(json.dumps([
        {"graphVersion": args.graph_version, "evaluationMode": "real_model" if args.live else "offline_preflight",
         "model": model, "effort": effort, "case": case.id, "trial": trial}
        for model, effort, case, trial in matrix
    ], indent=2), encoding="utf-8")
    print(f"{len(matrix)} evaluation requests -> {output}", flush=True)
    if not args.live:
        return
    try:
        base, configured = live_configuration(args.graph_version, args.env_file)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    def run(job):
        model, effort, case, trial = job
        selected = configured if args.graph_version == "v2_localLLM" else replace(
            configured, planner=replace(base, model=model, reasoning_effort=effort), plan_review_enabled=True)
        with open_gateway(args.graph_version, base, selected) as gateway:
            row = evaluate_case(case, gateway, plan_review_enabled=True, graph_version=args.graph_version)
        return {**row, "model": model, "effort": effort, "trial": trial}

    with ThreadPoolExecutor(max_workers=args.workers) as pool, (output / "results.jsonl").open("w") as file:
        for i, row in enumerate(pool.map(run, matrix), start=1):
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            file.flush()
            print(f"{i}/{len(matrix)} {row['model']}/{row['effort']} {row['case']} #{row['trial']} "
                  f"{'PASS' if row['pass'] else 'FAIL'}", flush=True)


if __name__ == "__main__":
    main()
