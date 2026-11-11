import math
from typing import Any

from ..contracts import CompareInputs
from ..metric_registry import CONDITION_KEYS, DEFAULT_METRICS, NUMERIC_POLICY_VERSION, UNITS, is_finite
from .common import DomainError, inputs_dict, is_usable, raw_value, run_ref, scalar, source_unit


def _source_values(baseline, target, metric):
    return {
        role: {
            "value": raw_value(run, metric) if is_finite(raw_value(run, metric)) else None,
            "unit": source_unit(run, metric),
        }
        for role, run in (("baseline", baseline), ("target", target))
    }


def _row(baseline, target, metric, *, condition=False):
    left, left_error = scalar(baseline, metric)
    right, right_error = scalar(target, metric)
    row = {
        ("field" if condition else "metric"): metric,
        "baseline": left,
        "target": right,
        "delta": None,
        "unit": UNITS[metric],
        "status": "UNAVAILABLE",
        "reason": None,
    }
    if not condition:
        row["percentChange"] = None
    errors = (left_error, right_error)
    if any(errors):
        if "UNIT_NOT_COMPARABLE" in errors:
            row["reason"] = "UNIT_NOT_COMPARABLE"
            row["sourceValues"] = _source_values(baseline, target, metric)
        elif "NUMERIC_OVERFLOW" in errors:
            row["reason"] = "NUMERIC_OVERFLOW"
            row["sourceValues"] = _source_values(baseline, target, metric)
        elif "INVALID_VALUE" in errors:
            row["reason"] = "INVALID_VALUE"
        else:
            row["reason"] = (
                "MISSING_BOTH"
                if left_error and right_error
                else "MISSING_BASELINE"
                if left_error
                else "MISSING_TARGET"
            )
        return row
    delta = right - left
    if not math.isfinite(delta):
        row["reason"] = "NUMERIC_OVERFLOW"
        return row
    row["delta"] = 0.0 if delta == 0 else delta
    row["status"] = "AVAILABLE"
    if condition:
        return row
    if left == 0:
        row.update(status="PERCENT_UNAVAILABLE", reason="ZERO_BASELINE")
        return row
    percent = (delta / abs(left)) * 100
    if not math.isfinite(percent):
        row.update(status="PERCENT_UNAVAILABLE", reason="NUMERIC_OVERFLOW")
    else:
        row["percentChange"] = 0.0 if percent == 0 else percent
    return row


def compare_runs(inputs, baseline, target):
    query = CompareInputs.model_validate(inputs_dict(inputs))
    baseline_ref, target_ref = run_ref(baseline), run_ref(target)
    if baseline_ref == target_ref:
        raise DomainError("SAME_RUN_REFERENCE")
    if not is_usable(baseline) or not is_usable(target):
        raise DomainError("DATA_NOT_COMPARABLE")
    metrics = query.metrics if query.metrics is not None else DEFAULT_METRICS
    conditions = [_row(baseline, target, key, condition=True) for key in CONDITION_KEYS]
    rows = [_row(baseline, target, metric) for metric in metrics]
    if not any(row["delta"] is not None for row in rows):
        status = "NO_COMPARABLE_DATA"
    elif any(row["status"] != "AVAILABLE" for row in [*conditions, *rows]):
        status = "COMPARISON_PARTIAL"
    else:
        status = "COMPARISON_READY"
    return {
        "kind": "compare_runs",
        "resultStatus": status,
        "baseline": baseline_ref,
        "target": target_ref,
        "conditions": conditions,
        "changedConditions": [
            row["field"] for row in conditions if row["delta"] is not None and row["delta"] != 0
        ],
        "metrics": rows,
        "quality": {
            role: {key: run[key] for key in ("qualityStatus", "convergenceStatus", "catalogStatus")}
            for role, run in (("baseline", baseline), ("target", target))
        },
        "usedRunRefs": [baseline_ref, target_ref],
        "numericPolicyVersion": NUMERIC_POLICY_VERSION,
    }


def datum(value, unit, reason=None, source=None):
    return {
        "value": value if reason is None else None,
        "unit": unit,
        "status": "AVAILABLE" if reason is None else "UNAVAILABLE",
        "reason": reason,
        "sourceValue": source,
    }


def run_datum(run, metric):
    value, error = scalar(run, metric)
    raw = raw_value(run, metric)
    source = {"value": raw if is_finite(raw) else None, "unit": source_unit(run, metric)}
    if not is_usable(run):
        error = "INSUFFICIENT_DATA"
    return datum(value, UNITS[metric], error, source)


