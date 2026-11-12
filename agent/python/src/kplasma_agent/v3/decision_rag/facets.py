"""Explicit conjunctions over record-local facts for large candidate pools.

The matcher uses source spans, never corpus labels or a requested result count.
Unknown or unmentioned required facts do not satisfy a conjunct. Scope and
immutable citation validation remain the caller's responsibility.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

FACET_POLICY = "large-pool-facets-1"

_PERF = r"성능|기능|품질|사용성|사용\s*편의|사용\s*가능|기술\s*검토|목적"
_COST = r"비용|지출|원가|가격|경제성|금액|돈|재정|운영비|계약료|경비|단가|견적|예산"
_TOTAL_COST = r"총\s*(?:지출|비용)|전체\s*(?:지출|비용)|지출|비용|돈|경비|운영비"
_APPROVAL = r"승인|결재|서명|도장|허용\s*절차|내부\s*허용"
_PHYSICAL = r"물리|실물|공간|구성|배치|구조|조립|설계|도면|실현|구현|가능성|성립"
_UNKNOWN = r"미상|미정|불명|미확인|불확실|추정|모르|모른|알\s*수\s*없|정리하지\s*못|정리할\s*수\s*없|확인하지\s*못|확인[^.!?]{0,8}필요|확정[^.!?]{0,8}(?:못|수\s*없)|계산하지\s*못|비어|끝나지\s*않|산정[^.!?]{0,8}못|입증할\s*수\s*없|결론[^.!?]{0,12}수\s*없|(?:부담|미달|적합|충분)[^.!?]{0,8}(?:일지도|할지도|가능성)"
_SHORTAGE = r"미달|부족|나빠|열세|결함|불합격|부적합|모자|충족하지\s*못|못\s*미"
_NEGATED_CLAIM = re.compile(r"아니다|아닌|아니라고|아니라는|뜻[^.!?]{0,12}않|확정[^.!?]{0,12}않|"
                            r"(?:과|와)(?:는|도)?\s*(?:다르|구분|구별)|의미[^.!?]{0,12}않|기록하지\s*않|표현하지\s*않|이유로\s*삼지|"
                            r"(?:근거|사유)[^.!?]{0,12}(?:적지\s*않|삼지\s*않)|판단[^.!?]{0,12}하지\s*않")


@dataclass(frozen=True)
class FacetRequirement:
    name: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class FacetRequest:
    requirements: tuple[FacetRequirement, ...]


@dataclass
class FacetSelection:
    documents: list[dict]
    required_facets: tuple[str, ...]
    diagnostics: dict


def _rx(value: str) -> re.Pattern[str]:
    return re.compile(value, re.I)


def _bound(topic: str, predicate: str, *, exclude: str = "", distance: int = 50) -> re.Pattern[str]:
    gap = rf"(?:(?!(?:{exclude}))[^.!?;]){{0,{distance}}}" if exclude else rf"[^.!?;]{{0,{distance}}}"
    return _rx(rf"(?:{topic}){gap}(?:{predicate})")


_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("performance", "ADEQUATE", _bound(_PERF, r"충족|충분|적합|통과|문제[^.!?]{0,6}없|결격[^.!?]{0,6}없|이상[^.!?]{0,6}없|확인된\s*전제", exclude=_COST)),
    ("performance", "ADEQUATE", _bound(r"기능|사용\s*성능|사용\s*가능", r"검토[^.!?]{0,28}(?:마쳤|끝|완료)|여부[^.!?]{0,12}확인", exclude=_COST)),
    ("performance", "DEFICIT", _bound(_PERF, _SHORTAGE, exclude=_COST)),
    ("performance", "DEFICIT", _rx(r"(?:구분|읽기|식별)[^.!?;]{0,20}(?:어렵|어려|못)[^.!?;]{0,20}(?:기능|성능)")),
    ("performance", "MAINTAINED", _bound(_PERF, r"같|그대로|유지|동일|변화[^.!?]{0,6}없", exclude=_COST)),
    ("cost", "BURDEN", _bound(_COST, r"부담|과중|높|비싸|초과|넘|감당[^.!?]{0,12}어려|허용\s*범위[^.!?]{0,8}벗어", exclude=_PERF)),
    ("cost", "UNKNOWN", _bound(_COST, _UNKNOWN, exclude=_PERF)),
    ("cost", "UNKNOWN", _rx(r"아직\s*모르[^.!?;]{0,12}(?:경제성|비용)|알려지지\s*않은\s*(?:비용|가격)")),
    ("cost", "NOT_COMPARED", _bound(r"가격|비용|지출|경제성", r"비교[^.!?]{0,18}(?:시작하지\s*못|하지\s*못|못|비어|끝나지\s*않)", exclude=_PERF)),
    ("cost", "SAVING_CONFIRMED", _bound(_TOTAL_COST, r"(?:줄|낮|절약|절감|감소)[^.!?]{0,35}(?:확인|비교|마쳤|끝|근거|결정)|(?:확인|비교)[^.!?]{0,25}(?:줄|낮|절약|절감|감소)", exclude=_PERF)),
    ("cost_reason", "SAVING", _bound(r"이유|근거|때문|결정", rf"(?:{_TOTAL_COST})[^.!?]{{0,30}}(?:줄|낮|절약|절감|적은)", exclude=_PERF)),
    ("cost_reason", "SAVING", _bound(r"절약|절감|적은\s*비용|비용[^.!?]{0,8}줄", r"근거|이유|때문|결정", exclude=_PERF)),
    ("physical_feasibility", "UNPROVEN", _bound(_PHYSICAL, r"입증[^.!?]{0,20}(?:없|못|부족|한계)|근거[^.!?]{0,20}(?:없|못|부족)|결론[^.!?]{0,20}수\s*없|가능\s*여부[^.!?]{0,18}수\s*없|판단[^.!?]{0,12}남겨")),
    ("physical_feasibility", "UNPROVEN", _bound(r"입증\s*자료|증거|실물\s*근거", r"부족|한계|확보되기\s*전", exclude=_PERF)),
    ("physical_feasibility", "IMPOSSIBLE", _bound(_PHYSICAL, r"성립하지\s*않|불가능|조립할\s*수\s*없|구현할\s*수\s*없")),
    ("internal_approval", "PENDING", _bound(_APPROVAL, r"기다|미완료|아직[^.!?]{0,15}(?:남|받지|나지)|남아|남았|만\s*남|나지\s*않|받지\s*않|서명\s*전|결재\s*전")),
    ("internal_approval", "PENDING", _bound(r"남은|아직\s*받아야", _APPROVAL)),
    ("internal_approval", "COMPLETE", _bound(_APPROVAL, r"끝났|끝나|완료됐|완료되었|완료한|마쳤|마친|받았|받아\s*둔|받아\s*두|받았다")),
    ("remaining_condition", "ONLY_INTERNAL_APPROVAL", _bound(_APPROVAL, r"만\s*(?:남|기다|미완료)|하나뿐|유일|하나만|것만을\s*이유")),
    ("conditional_adoption", "YES", _rx(r"조건부\s*채택|조건[^.!?;]{0,12}채택|채택[^.!?;]{0,45}조건|승인[^.!?;]{0,20}전제로|결재가\s*나야|서명\s*전에는\s*배포하지")),
    ("external_approval", "COMPLETE", _bound(r"외부|위원회", r"(?:승인)[^.!?]{0,20}(?:완료|받았|마쳤|끝)|최종\s*승인도\s*받")),
    ("repeated_measurement", "VERIFIED", _bound(r"반복\s*(?:계측|측정)|반복\s*검증", r"(?:검증|확인)[^.!?]{0,15}(?:끝|완료|마쳤)|검증도\s*모두\s*끝|마쳤|완료")),
    ("expansion", "UNRESTRICTED", _rx(r"(?:아무\s*)?제한\s*없이[^.!?;]{0,25}(?:확대|운영)|(?:전면|전체)\s*(?:운영|적용)[^.!?;]{0,20}확대")),
    ("reuse_container", "YES", _bound(r"용기|보관함", r"재사용|다시\s*(?:쓰|투입|사용)|돌려쓰|회수해|손질|정비")),
    ("reuse_container", "YES", _bound(r"재사용|돌려쓰|다시\s*쓰|버리던|폐기\s*대상", r"용기|보관함")),
    ("technical_review", "COMPLETE", _bound(_PERF + r"|수행\s*가능성|구현\s*가능성", r"적합|충분|확인|끝|완료|통과|마쳤|정리", exclude=_COST)),
    ("technical_review", "COMPLETE", _rx(r"(?:기술|성능|기능|수행\s*가능성)[^.!?;]{0,15}(?:과|와|및)[^.!?;]{0,8}(?:비용|지출)[^.!?;]{0,20}(?:모두|다)[^.!?;]{0,10}(?:정리|완료|확인|끝)")),
    ("cost_review", "COMPLETE", _bound(_COST, r"적합|정리|확인|알려|감당\s*가능|해소|끝|완료|마무리|비교[^.!?]{0,12}마쳤", exclude=_PERF)),
)
_COST_UNCERTAIN = _bound(_COST, _UNKNOWN, exclude=_PERF + "|" + _APPROVAL)
_PERF_UNCERTAIN = _bound(_PERF, _UNKNOWN, exclude=_COST + "|" + _APPROVAL)


def _claims(text: str) -> list[str]:
    claims = []
    for sentence in re.split(r"[.!?;\n]", text):
        for contrast in re.split(r"하지만|그러나|다만|반면|지만|으나|했으나", sentence):
            parts = re.split(r"아니라|아니며|아니고", contrast)
            # Clauses to the left of a corrective negation are denials, not
            # positive facts. Their affirmative replacement is the final part.
            claim = parts[-1].strip()
            if claim and not _NEGATED_CLAIM.search(claim):
                claims.append(claim)
    return claims


def extract_document_facets(document: dict) -> dict[str, dict[str, tuple[str, ...]]]:
    """Extract typed values and exact source substrings; do not edit a record."""
    text = document.get("text", "")
    found: dict[str, dict[str, list[str]]] = {}
    role = document.get("citationRole", document.get("attribution"))
    decision = document.get("decision")
    if role not in {"REFERENCE_ONLY", "SHARED_UNASSIGNED"} and decision in {"ADOPT", "REJECT", "HOLD"}:
        found["decision"] = {decision: ["decision metadata"]}
    for claim in _claims(text):
        for name, value, pattern in _RULES:
            match = pattern.search(claim)
            if not match:
                continue
            if name == "cost" and value in {"BURDEN", "SAVING_CONFIRMED"} and _COST_UNCERTAIN.search(claim):
                continue
            if name == "performance" and value in {"ADEQUATE", "DEFICIT", "MAINTAINED"} and _PERF_UNCERTAIN.search(claim):
                continue
            if name == "cost_review" and value == "COMPLETE" and _COST_UNCERTAIN.search(claim):
                continue
            if name == "technical_review" and value == "COMPLETE" and _PERF_UNCERTAIN.search(claim):
                continue
            if name == "internal_approval" and re.search(r"외부|위원회", match.group()):
                continue
            if name == "cost" and value == "SAVING_CONFIRMED" and re.search(r"단가|개당|항목\s*하나", claim) and not re.search(r"총|전체", match.group()):
                continue
            found.setdefault(name, {}).setdefault(value, []).append(match.group())
    return {name: {value: tuple(spans) for value, spans in values.items()} for name, values in found.items()}


def _positive_request(question: str) -> str:
    clauses = []
    for clause in re.split(r"[.!?;\n]", question):
        if re.search(r"제외|빼\s*줘|빼\s*주세요|말고", clause):
            continue
        clauses.append(re.split(r"아니라|대신", clause)[-1])
    return ". ".join(clauses)


def parse_facet_request(question: str) -> FacetRequest | None:
    """Recognize explicit requirements; ordinary generic history uses fallback."""
    active = _positive_request(question)
    required: list[FacetRequirement] = []

    def add(name: str, value: str) -> None:
        item = FacetRequirement(name, (value,))
        if item not in required:
            required.append(item)

    states = []
    for state, words in (("REJECT", r"기각|반려|거절|탈락"), ("HOLD", r"유보|보류"), ("ADOPT", r"채택")):
        if re.search(words, active):
            states.append(state)
    if len(states) == 1:
        add("decision", states[0])
    elif len(states) > 1:
        if re.search(r"또는|혹은", active):
            required.append(FacetRequirement("decision", tuple(states)))
        else:
            return None
    if re.search(_PERF, active):
        if re.search(r"충족|문제[^.!?]{0,6}없|충분|결격[^.!?]{0,6}없|적합", active):
            add("performance", "ADEQUATE")
        if re.search(_SHORTAGE + r"|못\s*미", active):
            add("performance", "DEFICIT")
        if re.search(r"그대로|유지|같|동일", active):
            add("performance", "MAINTAINED")
    if re.search(_COST, active):
        if re.search(r"부담|과중|높|비싸|초과|감당[^.!?]{0,10}어려", active):
            add("cost", "BURDEN")
        if re.search(_UNKNOWN + r"|아직\s*몰라|유불리[^.!?]{0,10}모르", active):
            add("cost", "UNKNOWN")
        if re.search(r"비교[^.!?]{0,15}(?:못|하지|조차)|비교조차", active):
            add("cost", "NOT_COMPARED")
        if re.search(r"절약|절감|총지출[^.!?]{0,10}줄|돈[^.!?]{0,8}아끼", active) and not re.search(r"아직\s*(?:몰라|모르)|이득[^.!?]{0,10}모르", active):
            add("cost", "SAVING_CONFIRMED")
            if re.search(r"이유|근거|그\s*절약", active):
                add("cost_reason", "SAVING")
    if re.search(_PHYSICAL, active):
        if re.search(r"입증[^.!?]{0,15}(?:못|없)|가능[^.!?]{0,12}(?:입증|모르)|증거\s*한계|입증할\s*수\s*없", active):
            add("physical_feasibility", "UNPROVEN")
        if re.search(r"물리[^.!?]{0,15}불가능|성립하지\s*않|구현[^.!?]{0,8}불가능", active):
            add("physical_feasibility", "IMPOSSIBLE")
    if re.search(_APPROVAL, active):
        if re.search(r"남|기다|아직|받아야|미완료", active):
            add("internal_approval", "PENDING")
        if re.search(r"내부[^.!?]{0,18}(?:하나만|하나|만)|다른\s*미결\s*사항\s*없이|결재\s*하나만", active):
            add("remaining_condition", "ONLY_INTERNAL_APPROVAL")
        if "ADOPT" in states and re.search(r"조건|일단|전제로", active):
            add("conditional_adoption", "YES")
        if re.search(r"외부|위원회", active) and re.search(r"최종\s*승인|승인[^.!?]{0,12}(?:받|완료)", active):
            add("external_approval", "COMPLETE")
    if re.search(r"반복\s*(?:계측|측정|검증)", active):
        add("repeated_measurement", "VERIFIED")
    if re.search(r"제한\s*없이|무제한|전면\s*(?:확대|운영)", active):
        add("expansion", "UNRESTRICTED")
    if re.search(r"용기|보관함", active) and re.search(r"재사용|다시\s*쓰|버리던|손질|돌려쓰|재투입", active):
        add("reuse_container", "YES")
    if re.search(r"기술[^.!?]{0,20}검토[^.!?]{0,12}(?:끝|완료)|기술과\s*비용\s*검토", active):
        add("technical_review", "COMPLETE")
        add("cost_review", "COMPLETE")
    # A mere decision word cannot verify an otherwise unknown semantic request.
    # At least one explicit non-decision aspect must be recognized.
    if len(required) < 2 or not any(item.name != "decision" for item in required):
        return None
    return FacetRequest(tuple(required))


def select_by_facets(question: str, documents: list[dict]) -> FacetSelection | None:
    request = parse_facet_request(question)
    if request is None:
        return None
    selected, decisions = [], []
    required_names = tuple(item.name + "=" + "|".join(item.values) for item in request.requirements)
    for document in documents:
        facts = extract_document_facets(document)
        missing = [item.name + "=" + "|".join(item.values) for item in request.requirements
                   if not any(value in facts.get(item.name, {}) for value in item.values)]
        supported = not missing
        if supported:
            selected.append(document)
        decisions.append({"documentId": document.get("documentId"), "supported": supported,
                          "missingFacets": missing, "matchedSpans": {
                              item.name: {value: facts.get(item.name, {}).get(value, ()) for value in item.values}
                              for item in request.requirements}})
    return FacetSelection(selected, required_names, {"policy": FACET_POLICY, "assessments": decisions})
