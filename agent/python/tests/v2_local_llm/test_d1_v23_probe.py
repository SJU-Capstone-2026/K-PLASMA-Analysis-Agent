"""Bounded comparison accounting; these tests never call models."""

import pytest
from evals import local_llm_d1_v23_probe as probe


def test_five_profiles_and_five_cases_bound_comparison_to_25():
    assert [(p["precision"], p["input_profile"]) for p in probe.PHASES] == [
        ("bf16", "ko-full"),
        ("q8", "ko-full"),
        ("q8", "en-full"),
        ("q8", "en-compact"),
        ("q8", "en-compact-no-view"),
    ]
    rows = probe.review_cases()
    assert len(rows) == 5 and len({x["case"] for x in rows}) == 5
    assert len(probe.PHASES) * len(rows) == 25
    assert {x["expected"] for x in rows} == {"PASS", "ISSUE"}
    assert any(x["case"] == "bad_metric_definition" for x in rows)


def test_per_check_tokens_are_weighted_by_actual_check_count():
    rows = [
        {"check_count": 2, "input_tokens": 100, "seconds": 1.0},
        {"check_count": 8, "input_tokens": 800, "seconds": 3.0},
    ]
    totals = probe.measurements(rows)
    assert totals["average_tokens_per_check"] == 90
    assert totals["seconds_per_check"] == 0.4
    assert totals["input_tokens"] == 900 and totals["checks"] == 10


def test_missing_usage_is_not_silently_counted_as_zero():
    totals = probe.measurements([{"check_count": 2, "input_tokens": None, "seconds": 1.0}])
    assert totals["average_tokens_per_check"] is None
    assert totals["input_tokens"] is None


@pytest.mark.parametrize("bad", [0, -1, True])
def test_invalid_check_denominator_is_rejected(bad):
    with pytest.raises(ValueError):
        probe.measurements([{"check_count": bad, "input_tokens": 10, "seconds": 1.0}])


def test_final_docker_failure_keeps_memory_evidence_instead_of_losing_completed_rows(monkeypatch):
    from threading import Event
    from types import SimpleNamespace

    memory = probe.ProbeMemory.__new__(probe.ProbeMemory)
    memory.stop = Event()
    memory.monitor = SimpleNamespace(join=lambda **_: None)
    memory.policy = "development"
    memory.before = {"limit_mib": 1536, "db_oom": {"synthetic": 0}}
    memory.samples = [{"pressure": 1, "swap_bytes": 0, "resident_bytes": 100}]
    memory.capture = lambda: None

    def unavailable():
        raise TimeoutError("Docker sampler timed out")

    monkeypatch.setattr(probe, "docker_sample", unavailable)
    result = memory.finish()
    assert result["passed"] is False and result["docker_after"] is None
    assert result["samples"] == memory.samples
