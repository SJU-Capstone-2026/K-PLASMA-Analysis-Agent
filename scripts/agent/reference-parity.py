"""Compare shared scalar semantics only; no external result values are printed."""

import json
import math
import sys

from kplasma_agent.domain import lookup_forward, search_reverse

packet = json.load(sys.stdin)
failures = []
intentional_differences = []
for index, conditions in enumerate(packet["forward"]):
    result = lookup_forward(
        {
            "conditions": {
                key: {"value": value, "unit": "mTorr" if key == "pressure" else "W"}
                for key, value in conditions.items()
            }
        },
        packet["runs"],
    )
    selected = result["run"]
    actual = {
        "status": result["status"],
        "runId": selected["runId"] if selected else None,
        "deltas": result["deltas"],
        "metrics": selected["metrics"] if selected else None,
    }
    if actual != packet["expectedForward"][index]:
        failures.append(f"forward-{index}")
operators = {"MIN": "gte", "MAX": "lte", "EQUAL": "eq", "RANGE": "between"}
directions = {"MIN": "minimize", "MAX": "maximize"}
runs_by_id = {run["runId"]: run for run in packet["runs"]}


def available(run_id, metrics):
    run = runs_by_id[run_id]
    for metric in metrics:
        value = (
            run.get(metric)
            if metric in ("pressure", "sourcePower", "biasPower")
            else run["metrics"].get(metric)
        )
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            return False
    return True


for index, query in enumerate(packet["reverse"]):
    inputs = {
        "constraints": [
            {**c, "operator": operators[c["operator"]]} for c in query["constraints"]
        ],
        "goals": [
            {**g, "direction": directions[g["direction"]]} for g in query["goals"]
        ],
    }
    result = search_reverse(inputs, packet["runs"])
    actual = {
        "status": result["status"],
        "common": result["commonRunIds"],
        "goals": [[r["runId"] for r in g["candidates"]] for g in result["goalResults"]],
        "near": [e["run"]["runId"] for e in result["nearMatches"]],
    }
    expected = packet["expectedReverse"][index]
    # The approved filter-first UI no longer creates global ranking-only tabs.
    expected = {**expected, "goals": []}
    if index == len(packet["reverse"]) - 1:
        presentation = [
            {
                "runId": entry["run"]["runId"],
                "matchPercent": entry["matchPercent"],
                "evaluations": [
                    {
                        "matchPercent": e["matchPercent"],
                        "actual": e["actual"],
                        "satisfied": e["satisfied"],
                        "targetLabel": f"{e['targetLabel']} {e['unit']}",
                        "rangeStatus": e["rangeStatus"],
                    }
                    for e in entry["evaluations"]
                ],
            }
            for entry in result["commonCandidates"]
        ]
        if presentation != packet["examplePresentation"]:
            failures.append("reverse-prototype-example-presentation")
    if actual != expected:
        # Plan X5 explicitly rejects legacy JS null-to-zero coercion. Removing
        # those IDs must leave exactly the original ordering and other fields.
        required = [r["metric"] for r in query["constraints"] + query["goals"]]
        expected = {
            **expected,
            "common": [key for key in expected["common"] if available(key, required)],
            "goals": [],
            "near": [key for key in expected["near"] if available(key, required)],
        }
        if actual == expected:
            intentional_differences.append(
                {"case": f"reverse-{index}", "policy": "X5_UNAVAILABLE_NOT_ZERO"}
            )
        else:
            failures.append(f"reverse-{index}")
print(
    json.dumps(
        {
            "passed": not failures,
            "runCount": len(packet["runs"]),
            "forwardCases": len(packet["forward"]),
            "reverseCases": len(packet["reverse"]),
            "prototypeExampleMatchCount": len(packet["examplePresentation"]),
            "failedCaseIds": failures,
            "intentionalDifferences": intentional_differences,
            "sourceHashes": packet["hashes"],
        }
    )
)
sys.exit(bool(failures))
