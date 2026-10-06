"""Deterministic hard filtering, per-objective groups and ordered soft goals."""

import math
from decimal import Decimal

from ..contracts import ReverseInputs
from ..metric_registry import NUMERIC_POLICY_VERSION, OUTPUT_METRICS, UNITS, normalize_value
from .common import (
    DomainError,
    inputs_dict,
    is_usable,
    presentation_score,
    public_run,
    run_id_key,
    run_ref,
    scalar,
    used_refs,
)


def _normalized_query(inputs):
    query = ReverseInputs.model_validate(inputs_dict(inputs))
    if query.context_rules:
        raise DomainError("UNRESOLVED_CONTEXT", "Apply context rules before domain execution")
    constraints, goals, defaulted = [], [], []
    for collection, output in ((query.constraints, constraints), (query.goals, goals)):
        for model in collection:
            item = model.model_dump(exclude_none=True)
            metric, unit = model.metric, model.unit
            numeric = any(key in item for key in ("value", "min", "max"))
            if numeric and not unit:
                raise DomainError("MISSING_UNIT", metric)
            # A pure high/low ranking uses the registry unit internally.
            normalize_value(metric, 0, unit)
            for key in ("value", "min", "max"):
                if key in item:
                    item[key] = normalize_value(metric, item[key], unit)
            item["unit"] = UNITS[metric]
            output.append(item)
    return constraints, goals, defaulted


def normalized_reverse_query(inputs):
    """Validated canonical predicates for the backend's whitelisted SQL builder."""
    constraints, goals, _ = _normalized_query(inputs)
    if not constraints and not goals:
        raise DomainError("MISSING_INPUT", "At least one constraint or goal is required")
    return {"constraints": constraints, "goals": goals}


def check_rule(value, rule):
    if value is None:
        return False
    operator = rule["operator"]
    if operator == "between":
        return rule["min"] <= value <= rule["max"]
    boundary = rule["value"]
    return {
        "eq": lambda: value == boundary,
        "lt": lambda: value < boundary,
        "lte": lambda: value <= boundary,
        "gt": lambda: value > boundary,
        "gte": lambda: value >= boundary,
    }[operator]()


def _finite(value):
    return value if math.isfinite(value) else None


def _percent(delta, denominator):
    return _finite(delta / abs(denominator) * 100) if delta is not None and denominator else None


def _stable_delta(value, digits=6):
    if not math.isfinite(value):
        return None
    if abs(value) > 1e15:
        return value
    scale = 10**digits
    rounded = math.floor(value * scale + 0.5) / scale
    return 0.0 if rounded == 0 else rounded


def _midpoint(lower, upper):
    return lower / 2 + upper / 2


def _objective(rule, index):
    operators = {"gte": "MIN", "gt": "MIN", "lte": "MAX", "lt": "MAX", "between": "RANGE", "eq": "EQUAL"}
    return {
        **rule,
        "id": f"objective-{index + 1}",
        "comparisonOperator": rule["operator"],
        "operator": operators[rule["operator"]],
    }


def evaluate_objective(run, objective):
    actual, error = scalar(run, objective["metric"])
    op = objective["comparisonOperator"]
    rule = {**objective, "operator": op}
    satisfied = check_rule(actual, rule)
    boundary_delta, percent, range_status = None, None, None
    if op == "between":
        low, high = objective["min"], objective["max"]
        target_label = f"{low:g}–{high:g}"
        if satisfied:
            range_status = "IN_RANGE"
        elif actual is None:
            range_status = "UNAVAILABLE"
        else:
            boundary = low if actual < low else high
            boundary_delta = _stable_delta(-abs(actual - boundary))
            percent = _percent(boundary_delta, boundary)
            range_status = "BELOW_RANGE" if actual < low else "ABOVE_RANGE"
    else:
        boundary = objective["value"]
        target_label = f"{ {'eq': '=', 'gte': '≥', 'gt': '>', 'lte': '≤', 'lt': '<'}[op] } {boundary:g}"
        if actual is not None:
            raw_delta = boundary - actual if op in ("lt", "lte") else actual - boundary
            boundary_delta = _stable_delta(raw_delta)
            percent = _percent(boundary_delta, boundary)
    reference = _midpoint(objective["min"], objective["max"]) if op == "between" else objective["value"]
    return {
        "objectiveId": objective["id"],
        "metric": objective["metric"],
        "operator": objective["operator"],
        "comparisonOperator": op,
        "unit": objective["unit"],
        "actual": actual,
        "satisfied": satisfied,
        "targetLabel": target_label,
        "boundaryDelta": boundary_delta,
        "percentDelta": percent,
        "rangeStatus": range_status,
        "baselineDelta": None,
        "baselinePercentDelta": None,
        "unavailableReason": error,
        "referenceValue": reference,
        "matchPercent": math.floor(_closeness(actual, objective) + 0.5),
    }


