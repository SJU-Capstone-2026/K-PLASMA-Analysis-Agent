"""Bounded Responses and Decisions calls for the v2 graph."""

from dataclasses import dataclass, replace
from typing import Literal
import json
import os

import httpx

from .. import tracing
from ..answer_stream import AnswerStreamProjector
from ..config import Settings
from ..metric_registry import UNITS
from ..model_client import ModelClient, ModelError, strict_schema
from .contracts import DataAnswerDraft, GeneralAnswerDraft, PlanDraft, ReviewAnswer, ReviewDecision
from .plan_review import CHOICES, PLAN_REVIEW_QUESTIONS, parse_plan_review, review_result

PLAN_INSTRUCTIONS = """원문과 확인된 문맥을 읽고 submit_plan을 정확히 한 번 제출한다.
조회·검색·비교를 코드가 순차 실행한다. 정성 해석은 답변 단계가 맡는다.
실험 결과의 경향·의미·이유 등 해석을 요청했으면 interpretation_requested를 true로 지정한다.
조회·정렬·수치 차이 계산·그래프 표시만 요청했거나 general_only이면 false다.
예: “RF 전류 파형과 최대·최소 차이를 보여줘”는 false, “전위 차이가 어디서 두드러지고 왜 그런지 설명해줘”는 true다.
원문의 조건·단위·정렬·엄격한 경계와 요구를 보존한다. 근거 없는 완화나 후보 제한을 추가하지 않는다.
후보 검색에서 명시한 수치 범위는 “가깝게”라고 표현해도 양끝을 포함하는 between 제약으로 적용한다.
예를 들어 “Ion Flux는 높게, Mean Ion Energy는 150–160 eV에 가깝게”는
meanIonEnergy between 150–160 eV와 ionFlux maximize다. 범위 밖 후보를 포함하지 않는다.
between 제약은 min과 max만 채우고 value는 반드시 null로 둔다.
eq·gt·gte·lt·lte 제약은 value만 채운다. “적어도 1”의 gte 경계값은 value에 둔다.
리터럴 source.quote에는 해당 수치와 명시된 단위가 들어 있는 원문 구절을 인용한다.
unit은 스키마의 단위 중 같은 배율의 표준 표기를 사용한다. 예: mtorr → mTorr, 와트 → W.
Torr를 mTorr로, m⁻²s⁻¹를 10¹⁸ m⁻²s⁻¹로 바꾸지 않는다. value도 원문 수치를 유지한다.
단위가 명시됐지만 지원되지 않으면 unsupported, 단위가 생략됐으면 null을 사용한다.
한 검색에 압력과 이온 플럭스처럼 조건이 여럿이면 constraints에 각 조건을 별도 항목으로 넣는다.
선택한 두 Run 모두보다 높은 값은 max 후 gt, 모두보다 낮은 값은 min 후 lt다.
비교마다 질문의 의미와 확인된 문맥으로 대상을 세 가지 중 하나로 정해 inputs.runs에 표현한다.
1. 검색 결과 전체: 조건으로 비교 집합을 지정하면 “모두”라는 단어가 없어도 전체 집합이다.
예: “플럭스 50 넘는 Run끼리 압력이 어떻게 달라?”는 ionFlux gt 50으로 reverse_search한 뒤 압력을 비교한다.
compare_runs는 검색 단계에 의존하고 inputs.runs에
{"kind":"result_ref","step_id":"search","field":"candidates","scope":{"kind":"candidate_group"}}을 사용한다.
요청하지 않은 확인 단계, 정렬 목표, 기준 Run, 개수 제한을 추가하지 않는다.
2. 이미 선택한 Run: 질문이 이미 선택한 대상을 가리키면 inputs.runs에 {"kind":"context_ref","key":"selected_runs"}를 사용한다.
문맥에 선택이 있어도 질문이 새 검색 결과를 비교하라고 하면 검색 결과를 사용한다.
3. 선택 필요: 일부 후보를 요구하지만 어느 Run인지 모르거나 전체와 일부 중 의도가 모호하면 await_input을 계획한다.
예: “플럭스 50 넘는 후보 찾아줘. 그중 괜찮은 것끼리 압력을 비교해줘”는 검색을 먼저 하고 비교 대상을 확인한다.
“그중 두 개”처럼 개수만 정해졌으면 기존에 선택한 Run이 있어도 어느 후보인지 확인한다. 임의로 두 개를 고르지 않는다.
어떤 검색 후보에서 고를지 알면 먼저 검색하고, await_input의 candidates를 검색의 candidates/candidate_group에 연결한다.
검색 다음에 이 선택이 필요하면 await_input을 조건 없이 실행한다. 후보가 부족한지는 실행 시 코드가 확인한다.
확인 단계의 confirmation은 run_selection, target_step_id는 후속 비교 단계 ID, field는 runs다.
선택 개수가 정확히 지정되면 inputs.selection_count에 정수를 넣는다. “두 개”면 2, “세 개”면 3이다.
정확한 선택 개수가 없거나 최소 개수만 요청하면 selection_count는 null이다.
selection_count는 비교 대상으로 고를 개수이며 검색 결과를 제한하는 값이 아니다.
compare_runs는 확인 단계에 의존하고 inputs.runs에
{"kind":"result_ref","step_id":"confirm","field":"selection","scope":{"kind":"scalar"}}을 사용한다.
확인 출력 이름은 selection이다. run_if로 확인을 조건부 실행하면 후속 비교에도 같은 조건을 둔다.
비교 대상 선택과 기준 Run 선택은 별개다. “기준 Run은 내가 고를게”라면 대상이 이미 정해졌어도 기준 선택 단계를 둔다.
예: “선택한 두 Run의 전위를 비교해줘. 기준 Run은 내가 고를게”는 confirmation이 baseline인 await_input을 추가한다.
이 단계의 inputs는 {"target_step_id":"compare","field":"baseline","selection_count":null,"candidates":null}이다.
compare의 inputs.runs는 그대로 비교 대상 출처를 가리킨다. 비교 대상도 선택해야 하면 먼저 run_selection을 계획한다.
기준 선택 단계가 있으면 compare의 inputs.baseline은 null로 두고, 코드는 기준 선택 결과를 연결한다.
사용자가 “R1을 기준으로”처럼 기준을 직접 지정했으면 그 Run의 확인된 문맥을 baseline에 참조한다.
순수 개념 설명이면 requirements와 steps를 빈 배열로, 최초 계획의 base_revision은 null로 제출한다.
정확한 필드 이름은 ionFlux, meanIonEnergy, iedWidth, pressure, sourcePower, biasPower다.
compare_runs는 기준 없는 두 Run의 동일 지표 절대 차이, 기준 대비 변화량, 여러 Run의 범위와 경향을 제공한다.
두 Run의 최댓값·최솟값 차이를 보여주거나 해석하려면 해당 지표를 compare_runs의 fields에만 넣는다. derive를 추가하지 않는다.
각 파형의 최댓값에서 최솟값을 뺀 폭은 potential.peakToPeak 또는 current.peakToPeak를 요청한다.
derive는 요청에 새 계산이 필요하거나 그 결과를 후속 도구의 입력으로 써야 할 때 사용한다.
IEAD 분포 비교는 plot_ids에 iead를, fields에 iead.maximum, iead.peakEnergy, iead.peakAngle을 넣는다.
비교 대상 전체의 수치를 계산한다. 화면에서 히트맵으로 볼 Run의 선택은 비교 대상을 제한하지 않는다.
selected_runs와 R1 같은 문맥 키는 Run 참조이며 수치가 아니다. 측정값을 얻는 단계는 compare_runs다.
비교 결과 전체 집합의 참조 예: {"kind":"result_ref","step_id":"compare","field":"ionFlux",
"scope":{"kind":"context_selection","key":"selected_runs"}}.
derive의 values에서 한 집합을 읽을 때는 위 참조 객체 하나를 사용한다. 입력 배열은 개별 값에만 사용하며, R1·R2는 confirmed_run으로 참조한다.
max/min/mean 결과의 참조 예: {"kind":"result_ref","step_id":"max","field":"value","scope":{"kind":"scalar"}}.
두 Run 모두에 관한 계산은 단일 confirmed_run 범위를 사용하지 않는다.
각 단계의 requirement_ids와 requirements의 handled_by에는 실제로 존재하는 ID를 넣는다.
이전 단계에서 만든 값을 쓰는 경우 depends_on에 그 단계의 ID를 넣는다.
앞 결과는 등록 필드와 범위가 있는 result_ref로 연결한다. JSON 경로나 계산된 수치를 만들지 않는다.
결과가 누락되면 입력을 확인하거나 지원되는 복구 계획을 세운다. 없는 데이터는 만들지 않는다.
재계획 시 base_revision을 유지하고 변경과 무관한 유효 단계의 ID와 내용을 보존한다.
메시지 인용은 제공된 messages의 키와 원문 구절을 사용한다. 순수 개념 설명만 general_only로 분류한다."""

