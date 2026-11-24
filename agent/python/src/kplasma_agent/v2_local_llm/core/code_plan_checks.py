"""Check explicit Run targets and search order against the accepted plan."""

import re
from typing import Literal, TypedDict

from ..domain.grounding import _ALIASES, _NUMBER, _UNIT, _operator
from ..metric_registry import DEFAULT_METRICS, NumericError, normalize_value
from .bindings import BlockedInput, resolve_comparison_entries
from .contracts import AwaitInputStep, CompareStep, ConstraintInput, DeriveStep, ExplainStep, GoalInput, LiteralInput, ReverseStep
from .planner_input import _remove_redundant_step, explicit_comparison_outputs, selected_aggregate_intent

_METRIC = "|".join(f"(?:{aliases})" for aliases in _ALIASES.values())
_METRIC_PATTERNS = {field: re.compile(aliases, re.I) for field, aliases in _ALIASES.items()}
_VALUE = rf"{_NUMBER}(?:\s*(?:×\s*)?{_UNIT})?"
_BOUND = r"(?:[을를]\s*)?(?:엄격히\s*)?(?:이상|이하|미만|초과|보다\s*(?:크고|작은|높고|낮은))"
_OPERAND = rf"(?:{_NUMBER}\s*[~–—-]\s*{_VALUE}|{_VALUE}(?:\s*{_BOUND}(?:\s+{_VALUE}\s*{_BOUND})?)?)"
_CONDITION = rf"(?:{_METRIC})(?:[이가은는])?\s+{_OPERAND}"
_FILTER = rf"{_CONDITION}(?:(?:\s|,|이면서|이고|이며|하고|고|와|과|및)+{_CONDITION}){{0,4}}"
_RUNS = r"(?:실제\s+)?Runs?"
_FIND = r"(?:찾아\s*줘|검색해\s*줘|보여\s*줘)"
_RUN_OBJECT = rf"{_RUNS}(?:을|만)(?:\s*모두)?"
_ORDER = (rf"(?P<metric>{_METRIC})(?:[이가의])?\s*"
          r"(?:(?P<descending>높은\s*순|내림차순)|낮은\s*순|오름차순)(?:으로|로)")
_SEARCH = re.compile(
    rf"(?:{_FILTER}(?:인|는)?\s*)?{_RUN_OBJECT}\s*"
    rf"(?:(?:찾아서,?\s*)?{_ORDER}\s*(?:정렬해\s*줘|{_FIND})|{_FIND})",
    re.I,
)
_SCIENTIFIC_FLUX_BOUND = re.compile(
    rf"(?:{_ALIASES['ionFlux']})(?:[이가은는])?\s+(?P<amount>{_NUMBER})\s*"
    r"(?:m⁻²\s*s⁻¹|m\^-2\s*s\^-1|m-2s-1)\s*(?P<bound>이상|이하|초과|미만)(?:이고|이며|하고|고)?",
    re.I,
)
_SHARED_ORDER = re.compile(
    rf"(?P<first>{_CONDITION})인\s*후보(?:와|과)\s*(?P<second>{_CONDITION}|{_OPERAND})인\s*후보를\s*각각\s*{_FIND}\.\s*"
    rf"(?:두|각)\s*그룹을\s*따로\s*보여\s*주고,?\s*(?:두|각)\s*그룹\s*안에서는\s*{_ORDER}\s*정렬해\s*줘",
    re.I,
)
_ENDPOINTS = re.compile(rf"(?P<low>{_VALUE})\s*(?:와|과)\s*(?P<high>{_VALUE})[은는]\s*둘\s*다\s*제외해\s*줘", re.I)
_OPEN_INTERVAL = re.compile(
    rf"(?P<field>{_METRIC})(?:[이가은는])?\s+(?P<lower>(?P<low>{_VALUE})\s*보다\s*(?:크고|높고))\s*"
    rf"(?P<upper>(?P<high>{_VALUE})\s*보다\s*(?:작은|낮은))\s*{_RUN_OBJECT}\s*{_FIND}", re.I,
)
_QUANTITY = re.compile(rf"(?P<number>{_NUMBER})(?:\s*(?:×\s*)?(?P<unit>{_UNIT}))?", re.I)
_RANGE = re.compile(rf"(?P<low>{_NUMBER})\s*[~–—-]\s*(?P<high>{_NUMBER})(?:\s*(?P<unit>{_UNIT}))?", re.I)
_ITEM = (rf"(?:{_METRIC}|(?:전극\s*전위\s*)?(?:최댓값|최솟값|첨두간\s*값)"
         r"|(?:IEAD|IAD|IED)\s*최대\s*강도|피크\s*(?:에너지·각도|에너지|입사각|각도))")
