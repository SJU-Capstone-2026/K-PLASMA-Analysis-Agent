"""External-bundle, frozen-oracle evaluator. No product imports, network, or model calls.

``pass`` means deterministic checks passed; ``humanReviewRequired`` prevents that
result from being mistaken for scientific approval of a free-form explanation.
"""

import hashlib
import json
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
COUNTS = {
    "lookup_search": 8,
    "boundary_units_sort": 8,
    "comparison_nested": 8,
    "hitl": 6,
    "empty_missing": 4,
    "concept_interpretation_mixed": 6,
}
UNITS = {
    "pressure": "mTorr",
    "sourcePower": "W",
    "biasPower": "W",
    "ionFlux": "10¹⁸ m⁻²s⁻¹",
    "meanIonEnergy": "eV",
    "iedWidth": "eV",
}


def configure(bundle):
    global HERE
    HERE = Path(bundle).resolve()
    load_oracle.cache_clear()
    load_overrides.cache_clear()


def oracle_dir():
    return HERE


@lru_cache(maxsize=1)
def load_oracle():
    root = oracle_dir()
    files = {
        name: (root / name).read_bytes()
        for name in ("runs.json", "wave-expected.json", "distribution-expected.json")
    }
    runs = json.loads(files["runs.json"])
    features, outputs = {}, {}
    for wave in json.loads(files["wave-expected.json"])["waves"]:
        rid = wave["ref"]["runId"]
        span = wave["maximum"] - wave["minimum"]
        features[rid] = {
            "potential.maximum": (wave["maximum"], "V"),
            "potential.minimum": (wave["minimum"], "V"),
            "potential.peakToPeak": (span, "V"),
            "potential.halfPeakToPeak": (span / 2, "V"),
            "potential.maximumPhase": (wave["maximum_x"][0], "RF cycle"),
            "potential.minimumPhase": (wave["minimum_x"][0], "RF cycle"),
        }
        outputs[(rid, "potential")] = {
            "status": "AVAILABLE",
            "reason": None,
            "sourceCount": wave["count"],
            "maximum": wave["maximum"],
            "minimum": wave["minimum"],
        }
    distributions = json.loads(files["distribution-expected.json"])
    for plot in ("iad", "iead"):
        for item in distributions[plot]:
            rid = item["ref"]["runId"]
            outputs[(rid, plot)] = item
            feature = features.setdefault(rid, {})
            feature[f"{plot}.maximum"] = (
                item.get("maximum"),
                "a.u." if plot == "iad" else "원본 단위 미지정",
            )
            if plot == "iad":
                feature["iad.peakAngle"] = (item.get("firstMaximumAngle"), "°")
            else:
                peak = item.get("peaks", [[None, None, None]])[0]
                feature["iead.peakAngle"] = (peak[1], "°")
                feature["iead.peakEnergy"] = (peak[2], "eV")
    return {
        "runs": runs,
        "byId": {r["runId"]: r for r in runs},
        "byVersion": {r["runVersionId"]: r for r in runs},
        "features": features,
        "outputs": outputs,
        "hashes": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()},
    }


def close(actual, expected):
    return (
        isinstance(actual, (int, float))
        and not isinstance(actual, bool)
        and math.isfinite(actual)
        and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
    )


def canonical(field, value, unit=None):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("non-finite or nonnumeric value")
    unit = UNITS.get(field) if unit is None else unit
    spelling = re.sub(r"\s+", "", unit or "").casefold()
    if field == "pressure" and spelling in ("torr", "토르", "토어"):
        return value * 1000
    if field == "pressure" and spelling in ("mtorr", "밀리토르", "millitorr"):
        return value
    if field in ("sourcePower", "biasPower") and spelling in ("w", "와트", "watt", "watts"):
        return value
    if field in ("meanIonEnergy", "iedWidth") and spelling in (
        "ev",
        "전자볼트",
        "electronvolt",
        "electronvolts",
    ):
        return value
    if field == "ionFlux":
        if spelling in ("m⁻²s⁻¹", "m^-2s^-1", "m-2s-1"):
            return value / 1e18
        if spelling in ("10¹⁸m⁻²s⁻¹", "10^18m^-2s^-1"):
            return value
    if unit == UNITS.get(field) and field in UNITS:
        return value
    raise ValueError(f"incompatible unit {field}: {unit}")