COMPOSE_INSTRUCTIONS = """사용자 질문과 확인된 근거로 한국어 답변을 구성한다.
사용자가 설명·해석·의미·차이의 이유를 요구하면 interpretations에 그 요구를 직접 다루는 해석을 작성한다.
조회·수치 비교만 요청했으면 interpretations는 빈 배열로 두고, 설명을 요청했는데 근거가 부족하면 limitations에 한계를 적는다.
각 해석은 evidence_ids로 근거를 연결하고, 원인 추정에 필요한 전제는 assumptions에 명시한다.
근거 ID는 제공된 evidence 목록에서만 선택한다. search_evidence에 나온 Run ID나 값을 근거 ID로 만들지 않는다.
feedback이 overclaim이면 관찰 가능한 범위로 해석을 고치고, 원인을 알 수 없으면 그 한계를 설명한다.
실험 답변의 fact_ids에는 실제 근거 ID를 넣는다. 표에 있는 Run별 값을 나열하지 말고 질문에 답하는 핵심 수치만 인용한다.
인용하는 모든 실험값(측정값, 위상, 차이, 배율, 공정 조건)은 근거의 value_parts에서 선택한다.
예: “최솟값 차이 {{value:compare:O7}}가 최댓값 차이 {{value:compare:O8}}보다 큽니다.”
value 이외의 항목은 {{value:compare:O7|percent}}처럼 고른 항목 이름을 붙인다. 숫자와 단위는 코드가 채운다.
각 참조는 해당 해석·가정·한계의 evidence_ids에 넣은 실제 근거 ID여야 한다. 참조 가능한 값이 없으면 관찰의 범위를 설명한다.
최댓값·최솟값의 부호와 비교 방향은 인용한 관측값과 일치시킨다.
Run이 많으면 각 Run의 근거 ID를 나열하지 않는다. 요청한 항목의 최솟값·최댓값·범위처럼
비교를 대표하는 요약 근거 ID를 선택한다.
comparison_coverage.availableRunValues는 지표별로 비교 표에 개별 값이 있는 Run 수다.
evidence가 요약만 제공하더라도 이 개수가 양수이면 해당 지표의 개별 값이 표에 표시된다.
comparison_coverage.rawRunValues는 IEAD 최대 강도처럼 단위를 확인할 수 없어 차이는 계산하지 않지만 표에서 원값을 보여주는 Run 수다.
그래프의 표시 상태와 비가용 이유는 화면이 comparison_coverage.plotOutputs에 해당하는 결과로 직접 안내한다.
모델 입력에 파형 좌표가 없어도 화면은 좌표를 별도로 조회한다. 표시 여부는 본문에 쓰지 말고, 해석의 한계만 limitations에 적는다.
실제로 비교·검색한 내용만 설명하고 누락, 0건, 미지원, 미실행을 구별한다.
search_evidence의 조건과 측정값은 저장된 검색 결과다.
순방향 조회의 EXACT는 requestedConditions에 정확히 일치하는 실제 Run 조회가 완료된 상태다.
검색의 측정값에는 필수 조건과 정렬 목표의 지표가 모두 포함된다. 개별 후보 목록은 화면에 표시된다.
관찰만으로 원인을 단정하지 않는다. 일반 지식은 실제 Run을 조회한 것처럼 표현하지 않는다."""

