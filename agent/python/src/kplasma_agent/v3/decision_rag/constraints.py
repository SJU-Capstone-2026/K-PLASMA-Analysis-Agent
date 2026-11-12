"""Conservative literal support checks, independent of the cost-count policy.

An unspecified performance issue is not evidence of a named metric shortage.
A pending response is not evidence that a response has already been received.
These checks narrow citations, never infer a reason or modify saved records.
"""
import re
from . import policy

_METRICS = (r"플럭스|flux", r"에너지|energy", r"균일도|균일성|uniformity", r"성능|performance")
_SHORTAGE = r"부족|미달|못\s*미친|못\s*미쳤|못\s*채운|충족하지\s*못|모자"
_PENDING = re.compile(r"기다[리린]|대기|확인\s*중|문의\s*중|추가\s*확인|불명|불확실|미정|모르|추정")
_UNCERTAIN_QUERY = re.compile(r"확정[^.!?\n]{0,12}(?:어려|어렵|못|않|아니|없)|불명|불확실|미정|모르|추정")
_FACTS = (
    (r"납품|배송|납기|운송|인도일", r"납품|배송|납기|운송|인도일"),
    (r"협상|흥정|(?<![가-힣])인하|(?:가격|단가|비용|요금)(?:를|가|는)?\s*인하|단가[^.!?\n]{0,8}낮춘",
     r"협상|흥정|(?<![가-힣])인하|(?:가격|단가|비용|요금)(?:를|가|는)?\s*인하|단가[^.!?\n]{0,8}낮"),
    (r"증액|예산[^.!?\n]{0,8}늘|추가\s*예산", r"증액|예산[^.!?\n]{0,8}늘|추가\s*예산"),
    (r"교체|대체|경쟁\s*후보", r"교체|대체|경쟁"),
    (r"오염|불순물", r"오염|불순물"),
    (r"손상|파손|고장", r"손상|파손|고장"),
    (r"안전(?:성)?\s*(?:문제|위험|기준)|사고|위험", r"안전|사고|위험"),
    (r"수명|내구", r"수명|내구"),
)
_COST_ANCHOR = r"비용|가격|원가|예산|금액|단가|지출|견적"
_COMPLETED_CLAUSE = re.compile(
    r"(?:확인|확정)(?:을|이|은|는)?\s*(?:완료|했|되었|됐)|답변[^.!?\n]{0,12}(?:이미\s*)?받"
)
_NEGATED_COMPLETION = re.compile(r"(?:확인|확정|완료|답변)[^.!?\n]{0,18}(?:아니|않|못|없)")


def _has_completed_relevant_clause(question, text):
    """An unrelated pending sentence cannot erase explicit requested evidence.

    An unrelated completed sentence cannot establish it either. Keep the old
    conservative rejection when the request has no explicit topic anchor.
    """
    anchors = [evidence for requested, evidence in _FACTS if re.search(requested, question)]
    anchors.extend(metric for metric in _METRICS if re.search(metric, question, re.I))
    if re.search(_COST_ANCHOR, question):
        anchors.append(_COST_ANCHOR)
    if not anchors:
        return False
    clauses = re.split(r"[.!?;]|하지만|그러나|다만|반면", re.sub(r"[\r\n]+", " ", text))
    return any(
        all(re.search(anchor, clause, re.I) for anchor in anchors)
        and _COMPLETED_CLAUSE.search(clause)
        and not _PENDING.search(clause)
        and not _NEGATED_COMPLETION.search(clause)
        for clause in clauses
    )


def supports_explicit_request(question, text, *, decision=None):
    # These are factual anchors, not automatic rejection categories. A note
    # about price alone cannot support a requested shipping/safety/etc. event.
    for requested, evidence in _FACTS:
        if re.search(requested, question) and not re.search(evidence, text):
            return False
    named_metrics = [metric for metric in _METRICS if re.search(metric, question, re.I)]
    collection = len(named_metrics) > 1 and re.search(r"함께|각각|기록들|메모들|나눠|구분", question)
    if collection and not re.search(r"동시에|둘\s*다|한\s*기록", question):
        if not any(re.search(metric, text, re.I) for metric in named_metrics):
            return False
    for metric in (() if collection else _METRICS):
        shortage = re.search(r"(?:" + metric + r")[^.!?\n]{0,10}(?:" + _SHORTAGE + r")|"
                             r"(?:" + _SHORTAGE + r")[^.!?\n]{0,22}(?:" + metric + r")", question, re.I)
        if shortage and not re.search(metric, text, re.I):
            return False
    completion = bool(re.search(r"확정|답변[^.!?\n]{0,12}(?:이미\s*)?받|확인[^.!?\n]{0,8}완료", question))
    if (completion and not _UNCERTAIN_QUERY.search(question) and _PENDING.search(text)
            and not _has_completed_relevant_clause(question, text)):
        return False
    unclear_cause = re.search(r"(?:원인|사유)[^.!?\n]{0,22}(?:불명|미정|모르|확정[^.!?\n]{0,8}(?:어려|어렵|못|않))", question)
    if "최종" in question and unclear_cause and not re.search(r"(?:원인|사유)[^.!?\n]{0,30}(?:불명|불확실|미정|모르|확인\s*중|확정[^.!?\n]{0,12}(?:못|않|어렵))", text):
        return False
    cost_positive = re.search(r"(?:비용|가격|원가|예산|금액)[^.!?\n]{0,35}(?:높|비싸|초과|부담)[^.!?\n]{0,30}(?:반려|탈락|거절)", question)
    mixed_history = re.search(r"함께|모두|전후|대조|각각|공존|반려\s*(?:후|이후)", question)
    negative_cost_query = re.search(r"(?:비용|가격|원가|예산|금액)[^.!?\n]{0,25}(?:없|아니|않|괜찮|적정|해결|해소)", question)
    if cost_positive and not mixed_history and not negative_cost_query and policy.classify(text) == "NO_COST":
        return False
    if (not mixed_history and not _UNCERTAIN_QUERY.search(question)
            and re.search(r"(?:원인|사유)[^.!?\n]{0,20}비용[^.!?\n]{0,20}확정|비용[^.!?\n]{0,25}(?:원인|사유)[^.!?\n]{0,12}확정", question)
            and policy.classify(text) != "COST"):
        return False
    approved = re.search(r"(?:채택|승인|선정)(?:했|한|되|받)|선택(?:했|된)", question)
    if (decision is not None and approved and not mixed_history
            and not re.search(r"반려|보류|대기|거절|탈락", question) and decision != "ADOPT"):
        return False
    return True
