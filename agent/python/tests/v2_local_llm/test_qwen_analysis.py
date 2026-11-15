import json

import pytest


def test_report_keeps_native_generation_and_diagnostic_overhead_separate():
    from evals.local_llm_qwen_analysis import summarize

    rows = [
        {
            "case": "synthetic",
            "usage": {
                "inputTokens": 1000,
                "outputTokens": 100,
                "nativeTimings": {"cache_n": 900, "prompt_ms": 500, "predicted_n": 100, "predicted_ms": 4000},
                "qwenDiagnostics": {
                    "reasoningTokens": 20,
                    "retokenizedReasoningTokens": 22,
                    "retokenizedArgumentTokens": 70,
                    "planStepCount": 2,
                    "diagnosticSeconds": 0.02,
                    "tokenCountSource": "provider",
                },
                "secret": "never copy",
            },
            "stage_seconds": 5,
        }
    ]
    report = summarize(rows)
    assert report["rows"][0]["generation_seconds"] == 4
    assert report["rows"][0]["tokens_per_second"] == 25
    assert report["rows"][0]["other_stage_seconds"] == pytest.approx(0.5)
    assert report["rows"][0]["diagnostic_seconds"] == 0.02
    assert report["rows"][0]["reasoning_seconds"] is None
    assert "never copy" not in json.dumps(report)


def test_unavailable_thought_counts_are_not_zeros():
    from evals.local_llm_qwen_analysis import summarize

    report = summarize([{"case": "synthetic", "usage": {"outputTokens": 10}}])
    assert report["rows"][0]["reasoning_tokens_exact"] is None
    assert report["rows"][0]["reasoning_tokens_recount"] is None