QUESTIONS = {
    "interpretation_scope": (
        "사용자에게 표시할 interpretations의 text와 assumptions를 각각 evidence_ids로 연결된 근거와 대조한다. "
        "근거와 반대인 해석, 또는 관찰만으로 인과·유일한 원인·일반적 경향을 입증했다고 단정하면 overclaim이다. "
        "가정을 가정으로 명시하거나 원인을 단정할 수 없다고 설명하는 것은 적절하다. "
        "질문의 충족 여부나 수치 표의 표시와 정렬은 이 검토의 대상이 아니다.",
        {"within_evidence": "표시할 해석과 가정이 연결 근거에 부합", "overclaim": "해석이 연결 근거와 충돌하거나 근거를 넘는 단정",
         "unassessable": "연결 근거로 의미 판정 불가"},
    ),
}


@dataclass(frozen=True)
class V2Settings:
    planner: Settings
    writer: Settings
    decisions_model: str
    decisions_url: str
    plan_review_enabled: bool = True

    @classmethod
    def from_env(cls, base: Settings) -> "V2Settings":
        url = (os.getenv("AGENT_V2_DECISIONS_BASE_URL") or os.getenv("OPENAI_BASE_URL")
               or "https://api.openai.com/v1").rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        return cls(
            planner=replace(base, model=os.getenv("AGENT_V2_PLAN_MODEL", "gpt-6-luna"),
                            reasoning_effort=os.getenv("AGENT_V2_PLAN_REASONING_EFFORT", "low")),
            writer=replace(base, model=os.getenv("AGENT_V2_ANSWER_MODEL", base.model),
                           reasoning_effort=os.getenv("AGENT_V2_ANSWER_REASONING_EFFORT", base.reasoning_effort)),
            decisions_model=os.getenv("AGENT_V2_DECISIONS_MODEL", "gpt-6-luna"),
            decisions_url=url + "/decisions",
            plan_review_enabled=os.getenv("AGENT_V2_PLAN_REVIEW_ENABLED", "true").lower() not in {"false", "0"},
        )


