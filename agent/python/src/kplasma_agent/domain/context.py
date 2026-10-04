"""Narrow, version-pinned continuation policies, never a natural-language fallback.

The interpreter chooses a policy name; code independently checks its supported
phrase and computes every derived number from the caller's fixed Run snapshot.
Unknown continuations, incompatible explicit inputs and missing sources fail
closed so the decision layer can ask the user to clarify.
"""

import math
import re

from ..contracts import ForwardInputs, ReverseInputs
from ..metric_registry import CONDITION_KEYS, UNITS, is_finite, normalize_value
from .common import DomainError, inputs_dict, is_usable, run_ref, scalar

_SPAN = r"[^.!?;\n]{0,45}"
_ENERGY = r"(?:에너지|(?:mean\s+ion\s+|ion\s+)?energy)"
_FLUX = r"(?:플럭스|플러스|플럿스|(?:ion\s+)?flux)"
_WIDTH = r"(?:ied\s*(?:width|폭)?|폭|width)"


def _matches(pattern, text):
    return re.search(pattern, text, re.IGNORECASE) is not None


def _phrase_grounded(rule, question):
    # Conservative negation handling: do not reinterpret a refusal/contrast as a
    # positive policy request. Such mixed clauses are clarified by the caller.
    if _matches(
        r"(?:말고|말아|마라|마세요|않|아니|하지\s*마|지\s*마|\bnot\b|\bnever\b|\bdon['’]?t\b)", question
    ):
        return False
    if rule == "selected_run_conditions":
        explicit_run = _matches(
            r"(?:(?:이|해당|선택한|선택된)\s*run|선택한\s*런|(?:this|selected|that)\s+run)", question
        )
        lookup = _matches(
            r"(?:결과|조회|보여|확인|분포|\bresults?\b|\bshow\b|\blookup\b|\bdistribution\b)", question
        )
        return explicit_run and lookup
    if rule == "energy_slightly_higher":
        return any(
            _matches(pattern, question)
            for pattern in (
                _ENERGY + _SPAN + r"(?:조금|좀)" + _SPAN + r"(?:높|올)",
                r"(?:조금|좀)" + _SPAN + r"(?:높|올)" + _SPAN + _ENERGY,
                _ENERGY + _SPAN + r"(?:slightly|a\s+little|a\s+bit)" + _SPAN + r"(?:higher|increase|raise)",
                r"(?:slightly|a\s+little|a\s+bit)\s+higher" + _SPAN + _ENERGY,
                r"(?:increase|raise)" + _SPAN + _ENERGY + _SPAN + r"(?:slightly|a\s+little|a\s+bit)",
            )
        )
    if rule == "flux_maintained_and_width_lower":
        maintain = _matches(
            _FLUX + _SPAN + r"(?:유지|maintain|keep|preserve|unchanged)", question
        ) or _matches(r"(?:maintain|keep|preserve)" + _SPAN + _FLUX, question)
        lower_width = _matches(_WIDTH + _SPAN + r"(?:낮|좁|줄|lower|narrow|reduc)", question) or _matches(
            r"(?:lower|narrow|reduce)" + _SPAN + _WIDTH, question
        )
        return maintain and lower_width
    return False


def _required_scalar(run, metric):
    value, error = scalar(run, metric)
    if error:
        raise DomainError("CONTEXT_DATA_UNAVAILABLE", f"{metric}: {error}")
    return value


def _one_decimal_js(value):
    scaled = value * 10
    if not is_finite(scaled):
        raise DomainError("NUMERIC_OVERFLOW", "energy continuation policy")
    result = math.floor(scaled + 0.5) / 10
    return 0.0 if result == 0 else result


def _same_rule(left, right):
    if left.get("metric") != right["metric"] or left.get("operator") != right["operator"]:
        return False
    for field in ("value", "min", "max"):
        if (field in left) != (field in right):
            return False
        if field in left and normalize_value(left["metric"], left[field], left.get("unit")) != right[field]:
            return False
    return True


def _add_constraint(inputs, constraint):
    metric = constraint["metric"]
    for goal in inputs.get("goals", []):
        if goal["metric"] == metric:
            raise DomainError("CONTEXT_RULE_CONFLICT", f"explicit goal changes continuation policy: {metric}")
    constraints = inputs.setdefault("constraints", [])
    existing = [(index, rule) for index, rule in enumerate(constraints) if rule["metric"] == metric]
    if existing:
        if len(existing) != 1 or not _same_rule(existing[0][1], constraint):
            raise DomainError("CONTEXT_RULE_CONFLICT", f"explicit constraint: {metric}")
        index = existing[0][0]
    else:
        index = len(constraints)
        constraints.append(constraint)
    return [f"constraints.{index}.{field}" for field in ("value", "min", "max") if field in constraint]


