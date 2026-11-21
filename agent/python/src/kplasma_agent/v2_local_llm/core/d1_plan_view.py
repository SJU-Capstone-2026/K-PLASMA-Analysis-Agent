"""Prepare the per-check d1 view without changing the executable plan."""

import json

from ..metric_registry import UNITS
from .d1_input import _COMMON_EN, _FORWARD_METRICS, focused_plan_instructions
from .flash_review import flash_check_input

OMISSION_QUESTION = "omission_question"
_COVERAGE = {"tasks", "filter_coverage", "confirmation_coverage"}
_HISTORY = " and latest input_history"
_FUTURE = "This is a pre-execution plan: future measurements, search results and user selections may not exist yet. "
_REFERENCE = "result_ref reads its source value and unit at execution time"
_AWAIT = "a planned await_input resumes after selection"
_BINDING = f"{_REFERENCE}; {_AWAIT}. "


def _instructions(payload: dict, spec: dict, text: str) -> str:
    steps = {step["id"]: step for step in payload["plan"]["steps"]}
    visited: set[str] = set()
    reference = guarded = False
    selection = spec["kind"] == "confirmation_coverage"

    def walk(value):
        nonlocal reference
        if isinstance(value, dict):
            if value.get("kind") == "result_ref":
                reference = True
                visit(value["step_id"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    def visit(step_id: str):
        nonlocal selection, guarded
        if step_id in visited:
            return
        visited.add(step_id)
        step = steps[step_id]
        selection |= step["kind"] == "await_input"
        guards = step["run_if"] + step["required_prior_outputs"]
        guarded |= bool(guards)
        walk(step["inputs"])
        for prior in step["depends_on"]:
            visit(prior)
        for guard in guards:
            visit(guard["step_id"])

    for step_id in spec["step_ids"] or steps:
        visit(step_id)

    common = _COMMON_EN
    if not payload["input_history"]:
        common = common.replace(_HISTORY, "", 1)
    if not (reference or selection or guarded):
        common = common.replace(_FUTURE, "", 1)
    clauses = ([_REFERENCE] if reference else []) + ([_AWAIT] if selection else [])
    return common.replace(_BINDING, "; ".join(clauses) + ". " if clauses else "", 1) + text[len(_COMMON_EN):]


def _cited_operand(value):
    if not isinstance(value, dict):
        return value
    if "kind" not in value:
        return {key: _cited_operand(item) for key, item in value.items()}
    if value["kind"] != "literal" or type(value.get("value")) not in (int, float):
        raise ValueError("nonliteral filter operand")
    return {("citation" if key == "source" else key): item for key, item in value.items()}


def _question_citations(value):
    if isinstance(value, list):
        for item in value:
            yield from _question_citations(item)
    elif isinstance(value, dict):
        citation = value.get("citation")
        if citation and citation["message_key"] == "question":
            yield citation["quote"]
        for item in value.values():
            yield from _question_citations(item)


def _compact_filter(step_id: str, index: int, selected: dict, spec: dict) -> dict:
    needs_default_unit = False

    def compact(operand):
        nonlocal needs_default_unit
        if "citation" not in operand:
            return {key: compact(item) if isinstance(item, dict) else item
                    for key, item in operand.items() if item is not None}
        citation = operand["citation"]
        if citation["message_key"] != "question":
            raise ValueError("filter refers to another message")
        needs_default_unit |= operand["unit"] is None
        return {"value": operand["value"], "unit": operand["unit"], "citation": {"quote": citation["quote"]}}

    inputs: dict = {}
    for _, _, _, key, *position in spec["paths"]:
        if position:
            row, = position
            values = inputs.setdefault(key, [])
            # Keep the path named by the check instructions even if earlier rows are omitted.
            values.extend([None] * (row + 1 - len(values)))
            values[row] = compact(selected[key][row])
        else:
            inputs[key] = compact(selected[key])
    state: dict = {"plan": {"steps": [None] * index + [{"id": step_id, "inputs": inputs}]}}
    if needs_default_unit:
        metric = spec["metric"]
        state["default_unit"] = UNITS[_FORWARD_METRICS.get(metric, metric)]
    return state


def _filter_operands(plan: dict, spec: dict) -> tuple[int, dict, dict]:
    index, = {path[1] for path in spec["paths"]}
    step = plan["steps"][index]
    if any(step[key] for key in ("depends_on", "run_if", "required_prior_outputs")):
        raise ValueError("dependent filter")
    selected: dict = {}
    if step["tool"] == "reverse_search":
        selected = {key: [{"omitted_from_review": True} for _ in step["inputs"][key]]
                    for key in ("constraints", "goals")}
        for _, _, _, key, row in spec["paths"]:
            selected[key][row] = _cited_operand(step["inputs"][key][row])
    else:
        _, _, _, field = spec["paths"][0]
        operand = step["inputs"][field]
        if not isinstance(operand, dict):
            raise ValueError("missing filter operand")
        selected[field] = _cited_operand(operand)
    return index, step, selected


def _excerpt(payload: dict, spec: dict) -> str:
    plan = payload["plan"]
    index, step, selected = _filter_operands(plan, spec)
    if not payload["input_history"]:
        try:
            compact = _compact_filter(step["id"], index, selected, spec)
        except ValueError:
            pass
        else:
            return json.dumps(compact, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    quotes = list(dict.fromkeys(_question_citations(selected)))
    if quotes:
        payload["question"] = "\n".join(quotes)
    plan["requirements"] = [{key: item[key] for key in ("id", "handled_by")} for item in plan["requirements"]]
    for i, item in enumerate(plan["steps"]):
        if i == index:
            item["inputs"] = selected
        else:
            plan["steps"][i] = {key: item[key] for key in ("id", "kind", "tool", "operation", "confirmation")
                                if key in item} | {"omitted_from_review": True}
    checks = payload["check_specs"]
    payload["check_specs"] = [spec, *(item for item in checks if item["name"] != spec["name"])]
    del payload["program_effects"]
    payload["review_view"] = {"kind": "numeric_excerpt", "complete_executable_plan": False,
                              "check_name": spec["name"], "included_plan_paths": spec["paths"],
                              "omitted_fields_are_not_missing_plan_fields": True}
    bindings = payload["tool_contracts"]["bindings"]
    bindings["literal"] = bindings["literal"].replace("source.quote", "citation.quote")
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _settings(value):
    if isinstance(value, list):
        return [_settings(item) for item in value]
    if isinstance(value, dict):
        return {key: _settings(item) for key, item in value.items() if key not in {"source", "citation"}}
    return value


def _value_quotes(value):
    if isinstance(value, list):
        for item in value:
            yield from _value_quotes(item)
    elif isinstance(value, dict):
        if value.get("kind") == "literal":
            yield value["source"]["quote"]
        else:
            for item in value.values():
                yield from _value_quotes(item)


def _tool_view(step: dict) -> dict:
    kind = step.get("tool", step["kind"])
    fields = {
        "forward_lookup": ("pressure", "source_power", "bias_power"),
        "reverse_search": ("constraints", "goals"),
        "compare_runs": ("runs", "baseline", "trend_axis", "fields", "plot_ids"),
        "await_input": ("candidates", "selection_count", "target_step_id", "field"),
        "derive": ("values", "direction"),
        "explain_answer": ("mode",),
    }[kind]
    inputs = {key: step["inputs"][key] for key in fields}
    if kind == "reverse_search":
        inputs["goals"] = [goal for goal in inputs["goals"] if goal["direction"] == "target_range"]
    return {key: step[key] for key in ("id", "kind", "tool", "operation", "confirmation") if key in step} | {
        "inputs": _settings(inputs),
    }


def _links(value):
    if isinstance(value, list):
        for item in value:
            yield from _links(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"step_id", "target_step_id"} and isinstance(item, str):
                yield ("step", item)
            elif key == "key" and value.get("kind") in {"context_ref", "confirmed_run", "context_selection"}:
                yield ("context", item)
            else:
                yield from _links(item)


def _focused_plan(payload: dict, spec: dict) -> dict:
    plan = payload["plan"]
    kind = spec["kind"]
    if kind in _COVERAGE:
        return {"question": payload[OMISSION_QUESTION], "plan": plan}

    steps = plan["steps"]
    index, = {path[1] for path in spec["paths"]}
    step = steps[index]
    selected = {"id": step["id"]}
    for _, _, key, *location in spec["paths"]:
        if key != "inputs" or not location:
            selected[key] = step[key]
            continue
        field, *rows = location
        inputs = selected.setdefault("inputs", {})
        if rows:
            row, = rows
            values = inputs.setdefault(field, [])
            values.extend([None] * (row + 1 - len(values)))
            values[row] = step["inputs"][field][row]
        else:
            inputs[field] = step["inputs"][field]
    if kind in {"selection_count", "selection_targets"}:
        selected["confirmation"] = step["confirmation"]
    if kind == "selection_targets":
        selected["inputs"] = {key: value for key, value in selected["inputs"].items() if key != "selection_count"}
    if kind == "ordering":
        selected["inputs"]["goals"] = [goal for goal in selected["inputs"]["goals"]
                                       if goal["direction"] in {"maximize", "minimize"}]
    if kind == "execution_guards":
        selected["action"] = step.get("tool", step["kind"])

    citations = [source["quote"] for requirement in plan["requirements"]
                 if step["id"] in requirement["handled_by"] or requirement["id"] in step["requirement_ids"]
                 for source in requirement["sources"]]
    citations.extend(_value_quotes(selected))
    question = payload["question"]
    retry = kind == "ordering" and question == payload[OMISSION_QUESTION]
    view = {"question": question if retry or not citations else "\n".join(dict.fromkeys(citations)),
            "plan": {"steps": [None] * index + [_settings(selected)]}}
    references = {step["id"]: step for step in steps}
    linked = []
    context = {}
    pending = list(_links(selected))
    if kind in {"baseline", "trend_axis"}:
        pending += [("step", item["id"]) for item in steps if item.get("confirmation") == kind
                    and item["inputs"]["target_step_id"] == step["id"]]
        selected_runs = step["inputs"]["runs"]
        if pending:
            view["comparison_runs"] = _settings(selected_runs)
            pending.extend(_links(selected_runs))
    if kind == "operation":
        uses = [{"step_id": item["id"], "field": condition["field"], "operator": condition["operator"]}
                for item in steps if item.get("tool") == "reverse_search"
                for condition in item["inputs"]["constraints"] if ("step", step["id"]) in _links(condition)]
        if uses:
            view["uses"] = uses
    visited = {("step", step["id"])}
    for ref in pending:
        if ref in visited:
            continue
        visited.add(ref)
        namespace, name = ref
        if namespace == "step":
            source = _tool_view(references[name])
            linked.append(source)
            pending.extend(_links(source))
        elif name in payload["confirmed_context"]:
            context[name] = payload["confirmed_context"][name]
    if linked:
        view["referenced_steps"] = linked
    if context:
        view["confirmed_context"] = context
    return view


def project_focused_check(state: str, name: str, question: dict, *, flash: bool = False) -> tuple[str, dict]:
    payload = json.loads(state)
    text = question["instructions"]
    spec, = [item for item in payload["check_specs"] if item["name"] == name]
    if not text.startswith(_COMMON_EN) or not isinstance(payload[OMISSION_QUESTION], str):
        raise ValueError("LOCAL_D1_REQUEST_INVALID")
    focused = None
    if spec["kind"] == "filter" and not payload["input_history"]:
        try:
            index, step, operands = _filter_operands(payload["plan"], spec)
            focused = _compact_filter(step["id"], index, operands, spec)
        except ValueError:
            pass
    if focused is None:
        focused = _focused_plan(payload, spec)
    instructions = focused_plan_instructions(spec, focused)
    if flash:
        focused, instructions = flash_check_input(
            payload, spec["kind"], focused, instructions, payload[OMISSION_QUESTION])
    return json.dumps(focused, ensure_ascii=False, allow_nan=False, separators=(",", ":")), {
        **question, "instructions": instructions}


def project_plan_view(state: str, name: str, question: dict) -> tuple[str, dict]:
    """Prepare the check-specific view on validated, compact English plan requests."""
    text = question["instructions"]
    if not text.startswith(_COMMON_EN):
        return state, question
    payload = json.loads(state)
    if any(key in payload for key in ("execution_view", "plan_digest", "input_digest")):
        return state, question
    try:
        spec, = [item for item in payload["check_specs"] if item["name"] == name]
        text = _instructions(payload, spec, text)
    except (KeyError, TypeError, ValueError):
        return state, question
    if spec["kind"] == "filter":
        try:
            state = _excerpt(payload, spec)
        except (KeyError, TypeError, ValueError, IndexError):
            pass
        else:
            text = text.replace("source.quote", "citation.quote")
    return state, {**question, "instructions": text}