def submit_plan_tool_schema():
    parameters = strict_schema(PlanDraft)
    parameters["properties"]["interpretation_requested"] = {"type": "boolean"}
    definitions = parameters["$defs"]
    definitions["LiteralInput"]["properties"]["unit"] = {
        "type": ["string", "null"],
        "enum": [*dict.fromkeys(UNITS.values()), "Torr", "m⁻²s⁻¹", "unsupported", None],
    }
    constraint = definitions["ConstraintInput"]
    field = constraint["properties"]["field"]
    operators = constraint["properties"]["operator"]["enum"]
    binding = {"anyOf": [{"$ref": f"#/$defs/{name}"} for name in ("LiteralInput", "ContextRef", "ResultRef")]}
    null = {"type": "null"}
    definitions["ConstraintInput"] = {"anyOf": [
        {**constraint, "properties": {
            "field": field, "operator": {"type": "string", "enum": [op for op in operators if op != "between"]},
            "value": binding, "min": null, "max": null,
        }},
        {**constraint, "properties": {
            "field": field, "operator": {"type": "string", "enum": ["between"]},
            "value": null, "min": binding, "max": binding,
        }},
    ]}
    return {"type": "function", "name": "submit_plan", "description": "검사할 전체 작업 계획을 제출한다.",
            "strict": True, "parameters": parameters}


def _plan_defaults(value):
    """Normalize omitted list defaults and duplicate bounds in a submitted range."""
    optional_lists = {"requirement_ids", "depends_on", "requires", "run_if", "goals", "plot_ids"}
    if isinstance(value, dict):
        result = {k: _plan_defaults(v) for k, v in value.items() if v is not None or k not in optional_lists}
        if (result.get("operator") == "between" and result.get("min") is not None and result.get("max") is not None
                and result.get("value") in (result["min"], result["max"])):
            result["value"] = None
        return result
    if isinstance(value, list):
        return [_plan_defaults(v) for v in value]
    return value


def review_answer(client: httpx.Client, settings: V2Settings, payload):
    body = {
        "model": settings.decisions_model,
        "input": [{"role": "user", "content": [{"type": "input_json", "data": payload}]}],
        "questions": [
            {"type": "choice", "name": name, "instructions": instructions,
             "choices": [{"value": value, "description": desc} for value, desc in choices.items()]}
            for name, (instructions, choices) in QUESTIONS.items()
        ],
    }
    try:
        response = client.post(settings.decisions_url, json=body,
                               headers={"Authorization": "Bearer " + settings.writer.api_key})
        response.raise_for_status()
        data = response.json()
        rows = data["answers"]
        by_name = {row["name"]: row for row in rows}
        if len(rows) != len(QUESTIONS) or set(by_name) != set(QUESTIONS):
            raise ValueError("incomplete decisions response")
        answers = []
        for name, (_, choices) in QUESTIONS.items():
            row = by_name[name]
            probs = {p["value"]: p["probability"] for p in row["probabilities"]}
            if row["type"] != "choice" or row["choice"] not in choices or set(probs) != set(choices):
                raise ValueError("invalid decisions choice")
            answers.append(ReviewAnswer.model_validate({
                "name": name, "choice": row["choice"], "probabilities": probs,
                "confidence": row.get("confidence"),
            }))
        status: Literal["PASS", "ISSUE"] = "PASS" if answers[0].choice == "within_evidence" else "ISSUE"
        return ReviewDecision(status=status, answers=answers), data.get("usage")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return ReviewDecision(status="UNAVAILABLE", answers=[], reason="DECISIONS_UNAVAILABLE"), None


