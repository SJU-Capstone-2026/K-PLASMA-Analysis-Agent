"""Compute derived search inputs from verified, unit-aware quantities."""

import math
from statistics import fmean
from typing import Literal

from ..metric_registry import UNITS, normalize_value
from .contracts import Operation, Quantity

DifferenceDirection = Literal["absolute", "first_minus_second", "second_minus_first"]


def compute_derived(
    operation: Operation, operands: list[Quantity], *, direction: DifferenceDirection | None = None,
) -> Quantity:
    if not operands:
        raise ValueError("derivation requires verified operands")
    if operation in {"difference", "scale", "ratio"} and len(operands) != 2:
        raise ValueError(f"{operation} requires exactly two operands")
    first = operands[0]
    sources = list(dict.fromkeys(evidence for q in operands for evidence in q.evidence_ids))
    quantities = operands[:1] if operation == "scale" else operands
    if any(q.field != first.field for q in quantities):
        raise ValueError("operands must represent the same physical quantity")
    if first.field == "ratio":
        if any(q.unit != "1" for q in quantities):
            raise ValueError("dimensionless operands require unit 1")
        values = [q.value for q in quantities]
        unit = "1"
    else:
        if any(q.unit is None for q in quantities):
            raise ValueError("verified physical operands must have a unit")
        values = [normalize_value(q.field, q.value, q.unit) for q in quantities]
        unit = UNITS[first.field]

    if operation == "min":
        result = min(values)
    elif operation == "max":
        result = max(values)
    elif operation == "mean":
        result = fmean(values)
    elif operation == "difference":
        if direction == "absolute":
            result = abs(values[0] - values[1])
        elif direction == "first_minus_second":
            result = values[0] - values[1]
        elif direction == "second_minus_first":
            result = values[1] - values[0]
        else:
            raise ValueError("difference requires a direction")
    elif operation == "scale":
        factor = operands[1]
        if factor.unit != "1":
            raise ValueError("scale factor must be dimensionless")
        result = values[0] * factor.value
    elif operation == "ratio":
        if values[1] == 0:
            raise ValueError("ratio denominator is zero")
        result = values[0] / values[1]
        return Quantity(value=result, field="ratio", unit="1", evidence_ids=sources)
    else:
        raise ValueError(f"unsupported derivation: {operation}")
    if not math.isfinite(result):
        raise ValueError("derived value is not finite")
    return Quantity(value=result, field=first.field, unit=unit, evidence_ids=sources)