_FIELDS = rf"{_ITEM}(?:\s*(?:,|와|과|및|그리고)\s*{_ITEM}){{0,6}}(?:을|를|만)?"
_COMPARE = (rf"{_FIELDS}\s*(?:(?:현재 지정된 )?기준(?: Run)? 대비(?: 부호 있는 차이와 변화율로)?\s*"
            r"|공정 조건에 따른 경향으로\s*)?"
            r"(?:비교해\s*줘|비교해서\s*각 항목의 절대 차이를 보여\s*줘|차이를 보여\s*줘)")
_SELECTED = re.compile(rf"(?:이미\s*)?선택한\s*(?:두|2개(?:의)?)\s*{_RUNS}의\s*{_COMPARE}", re.I)
_WHOLE_GROUP = re.compile(
    rf"{_FILTER}(?:인|는)?\s*(?:모든\s*{_RUNS}의\s*"
    rf"|{_RUNS}을\s*모두\s*찾아(?:서|내고),?\s*(?:찾은\s*)?전체(?:\s*{_RUNS})?의\s*){_COMPARE}",
    re.I,
)
_CHOOSE_AXIS = re.compile(r"경향을 볼 공정 조건 축은 내가 직접 선택하게 해\s*줘")
_CHOOSE_COUNT = r"(?:두|세|[2-9])\s*개"
_SEARCH_THEN_PICK = re.compile(
    rf"{_FILTER}(?:인|는)?\s*{_RUN_OBJECT}\s*{_FIND}\.\s*그\s*중\s*(?:정확히\s*)?{_CHOOSE_COUNT}(?:는|를)?\s*"
    rf"내가\s*(?:직접\s*)?고를\s*테니\s*선택창을\s*띄우고,?\s*선택한\s*{_CHOOSE_COUNT}의\s*{_COMPARE}",
    re.I,
)
_PICK_FROM_SEARCH = re.compile(
    rf"{_FILTER}(?:인|는)?\s*{_RUNS}에서\s*(?:정확히\s*)?(?P<count>{_CHOOSE_COUNT})(?:는|를)?\s*"
    rf"내가\s*(?:직접\s*)?고를게\.\s*먼저\s*선택하게\s*해\s*주고\s*"
    rf"(?:고른|선택한)\s*(?P<picked>{_CHOOSE_COUNT})의\s*{_COMPARE}", re.I,
)
_AGGREGATE_SEARCH_SUFFIX = re.compile(rf"(?:{_FILTER}(?:인|는)?\s*)?{_RUN_OBJECT}\s*{_FIND}", re.I)


class CodeCheck(TypedDict):
    choice: Literal["match", "missing", "unexpected", "direction_changed", "target_changed"]
    path: str
    actual: list | dict
    allowed: list | dict
    message: str