def review_plan(client: httpx.Client, settings: V2Settings, payload):
    body = {
        "model": settings.decisions_model,
        "input": [{"role": "user", "content": [{"type": "input_json", "data": payload}]}],
        "questions": [{"type": "choice", "name": name, "instructions": instructions,
                       "choices": [{"value": value, "description": description} for value, description in CHOICES.items()]}
                      for name, instructions in PLAN_REVIEW_QUESTIONS.items()],
    }
    try:
        response = client.post(settings.decisions_url, json=body,
                               headers={"Authorization": "Bearer " + settings.writer.api_key})
        response.raise_for_status()
        data = response.json()
        return parse_plan_review(data, payload).model_dump(mode="json"), data.get("usage")
    except httpx.TimeoutException:
        reason = "DECISIONS_TIMEOUT"
    except httpx.HTTPStatusError as error:
        reason = f"DECISIONS_HTTP_{error.response.status_code}"
    except httpx.HTTPError:
        reason = "DECISIONS_CONNECTION"
    except (ValueError, KeyError, TypeError):
        reason = "DECISIONS_INVALID_RESPONSE"
    return review_result(payload, "UNAVAILABLE", reason=reason).model_dump(mode="json"), None


class V2ModelGateway:
    def __init__(self, settings: V2Settings, decisions: httpx.Client, input_guard):
        self.settings = settings
        self.planner = ModelClient(settings.planner)
        self.writer = ModelClient(settings.writer)
        self.decisions = decisions
        self.input_guard = input_guard

    def review_plan(self, context):
        self.input_guard({"input": context, "questions": PLAN_REVIEW_QUESTIONS}, "plan_review")
        return review_plan(self.decisions, self.settings, context)

    def submit_plan(self, context):
        tool = submit_plan_tool_schema()
        payload = self.planner._input(context, None)
        self.input_guard({"instructions": PLAN_INSTRUCTIONS, "input": payload, "tools": [tool]}, "plan")
        with tracing.span("v2.plan", kind="LLM") as span:
            response, usage = self.planner._request(
                PLAN_INSTRUCTIONS, payload, span, tools=[tool],
                tool_choice={"type": "function", "name": "submit_plan"}, parallel_tool_calls=False,
            )
        calls = [item for item in response.output if item.type == "function_call"]
        if len(calls) != 1 or calls[0].name != "submit_plan" or not calls[0].call_id:
            raise ModelError("MODEL_OUTPUT_INVALID")
        try:
            plan = PlanDraft.model_validate(_plan_defaults(json.loads(calls[0].arguments)))
        except (ValueError, TypeError):
            raise ModelError("MODEL_OUTPUT_INVALID") from None
        return plan.model_dump(mode="json"), usage

    def compose(self, context, *, on_block=None, numeric_values=None):
        schema = GeneralAnswerDraft if context["mode"] == "general_only" else DataAnswerDraft
        self.input_guard({"instructions": COMPOSE_INSTRUCTIONS, "input": context,
                          "schema": strict_schema(schema)}, "answer")
        if on_block is None:
            return self.writer.generate(COMPOSE_INSTRUCTIONS, context, schema)
        projection = AnswerStreamProjector(context["mode"], on_block,
                                           evidence_ids={row["id"] for row in context.get("evidence", [])},
                                           numeric_values=numeric_values)
        return self.writer.generate(COMPOSE_INSTRUCTIONS, context, schema, on_text_delta=projection.feed)

    def stream_compose(self, context, *, on_block, numeric_values=None):
        return self.compose(context, on_block=on_block, numeric_values=numeric_values)

    def review(self, context):
        self.input_guard({"input": context, "questions": QUESTIONS}, "review")
        decision, usage = review_answer(self.decisions, self.settings, context)
        return decision.model_dump(mode="json"), usage
