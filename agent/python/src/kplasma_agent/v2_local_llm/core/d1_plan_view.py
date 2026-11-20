"""Prepare the per-check d1 view without changing the executable plan."""

import json

from .d1_input import _COMMON_EN

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


def _excerpt(payload: dict, spec: dict) -> str:
    plan = payload["plan"]
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


def project_plan_view(state: str, name: str, question: dict) -> tuple[str, dict]:
    """Use the v2.5 view on already validated, compact English plan requests."""
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