def use_explicit_search_intent(plan, question):
    if plan.request_mode != "data_request" or len(question) > 512:
        return
    text = " ".join(question.split()).rstrip(".!?")
    shared = _SHARED_ORDER.fullmatch(text)
    separate = text.split(". ", 1)
    opened = _OPEN_INTERVAL.fullmatch(separate[0]) if len(separate) == 2 else None
    excluded = _ENDPOINTS.fullmatch(separate[1]) if opened else None
    plain = _SEARCH.fullmatch(text)
    if not (shared or (opened and excluded) or plain):
        return
    searches = [step for step in plan.steps if isinstance(step, ReverseStep)]
    if len(searches) != (2 if shared else 1):
        return
    if any(step.depends_on or step.run_if or step.required_prior_outputs for step in searches):
        return
    order = _sort_spec(plain) if plain else []
    goal = GoalInput.model_validate(order[0]) if len(order) == 1 and order[0]["field"] in DEFAULT_METRICS else None
    extras = [step for step in plan.steps if not isinstance(step, ReverseStep)]
    if any(not (isinstance(step, ExplainStep) or isinstance(step, AwaitInputStep)
                and step.confirmation == "run_selection"
                or goal and _sort_only_comparison(step, searches[0].id, goal.field)) for step in extras):
        return
    if shared and not _apply_grouped_order(searches, shared, question):
        return
    if opened and not _apply_open_interval(searches[0], opened, excluded, question):
        return
    if plain:
        _preserve_scientific_flux_threshold(searches[0], question)
        if goal and not any(item.direction != "target_range" for item in searches[0].inputs.goals):
            searches[0].inputs.goals.append(goal)
    if not extras:
        return
    extra_ids = {step.id for step in extras}
    extra_requirements = [req for step in extras for req in step.requirement_ids]
    search_ids = [step.id for step in searches]
    for step in searches:
        step.requirement_ids = list(dict.fromkeys([*step.requirement_ids, *extra_requirements]))
    for requirement in plan.requirements:
        requirement.handled_by = list(dict.fromkeys(
            step_id for sid in requirement.handled_by for step_id in (search_ids if sid in extra_ids else [sid])))
    plan.steps = searches


def _sort_only_comparison(step, search_id, field):
    return (isinstance(step, CompareStep) and step.depends_on == [search_id] and not step.run_if
            and step.inputs.baseline is None and step.inputs.trend_axis is None and not step.inputs.plot_ids
            and set(step.inputs.fields) == {field} and step.inputs.runs.model_dump() == {
                "kind": "result_ref", "step_id": search_id, "field": "candidates", "scope": {"kind": "candidate_group"},
            })


def use_explicit_comparison_results_only(plan, question):
    if plan.request_mode != "data_request" or len(question) > 512 or len(plan.steps) < 3:
        return
    explanation = plan.steps[-1]
    if not isinstance(explanation, ExplainStep) or explanation.inputs.mode != "results":
        return
    work = plan.steps[:-1]
    searches = [step for step in work if isinstance(step, ReverseStep)]
    comparisons = [step for step in work if isinstance(step, CompareStep)]
    if len(searches) != 1 or len(comparisons) != 1:
        return
    text = " ".join(question.split()).rstrip(".!?")
    compare, = comparisons
    search, = searches
    if compare.inputs.baseline is not None or compare.inputs.trend_axis is not None:
        return
    if len(work) == 2 and _WHOLE_GROUP.fullmatch(text):
        _remove_redundant_step(plan, explanation, compare)
    elif len(work) == 3 and any(isinstance(step, AwaitInputStep) and step.confirmation == "run_selection" for step in work):
        if _SEARCH_THEN_PICK.fullmatch(text) or _PICK_FROM_SEARCH.fullmatch(text):
            _remove_redundant_step(plan, explanation, compare)
    elif len(work) == 3 and any(isinstance(step, DeriveStep) for step in work):
        if selected_aggregate_intent(text, search_suffix=_AGGREGATE_SEARCH_SUFFIX):
            _remove_redundant_step(plan, explanation, search)


def _quantity(field, number, unit):
    return normalize_value(field, float(number.replace(",", "")), unit)


def _apply_open_interval(search, opened, excluded, question):
    bounds = search.inputs.constraints
    if len(bounds) != 1 or bounds[0].operator != "between":
        return True
    bound = bounds[0]
    if (not _METRIC_PATTERNS[bound.field].fullmatch(opened["field"])
            or not all(isinstance(item, LiteralInput) for item in (bound.min, bound.max))):
        return False
    try:
        for name, binding in (("low", bound.min), ("high", bound.max)):
            clause = _QUANTITY.fullmatch(opened[name])
            exclusion = _QUANTITY.fullmatch(excluded[name])
            value = normalize_value(bound.field, binding.value, binding.unit)
            if not clause or not exclusion or not all(
                value == _quantity(bound.field, item["number"], item["unit"]) for item in (clause, exclusion)
            ):
                return False
    except NumericError:
        return False
    for binding, clause in ((bound.min, opened["lower"]), (bound.max, opened["upper"])):
        if binding.source.message_key == "question" and binding.source.quote not in question and question.count(clause) == 1:
            binding.source.quote = clause
    search.inputs.constraints = [ConstraintInput(field=bound.field, operator="gt", value=bound.min),
                                 ConstraintInput(field=bound.field, operator="lt", value=bound.max)]
    return True


