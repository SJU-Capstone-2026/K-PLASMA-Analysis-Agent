"""Local checks for whether a note supports the explicitly requested evidence.

These checks supplement dense relevance and the scope/ownership checks. They do
not classify saved decisions, change rule counts, or claim general entailment.
Unknown wording remains the responsibility of retrieval and its stated limits.
"""
from __future__ import annotations

import re

SUPPORT_POLICY = "explicit-evidence-support-2"


def _pattern(value: str) -> re.Pattern[str]:
    return re.compile(value, re.IGNORECASE)


_COST = _pattern(r"비용|가격|원가|예산|금액|단가|재정|경비|지출|견적|구매가|금전|경제적|"
                 r"돈(?:의|이|은|는|을|에|\s|문제|규모|$)|\b(?:cost|budget|price|expense)\b")
_PERFORMANCE = _pattern(r"성능|performance")
_PERFORMANCE_EVIDENCE = _pattern(r"성능|performance|플럭스|flux|에너지|energy|균일도|균일성|uniformity|표면\s*상태|막\s*두께")
_FLUX = _pattern(r"플럭스|flux")
_ENERGY = _pattern(r"에너지|energy")
_UNIFORMITY = _pattern(r"균일도|균일성|uniformity")
_PHYSICS = _pattern(r"물리[^.!?\n]{0,12}(?:원인|기전|메커니즘)|공정\s*원인|장비\s*내부|"
                    r"인과\s*(?:관계|효과|기전)?|원인\s*(?:과|[-→>])\s*결과|"
                    r"physical\s+(?:cause|mechanism)|\bcausal(?:ity|\s+(?:relation|effect|mechanism))?\b")
_METRICS = (_PERFORMANCE, _FLUX, _ENERGY, _UNIFORMITY)
_FACT_TOPICS = (
    _pattern(r"납품|배송|납기|운송|인도일"),
    _pattern(r"협상|흥정|(?<![가-힣])인하|(?:가격|단가|비용|요금)(?:를|가|는)?\s*인하|단가[^.!?\n]{0,8}낮"),
    _pattern(r"증액|추가\s*예산|예산[^.!?\n]{0,8}늘"),
    _pattern(r"환경\s*인증|환경\s*기준|인증\s*통과|인증서"),
    _pattern(r"오염|불순물"),
    _pattern(r"손상|파손|고장"),
    _pattern(r"안전(?:성)?\s*(?:문제|위험|기준)|사고|위험"),
    _pattern(r"수명|내구"),
    _pattern(r"표면\s*상태|막\s*두께"),
    _pattern(r"일정|검토\s*시간|심사\s*시간"),
    _pattern(r"예외\s*승인|조건부\s*(?:승인|채택)|보완[^.!?\n]{0,8}조건"),
)
_SHORTAGE = _pattern(r"부족|미달|못\s*미|못\s*채|충족하지\s*못|모자")
_MIXED = _pattern(r"전후|대조|공존|변화|바뀌|반려[^.!?\n]{0,16}(?:후|이후|다가)|이전[^.!?\n]{0,30}후속")
_PENDING = _pattern(r"추정|불명|불확실|미정|미확정|기다[리린]|대기|확인\s*중|문의\s*중|"
                    r"추가\s*확인|더\s*확인|확인[^.!?\n]{0,8}(?:필요|해야)|근거[^.!?\n]{0,12}(?:없|못)|"
                    r"(?:확정|단정)[^.!?\n]{0,10}(?:어려|어렵|못|않|없)")
_PROOF = _pattern(r"검증|입증|실험|분석|확인|증명")
_PROOF_NEGATIVE = _pattern(r"미검증|미입증|미확인|검증\s*전|입증\s*전|"
                           r"(?:검증|입증|실험|분석|확인|증명)[^.!?\n]{0,22}"
                           r"(?:아니|아님|않|못|없|어려|어렵)|"
                           r"(?:못|않)[^.!?\n]{0,5}(?:검증|입증|실험|분석|확인)")
_NEUTRAL_PROOF = _pattern(r"(?:검증|입증|확인|분석)(?:\s*완료)?\s*여부|했는지|됐는지|되었는지")
_PROOF_CAPABILITY = _pattern(r"(?:검증|입증|증명)[^.!?\n]{0,12}(?:수\s*있는지|가능|자료인지)|"
                            r"메모[^.!?\n]{0,10}만으로[^.!?\n]{0,10}(?:입증|검증)|근거[^.!?\n]{0,8}충분")