def compare_selected(inputs, entries, outputs=None):
    """Deterministic selected-version comparison. No implicit catalog or baseline."""
    from ..answer_contracts import ComparisonResultV2, ComparisonResultV3
    from ..comparison_catalog import comparison_plan, FIELD_META, COORDINATE_FIELDS, FEATURE_POLICY
    from ..tools import CompareToolInputs
    from .comparison_evidence import observations

    query = CompareToolInputs.model_validate(inputs)
    keys = [e["key"] for e in entries]
    refs = [e["ref"] for e in entries]
    if len(entries) < 2 or len(set(keys)) != len(keys) or len({tuple(r.items()) for r in refs}) != len(refs):
        raise DomainError("INVALID_COMPARISON_SELECTION")
    if any(run_ref(e["run"]) != e["ref"] for e in entries):
        raise DomainError("RESULT_SOURCE_MISMATCH")
    if query.baseline_key is not None and query.baseline_key not in keys:
        raise DomainError("INVALID_BASELINE_KEY")
    extended = query.comparison_fields is not None or query.plot_ids is not None
    metrics, plots, needed = comparison_plan(inputs)
    units = {m: FIELD_META[m]["unit"] for m in metrics}
    by_ref = {}
    for output in outputs or []:
        meta = output["metadata"]
        if meta["ref"] not in refs or meta["outputId"] not in needed:
            raise DomainError("RESULT_SOURCE_MISMATCH")
        identity = (meta["ref"]["runId"], meta["ref"]["runVersionId"], meta["outputId"])
        if identity in by_ref:
            raise DomainError("RESULT_SOURCE_MISMATCH")
        by_ref[identity] = output
    def feature(entry, metric):
        if "." not in metric:
            return run_datum(entry["run"], metric)
        output = by_ref.get((entry["ref"]["runId"], entry["ref"]["runVersionId"], FIELD_META[metric]["plotId"]), {})
        value = output.get("features", {}).get(metric)
        if value is None:
            return datum(None, units[metric], "INSUFFICIENT_DATA")
        if value["unit"] != units[metric]:
            return datum(None, units[metric], "UNIT_NOT_COMPARABLE")
        return value
    rows = [
        {
            "key": e["key"],
            "ref": e["ref"],
            "conditions": {m: run_datum(e["run"], m) for m in CONDITION_KEYS},
            "metrics": {m: feature(e, m) for m in metrics},
            "quality": {
                k: e["run"].get(k, "UNKNOWN") for k in ("convergenceStatus", "qualityStatus", "catalogStatus")
            },
        }
        for e in entries
    ]
    comparisons = []

    def difference(left, right, metric, kind):
        signed = kind != "absolute_difference"
        a, b = left["metrics"][metric], right["metrics"][metric]
        error = None
        if a["status"] != "AVAILABLE" or b["status"] != "AVAILABLE":
            errors = [x["reason"] for x in (a, b) if x["reason"]]
            error = next(
                (
                    e
                    for e in errors
                    if e in ("UNIT_NOT_COMPARABLE", "INVALID_VALUE", "NUMERIC_OVERFLOW", "INSUFFICIENT_DATA")
                ),
                "MISSING_BOTH"
                if len(errors) == 2
                else "MISSING_BASELINE"
                if a["reason"]
                else "MISSING_TARGET",
            )
        delta = None if error else b["value"] - a["value"]
        if error is None and not is_finite(delta):
            error = "NUMERIC_OVERFLOW"
        diff = datum(delta if signed or delta is None else abs(delta), units[metric], error)
        percent = None
        if signed and metric not in COORDINATE_FIELDS:
            if error:
                percent = datum(None, "%", error)
            elif a["value"] == 0:
                percent = datum(None, "%", "ZERO_BASELINE")
            else:
                ratio = (delta / abs(a["value"])) * 100
                percent = datum(ratio, "%") if is_finite(ratio) else datum(None, "%", "NUMERIC_OVERFLOW")
        direction = (
            "unavailable"
            if error or delta is None
            else "not_applicable"
            if not signed
            else ("increase" if delta > 0 else "decrease" if delta < 0 else "unchanged")
        )
        row = {
            "id": f"{kind}:{left['key']}:{right['key']}:{metric}",
            "kind": kind,
            "leftKey": left["key"],
            "rightKey": right["key"],
            "metric": metric,
            "difference": diff,
            "percentChange": percent,
            "direction": direction,
        }
        comparisons.append(row)
        return row

    mode = (
        "values"
        if query.analysis == "values"
        else "trend"
        if query.analysis == "trend"
        else ("baseline" if query.baseline_key else "pair" if len(rows) == 2 else "overview")
    )
    if mode == "baseline":
        baseline = next(r for r in rows if r["key"] == query.baseline_key)
        for target in rows:
            if target is not baseline:
                for metric in metrics:
                    difference(baseline, target, metric, "baseline_delta")
    elif mode == "pair":
        for metric in metrics:
            difference(rows[0], rows[1], metric, "absolute_difference")
    summaries = []
    for metric in metrics:
        available = [r for r in rows if r["metrics"][metric]["status"] == "AVAILABLE"]
        values = [r["metrics"][metric]["value"] for r in available]
        minimum, maximum = (min(values), max(values)) if values else (None, None)
        span = maximum - minimum if len(values) >= 2 and maximum is not None and minimum is not None else None
        summaries.append(
            {
                "id": f"summary:{metric}",
                "metric": metric,
                "availableCount": len(values),
                "minimum": datum(minimum, units[metric], None if values else "INSUFFICIENT_DATA"),
                "minimumKeys": [r["key"] for r in available if r["metrics"][metric]["value"] == minimum],
                "maximum": datum(maximum, units[metric], None if values else "INSUFFICIENT_DATA"),
                "maximumKeys": [r["key"] for r in available if r["metrics"][metric]["value"] == maximum],
                "range": datum(
                    span,
                    units[metric],
                    "INSUFFICIENT_DATA"
                    if span is None
                    else ("NUMERIC_OVERFLOW" if not is_finite(span) else None),
                ),
            }
        )
    trends = []
    if mode == "trend":
        axis = query.trend_axis
        if axis is None:
            raise DomainError("MISSING_TREND_AXIS")
        fixed = [k for k in CONDITION_KEYS if k != axis]
        groups: dict[tuple, list[dict[str, Any]]] = {}
        for row in rows:
            signature = tuple(row["conditions"][k]["value"] for k in fixed)
            # Missing conditions cannot establish a controlled comparison group.
            if any(row["conditions"][k]["status"] != "AVAILABLE" for k in CONDITION_KEYS):
                signature = (*signature, row["key"])
            groups.setdefault(signature, []).append(row)
        for index, group in enumerate(groups.values()):
            ordered = sorted(
                group,
                key=lambda r: (r["conditions"][axis]["value"] is None, r["conditions"][axis]["value"] or 0),
            )
            axis_values = [r["conditions"][axis]["value"] for r in ordered]
            for metric in metrics:
                ids = []
                if len(ordered) < 2:
                    direction = "insufficient_data"
                elif None in axis_values or len(set(axis_values)) != len(axis_values):
                    direction = "unavailable"
                else:
                    changes = [
                        difference(a, b, metric, "adjacent_delta") for a, b in zip(ordered, ordered[1:])
                    ]
                    ids = [c["id"] for c in changes]
                    directions = {c["direction"] for c in changes}
                    direction = (
                        "unavailable"
                        if "unavailable" in directions
                        else "constant"
                        if directions == {"unchanged"}
                        else "increasing"
                        if directions <= {"increase", "unchanged"}
                        else "decreasing"
                        if directions <= {"decrease", "unchanged"}
                        else "non_monotonic"
                    )
                trends.append(
                    {
                        "id": f"trend:{index}:{metric}",
                        "metric": metric,
                        "axis": axis,
                        "fixedConditions": {k: ordered[0]["conditions"][k] for k in fixed},
                        "orderedKeys": [r["key"] for r in ordered],
                        "comparisonIds": ids,
                        "direction": direction,
                    }
                )
    scalar_data = [r["metrics"][m] for r in rows for m in metrics]
    if mode == "values":
        comparable = any(d["status"] == "AVAILABLE" for d in scalar_data)
        summaries = []
    elif mode in ("pair", "baseline"):
        comparable = any(c["difference"]["status"] == "AVAILABLE" for c in comparisons)
    elif mode == "trend":
        comparable = any(t["direction"] not in ("unavailable", "insufficient_data") for t in trends)
    else:
        comparable = any(s["range"]["status"] == "AVAILABLE" for s in summaries)
    partial = any(d["status"] != "AVAILABLE" for d in scalar_data)
    partial |= any(d["status"] != "AVAILABLE" for r in rows for d in r["conditions"].values())
    partial |= any(
        d["difference"]["status"] != "AVAILABLE"
        or (d["percentChange"] is not None and d["percentChange"]["status"] != "AVAILABLE")
        for d in comparisons
    )
    partial |= any(t["direction"] in ("unavailable", "insufficient_data") for t in trends)
    result = {
        "kind": "compare_runs",
        "resultStatus": "NO_COMPARABLE_DATA"
        if not comparable
        else ("COMPARISON_PARTIAL" if partial else "COMPARISON_READY"),
        "mode": mode,
        "metricIds": metrics,
        "baselineKey": query.baseline_key,
        "trendAxis": query.trend_axis,
        "runs": rows,
        "comparisons": comparisons,
        "summaries": summaries,
        "trends": trends,
        "observations": [],
        "usedRunRefs": refs,
        "numericPolicyVersion": "v1",
        "aggregationPolicyVersion": "multi-run-1",
    }
    if extended:
        result.update(plotIds=plots, outputs=[o["metadata"] for o in outputs or []], featurePolicyVersion=FEATURE_POLICY)
    result["observations"] = observations(result)
    return (ComparisonResultV3 if extended else ComparisonResultV2).model_validate(result).model_dump()