def _apply_grouped_order(searches, shared, question):
    goals = _sort_spec(shared)
    if (len(goals) != 1 or goals[0]["field"] not in DEFAULT_METRICS
            or any(len(step.inputs.constraints) != 1 for step in searches)):
        return False
    first, second = [step.inputs.constraints[0] for step in searches]
    metric_name = _METRIC_PATTERNS[first.field].pattern
    named_metric = rf"(?:{metric_name})(?:[이가은는])?\s+"
    first_range = re.sub(r"^" + named_metric, "", shared["first"], flags=re.I)
    second_range = shared["second"]
    ranges = (_RANGE.fullmatch(first_range), _RANGE.fullmatch(second_range))
    if first.field != second.field or not all(ranges) or question.count(second_range) != 1:
        return False
    for bound, limits in zip((first, second), ranges, strict=True):
        if bound.operator != "between" or not all(isinstance(item, LiteralInput) for item in (bound.min, bound.max)):
            return False
        try:
            if any(normalize_value(bound.field, item.value, item.unit) != _quantity(bound.field, limits[key], limits["unit"])
                   for key, item in (("low", bound.min), ("high", bound.max))):
                return False
        except NumericError:
            return False
    for item in (second.min, second.max):
        source = item.source
        if (source.message_key == "question" and source.quote not in question
                and re.fullmatch(named_metric + re.escape(second_range), source.quote, re.I)):
            source.quote = second_range
    for step in searches:
        if not step.inputs.goals:
            step.inputs.goals = [GoalInput.model_validate(goals[0])]
    return True


def _preserve_scientific_flux_threshold(search, question):
    bounds = [condition for condition in search.inputs.constraints if condition.field == "ionFlux"]
    if len(bounds) != 1 or not isinstance(bounds[0].value, LiteralInput):
        return
    condition = bounds[0]
    binding = condition.value
    quote = binding.source.quote
    if binding.source.message_key != "question" or question.count(quote) != 1:
        return
    match = _SCIENTIFIC_FLUX_BOUND.fullmatch(" ".join(quote.split()))
    if not match or "e" not in match["amount"].lower() or condition.operator != _operator(match["bound"]):
        return
    amount = float(match["amount"].replace(",", ""))
    unit = "m⁻²s⁻¹"
    try:
        expected = normalize_value("ionFlux", amount, unit)
        actual = normalize_value("ionFlux", binding.value, binding.unit)
    except NumericError:
        return
    if actual != expected:
        condition.value = binding.model_copy(update={"value": amount, "unit": unit})


def code_plan_checks(question: str, plan: dict, confirmed_context: dict, input_history: list[dict],
                     *, flash: bool = False) -> dict[str, CodeCheck]:
    checks = _explicit_plan_checks(question, plan, confirmed_context, input_history)
    if flash:
        if not input_history:
            checks.update(_selected_aggregate_checks(question, plan, confirmed_context))
            checks.update(_explicit_output_checks(question, plan, confirmed_context))
        checks.update(_flash_checks(question, plan, input_history))
    return checks


