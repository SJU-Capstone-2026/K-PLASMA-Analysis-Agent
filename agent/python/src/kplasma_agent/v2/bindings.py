"""Bind plan references to exact, verified data before a step can execute."""

import operator

from ..contracts import ForwardInputs, ReverseInputs
from ..metric_registry import UNITS, normalize_value
from ..tools import CompareToolInputs
from .contracts import (
    AwaitInputStep, CandidateScope, CompareStep, ContextRef, ContextSelectionScope, DecisionRecordStep, DeriveStep,
    ForwardStep,
    LiteralInput, Quantity, ResultRef, ReverseStep, RunScope, ScalarScope, StepResult, StepSpec,
)


class BlockedInput(ValueError):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"Required input unavailable: {field}")


def _available(results, step_id, field):
    result = results.get(step_id)
    if not result or result.status not in {"verified", "partial", "empty"}:
        raise BlockedInput(field)
    if field not in result.outputs or result.outputs[field] is None:
        raise BlockedInput(field)
    return result.outputs[field]


def _refs(value):
    if not isinstance(value, list):
        value = [value]
    return [item.get("ref", item) for item in value if isinstance(item, dict)]


def _bind(binding, context, results):
    if isinstance(binding, LiteralInput):
        return {"value": binding.value, "unit": binding.unit}
    if isinstance(binding, ContextRef):
        value = context.get(binding.key)
        if value is None:
            raise BlockedInput(binding.key)
        return value
    value = _available(results, binding.step_id, binding.field)
    scope = binding.scope
    if isinstance(scope, CandidateScope):
        if binding.field != "candidates" or not isinstance(value, list):
            raise BlockedInput(binding.field)
        return value
    if binding.field == "selection" and isinstance(scope, ScalarScope):
        return value
    if isinstance(scope, ScalarScope):
        if isinstance(value, list):
            raise BlockedInput(binding.field)
        return value
    refs = (_refs(_available(results, scope.step_id, "selection"))
            if not isinstance(scope, (RunScope, ContextSelectionScope)) else _refs(context.get(scope.key)))
    if not refs or not isinstance(value, list):
        raise BlockedInput(binding.field)
    matched = []
    for ref in refs:
        item = next((v for v in value if isinstance(v, dict) and v.get("run_ref") == ref), None)
        if item is None:
            raise BlockedInput(binding.field)
        matched.append(item)
    return matched[0] if isinstance(scope, RunScope) else matched


def _quantity(value, field):
    if not isinstance(value, dict) or "value" not in value or value.get("field", field) != field:
        raise BlockedInput(field)
    return {"value": value["value"], "unit": value.get("unit")}


def _bounds(row, bind):
    result = {}
    if getattr(row, "value", None) is not None:
        result.update(_quantity(bind(row.value), row.field))
    elif row.min is not None and row.max is not None:
        lower = _quantity(bind(row.min), row.field)
        upper = _quantity(bind(row.max), row.field)
        if lower["unit"] == upper["unit"]:
            result.update(min=lower["value"], max=upper["value"], unit=lower["unit"])
        else:
            result.update(min=normalize_value(row.field, lower["value"], lower["unit"]),
                          max=normalize_value(row.field, upper["value"], upper["unit"]),
                          unit=UNITS[row.field])
    return {"metric": row.field, **result}


def should_run(step: StepSpec, results: dict[str, StepResult]) -> bool:
    operations = {"eq": operator.eq, "lt": operator.lt, "lte": operator.le, "gt": operator.gt, "gte": operator.ge}
    for condition in step.run_if:
        result = results.get(condition.step_id)
        if result is None:
            raise BlockedInput(condition.field)
        value = result.status if condition.field == "status" else len(
            _available(results, condition.step_id, "candidates")
        )
        if not operations[condition.operator](value, condition.value):
            return False
    return True


def resolve_comparison_entries(step: CompareStep, context: dict, results: dict[str, StepResult]) -> list[dict]:
    run_input = step.inputs.runs
    runs = _refs(_bind(run_input, context, results))
    from_search = isinstance(run_input, ResultRef) and isinstance(run_input.scope, CandidateScope)
    if len(runs) < 2:
        raise BlockedInput("INSUFFICIENT_CANDIDATES" if from_search else "selected_runs")
    if len({ref["runVersionId"] for ref in runs}) != len(runs):
        raise BlockedInput("selected_runs")
    if from_search:
        return [{"key": f"R{index}", "ref": ref} for index, ref in enumerate(runs, 1)]
    available = context.get("comparison_entries", [])
    entries = []
    for ref in runs:
        entry = next((entry for entry in available if entry["ref"] == ref), None)
        if entry is None:
            raise BlockedInput("selected_runs")
        entries.append(entry)
    return entries


