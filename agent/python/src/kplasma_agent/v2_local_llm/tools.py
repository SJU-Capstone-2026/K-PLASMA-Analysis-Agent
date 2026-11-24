"""Validated tool inputs and compatibility for saved answers."""

from pydantic import model_validator

from .contracts import ConditionId, ForwardInputs, OutputMetric, ReverseInputs, StrictModel
from typing import Literal
from .comparison_catalog import ComparisonField, PlotId


class CompareToolInputs(StrictModel):
    ref_keys: list[str] | None = None
    metrics: list[OutputMetric] | None = None
    comparison_fields: list[ComparisonField] | None = None
    plot_ids: list[PlotId] | None = None
    analysis: Literal["auto", "values", "differences", "trend", "interpretation"] | None = None
    baseline_key: str | None = None
    trend_axis: ConditionId | None = None

    @model_validator(mode="after")
    def unique_lists(self):
        for values in (self.ref_keys, self.metrics, self.comparison_fields, self.plot_ids):
            if values is not None and (
                not values or len(set(values)) != len(values) or any(not v for v in values)
            ):
                raise ValueError("supplied lists must be nonempty and unique")
        if self.metrics is not None and self.comparison_fields is not None and self.metrics != self.comparison_fields:
            raise ValueError("metrics and comparison_fields conflict")
        return self


class GeneralInputs(StrictModel):
    pass


class DecisionRecordInputs(StrictModel):
    action: Literal["view", "exclude"]


TOOL_MODELS: dict[str, type[StrictModel]] = {
    "forward_lookup": ForwardInputs,
    "reverse_search": ReverseInputs,
    "compare_runs": CompareToolInputs,
    "generate_answer": GeneralInputs,
    "decision_records": DecisionRecordInputs,
}
