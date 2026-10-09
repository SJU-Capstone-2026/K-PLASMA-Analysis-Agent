from kplasma_agent.domain import lookup_forward, validate_result
from fixtures import run


QUERY = {
    "conditions": {"pressure": {"value": 10, "unit": "mTorr"},
                   "sourcePower": {"value": 300, "unit": "W"}, "biasPower": {"value": 100, "unit": "W"}}
}


def test_exact_preserves_source_version_order_and_metadata():
    runs = [run("B"), run("A")]
    result = lookup_forward(QUERY, runs)
    assert result["resultStatus"] == "EXACT"
    assert result["run"]["runId"] == "B"
    assert result["run"]["sourceFileCount"] == 2
    assert result["usedRunRefs"] == [{"runId": "B", "runVersionId": "synthetic-B-v1"}]
    assert validate_result(QUERY, result, runs)["valid"]


def test_nearest_is_actual_run_and_stable_tie():
    result = lookup_forward(QUERY, [run("B", pressure=11), run("A", pressure=9)])
    assert result["resultStatus"] == "NEAREST_ONLY"
    assert result["run"]["pressure"] == 11
    assert result["deltas"]["pressure"] == 1


def test_unusable_and_missing_conditions_are_excluded():
    bad = run("B")
    bad["qualityStatus"] = "UNVERIFIED"
    missing = run("C", pressure=None)
    result = lookup_forward(QUERY, [bad, missing])
    assert result["resultStatus"] == "NO_DATA"
    assert result["usedRunRefs"] == []
    assert len(result["excludedRuns"]) == 2


def test_validation_rejects_changed_number_or_order():
    runs = [run()]
    result = lookup_forward(QUERY, runs)
    result["run"]["metrics"]["ionFlux"] = 123
    assert not validate_result(QUERY, result, runs)["valid"]
