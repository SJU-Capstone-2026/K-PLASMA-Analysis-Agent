"""V3 cost-regex-2 rules; retrieval similarity never changes exclusion policy.

Source: domain/decision_records.py at c10c79d0747cf04d5df163e698fd77917ccff4ca.
The V1/V2 policy is preserved at its original source. V3 classifies cost clauses
before counting immutable records, so a contrast about record keeping does not
erase an otherwise explicit cost rejection.
Notes stay local and are not interpreted by a model.
"""

import math
import re


class PolicyError(ValueError):
    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message or code)


RECORD_POLICY_VERSION = "cost-regex-2"

# JavaScript String.prototype.trim() whitespace, including BOM but excluding U+001C.
_JS_WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def _js(pattern, flags=0):
    pattern = pattern.replace("<D>", "[^\n\r\u2028\u2029]").replace("<S>", f"[{_JS_WHITESPACE}]")
    return re.compile(pattern, flags | re.ASCII)


_NO_COST = _js(r"(비용|원가|가격)<D>{0,15}(없|않|아니|아님|무관|괜찮|적정)")
_TRANSITION = _js(r"하지만|그러나|다만|반면|지만|으나")
_CLAUSE_BOUNDARY = _js(r"[.!;\n\r\u2028\u2029]|하지만|그러나|다만|반면|지만|으나")
_COST = _js(r"(비용|원가|가격)<D>{0,15}(높|비싸|초과|부담|때문|문제|과다)|예산<D>{0,8}초과")
_UNCERTAIN = _js(r"불명|불확실|미정|미확정|추정|모르|\?|"
                 r"확인<D>{0,8}(필요|중|못|대기)|(?:답변|자료)<D>{0,8}(기다|대기)|"
                 r"(?:해결|해소)<D>{0,8}(가능|수<D>{0,3}있|예정|계획)")
_OTHER = _js(r"(성능|균일도|에너지|플럭스)<D>{0,12}(때문|미달|문제|부족)")
_OTHER_TOPIC = _js(r"성능|균일도|에너지|플럭스|담당자|작성자")
_COST_TOPIC = _js(r"비용|원가|가격|예산")
_CURRENT = _js(r"현재|이번|지금|이제|최종|후속")
_RESOLVED = _js(r"(비용|원가|가격|예산)<D>{0,15}(해결|해소)")
_UNRESOLVED = _js(r"(비용|원가|가격|예산)<D>{0,15}(해결|해소)<D>{0,8}(않|못|안\s*됐|안\s*되)")
_REJECTION_DENIED = _js(r"반려<D>{0,8}(아니|않|못)|반려하지|거절하지")
_COST_CAUSE = _js(r"(비용|원가|가격|예산)<D>{0,30}(때문|사유|원인|반려|거절|탈락)")
_INHERITED_STATE = _js(
    r"^(?:(?:현재|이번|지금|이제|최종|후속)(?:검토)?(?:에서는|에는|은|는|에)?\s*)?"
    r"(?:(?:그|이)\s*(?:문제|사유|이유)(?:은|는|이|가)?\s*)?"
    r"(?:해결|해소|적정|괜찮|무관|불명|불확실|미정|미확정|추정|모르|확인|높|비싸|초과|부담|과다|반려|거절)|"
    r"^그\s*때문"
)
_RUN_ID = _js(r"RUN-[A-Z0-9-]+")
_RECORD_REQUEST = _js(r"(반려|과거 기록|이전<D>*이유)")
_EXCLUDE = _js(r"제외|빼")
_THRESHOLD = _js(r"([+-]?[0-9]+(?:\.[0-9]+)?)<S>*건<S>*이상")
_MANY = _js(r"많")
_COST_TERM = _js(r"(비용|원가|가격)")
_NUMERIC_CONDITION = _js(
    r"(?:flux|플럭스|에너지|energy|압력|pressure|source(?:<S>*power)?|소스(?:<S>*전력)?|bias(?:<S>*power)?|바이어스)"
    r"<S>*(?:가|는|이)?<S>*[0-9]",
    re.IGNORECASE,
)
_CANDIDATE_GROUP = _js(r"(?:이<S>*)?후보(?:들|군)")


def _text(value):
    return value if isinstance(value, str) else ""


def _first(*values):
    # Match the preserved port's JavaScript a || b behavior.
    for value in values:
        if value is not None and value != "" and value is not False and value != 0:
            return value
    return values[-1]


def _cost_match(pattern, text):
    # A later predicate about performance or an administrator is not a cost
    # predicate merely because a cost word occurs earlier in the same clause.
    return any(not _OTHER_TOPIC.search(match.group()) for match in pattern.finditer(text))


def _cost_state(clause):
    if _UNCERTAIN.search(clause):
        return "UNCLEAR"
    if _cost_match(_UNRESOLVED, clause):
        return "COST"
    if _REJECTION_DENIED.search(clause):
        return "NO_COST" if _cost_match(_NO_COST, clause) else "UNCLEAR"
    if _cost_match(_NO_COST, clause) or _cost_match(_RESOLVED, clause):
        return "NO_COST"
    if _cost_match(_COST, clause):
        return "COST"
    return None