def _closeness(actual, objective):
    if actual is None:
        return 0.0
    reference = (
        _midpoint(objective["min"], objective["max"])
        if objective["comparisonOperator"] == "between"
        else objective["value"]
    )
    if reference == 0:
        return 100.0 if actual == 0 else 0.0
    return max(0.0, 100 - abs(actual - reference) / abs(reference) * 100)


def _goal_key(run, goal):
    actual = scalar(run, goal["metric"])[0]
    if goal["direction"] == "maximize":
        return (0, -actual)
    if goal["direction"] == "minimize":
        return (0, actual)
    low, high = goal["min"], goal["max"]
    if low <= actual <= high:
        return (0, abs(Decimal.from_float(actual) - Decimal.from_float(_midpoint(low, high))))
    boundary = low if actual < low else high
    return (1, abs(Decimal.from_float(actual) - Decimal.from_float(boundary)))


def _objective_key(entry, objective):
    actual = scalar(entry["run"], objective["metric"])[0]
    op = objective["comparisonOperator"]
    if op == "between":
        distance = abs(
            Decimal.from_float(actual) - Decimal.from_float(_midpoint(objective["min"], objective["max"]))
        )
    elif op in ("gt", "gte"):
        distance = -actual
    else:
        distance = actual
    return (distance, -presentation_score(entry["run"]), run_id_key(entry["run"]))


def _violation(run, rule):
    actual, error = scalar(run, rule["metric"])
    if error:
        return {
            "metric": rule["metric"],
            "operator": rule["operator"],
            "actual": None,
            "required": None,
            "delta": None,
            "unit": rule["unit"],
            "reason": error,
        }
    if check_rule(actual, rule):
        return None
    if rule["operator"] == "between":
        nearest = rule["min"] if actual < rule["min"] else rule["max"]
        required = f"{rule['min']:g}–{rule['max']:g}"
    else:
        nearest = rule["value"]
        required = f"{rule['operator']} {nearest:g}"
    delta = _stable_delta(actual - nearest, digits=3)
    return {
        "metric": rule["metric"],
        "operator": rule["operator"],
        "actual": actual,
        "required": required,
        "delta": delta,
        "unit": rule["unit"],
        "reason": None if delta is not None else "NUMERIC_OVERFLOW",
    }


