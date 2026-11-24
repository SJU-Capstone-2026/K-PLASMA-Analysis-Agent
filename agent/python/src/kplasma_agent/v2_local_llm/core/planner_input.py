"""Connect explicit comparison requests and search thresholds to existing plan fields."""

import re
from typing import Literal, NamedTuple

from ..comparison_catalog import FIELD_META, comparison_plan
from ..domain.grounding import _ALIASES, _NUMBER, _UNIT
from ..metric_registry import DEFAULT_METRICS, NumericError, UNITS, normalize_value
from .contracts import (
    ClosedModel, CompareStep, ContextRef, DeriveStep, ExplainStep, ForwardStep, LiteralInput, PlanDraft, ResultRef, ReverseStep,
)

_METRIC = "|".join(f"(?:{alias})" for alias in _ALIASES.values())
_GROUP = r"(?:이미\s+)?선택한\s*(?:두|2\s*개)\s*Runs?의\s*"
_DIRECTION = rf"(?P<field>{_METRIC})(?:이|가|은|는)?\s*(?P<direction>높|낮)(?:고|으면서|은)\s+"
_ALL = re.compile(
    rf"{_GROUP}(?P<primary>{_METRIC})(?:을|를)\s*비교(?:하고|한\s*뒤|한\s*다음),?\s*"
    rf"(?:선택한\s*)?(?:두|2\s*개)\s*Runs?\s*모두보다\s*{_DIRECTION}", re.I,
)
_AVERAGE = re.compile(
    rf"{_GROUP}(?P<primary>{_METRIC})의?\s*평균(?:값)?(?:을|를)\s*(?:구하고|계산하고|계산한\s*뒤),?\s*"
    rf"그\s*평균보다\s*{_DIRECTION}", re.I,
)
_CAUSAL_CONDITIONS = {
    field: re.compile(rf"(?<!\w)(?:{_ALIASES[field]})(?:만(?:이|을)?|이|가|을|를)?\s*"
                      r"(?:유일한\s*)?원인(?:인지|인가|이라고|이라면|일\s*수)", re.I)
    for field in ("pressure", "sourcePower", "biasPower")
}
_EXTREME = r"(?:최[댓대]값|최[솟소]값)"
_WAVEFORM_OUTPUTS = re.compile(
    rf"{_GROUP}(?P<signal>전극\s*전위|전류\s*밀도)의?\s*"
    rf"(?P<first>{_EXTREME})(?:과|와|\s*및|,)\s*(?P<second>{_EXTREME})(?:을|를)\s*"
    r"(?:(?:공정 조건에 따른 경향으로\s*)?비교해\s*줘"
    r"(?P<choose_axis>\.\s*경향을 볼 공정 조건 축은 내가 직접 선택하게 해\s*줘)?"
    r"|(?P<choose_baseline>기준 대비 비교(?:하고 싶어|해\s*줘)\.\s*기준 Run은 내가 (?:직접\s*)?고를 테니 먼저 선택하게 해\s*줘))[.!?]?",
    re.I,
)
_DISTRIBUTION_OUTPUTS = re.compile(
    rf"(?:이미\s+)?선택한\s*(?:(?P<qualifier>(?P<condition>{_METRIC})(?:이|가|은|는)?\s*"
    rf"(?P<amount>{_NUMBER})\s*(?P<unit>{_UNIT}))\s*인\s*)?"
    r"(?:두|2\s*개)\s*Runs?의\s*(?P<family>IEAD|IAD|IED)(?:의|\s*분포의?)?\s*"
    r"최대\s*강도(?:와|과|\s*및|,)\s*피크\s*(?P<peak>입사각|각도|에너지)(?:을|를)\s*비교해\s*줘"
    r"(?:\.\s*원본 데이터가 없으면 (?:그 )?이유를 (?:명확히 )?알려\s*줘)?[.!?]?",
    re.I,
)
_FILTERED_DISTRIBUTION_CONDITION = (
    rf"(?:{_METRIC})(?:이|가|은|는)?\s*{_NUMBER}\s*(?:(?:×\s*)?{_UNIT})?\s*(?:이상|이하|초과|미만)인"
)
_GROUP_DISTRIBUTION = re.compile(
    rf"{_FILTERED_DISTRIBUTION_CONDITION}\s*(?:(?:실제\s+)?Runs?\s*중\s*{_FILTERED_DISTRIBUTION_CONDITION}\s*)?"
    r"(?:전체|모든)\s*(?:실제\s+)?Runs?의\s*(?P<plot>IEAD|IAD|IED)(?:를|을)\s*비교해\s*줘"
    r"(?:\.\s*(?:원본\s+)?데이터가 없는 Runs?도 (?:누락 )?이유를 보여\s*줘)?[.!?]?", re.I,
)
_GROUP_IEAD_FEATURES = (
    rf"(?:{_METRIC})(?:이|가|은|는)?\s*{_NUMBER}\s*[~–—-]\s*{_NUMBER}\s*{_UNIT}\s*인\s*"
    r"(?:전체|모든)\s*(?:실제\s+)?Runs?의\s*IEAD 최대 강도와 피크 에너지[·ㆍ]각도를 비교"
)
_GROUP_IEAD_COMPARISON = re.compile(_GROUP_IEAD_FEATURES + r"해\s*줘[.!?]?", re.I)
_IEAD_UNIT_LIMITATION = re.compile(
    _GROUP_IEAD_FEATURES + r"하고,\s*"
    r"(?P<limitation>원본 강도 단위가 지정되지 않은 점이 해석에 주는 한계를 설명해\s*줘)[.!?]?", re.I,
)
_FORWARD_KEYS = {"pressure": "pressure", "sourcePower": "source_power", "biasPower": "bias_power"}
_SINGLE_RUN_CONDITIONS = r"\s*,\s*".join(
    rf"(?:{_ALIASES[field]})(?:이|가|은|는)?\s*(?P<{field}>{_NUMBER})\s*(?P<{field}_unit>{_UNIT})"
    for field in _FORWARD_KEYS
)
_OUTPUT_METRIC = "|".join(f"(?:{_ALIASES[field]})" for field in DEFAULT_METRICS)
_EXPLAIN_SINGLE_RUN = re.compile(
    rf"(?P<definition>(?:{_OUTPUT_METRIC})(?:이|가|은|는)?\s*무엇인지\s*(?:짧게\s*)?설명하고,\s*)?"
    rf"{_SINGLE_RUN_CONDITIONS}\s*인\s*(?:실제\s+)?Run의\s*(?:{_OUTPUT_METRIC})"
    rf"(?:(?:와|과|및|,)\s*(?:{_OUTPUT_METRIC})){{0,2}}(?:을|를)\s*근거로\s*결과를\s*설명해\s*줘[.!?]?",
    re.I,
)