_CAUSAL_QUESTION = _pattern(r"왜|원인|기전|메커니즘")
_PROOF_LIMITS = _pattern(r"한계|구분|분리")
_CAUSE_ANALYSIS = _pattern(r"원인\s*(?:분석|자료)|공정\s*원인|물리[^.!?\n]{0,12}(?:원인|기전|메커니즘)")
_PROOF_COMPLETED = _pattern(r"(?:검증|입증|증명|분석|확인)(?:을|를|이|가|은|는|\s)*(?:완료|했|한|되었|됐|되었음)|"
                            r"(?:검증|입증|증명|분석|확인)된|실험[^.!?\n]{0,20}(?:밝혀|확인|입증|검증)")
_VERIFICATION = _pattern(r"검증|입증|증명")
_VERIFICATION_COMPLETED = _pattern(
    r"(?:검증|입증|증명)(?:을|를|이|가|은|는|\s)*(?:완료|했|한|되었|됐)|(?:검증|입증|증명)된|"
    r"실험[^.!?\n]{0,20}(?:밝혀|입증|검증)"
)
_TEXT_QUERY = _pattern(r"문자열|시스템\s*지시|인젝션|canary|프롬프트|검증용\s*문장")
_ALTERNATIVES = _pattern(r"또는|혹은|이나|거나|각각|함께|모두|모아")
_CONJUNCTION = _pattern(r"동시에|둘\s*다|하나의\s*기록|(?<![가-힣])한\s+기록")
_DECISION_WORDS = {
    "REJECT": _pattern(r"반려|거절|탈락|제외|선정하지|채택하지|승인하지"),
    "ADOPT": _pattern(r"(?<!미)(?:채택|승인|선정)(?!하지|\s*않|\s*안)"),
    "HOLD": _pattern(r"보류|판단\s*대기"),
}
_PROHIBITED_EVIDENCE_ACTION = _pattern(
    r"(?:쓰|사용하|인용하|가져오|찾|포함하|보여주|제시하|취급하|삼)지\s*(?:말|마(?:세요|라)?)|"
    r"(?:인용|사용|포함|제시|검색)\s*(?:금지|하지\s*마)|"
    r"(?:제외|배제)(?:해\s*줘|해\s*주세요|해주세요|하자)|"
    r"(?:필요\s*(?:없(?:어|어요|습니다|다)?|하지\s*않(?:아|아요|습니다))|"
    r"원하지\s*않(?:아|아요|습니다))\s*$"
)
_FINISHED_REQUEST_ACTION = (
    r"(?:(?:찾아|보여|알려|가져와|읽어|정리해|확인해|조회해)(?:줘|주세요|주라)|"
    r"(?:쓰|사용하|인용하|가져오|찾|포함하|보여주|제시하|취급하|삼)지\s*"
    r"(?:말아(?:줘|주세요)?|마(?:세요|라)?|말라)|"
    r"(?:필요\s*(?:없(?:어|어요|습니다|다)?|하지\s*않(?:아|아요|습니다))|"
    r"원하지\s*않(?:아|아요|습니다)))"
)
_CAUSAL_ANCHORS = (
    _pattern(r"압력|pressure"),
    _pattern(r"IED\s*(?:폭|너비|분포\s*폭)|이온\s*에너지\s*분포\s*(?:폭|너비)"),
    _FLUX, _ENERGY, _UNIFORMITY,
    _pattern(r"오염|불순물|contamination"),
    _pattern(r"온도|temperature"),
    _pattern(r"소스\s*(?:전력|파워)|source\s*power"),
    _pattern(r"바이어스\s*(?:전력|파워)|bias\s*power"),
)
_UP = _pattern(r"상승|증가|확대|높(?:아|였|인|임|이)|늘(?:었|어|린|림|어남)?|커(?:졌|진)|증대")
_DOWN = _pattern(r"하락|감소|축소|낮(?:아|췄|춘|춤)|줄(?:었|어|인|임)|작아")
_CAUSAL_LINK = _pattern(r"때문|유발|일으|영향|원인|인과|으로|caus")
_PROOF_COREFERENCE = _pattern(r"^(?:이|해당|위|그)\s*(?:인과\s*관계|관계|현상|원인|기전|분석)")


def _clauses(text: str) -> list[str]:
    # Line breaks can separate a subject from its predicate in real notes.
    # A question mark inside '원가 문제? 답변을 기다린다' expresses doubt,
    # rather than a separate event whose pending state should be discarded.
    text = re.sub(r"[\r\n?]+", " ", text)
    return [part.strip() for part in re.split(r"[.!;]|하지만|그러나|다만|반면|지만", text) if part.strip()]


