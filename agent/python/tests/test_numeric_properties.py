import json
from kplasma_agent.domain import compare_runs, search_reverse
from fixtures import run


def test_signed_delta_antisymmetry_and_finite_json():
    for a, b in [(0, 3), (-3, 8), (20.125, 13.75), (1e-100, 1e100)]:
        forward = compare_runs({"metrics": ["ionFlux"]}, run("A", flux=a), run("B", flux=b))
        reverse = compare_runs({"metrics": ["ionFlux"]}, run("B", flux=b), run("A", flux=a))
        assert forward["metrics"][0]["delta"] == -reverse["metrics"][0]["delta"]
        json.dumps(forward, allow_nan=False)


def test_input_not_mutated_and_strengthening_constraint_cannot_add_candidates():
    runs = [run(str(i), pressure=i, flux=i) for i in range(12)]
    before = json.dumps(runs)

    def selected(bound):
        return {
            r["runId"]
            for r in search_reverse(
                {"constraints": [{"metric": "pressure", "operator": "lt", "value": bound}]}, runs
            )["representativeCandidates"]
        }

    assert selected(5) <= selected(10)
    assert json.dumps(runs) == before
