"""Check model-proposed scalar slots against user text or accepted explicit input.

This gate never constructs an operation or repairs a value. It recognizes only
common explicit numeric clauses; an unbound proposal needs clarification. The
model remains the interpreter and the numerical engine remains the executor.
"""

import math
import re
from decimal import Decimal

from ..metric_registry import UNITS, NumericError, normalize_value
from .common import DomainError, inputs_dict

_NUMBER = r"[-+]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?"
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])" + _NUMBER)
_UNIT = r"(?:10¹⁸\s*m⁻²\s*s⁻¹|10\^18\s*m\^-2\s*s\^-1|m⁻²\s*s⁻¹|m\^-2\s*s\^-1|m-2s-1|mTorr|Torr|kPa|Pa|keV|eV|kW|W|watts?|[가-힣]*와트)"
_UNIT_RE = re.compile(r"(?<![A-Za-z])" + _UNIT + r"(?![A-Za-z])", re.IGNORECASE)
_ALIASES = {
    "pressure": r"pressure|압력",
    "sourcePower": r"source\s*power|source|소스\s*(?:전력|파워)?",
    "biasPower": r"bias\s*power|bias|바이어스\s*(?:전력|파워)?",
    "meanIonEnergy": r"mean\s*ion\s*energy|ion\s*energy|energy|평균\s*이온\s*에너지|이온\s*에너지|에너지",
    "ionFlux": r"ion\s*flux|flux|이온\s*(?:플럭스|플럿스)|플럭스|플럿스",
    "iedWidth": r"ied\s*(?:width|폭)|width|폭",
}


def _decimal(value):
    return Decimal(str(value).replace(",", ""))


def _anchors(text):
    matches = []
    for metric, aliases in _ALIASES.items():
        for found in re.finditer(r"(?<![A-Za-z])(?:" + aliases + r")(?![A-Za-z])", text, re.IGNORECASE):
            matches.append((found.start(), found.end(), metric))
    accepted = []
    for start, end, metric in sorted(matches, key=lambda m: (m[0], -(m[1] - m[0]))):
        if not accepted or start >= accepted[-1][1]:
            accepted.append((start, end, metric))
    return accepted


def _without_ids(text):
    # Run-10 / RUN10 / Run 10 / Run A12 are references, never process numbers.
    return re.sub(r"(?i)(?<![A-Za-z])(?:run|런)\s*[-_:]?\s*[A-Za-z0-9][A-Za-z0-9_.:-]*", " ", text)


def _unit_text(segment):
    match = _UNIT_RE.search(segment)
    return match.group() if match else None


def _unit_signature(metric, unit):
    if unit is None:
        unit = UNITS[metric]
    canonical = {"mtorr": "mTorr", "torr": "Torr", "ev": "eV", "w": "W"}.get(unit.casefold(), unit)
    canonical = re.sub(r"\s+", " ", canonical).strip()
    try:
        return normalize_value(metric, 1, canonical)
    except NumericError:
        return canonical


def _operator(segment):
    patterns = [
        ("lte", r"이하|≤|<=|at\s+most|no\s+more\s+than|less\s+than\s+or\s+equal"),
        ("gte", r"이상|≥|>=|at\s+least|no\s+less\s+than|greater\s+than\s+or\s+equal"),
        ("lt", r"미만|보다\s*(?:작|낮)|<|\bunder\b|\bbelow\b|less\s+than"),
        ("gt", r"초과|보다\s*(?:크|높)|>|\bover\b|\babove\b|greater\s+than|higher\s+than"),
    ]
    for operator, pattern in patterns:
        if re.search(pattern, segment, re.IGNORECASE):
            return operator
    return "eq"


def _allows_outside_range(segment):
    permissions = list(
        re.finditer(
            r"범위\s*(?:밖|외)(?:도|를|을)?\s*(?:허용|포함)"
            r"|\ballow\b.{0,30}\boutside\b.{0,20}\brange\b",
            segment,
            re.IGNORECASE,
        )
    )
    for permission in permissions:
        before = segment[: permission.start()]
        after = segment[permission.end() :]
        if re.search(r"(?:\bnot|\bnever|\bno|\bdon['’]t|\bcannot|\bcan't)\s*$", before, re.IGNORECASE):
            return False
        if re.match(r"\s*(?:안|못|하지|하지\s*마|하지\s*않)", after):
            return False
    return bool(permissions)


