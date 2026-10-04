"""Qualitative evidence and validated explanation contracts, never numerical inference."""

import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ExplanationError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterpretationText(StrictModel):
    text: str = Field(min_length=1, max_length=600)
    observation_refs: list[str] = Field(min_length=1, max_length=6)
    assumptions: list[str] = Field(max_length=3)


class ChangeDraft(StrictModel):
    status: Literal["answered", "insufficient_knowledge"]
    interpretations: list[InterpretationText] = Field(max_length=3)
    limitations: list[str] = Field(min_length=1, max_length=5)
    suggested_checks: list[str] = Field(max_length=3)


class ConceptSection(StrictModel):
    topic_refs: list[str] = Field(min_length=1, max_length=2)
    text: str = Field(min_length=1, max_length=600)


class ConceptDraft(StrictModel):
    status: Literal["answered", "insufficient_knowledge"]
    sections: list[ConceptSection] = Field(max_length=5)
    limitations: list[str] = Field(min_length=1, max_length=5)


def build_change_evidence(comparison):
    observations = []
    for group, key, prefix in [("conditions", "field", "condition"), ("metrics", "metric", "metric")]:
        for row in comparison[group]:
            delta = row.get("delta")
            available = delta is not None
            if not available:
                direction = "unavailable"
            elif delta > 0:
                direction = "increased"
            elif delta < 0:
                direction = "decreased"
            else:
                direction = "unchanged"
            observations.append(
                {
                    "id": f"{prefix}_{row[key]}",
                    "subject": row[key],
                    "direction": direction,
                    "available": available,
                }
            )
    conditions = [x for x in observations if x["id"].startswith("condition_")]
    changed = sum(x["direction"] in ("increased", "decreased") for x in conditions)
    incomplete = any(not x["available"] for x in conditions)
    if incomplete:
        mode = "conditions_incomplete"
    elif changed > 1:
        mode = "multiple_conditions_changed"
    elif changed:
        mode = "single_condition_changed"
    else:
        mode = "no_condition_changed"
    limits = ["NO_CAUSAL_PROOF"]
    if mode != "single_condition_changed":
        limits.append(mode.upper())
    if any(not x["available"] for x in observations):
        limits.append("MISSING_DATA")
    return {
        "kind": "change_evidence",
        "scope": "paired_runs",
        "comparisonMode": mode,
        "observations": observations,
        "limitations": limits,
    }


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in ("observation_refs", "topic_refs", "status"):
                yield from _texts(item)


# These guards catch explicit contradictions, not arbitrary scientific errors. They
# deliberately leave conditional/general statements to the prompt and human eval.
_SUBJECTS = {
    "pressure": r"(?:압력|pressure)",
    "sourcePower": r"(?:소스\s*전력|source\s*power|sourcePower)",
    "biasPower": r"(?:바이어스\s*전력|bias\s*power|biasPower)",
    "ionFlux": r"(?:이온\s*플[럭럿]스|플[럭럿]스|ion\s*flux|ionFlux)",
    "meanIonEnergy": r"(?:평균\s*이온\s*에너지|평균\s*에너지|mean\s*ion\s*energy|meanIonEnergy)",
    "iedWidth": r"(?:IED\s*(?:폭|width)|이온\s*에너지\s*분포\s*폭|iedWidth)",
}
_TRENDS = {
    "increased": r"(?:증가|상승|증대)(?:했|하였|한|함|는|가|로)|(?:높아|커|넓어)(?:졌|진)|늘어(?:났|난)|increased\b|rose\b",
    "decreased": r"(?:감소|하락|저하)(?:했|하였|한|함|는|가|로)|(?:낮아|작아|좁아)(?:졌|진)|줄어(?:들었|든)|decreased\b|fell\b",
    "unchanged": r"변하지\s*않(?:았|은)|변화가\s*없(?:었|는|습니다)|동일(?:했|한|합니다)|유지(?:됐|된)|(?:is |was )?unchanged\b",
}