def classify(note):
    text = _text(note).strip(_JS_WHITESPACE)
    if not text:
        return "MISSING"
    observations: list[tuple[str, bool, bool]] = []
    competing_clause = False
    competing_reason = False
    for clause in (part.strip(_JS_WHITESPACE) for part in _CLAUSE_BOUNDARY.split(text)):
        if not clause:
            continue
        has_cost = bool(_COST_TOPIC.search(clause))
        inherited = bool(observations and not has_cost and not _OTHER_TOPIC.search(clause)
                         and _INHERITED_STATE.search(clause))
        if not has_cost and not inherited:
            competing_clause |= bool(_OTHER_TOPIC.search(clause))
            competing_reason |= bool(_OTHER.search(clause))
            continue
        # Only an unambiguous continuation may borrow the previous cost subject.
        analysis = clause if has_cost else "비용 " + _CURRENT.sub("", clause)
        state = _cost_state(analysis)
        if state is not None:
            observations.append((state, bool(_CURRENT.search(clause)),
                                 bool(_cost_match(_COST_CAUSE, analysis))))
    if observations:
        states = {state for state, _, _ in observations}
        if len(states) > 1:
            current = [state for state, is_current, _ in observations if is_current]
            # A clearly named current state can supersede a historical one;
            # contradictory states without that ordering remain uncertain.
            if current and len(set(current)) == 1 and observations[-1][1]:
                return current[-1]
            return "UNCLEAR"
        state = observations[0][0]
        if (state == "COST" and competing_clause and (_TRANSITION.search(text) or competing_reason)
                and not any(explicit for _, _, explicit in observations)):
            return "UNCLEAR"
        return state
    return "OTHER" if _OTHER.search(text) else "UNCLEAR"


def evidence(records, run_id):
    entries = []
    for record in records:
        if record.get("version") == 2:
            candidates = record.get("candidates") or []
        else:
            candidates = [{
                "runId": record.get("targetRunId"),
                "runVersionId": (record.get("targetRunRef") or {}).get("runVersionId"),
                "decision": record.get("decision"), "note": record.get("comment"),
            }]
        candidate = next((item for item in candidates if item.get("runId") == run_id), None)
        if candidate is None:
            continue
        # A shared comment belongs to a Run only when there is exactly one candidate.
        note = _text(_first(candidate.get("note"), record.get("overallComment") if len(candidates) == 1 else "", ""))
        foreign_run = any(found != run_id for found in _RUN_ID.findall(note))
        snapshot = next((item for item in record.get("runSnapshots") or [] if item.get("runId") == run_id), None)
        entries.append({
            "recordId": _first(record.get("reviewId"), record.get("id")),
            "runId": run_id, "runVersionId": candidate.get("runVersionId"),
            "decision": candidate.get("decision"), "note": note,
            "sharedComment": _text(_first(record.get("overallComment"), "")),
            "reason": "UNCLEAR" if foreign_run else classify(note),
            "createdAt": record.get("createdAt"),
            "question": _text(_first(record.get("question"), record.get("queryText"), "")),
            "conditions": _first(candidate.get("conditions"), (snapshot or {}).get("conditions"), {}),
            "demo": bool(record.get("isDemo")),
        })
    return entries


def summarize(records, run_id):
    entries = evidence(records, run_id)
    count = len({e["recordId"] for e in entries if e["decision"] == "REJECT" and e["reason"] == "COST"})
    if not entries:
        status = "관련 기록 없음"
    elif count:
        status = f"비용 반려 {count}건"
    elif any(e["reason"] == "NO_COST" for e in entries):
        status = "비용 문제 없음 기록"
    elif any(e["decision"] == "REJECT" and e["reason"] == "MISSING" for e in entries):
        status = "반려 사유 미기록"
    elif any(e["reason"] == "UNCLEAR" for e in entries):
        status = "사유 확인 필요"
    else:
        status = "비용 반려 근거 없음"
    decisions = {e["decision"] for e in entries}
    return {"runId": run_id, "count": count, "status": status, "entries": entries,
            "mixed": "ADOPT" in decisions and "REJECT" in decisions}


def valid_threshold(threshold):
    if isinstance(threshold, bool):
        return False
    if isinstance(threshold, int):
        return threshold >= 1
    return isinstance(threshold, float) and math.isfinite(threshold) and threshold.is_integer() and threshold >= 1


def filter_runs(records, run_ids, threshold=1):
    if threshold != math.inf and not valid_threshold(threshold):
        raise PolicyError("INVALID_THRESHOLD", "제외 기준은 1 이상의 정수여야 합니다.")
    summaries = [summarize(records, run_id) for run_id in dict.fromkeys(run_ids)]
    return {"remaining": [s for s in summaries if s["count"] < threshold],
            "excluded": [s for s in summaries if s["count"] >= threshold]}


def parse_request(text):
    text = _text(text)
    if not _RECORD_REQUEST.search(text):
        return None
    exclude = bool(_EXCLUDE.search(text))
    number = _THRESHOLD.search(text)
    threshold: int | float | None
    if number:
        value = float(number.group(1))
        threshold = int(value) if value.is_integer() else value
    else:
        threshold = None if _MANY.search(text) and exclude else 1
    return {"exclude": exclude, "threshold": threshold}


def mentions_cost(text):
    return bool(_COST_TERM.search(_text(text)))


def has_numeric_condition(text):
    return bool(_NUMERIC_CONDITION.search(_text(text)))


def mentions_candidate_group(text):
    return bool(_CANDIDATE_GROUP.search(_text(text)))
