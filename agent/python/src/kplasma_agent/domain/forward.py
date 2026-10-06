import math
from decimal import Decimal

from ..contracts import ForwardInputs
from ..metric_registry import CONDITION_KEYS, NUMERIC_POLICY_VERSION, UNITS, normalize_value
from .common import DomainError, inputs_dict, is_usable, public_run, run_ref, scalar


def lookup_forward(inputs, ordered_runs):
    query = ForwardInputs.model_validate(inputs_dict(inputs))
    requested = {}
    defaulted_units = []
    for metric in CONDITION_KEYS:
        item = getattr(query.conditions, metric)
        if item is None:
            raise DomainError("MISSING_INPUT", f"conditions.{metric}")
        if not item.unit:
            raise DomainError("MISSING_UNIT", metric)
        requested[metric] = normalize_value(metric, item.value, item.unit)
    if query.context_rules:
        raise DomainError("UNRESOLVED_CONTEXT", "Apply context rules before domain execution")
    eligible, excluded = [], []
    for run in ordered_runs:
        ref = run_ref(run)
        reasons = []
        if not is_usable(run):
            reasons.append({"code": "DATA_NOT_COMPARABLE"})
        for metric in CONDITION_KEYS:
            _, reason = scalar(run, metric)
            if reason:
                reasons.append({"metric": metric, "code": reason})
        if reasons:
            excluded.append({**ref, "reasons": reasons})
        else:
            eligible.append(run)
    selected = next(
        (r for r in eligible if all(scalar(r, k)[0] == requested[k] for k in CONDITION_KEYS)), None
    )
    status = "EXACT" if selected else "NO_DATA"
    if selected is None and eligible:
        scales = {"pressure": 10, "sourcePower": 500, "biasPower": 1000}

        # Preserve binary64 comparison and ties for ordinary inputs. Only an
        # overflowing distance needs Decimal to order two otherwise infinite
        # candidates. Any finite distance always ranks ahead of those candidates.
        def distance(run):
            try:
                numeric = sum(
                    ((scalar(run, key)[0] - requested[key]) / scales[key]) ** 2 for key in CONDITION_KEYS
                )
            except OverflowError:
                numeric = math.inf
            if math.isfinite(numeric):
                return (0, numeric)
            precise = sum(
                ((Decimal.from_float(scalar(run, key)[0]) - Decimal.from_float(requested[key])) / scales[key])
                ** 2
                for key in CONDITION_KEYS
            )
            return (1, precise)

        selected = min(eligible, key=distance)
        status = "NEAREST_ONLY"
    output_run = public_run(selected) if selected else None
    deltas = None
    if selected:
        deltas = {}
        for key in CONDITION_KEYS:
            delta = scalar(selected, key)[0] - requested[key]
            if not math.isfinite(delta):
                raise DomainError("NUMERIC_OVERFLOW", f"condition delta: {key}")
            deltas[key] = 0.0 if delta == 0 else delta
    return {
        "kind": "forward_lookup",
        "resultStatus": status,
        "status": status,
        "run": output_run,
        "selectedRun": output_run,
        "candidates": [output_run] if output_run else [],
        "deltas": deltas,
        "requestedConditions": requested,
        "units": dict(UNITS),
        "usedRunRefs": [run_ref(selected)] if selected else [],
        "excludedRuns": excluded,
        "defaultedUnits": defaulted_units,
        "numericPolicyVersion": NUMERIC_POLICY_VERSION,
    }