def _check_directions(text, observations):
    for observation in observations:
        subject = _SUBJECTS.get(observation["subject"])
        if not observation["available"] or subject is None:
            continue
        for match in re.finditer(subject, text, re.I):
            # An explicit hypothetical antecedent is not a claim about this pair.
            prefix = re.split(r"[.!?。;]", text[: match.start()])[-1]
            if re.search(r"\bif\b|만약", prefix, re.I):
                continue
            tail = text[match.end() :]
            for direction, pattern in _TRENDS.items():
                claim = re.match(
                    r"\s*(?:의|은|는|이|가|has|have|had|was|is)?\s*(?:" + pattern + r")", tail, re.I
                )
                if claim and direction != observation["direction"]:
                    following = tail[claim.end() : claim.end() + 16]
                    if re.match(r"\s*(?:경우|때|조건|것이\s*아니)", following):
                        continue
                    raise ExplanationError("EXPLANATION_DIRECTION_CONTRADICTION")


def _certain_causality(text):
    for clause in re.split(r"[.!?。;]", text):
        # Keep a statement explicitly denying certainty, even if it mentions it.
        if re.search(
            r"(?:확정|단정|입증|확실|분명|명백).{0,25}(?:할\s*수(?:는)?\s*없|하기\s*어렵|하지\s*않|볼\s*수\s*없|아닙)",
            clause,
        ):
            continue
        if re.search(
            r"원인으로\s*확정|때문임이\s*입증|반드시\s*(?:증가|감소)|유일한?\s*원인|"
            r"(?:확실|분명|명백|틀림없).{0,24}(?:원인|때문|유발|초래)|"
            r"(?:원인|때문).{0,24}(?:확실|분명|명백|단정|입증|확정)|"
            r"\b(?:definitely|certainly|proven|sole)\b.{0,30}\b(?:cause|caused|because)\b|"
            r"\bcause\b.{0,20}\b(?:definitely|certainly|proven)\b",
            clause,
            re.I,
        ):
            return True
    return False


def _unique(values):
    keys = [re.sub(r"\s+", " ", value).strip().casefold() for value in values]
    if len(keys) != len(set(keys)):
        raise ExplanationError("EXPLANATION_DUPLICATE")


def validate_explanation(kind, draft, evidence):
    try:
        model = ChangeDraft if kind == "explain_change" else ConceptDraft
        data = model.model_validate(draft).model_dump()
    except ValueError as error:
        raise ExplanationError("EXPLANATION_SCHEMA_INVALID") from error
    for text in _texts(data):
        if len(text) > 600 or any(c.isnumeric() for c in text):
            raise ExplanationError("EXPLANATION_NUMERIC_TEXT")
        if re.search(
            r"https?://|www\.|doi:|\[\d|(?:두|세|네|몇|수십|수백)\s*배|[0-9%％]|논문에 따르면|문헌에 따르면",
            text,
            re.I,
        ):
            raise ExplanationError("EXPLANATION_UNVERIFIED_CLAIM")
        if kind == "explain_change" and _certain_causality(text):
            raise ExplanationError("EXPLANATION_CAUSAL_CLAIM")
        if kind == "explain_concept" and re.search(
            r"change_evidence|(?:제공된|주어진|위의)\s*(?:관찰|측정|실험\s*결과|수치|데이터)|"
            r"(?:이번|해당|선택한|기준)\s*Run|(?:provided|given|these)\s+(?:observations?|measurements?|data)",
            text, re.I,
        ):
            raise ExplanationError("EXPLANATION_FABRICATED_OBSERVATION")
    if kind == "explain_change":
        allowed = {o["id"] for o in evidence["observations"] if o["available"]}
        if any(not set(i["observation_refs"]) <= allowed for i in data["interpretations"]):
            raise ExplanationError("EXPLANATION_UNKNOWN_EVIDENCE")
        entries = data["interpretations"]
        for entry in entries:
            _unique(entry["observation_refs"])
            _unique(entry["assumptions"])
            _check_directions(entry["text"], evidence["observations"])
        if data["status"] == "insufficient_knowledge" and data["suggested_checks"]:
            raise ExplanationError("EXPLANATION_STATUS_MISMATCH")
    else:
        allowed = set(evidence["topics"])
        seen = {ref for section in data["sections"] for ref in section["topic_refs"]}
        if not seen <= allowed or (data["status"] == "answered" and seen != allowed):
            raise ExplanationError("EXPLANATION_TOPIC_MISMATCH")
        entries = data["sections"]
        for entry in entries:
            _unique(entry["topic_refs"])
    _unique(entry["text"] for entry in entries)
    _unique(data["limitations"])
    if kind == "explain_change":
        _unique(data["suggested_checks"])
    if (data["status"] == "answered" and not entries) or (
        data["status"] == "insufficient_knowledge" and entries
    ):
        raise ExplanationError("EXPLANATION_STATUS_MISMATCH")
    return data
