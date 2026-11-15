"""Summarize numeric planner usage, never prompts, thoughts or generated plans."""

import argparse
import json
import math
from pathlib import Path
from statistics import mean, median


def number(value):
    return value if type(value) in {int, float} and math.isfinite(value) and value >= 0 else None


def summarize(records):
    rows = []
    for record in records:
        usage = record.get("usage") or {}
        native = usage.get("nativeTimings") or {}
        diagnostic = usage.get("qwenDiagnostics") or {}
        prompt, generated = number(native.get("prompt_ms")), number(native.get("predicted_ms"))
        tokens = number(native.get("predicted_n"))
        stage = number(record.get("stage_seconds"))
        rows.append(
            {
                "case": record.get("case"),
                "input_tokens": number(usage.get("inputTokens")),
                "output_tokens": number(usage.get("outputTokens")),
                "cached_tokens": number(native.get("cache_n")),
                "prefill_seconds": prompt / 1000 if prompt is not None else None,
                "generation_seconds": generated / 1000 if generated is not None else None,
                "tokens_per_second": tokens * 1000 / generated if tokens is not None and generated else None,
                "other_stage_seconds": max(0, stage - (prompt + generated) / 1000)
                if stage is not None and prompt is not None and generated is not None
                else None,
                "reasoning_tokens_exact": number(diagnostic.get("reasoningTokens")),
                "reasoning_tokens_recount": number(diagnostic.get("retokenizedReasoningTokens")),
                "argument_tokens_recount": number(diagnostic.get("retokenizedArgumentTokens")),
                "plan_steps": number(diagnostic.get("planStepCount")),
                "diagnostic_seconds": number(diagnostic.get("diagnosticSeconds")),
                "tokenizer_prepare_seconds": number(diagnostic.get("tokenizerPrepareSeconds")),
                "reasoning_seconds": None,
                "count_method": diagnostic.get("tokenCountSource", "unavailable"),
            }
        )
    columns = ["prefill_seconds", "generation_seconds", "tokens_per_second", "diagnostic_seconds"]
    aggregate = {}
    for name in columns:
        values = [r[name] for r in rows if r[name] is not None]
        aggregate[name] = (
            {"mean": mean(values), "median": median(values), "n": len(values)} if values else None
        )
    return {"rows": rows, "summary": aggregate, "reasoning_time_measured": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    Path(args.output).write_text(
        json.dumps(summarize(json.loads(Path(args.input).read_text())), indent=2) + "\n"
    )
