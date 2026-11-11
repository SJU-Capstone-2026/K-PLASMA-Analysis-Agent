"""Strict interpretation contracts. Missing slots stay missing until decision."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, model_validator

FiniteNumber = Annotated[StrictFloat, Field(allow_inf_nan=False)]
ConditionId = Literal["pressure", "sourcePower", "biasPower"]
OutputMetric = Literal["meanIonEnergy", "ionFlux", "iedWidth"]
MetricId = Literal["pressure", "sourcePower", "biasPower", "meanIonEnergy", "ionFlux", "iedWidth"]
ConceptId = Literal[
    "ionFlux",
    "meanIonEnergy",
    "iedWidth",
    "ied",
    "sourcePower",
    "biasPower",
    "pressure",
    "electronDensity",
    "electronTemperature",
    "sheath",
    "plasma",
]
ContextRule = Literal["selected_run_conditions", "energy_slightly_higher", "flux_maintained_and_width_lower"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class NumberWithUnit(StrictModel):
    value: FiniteNumber
    unit: str | None = None


class Conditions(StrictModel):
    pressure: NumberWithUnit | None = None
    sourcePower: NumberWithUnit | None = None
    biasPower: NumberWithUnit | None = None


class ForwardInputs(StrictModel):
    conditions: Conditions = Field(default_factory=Conditions)
    context_rules: list[Literal["selected_run_conditions"]] = Field(default_factory=list)


class Constraint(StrictModel):
    metric: MetricId
    operator: Literal["eq", "lte", "gte", "lt", "gt", "between"]
    value: FiniteNumber | None = None
    min: FiniteNumber | None = None
    max: FiniteNumber | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.operator == "between":
            if self.min is None or self.max is None or self.value is not None or self.min > self.max:
                raise ValueError("between requires ordered min/max and no value")
        elif self.value is None or self.min is not None or self.max is not None:
            raise ValueError("scalar operator requires value and no min/max")
        return self


class Goal(StrictModel):
    metric: OutputMetric
    direction: Literal["maximize", "minimize", "target_range"]
    min: FiniteNumber | None = None
    max: FiniteNumber | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.direction == "target_range":
            if self.min is None or self.max is None or self.min > self.max:
                raise ValueError("target_range requires ordered min/max")
        elif self.min is not None or self.max is not None:
            raise ValueError("maximize/minimize do not accept bounds")
        return self


class ReverseInputs(StrictModel):
    constraints: list[Constraint] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)
    context_rules: list[Literal["energy_slightly_higher", "flux_maintained_and_width_lower"]] = Field(
        default_factory=list
    )


class ExplicitRunSelector(StrictModel):
    kind: Literal["run_id"]
    run_id: Annotated[str, Field(min_length=1, max_length=200)]
    run_version_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class ContextRunSelector(StrictModel):
    kind: Literal["reference_run", "selected_run", "comparison_baseline", "comparison_target"]


RunSelector = Annotated[Union[ExplicitRunSelector, ContextRunSelector], Field(discriminator="kind")]


class CompareInputs(StrictModel):
    baseline: RunSelector | None = None
    target: RunSelector | None = None
    metrics: list[OutputMetric] | None = None

    @model_validator(mode="after")
    def valid_metrics(self):
        if self.metrics is not None and (not self.metrics or len(set(self.metrics)) != len(self.metrics)):
            raise ValueError("metrics must be nonempty and unique when supplied")
        return self


class ExplainChangeInputs(CompareInputs):
    pass


class ExplainConceptInputs(StrictModel):
    topics: list[ConceptId] = Field(default_factory=list)
    aspect: Literal["definition", "difference", "relationship"] | None = None


class ForwardOperation(StrictModel):
    kind: Literal["forward_lookup"]
    inputs: ForwardInputs


class ReverseOperation(StrictModel):
    kind: Literal["reverse_search"]
    inputs: ReverseInputs


class CompareOperation(StrictModel):
    kind: Literal["compare_runs"]
    inputs: CompareInputs


class ExplainChangeOperation(StrictModel):
    kind: Literal["explain_change"]
    inputs: ExplainChangeInputs


class ExplainConceptOperation(StrictModel):
    kind: Literal["explain_concept"]
    inputs: ExplainConceptInputs


Operation = Annotated[
    Union[
        ForwardOperation, ReverseOperation, CompareOperation, ExplainChangeOperation, ExplainConceptOperation
    ],
    Field(discriminator="kind"),
]


class Unresolved(StrictModel):
    reason: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=1000)]


class Interpretation(StrictModel):
    status: Literal["resolved", "needs_input", "unsupported"]
    operations: list[Operation] = Field(default_factory=list)
    unresolved: list[Unresolved] = Field(default_factory=list)


def normalize_interpretation(raw: dict | Interpretation) -> Interpretation:
    """Validate, without coercing numbers, filling unknown slots or applying units."""
    return raw if isinstance(raw, Interpretation) else Interpretation.model_validate(raw)
