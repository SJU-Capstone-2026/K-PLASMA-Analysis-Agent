import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seed import condition, dataset_indices, make_run, query_for, run_id


def test_nested_unique_datasets_cover_actual_grid_and_preserve_zero():
    small = dataset_indices(150)
    large = dataset_indices(10_000)
    assert large[:150] == small
    assert len(set(large)) == 10_000
    triples = {condition(i) for i in small}
    assert triples == {
        (p, s, b)
        for p in (2, 4, 6, 8, 10)
        for s in (100, 200, 300, 400, 500)
        for b in (0, 200, 400, 600, 800, 1000)
    }
    assert dataset_indices(10_000) == large
    assert "B0000" in run_id(8, 300, 0)


def test_id_never_truncates_conditions_or_accepts_nonfinite():
    assert run_id(8, 300, 600) == "RUN-P08-S300-B0600"
    for bad in (8.5, float("nan"), float("inf"), -1):
        with pytest.raises(ValueError):
            run_id(bad, 300, 600)


def test_large_grid_permutation_is_bijective_without_generating_large_fixture():
    import math

    assert math.gcd(485863, 1_000_000) == 1
    assert condition(999_999) == (50, 500, 9950)


@pytest.mark.parametrize(
    "responses",
    [
        ["ordinary-service"],
        ["forward-lookup-synthetic-only", "service_database"],
    ],
)
def test_seed_refuses_wrong_container_or_database_before_writing(
    monkeypatch, tmp_path, responses
):
    import seed

    calls = []

    def output(command, **kwargs):
        calls.append((command, kwargs.get("input")))
        return responses[len(calls) - 1]

    monkeypatch.setattr(seed.subprocess, "check_output", output)
    with pytest.raises(RuntimeError, match="Refusing"):
        seed.seed(150, tmp_path)
    assert len(calls) == len(responses)
    assert all("TRUNCATE" not in (text or "") for _, text in calls)


def test_generator_oracle_matches_actual_domain_and_replay():
    from kplasma_agent.domain import lookup_forward, validate_result
    from kplasma_agent.domain.common import public_run

    saved = make_run(dataset_indices(150)[0])
    query = query_for(saved)
    query["conditions"]["pressure"] = {
        "value": saved["pressure"] / 1000,
        "unit": "Torr",
    }
    result = lookup_forward(query, [saved])
    assert result["resultStatus"] == "EXACT"
    assert result["run"] == public_run(saved)
    assert validate_result(query, result, [saved])["valid"]
    result["run"]["metrics"]["ionFlux"] += 1
    assert not validate_result(query, result, [saved])["valid"]
