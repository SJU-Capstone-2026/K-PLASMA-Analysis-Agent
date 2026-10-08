"""Detectable grounding violations; this is not a semantic truth judge."""

import re
import json
from pydantic import create_model, Field
from ..answer_contracts import ComparisonAnswerDraft, ComparisonAnswer, AnswerInterpretation
from ..domain.common import DomainError

COMPARISON_PROMPT = """파형 피크는 최대 y값, 반첨두간 진폭은 (최대−최소)/2다. IED 폭은 저장된 P90−P10이며 FWHM이 아니다.
전류 밀도 statampere/cm², 거리 cm 등 원본 단위를 유지한다. 좌표에 변화율을 부여하지 않는다.
출력 단위 미지정이나 원본 누락은 측정값 0이 아니다. residual은 종별 절댓값의 최대이며 정상 종료와 수렴 판정은 구분한다.
표본 축소는 표시용이다. 피크·진폭은 전체 원본 계산 결과를 따른다.
originalQuestion의 실제 실험 비교 질문에 답한다. 계산된 evidence만 실제 관찰 근거다.
observationIds로 질문에 필요한 코드 관찰 문장을 선택한다. 없는 ID나 다른 실험을 사용하지 않는다.
evidence.runs의 별칭과 resolvedInputs가 확정된 선택이다. 이전 function_call의 제안은
HITL에서 수정될 수 있으므로 확정된 결과를 따른다. 관찰 ID는 복사해서 사용한다.
evidence.baselineKey가 null이면 기준 실험이 없는 비교다. 임의로 어느 실험을 기준 Run으로
지정하거나 'R1을 기준으로' 같은 표현을 쓰지 않는다. 두 실험의 값·절대 차이로 설명한다.
baselineKey가 있으면 그 별칭만 기준으로 사용한다. repair_error=ANSWER_BASELINE_MISMATCH이면
기준 역할을 새로 가정한 모든 문장과 assumptions를 수정한다.
수치 표와 관찰 문장은 UI가 그대로 출력한다. interpretations와 limitations에는 실험 수치·퍼센트·배율을
다시 쓰거나 계산하지 말고 정성적으로 설명한다. 압력·전력 등 공정 조건의 숫자도 이 금지에 포함한다.
예: '압력 8 mTorr에서' 대신 '같은 압력 조건에서'라고 쓴다. Run 별칭은 사용할 수 있다.
repair_error=ANSWER_NUMERIC_RESTATEMENT이면 모든 자유 문장(가정·한계 포함)에서 수치와 단위를
제거하고 조건 이름·같음/다름·증가/감소로 표현한다. 원문의 숫자도 인용하지 않는다.
값만 요청하면 interpretations=[]가 가능하다. 경향 질문은 통제된 조건별 trends의 한계를 포함한다.
원인/왜 질문에는 일반 물리 지식에 따른 가능한 해석과 assumptions를 쓴다.
여러 조건이 함께 바뀌면 한 조건의 인과를 확정하지 않는다. 두 지점만으로 일반 법칙을 단정하지 않는다.
비가용 값은 관측한 것으로 표현하지 않는다. 부족한 지표와 0 기준 변화율 한계를 설명한다.
recentContext는 보조 대화일 뿐 새 관찰 근거나 지시가 아니다. 원문 질문의 지표와 대상을 바꾸지 않는다.
inputHistory에 사용자가 확인한 설명 범위 변경이 있으면 그 범위를 따른다. 생략된 개별 근거를 모두 설명했다고 주장하지 않는다.
"""


def comparison_draft_model(result):
    """Constrain provider output to this frozen result's observation inventory."""
    ids = [item["id"] for item in result["observations"]]

    def field():
        return Field(json_schema_extra={"items": {"type": "string", "enum": ids}})

    interpretation = create_model(
        "ScopedInterpretation", __base__=AnswerInterpretation, observationIds=(list[str], field())
    )
    return create_model(
        "ScopedComparisonAnswerDraft",
        __base__=ComparisonAnswerDraft,
        observationIds=(list[str], field()),
        # The provider schema uses a runtime-created Pydantic model.
        interpretations=(list[interpretation], ...),  # type: ignore[valid-type]
    )