class ComparisonOutputs(NamedTuple):
    fields: tuple[str, str]
    plot: str
    confirmation: Literal["trend_axis", "baseline"] | None


def explicit_comparison_outputs(question):
    if len(question) > 512:
        return None
    text = " ".join(question.split())
    waveform = _WAVEFORM_OUTPUTS.fullmatch(text)
    if waveform:
        plot = "potential" if waveform["signal"].startswith("전극") else "current"
        first, second = (f"{plot}.{'maximum' if value.startswith(('최댓', '최대')) else 'minimum'}"
                         for value in (waveform["first"], waveform["second"]))
        if first != second:
            confirmation = "baseline" if waveform["choose_baseline"] else "trend_axis" if waveform["choose_axis"] else None
            return ComparisonOutputs((first, second), plot, confirmation)
    distribution = _DISTRIBUTION_OUTPUTS.fullmatch(text)
    if distribution:
        plot = distribution["family"].lower()
        peak = f"{plot}.{'peakEnergy' if distribution['peak'] == '에너지' else 'peakAngle'}"
        if peak in FIELD_META:
            return ComparisonOutputs((f"{plot}.maximum", peak), plot, None)
    return None


def use_explicit_comparison_outputs(plan, question, selected_keys):
    if len(question) > 512:
        return
    comparisons = [step for step in plan.steps if isinstance(step, CompareStep)]
    if len(comparisons) != 1:
        return
    comparison = comparisons[0]
    text = " ".join(question.split())
    group = _GROUP_DISTRIBUTION.fullmatch(text)
    if group:
        _use_group_distribution(plan, comparison, group["plot"].lower())
        return
    if _GROUP_IEAD_COMPARISON.fullmatch(text):
        _use_group_distribution(plan, comparison, "iead", exact_features=True)
        return
    limitation = _IEAD_UNIT_LIMITATION.fullmatch(text)
    if limitation:
        if _use_group_distribution(plan, comparison, "iead", exact_features=True):
            _use_distribution_limitation(plan, comparison, question, limitation["limitation"])
        return
    outputs = explicit_comparison_outputs(question) if len(selected_keys) == 2 else None
    if not outputs:
        return
    distribution = _DISTRIBUTION_OUTPUTS.fullmatch(text)
    if distribution:
        _use_selected_distribution_runs(plan, comparison, distribution, selected_keys)
    if comparison.inputs.runs.model_dump() != {"kind": "context_ref", "key": "selected_runs"}:
        return
    comparison.inputs.fields = list(outputs.fields)
    comparison.inputs.plot_ids = [plot for plot in comparison.inputs.plot_ids if plot == outputs.plot]


