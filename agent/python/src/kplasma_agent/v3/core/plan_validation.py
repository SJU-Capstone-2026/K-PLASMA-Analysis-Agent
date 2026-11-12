"""Validate the dependency graph and produce its stable execution order."""

from collections.abc import Iterator, Mapping, Set
from typing import get_args

from pydantic import BaseModel

from ..comparison_catalog import FIELD_META, ComparisonField, PlotId
from ..contracts import ConditionId, OutputMetric
from ..metric_registry import NumericError, normalize_value
from .contracts import (
    AwaitInputStep, ChoiceResultRef, CompareStep, ContextRef, ContextSelectionScope, DeriveStep, ForwardStep, LiteralInput,
    DecisionRecordStep, ExplainStep, PlanDraft, ResultRef, ReverseStep, RunScope, ScalarScope, SelectionScope, StepSpec,
)


class InvalidPlan(ValueError):
    def __init__(self, message, *, path="/", actual=None, allowed=None):
        super().__init__(message)
        self.details = {"code": "INVALID_PLAN", "message": message, "path": path,
                        "actual": actual, "allowed": allowed}


def _bindings(value: object) -> Iterator[ContextRef | LiteralInput | ResultRef]:
    if isinstance(value, (ContextRef, LiteralInput, ResultRef)):
        yield value
    elif isinstance(value, BaseModel):
        for _, field in value:
            yield from _bindings(field)
    elif isinstance(value, list):
        for item in value:
            yield from _bindings(item)


def _fields(step: StepSpec) -> set[str]:
    if isinstance(step, ExplainStep):
        return set()
    if isinstance(step, CompareStep):
        return set(step.inputs.fields)
    if isinstance(step, DeriveStep):
        return {"value"}
    if isinstance(step, (ForwardStep, ReverseStep, DecisionRecordStep)):
        return {"candidates"}
    return {"selection"} if step.confirmation == "run_selection" else {"value"}


def _connect_comparison_choices(steps: dict[str, StepSpec]) -> None:
    for choice in list(steps.values()):
        if not isinstance(choice, AwaitInputStep) or choice.confirmation not in {"baseline", "trend_axis"}:
            continue
        comparison = steps.get(choice.inputs.target_step_id)
        field = choice.confirmation
        if not isinstance(comparison, CompareStep) or choice.inputs.field != field:
            raise InvalidPlan(f"{field} confirmation must target compare_runs.inputs.{field}")
        binding = getattr(comparison.inputs, field)
        if binding is not None and (not isinstance(binding, ResultRef) or binding.step_id != choice.id
                                    or binding.field != "value" or not isinstance(binding.scope, ScalarScope)):
            raise InvalidPlan(f"comparison {field} conflicts with its user confirmation")

        # Connect the confirmed value before accepting the plan; dependency order alone cannot bind it.
        dependencies = choice.depends_on
        if isinstance(comparison.inputs.runs, ResultRef):
            dependencies = list(dict.fromkeys([*dependencies, comparison.inputs.runs.step_id]))
        steps[choice.id] = choice.model_copy(update={
            "depends_on": dependencies, "inputs": choice.inputs.model_copy(update={"candidates": None}),
        })
        result = ChoiceResultRef(kind="result_ref", step_id=choice.id, field="value", scope=ScalarScope(kind="scalar"))
        steps[comparison.id] = comparison.model_copy(update={
            "depends_on": list(dict.fromkeys([*comparison.depends_on, choice.id])),
            "inputs": comparison.inputs.model_copy(update={field: result}),
        })


def _check_literal_unit(field: str, binding) -> None:
    if isinstance(binding, LiteralInput) and binding.unit is not None:
        try:
            normalize_value(field, binding.value, binding.unit)
        except NumericError as error:
            raise InvalidPlan(
                f"{field} has an invalid value or unit. Use the original number and a supported unit; "
                "use null only when the user omitted the unit."
            ) from error


def _check_numeric_input(field: str, binding, steps: Mapping[str, StepSpec]) -> None:
    _check_literal_unit(field, binding)
    if not isinstance(binding, ResultRef) or binding.step_id not in steps:
        return
    source = steps[binding.step_id]
    scalar = isinstance(source, DeriveStep) and isinstance(binding.scope, ScalarScope)
    measured = isinstance(source, CompareStep) and isinstance(binding.scope, RunScope) and binding.field == field
    if not scalar and not measured:
        raise InvalidPlan(
            f"{field} requires a single quantity, not a Run list or quantity collection. "
            "Select one confirmed Run value or derive one threshold according to the original request; keep the condition."
        )