def interval(filters, field):
    low, low_closed, high, high_closed = -math.inf, False, math.inf, False
    for item in filters:
        if item.get("field", item.get("metric")) != field:
            continue
        op = item["operator"]
        unit = item.get("unit")
        if op in ("between", "range"):
            a, b = canonical(field, item["min"], unit), canonical(field, item["max"], unit)
            parts = [("gte", a), ("lte", b)]
        else:
            parts = [(op, canonical(field, item["value"], unit))]
        for operator, value in parts:
            if operator in ("eq", "gte", "gt"):
                inclusive = operator != "gt"
                if value > low or value == low and not inclusive:
                    low, low_closed = value, inclusive
            if operator in ("eq", "lte", "lt"):
                inclusive = operator != "lt"
                if value < high or value == high and not inclusive:
                    high, high_closed = value, inclusive
            if operator not in ("eq", "gte", "gt", "lte", "lt"):
                raise ValueError(f"unknown operator {operator}")
    return low, low_closed, high, high_closed


def conditions_equal(expected, actual):
    fields = {f["field"] for f in expected}
    if fields != {f.get("field", f.get("metric")) for f in actual}:
        return False
    try:
        for field in fields:
            a, b = interval(expected, field), interval(actual, field)
            if a[1] != b[1] or a[3] != b[3]:
                return False
            if not all(x == y or close(x, y) for x, y in ((a[0], b[0]), (a[2], b[2]))):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def raw_value(run, field):
    return run.get(field, run.get("metrics", {}).get(field))


def matching_ids(search, oracle):
    found = []
    for run in oracle["runs"]:
        good = True
        for field in {f["field"] for f in search["filters"]}:
            value = raw_value(run, field)
            low, lc, high, hc = interval(search["filters"], field)
            good = (
                good
                and value is not None
                and (value > low or lc and value == low)
                and (value < high or hc and value == high)
            )
        if good:
            found.append(run["runId"])
    found.sort()
    for order in reversed(search.get("sort", [])):
        found.sort(
            key=lambda rid: raw_value(oracle["byId"][rid], order["field"]),
            reverse=order["direction"] == "desc",
        )
    return found


def load_cases_raw():
    cases = json.loads((HERE / "cases.json").read_text())
    oracle = load_oracle()
    assert len(cases) == 40 and len({c["id"] for c in cases}) == 40
    assert len({c["question"] for c in cases}) == 40
    assert dict(Counter(c["category"] for c in cases)) == COUNTS
    assert len(oracle["runs"]) == 149 and len(oracle["byId"]) == 149
    for case in cases:
        assert case["sourceOracle"]["files"] == oracle["hashes"], case["id"]
        assert all(r in oracle["byId"] for r in case["selected"])
        assert case["baseline"] is None or case["baseline"] in case["selected"]
        for search in case["expected"]["searches"]:
            assert search["runIds"] == matching_ids(search, oracle), case["id"]
        for comparison in case["expected"]["comparisons"]:
            assert len(comparison["runIds"]) >= 2 and all(r in oracle["byId"] for r in comparison["runIds"])
            assert all(
                field in UNITS or all(field in oracle["features"].get(r, {}) for r in comparison["runIds"])
                for field in comparison["fields"]
            ), case["id"]
        for item in case["expected"]["derived"]:
            values = [raw_value(oracle["byId"][rid], item["field"]) for rid in item["runIds"]]
            expected = {"max": max, "min": min, "mean": lambda v: sum(v) / len(v)}[item["operation"]](values)
            assert close(item["value"], expected), case["id"]
        for group in case["expected"].get("text", {}).get("requiredAny", []):
            for pattern in group:
                re.compile(pattern)
    return cases


def known_value(rid, field, oracle):
    if field in UNITS:
        run = oracle["byId"][rid]
        return raw_value(run, field), run["units"][field]
    return oracle["features"][rid][field]