def resolve_inputs(step: StepSpec, context: dict, results: dict[str, StepResult]) -> dict:
    def bind(value):
        return _bind(value, context, results)

    if isinstance(step, CompareStep):
        entries = resolve_comparison_entries(step, context, results)

    for req in step.requires:
        value = _available(results, req.step_id, req.field)
        values = value if isinstance(value, list) else [value]
        if not values or any(v is None for v in values) or (req.count is not None and len(values) != req.count):
            raise BlockedInput(req.field)
        if req.unit is not None and any(not isinstance(v, dict) or v.get("unit") != req.unit for v in values):
            raise BlockedInput(req.field)
        if req.value_type == "quantity" and isinstance(value, list):
            raise BlockedInput(req.field)
        if req.value_type in {"quantities", "run_refs"} and not isinstance(value, list):
            raise BlockedInput(req.field)

    if isinstance(step, ForwardStep):
        source = {"pressure": step.inputs.pressure, "sourcePower": step.inputs.source_power,
                  "biasPower": step.inputs.bias_power}
        if any(value is None for value in source.values()):
            raise BlockedInput(next(key for key, value in source.items() if value is None))
        conditions = {key: _quantity(bind(value), key) for key, value in source.items()}
        return ForwardInputs.model_validate({"conditions": conditions}).model_dump(exclude_none=True)
    if isinstance(step, ReverseStep):
        constraints = [{**_bounds(row, bind), "operator": row.operator} for row in step.inputs.constraints]
        goals = []
        for goal in step.inputs.goals:
            bounds = _bounds(goal, bind)
            if goal.direction == "target_range":
                constraint = {**bounds, "operator": "between"}
                if constraint not in constraints:
                    constraints.append(constraint)
            else:
                goals.append({**bounds, "direction": goal.direction})
        return ReverseInputs.model_validate({"constraints": constraints, "goals": goals}).model_dump(exclude_none=True)
    if isinstance(step, CompareStep):
        baseline = bind(step.inputs.baseline) if step.inputs.baseline is not None else None
        axis = bind(step.inputs.trend_axis) if step.inputs.trend_axis is not None else None
        if isinstance(baseline, dict):
            baseline = next((e["key"] for e in entries if e["ref"] == baseline), None)
            if baseline is None:
                raise BlockedInput("baseline")
        options = CompareToolInputs.model_validate({
            "ref_keys": [e["key"] for e in entries], "comparison_fields": step.inputs.fields,
            "baseline_key": baseline, "trend_axis": axis.get("value") if isinstance(axis, dict) else axis,
            "plot_ids": step.inputs.plot_ids or None, "analysis": "trend" if axis else "auto",
        }).model_dump(exclude_none=True)
        inputs = {"runs": [entry["ref"] for entry in entries], "entries": entries, "options": options}
        run_input = step.inputs.runs
        if isinstance(run_input, ResultRef) and isinstance(run_input.scope, CandidateScope):
            inputs["candidateExecutionId"] = results[run_input.step_id].executionId
        return inputs
    if isinstance(step, DecisionRecordStep):
        runs = [{"runId": ref.get("runId"), "runVersionId": ref.get("runVersionId")}
                for ref in _refs(bind(step.inputs.runs))]
        if any(not isinstance(value, str) or not value for ref in runs for value in ref.values()):
            raise ValueError("decision records need fixed Run references")
        # Records are summarized per Run ID, so two versions of one Run cannot share a step.
        if len({ref["runId"] for ref in runs}) != len(runs):
            raise ValueError("decision records need distinct Runs")
        inputs = {"action": step.inputs.action, "runs": runs}
        run_input = step.inputs.runs
        if isinstance(run_input, ResultRef) and isinstance(run_input.scope, CandidateScope):
            inputs["candidateExecutionId"] = results[run_input.step_id].executionId
        return inputs
    if isinstance(step, DeriveStep):
        resolved = ([bind(v) for v in step.inputs.values] if isinstance(step.inputs.values, list)
                    else bind(step.inputs.values))
        values = resolved if isinstance(resolved, list) else [resolved]
        if any(v is None for v in values):
            raise BlockedInput("values")
        operands = []
        for value in values:
            if isinstance(value, dict) and value.get("unit") == "1" and "field" not in value:
                value = {**value, "field": "ratio"}
            operands.append(Quantity.model_validate(value).model_dump(mode="json"))
        return {"values": operands, "direction": step.inputs.direction}
    if isinstance(step, AwaitInputStep):
        return {"candidates": bind(step.inputs.candidates) if step.inputs.candidates is not None else None}
    raise TypeError("unknown plan step")