def _uses_builtin_difference(step: DeriveStep, compare: CompareStep, selected_run_keys: Set[str]) -> bool:
    if compare.inputs.runs != ContextRef(kind="context_ref", key="selected_runs"):
        return False
    if compare.inputs.baseline is not None or compare.inputs.trend_axis is not None or step.run_if:
        return False

    values = step.inputs.values if isinstance(step.inputs.values, list) else [step.inputs.values]
    refs = [value for value in values if isinstance(value, ResultRef) and value.step_id == compare.id]
    if len(refs) != len(values) or len(refs) not in (1, 2):
        return False
    fields = {ref.field for ref in refs}
    if any(
        requirement.step_id != compare.id or requirement.field not in fields
        or requirement.count not in (None, len(selected_run_keys))
        or requirement.value_type not in (None, "quantities")
        or requirement.unit not in (None, FIELD_META[requirement.field]["unit"])
        for requirement in step.requires
    ):
        return False

    whole_selection = all(isinstance(ref.scope, ContextSelectionScope) and ref.scope.key == "selected_runs"
                          for ref in refs)
    if len(refs) == 1:
        return whole_selection
    if len(fields) == 1:
        # Some drafts use context_selection with each individual Run key, yielding singleton lists.
        run_keys = {ref.scope.key for ref in refs if isinstance(ref.scope, (RunScope, ContextSelectionScope))}
        return run_keys == selected_run_keys
    return whole_selection and any(
        fields == {f"{plot}.maximum", f"{plot}.minimum"} and f"{plot}.peakToPeak" in compare.inputs.fields
        for plot in ("current", "potential")
    )


def _reuse_builtin_differences(plan: PlanDraft, selected_run_keys: Set[str]) -> PlanDraft:
    if len(selected_run_keys) != 2:
        return plan

    by_id = {step.id: step for step in plan.steps}
    consumed = {parent for step in plan.steps for parent in step.depends_on}
    consumed.update(step.inputs.target_step_id for step in plan.steps if isinstance(step, AwaitInputStep))
    replacements = {}
    for step in plan.steps:
        if (not isinstance(step, DeriveStep) or step.operation != "difference"
                or step.inputs.direction != "absolute" or step.id in consumed or len(step.depends_on) != 1):
            continue
        compare = by_id[step.depends_on[0]]
        if isinstance(compare, CompareStep) and _uses_builtin_difference(step, compare, selected_run_keys):
            replacements[step.id] = compare.id

    if not replacements:
        return plan
    steps = []
    for step in plan.steps:
        if step.id in replacements:
            continue
        inherited = [requirement for source, target in replacements.items() if target == step.id
                     for requirement in by_id[source].requirement_ids]
        steps.append(step.model_copy(update={"requirement_ids": list(dict.fromkeys(step.requirement_ids + inherited))})
                     if inherited else step)
    requirements = [requirement.model_copy(update={
        "handled_by": list(dict.fromkeys(replacements.get(step_id, step_id) for step_id in requirement.handled_by)),
    }) for requirement in plan.requirements]
    return plan.model_copy(update={"steps": steps, "requirements": requirements})