def _explicit_output_checks(question, plan, confirmed_context):
    if len({ref["runVersionId"] for ref in confirmed_context.get("selected_runs", [])}) != 2:
        return {}
    outputs = explicit_comparison_outputs(question)
    comparisons = [(index, step) for index, step in enumerate(plan["steps"]) if step.get("tool") == "compare_runs"]
    if not outputs or len(comparisons) != 1:
        return {}
    index, comparison = comparisons[0]
    inputs = comparison["inputs"]
    if inputs["runs"] != {"kind": "context_ref", "key": "selected_runs"}:
        return {}
    checks = {}
    if inputs["fields"] == list(outputs.fields) and set(inputs["plot_ids"]) <= {outputs.plot}:
        actual = {"fields": inputs["fields"], "plot_ids": inputs["plot_ids"]}
        checks[f"outputs.{comparison['id']}"] = {
            "choice": "match", "path": f"/steps/{index}/inputs/fields", "actual": actual, "allowed": actual,
            "message": "원문에 명시된 비교 지표와 분포 계열이 일치한다.",
        }
    choice = outputs.confirmation
    if not choice:
        return checks
    for index, step in enumerate(plan["steps"]):
        if step.get("confirmation") != choice:
            continue
        expected = {"target_step_id": comparison["id"], "field": choice, "candidates": None,
                    "selection_count": None}
        reference = {"kind": "result_ref", "step_id": step["id"], "field": "value", "scope": {"kind": "scalar"}}
        if (step["inputs"] == expected and not step["run_if"] and not step["required_prior_outputs"]
                and inputs[choice] == reference and step["id"] in comparison["depends_on"]):
            name = f"baseline.{comparison['id']}" if choice == "baseline" else f"selection_targets.{step['id']}"
            checks[name] = {
                "choice": "match", "path": f"/steps/{index}/inputs", "actual": expected, "allowed": expected,
                "message": "사용자가 직접 고른 값을 요청한 비교 옵션에 연결한다.",
            }
    return checks


def _explicit_plan_checks(question, plan, confirmed_context, input_history):
    # Full clauses avoid treating an unrecognized qualifier or selection as absent.
    if input_history or len(question) > 512:
        return {}
    question = " ".join(question.split()).rstrip(".!?")
    shared = _SHARED_ORDER.fullmatch(question)
    clauses = [] if shared else re.split(r"[.!?](?:\s+|$)", question)
    orders = [_sort_spec(shared)] * 2 if shared else []
    targets = []
    preceding = ""
    for clause in filter(None, clauses):
        search = _SEARCH.fullmatch(clause)
        if search:
            orders.append(_sort_spec(search))
            if search["metric"] and len(orders[-1]) != 1:
                return {}
            preceding = "search"
        elif preceding == "search" and _ENDPOINTS.fullmatch(clause):
            preceding = ""
        elif _SELECTED.fullmatch(clause):
            targets.append("selected")
            preceding = "selected"
        elif preceding == "selected" and _CHOOSE_AXIS.fullmatch(clause):
            preceding = ""
        elif _WHOLE_GROUP.fullmatch(clause):
            orders.append([])
            targets.append("search")
            preceding = "group"
        else:
            return {}

    steps = plan["steps"]
    searches = [(index, step) for index, step in enumerate(steps) if step.get("tool") == "reverse_search"]
    comparisons = [(index, step) for index, step in enumerate(steps) if step.get("tool") == "compare_runs"]
    checks: dict[str, CodeCheck] = {}
    if (shared or len(orders) == 1) and len(orders) == len(searches):
        for (index, step), expected in zip(searches, orders, strict=True):
            checks[f"ordering.{step['id']}"] = _ordering_check(step, index, expected)

    if len(targets) == len(comparisons) == 1:
        index, step = comparisons[0]
        runs = step["inputs"]["runs"]
        if targets[0] == "search":
            if len(searches) != 1 or len(orders) != 1:
                return checks
            expected_runs = {"kind": "result_ref", "step_id": searches[0][1]["id"], "field": "candidates",
                             "scope": {"kind": "candidate_group"}}
            matched = runs == expected_runs and expected_runs["step_id"] in step["depends_on"]
        else:
            selected = confirmed_context.get("selected_runs", [])
            expected_refs = {ref["runVersionId"] for ref in selected}
            if len(selected) != 2 or len(expected_refs) != 2:
                return checks
            expected_runs = {"kind": "context_ref", "key": "selected_runs"}
            try:
                entries = resolve_comparison_entries(CompareStep.model_validate(step), confirmed_context, {})
                matched = {entry["ref"]["runVersionId"] for entry in entries} == expected_refs
            except BlockedInput:
                matched = False
        checks[f"targets.{step['id']}"] = {
            "choice": "match" if matched else "target_changed",
            "path": f"/steps/{index}/inputs/runs", "actual": runs, "allowed": expected_runs,
            "message": "runs를 allowed의 비교 대상으로 연결한다. 결과 참조면 해당 단계에 의존하도록 연결한다.",
        }
    return checks


