"""Run with PYTHONPATH=src:. python -m evals.run_interpretation --repeat 3.

Raw questions and model outputs are written only under agent/python/.runtime/.
The console emits aggregate counters; --dry-run performs no model requests.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import threading
import time

from kplasma_agent.config import Settings
from kplasma_agent.contracts import Interpretation
from kplasma_agent.graphs.v1 import INTERPRET_PROMPT
from kplasma_agent.model_client import ModelClient, ModelError

from .cases import CASES
from .judge import case_payload, judge, public_case

_LOCAL = threading.local()
_RUNTIME = Path(__file__).resolve().parents[1] / ".runtime" / "evals"


def summarize(results, *, model, reasoning_effort, expected_count):
    categories = defaultdict(lambda: {"attempts": 0, "passed": 0, "criticalWrongDispatch": 0})
    for result in results:
        category = categories[result["category"]]
        category["attempts"] += 1
        category["passed"] += result["assessment"]["passed"]
        category["criticalWrongDispatch"] += result["assessment"]["criticalWrongDispatch"]
    return {
        "evaluationProtocol": "mandatory-slots-v3-scoped-context",
        "interpretPromptSha256": hashlib.sha256(INTERPRET_PROMPT.encode()).hexdigest(),
        "model": model,
        "reasoningEffort": reasoning_effort,
        "expectedAttempts": expected_count,
        "completedAttempts": len(results),
        "passed": sum(row["assessment"]["passed"] for row in results),
        "exactCasePassRate": sum(row["assessment"]["passed"] for row in results) / len(results)
        if results
        else 0,
        "criticalWrongDispatch": sum(row["assessment"]["criticalWrongDispatch"] for row in results),
        "mandatorySlotChecksPassed": sum(row["assessment"]["checksPassed"] for row in results),
        "mandatorySlotChecksTotal": sum(row["assessment"]["checksTotal"] for row in results),
        "inputTokens": sum(row.get("metadata", {}).get("inputTokens", 0) for row in results),
        "outputTokens": sum(row.get("metadata", {}).get("outputTokens", 0) for row in results),
        "modelErrors": dict(Counter(row["errorCode"] for row in results if row.get("errorCode"))),
        "categories": dict(categories),
        "scope": "Synthetic interpretation, mandatory slots, grounding and clarification only; not domain-expert validation of physical explanations.",
    }


def _attempt(case, repeat, settings):
    if not hasattr(_LOCAL, "model"):
        _LOCAL.model = ModelClient(settings)
    started = time.monotonic()
    record = {
        "caseId": case.id,
        "category": case.category,
        "repeat": repeat,
        "syntheticCase": public_case(case),
        "errorCode": None,
    }
    try:
        response, metadata = _LOCAL.model.generate(INTERPRET_PROMPT, case_payload(case), Interpretation)
        record.update(response=response, metadata=metadata, assessment=judge(case, response))
    except ModelError as error:
        record.update(
            errorCode=error.code,
            assessment={
                "passed": False,
                "criticalWrongDispatch": False,
                "checksPassed": 0,
                "checksTotal": 1,
                "failures": [error.code],
                "groundingError": None,
            },
        )
    except Exception as error:
        # Never serialize exception text or provider bodies containing request contents.
        record.update(
            errorCode=type(error).__name__,
            assessment={
                "passed": False,
                "criticalWrongDispatch": False,
                "checksPassed": 0,
                "checksTotal": 1,
                "failures": ["HARNESS_ERROR"],
                "groundingError": None,
            },
        )
    record["elapsedSeconds"] = round(time.monotonic() - started, 3)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--category", choices=["forward", "reverse", "compare", "change", "concept"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.repeat <= 10:
        parser.error("--repeat must be between 1 and 10")
    cases = [
        case
        for case in CASES
        if (not args.case or case.id in args.case) and (not args.category or case.category == args.category)
    ]
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        cases = cases[: args.limit]
    if not cases:
        parser.error("No matching synthetic cases")
    expected_count = len(cases) * args.repeat
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dryRun": True,
                    "distinctCases": len(cases),
                    "attempts": expected_count,
                    "categories": dict(Counter(case.category for case in cases)),
                },
                ensure_ascii=False,
            )
        )
        return 0
    settings = replace(Settings.from_env(), model="gpt-5.6-luna", reasoning_effort="none")
    if not settings.api_key:
        parser.error("OPENAI_API_KEY is not configured")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = _RUNTIME / stamp
    destination.mkdir(parents=True, exist_ok=False)
    results = []
    # Sequential file appends preserve each completion even if this process stops.
    with (destination / "attempts.jsonl").open("x", encoding="utf-8") as stream:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [
                executor.submit(_attempt, case, repeat, settings)
                for repeat in range(1, args.repeat + 1)
                for case in cases
            ]
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                if len(results) % 20 == 0:
                    print(
                        json.dumps(
                            {
                                "completed": len(results),
                                "expected": expected_count,
                                "passed": sum(row["assessment"]["passed"] for row in results),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
    summary = summarize(
        results,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
        expected_count=expected_count,
    )
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({**summary, "localOutputDirectory": str(destination)}, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == expected_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