def _use_group_distribution(plan, comparison, plot, *, exact_features=False):
    searches = [step for step in plan.steps if isinstance(step, ReverseStep)]
    if len(searches) != 1:
        return False
    expected = {"kind": "result_ref", "step_id": searches[0].id, "field": "candidates",
                "scope": {"kind": "candidate_group"}}
    if comparison.inputs.runs.model_dump() != expected or searches[0].id not in comparison.depends_on:
        return False
    fields, _, _ = comparison_plan({"plot_ids": [plot]})
    comparison.inputs.fields = fields if exact_features else list(dict.fromkeys([*comparison.inputs.fields, *fields]))
    comparison.inputs.plot_ids = [plot] if exact_features else list(dict.fromkeys([*comparison.inputs.plot_ids, plot]))
    return True


def _use_distribution_limitation(plan, comparison, question, excerpt):
    explanation = plan.steps[-1]
    if not isinstance(explanation, ExplainStep) or comparison.id not in explanation.depends_on:
        return
    explanation.inputs.mode = "results"
    explanation.required_prior_outputs = [guard for guard in explanation.required_prior_outputs
                                           if guard.step_id != comparison.id]
    if question.count(excerpt) != 1:
        return
    for requirement in plan.requirements:
        if requirement.handled_by != [explanation.id]:
            continue
        for source in requirement.sources:
            if source.message_key == "question" and source.quote.rstrip(".") == excerpt.replace("한계를", "한계"):
                source.quote = excerpt


def _use_selected_distribution_runs(plan, comparison, request, selected_keys):
    lookups = [step for step in plan.steps if isinstance(step, (ForwardStep, ReverseStep))]
    if not lookups or any(not isinstance(step, (CompareStep, ExplainStep, ForwardStep, ReverseStep)) for step in plan.steps):
        return
    selected = {"kind": "context_ref", "key": "selected_runs"}
    runs = comparison.inputs.runs.model_dump()
    candidate = (len(lookups) == 1 and runs == {"kind": "result_ref", "step_id": lookups[0].id,
                 "field": "candidates", "scope": {"kind": "candidate_group"}})
    if runs != selected and not candidate:
        return
    if any(step.run_if or step.depends_on or step.required_prior_outputs for step in lookups):
        return
    if not all(_is_selected_run_relookup(step, request, selected_keys, single=len(lookups) == 1) for step in lookups):
        return
    ids = {step.id for step in lookups}
    if any(getattr(ref, "step_id", None) in ids for ref in (comparison.inputs.baseline, comparison.inputs.trend_axis)):
        return
    if any(guard.step_id in ids for step in plan.steps for guard in step.run_if):
        return
    comparison.inputs.runs = ContextRef.model_validate(selected)
    for lookup in lookups:
        _remove_redundant_step(plan, lookup, comparison)