def validate_plan(
    plan: PlanDraft, *, messages: Mapping[str, str], context_keys: Set[str],
    base_revision: int | None = None, data_required: bool = False, selected_run_keys: Set[str] = frozenset(),
) -> PlanDraft:
    if plan.base_revision != base_revision:
        raise InvalidPlan("plan base revision is stale")
    explanations = [step for step in plan.steps if isinstance(step, ExplainStep)]
    work = [step for step in plan.steps if not isinstance(step, ExplainStep)]
    if len(explanations) > 1:
        raise InvalidPlan("explain_answer must appear at most once, as the last step")
    if explanations:
        explanation = explanations[0]
        if plan.steps[-1].id != explanation.id or explanation.run_if or explanation.requires:
            raise InvalidPlan("explain_answer must be the last, unconditional step without requires")
        if any(explanation.id in step.depends_on for step in work):
            raise InvalidPlan("no step may depend on explain_answer")
    if plan.request_mode == "general_only":
        if work or data_required:
            raise InvalidPlan("general-only mode cannot perform or bypass a data request")
        if len(explanations) != 1 or explanations[0].inputs.mode != "concept":
            raise InvalidPlan("general_only needs one explain_answer with mode=concept and mapped requirements")
    elif not work or not plan.requirements:
        raise InvalidPlan("data requests need steps and requirements")

    by_id = {s.id: s for s in plan.steps}
    if len(by_id) != len(plan.steps):
        raise InvalidPlan("duplicate step ID")
    _connect_comparison_choices(by_id)
    requirements = {r.id: r for r in plan.requirements}
    if len(requirements) != len(plan.requirements):
        raise InvalidPlan("duplicate requirement ID")

    def check_quote(key: str, quote: str, path="/") -> None:
        if key not in messages or quote not in messages[key]:
            raise InvalidPlan(f"unrecognized original text at {key}", path=path, actual=quote,
                              allowed={"message_key": key, "original_text": messages.get(key)})

    for req_index, req in enumerate(plan.requirements):
        for source_index, source in enumerate(req.sources):
            check_quote(source.message_key, source.quote,
                        f"/requirements/{req_index}/sources/{source_index}/quote")
        actual = {s.id for s in plan.steps if req.id in s.requirement_ids}
        if not set(req.handled_by) <= actual or (plan.steps and not req.handled_by):
            raise InvalidPlan(f"requirement mapping does not match its steps: {req.id}",
                              path=f"/requirements/{req_index}/handled_by", actual=req.handled_by,
                              allowed=sorted(actual))

    pending = list(by_id.values())
    ordered: list[StepSpec] = []
    ancestors: dict[str, set[str]] = {}
    for step in pending:
        if not set(step.depends_on) <= by_id.keys():
            raise InvalidPlan(f"unknown dependency in {step.id}")
        if not set(step.requirement_ids) <= requirements.keys() or not step.requirement_ids:
            raise InvalidPlan(f"unmapped requirement in {step.id}")
    while pending:
        ready = next((s for s in pending if set(s.depends_on) <= ancestors.keys()), None)
        if ready is None:
            raise InvalidPlan("dependency cycle")
        pending.remove(ready)
        ordered.append(ready)
        parents = set(ready.depends_on)
        for dependency in ready.depends_on:
            parents.update(ancestors[dependency])
        ancestors[ready.id] = parents

    allowed_search_fields = set(get_args(OutputMetric) + get_args(ConditionId))
    for step in ordered:
        parents = ancestors[step.id]
        if isinstance(step, ExplainStep):
            if not {item.id for item in work} <= parents:
                raise InvalidPlan("explain_answer must depend on all preceding work steps")
            if step.inputs.mode == "results" and not any(
                isinstance(by_id[parent], (ForwardStep, ReverseStep, CompareStep, DecisionRecordStep)) for parent in parents
            ):
                raise InvalidPlan("explain_answer results needs preceding Run data evidence")

        def producer(step_id: str, field: str) -> StepSpec:
            if step_id not in parents:
                raise InvalidPlan(f"{step.id} references a non-predecessor: {step_id}")
            previous = by_id[step_id]
            if field not in _fields(previous):
                raise InvalidPlan(f"{step_id} does not produce {field}", actual=field,
                                  allowed=sorted(_fields(previous)))
            return previous

        if isinstance(step, AwaitInputStep) and step.inputs.selection_count is not None and step.confirmation != "run_selection":
            raise InvalidPlan("selection_count is only valid for Run selection")
        if isinstance(step, AwaitInputStep) and step.confirmation == "run_selection":
            candidate_source = step.inputs.candidates
            if candidate_source is not None and not (
                isinstance(candidate_source, ResultRef) and candidate_source.field == "candidates"
                and candidate_source.scope.kind == "candidate_group"
                and isinstance(by_id.get(candidate_source.step_id), (ForwardStep, ReverseStep, DecisionRecordStep))
            ):
                raise InvalidPlan(
                    "Run selection candidates must reference a preceding candidate_group result. "
                    "Only when the original request asks to choose from the registered Run catalog, "
                    "set candidates to null; comparison_entries and selected_runs are prior selections, "
                    "not the catalog. Never replace an attached or filtered candidate scope with null.",
                    path=f"/steps/{plan.steps.index(step)}/inputs/candidates",
                    actual=candidate_source.model_dump(mode="json"),
                    allowed=[None, {"kind": "result_ref", "field": "candidates",
                                    "scope": {"kind": "candidate_group"}}],
                )
        if isinstance(step, ForwardStep):
            conditions = {"pressure": step.inputs.pressure, "sourcePower": step.inputs.source_power,
                          "biasPower": step.inputs.bias_power}
            for field, binding in conditions.items():
                _check_numeric_input(field, binding, by_id)
        if isinstance(step, ReverseStep):
            for constraint in step.inputs.constraints:
                if constraint.field not in allowed_search_fields:
                    raise InvalidPlan(f"unsupported search field: {constraint.field}")
                if constraint.operator == "between":
                    valid = constraint.value is None and constraint.min is not None and constraint.max is not None
                else:
                    valid = constraint.value is not None and constraint.min is None and constraint.max is None
                if not valid:
                    raise InvalidPlan(f"invalid bounds for {constraint.field}")
                for binding in (constraint.value, constraint.min, constraint.max):
                    _check_numeric_input(constraint.field, binding, by_id)
            for goal in step.inputs.goals:
                if goal.field not in allowed_search_fields:
                    raise InvalidPlan("unsupported search objective")
                for binding in (goal.min, goal.max):
                    _check_numeric_input(goal.field, binding, by_id)
        if isinstance(step, DecisionRecordStep):
            check_quote(step.inputs.source.message_key, step.inputs.source.quote)
            if step.inputs.query != messages[step.inputs.source.message_key]:
                raise InvalidPlan("record query must preserve the complete original source message")
            if isinstance(step.inputs.runs, LiteralInput):
                raise InvalidPlan("record Runs must come from confirmed context or a whole candidate group")
            if step.inputs.action == "cost_exclusion":
                from ..decision_rag import policy
                parsed = policy.parse_request(step.inputs.query)
                threshold = step.inputs.threshold
                if (parsed is None or not parsed["exclude"] or not policy.mentions_cost(step.inputs.query)
                        or not policy.valid_threshold(parsed["threshold"]) or threshold is None
                        or threshold.value != parsed["threshold"] or threshold.unit is not None):
                    raise InvalidPlan("cost exclusion requires the original explicit positive integer threshold and cost reason")
            elif step.inputs.threshold is not None:
                raise InvalidPlan("semantic retrieval does not apply an exclusion threshold")
        if isinstance(step, CompareStep):
            if not set(step.inputs.fields) <= set(get_args(ComparisonField)):
                raise InvalidPlan("unsupported comparison field")
            if not set(step.inputs.plot_ids) <= set(get_args(PlotId)):
                raise InvalidPlan("unsupported comparison plot")
            if isinstance(step.inputs.runs, LiteralInput):
                raise InvalidPlan("Run references must come from confirmed context")
            if isinstance(step.inputs.runs, ResultRef):
                selected = by_id.get(step.inputs.runs.step_id)
                if isinstance(selected, (ReverseStep, DecisionRecordStep)) and step.inputs.runs.scope.kind == "candidate_group":
                    if step.inputs.runs.field != "candidates":
                        raise InvalidPlan("whole-group comparison must read the search candidates field",
                                          actual=step.inputs.runs.field, allowed=["candidates"])
                elif not isinstance(selected, AwaitInputStep) or selected.confirmation != "run_selection":
                    raise InvalidPlan("search candidates must be confirmed before comparison unless the plan uses the whole candidate group")
                elif step.inputs.runs.field != "selection" or step.inputs.runs.scope.kind != "scalar":
                    raise InvalidPlan("compare_runs.inputs.runs must read the confirmation step's selection field with scalar scope")
        for binding in _bindings(step.inputs):
            if isinstance(binding, LiteralInput):
                check_quote(binding.source.message_key, binding.source.quote)
            elif isinstance(binding, ContextRef):
                if binding.key not in context_keys:
                    raise InvalidPlan(f"unknown context key: {binding.key}")
            else:
                previous = producer(binding.step_id, binding.field)
                if any(condition not in step.run_if for condition in previous.run_if):
                    raise InvalidPlan(f"{step.id} reads a conditionally skipped result")
                scope = binding.scope
                if isinstance(previous, DeriveStep) and scope.kind != "scalar":
                    raise InvalidPlan("derived outputs require scalar scope")
                if isinstance(previous, CompareStep) and scope.kind not in {"confirmed_run", "confirmed_selection", "context_selection"}:
                    raise InvalidPlan("comparison outputs require a confirmed Run or selection scope")
                if isinstance(step, DeriveStep) and isinstance(previous, CompareStep) and isinstance(scope, RunScope):
                    if not isinstance(step.inputs.values, list):
                        raise InvalidPlan("a single confirmed Run is not a comparison value set")
                if scope.kind == "candidate_group" and not (
                    isinstance(step, AwaitInputStep) and step.confirmation == "run_selection"
                    and isinstance(previous, (ForwardStep, ReverseStep, DecisionRecordStep))
                    or isinstance(step, (CompareStep, DecisionRecordStep)) and binding is step.inputs.runs
                    and isinstance(previous, (ForwardStep, ReverseStep, DecisionRecordStep))
                ):
                    raise InvalidPlan("candidate groups require user confirmation or a whole-group comparison")
                if isinstance(scope, SelectionScope):
                    confirmation = producer(scope.step_id, "selection")
                    if not isinstance(confirmation, AwaitInputStep):
                        raise InvalidPlan("selection requires an input confirmation step")
                elif isinstance(scope, (RunScope, ContextSelectionScope)) and scope.key not in context_keys:
                    raise InvalidPlan(f"unknown confirmed Run: {scope.key}")
        for output in step.requires:
            producer(output.step_id, output.field)
        for condition in step.run_if:
            if condition.step_id not in parents:
                raise InvalidPlan("run condition references a non-predecessor")
            if condition.field == "status":
                if condition.operator != "eq" or condition.value not in {
                    "verified", "empty", "partial", "blocked", "failed", "skipped"
                }:
                    raise InvalidPlan("invalid status condition")
            elif not isinstance(condition.value, int):
                raise InvalidPlan("candidate count must be an integer")

    return _reuse_builtin_differences(plan.model_copy(update={"steps": ordered}), selected_run_keys)