def _sort_spec(match):
    metric = match["metric"]
    direction = "maximize" if match["descending"] else "minimize"
    return [{"field": field, "direction": direction}
            for field, pattern in _METRIC_PATTERNS.items() if metric and pattern.fullmatch(metric)]


def _ordering_check(step, index, expected):
    actual = [{"field": goal["field"], "direction": goal["direction"]}
              for goal in step["inputs"]["goals"] if goal["direction"] != "target_range"]
    return {
        "choice": ("match" if actual == expected else "unexpected" if not expected
                   else "missing" if not actual else "direction_changed"),
        "path": f"/steps/{index}/inputs/goals", "actual": actual, "allowed": expected,
        "message": "goals의 정렬 지표와 방향을 allowed대로 수정한다. target_range 필터는 보존한다.",
    }


def _selected_aggregate_checks(question, plan, confirmed_context):
    if len({ref["runVersionId"] for ref in confirmed_context.get("selected_runs", [])}) != 2:
        return {}
    intent = selected_aggregate_intent(question)
    if intent is None:
        return {}
    field, operation, operator = intent
    steps = plan["steps"]
    by_id = {step["id"]: step for step in steps}
    bindings = [(condition, condition["value"]["step_id"]) for step in steps
                if step.get("tool") == "reverse_search" for condition in step["inputs"]["constraints"]
                if isinstance(condition["value"], dict) and condition["value"]["kind"] == "result_ref"
                and by_id.get(condition["value"]["step_id"], {}).get("kind") == "derive"]
    matching = [(condition, step_id) for condition, step_id in bindings if condition["field"] == field]
    if len(matching) != 1:
        return {}
    condition, step_id = matching[0]
    if sum(source == step_id for _, source in bindings) != 1:
        return {}
    step = by_id[step_id]
    values = step["inputs"]["values"]
    values = values if isinstance(values, list) else [values]
    if len(values) != 1 or values[0]["kind"] != "result_ref":
        return {}
    ref = values[0]
    comparator = by_id.get(ref["step_id"], {})
    expected_source = {"kind": "context_ref", "key": "selected_runs"}
    expected_scope = {"kind": "context_selection", "key": "selected_runs"}
    source = comparator.get("inputs", {}).get("runs")
    actual = {"operation": step["operation"], "operator": condition["operator"],
              "field": ref["field"], "runs": source, "scope": ref["scope"]}
    allowed = {"operation": operation, "operator": operator, "field": field,
               "runs": expected_source, "scope": expected_scope}
    if step["operation"] != operation or condition["operator"] != operator:
        choice = "direction_changed"
    elif actual != allowed or comparator.get("tool") != "compare_runs":
        choice = "target_changed"
    else:
        choice = "match"
    checks = {f"operation.{step_id}": {
        "choice": choice, "path": f"/steps/{steps.index(step)}/inputs", "actual": actual, "allowed": allowed,
        "message": "확인된 두 Run의 해당 지표를 계산하고 그 계산값을 검색의 비교 기준으로 연결한다.",
    }}
    if (choice == "match" and operation == "mean" and comparator["inputs"]["baseline"] is None
            and not re.search(r"기준|대비|상대|baseline|reference", question, re.I)
            and not any(item.get("confirmation") == "baseline" for item in steps)):
        checks[f"baseline.{comparator['id']}"] = {
            "choice": "match", "path": f"/steps/{steps.index(comparator)}/inputs/baseline",
            "actual": {"baseline": None}, "allowed": {"baseline": None},
            "message": "선택한 Run들의 평균 수치가 검색값이며 비교 기준 Run을 지정할 필요가 없다.",
        }
    return checks