def _is_selected_run_relookup(step, request, selected_keys, *, single):
    qualifier = request["qualifier"]
    if isinstance(step, ReverseStep):
        if not single or not qualifier or len(step.inputs.constraints) != 1 or step.inputs.goals:
            return False
        condition = step.inputs.constraints[0]
        binding = condition.value
        if (condition.operator != "eq" or not isinstance(binding, LiteralInput)
                or binding.source.message_key != "question" or qualifier not in binding.source.quote
                or not re.fullmatch(_ALIASES[condition.field], request["condition"], re.I)):
            return False
        try:
            requested = float(request["amount"].replace(",", ""))
            return normalize_value(condition.field, binding.value, binding.unit) == normalize_value(
                condition.field, requested, request["unit"])
        except NumericError:
            return False

    supplied = [binding for attr in _FORWARD_KEYS.values() if (binding := getattr(step.inputs, attr)) is not None]
    if supplied and all(isinstance(binding, ContextRef) for binding in supplied):
        keys = {binding.key for binding in supplied}
        return len(keys) == 1 and keys <= {*selected_keys, "selected_runs"}
    if not supplied or len(supplied) != 1 or not single:
        return not supplied and single
    binding = supplied[0]
    return (isinstance(binding, LiteralInput) and qualifier and binding.source.message_key == "question"
            and binding.source.quote.removesuffix("인").strip() == qualifier)


def use_explicit_single_run_lookup(plan, question):
    if len(question) > 512:
        return
    match = _EXPLAIN_SINGLE_RUN.fullmatch(" ".join(question.split()))
    if not match:
        return
    if len(plan.steps) in (2, 3) and any(isinstance(step, ForwardStep) for step in plan.steps):
        _normalize_forward_explanation(plan, includes_definition=bool(match["definition"]))
        return
    if len(plan.steps) != 3:
        return
    search, comparison, explanation = plan.steps
    if not isinstance(search, ReverseStep) or not isinstance(comparison, CompareStep) or not isinstance(explanation, ExplainStep):
        return
    if search.inputs.goals or any(step.run_if for step in plan.steps) or search.depends_on or search.required_prior_outputs:
        return
    expected = {"kind": "result_ref", "step_id": search.id, "field": "candidates", "scope": {"kind": "candidate_group"}}
    if (comparison.inputs.runs.model_dump() != expected or comparison.inputs.baseline is not None
            or comparison.inputs.trend_axis is not None or comparison.inputs.plot_ids
            or not set(comparison.inputs.fields) <= set(DEFAULT_METRICS)):
        return
    inputs = {}
    for condition in search.inputs.constraints:
        attr = _FORWARD_KEYS.get(condition.field)
        if not attr or attr in inputs or condition.operator != "eq" or not isinstance(condition.value, LiteralInput):
            return
        binding = condition.value
        try:
            wanted = normalize_value(condition.field, float(match[condition.field].replace(",", "")),
                                     match[f"{condition.field}_unit"])
            if normalize_value(condition.field, binding.value, binding.unit) != wanted:
                return
        except NumericError:
            return
        inputs[attr] = binding
    if len(inputs) != len(_FORWARD_KEYS):
        return
    forward = ForwardStep(id=search.id, kind="tool", tool="forward_lookup", inputs=inputs,
                          requirement_ids=list(search.requirement_ids))
    plan.steps[0] = forward
    _remove_redundant_step(plan, comparison, forward)


