"""Generate and conservatively validate qualitative synthetic explanations."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time

from kplasma_agent.config import Settings
from kplasma_agent.explanations.engine import (
    ChangeDraft,
    ConceptDraft,
    ExplanationError,
    validate_explanation,
)
from kplasma_agent.graphs.v1 import EXPLAIN_PROMPT
from kplasma_agent.model_client import ModelClient, ModelError

from .explanation_cases import EXPLANATION_CASES

_LOCAL = threading.local()


def _limited_draft():
    return {
        "status": "insufficient_knowledge",
        "interpretations": [],
        "limitations": ["비교 가능한 측정 지표가 없거나 관찰된 변화가 없어 변화 원인을 해석하지 않습니다."],
        "suggested_checks": [],
    }


def _attempt(case, repeat, settings):
    started = time.monotonic()
    record = {
        "caseId": case.id,
        "kind": case.kind,
        "repeat": repeat,
        "syntheticCase": asdict(case),
        "bypassedGeneration": case.bypass_generation,
        "attempts": [],
        "passed": False,
        "answered": False,
        "limited": False,
        "errorCode": None,
        "apiCalls": 0,
        "inputTokens": 0,
        "outputTokens": 0,
    }
    try:
        if case.bypass_generation:
            result = validate_explanation(case.kind, _limited_draft(), case.evidence)
            record.update(passed=True, limited=True, response=result)
        else:
            if not hasattr(_LOCAL, "model"):
                _LOCAL.model = ModelClient(settings)
            repair_error = None
            for attempt in range(2):
                record["apiCalls"] += 1
                response, metadata = _LOCAL.model.generate(
                    EXPLAIN_PROMPT,
                    {"evidence": case.evidence, "repair_error": repair_error},
                    ChangeDraft if case.kind == "explain_change" else ConceptDraft,
                )
                record["inputTokens"] += metadata.get("inputTokens", 0)
                record["outputTokens"] += metadata.get("outputTokens", 0)
                stage = {"response": response, "metadata": metadata, "validationError": None}
                record["attempts"].append(stage)
                try:
                    result = validate_explanation(case.kind, response, case.evidence)
                    record.update(
                        passed=result["status"] == "answered",
                        answered=result["status"] == "answered",
                        limited=result["status"] == "insufficient_knowledge",
                        response=result,
                    )
                    break
                except ExplanationError as error:
                    repair_error = str(error)
                    stage["validationError"] = repair_error
                    if attempt == 1:
                        record["errorCode"] = repair_error
    except ModelError as error:
        record["errorCode"] = error.code
    except Exception as error:
        record["errorCode"] = type(error).__name__
    record["elapsedSeconds"] = round(time.monotonic() - started, 3)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--kind", choices=("explain_change", "explain_concept"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.repeat <= 10:
        parser.error("--repeat must be between 1 and 10")
    cases = [
        case
        for case in EXPLANATION_CASES
        if (not args.case or case.id in args.case) and (not args.kind or case.kind == args.kind)
    ]
    if not cases:
        parser.error("No matching case")
    expected = len(cases) * args.repeat
    bypass_count = sum(case.bypass_generation for case in cases) * args.repeat
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dryRun": True,
                    "distinctCases": len(cases),
                    "attempts": expected,
                    "codeOnlyLimitedCases": bypass_count,
                    "minimumModelCalls": expected - bypass_count,
                }
            )
        )
        return 0
    settings = replace(Settings.from_env(), model="gpt-5.6-luna", reasoning_effort="none")
    if not settings.api_key:
        parser.error("OPENAI_API_KEY is not configured")
    destination = (
        Path(__file__).resolve().parents[1]
        / ".runtime"
        / "evals"
        / "explanations"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    destination.mkdir(parents=True, exist_ok=False)
    results = []
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
                                "expected": expected,
                                "passed": sum(row["passed"] for row in results),
                            }
                        ),
                        flush=True,
                    )
    summary = {
        "evaluationProtocol": "qualitative-synthetic-v1",
        "model": settings.model,
        "reasoningEffort": settings.reasoning_effort,
        "explanationPromptSha256": hashlib.sha256(EXPLAIN_PROMPT.encode()).hexdigest(),
        "expectedAttempts": expected,
        "completedAttempts": len(results),
        "passed": sum(row["passed"] for row in results),
        "answered": sum(row["answered"] for row in results),
        "limited": sum(row["limited"] for row in results),
        "codeOnlyLimitedCases": sum(row["bypassedGeneration"] for row in results),
        "actualModelCalls": sum(row["apiCalls"] for row in results),
        "repairedCases": sum(len(row["attempts"]) > 1 and row["passed"] for row in results),
        "inputTokens": sum(row["inputTokens"] for row in results),
        "outputTokens": sum(row["outputTokens"] for row in results),
        "errors": dict(Counter(row["errorCode"] for row in results if row["errorCode"])),
        "scope": "Schema, reference coverage, numeric/citation/causal claim guards and explicit direction checks. No domain-expert endorsement or proof of scientific truth.",
    }
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({**summary, "localOutputDirectory": str(destination)}, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