def _flash_checks(question, plan, input_history) -> dict[str, CodeCheck]:
    steps = plan["steps"]
    sources = {step["id"]: step for step in steps}
    checks = {}
    standalone = " ".join(question.split()).rstrip(".!?") if not input_history and len(question) <= 512 else ""
    selection_request = _SEARCH_THEN_PICK.fullmatch(standalone)
    pick_from_search = _PICK_FROM_SEARCH.fullmatch(standalone)
    for index, step in enumerate(steps):
        if (selection_request or pick_from_search) and step.get("confirmation") == "run_selection" and not step["run_if"]:
            candidates = step["inputs"]["candidates"] or {}
            source = sources.get(candidates.get("step_id"), {})
            expected = [{"step_id": source.get("id"), "field": "candidates", "count": None,
                         "value_type": "run_refs", "unit": None}]
            if (source.get("tool") == "reverse_search" and candidates.get("field") == "candidates"
                    and step["required_prior_outputs"] == expected):
                checks[f"execution_guards.{step['id']}"] = {
                    "choice": "match", "path": f"/steps/{index}/required_prior_outputs",
                    "actual": expected, "allowed": expected,
                    "message": "선택창이 읽는 동일한 후보 목록의 자료형만 확인한다.",
                }
            if pick_from_search and _matches_requested_choice(step, source, sources, pick_from_search):
                checks[f"selection_targets.{step['id']}"] = {
                    "choice": "match", "path": f"/steps/{index}/inputs",
                    "actual": step["inputs"], "allowed": step["inputs"],
                    "message": "검색 후보 중 사용자가 고르는 Run을 후속 비교가 읽는다.",
                }
        if step.get("tool") != "compare_runs":
            continue
        prerequisites = step["required_prior_outputs"]
        allowed = []
        for requirement in prerequisites:
            source = sources.get(requirement["step_id"], {})
            run_list = (
                source.get("tool") == "reverse_search" and requirement["field"] == "candidates"
                or source.get("confirmation") == "run_selection" and requirement["field"] == "selection"
            )
            allowed.append({**requirement, "unit": None, "value_type": "run_refs"}
                           if run_list and requirement["unit"] is not None else requirement)
        if allowed != prerequisites:
            checks[f"execution_guards.{step['id']}"] = {
                "choice": "unexpected", "path": f"/steps/{index}/required_prior_outputs",
                "actual": prerequisites, "allowed": allowed,
                "message": "Run 참조 목록에는 물리 단위가 없다. 실행 전제에서 해당 물리 단위를 제거한다.",
            }

    # Only a fully recognized, standalone search can prove that no dialog or comparison was requested.
    if not _SEARCH.fullmatch(standalone):
        return checks
    confirmations = [step["confirmation"] for step in steps if step["kind"] == "await_input"]
    if confirmations:
        checks["request.confirmation_coverage"] = {
            "choice": "unexpected", "path": "/steps", "actual": confirmations, "allowed": [],
            "message": "사용자가 요청한 조회·정렬을 바로 수행하고, 요청하지 않은 확인 단계를 제거한다.",
        }
    for index, step in enumerate(steps):
        if step.get("tool") == "compare_runs":
            checks[f"targets.{step['id']}"] = {
                "choice": "unexpected", "path": f"/steps/{index}/inputs/runs",
                "actual": step["inputs"]["runs"], "allowed": [],
                "message": "사용자가 요청한 조회·정렬을 보존하고, 요청하지 않은 비교 단계를 제거한다.",
            }
    return checks


def _matches_requested_choice(step, source, sources, request):
    count = {"두": 2, "세": 3, **{str(number): number for number in range(2, 10)}}
    requested = count[request["count"][:-1].strip()]
    if requested != count[request["picked"][:-1].strip()] or step["inputs"]["selection_count"] != requested:
        return False
    if source.get("tool") != "reverse_search" or source["run_if"] or step["depends_on"] != [source["id"]]:
        return False
    expected_candidates = {"kind": "result_ref", "step_id": source["id"], "field": "candidates",
                           "scope": {"kind": "candidate_group"}}
    if step["inputs"]["candidates"] != expected_candidates:
        return False
    comparison = sources.get(step["inputs"]["target_step_id"], {})
    expected_runs = {"kind": "result_ref", "step_id": step["id"], "field": "selection", "scope": {"kind": "scalar"}}
    return (step["inputs"]["field"] == "runs" and comparison.get("tool") == "compare_runs"
            and comparison["inputs"]["runs"] == expected_runs and step["id"] in comparison["depends_on"])
