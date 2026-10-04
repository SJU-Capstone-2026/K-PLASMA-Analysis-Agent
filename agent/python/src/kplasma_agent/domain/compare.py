import math

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