def _active_request(question: str) -> str:
    """Keep requested clauses, not explicitly excluded comparison subjects.

    This only recognizes corrective instructions. A factual negative such as
    '검증한 기록이 아니라는 메모' remains intact and is handled as evidence.
    """
    active: list[str] = []
    commands = re.sub(
        r"((?:찾(?:아주)?|보여주|가져오|읽(?:어주)?|포함하|참조하|인용하|정리하)(?:고|되))\s*",
        r"\1;", question)
    # A comma after a completed action can separate two instructions. A
    # comma between objects cannot: the final 'do not cite' applies to the
    # entire object list, including the objects before its last comma.
    commands = re.sub(r"(" + _FINISHED_REQUEST_ACTION + r")\s*[,，]\s*", r"\1;", commands)
    for clause in re.split(r"[.!?;\n]", commands):
        corrected = re.split(r"말고|아니라(?![는고])|배제하고|제외하고|빼고", clause)
        target = corrected[-1].strip()
        if not target:
            continue
        # An imperative such as '반려 메모는 근거로 쓰지 말라' describes
        # excluded evidence, not another requested topic. Its object may be
        # a comma-separated list; retain none of that list as positive topics.
        if _PROHIBITED_EVIDENCE_ACTION.search(target):
            continue
        elif not re.search(r"(?:제외|배제|빼)(?:해\s*줘|해\s*주세요|줘|주세요|하자|하고\s*싶)", target):
            active.append(target)
    return ". ".join(active)


def _requested_topics(question: str) -> list[re.Pattern[str]]:
    topics = []
    if _COST.search(question):
        topics.append(_COST)
    # A scalar context such as '에너지가 높은 후보의 비용 메모' does not
    # request an energy reason. Otherwise a named metric in a note request is
    # topical, including a joint collection of cost and performance notes.
    metrics = [metric for metric in _METRICS if metric.search(question)]
    for metric in metrics:
        local = next((clause for clause in _clauses(question) if metric.search(clause)), question)
        match = metric.search(local)
        assert match is not None
        after_metric = local[match.end():]
        scalar_context = bool(_COST.search(local) and re.match(
            r"(?:가|이|는|은)?\s*(?:높은|높고|낮은|[0-9][0-9.]*)[^.!?\n]{0,12}(?:후보|조건)", after_metric))
        if not scalar_context or _SHORTAGE.search(local):
            topics.append(_PERFORMANCE_EVIDENCE if metric is _PERFORMANCE else metric)
    if _PHYSICS.search(question):
        topics.append(_PHYSICS)
    topics.extend(topic for topic in _FACT_TOPICS if topic.search(question))
    return topics


def _directions(text: str, anchor: re.Pattern[str]) -> set[str]:
    directions = set()
    for match in _anchor_mentions(text, anchor):
        tail = text[match.end():match.end() + 24]
        following = [other.search(tail) for other in _CAUSAL_ANCHORS if other is not anchor]
        boundaries = [found.start() for found in following if found]
        if boundaries:
            tail = tail[:min(boundaries)]
        if _UP.search(tail):
            directions.add("UP")
        if _DOWN.search(tail):
            directions.add("DOWN")
    return directions


def _same_causal_relation(question: str, clause: str) -> bool:
    anchors = _relation_anchors(question)
    if not all(_anchor_mentions(clause, anchor) for anchor in anchors):
        return False
    for anchor in anchors:
        required = _directions(question, anchor)
        if required and not required.issubset(_directions(clause, anchor)):
            return False
    requested_roles = _causal_roles(question, anchors)
    if requested_roles and not requested_roles.issubset(_causal_roles(clause, anchors)):
        return False
    return True


def _causal_roles(text: str, anchors: list[re.Pattern[str]]) -> set[tuple[int, int]]:
    """Preserve explicit cause/effect direction, not just matching anchor sets."""
    mentions = sorted((match.start(), match.end(), index)
                      for index, anchor in enumerate(anchors) for match in _anchor_mentions(text, anchor))
    roles = set()
    for left, right in zip(mentions, mentions[1:]):
        if left[2] == right[2]:
            continue
        between = text[left[1]:right[0]]
        after = text[right[1]:right[1] + 28]
        if re.search(r"때문|으로\s*인해|로\s*인하여|영향으로|[-=]+>|→", between):
            roles.add((left[2], right[2]))
        elif re.search(r"때문", after):
            roles.add((right[2], left[2]))
        elif re.search(r"원인(?:은|이)", between):
            roles.add((right[2], left[2]))
        elif re.search(r"의\s*원인", after):
            roles.add((left[2], right[2]))
        elif re.search(r"원인(?:은|이|으로)", after):
            roles.add((right[2], left[2]))
        elif re.search(r"일으|유발|초래", after):
            # Korean may place the object before the subject. An explicit
            # object particle on the first anchor reverses that surface order.
            if re.search(r"(?:을|를)\s*$", between):
                roles.add((right[2], left[2]))
            else:
                roles.add((left[2], right[2]))
    return roles


def _relation_anchors(question: str) -> list[re.Pattern[str]]:
    return [anchor for anchor in _CAUSAL_ANCHORS if _anchor_mentions(question, anchor)]


