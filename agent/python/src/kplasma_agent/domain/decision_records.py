"""Deterministic reuse of saved decisions, ported from prototype v12.3.1 record-reuse.js.

Only explicit cost rejections count. Notes are classified locally and never interpreted by a model.
"""

import math
import re

from .common import DomainError

RECORD_POLICY_VERSION = "cost-regex-1"

# JavaScript String.prototype.trim() whitespace; Python str.strip() differs (e.g. U+FEFF, U+001C).
_JS_WHITESPACE = (
    "\t\n\v\f\r              "
    "    　﻿"
)


def _js(pattern, flags=0):
    # <D> and <S> are JavaScript `.` and `\s` without the `u` flag; Python's built-ins differ.
    # ASCII keeps case folding to JavaScript's non-unicode rules (e.g. no Kelvin sign for k).
    pattern = pattern.replace("<D>", "[^\n\r  ]").replace("<S>", f"[{_JS_WHITESPACE}]")
    return re.compile(pattern, flags | re.ASCII)


# The order of these checks is part of the prototype contract.
_NO_COST = _js(r"(비용|원가|가격)<D>{0,15}(없|않|아니|아님|무관|괜찮|적정)")
_TRANSITION = _js(r"(해결|해소|지만|그러나|다만|반면)")
_COST = _js(r"(비용|원가|가격)<D>{0,15}(높|비싸|초과|부담|때문|문제|과다)|예산<D>{0,8}초과")
_UNCERTAIN = _js(r"(불명|확인|추정|모르|\?)")
_OTHER = _js(r"(성능|균일도|에너지|플럭스)<D>{0,12}(때문|미달|문제|부족)")
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
    # JavaScript `a || b`: empty strings fall through, objects (even empty) do not.
    for value in values:
        if value is not None and value != "" and value is not False and value != 0:
            return value
    return values[-1]


def classify(note):
    text = _text(note).strip(_JS_WHITESPACE)
    if not text:
        return "MISSING"
    if _NO_COST.search(text):
        return "NO_COST"
    if _TRANSITION.search(text):
        return "UNCLEAR"
    if _COST.search(text) and not _UNCERTAIN.search(text):
        return "COST"
    if _OTHER.search(text):
        return "OTHER"
    return "UNCLEAR"


def evidence(records, run_id):
    entries = []
    for record in records:
        if record.get("version") == 2:
            candidates = record.get("candidates") or []
        else:
            candidates = [
                {
                    "runId": record.get("targetRunId"),
                    "runVersionId": (record.get("targetRunRef") or {}).get("runVersionId"),
                    "decision": record.get("decision"),
                    "note": record.get("comment"),
                }
            ]
        candidate = next((item for item in candidates if item.get("runId") == run_id), None)
        if candidate is None:
            continue
        # Shared comments are only attributable when the record has one candidate.
        note = _text(_first(candidate.get("note"), record.get("overallComment") if len(candidates) == 1 else "", ""))
        foreign_run = any(found != run_id for found in _RUN_ID.findall(note))
        snapshot = next((item for item in record.get("runSnapshots") or [] if item.get("runId") == run_id), None)
        entries.append(
            {
                "recordId": _first(record.get("reviewId"), record.get("id")),
                "runId": run_id,
                "runVersionId": candidate.get("runVersionId"),
                "decision": candidate.get("decision"),
                "note": note,
                "sharedComment": _text(_first(record.get("overallComment"), "")),
                "reason": "UNCLEAR" if foreign_run else classify(note),
                "createdAt": record.get("createdAt"),
                "question": _text(_first(record.get("question"), record.get("queryText"), "")),
                "conditions": _first(candidate.get("conditions"), (snapshot or {}).get("conditions"), {}),
                "demo": bool(record.get("isDemo")),
            }
        )
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
    return {
        "runId": run_id,
        "count": count,
        "status": status,
        "entries": entries,
        "mixed": "ADOPT" in decisions and "REJECT" in decisions,
    }


def valid_threshold(threshold):
    """User-supplied rule: an integer of at least 1 (JavaScript Number.isInteger)."""
    if isinstance(threshold, bool):
        return False
    if isinstance(threshold, int):
        return threshold >= 1
    return isinstance(threshold, float) and math.isfinite(threshold) and threshold.is_integer() and threshold >= 1


def filter_runs(records, run_ids, threshold=1):
    # Infinity means "exclude nothing" and is used only to undo an exclusion.
    if threshold != math.inf and not valid_threshold(threshold):
        raise DomainError("INVALID_THRESHOLD", "제외 기준은 1 이상의 정수여야 합니다.")
    summaries = [summarize(records, run_id) for run_id in dict.fromkeys(run_ids)]
    return {
        "remaining": [s for s in summaries if s["count"] < threshold],
        "excluded": [s for s in summaries if s["count"] >= threshold],
    }


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
