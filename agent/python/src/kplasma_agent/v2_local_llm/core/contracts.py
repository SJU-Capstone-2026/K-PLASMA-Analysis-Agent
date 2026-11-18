"""Graph v2 plan and snapshot contracts, separate from the v1 wire families."""

from typing import Annotated, Literal, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue

from ..comparison_catalog import ComparisonField, PlotId
from ..contracts import MetricId, OutputMetric

GraphVersion = Literal["v1", "v2_localLLM"]
Identifier = Annotated[str, Field(min_length=1, max_length=96)]
ToolName = Literal["forward_lookup", "reverse_search", "compare_runs", "explain_answer"]
Operation = Literal["min", "max", "difference", "scale", "ratio", "mean"]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SourceQuote(ClosedModel):
    message_key: Identifier = Field(description="제공된 messages에서 인용한 메시지의 키.")
    quote: Annotated[str, Field(min_length=1)] = Field(description="해당 메시지에 실제로 있는 원문 구절.")


class Requirement(ClosedModel):
    id: Identifier = Field(description="사용자가 요청한 작업의 식별자. 단계의 requirement_ids에서 참조한다.")
    sources: Annotated[list[SourceQuote], Field(min_length=1)] = Field(description="이 작업을 요구한 원문 인용.")
    text: Annotated[str, Field(min_length=1)] = Field(description="원문이 요구한 작업. 실행 전 출력 조건과 구별한다.")
    handled_by: list[Identifier] = Field(description="이 요구사항을 실제로 수행하는 steps의 ID 목록.")


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
    step_id: Identifier = Field(description="depends_on으로 연결된 선행 단계의 ID. 자기 자신이나 후속 단계는 금지한다.")
    field: Identifier = Field(description="선행 단계가 실제로 만드는 출력 키. 조회·검색은 candidates, 계산은 value다.")
    count: Annotated[int, Field(ge=1)] | None = Field(
        default=None, description="필요한 출력 값의 정확한 개수. 최소 개수나 검색 제한이 아니다. 개수 조건이 없으면 null.")
    value_type: Literal["quantity", "quantities", "run_refs"] | None = Field(
        default=None, description="선행 출력의 형태: 단일 수치 quantity, 수치 목록 quantities, Run 참조 목록 run_refs. 미지정은 null.")
    unit: str | None = Field(default=None, description="선행 출력 값에 필요한 단위. 단위 조건이 없으면 null.")


class RunCondition(ClosedModel):
    step_id: Identifier
    field: Literal["status", "candidate_count"]
    operator: Literal["eq", "lt", "lte", "gt", "gte"]
    value: str | Annotated[int, Field(ge=0)]


class StepBase(ClosedModel):
    model_config = ConfigDict(loc_by_alias=False)

    id: Identifier = Field(description="계획 안에서 고유한 단계 ID.")
    requirement_ids: list[Identifier] = Field(
        default_factory=list, description="이 단계가 처리하는 사용자 작업의 requirements[].id 목록.")
    depends_on: list[Identifier] = Field(
        default_factory=list, description="이 단계보다 먼저 실행해야 하는 단계 ID 목록. 입력 값은 inputs의 result_ref로 연결한다.")
    required_prior_outputs: list[OutputRequirement] = Field(
        default_factory=list, validation_alias=AliasChoices("required_prior_outputs", "requires"),
        description="실행 전에 필요한 선행 단계 출력의 조건. 이번 단계가 만들거나 표시할 지표 목록이 아니다. 없으면 [].")
    run_if: list[RunCondition] = Field(
        default_factory=list, description="선행 결과에 따라 이번 단계의 실행 여부를 정하는 조건. 조건부 요청이 아니면 [].")


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


StepSpec = Union[ForwardStep, ReverseStep, CompareStep, DeriveStep, AwaitInputStep, ExplainStep]


class PlanDraft(ClosedModel):
    schema_version: Literal[2] = Field(description="계획 계약 버전. 항상 2.")
    request_mode: Literal["general_only", "data_request"] = Field(
        description="순수 개념 설명은 general_only, 실제 Run 정보가 필요한 요청·혼합 요청은 data_request.")
    base_revision: Annotated[int, Field(ge=1)] | None = Field(
        description="최초 계획은 null, 재계획은 제공된 승인 계획 revision.")
    requirements: list[Requirement] = Field(description="원문에서 요청한 작업 목록. 단계의 선행 출력 조건과 구별한다.")
    steps: Annotated[list[StepSpec], Field(max_length=16)] = Field(description="요구사항을 수행할 전체 실행 단계. 최대 16개.")


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


class GraphV2LocalLLMAnswerSnapshotV1(ClosedModel):
    implementationId: Literal["v2_localLLM"]
    graphVersion: Literal["v2_localLLM"]
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