def _evidence(segment, *, allow_prefix=False):
    correction = re.search(r"말고|아니(?:고|라)|대신|\binstead\b|\brather\b", segment, re.IGNORECASE)
    if correction and _NUMBER_RE.search(segment[correction.end() :]):
        segment = segment[correction.end() :]
    # Unit exponents are not additional numeric endpoints.
    numeric_text = _UNIT_RE.sub(" ", segment)
    # 30-40 uses a range separator; the sign in 1e-3 remains a sign.
    numeric_text = re.sub(r"(?<=\d)\s*-\s*(?=\d)", " ~ ", numeric_text)
    found = list(_NUMBER_RE.finditer(numeric_text))
    if not found:
        return None
    values = [_decimal(match.group()) for match in found]
    # The prototype's bounded search filters first, even for '가깝게'. Only
    # explicit permission to include out-of-range values makes this a soft goal.
    soft = _allows_outside_range(segment)
    interval = len(values) == 2 and bool(
        re.search(
            r"[~〜∼–—]|(?<=\d)\s*-\s*-?\d|\bbetween\b|\bto\b|부터|에서|범위|range", segment, re.IGNORECASE
        )
    )
    if interval:
        return {"numbers": values, "operator": "between", "unit": _unit_text(segment), "soft": soft}
    if len(values) > 1:
        if re.search(r"말고|아니(?:고|라|,|\s)|대신|instead|rather", segment, re.IGNORECASE):
            # Explicit correction: only the final value is acceptable.
            values = [values[-1]]
        else:
            return None
    return {
        "numbers": values,
        "operator": "eq" if allow_prefix else _operator(segment),
        "unit": _unit_text(segment),
        "soft": soft,
    }


def _text_evidence(text):
    text = _without_ids(text)
    anchors = _anchors(text)
    evidence = {}
    for index, (start, end, metric) in enumerate(anchors):
        following = text[end : anchors[index + 1][0] if index + 1 < len(anchors) else len(text)]
        preceding = text[:start]
        prefix = re.search(
            r"(?P<number>" + _NUMBER + r")\s*(?P<unit>" + _UNIT + r")?\s*(?:의\s*)?$",
            preceding,
            re.IGNORECASE,
        )
        direct = re.match(r"\s*(?:(?:은|는|이|가|을|를|:|=)\s*)*(?:" + _NUMBER + r")", following)
        if prefix and not direct:
            record = _evidence(prefix.group(), allow_prefix=True)
        else:
            record = _evidence(following)
        if record is not None:
            evidence[metric] = record
        elif _NUMBER_RE.search(_UNIT_RE.sub(" ", following)):
            evidence[metric] = {"invalid": True}
    return evidence


def _finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _claims(operation, *, ignore_invalid=False):
    inputs = operation.get("inputs", {})
    records = []
    conditions = inputs.get("conditions") or {}
    if not isinstance(conditions, dict):
        if not ignore_invalid:
            raise DomainError("UNGROUNDED_NUMBER", "conditions")
        conditions = {}
    for metric, scalar in conditions.items():
        if metric not in _ALIASES:
            if ignore_invalid:
                continue
            raise DomainError("UNGROUNDED_NUMBER", "conditions." + str(metric))
        if isinstance(scalar, dict) and "value" in scalar:
            if not _finite_number(scalar["value"]):
                if ignore_invalid:
                    continue
                raise DomainError("UNGROUNDED_NUMBER", f"conditions.{metric}")
            records.append(
                {
                    "key": ("conditions", metric),
                    "metric": metric,
                    "numbers": [_decimal(scalar["value"])],
                    "operator": "eq",
                    "unit": scalar.get("unit"),
                    "soft": False,
                }
            )
    for section in ("constraints", "goals"):
        items = inputs.get(section, []) or []
        if not isinstance(items, list):
            if ignore_invalid:
                continue
            raise DomainError("UNGROUNDED_NUMBER", section)
        for item in items:
            if not isinstance(item, dict) or item.get("metric") not in _ALIASES:
                if ignore_invalid:
                    continue
                raise DomainError("UNGROUNDED_NUMBER", section)
            values = [item[key] for key in ("value", "min", "max") if item.get(key) is not None]
            if not all(_finite_number(value) for value in values):
                if ignore_invalid:
                    continue
                raise DomainError("UNGROUNDED_NUMBER", section + "." + item["metric"])
            numbers = [
                _decimal(item[key])
                for key in ("value", "min", "max")
                if key in item and item[key] is not None
            ]
            if not numbers:
                continue
            operator = item.get("operator", "between")
            records.append(
                {
                    "key": (section, item["metric"]),
                    "metric": item["metric"],
                    "numbers": numbers,
                    "operator": operator,
                    "unit": item.get("unit"),
                    "soft": section == "goals",
                }
            )
    return records


def _same(claim, evidence, *, ignore_operator=False):
    if evidence.get("invalid"):
        return False
    return (
        claim["numbers"] == evidence["numbers"]
        and _unit_signature(claim["metric"], claim["unit"])
        == _unit_signature(claim["metric"], evidence["unit"])
        and (
            ignore_operator
            or (claim["operator"] == evidence["operator"] and claim["soft"] == evidence["soft"])
        )
    )