def _anchor_mentions(text: str, anchor: re.Pattern[str]) -> list[re.Match[str]]:
    # '이온 에너지 분포 폭' and 'IED 폭' name the same quantity. Do not
    # accidentally require a second, independent mean-energy statement.
    mentions = list(anchor.finditer(text))
    if anchor is _ENERGY:
        width_spans = [match.span() for match in _CAUSAL_ANCHORS[1].finditer(text)]
        mentions = [match for match in mentions if not any(
            start <= match.start() and match.end() <= end for start, end in width_spans)]
    return mentions


def _causal_request(question: str) -> bool:
    if _TEXT_QUERY.search(question):
        return False
    return bool(_PHYSICS.search(question)
                or (_CAUSE_ANALYSIS.search(question) and _PROOF.search(question))
                or (_CAUSAL_QUESTION.search(question) and _PROOF_CAPABILITY.search(question)))


def _physics_support(question: str, clauses: list[str]) -> bool:
    """Match proof state inside physical-cause clauses, not other sentences."""
    units: list[str] = []
    for clause in clauses:
        # Permit an explicitly linked following proof sentence, without using
        # a completion statement about an unrelated quotation/price review.
        if units and _PROOF_COREFERENCE.search(clause):
            units[-1] += ". " + clause
        else:
            units.append(clause)
    anchors = _relation_anchors(question)
    relevant = [clause for clause in units if _PHYSICS.search(clause)
                or (len(anchors) >= 2 and _CAUSAL_LINK.search(clause)
                    and all(_anchor_mentions(clause, anchor) for anchor in anchors))]
    neutral = bool(_NEUTRAL_PROOF.search(question) or _PROOF_CAPABILITY.search(question))
    if _PROOF_LIMITS.search(question) or _PENDING.search(question) or neutral:
        relevant.extend(clause for clause in units if _CAUSE_ANALYSIS.search(clause) and clause not in relevant)
    relevant = [clause for clause in relevant if _same_causal_relation(question, clause)]
    if not relevant:
        return False
    if not _PROOF.search(question) or neutral:
        return True
    if _PROOF_NEGATIVE.search(question):
        return any(_PROOF_NEGATIVE.search(clause) for clause in relevant)
    if _PENDING.search(question):
        return any(_PENDING.search(clause) for clause in relevant)
    if _PROOF_LIMITS.search(question) and not _PROOF_COMPLETED.search(question):
        return any(_PROOF_NEGATIVE.search(clause) or _PENDING.search(clause) for clause in relevant)
    completed = _VERIFICATION_COMPLETED if _VERIFICATION.search(question) else _PROOF_COMPLETED
    return any(completed.search(clause)
               and not _PROOF_NEGATIVE.search(clause) and not _PENDING.search(clause)
               for clause in relevant)


def supports_requested_evidence(question: str, text: str, *, decision: str | None = None) -> bool:
    """Whether the note supports the request's explicit topic/evidence state.

    Run ownership, version scope, source integrity, and immutable policy counts
    are checked elsewhere. Multiple requested topics are a union: a collection
    may legitimately need different records for its separate requested reasons.
    The optional decision argument is accepted for the shared guard interface;
    this module never replaces a stored decision with one inferred from prose.
    """
    if _TEXT_QUERY.search(question):
        return True
    question = _active_request(question)
    if not question:
        return False
    topics = _requested_topics(question)
    clauses = _clauses(text)
    causal_request = _causal_request(question)
    other_match = any(topic.search(text) for topic in topics if topic is not _PHYSICS)
    if causal_request:
        causal_match = _physics_support(question, clauses)
        alternatives = bool(_ALTERNATIVES.search(question) and not _CONJUNCTION.search(question))
        # Separate requested branches can be supported by different records. A
        # cost-only record is not required to prove an alternative physics claim.
        if not causal_match and not (alternatives and other_match):
            return False
        if _CONJUNCTION.search(question) and any(topic is not _PHYSICS for topic in topics) and not other_match:
            return False
    elif topics and not other_match:
        return False
    cost_only = len(topics) == 1 and topics[0] is _COST
    if not cost_only:
        return True
    if _MIXED.search(question):
        requested = {state for state, words in _DECISION_WORDS.items() if words.search(question)}
        # A rejection-to-adoption history is a collection of two states, not a
        # request for a third HOLD event merely sharing the cost vocabulary.
        # Explicit prose takes precedence because a comparison quote may refer
        # to a different candidate than the record's stored decision does.
        if len(requested) > 1:
            stated = {state for state, words in _DECISION_WORDS.items() if words.search(text)}
            if stated and not (stated & requested):
                return False
            if not stated and decision is not None and decision not in requested:
                return False
        return True
    # Cost polarity is intentionally left to constraints.py. Applying a second
    # whole-query negation rule here confuses 'not this candidate', 'not a count',
    # and 'exclude pending notes' with a claim that cost itself is absent.
    return True
