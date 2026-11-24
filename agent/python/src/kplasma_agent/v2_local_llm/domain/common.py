"""Shared scalar extraction. Quality failures never turn into fabricated data."""

import math
from copy import deepcopy

from pydantic import BaseModel

from ..metric_registry import CONDITION_KEYS, OUTPUT_METRICS, UNITS, NumericError, is_finite, normalize_value


class DomainError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def inputs_dict(inputs):
    return inputs.model_dump(exclude_none=True) if isinstance(inputs, BaseModel) else deepcopy(inputs)


def run_ref(run):
    if (
        not isinstance(run.get("runId"), str)
        or not run.get("runId")
        or not isinstance(run.get("runVersionId"), str)
        or not run.get("runVersionId")
    ):
        raise DomainError("DATA_REFERENCE_UNAVAILABLE", "Run ID and exact version are required")
    return {"runId": run["runId"], "runVersionId": run["runVersionId"]}


def is_usable(run):
    return all(
        run.get(key) == value
        for key, value in (
            ("qualityStatus", "VERIFIED"),
            ("convergenceStatus", "CONVERGED"),
            ("catalogStatus", "READY"),
        )
    )


def raw_value(run, metric):
    return run.get(metric) if metric in CONDITION_KEYS else (run.get("metrics") or {}).get(metric)


def source_unit(run, metric):
    unit = (run.get("units") or {}).get(metric)
    return UNITS[metric] if unit is None else unit


def scalar(run, metric):
    value = raw_value(run, metric)
    if value is None:
        return None, (run.get("metricAvailability") or {}).get(metric, "MISSING_VALUE")
    try:
        return normalize_value(metric, value, source_unit(run, metric)), None
    except NumericError as error:
        return None, error.code


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def public_run(run):
    """Copy scalar snapshots with canonical units, keeping metadata and availability."""
    result = _json_safe(deepcopy(run))
    result.setdefault("metrics", {})
    result.setdefault("units", {})
    availability = {}
    for metric in (*CONDITION_KEYS, *OUTPUT_METRICS):
        value, reason = scalar(run, metric)
        if metric in CONDITION_KEYS:
            result[metric] = value
        else:
            result["metrics"][metric] = value
        result["units"][metric] = UNITS[metric]
        if reason:
            availability[metric] = reason
    if availability:
        result["metricAvailability"] = availability
    return result


def presentation_score(run):
    value = run.get("presentationScore")
    return value if is_finite(value) else 0


def run_id_key(run):
    """Stable lexical ID order, case insensitive primary with lowercase-first ties."""
    value = run["runId"]
    return (value.casefold(), tuple(c.isupper() for c in value), value)


def used_refs(runs):
    refs = []
    seen = set()
    for run in runs:
        ref = run_ref(run)
        key = (ref["runId"], ref["runVersionId"])
        if key not in seen:
            refs.append(ref)
            seen.add(key)
    return refs