def _prior_operation(operation, prior):
    if not prior:
        return None
    prior = inputs_dict(prior)
    if prior.get("status") == "unsupported" or any(
        "UNGROUNDED" in issue.get("reason", "") for issue in prior.get("unresolved", [])
    ):
        return None
    candidates = prior.get("operations", [prior] if "kind" in prior else [])
    matches = [item for item in candidates if item.get("kind") == operation["kind"]]
    return matches[0] if len(matches) == 1 else None


def _reference_grounding(operation, question, input_history, prior):
    text = "\n".join(
        [question, *(entry.get("text", "") for entry in input_history if isinstance(entry.get("text"), str))]
    )
    explicit_baselines = []
    for selector in operation.get("inputs", {}).values():
        if not isinstance(selector, dict) or selector.get("kind") != "run_id":
            continue
        value = selector["run_id"]
        role_pattern = (
            re.escape(value)
            + r"\s*(?:을|를)?\s*(?:기준|as\s+(?:the\s+)?(?:baseline|reference))"
            + r"|(?:baseline\s*[:=]?\s*|기준\s*[:=]\s*)"
            + re.escape(value)
        )
        explicit_baselines.extend(
            (match.start(), value) for match in re.finditer(role_pattern, text, re.IGNORECASE)
        )
    if explicit_baselines:
        named_baseline = max(explicit_baselines)[1]
        actual_baseline = operation.get("inputs", {}).get("baseline", {})
        if actual_baseline.get("kind") == "run_id" and actual_baseline.get("run_id") != named_baseline:
            raise DomainError("UNGROUNDED_RUN_REFERENCE", "baseline role contradicts explicit user role")
    for role in ("baseline", "target"):
        selector = operation.get("inputs", {}).get(role)
        if not isinstance(selector, dict) or selector.get("kind") != "run_id":
            continue
        previous = (prior or {}).get("inputs", {}).get(role)
        explicit = next(
            (item[role] for item in reversed(input_history) if isinstance(item.get(role), dict)), None
        )
        for field in ("run_id", "run_version_id"):
            if not selector.get(field):
                continue
            value = selector[field]
            if any(
                isinstance(source, dict) and source.get(field) == value for source in (previous, explicit)
            ):
                continue
            if not re.search(r"(?<![A-Za-z0-9_-])" + re.escape(value) + r"(?![A-Za-z0-9_-])", text):
                raise DomainError("UNGROUNDED_RUN_REFERENCE", f"{role}.{field}")


def _goal_grounding(operation, question, history):
    directions = {}
    priority = None
    for text in [question, *(item.get("text", "") for item in history)]:
        if not isinstance(text, str):
            continue
        anchors = _anchors(text)
        if re.search(r"최우선|우선하고|우선하되|동률|\bfirst\b.{0,80}\bthen\b", text, re.IGNORECASE):
            # Validate explicit sequential priority; never reorder model output.
            priority = list(dict.fromkeys(metric for _, _, metric in anchors))
        for index, (_, end, metric) in enumerate(anchors):
            segment = text[end : anchors[index + 1][0] if index + 1 < len(anchors) else len(text)]
            low = bool(
                re.search(
                    r"최소|가장\s*(?:낮|좁)|\bminimi[sz]e\b|\blowest\b|\bnarrowest\b", segment, re.IGNORECASE
                )
            )
            high = bool(re.search(r"최대|가장\s*높|\bmaximi[sz]e\b|\bhighest\b", segment, re.IGNORECASE))
            if low != high:
                directions[metric] = "minimize" if low else "maximize"
    for goal in operation.get("inputs", {}).get("goals", []):
        expected = directions.get(goal["metric"])
        if expected and goal["direction"] in ("minimize", "maximize") and goal["direction"] != expected:
            raise DomainError("UNGROUNDED_GOAL", goal["metric"])
    goals = [goal["metric"] for goal in operation.get("inputs", {}).get("goals", [])]
    if priority and len(set(goals)) > 1:
        expected = [metric for metric in priority if metric in goals]
        if len(expected) == len(goals) and expected != goals:
            raise DomainError("UNGROUNDED_GOAL_PRIORITY", "explicit priority differs from goal order")


