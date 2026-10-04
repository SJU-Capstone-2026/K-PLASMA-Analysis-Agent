import pytest
from kplasma_agent.domain import search_reverse
from fixtures import run


def ids(result):
    return [r["runId"] for r in result["representativeCandidates"]]


def test_soft_goal_priority_order_and_hard_range():
    runs = [run(i, energy=e, flux=f) for i, e, f in zip("ABCDE", [31, 35, 39, 29, 41], [9, 1, 10, 100, 200])]
    range_goal = {"metric": "meanIonEnergy", "direction": "target_range", "min": 30, "max": 40}
    flux_goal = {"metric": "ionFlux", "direction": "maximize"}
    assert ids(search_reverse({"goals": [range_goal, flux_goal]}, runs)) == list("BCAED")
    assert ids(search_reverse({"goals": [flux_goal, range_goal]}, runs)) == list("EDCAB")
    assert ids(
        search_reverse(
            {
                "constraints": [{"metric": "meanIonEnergy", "operator": "between", "min": 30, "max": 40}],
                "goals": [flux_goal],
            },
            runs,
        )
    ) == list("CAB")


@pytest.mark.parametrize(
    "operator,expected",
    [("lt", ["A"]), ("lte", ["A", "B"]), ("gt", ["C"]), ("gte", ["B", "C"]), ("eq", ["B"])],
)
def test_strict_boundary(operator, expected):
    runs = [run("A", pressure=9), run("B", pressure=10), run("C", pressure=11)]
    result = search_reverse(
        {"constraints": [{"metric": "pressure", "operator": operator, "value": 10}]}, runs
    )
    assert ids(result) == expected


def test_no_top_k_and_unrelated_missing_metric_allowed():
    runs = [run(f"R-{i:02}", width=None) for i in range(20)]
    assert len(ids(search_reverse({"goals": [{"metric": "ionFlux", "direction": "maximize"}]}, runs))) == 20
    result = search_reverse({"goals": [{"metric": "iedWidth", "direction": "minimize"}]}, runs)
    assert result["resultStatus"] == "NO_MATCH"
    assert len(result["excludedRuns"]) == 20


def test_independent_objective_and_goal_groups_do_not_claim_all_constraints():
    result = search_reverse(
        {
            "constraints": [
                {"metric": "pressure", "operator": "lt", "value": 10},
                {"metric": "meanIonEnergy", "operator": "between", "min": 30, "max": 40},
            ],
            "goals": [{"metric": "ionFlux", "direction": "maximize"}],
        },
        [
            run("A", pressure=5, energy=35),
            run("B", pressure=20, energy=35, flux=20),
            run("C", pressure=5, energy=60),
        ],
    )
    assert ids(result) == ["A"]
    assert [c["run"]["runId"] for c in result["objectiveResults"][0]["candidates"]] == ["A", "B"]
    assert result["goalResults"][0]["candidates"][0]["runId"] == "B"
    assert result["goalResults"][0]["allConstraintsGuaranteed"] is False


def test_near_matches_keep_violations_and_limit_three():
    result = search_reverse(
        {"constraints": [{"metric": "pressure", "operator": "lt", "value": 1}]},
        [run(i, pressure=p) for i, p in zip("ABCD", [5, 2, 1, 3])],
    )
    assert result["resultStatus"] == "NO_MATCH"
    assert [e["run"]["runId"] for e in result["nearMatches"]] == ["C", "B", "D"]
    assert result["nearMatches"][0]["violations"][0]["operator"] == "lt"