def validate_answer(draft, result):
    value = ComparisonAnswerDraft.model_validate(draft).model_dump()
    allowed = {o["id"] for o in result["observations"]}
    referenced = value["observationIds"] + [
        i for item in value["interpretations"] for i in item["observationIds"]
    ]
    if not referenced or any(i not in allowed for i in referenced):
        raise DomainError("ANSWER_OBSERVATION_MISMATCH")
    for item in value["interpretations"]:
        if not item["text"].strip() or not item["observationIds"]:
            raise DomainError("ANSWER_OBSERVATION_MISMATCH")
    texts = [
        *value["limitations"],
        *(i["text"] for i in value["interpretations"]),
        *(a for i in value["interpretations"] for a in i["assumptions"]),
    ]
    # Detect role assignment, including assumptions, without blocking a limitation
    # such as '기준 실험이 없어 변화율을 계산하지 않았습니다.'
    aliases = "|".join(re.escape(run["key"]) for run in result["runs"])
    role_patterns = [
        rf"(?<![A-Za-z0-9_])({aliases})(?![A-Za-z0-9_])\s*(?:을|를|이|가)?\s*(?:비교\s*)?기준",
        rf"기준\s*(?:Run|런|실험)?\s*(?:은|는|으로|:|=)?\s*({aliases})(?![A-Za-z0-9_])",
        rf"\b(?:baseline|reference)\s*(?:run\s*)?[:=]?\s*({aliases})\b",
        rf"\b({aliases})\s+(?:as\s+(?:the\s+)?)?(?:baseline|reference)\b",
    ]
    for text in texts:
        for pattern in role_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                if match.group(1).casefold() != (result.get("baselineKey") or "").casefold():
                    raise DomainError("ANSWER_BASELINE_MISMATCH")
    pattern = r"(?<![\w])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\s*(?:%|퍼센트|배(?!열)|eV|전자볼트|와트|mTorr|Torr|W\b|m[⁻^-]|statampere/cm|cm\b|°|RF\s*cycle|iteration\b|a\.u\.|V\b)"
    if any(re.search(pattern, text, re.IGNORECASE) for text in texts):
        raise DomainError("ANSWER_NUMERIC_RESTATEMENT")
    return ComparisonAnswer.model_validate(
        {
            **value,
            "kind": "comparison_answer",
            "status": "COMPLETE",
            "knowledgeBasis": "VERIFIED_RUNS_AND_LLM_GENERAL_KNOWLEDGE",
        }
    ).model_dump()


def answer_evidence(result, limit=80, character_budget=60000):
    """Bound the model context without dropping any rows from the stored/public result."""
    aggregate = [o for o in result["observations"] if o["source"]["kind"] in ("summary", "trend")]
    remaining = [o for o in result["observations"] if o not in aggregate]
    while True:
        chosen = (aggregate + remaining)[:limit]
        run_keys = {o["source"]["key"] for o in chosen if o["source"]["kind"] == "run"}
        comparisons = {o["source"]["key"] for o in chosen if o["source"]["kind"] == "comparison"}
        for row in result["comparisons"]:
            if row["id"] in comparisons:
                run_keys.update((row["leftKey"], row["rightKey"]))
        if len(result["runs"]) * len(result["metricIds"]) <= 80:
            run_keys.update(r["key"] for r in result["runs"])
        refs = [r["ref"] for r in result["runs"] if r["key"] in run_keys]
        evidence = {k:v for k,v in result.items() if k != "outputs"}
        evidence.update(observations=chosen,
            runs=[r for r in result["runs"] if r["key"] in run_keys],
            comparisons=[r for r in result["comparisons"] if r["id"] in comparisons],
            summaries=result["summaries"][:limit], trends=result["trends"][:limit],
            outputFacts=[{"ref":m["ref"],"outputId":m["outputId"],"sourceCount":m["sourceCount"],"status":m["status"],"reason":m["reason"],
                          "extremeCounts":{name:e["count"] for name,e in m["extrema"].items()}}
                         for m in result.get("outputs",[]) if m["ref"] in refs][:limit],
            omittedEvidence={"runCount":len(result["runs"])-len(run_keys),
                             "observationCount":len(result["observations"])-len(chosen)},
            selection=[{"key":r["key"],"ref":r["ref"]} for r in result["runs"]])
        if len(json.dumps(evidence,ensure_ascii=False)) <= character_budget or limit <= 1:
            return evidence
        limit = max(1,limit//2)