def search_reverse(inputs, ordered_runs):
    constraints, goals, defaulted_units = _normalized_query(inputs)
    if not constraints and not goals:
        raise DomainError("MISSING_INPUT", "At least one constraint or goal is required")
    objectives = [
        _objective(rule, index) for index, rule in enumerate(constraints) if rule["metric"] in OUTPUT_METRICS
    ]
    required = list(dict.fromkeys([r["metric"] for r in constraints] + [g["metric"] for g in goals]))
    usable, common_eligible, excluded = [], [], []
    for source in ordered_runs:
        ref = run_ref(source)
        if not is_usable(source):
            excluded.append({**ref, "reasons": [{"code": "DATA_NOT_COMPARABLE"}]})
            continue
        run = public_run(source)
        usable.append(run)
        # Record errors from the original source, before its public null encoding.
        reasons = [
            {"metric": metric, "code": error} for metric in required if (error := scalar(source, metric)[1])
        ]
        if reasons:
            excluded.append({**ref, "reasons": reasons})
        else:
            common_eligible.append(run)
    entries = [
        {"run": run, "evaluations": [evaluate_objective(run, objective) for objective in objectives]}
        for run in usable
    ]
    for entry in entries:
        scores = [evaluation["matchPercent"] for evaluation in entry["evaluations"]]
        entry["matchPercent"] = math.floor(sum(scores) / len(scores) + 0.5) if scores else 0
    entries_by_ref = {(entry["run"]["runId"], entry["run"]["runVersionId"]): entry for entry in entries}
    combined = []
    for run in common_eligible:
        if all(check_rule(scalar(run, rule["metric"])[0], rule) for rule in constraints):
            entry = entries_by_ref[(run["runId"], run["runVersionId"])]
            entry["closeness"] = (
                sum(_closeness(scalar(run, o["metric"])[0], o) for o in objectives) / len(objectives)
                if objectives
                else 0.0
            )
            combined.append(entry)
    combined.sort(
        key=lambda entry: (
            tuple(_goal_key(entry["run"], goal) for goal in goals),
            -entry["closeness"],
            -presentation_score(entry["run"]),
            run_id_key(entry["run"]),
        )
    )
    objective_results = []
    for objective in objectives:
        selected = [
            entry
            for entry in entries
            if any(e["objectiveId"] == objective["id"] and e["satisfied"] for e in entry["evaluations"])
        ]
        selected.sort(key=lambda entry: _objective_key(entry, objective))
        objective_results.append(
            {"objective": objective, "candidates": selected, "allConstraintsGuaranteed": False}
        )
    near_matches = []
    if not combined:
        for run in common_eligible:
            violations = [v for rule in constraints if (v := _violation(run, rule)) is not None]
            if violations:
                near_matches.append({"run": run, "violations": violations, "allConstraintsGuaranteed": False})
        # Mixed units are legacy display ranking only, never a physical distance.
        near_matches.sort(
            key=lambda entry: sum(
                Decimal.from_float(abs(v["delta"])) if v["delta"] is not None else Decimal("Infinity")
                for v in entry["violations"]
            )
        )
        near_matches = near_matches[:3]
    representatives = [entry["run"] for entry in combined]
    all_displayed = [
        *representatives,
        *(entry["run"] for group in objective_results for entry in group["candidates"]),
        *(entry["run"] for entry in near_matches),
    ]
    status = "MATCH" if representatives else "NO_MATCH"
    displayed_refs = used_refs(all_displayed)
    displayed_keys = {(ref["runId"], ref["runVersionId"]) for ref in displayed_refs}
    return {
        "kind": "reverse_search",
        "resultStatus": status,
        "status": status,
        "processMode": "RUN_SEARCH",
        "constraints": constraints,
        "goals": goals,
        "objectives": objectives,
        "totalCount": len(representatives),
        "allMatches": representatives,
        "candidates": representatives,
        "representativeCandidates": representatives,
        "commonCandidates": combined,
        "commonRunIds": [r["runId"] for r in representatives],
        "commonRecommendation": representatives[0] if representatives else None,
        "objectiveResults": objective_results,
        # Retain the field for compatibility with existing saved answer schemas.
        # Goals order common matches; they no longer create global candidate tabs.
        "goalResults": [],
        # Independent condition tabs need saved evaluations even outside common matches.
        "candidateEvaluations": [
            {
                **run_ref(entry["run"]),
                "evaluations": entry["evaluations"],
                "matchPercent": entry["matchPercent"],
            }
            for entry in entries
            if (entry["run"]["runId"], entry["run"]["runVersionId"]) in displayed_keys
        ],
        "nearMatches": near_matches,
        "nearMisses": near_matches,
        "usedRunRefs": displayed_refs,
        "excludedRuns": excluded,
        "defaultedUnits": defaulted_units,
        "numericPolicyVersion": NUMERIC_POLICY_VERSION,
    }
