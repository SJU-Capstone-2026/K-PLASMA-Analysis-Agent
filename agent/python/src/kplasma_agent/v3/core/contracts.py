"""Graph v2 plan and snapshot contracts, separate from the v1 wire families."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ..comparison_catalog import ComparisonField, PlotId
from ..contracts import MetricId, OutputMetric

GraphVersion = Literal["v1", "v3"]
Identifier = Annotated[str, Field(min_length=1, max_length=96)]
ToolName = Literal["forward_lookup", "reverse_search", "compare_runs", "explain_answer", "decision_records"]
Operation = Literal["min", "max", "difference", "scale", "ratio", "mean"]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SourceQuote(ClosedModel):
    message_key: Identifier
    quote: Annotated[str, Field(min_length=1)]


class Requirement(ClosedModel):
    id: Identifier
    sources: Annotated[list[SourceQuote], Field(min_length=1)]
    text: Annotated[str, Field(min_length=1)]
    handled_by: list[Identifier]


class LiteralInput(ClosedModel):
    kind: Literal["literal"]
    value: str | int | float
    unit: str | None
    source: SourceQuote


class ContextRef(ClosedModel):
    kind: Literal["context_ref"]
    key: Identifier


class ScalarScope(ClosedModel):
    kind: Literal["scalar"]


class SelectionScope(ClosedModel):
    kind: Literal["confirmed_selection"]
    step_id: Identifier


class CandidateScope(ClosedModel):
    kind: Literal["candidate_group"]


class ContextSelectionScope(ClosedModel):
    kind: Literal["context_selection"]
    key: Identifier


class RunScope(ClosedModel):
    kind: Literal["confirmed_run"]
    key: Identifier


class ResultRef(ClosedModel):
    kind: Literal["result_ref"]
    step_id: Identifier
    field: Literal["candidates", "selection", "value"] | ComparisonField
    scope: Annotated[Union[ScalarScope, SelectionScope, CandidateScope, ContextSelectionScope, RunScope], Field(discriminator="kind")]


Binding = Annotated[Union[LiteralInput, ContextRef, ResultRef], Field(discriminator="kind")]


class ChoiceResultRef(ResultRef):
    field: Literal["value"]
    scope: ScalarScope


AxisBinding = Annotated[Union[LiteralInput, ContextRef, ChoiceResultRef], Field(discriminator="kind")]


class OutputRequirement(ClosedModel):
    step_id: Identifier
    field: Identifier
    count: Annotated[int, Field(ge=1)] | None = None
    value_type: Literal["quantity", "quantities", "run_refs"] | None = None
    unit: str | None = None


class RunCondition(ClosedModel):
    step_id: Identifier
    field: Literal["status", "candidate_count"]
    operator: Literal["eq", "lt", "lte", "gt", "gte"]
    value: str | Annotated[int, Field(ge=0)]


class StepBase(ClosedModel):
    id: Identifier
    requirement_ids: list[Identifier] = Field(default_factory=list)
    depends_on: list[Identifier] = Field(default_factory=list)
    requires: list[OutputRequirement] = Field(default_factory=list)
    run_if: list[RunCondition] = Field(default_factory=list)


class ForwardInputs(ClosedModel):
    pressure: Binding | None = None
    source_power: Binding | None = None
    bias_power: Binding | None = None


class ConstraintInput(ClosedModel):
    field: MetricId
    operator: Literal["eq", "lte", "gte", "lt", "gt", "between"]
    value: Binding | None = None
    min: Binding | None = None
    max: Binding | None = None


class GoalInput(ClosedModel):
    field: OutputMetric
    direction: Literal["maximize", "minimize", "target_range"]
    min: Binding | None = None
    max: Binding | None = None


class ReverseInputs(ClosedModel):
    constraints: list[ConstraintInput]
    goals: list[GoalInput] = Field(default_factory=list)


class CompareInputs(ClosedModel):
    runs: Binding
    fields: Annotated[list[ComparisonField], Field(min_length=1)]
    baseline: Binding | None = None
    trend_axis: AxisBinding | None = None
    plot_ids: list[PlotId] = Field(default_factory=list)


class ForwardStep(StepBase):
    kind: Literal["tool"]
    tool: Literal["forward_lookup"]
    inputs: ForwardInputs


class ReverseStep(StepBase):
    kind: Literal["tool"]
    tool: Literal["reverse_search"]
    inputs: ReverseInputs


class CompareStep(StepBase):
    kind: Literal["tool"]
    tool: Literal["compare_runs"]
    inputs: CompareInputs


class ExplainInputs(ClosedModel):
    mode: Literal["concept", "results"]


class ExplainStep(StepBase):
    kind: Literal["tool"]
    tool: Literal["explain_answer"]
    inputs: ExplainInputs


class DecisionRecordInputs(ClosedModel):
    runs: Binding
    action: Literal["search", "cost_exclusion"]
    query: Annotated[str, Field(min_length=1, max_length=4000)]
    source: SourceQuote
    threshold: LiteralInput | None = None


class DecisionRecordStep(StepBase):
    kind: Literal["tool"]
    tool: Literal["decision_records"]
    inputs: DecisionRecordInputs


class DeriveInputs(ClosedModel):
    values: Binding | list[Binding]
    direction: Literal["absolute", "first_minus_second", "second_minus_first"] | None = None


class DeriveStep(StepBase):
    kind: Literal["derive"]
    operation: Operation
    inputs: DeriveInputs


class AwaitInputs(ClosedModel):
    selection_count: Annotated[int, Field(ge=2)] | None = None
    target_step_id: Identifier
    field: Identifier
    candidates: Binding | None = None


class AwaitInputStep(StepBase):
    kind: Literal["await_input"]
    confirmation: Literal["run_selection", "condition", "baseline", "trend_axis", "calculation_direction"]
    inputs: AwaitInputs


StepSpec = Union[ForwardStep, ReverseStep, CompareStep, DeriveStep, AwaitInputStep, ExplainStep, DecisionRecordStep]


class PlanDraft(ClosedModel):
    schema_version: Literal[2]
    request_mode: Literal["general_only", "data_request"]
    base_revision: Annotated[int, Field(ge=1)] | None
    requirements: list[Requirement]
    steps: Annotated[list[StepSpec], Field(max_length=16)]


class RunRef(ClosedModel):
    runId: Identifier
    runVersionId: Identifier


class Quantity(ClosedModel):
    value: float
    field: Identifier
    unit: str | None
    run_ref: RunRef | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list)


class StepResult(ClosedModel):
    executionId: Identifier
    stepId: Identifier
    status: Literal["verified", "empty", "partial", "blocked", "failed", "skipped"]
    outputs: dict[str, JsonValue]
    runRefs: list[RunRef] = Field(default_factory=list)
    groupId: Identifier | None = None
    reason: str | None = None


class Evidence(ClosedModel):
    id: Identifier
    executionId: Identifier
    field: Identifier
    value: JsonValue
    unit: str | None
    runRef: RunRef | None = None


class Interpretation(ClosedModel):
    id: Identifier
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    text: str
    assumptions: list[str]


class Limitation(ClosedModel):
    id: Identifier
    evidence_ids: list[Identifier]
    text: str


class DataAnswerDraft(ClosedModel):
    fact_ids: list[Identifier]
    interpretations: list[Interpretation]
    limitations: list[Limitation]


class GeneralAnswerDraft(ClosedModel):
    paragraphs: Annotated[list[str], Field(min_length=1)]
    sources: list[str]


class ReviewAnswer(ClosedModel):
    name: Literal["request_coverage", "evidence_alignment", "interpretation_scope"]
    choice: str
    probabilities: dict[str, Annotated[float, Field(ge=0, le=1)]]
    confidence: Annotated[float, Field(ge=0, le=1)] | None


class ReviewDecision(ClosedModel):
    status: Literal["PASS", "ISSUE", "UNAVAILABLE", "SKIPPED"]
    answers: list[ReviewAnswer]
    reason: str | None = None


class BudgetState(ClosedModel):
    replans_used: Annotated[int, Field(ge=0, le=2)]
    answer_rewrites_used: Annotated[int, Field(ge=0, le=1)]
    partial_finalizations_used: Annotated[int, Field(ge=0, le=1)]
    model_requests_used: Annotated[int, Field(ge=0, le=13)]
    tool_invocations_used: Annotated[int, Field(ge=0, le=12)]
    active_elapsed_seconds: Annotated[float, Field(ge=0)]


class GraphV3AnswerSnapshotV1(ClosedModel):
    implementationId: Literal["v3"]
    graphVersion: Literal["v3"]
    schemaVersion: Literal[1]
    intent: Literal["COMPOSITE_ANSWER", "GENERAL_ANSWER"]
    question: str
    confirmedContext: dict[str, JsonValue]
    planRevision: Annotated[int, Field(ge=1)] | None
    stepResults: list[StepResult]
    evidence: list[Evidence]
    draft: DataAnswerDraft | GeneralAnswerDraft | None
    answer: str
    executionStatus: Literal["COMPLETE", "PARTIAL", "FAILED"]
    hasIncompleteWork: bool = False
    review: ReviewDecision
    budget: BudgetState
    executionMode: dict[str, JsonValue] | None = None
    decisionEvidence: list[dict[str, JsonValue]] | None = None
