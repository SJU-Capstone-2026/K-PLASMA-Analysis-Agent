"""Schema-2 public answer contracts; no provider-native items or graph arrays."""

from typing import Literal
from .contracts import StrictModel, FiniteNumber, ConditionId, OutputMetric
from pydantic import Field, model_validator

Reason = Literal[
    "MISSING_VALUE",
    "MISSING_BASELINE",
    "MISSING_TARGET",
    "MISSING_BOTH",
    "ZERO_BASELINE",
    "INVALID_VALUE",
    "UNIT_NOT_COMPARABLE",
    "NUMERIC_OVERFLOW",
    "INSUFFICIENT_DATA",
]


class RunRef(StrictModel):
    runId: str
    runVersionId: str


class SourceValue(StrictModel):
    value: FiniteNumber | None
    unit: str


class ScalarDatum(StrictModel):
    value: FiniteNumber | None
    unit: str
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    reason: Reason | None
    sourceValue: SourceValue | None

    @model_validator(mode="after")
    def availability(self):
        if self.status == "AVAILABLE" and (self.value is None or self.reason is not None):
            raise ValueError("available requires value and no reason")
        if self.status == "UNAVAILABLE" and (self.value is not None or self.reason is None):
            raise ValueError("unavailable requires null value and reason")
        return self


class Quality(StrictModel):
    convergenceStatus: str
    qualityStatus: str
    catalogStatus: str


class ComparisonRun(StrictModel):
    key: str
    ref: RunRef
    conditions: dict[ConditionId, ScalarDatum]
    metrics: dict[OutputMetric, ScalarDatum]
    quality: Quality


class ComparisonDifference(StrictModel):
    id: str
    kind: Literal["absolute_difference", "baseline_delta", "adjacent_delta"]
    leftKey: str
    rightKey: str
    metric: OutputMetric
    difference: ScalarDatum
    percentChange: ScalarDatum | None
    direction: Literal["increase", "decrease", "unchanged", "not_applicable", "unavailable"]


class MetricSummary(StrictModel):
    id: str
    metric: OutputMetric
    availableCount: int
    minimum: ScalarDatum
    minimumKeys: list[str]
    maximum: ScalarDatum
    maximumKeys: list[str]
    range: ScalarDatum


class TrendGroup(StrictModel):
    id: str
    metric: OutputMetric
    axis: ConditionId
    fixedConditions: dict[ConditionId, ScalarDatum]
    orderedKeys: list[str]
    comparisonIds: list[str]
    direction: Literal[
        "increasing", "decreasing", "constant", "non_monotonic", "insufficient_data", "unavailable"
    ]


class ObservationSource(StrictModel):
    kind: Literal["run", "comparison", "summary", "trend"]
    key: str
    metric: OutputMetric


class Observation(StrictModel):
    id: str
    source: ObservationSource
    text: str


class ComparisonResultV2(StrictModel):
    kind: Literal["compare_runs"]
    resultStatus: Literal["COMPARISON_READY", "COMPARISON_PARTIAL", "NO_COMPARABLE_DATA"]
    mode: Literal["values", "pair", "overview", "baseline", "trend"]
    metricIds: list[OutputMetric]
    baselineKey: str | None
    trendAxis: ConditionId | None
    runs: list[ComparisonRun]
    comparisons: list[ComparisonDifference]
    summaries: list[MetricSummary]
    trends: list[TrendGroup]
    observations: list[Observation]
    usedRunRefs: list[RunRef]
    numericPolicyVersion: Literal["v1"]
    aggregationPolicyVersion: Literal["multi-run-1"]

    @model_validator(mode="after")
    def inventory(self):
        keys = [r.key for r in self.runs]
        if len(keys) < 2 or len(set(keys)) != len(keys) or [r.ref for r in self.runs] != self.usedRunRefs:
            raise ValueError("comparison requires ordered unique selection")
        if len({(r.runId, r.runVersionId) for r in self.usedRunRefs}) != len(keys):
            raise ValueError("duplicate exact Run reference")
        if not self.metricIds or len(set(self.metricIds)) != len(self.metricIds):
            raise ValueError("metrics must be unique and nonempty")
        for run in self.runs:
            if set(run.conditions) != {"pressure", "sourcePower", "biasPower"} or set(run.metrics) != set(
                self.metricIds
            ):
                raise ValueError("Run scalar keys mismatch")
        if self.baselineKey is not None and self.baselineKey not in keys:
            raise ValueError("unknown baseline")
        for trend in self.trends:
            if set(trend.fixedConditions) != {"pressure", "sourcePower", "biasPower"} - {trend.axis}:
                raise ValueError("fixed conditions mismatch")
        return self