def _normalize_forward_explanation(plan, *, includes_definition):
    lookup, explanation = plan.steps[-2:]
    if (not isinstance(lookup, ForwardStep) or not isinstance(explanation, ExplainStep)
            or explanation.inputs.mode != "results" or explanation.depends_on != [lookup.id]
            or not all(guard.step_id == lookup.id and guard.count is None and guard.unit is None and (
                guard.field == "candidates" and guard.value_type in (None, "run_refs")
                or guard.field == "value" and guard.value_type in (None, "quantity", "quantities")
            ) for guard in explanation.required_prior_outputs)):
        return
    if len(plan.steps) == 3:
        definition = plan.steps[0]
        if (not includes_definition or not isinstance(definition, ExplainStep) or definition.inputs.mode != "concept"
                or definition.run_if or definition.depends_on or definition.required_prior_outputs):
            return
        _remove_redundant_step(plan, definition, explanation)
    explanation.required_prior_outputs = []


def _remove_redundant_step(plan, step, replacement):
    replacement.requirement_ids = list(dict.fromkeys([*replacement.requirement_ids, *step.requirement_ids]))
    plan.steps = [remaining for remaining in plan.steps if remaining is not step]
    for remaining in plan.steps:
        remaining.depends_on = list(dict.fromkeys(
            replacement.id if parent == step.id else parent for parent in remaining.depends_on
            if (replacement.id if parent == step.id else parent) != remaining.id))
        remaining.required_prior_outputs = [guard for guard in remaining.required_prior_outputs if guard.step_id != step.id]
    for requirement in plan.requirements:
        requirement.handled_by = list(dict.fromkeys(
            replacement.id if current == step.id else current for current in requirement.handled_by))


def include_causal_comparison_evidence(plan, question):
    comparisons = [step for step in plan.steps if isinstance(step, CompareStep)]
    if len(comparisons) != 1 or not any(isinstance(step, ExplainStep) and step.inputs.mode == "results"
                                         for step in plan.steps):
        return
    fields = comparisons[0].inputs.fields
    fields.extend(field for field, pattern in _CAUSAL_CONDITIONS.items() if field not in fields and pattern.search(question))


def selected_aggregate_intent(question, *, search_suffix=None):
    if len(question) > 512:
        return None
    text = " ".join(question.split())
    average = _AVERAGE.match(text)
    match = average or _ALL.match(text)
    if not match:
        return None
    suffix = text[match.end():]
    if (not re.search(r"(?:Runs?|후보)(?:을|를|만)\s*(?:찾아|검색해|보여)", suffix, re.I)
            or re.search(r"말고|대신|아니(?:라|고)|제외", suffix)
            or search_suffix is not None and not search_suffix.fullmatch(suffix)):
        return None
    fields = [name for name, alias in _ALIASES.items()
              if all(re.fullmatch(alias, match[key], re.I) for key in ("primary", "field"))]
    if len(fields) != 1:
        return None
    higher = match["direction"] == "높"
    return fields[0], "mean" if average else "max" if higher else "min", "gt" if higher else "lt"


