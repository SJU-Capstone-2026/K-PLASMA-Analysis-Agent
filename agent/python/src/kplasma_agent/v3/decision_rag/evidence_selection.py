"""Record-local support decisions for bounded retrieval, not policy counting.

Scope, ownership, versions and immutable citations are checked upstream. This
module neither invents a source value nor chooses a fixed number of results.
Only explicit request facts can rescue a legacy language-filter rejection.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .constraints import _FACTS, supports_explicit_request
from .support import _active_request, _causal_request, _clauses, _physics_support, supports_requested_evidence

EVIDENCE_SELECTION_POLICY = "branch-evidence-selection-2"


@dataclass(frozen=True)
class EvidenceAssessment:
    supported: bool
    reason: str
    strong_support: bool = False


_COST = r"비용|원가|가격|예산|견적|금액|단가|지출|금전|경제적|고비용"
_COST_RE = re.compile(_COST)
_PENDING = re.compile(
    r"추정|불명|미정|불확실|미확정|미확인|기다[리린]|대기|확인\s*중|문의\s*중|"
    r"(?:추가|더)\s*(?:확인|답변)|확인[^.!?;]{0,10}(?:필요|해야|못)|"
    r"근거[^.!?;]{0,12}(?:못|없)|(?:확정|단정)[^.!?;]{0,12}(?:못|않|없|어려|어렵)"
)
_COST_NEGATIVE = re.compile(
    r"(?:" + _COST + r")[^.!?;]{0,10}(?:문제|부담)(?:이|가|은|는)?\s*(?:없|아니)|"
    r"(?:" + _COST + r")(?:은|는|이|가)?\s*(?:적정|괜찮|무관)|"
    r"(?:" + _COST + r")(?:와|과)(?:는|도)?\s*무관|"
    r"(?:" + _COST + r")[^.!?;]{0,10}(?:해결|해소|허용\s*범위\s*안|감당\s*가능|감당할\s*수\s*있)|"
    r"(?:" + _COST + r")(?:이|가|은|는)?\s*(?:때문|탓|(?:반려\s*)?원인|사유)(?:이|가|은|는)?\s*(?:아니|아님|않|없)"
)
_COST_POSITIVE = re.compile(
    r"(?:" + _COST + r")[^.!?;]{0,75}(?:높|비싸|초과|넘|부담|때문|문제|과다|상한[^.!?;]{0,8}벗어나|감당할\s*수\s*없)"
)
_REJECT = re.compile(r"(?:반려|거절|탈락|제외)(?!하지|되지|\s*(?:아니|않))|불승인|선정하지|채택하지|승인하지|후보에서\s*뺐")
_ADOPT = re.compile(r"(?<!불)(?:채택|승인|선정)(?!하지|\s*않|\s*안|\s*일정|\s*여부|\s*대기)")
_HOLD = re.compile(r"보류|판단\s*대기")
_ACTUAL_AMOUNT = re.compile(r"몇\s*원|원\s*단위|견적\s*총액|금액[^.!?;]{0,14}(?:숫자|수치|얼마)|"
                            r"(?:실제|정확한|구체적)[^.!?;]{0,15}(?:금액|견적|가격)|얼마(?!나)")
_MONEY = re.compile(r"(?:(?:[₩$€]|\b(?:USD|KRW|EUR))\s*[0-9][0-9,.]*|"
                    r"[0-9][0-9,.]*\s*(?:천만|백만|십만|억|만|천)?\s*(?:원(?!가)|달러|USD\b|KRW\b|EUR\b))", re.I)
_FINAL_ADOPT = re.compile(r"(?:승인|채택|선정)\s*완료|최종\s*(?:승인|채택|선정)|"
                          r"(?:승인|채택|선정)(?:했|한|된|받)")
_CAUSE = re.compile(r"물리[^.!?;]{0,12}(?:원인|기전|메커니즘)|공정\s*원인|원인\s*(?:분석|자료)")
_PROOF_NEGATIVE = re.compile(r"(?:검증|입증|분석|확인)[^.!?;]{0,25}(?:아니|않|못|없)|미검증|미입증|미확인")
_LIMIT_QUERY = re.compile(r"한계|제한|구분|분리|아니라고|아니라는|검증하지|입증하지|더\s*확인|추가\s*확인")
_METRICS = (
    (re.compile(r"플럭스|flux", re.I), re.compile(r"플럭스|flux", re.I)),
    (re.compile(r"에너지|energy", re.I), re.compile(r"에너지|energy", re.I)),
    (re.compile(r"균일도|균일성|uniformity", re.I), re.compile(r"균일도|균일성|uniformity", re.I)),
    (re.compile(r"성능|performance", re.I), re.compile(r"성능|플럭스|에너지|균일도|균일성|표면\s*상태|막\s*두께|performance|flux|energy|uniformity", re.I)),
)
_DEFICIT = re.compile(r"미달|부족|모자|못\s*(?:채|맞|미)|충족하지\s*못")
_ORDINALS = {
    1: re.compile(r"첫\s*(?:번째)?|1\s*차"),
    2: re.compile(r"두\s*번째|2\s*차"),
    3: re.compile(r"세\s*번째|3\s*차"),
}
_RUN_ID = re.compile(r"RUN-[A-Z0-9-]+", re.I)
_PRIOR_REFERENCE = re.compile(r"앞서|앞\s*후보|과거|이전")
_ADJACENT_REFERENCE = re.compile(r"옆\s*후보")
_SAME_RECORD = re.compile(r"동시에|둘\s*다|하나의\s*기록|한\s*개의\s*기록|단일\s*기록|"
                          r"(?<![가-힣])한\s+기록(?:에|안에|내에)|모두\s*만족")
_PROOF_STATE_TERM = r"미검증|미입증|검증|입증|증명"
_INTERPRETATION_BAN = re.compile(
    r"(?:(?:추측|추정|단정|확정|배정|할당|지정|귀속|간주|해석)(?:하|시키)|붙이|돌리|옮기)지\s*"
    r"(?:말(?:아|고|라)?(?:줘|주세요)?|마(?:세요|라)?)"
)
_PRESENTATION = re.compile(r"원문|인용문|문장|표로|목록|구분|분리|대조|출처|귀속|주인|후보별|개별")
_CHRONOLOGY = re.compile(r"시각|시간|날짜|작성일|일시|순서|시점|최신|과거|최근")


def _factual_request(clause: str) -> bool:
    return bool(_COST_RE.search(clause) or _causal_request(clause) or _PENDING.search(clause)
                or _REJECT.search(clause) or _ADOPT.search(clause) or _HOLD.search(clause)
                or _ACTUAL_AMOUNT.search(clause) or _CHRONOLOGY.search(clause)
                or any(query.search(clause) for query, _ in _METRICS)
                or any(re.search(requested, clause) for requested, _ in _FACTS))


def _request_analysis_text(question: str) -> str:
    """Separate instructions about attribution/contrasts from requested events."""
    clauses = []
    for clause in re.split(r"[.!?;]", question):
        if _INTERPRETATION_BAN.search(clause) and not re.search(r"찾|모아|보여|읽|검색", clause):
            continue
        if re.search(r"(?:배정|귀속|할당)[^.!?;]{0,15}(?:않|말|없)", clause) and not re.search(r"찾|모아|보여", clause):
            continue
        if re.search(r"(?:기다|대기)[^.!?;]{0,25}과\s*구분", clause):
            continue
        clauses.append(re.sub(r"귀속[^.!?;]{0,8}불명(?:확)?", "", clause))
    if any(_factual_request(clause) for clause in clauses):
        # Formatting and attribution are obligations on the selected evidence,
        # not extra OR branches authorizing any vaguely related record. A
        # generic scope-only lookup remains valid when no factual event was
        # requested, and actual timeline/state requests remain factual.
        clauses = [clause for clause in clauses
                   if not _PRESENTATION.search(clause) or _factual_request(clause)]
    return ". ".join(clauses)


def _sentences(text: str) -> list[str]:
    # Keep line-wrapped subjects and their predicates together. Question marks
    # inside a note can express uncertainty, not a separate evidence event.
    return [part.strip() for part in re.split(
        r"[.!;]|하지만|그러나|다만|반면|(?<=며)\s*(?=(?:현재|이번)\s*(?:대상|후보|안))",
        re.sub(r"[\r\n?]+", " ", text)) if part.strip()]


def _cost_clauses(text: str) -> list[str]:
    return [clause for clause in _sentences(text) if _COST_RE.search(clause)]


def _legacy(question: str, text: str, decision: str | None) -> bool:
    return bool(supports_explicit_request(question, text, decision=decision)
                and supports_requested_evidence(question, text, decision=decision))


def _assess_branch(question: str, text: str, decision: str | None) -> EvidenceAssessment:
    if re.search(r"문자열|시스템\s*지시|프롬프트|검증용", question):
        specific = re.split(r"(?:기록|메모)(?:들)?\s*중", question)
        if len(specific) > 1 and specific[-1].strip():
            question = specific[-1].strip()
    legacy = _legacy(question, text, decision)
    # Mandatory proof-state requirements cannot be bypassed by an earlier
    # cost/pending/approval branch that merely shares a topic with the query.
    if _causal_request(question) and not _physics_support(question, _clauses(text)):
        return EvidenceAssessment(False, "REQUESTED_CAUSAL_PROOF_UNSUPPORTED")
    cost = bool(_COST_RE.search(question))
    clauses = _cost_clauses(text)
    pending_request = bool(_PENDING.search(question))
    if (re.search(r"(?:현재|이번|선택)[^.!?;]{0,20}(?:사유|이유)[^.!?;]{0,20}(?:미정|미확인|모르|확인하지\s*못)", question)
            and re.search(r"다른|앞|옆|인용|참고", question)):
        pending_request = False
    resolved_alternative = bool(re.search(r"풀렸거나|해결[^.!?;]{0,12}거나|해소[^.!?;]{0,12}거나", question))
    if resolved_alternative:
        pending_request = False
    requested_states = {name for name, words in (("REJECT", _REJECT), ("ADOPT", _ADOPT), ("HOLD", _HOLD))
                        if words.search(question)}
    mixed = len(requested_states) > 1 or bool(re.search(r"전후|공존|과거[^.!?;]{0,35}후속|반려[^.!?;]{0,25}채택", question))
    for requested, evidence in _FACTS:
        if re.search(requested, question) and not re.search(evidence, text):
            return EvidenceAssessment(False, "EXPLICIT_EVENT_MISSING")
    if _SAME_RECORD.search(question):
        for query_metric, evidence_metric in _METRICS:
            if query_metric.search(question) and not evidence_metric.search(text):
                return EvidenceAssessment(False, "SAME_RECORD_METRIC_MISSING")
    requested_ordinals = {number for number, words in _ORDINALS.items()
                          if any(words.search(clause) and "검토" in clause for clause in _sentences(question))}
    if len(requested_ordinals) > 1 and re.search(r"부터[^.!?;]{0,30}까지", question):
        requested_ordinals = set(range(min(requested_ordinals), max(requested_ordinals) + 1))
    if requested_ordinals:
        stated = {number for number, words in _ORDINALS.items()
                  if any(words.search(clause) and "검토" in clause for clause in _sentences(text))}
        if not (requested_ordinals & stated):
            return EvidenceAssessment(False, "REQUESTED_REVIEW_ORDINAL_MISSING")

    if cost and _ACTUAL_AMOUNT.search(question) and not pending_request:
        monetary = [clause for clause in clauses if _MONEY.search(clause)]
        if re.search(r"견적|가격|원가|단가|구매가", question):
            monetary = [clause for clause in monetary if re.search(r"견적|가격|원가|단가|구매가", clause)
                        or ("금액" in clause and not re.search(r"예산|한도|상한", clause))]
        if re.search(r"몇\s*원|원\s*단위|원화|KRW|₩", question, re.I):
            monetary = [clause for clause in monetary if re.search(r"[0-9][0-9,.]*\s*(?:천만|백만|십만|억|만|천)?\s*원|KRW\s*[0-9]|₩\s*[0-9]", clause, re.I)]
        if re.search(r"달러|USD|\$", question, re.I):
            monetary = [clause for clause in monetary if re.search(r"[0-9][0-9,.]*\s*(?:달러|USD)|USD\s*[0-9]|\$\s*[0-9]", clause, re.I)]
        if re.search(r"유로|EUR|€", question, re.I):
            monetary = [clause for clause in monetary if re.search(r"[0-9][0-9,.]*\s*EUR|EUR\s*[0-9]|€\s*[0-9]", clause, re.I)]
        found = any(not _PENDING.search(clause)
                    and not re.search(r"(?:원|달러|USD|KRW|EUR)[^.!?;]{0,8}(?:아니|않|못)", clause, re.I)
                    for clause in monetary)
        return EvidenceAssessment(found, "MONETARY_VALUE_PRESENT" if found else "MONETARY_VALUE_MISSING", found)

    positive_completion = bool(_FINAL_ADOPT.search(question)
                               and not re.search(r"(?:승인|채택|선정)[^.!?;]{0,12}(?:완료되지|완료하지|여부|됐는지|못|않)", question))
    adoption_only = requested_states == {"ADOPT"} and not re.search(r"여부|했는지|됐는지|되었는지", question)
    if (positive_completion or adoption_only) and "REJECT" not in requested_states:
        # A record's own decision metadata is authoritative for an individual
        # note. Contextual/shared notes must explicitly state the requested event.
        completed = bool(not _PENDING.search(text) and decision in {None, "ADOPT"}
                         and (_ADOPT.search(text) or (decision == "ADOPT" and not _REJECT.search(text))))
        return EvidenceAssessment(completed and legacy, "ADOPTION_COMPLETED" if completed else "ADOPTION_NOT_COMPLETED", completed and legacy)

    if requested_states == {"HOLD"}:
        held = bool(_HOLD.search(text) or (decision == "HOLD" and not _REJECT.search(text) and not _ADOPT.search(text)))
        if not held:
            return EvidenceAssessment(False, "HOLD_REQUEST_WITH_OTHER_DECISION")

    if cost and pending_request and not mixed:
        pending = any(_PENDING.search(clause)
                      or ("HOLD" in requested_states and re.search(r"협의|보류", clause)) for clause in clauses)
        if pending:
            return EvidenceAssessment(True, "COST_AWAITING_EVIDENCE", True)
        if clauses:
            return EvidenceAssessment(False, "COST_NOT_PENDING")

    # Limitations/negative-proof queries can be answered by an explicitly
    # unverified cause-analysis note even when it omits the repeated word physics.
    if _CAUSE.search(question) and _LIMIT_QUERY.search(question):
        related = [clause for clause in _sentences(text) if _CAUSE.search(clause)]
        asks_denial = bool(_PROOF_NEGATIVE.search(question))
        asks_pending = bool(_PENDING.search(question))
        broad_limits = bool(re.search(r"한계|제한|구분|분리", question))
        if asks_denial and not asks_pending and not broad_limits:
            limited = any(_PROOF_NEGATIVE.search(clause) for clause in related)
        elif asks_pending and not asks_denial and not broad_limits:
            limited = any(_PENDING.search(clause) for clause in related)
        else:
            limited = any(_PROOF_NEGATIVE.search(clause) or _PENDING.search(clause) for clause in related)
        if limited:
            return EvidenceAssessment(True, "CAUSE_ANALYSIS_LIMITATION", True)
        if related:
            return EvidenceAssessment(False, "REQUESTED_CAUSE_LIMITATION_STATE_MISSING")

    positive_cost = bool(cost and _REJECT.search(question) and not mixed and not pending_request and not resolved_alternative
                         and not _COST_NEGATIVE.search(question)
                         and re.search(r"높|고비용|부담|초과|비싸|때문|원인|사유|문제|확정|비용\s*반려|원가\s*반려|가격\s*반려", question))
    if positive_cost:
        positive = any(_COST_POSITIVE.search(clause) and not _COST_NEGATIVE.search(clause)
                       and not _PENDING.search(clause)
                       and not _HOLD.search(clause)
                       and (_REJECT.search(clause) or (decision == "REJECT" and not _ADOPT.search(clause))
                            or re.search(r"비싸(?:거나|다거나)", question))
                       for clause in clauses)
        if not positive:
            return EvidenceAssessment(False, "AFFIRMATIVE_COST_REJECTION_UNSUPPORTED")
        return EvidenceAssessment(True, "AFFIRMATIVE_COST_REJECTION", True)

    metric_match = any(query.search(question) and evidence.search(text) and _DEFICIT.search(question)
                       and _DEFICIT.search(text) for query, evidence in _METRICS)
    return EvidenceAssessment(legacy, "EXPLICIT_TOPIC_AND_STATE" if legacy and metric_match else
                              "LEGACY_SUPPORTED" if legacy else "EXPLICIT_CONDITION_UNSUPPORTED",
                              bool(legacy and metric_match))


def assess_requested_evidence(question: str, document: dict) -> EvidenceAssessment:
    """Assess one already scoped/attributed source without changing its fields.

    A collection of distinct requested facts is an OR over request branches;
    explicit same-record conjunction remains a single conjunctive request.
    Strong support means direct textual/state support, never an oracle label.
    """
    text = document.get("text", "")
    role = document.get("citationRole", document.get("attribution"))
    decision = document.get("decision") if role not in {"REFERENCE_ONLY", "SHARED_UNASSIGNED"} else None
    if not isinstance(question, str) or not isinstance(text, str) or not text.strip():
        return EvidenceAssessment(False, "EMPTY_EVIDENCE")
    active = _request_analysis_text(_active_request(question))
    if not active.strip():
        return EvidenceAssessment(False, "NO_POSITIVE_EVIDENCE_REQUEST")
    if role == "REFERENCE_ONLY" and (_COST_RE.search(active) or "비싸" in active):
        descriptors = [pattern for pattern in (_PRIOR_REFERENCE, _ADJACENT_REFERENCE) if pattern.search(active)]
        if descriptors and not any(pattern.search(text) for pattern in descriptors):
            return EvidenceAssessment(False, "REQUESTED_REFERENCE_DESCRIPTOR_MISSING")
    # Explicitly requested labels are literal evidence, not generic semantic
    # topics. Preserve the source string rather than substituting another label.
    labels = re.findall(r"[‘\"']([^’\"']+)[’\"']\s*(?:이?라고)\s*(?:표시|적)", active)
    if not labels:
        labels = re.findall(r"(?:에서|\s중)\s*([^.!?;]+?)(?:이라고|라고)\s*(?:표시|적힌)", active)
    if labels and not any(re.sub(r"\s+", "", label).casefold() in re.sub(r"\s+", "", text).casefold() for label in labels):
        return EvidenceAssessment(False, "REQUESTED_LITERAL_LABEL_MISSING")
    conjunction = bool(_SAME_RECORD.search(active))
    branches = [active]
    if not conjunction and re.search(r"[,，]|함께|각각|나뉜|통틀어|전후", active):
        split = [branch.strip() for branch in re.split(r"[,，]", active) if branch.strip()]
        if len(split) > 1:
            branches = ([split[0] + " " + branch for branch in split[1:]]
                        if re.search(r"(?:중|에서)$", split[0]) else split)
    if not conjunction and len(_RUN_ID.findall(active)) > 1:
        branches = [part for branch in branches
                    for part in re.split(r"(?<=[가-힣])(?:와|과)\s+(?=RUN-)", branch) if part.strip()]
    if not conjunction:
        branches = [part for branch in branches for part in re.split(
            r"(?:와|과|및)\s*(?=비용|가격|원가|예산|성능|에너지|플럭스|균일|사유|원인|물리|인과)", branch) if part.strip()]
        proof_branches = []
        for branch in branches:
            parts = re.split(r"(?:와|과|및|또는)\s*(?=(?:" + _PROOF_STATE_TERM + r"))", branch)
            shared_subject = re.split(_PROOF_STATE_TERM, parts[0], maxsplit=1)[0]
            for index, part in enumerate(parts):
                # A list of proof states about one relation may omit that
                # relation after 'and'. Keep it on each state branch instead
                # of treating '미검증 기록' as an unscoped generic request.
                if index and _causal_request(shared_subject) and not _causal_request(part):
                    part = shared_subject + " " + part
                proof_branches.append(part)
        branches = proof_branches
    subject = document.get("runId")
    if role == "REFERENCE_ONLY":
        named = set(_RUN_ID.findall(text))
        if len(named) == 1:
            subject = next(iter(named))
    assessments = []
    for branch in branches:
        identifiers = set(_RUN_ID.findall(branch))
        if len(branches) > 1 and identifiers and subject and subject not in identifiers:
            continue
        assessments.append(_assess_branch(branch, text, decision))
    if not assessments:
        return EvidenceAssessment(False, "REQUEST_BRANCH_SUBJECT_MISMATCH")
    supported = [assessment for assessment in assessments if assessment.supported]
    if supported:
        return next((assessment for assessment in supported if assessment.strong_support), supported[0])
    return assessments[0]


def select_evidence(question: str, documents: list[dict]) -> list[dict]:
    """Return supported original documents; no count padding or dedup of events."""
    return [document for document in documents if assess_requested_evidence(question, document).supported]
