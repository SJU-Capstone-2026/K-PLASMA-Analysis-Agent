"""Machine-checkable slot and dispatch assessment, not a scientific truth judge."""

from dataclasses import asdict

from kplasma_agent.tools import TOOL_MODELS
from kplasma_agent.domain import DomainError, validate_grounding
from kplasma_agent.metric_registry import CONDITION_KEYS, NumericError, normalize_value

_MISSING = object()


def _get(value, path):
    for component in path.split("."):
        if not isinstance(value, dict) or component not in value:
            return _MISSING
        value = value[component]
    return value


def _subset(expected, actual, path="inputs"):
    checks = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [(path, False)]
        for key, value in expected.items():
            checks.extend(_subset(value, actual.get(key, _MISSING), f"{path}.{key}"))
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [(path + ".length", False)]
        if path.endswith(".constraints"):
            remaining = list(actual)
            for index, item in enumerate(expected):
                found = next(
                    (i for i, other in enumerate(remaining) if all(ok for _, ok in _subset(item, other))),
                    None,
                )
                checks.append((f"{path}.{index}", found is not None))
                if found is not None:
                    remaining.pop(found)
        else:
            for index, item in enumerate(expected):
                checks.extend(_subset(item, actual[index], f"{path}.{index}"))
    else:
        checks.append((path, actual == expected))
    return checks


def _clarification_needed(value, context, case=None):
    if value.get("unresolved"):
        return True
    operations = value["operations"]
    if len(operations) != 1:
        return True
    kind, inputs = operations[0]["kind"], operations[0]["inputs"]
    try:
        for metric, quantity in inputs.get("conditions", {}).items():
            if quantity:
                if not quantity.get("unit"):
                    return True
                normalize_value(metric, quantity["value"], quantity.get("unit"))
        for rule in [*inputs.get("constraints", []), *inputs.get("goals", [])]:
            if any(rule.get(key) is not None for key in ("value", "min", "max")) and not rule.get("unit"):
                return True
            normalize_value(rule["metric"], 0, rule.get("unit"))
    except NumericError:
        return True
    if inputs.get("context_rules"):
        rules = inputs["context_rules"]
        allowed = (
            {"selected_run_conditions"}
            if kind == "forward_lookup"
            else {"energy_slightly_higher", "flux_maintained_and_width_lower"}
            if kind == "reverse_search"
            else set()
        )
        if any(rule not in allowed for rule in rules) or len(set(rules)) != len(rules):
            return True
        return not (context.get("reference_run") or context.get("selected_run"))
    if kind == "forward_lookup":
        return any(not inputs.get("conditions", {}).get(key) for key in CONDITION_KEYS)
    if kind == "reverse_search":
        return not (inputs.get("constraints") or inputs.get("goals"))
    if kind == "compare_runs":
        refs = case.references if case is not None else []
        requested = inputs.get("ref_keys")
        return len([r for r in refs if requested is None or r["key"] in requested]) < 2
    return False


def judge(case, raw):
    checks = []
    try:
        name = raw["name"]
        inputs = TOOL_MODELS[name].model_validate(raw["arguments"]).model_dump(exclude_none=True)
        if not raw.get("call_id"):
            raise ValueError("Missing call id")
        value = {"status": "resolved", "operations": [{"kind": name, "inputs": inputs}]}
    except (ValueError, TypeError, KeyError):
        return {
            "passed": False,
            "criticalWrongDispatch": False,
            "checksPassed": 0,
            "checksTotal": 1,
            "failures": ["SCHEMA_INVALID"],
            "groundingError": None,
        }
    grounding_error = None
    for operation in value["operations"]:
        if operation["kind"] not in ("forward_lookup", "reverse_search"):
            continue
        try:
            validate_grounding(operation, case.question, case.input_history, case.prior_interpretation)
        except DomainError as error:
            grounding_error = error.code
            break
    needs_clarification = (
        _clarification_needed(value, case.context_available, case) or grounding_error is not None
    )
    if case.unsupported:
        checks.append(("unsupported", value["status"] == "unsupported"))
    else:
        checks.append(("supported", value["status"] != "unsupported"))
        operations = value["operations"]
        matching = [operation for operation in operations if operation["kind"] == case.kind]
        # Ambiguous questions may explicitly ask for input without proposing a tool.
        empty_clarification = (
            case.clarification and not operations and needs_clarification and not case.expected_inputs
        )
        checks.append(("kind", len(matching) == 1 or empty_clarification))
        if matching:
            inputs = matching[0]["inputs"]
            checks.extend(_subset(case.expected_inputs, inputs))
            for path in case.absent_slots:
                checks.append(("absent." + path, _get(inputs, path) in (_MISSING, None)))
        checks.append(("clarification", needs_clarification == case.clarification))
        # A clarification can safely withhold an ungrounded proposal; normal cases must execute safely.
        checks.append(("grounding", grounding_error is None or (case.clarification and needs_clarification)))
    passed = all(ok for _, ok in checks)
    could_dispatch = value["status"] == "resolved" and not needs_clarification and grounding_error is None
    return {
        "passed": passed,
        "criticalWrongDispatch": not passed and could_dispatch,
        "checksPassed": sum(ok for _, ok in checks),
        "checksTotal": len(checks),
        "failures": [name for name, ok in checks if not ok],
        "groundingError": grounding_error,
    }


def case_payload(case):
    context = {
        "reference_run": False,
        "selected_run": False,
        "comparison_pair": False,
        **case.context_available,
    }
    pending = None
    if case.prior_interpretation and case.input_history:
        operations = case.prior_interpretation.get("operations", [])
        if len(operations) == 1 and operations[0]["kind"] == "forward_lookup":
            missing = [
                key for key in CONDITION_KEYS if key not in operations[0]["inputs"].get("conditions", {})
            ]
            pending = {
                "reason": "MISSING_CONDITIONS",
                "fields": missing,
                "message": ", ".join(missing) + " 조건을 알려 주세요.",
            }
    return {
        "explicitReferences": {"entries": case.references, "baselineKey": None},
        "question": case.question,
        "input_history": case.input_history,
        "prior_interpretation": case.prior_interpretation,
        "context_available": context,
        "pending_question": pending,
        "latest_reply": case.input_history[-1] if case.input_history else None,
    }


def public_case(case):
    """Synthetic fixture metadata is serializable, unlike API credentials."""
    return asdict(case)