def _comparison_intent_grounding(operation, question, history, prior):
    kind = operation["kind"]
    if kind not in ("compare_runs", "explain_change"):
        return
    text = question
    for item in history:
        reply = item.get("text", "")
        if isinstance(reply, str) and re.search(
            r"원인|이유|왜|해석|설명|수치|차이만|why|reason|explain|numerically", reply, re.IGNORECASE
        ):
            text = reply
    omitted = bool(
        re.search(
            r"(?:원인|이유|해석|설명).{0,20}(?:빼|제외|말고|하지\s*마)|(?:without|no)\s+(?:causal\s+)?(?:explanation|reason)",
            text,
            re.IGNORECASE,
        )
    )
    causal = bool(
        re.search(
            r"원인|이유|왜|해석|까닭|메커니즘|\bwhy\b|\breason\b|\bcause\b|\binterpret|\bmechanism",
            text,
            re.IGNORECASE,
        )
    )
    numeric_only = bool(
        re.search(r"수치|숫자|차이만|변화율|\bhow\s+much\b|\bnumerically\b", text, re.IGNORECASE)
    )
    general_explain = bool(re.search(r"설명|\bexplain", text, re.IGNORECASE)) and not numeric_only
    wants_reason = not omitted and (causal or general_explain)
    if kind == "compare_runs" and wants_reason:
        raise DomainError(
            "UNGROUNDED_OPERATION", "causal interpretation request cannot execute comparison only"
        )
    if kind == "explain_change" and not wants_reason:
        inherited = prior is not None and prior.get("kind") == kind and not numeric_only and not omitted
        if not inherited:
            raise DomainError(
                "UNGROUNDED_OPERATION", "numeric comparison cannot silently add causal interpretation"
            )


def validate_grounding(operation, question, input_history, prior_interpretation=None):
    """Return True or raise DomainError; never modify/repair a proposed operation.

    Prior input must be an already accepted interpretation. A rejected grounding
    result cannot become a trusted inherited slot on the next turn. Structured
    history entries bind only their explicitly provided fields.
    """
    operation = inputs_dict(operation)
    history = [item for item in (input_history or []) if isinstance(item, dict)]
    prior = _prior_operation(operation, prior_interpretation)
    _comparison_intent_grounding(operation, question, history, prior)
    _reference_grounding(operation, question, history, prior)
    _goal_grounding(operation, question, history)
    claims = _claims(operation)
    prior_claims = _claims(prior, ignore_invalid=True) if prior else []
    evidence = {claim["metric"]: claim for claim in prior_claims}
    evidence.update(_text_evidence(question))
    for entry in history:
        if isinstance(entry.get("text"), str):
            evidence.update(_text_evidence(entry["text"]))
        # Structured values are explicit user input at the corresponding field.
        for claim in _claims({"inputs": entry}, ignore_invalid=True):
            evidence[claim["metric"]] = claim
    if operation["kind"] in ("forward_lookup", "reverse_search"):
        proposed_metrics = {claim["metric"] for claim in claims}
        for metric, observed in evidence.items():
            if not observed.get("invalid") and metric not in proposed_metrics:
                raise DomainError("UNGROUNDED_OMISSION", metric)
    new_claims = [claim for claim in claims if not any(old["key"] == claim["key"] for old in prior_claims)]
    anonymous = None
    if prior and len(new_claims) == 1 and history:
        latest = history[-1].get("text", "")
        if isinstance(latest, str) and not _anchors(latest):
            anonymous = _evidence(_without_ids(latest))
    for claim in claims:
        observed = evidence.get(claim["metric"])
        if observed is not None:
            if _same(claim, observed):
                continue
            raise DomainError("UNGROUNDED_NUMBER", ".".join(claim["key"]))
        if any(old["key"] == claim["key"] and _same(claim, old) for old in prior_claims):
            continue
        if anonymous is not None and claim is new_claims[0] and _same(claim, anonymous):
            continue
        raise DomainError("UNGROUNDED_NUMBER", ".".join(claim["key"]))
    return True


def validate_comparison_metrics(inputs, question, history, previous_metrics):
    """Require an explicit metric request before changing a prior comparison scope."""
    inputs = inputs_dict(inputs)
    uses_comparison = any(
        isinstance(inputs.get(role), dict)
        and inputs[role].get("kind") in ("comparison_baseline", "comparison_target")
        for role in ("baseline", "target")
    )
    proposed = inputs.get("metrics")
    if not uses_comparison or not previous_metrics or proposed is None or proposed == previous_metrics:
        return True
    history = [entry for entry in (history or []) if isinstance(entry, dict)]
    if any(entry.get("metrics") == proposed for entry in history):
        return True
    text = "\n".join([question, *(entry["text"] for entry in history if isinstance(entry.get("text"), str))])
    if re.search(
        r"(?:모든|전체|전부)\s*(?:측정\s*)?지표|(?:all|every)\s+(?:output\s+)?metrics?", text, re.IGNORECASE
    ):
        return True
    mentioned = {metric for _, _, metric in _anchors(text)} & {"meanIonEnergy", "ionFlux", "iedWidth"}
    added = set(proposed) - set(previous_metrics)
    # A new named metric may supplement unchanged existing metrics. A narrower
    # replacement must itself be named; reordering needs every proposed name.
    if mentioned and ((added and added <= mentioned) or set(proposed) <= mentioned):
        return True
    raise DomainError(
        "UNGROUNDED_METRICS", "comparison metric scope changed without an explicit user request"
    )