def apply_context_rules(kind, inputs, question, selected_run=None):
    """Return `{inputs, appliedRules, usedRunRefs, interpretationNotes}`.

    `selected_run` is the caller's already-authorized, version-pinned context
    snapshot. This function never resolves an ID, chooses another Run, changes
    a caller object, calls a model, or fills unrelated missing numeric slots.
    """
    model = {"forward_lookup": ForwardInputs, "reverse_search": ReverseInputs}.get(kind)
    if model is None:
        raise DomainError("UNSUPPORTED_CONTEXT_OPERATION", str(kind))
    raw = inputs_dict(inputs)
    allowed = (
        {"selected_run_conditions"}
        if kind == "forward_lookup"
        else {"energy_slightly_higher", "flux_maintained_and_width_lower"}
    )
    if any(not isinstance(rule, str) or rule not in allowed for rule in raw.get("context_rules", [])):
        raise DomainError("CONTEXT_RULE_CONFLICT", "wrong operation policy")
    resolved = model.model_validate(raw).model_dump(exclude_none=True)
    rules = resolved.get("context_rules", [])
    response = {"inputs": resolved, "appliedRules": [], "usedRunRefs": [], "interpretationNotes": []}
    if not rules:
        return response
    allowed = (
        {"selected_run_conditions"}
        if kind == "forward_lookup"
        else {"energy_slightly_higher", "flux_maintained_and_width_lower"}
    )
    if len(set(rules)) != len(rules) or any(rule not in allowed for rule in rules):
        raise DomainError("CONTEXT_RULE_CONFLICT", "duplicate or wrong operation policy")
    if not isinstance(question, str) or any(not _phrase_grounded(rule, question) for rule in rules):
        raise DomainError("CONTEXT_RULE_NOT_GROUNDED")
    if selected_run is None:
        raise DomainError("CONTEXT_REFERENCE_REQUIRED")
    ref = run_ref(selected_run)
    if not is_usable(selected_run):
        raise DomainError("DATA_NOT_COMPARABLE")
    for rule in rules:
        generated_fields = []
        if rule == "selected_run_conditions":
            conditions = resolved.setdefault("conditions", {})
            for metric in CONDITION_KEYS:
                value = _required_scalar(selected_run, metric)
                if metric in conditions:
                    explicit = conditions[metric]
                    if normalize_value(metric, explicit["value"], explicit.get("unit")) != value:
                        raise DomainError("CONTEXT_RULE_CONFLICT", f"explicit condition: {metric}")
                else:
                    conditions[metric] = {"value": value, "unit": UNITS[metric]}
                    generated_fields.append(f"conditions.{metric}.value")
            note = "선택한 Run의 고정된 버전에서 압력·소스·바이어스 조건을 사용했습니다."
        elif rule == "energy_slightly_higher":
            energy = _required_scalar(selected_run, "meanIonEnergy")
            lower, upper = _one_decimal_js(energy + 5), _one_decimal_js(energy + 20)
            generated_fields = _add_constraint(
                resolved,
                {"metric": "meanIonEnergy", "operator": "between", "min": lower, "max": upper, "unit": "eV"},
            )
            note = (
                f"‘에너지를 조금 더 높게’를 기준 Run 대비 +5~20 eV ({lower:g}–{upper:g} eV)로 해석했습니다."
            )
        else:
            flux = _required_scalar(selected_run, "ionFlux")
            width = _required_scalar(selected_run, "iedWidth")
            low, high = flux * 0.95, flux * 1.05
            if not is_finite(low) or not is_finite(high):
                raise DomainError("NUMERIC_OVERFLOW", "flux continuation policy")
            if low > high:
                raise DomainError(
                    "CONTEXT_DATA_UNAVAILABLE", "negative baseline flux cannot form a ±5% interval"
                )
            generated_fields.extend(
                _add_constraint(
                    resolved,
                    {
                        "metric": "ionFlux",
                        "operator": "between",
                        "min": low,
                        "max": high,
                        "unit": UNITS["ionFlux"],
                    },
                )
            )
            generated_fields.extend(
                _add_constraint(
                    resolved, {"metric": "iedWidth", "operator": "lte", "value": width, "unit": "eV"}
                )
            )
            note = "‘플럭스 유지’를 기준 Run의 ±5%, ‘IED 폭을 낮게’를 기준값 이하로 해석했습니다."
        response["appliedRules"].append(
            {"name": rule, "sourceRunRef": dict(ref), "generatedFields": generated_fields}
        )
        response["interpretationNotes"].append(note)
    resolved["context_rules"] = []
    # Validate the generated shape too; all model inputs are already validated.
    response["inputs"] = model.model_validate(resolved).model_dump(exclude_none=True)
    response["usedRunRefs"] = [ref]
    return response