def datum_ok(datum, rid, field, oracle):
    expected, unit = known_value(rid, field, oracle)
    if not isinstance(datum, dict):
        return False
    actual = datum.get("value")
    if not isinstance(datum.get("unit"), str) or not datum["unit"]:
        return False
    if expected is None:
        return (
            actual is None
            and datum.get("status") == "UNAVAILABLE"
            and bool(datum.get("reason"))
            and (datum.get("sourceValue") or {}).get("value") is None
            and datum.get("unit") == unit
        )
    if field == "iead.maximum":
        source = datum.get("sourceValue") or {}
        return (
            actual is None
            and datum.get("status") == "UNAVAILABLE"
            and datum.get("reason") == "UNIT_NOT_COMPARABLE"
            and close(source.get("value"), expected)
            and source.get("unit") == unit
            and datum.get("unit") == unit
        )
    if datum.get("status") != "AVAILABLE" or datum.get("reason") is not None:
        return False
    try:
        normalized = canonical(field, actual, datum.get("unit")) if field in UNITS else actual
        return close(normalized, expected) and (field in UNITS or datum.get("unit") == unit)
    except (ValueError, TypeError):
        return False


def grade_raw(case, view, interactions):
    """Grade one final request and its actual, same-request HITL interactions."""
    checks = []
    expected = case["expected"]
    human = bool(expected.get("general") or expected.get("interpretation"))

    def check(name, passed, detail=None):
        checks.append({"name": name, "pass": bool(passed), "detail": detail})

    try:
        oracle = load_oracle()
    except (OSError, ValueError, KeyError) as error:
        check("oracle_available", False, str(error))
        return {"pass": False, "checks": checks, "humanReviewRequired": human}
    check("frozen_oracle_identity", case.get("sourceOracle", {}).get("files") == oracle["hashes"])
    check("request_completed", view.get("status") == "COMPLETED", view.get("status"))
    check("actual_v2", view.get("graphVersion") == "v2", view.get("graphVersion"))
    snapshot = view.get("answerSnapshot")
    check("answer_snapshot_present", isinstance(snapshot, dict))
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    answer = snapshot.get("answer")
    check("nonempty_final_answer", isinstance(answer, str) and bool(answer.strip()))
    answer = answer if isinstance(answer, str) else ""
    steps = snapshot.get("stepResults", [])
    tools = [
        s.get("outputs", {}).get("toolResult")
        for s in steps
        if isinstance(s.get("outputs", {}).get("toolResult"), dict)
    ]
    searches = [t for t in tools if t.get("kind") == "reverse_search"]
    comparisons = [t for t in tools if t.get("kind") == "compare_runs"]
    entries = (snapshot.get("confirmedContext") or {}).get("entries", [])
    key_ids = {e["key"]: e["ref"]["runId"] for e in entries}
    for tool in comparisons:
        for row in tool.get("runs", []):
            key_ids.setdefault(row["key"], row["ref"]["runId"])

    def ref_ok(ref):
        run = oracle["byId"].get((ref or {}).get("runId"))
        return run is not None and ref.get("runVersionId") == run["runVersionId"]

    scalar_errors = []
    scalar_count = 0
    for tool in tools:
        raw_runs = []
        if tool.get("kind") == "forward_lookup" and isinstance(tool.get("run"), dict):
            raw_runs.append(tool["run"])
        if tool.get("kind") == "reverse_search":
            refs = tool.get("commonRunRefs", [])
            check("search_refs_are_frozen_versions", all(ref_ok(r) for r in refs))
            for ref in refs:
                run = tool.get("runsByVersion", {}).get(ref.get("runVersionId"))
                if run is not None:
                    raw_runs.append(run)
        for run in raw_runs:
            if not ref_ok(run):
                scalar_errors.append({"unknownRef": {k: run.get(k) for k in ("runId", "runVersionId")}})
                continue
            source = oracle["byId"][run["runId"]]
            for field in UNITS:
                actual, wanted = raw_value(run, field), raw_value(source, field)
                unit = run.get("units", {}).get(field)
                scalar_count += 1
                try:
                    good = (
                        actual is None and unit == source["units"][field]
                        if wanted is None
                        else isinstance(unit, str)
                        and bool(unit)
                        and close(canonical(field, actual, unit), wanted)
                    )
                except (ValueError, TypeError):
                    good = False
                if not good:
                    scalar_errors.append(
                        {
                            "runId": run["runId"],
                            "field": field,
                            "actual": actual,
                            "expected": wanted,
                            "unit": run.get("units", {}).get(field),
                        }
                    )
        for row in tool.get("runs", []) if tool.get("kind") == "compare_runs" else []:
            if not ref_ok(row.get("ref")):
                scalar_errors.append({"unknownRef": row.get("ref")})
                continue
            rid = row["ref"]["runId"]
            for field, datum in {**row.get("conditions", {}), **row.get("metrics", {})}.items():
                if field not in UNITS and field not in oracle["features"].get(rid, {}):
                    continue
                scalar_count += 1
                if not datum_ok(datum, rid, field, oracle):
                    scalar_errors.append(
                        {
                            "runId": rid,
                            "field": field,
                            "datum": datum,
                            "expected": known_value(rid, field, oracle),
                        }
                    )
    check(
        "observed_source_values_and_units",
        not scalar_errors,
        {"valuesChecked": scalar_count, "errors": scalar_errors[:12]},
    )

    for index, wanted in enumerate(expected.get("searches", []), 1):
        valid_conditions = [
            t for t in searches if conditions_equal(wanted["filters"], t.get("constraints", []))
        ]
        valid_forwards = []
        for tool in tools:
            if (
                tool.get("kind") != "forward_lookup"
                or tool.get("resultStatus", tool.get("status")) != "EXACT"
            ):
                continue
            conditions = [
                {"field": k, "operator": "eq", "value": v, "unit": UNITS.get(k)}
                for k, v in tool.get("requestedConditions", {}).items()
            ]
            if conditions_equal(wanted["filters"], conditions):
                valid_forwards.append(tool)
        check(
            f"search_{index}_condition_preserved",
            bool(valid_conditions or valid_forwards),
            {"expected": wanted["filters"], "observed": [t.get("constraints", []) for t in searches]},
        )
        results = [(t, t.get("commonRunRefs", [])) for t in valid_conditions]
        results += [(t, [t["run"]]) for t in valid_forwards if isinstance(t.get("run"), dict)]
        wanted_set = set(wanted["runIds"])
        candidates = [
            (t, refs)
            for t, refs in results
            if len(refs) == len(wanted_set)
            and {r.get("runId") for r in refs} == wanted_set
            and all(ref_ok(r) for r in refs)
        ]
        check(
            f"search_{index}_exact_run_set",
            bool(candidates),
            {"expectedCount": len(wanted_set), "observedCounts": [len(r) for _, r in results]},
        )
        if wanted.get("sort"):

            def sorted_correctly(refs):
                ids = [r["runId"] for r in refs]
                reordered = list(ids)
                for order in reversed(wanted["sort"]):
                    reordered.sort(
                        key=lambda rid: raw_value(oracle["byId"][rid], order["field"]),
                        reverse=order["direction"] == "desc",
                    )
                return reordered == ids

            check(f"search_{index}_requested_sort", any(sorted_correctly(refs) for _, refs in candidates))

    for index, wanted in enumerate(expected.get("comparisons", []), 1):
        ids = set(wanted["runIds"])
        candidates = [
            t
            for t in comparisons
            if {r.get("ref", {}).get("runId") for r in t.get("runs", [])} == ids
            and len(t.get("runs", [])) == len(ids)
        ]
        check(
            f"comparison_{index}_all_requested_runs",
            bool(candidates),
            {"expectedCount": len(ids), "actualCounts": [len(t.get("runs", [])) for t in comparisons]},
        )
        missing = [
            (rid, field)
            for rid in wanted["runIds"]
            for field in wanted["fields"]
            if not any(
                any(
                    r.get("ref", {}).get("runId") == rid
                    and field in r.get("metrics", {})
                    and datum_ok(r["metrics"][field], rid, field, oracle)
                    for r in t.get("runs", [])
                )
                for t in candidates
            )
        ]
        check(f"comparison_{index}_fields_values_units", not missing, {"missingOrInvalid": missing[:12]})
        if wanted.get("baselineRunId"):
            good = [
                t
                for t in candidates
                if any(
                    r.get("key") == t.get("baselineKey")
                    and r.get("ref", {}).get("runId") == wanted["baselineRunId"]
                    for r in t.get("runs", [])
                )
            ]
            check(f"comparison_{index}_chosen_baseline", bool(good), wanted["baselineRunId"])
            for field in wanted["fields"]:
                check(
                    f"comparison_{index}_baseline_delta_{field}",
                    any(
                        row.get("kind") == "baseline_delta"
                        and row.get("metric") == field
                        and next(
                            (r["ref"]["runId"] for r in t["runs"] if r["key"] == row.get("leftKey")), None
                        )
                        == wanted["baselineRunId"]
                        for t in good
                        for row in t.get("comparisons", [])
                    ),
                )
                if wanted.get("percentChange"):
                    check(
                        f"comparison_{index}_baseline_percentage_{field}",
                        any(
                            row.get("kind") == "baseline_delta"
                            and row.get("metric") == field
                            and (row.get("percentChange") or {}).get("status") == "AVAILABLE"
                            and isinstance((row.get("percentChange") or {}).get("value"), (int, float))
                            for t in good
                            for row in t.get("comparisons", [])
                        ),
                    )
        if wanted.get("difference") == "absolute":
            for field in wanted["fields"]:
                check(
                    f"comparison_{index}_absolute_difference_{field}",
                    any(
                        row.get("kind") == "absolute_difference" and row.get("metric") == field
                        for t in candidates
                        for row in t.get("comparisons", [])
                    ),
                )
        if wanted.get("trendAxis"):
            axis = wanted["trendAxis"]
            ordered_ids = sorted(wanted["runIds"], key=lambda rid: raw_value(oracle["byId"][rid], axis))
            for field in wanted["fields"]:
                values = [known_value(rid, field, oracle)[0] for rid in ordered_ids]
                changes = {1 if b > a else -1 if b < a else 0 for a, b in zip(values, values[1:])}
                direction = (
                    "constant"
                    if changes == {0}
                    else "increasing"
                    if changes <= {0, 1}
                    else "decreasing"
                    if changes <= {-1, 0}
                    else "non_monotonic"
                )
                check(
                    f"comparison_{index}_chosen_trend_axis_{field}",
                    any(
                        t.get("trendAxis") == axis
                        and t.get("mode") == "trend"
                        and trend.get("metric") == field
                        and trend.get("axis") == axis
                        and trend.get("direction") == direction
                        and [
                            next((r["ref"]["runId"] for r in t["runs"] if r["key"] == key), None)
                            for key in trend.get("orderedKeys", [])
                        ]
                        == ordered_ids
                        for t in candidates
                        for trend in t.get("trends", [])
                    ),
                )

    difference_errors = []
    for tool in comparisons:
        rows = {r.get("key"): r for r in tool.get("runs", [])}
        for difference in tool.get("comparisons", []):
            field = difference.get("metric")
            left, right = rows.get(difference.get("leftKey")), rows.get(difference.get("rightKey"))
            if (
                not left
                or not right
                or field not in UNITS
                and field not in oracle["features"].get(left["ref"]["runId"], {})
            ):
                continue
            a, unit = known_value(left["ref"]["runId"], field, oracle)
            b, _ = known_value(right["ref"]["runId"], field, oracle)
            datum = difference.get("difference") or {}
            if a is None or b is None or field == "iead.maximum":
                valid = datum.get("value") is None and datum.get("status") == "UNAVAILABLE"
            else:
                delta = abs(b - a) if difference.get("kind") == "absolute_difference" else b - a
                valid = close(datum.get("value"), delta) and datum.get("unit") == unit
                percent = difference.get("percentChange")
                if percent is not None:
                    valid = valid and (
                        percent.get("value") is None and percent.get("reason") == "ZERO_BASELINE"
                        if a == 0
                        else close(percent.get("value"), (b - a) / abs(a) * 100)
                        and percent.get("unit") == "%"
                    )
            if not valid:
                difference_errors.append(difference.get("id"))
    check("comparison_differences_and_percentages", not difference_errors, difference_errors)

    for index, wanted in enumerate(expected.get("derived", []), 1):
        materialized = []
        for step in steps:
            datum = step.get("outputs", {}).get("value")
            if isinstance(datum, dict) and datum.get("field", wanted["field"]) == wanted["field"]:
                materialized.append((datum.get("value"), datum.get("unit")))
        for search in searches:
            for constraint in search.get("constraints", []):
                if constraint.get("metric") == wanted["field"]:
                    materialized.extend(
                        (constraint[k], constraint.get("unit"))
                        for k in ("value", "min", "max")
                        if k in constraint and constraint[k] is not None
                    )

        def matches_derived(pair):
            try:
                return close(canonical(wanted["field"], pair[0], pair[1]), wanted["value"])
            except (ValueError, TypeError):
                return False

        check(
            f"derived_{index}_{wanted['operation']}_independent_value",
            any(matches_derived(v) for v in materialized),
            wanted["value"],
        )

    for plot in expected.get("plots", []):
        problems = []
        for rid in plot["runIds"]:
            source = oracle["outputs"].get((rid, plot["id"]))
            observed = [
                o
                for t in comparisons
                for o in t.get("outputs", [])
                if o.get("outputId") == plot["id"] and o.get("ref", {}).get("runId") == rid
            ]
            valid = False
            for output in observed:
                good = (
                    bool(source)
                    and ref_ok(output.get("ref"))
                    and output.get("status") == source["status"]
                    and output.get("sourceCount") == source.get("sourceCount")
                )
                if source and source["status"] == "UNAVAILABLE":
                    good = good and output.get("reason") == source.get("reason") and not output.get("extrema")
                elif source:
                    good = good and close(
                        (output.get("extrema", {}).get("maximum") or {}).get("value"), source.get("maximum")
                    )
                valid = valid or good
            if not valid:
                problems.append(rid)
        # Snapshot exposes provenance and extrema; full plot samples/rendering are separate UI evidence.
        check(f"plot_{plot['id']}_source_metadata", not problems, {"invalidRuns": problems[:12]})

    expected_actions = case.get("hitl", [])
    check(
        "hitl_interaction_count",
        len(interactions) == len(expected_actions),
        {"expected": len(expected_actions), "actual": len(interactions)},
    )
    accepted = [e.get("input", {}).get("type") for e in view.get("inputEvents", [])]
    check("hitl_server_accepted_actions", accepted == [a["type"] for a in expected_actions], accepted)
    for index, (wanted, interaction) in enumerate(zip(expected_actions, interactions), 1):
        pending = interaction.get("pending") or {}
        posted = interaction.get("input") or {}
        wrapper = posted
        if isinstance(posted.get("input"), dict):
            posted = posted["input"]
        options = interaction.get("options") or {}
        option_rows = options.get("options", []) if isinstance(options, dict) else options
        option_keys = {o.get("key"): o.get("ref", {}).get("runId") for o in option_rows}
        check(
            f"hitl_{index}_actually_requested",
            interaction.get("type") == wanted["type"]
            and pending.get("type") == wanted["type"]
            and bool(pending.get("id"))
            and posted.get("type") == wanted["type"],
        )
        check(
            f"hitl_{index}_same_request",
            (interaction.get("requestId", view.get("requestId")) == view.get("requestId"))
            and (
                not isinstance(options, dict)
                or options.get("requestId", view.get("requestId")) == view.get("requestId")
            )
            and wrapper.get("pendingInputId", pending.get("id")) == pending.get("id"),
        )
        if wanted["type"] == "run_selection":
            check(
                f"hitl_{index}_exact_selection_limits",
                pending.get("minSelections") == wanted["min"]
                and pending.get("maxSelections") == wanted.get("max"),
            )
            chosen = [option_keys.get(key) for key in posted.get("runKeys", [])]
            check(
                f"hitl_{index}_user_chose_requested_runs",
                len(chosen) == len(wanted["runIds"]) and set(chosen) == set(wanted["runIds"]),
                chosen,
            )
            candidate_ids = (
                set(expected["searches"][-1]["runIds"]) if expected.get("searches") else set(oracle["byId"])
            )
            selectable = [o for o in option_rows if o.get("selectable") is True]
            check(
                f"hitl_{index}_candidate_scope",
                len(selectable) == len(candidate_ids)
                and {o.get("ref", {}).get("runId") for o in selectable} == candidate_ids
                and all(ref_ok(o.get("ref")) for o in selectable),
            )
            bad_measurements = []
            measurement_fields = {
                f["field"]
                for s in expected.get("searches", [])[-1:]
                for f in s["filters"]
                if f["field"] in ("ionFlux", "meanIonEnergy", "iedWidth")
            }
            for option in selectable:
                rid = option["ref"]["runId"]
                for field in measurement_fields:
                    datum = option.get("searchMeasurements", {}).get(field) or {}
                    try:
                        good = close(
                            canonical(field, datum.get("value"), datum.get("unit")),
                            raw_value(oracle["byId"][rid], field),
                        )
                    except (TypeError, ValueError):
                        good = False
                    if not good:
                        bad_measurements.append((rid, field))
            check(f"hitl_{index}_search_values_shown", not bad_measurements, bad_measurements[:12])
        else:
            if wanted.get("baselineRunId"):
                check(
                    f"hitl_{index}_baseline_choice",
                    "baselineKey" in pending.get("fields", [])
                    and key_ids.get(posted.get("baselineKey")) == wanted["baselineRunId"]
                    and posted.get("baselineKey") in pending.get("allowedRunKeys", []),
                )
            if wanted.get("trendAxis"):
                check(
                    f"hitl_{index}_trend_axis_choice",
                    "trendAxis" in pending.get("fields", [])
                    and posted.get("trendAxis") == wanted["trendAxis"]
                    and posted.get("trendAxis") in pending.get("allowedTrendAxes", []),
                )

    if expected.get("general"):
        check("general_answer_without_run_tools", not tools)
    if expected.get("interpretation"):
        check("substantive_interpretation_present", len(answer.strip()) >= 40)
    allowed_partial = expected.get("expectedPartial") and all(
        s.get("status") in ("verified", "partial", "empty") for s in steps
    )
    check(
        "completion_or_expected_honest_data_limit",
        snapshot.get("hasIncompleteWork") is False or allowed_partial,
        {"hasIncompleteWork": snapshot.get("hasIncompleteWork"), "allowedPartial": bool(allowed_partial)},
    )
    for index, patterns in enumerate(expected.get("text", {}).get("requiredAny", []), 1):
        check(
            f"text_required_group_{index}",
            any(re.search(p, answer, re.IGNORECASE) for p in patterns),
            patterns,
        )
    for pattern in expected.get("text", {}).get("forbidden", []):
        check("text_forbidden", re.search(pattern, answer, re.IGNORECASE) is None, pattern)
    return {"pass": all(c["pass"] for c in checks), "checks": checks, "humanReviewRequired": human}


