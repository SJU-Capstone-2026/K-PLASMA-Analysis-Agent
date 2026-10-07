import pytest
from fixtures import run
from kplasma_agent.domain.compare import compare_selected


def selected(*runs):
    return [
        {"key": f"R{i + 1}", "ref": {k: r[k] for k in ("runId", "runVersionId")}, "run": r}
        for i, r in enumerate(runs)
    ]


def test_all_runs_and_zero_baseline():
    result = compare_selected(
        {"metrics": ["ionFlux"], "baseline_key": "R1"},
        selected(run("A", flux=0), run("B", flux=2), run("C", flux=4)),
    )
    assert result["mode"] == "baseline" and len(result["runs"]) == 3
    assert len(result["comparisons"]) == 2
    row = result["comparisons"][0]
    assert row["difference"]["value"] == 2
    assert row["percentChange"]["reason"] == "ZERO_BASELINE"
    assert result["resultStatus"] == "COMPARISON_PARTIAL"


def test_without_baseline_no_signed_percent_and_no_dropped_runs():
    result = compare_selected({"metrics": ["ionFlux"]}, selected(run("A", flux=4), run("B", flux=2)))
    assert result["mode"] == "pair"
    assert result["comparisons"][0]["difference"]["value"] == 2
    assert result["comparisons"][0]["percentChange"] is None
    overview = compare_selected({"metrics": ["ionFlux"]}, selected(run("A"), run("B"), run("C")))
    assert overview["mode"] == "overview" and overview["summaries"][0]["minimumKeys"] == ["R1", "R2", "R3"]


def test_duplicate_axis_and_single_available_do_not_invent_trends_or_range():
    result = compare_selected(
        {"analysis": "trend", "trend_axis": "pressure", "metrics": ["ionFlux"]},
        selected(run("A", pressure=8), run("B", pressure=8, flux=5)),
    )
    assert result["trends"][0]["direction"] == "unavailable"
    result = compare_selected({"metrics": ["iedWidth"]}, selected(run("A", width=3), run("B", width=None)))
    assert result["summaries"][0]["range"]["reason"] == "INSUFFICIENT_DATA"


@pytest.mark.parametrize("size", [2, 5, 150])
def test_order_and_inventory(size):
    entries = selected(*(run(str(i), flux=i) for i in range(size)))
    result = compare_selected({}, entries)
    assert result["usedRunRefs"] == [e["ref"] for e in entries]
    assert [r["key"] for r in result["runs"]] == [e["key"] for e in entries]


def test_raw_values_do_not_add_differences_or_aggregates():
    result = compare_selected(
        {"analysis": "values", "metrics": ["iedWidth"]}, selected(run("A", width=3), run("B", width=None))
    )
    assert result["mode"] == "values"
    assert result["comparisons"] == result["summaries"] == result["trends"] == []
    assert result["resultStatus"] == "COMPARISON_PARTIAL"


def test_overflow_and_unconvertible_source_are_preserved_without_false_zero():
    result = compare_selected(
        {"baseline_key": "R1", "metrics": ["ionFlux"]}, selected(run("A", flux=1e-308), run("B", flux=1e308))
    )
    assert result["comparisons"][0]["percentChange"]["reason"] == "NUMERIC_OVERFLOW"
    broken = run("B", energy=3)
    broken["units"]["meanIonEnergy"] = "joule"
    result = compare_selected({"metrics": ["meanIonEnergy"]}, selected(run("A"), broken))
    datum = result["runs"][1]["metrics"]["meanIonEnergy"]
    assert datum["value"] is None and datum["reason"] == "UNIT_NOT_COMPARABLE"
    assert datum["sourceValue"] == {"value": 3, "unit": "joule"}