class AnswerInterpretation(StrictModel):
    text: str
    observationIds: list[str]
    assumptions: list[str]


class ComparisonAnswerDraft(StrictModel):
    observationIds: list[str]
    interpretations: list[AnswerInterpretation]
    limitations: list[str]


class ComparisonAnswer(ComparisonAnswerDraft):
    kind: Literal["comparison_answer"]
    status: Literal["COMPLETE"]
    knowledgeBasis: Literal["VERIFIED_RUNS_AND_LLM_GENERAL_KNOWLEDGE"]


class GeneralAnswerResult(StrictModel):
    kind: Literal["generate_answer"]
    resultStatus: Literal["ANSWER_READY"]
    markdown: str
    knowledgeBasis: Literal["LLM_GENERAL_KNOWLEDGE"]
    usedRunRefs: list[RunRef]

    @model_validator(mode="after")
    def general(self):
        if not self.markdown.strip() or self.usedRunRefs:
            raise ValueError("general answer requires text and no Run dependency")
        return self


class ToolSelection(StrictModel):
    call_id: str
    name: Literal["forward_lookup", "reverse_search", "compare_runs", "generate_answer"]
    arguments: dict


class UnitAssumption(StrictModel):
    metric: Literal["pressure", "sourcePower", "biasPower", "meanIonEnergy", "ionFlux", "iedWidth"]
    unit: str


class AnswerSnapshotV2(StrictModel):
    implementationId: Literal["v1"]
    graphVersion: Literal["v1"]
    schemaVersion: Literal[2]
    kind: Literal["forward_lookup", "reverse_search", "compare_runs", "generate_answer"]
    summary: str
    originalQuestion: str
    toolSelection: ToolSelection
    resolvedInputs: dict
    result: dict
    answer: ComparisonAnswer | None
    contextProvenance: dict
    inputHistory: list[dict]
    usedRunRefs: list[RunRef]
    versions: dict
    unitAssumptions: list[UnitAssumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def result_contract(self):
        from .tools import TOOL_MODELS

        if (
            self.toolSelection.name != self.kind
            or not self.toolSelection.call_id
            or self.result.get("kind") != self.kind
        ):
            raise ValueError("tool/result mismatch")
        TOOL_MODELS[self.kind].model_validate(self.toolSelection.arguments)
        if self.unitAssumptions:
            from .metric_registry import UNITS

            if self.kind not in ("forward_lookup", "reverse_search"):
                raise ValueError("unit assumptions are only valid for searches")
            seen = set()
            quantities = {**self.resolvedInputs.get("conditions", {})}
            for group in ("constraints", "goals"):
                for item in self.resolvedInputs.get(group, []):
                    if any(item.get(k) is not None for k in ("value", "min", "max")):
                        quantities[item["metric"]] = item
            for assumption in self.unitAssumptions:
                if (
                    assumption.metric in seen
                    or assumption.unit != UNITS[assumption.metric]
                    or quantities.get(assumption.metric, {}).get("unit") != assumption.unit
                ):
                    raise ValueError("unit assumption does not match resolved input")
                seen.add(assumption.metric)
        if self.kind == "compare_runs":
            value = ComparisonResultV2.model_validate(self.result)
            if self.answer is None or value.usedRunRefs != self.usedRunRefs:
                raise ValueError("comparison answer/inventory mismatch")
        elif self.answer is not None:
            raise ValueError("only comparisons have structured answers")
        if self.kind == "generate_answer":
            GeneralAnswerResult.model_validate(self.result)
            if self.resolvedInputs or self.contextProvenance or self.usedRunRefs:
                raise ValueError("general cannot acquire Run dependencies")
        return self
