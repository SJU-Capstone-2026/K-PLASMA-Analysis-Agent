import pytest
from kplasma_agent.domain import DomainError, compare_runs, validate_result
from fixtures import run


def test_hand_computed_comparison_preserves_order_and_conditions():
    baseline, target = run("A"), run("B", energy=30, flux=3, source=500)
    result = compare_runs({"metrics": ["meanIonEnergy", "ionFlux"]}, baseline, target)
    assert result["resultStatus"] == "COMPARISON_READY"
    assert result["changedConditions"] == ["sourcePower"]
    assert [m["delta"] for m in result["metrics"]] == [10, 1]
    assert [m["percentChange"] for m in result["metrics"]] == [50, 50]
    assert validate_result({"metrics": ["meanIonEnergy", "ionFlux"]}, result, [baseline, target])["valid"]


def test_direction_change_is_not_percent_sign_reversal():
    result = compare_runs({"metrics": ["meanIonEnergy"]}, run("B", energy=30), run("A", energy=20))
    assert result["metrics"][0]["delta"] == -10
    assert result["metrics"][0]["percentChange"] == pytest.approx(-33.33333333333333)


@pytest.mark.parametrize("target,delta", [(0, 0), (3, 3)])
def test_zero_baseline_keeps_delta(target, delta):
    result = compare_runs({"metrics": ["ionFlux"]}, run("A", flux=0), run("B", flux=target))
    assert result["metrics"][0] == {
        "metric": "ionFlux",
        "baseline": 0,
        "target": target,
        "delta": delta,
        "percentChange": None,
        "unit": "10¹⁸ m⁻²s⁻¹",
        "status": "PERCENT_UNAVAILABLE",
        "reason": "ZERO_BASELINE",
    }
    assert result["resultStatus"] == "COMPARISON_PARTIAL"


@pytest.mark.parametrize(
    "a,b,reason",
    [
        (None, 1, "MISSING_BASELINE"),
        (1, None, "MISSING_TARGET"),
        (None, None, "MISSING_BOTH"),
        (True, 1, "INVALID_VALUE"),
        (float("nan"), 1, "INVALID_VALUE"),
        (float("inf"), 1, "INVALID_VALUE"),
    ],
)
def test_missing_and_invalid_values(a, b, reason):
    result = compare_runs({"metrics": ["iedWidth"]}, run("A", width=a), run("B", width=b))
    row = result["metrics"][0]
    assert row["reason"] == reason
    assert row["delta"] is None
    assert result["resultStatus"] == "NO_COMPARABLE_DATA"


def test_units_normalize_before_subtraction():
    a, b = run("A"), run("B", pressure=0.01, flux=3e18)
    b["units"]["pressure"] = "Torr"
    b["units"]["ionFlux"] = "m⁻²s⁻¹"
    result = compare_runs({"metrics": ["ionFlux"]}, a, b)
    assert result["changedConditions"] == []
    assert result["metrics"][0]["delta"] == 1


def test_incompatible_unit_preserves_original_without_mislabeling():
    a, b = run("A"), run("B")
    b["units"]["ionFlux"] = "unknown"
    row = compare_runs({"metrics": ["ionFlux"]}, a, b)["metrics"][0]
    assert row["reason"] == "UNIT_NOT_COMPARABLE"
    assert row["target"] is None
    assert row["sourceValues"]["target"] == {"value": 2, "unit": "unknown"}


def test_overflow_and_same_ref_or_unusable_are_not_fake_success():
    row = compare_runs({"metrics": ["meanIonEnergy"]}, run("A", energy=-1e308), run("B", energy=1e308))[
        "metrics"
    ][0]
    assert row["reason"] == "NUMERIC_OVERFLOW"
    assert row["baseline"] == -1e308 and row["target"] == 1e308
    assert row["delta"] is None
    with pytest.raises(DomainError, match="SAME_RUN_REFERENCE"):
        compare_runs({}, run("A"), run("A"))
    bad = run("B")
    bad["catalogStatus"] = "BROKEN"
    with pytest.raises(DomainError, match="DATA_NOT_COMPARABLE"):
        compare_runs({}, run("A"), bad)