def connect_selected_comparison_threshold(plan, question, selected_keys):
    intent = selected_aggregate_intent(question) if len(selected_keys) == 2 else None
    if intent is None or any(getattr(step, "confirmation", None) == "run_selection" for step in plan.steps):
        return plan
    field, operation, operator = intent
    by_id = {step.id: step for step in plan.steps}
    matches = [(index, step, offset, condition.value) for index, step in enumerate(plan.steps)
               if isinstance(step, ReverseStep)
               for offset, condition in enumerate(step.inputs.constraints)
               if condition.field == field and condition.operator == operator]
    if len(matches) != 1:
        return plan
    index, search, offset, value = matches[0]
    if not isinstance(value, ResultRef) or value.step_id not in search.depends_on:
        return plan
    compare = by_id.get(value.step_id)
    if isinstance(compare, DeriveStep) and value.field == "value" and value.scope.kind == "scalar":
        if _bind_existing_group_calculation(compare, by_id, field, operation, len(selected_keys)):
            return plan
        return _connect_selected_value_source(plan, search, compare, field, operation)
    if not isinstance(compare, CompareStep):
        return plan
    generic_result = value.field == "value" and compare.inputs.fields == [field]
    if value.field != field and not generic_result:
        return plan
    if value.scope.kind != "scalar" and not (value.scope.kind == "context_selection"
                                              and value.scope.key == "selected_runs"):
        return plan
    if (field not in compare.inputs.fields
            or compare.inputs.runs.model_dump() != {"kind": "context_ref", "key": "selected_runs"}
            or compare.run_if or compare.required_prior_outputs):
        return plan
    raw = plan.model_dump(mode="json")
    search_step = raw["steps"][index]
    search_step["inputs"]["constraints"][offset]["value"] = {"kind": "selected_runs_aggregate", "operation": operation}
    # The comparison is already a dependency and provides the two operands through the new binding.
    search_step["required_prior_outputs"] = [
        row.model_dump() for row in search.required_prior_outputs
        if not (row.step_id == compare.id and row.unit in (None, UNITS[field])
                and (row.field == field and row.count in (None, len(selected_keys)) and row.value_type in (None, "quantities")
                     or generic_result and row.field == "value" and row.count in (None, 1)
                     and row.value_type in (None, "quantity")))
    ]
    return PlanDraft.model_validate(expand_selected_runs_aggregates(raw, selected_keys))


def _bind_existing_group_calculation(calculation, by_id, field, operation, size):
    if calculation.operation not in {"min", "max", "mean"} or calculation.run_if or calculation.inputs.direction:
        return False
    values = calculation.inputs.values
    operands = values if isinstance(values, list) else [values]
    if len(operands) != 1 or not isinstance(operands[0], ResultRef):
        return False
    ref = operands[0]
    source = by_id.get(ref.step_id)
    expected = {"kind": "context_selection", "key": "selected_runs"}
    if (ref.field != field or ref.scope.model_dump() != expected or calculation.depends_on != [ref.step_id]
            or not isinstance(source, CompareStep) or field not in source.inputs.fields or source.run_if
            or source.inputs.runs.model_dump() != {"kind": "context_ref", "key": "selected_runs"}):
        return False
    if calculation.operation == operation and not isinstance(values, list):
        return True
    calculation.operation = operation
    calculation.inputs.values = ref
    calculation.required_prior_outputs = [
        guard for guard in calculation.required_prior_outputs
        if not (guard.step_id == source.id and guard.unit in (None, UNITS[field])
                and (guard.field == field and guard.count in (None, size) and guard.value_type in (None, "quantities")
                     or source.inputs.fields == [field] and guard.field == "value" and guard.count in (None, 1)
                     and guard.value_type in (None, "quantity")))
    ]
    return True


def _new_id(base, occupied):
    name, index = base, 1
    while name in occupied:
        index += 1
        name = f"{base}_{index}"
    occupied.add(name)
    return name


def _connect_selected_value_source(plan, search, calculation, field, operation):
    if (calculation.operation != operation or calculation.depends_on or calculation.run_if
            or calculation.required_prior_outputs or calculation.inputs.direction is not None):
        return plan
    source = calculation.inputs.values
    values = source if isinstance(source, list) else [source]
    group = {"kind": "context_ref", "key": "selected_runs"}
    self_ref = {"kind": "result_ref", "step_id": calculation.id, "field": "value", "scope": {"kind": "scalar"}}
    # A selection or the calculation's own result does not supply its numeric operands.
    if len(values) != 1 or values[0].model_dump() not in (group, self_ref):
        return plan
    raw = plan.model_dump(mode="json")
    by_id = {step["id"]: step for step in raw["steps"]}
    calculation_step = by_id[calculation.id]
    compare_id = _new_id("s_selected_compare", set(by_id))
    raw["steps"].insert(raw["steps"].index(calculation_step), {
        "id": compare_id, "kind": "tool", "tool": "compare_runs",
        "inputs": {"runs": group, "fields": [field]}, "requirement_ids": calculation.requirement_ids,
    })
    calculation_step["depends_on"] = [compare_id]
    calculation_step["inputs"]["values"] = {"kind": "result_ref", "step_id": compare_id, "field": field,
                                             "scope": {"kind": "context_selection", "key": "selected_runs"}}
    by_id[search.id]["required_prior_outputs"] = [
        row.model_dump() for row in search.required_prior_outputs
        if not (row.step_id == calculation.id and row.field == "value" and row.count in (None, 1)
                and row.value_type in (None, "quantity") and row.unit in (None, UNITS[field]))
    ]
    for requirement in raw["requirements"]:
        if requirement["id"] in calculation.requirement_ids:
            requirement["handled_by"].append(compare_id)
    return PlanDraft.model_validate(raw)