@lru_cache(maxsize=1)
def load_overrides():
    path = HERE / "oracle-overrides.json"
    return json.loads(path.read_text()) if path.exists() else {"overrides": {}, "oracleFiles": {}}


def _corrected_case(case):
    override = load_overrides()["overrides"].get(case["id"])
    if not override or case.get("sourceOracle", {}).get("files") != load_overrides()["oracleFiles"]:
        return case, None
    corrected = json.loads(json.dumps(case))
    corrected["expected"].update(override["expected"])
    return corrected, override


def load_cases():
    return [_corrected_case(case)[0] for case in load_cases_raw()]


def grade(case, view, interactions):
    corrected, override = _corrected_case(case)
    result = grade_raw(corrected, view, interactions)
    errors, count = [], 0
    for step_index, step in enumerate((view.get("answerSnapshot") or {}).get("stepResults", []), 1):
        tool = step.get("outputs", {}).get("toolResult")
        if not isinstance(tool, dict) or tool.get("kind") != "compare_runs":
            continue
        rows = {}
        for row in tool.get("runs", []):
            key = row.get("key")
            if not isinstance(key, str) or not key or key in rows:
                errors.append({"step": step_index, "reason": "missing_or_duplicate_run_key", "key": key})
            else:
                rows[key] = row
        for index, comparison in enumerate(tool.get("comparisons", []), 1):
            count += 1
            keys = (comparison.get("leftKey"), comparison.get("rightKey"))
            endpoints = [rows.get(key) if isinstance(key, str) and key else None for key in keys]
            if any(row is None for row in endpoints):
                reason = "missing_or_unknown_endpoint"
            elif endpoints[0].get("ref", {}).get("runId") == endpoints[1].get("ref", {}).get("runId"):
                reason = "self_comparison"
            else:
                continue
            errors.append(
                {
                    "step": step_index,
                    "comparison": index,
                    "id": comparison.get("id"),
                    "leftKey": keys[0],
                    "rightKey": keys[1],
                    "reason": reason,
                }
            )
    result["checks"].append(
        {
            "name": "comparison_endpoints_resolve_to_distinct_runs",
            "pass": not errors,
            "detail": {"comparisonsChecked": count, "errors": errors},
        }
    )
    result["pass"] = all(check["pass"] for check in result["checks"])
    result["oracleOverridesApplied"] = [case["id"]] if override else []
    result["answerReviewRequired"] = result["humanReviewRequired"] or bool(
        override and override.get("answerReviewRequired")
    )
    return result