class SelectedRunsAggregate(ClosedModel):
    kind: Literal["selected_runs_aggregate"]
    operation: Literal["max", "min", "mean"]


def expand_selected_runs_aggregates(plan, confirmed_run_keys):
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
        return plan
    steps = plan["steps"]
    occupied = {step["id"] for step in steps if isinstance(step, dict) and isinstance(step.get("id"), str)}
    selected_runs = {"kind": "context_ref", "key": "selected_runs"}

    for search in tuple(steps):
        if not isinstance(search, dict) or search.get("tool") != "reverse_search":
            continue
        inputs = search.get("inputs")
        if not isinstance(inputs, dict) or not isinstance(inputs.get("constraints"), list):
            continue
        for condition in inputs["constraints"]:
            value = condition.get("value") if isinstance(condition, dict) else None
            if not isinstance(value, dict) or value.get("kind") != "selected_runs_aggregate":
                continue
            aggregate = SelectedRunsAggregate.model_validate(value)
            if len(set(confirmed_run_keys)) < 2 or any(
                isinstance(step, dict) and step.get("confirmation") == "run_selection" for step in steps
            ):
                raise ValueError("selected_runs_aggregate requires at least two already confirmed Runs")
            if condition.get("operator") == "between":
                raise ValueError("selected_runs_aggregate requires a single search threshold")

            field = condition.get("field")
            dependencies = search.get("depends_on", [])
            requirement_ids = search.get("requirement_ids", [])
            if not isinstance(dependencies, list) or not isinstance(requirement_ids, list):
                raise ValueError("search step dependencies and requirements must be arrays")
            compare = None
            for step in steps:
                if not isinstance(step, dict) or step.get("tool") != "compare_runs":
                    continue
                if not isinstance(step.get("id"), str):
                    continue
                if step.get("depends_on") and step.get("id") not in dependencies:
                    continue
                if step.get("run_if") or step.get("required_prior_outputs") or step.get("requires"):
                    continue
                compared = step.get("inputs")
                if (isinstance(compared, dict) and compared.get("runs") == selected_runs
                        and isinstance(compared.get("fields"), list) and field in compared["fields"]):
                    compare = step
                    break
            added = []
            if compare is None:
                compare = {"id": _new_id("s_selected_compare", occupied), "kind": "tool", "tool": "compare_runs",
                           "inputs": {"runs": selected_runs, "fields": [field]},
                           "requirement_ids": requirement_ids}
                added.append(compare)
            calculation = _new_id("s_search_threshold", occupied)
            compare_id = compare["id"]
            added.append({
                "id": calculation, "kind": "derive", "operation": aggregate.operation,
                "depends_on": [compare_id], "requirement_ids": requirement_ids,
                "inputs": {"values": {"kind": "result_ref", "step_id": compare_id, "field": field,
                                      "scope": {"kind": "context_selection", "key": "selected_runs"}}},
            })
            index = steps.index(search)
            steps[index:index] = added
            search["depends_on"] = [*dependencies, calculation]
            condition["value"] = {"kind": "result_ref", "step_id": calculation, "field": "value",
                                  "scope": {"kind": "scalar"}}
            for item in plan.get("requirements", []):
                if (isinstance(item, dict) and item.get("id") in requirement_ids
                        and isinstance(item.get("handled_by"), list)):
                    item["handled_by"].extend(step["id"] for step in added)
    return plan
