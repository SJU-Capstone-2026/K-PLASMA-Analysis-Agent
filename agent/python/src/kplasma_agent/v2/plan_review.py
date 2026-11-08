"""Plan-meaning review contracts. Decisions judges; code controls execution."""

from hashlib import sha256
import json
from typing import Annotated, Literal, TypedDict, get_args

from pydantic import Field, model_validator

from ..comparison_catalog import FIELD_META, PlotId
from ..contracts import MetricId
from ..metric_registry import UNITS, normalize_value
from .contracts import ClosedModel, Operation, PlanDraft
from .plan_checks import build_check_specs, choices_for, rejection_evidence

PROMPT_VERSION = "plan-semantics-conditions-2"
LEGACY_NAMES = {"request_coverage", "condition_preservation", "target_operation_alignment"}
Choice = Literal["match", "mismatch", "unclear", "missing", "unexpected", "value_changed", "unit_changed",
                 "boundary_changed", "direction_changed", "target_changed"]
Probability = Annotated[float, Field(ge=0, le=1)]

class PlanReviewContext(TypedDict):
    schema_version: int
    question: str
    input_history: list[dict]
    plan_revision: int
    plan: dict
    confirmed_context: dict
    tool_contracts: dict
    policy_context: dict
    completed_steps: dict
    execution_view: list[dict]
    program_effects: list[str]
    plan_digest: str
    input_digest: str
    prompt_version: str
    check_specs: list[dict]


class PlanReviewCheck(ClosedModel):
    name: str
    choice: Choice
    probabilities: dict[Choice, Probability]
    confidence: Probability | None
    kind: str | None = None
    issue: dict | None = None


class PlanReviewResult(ClosedModel):
    schema_version: Literal[1, 2] = 2
    status: Literal["PASS", "ISSUE", "UNCLEAR", "UNAVAILABLE", "SKIPPED"]
    plan_revision: int
    plan_digest: str
    input_digest: str
    prompt_version: str
    checks: list[PlanReviewCheck]
    reason: str | None = None
    expected_check_names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_verdict(self):
        if self.status in {"PASS", "ISSUE", "UNCLEAR"}:
            names = [c.name for c in self.checks]
            expected_names = LEGACY_NAMES if self.schema_version == 1 else set(self.expected_check_names)
            if not expected_names or len(names) != len(expected_names) or set(names) != expected_names:
                raise ValueError("incomplete plan review checks")
            for check in self.checks:
                allowed = {"match", "mismatch", "unclear"} if self.schema_version == 1 else set(choices_for(check.kind))
                if set(check.probabilities) != allowed or check.choice not in allowed:
                    raise ValueError("invalid plan review probabilities or choice")
                if self.schema_version == 2 and ((check.choice == "match") != (check.issue is None)):
                    raise ValueError("plan rejection must include its condition evidence")
            expected = "ISSUE" if any(c.choice not in {"match", "unclear"} for c in self.checks) else (
                "UNCLEAR" if any(c.choice == "unclear" for c in self.checks) else "PASS")
            if self.status != expected:
                raise ValueError("plan review verdict conflicts with its choices")
        return self


def digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(raw.encode()).hexdigest()


def plan_digest(plan) -> str:
    return digest(plan.model_dump(mode="json") if isinstance(plan, PlanDraft) else plan)


def tool_contracts() -> dict:
    return {
        "forward_lookup": {"description": "압력·소스·바이어스 조건으로 저장된 실제 Run 조회",
                           "inputs": ["pressure", "source_power", "bias_power"], "outputs": ["candidates"]},
        "reverse_search": {"description": "constraints와 target_range로 후보를 필터링한 뒤 maximize/minimize 순서로 정렬",
                           "constraint_logic": "constraints와 goals의 target_range는 전부 AND 필터. 독립 범위를 각각 조회하려면 별개 검색 단계가 필요하다. maximize/minimize만 필터 통과 후 정렬이다.",
                           "fields": list(get_args(MetricId)),
                           "operators": ["eq", "lt", "lte", "gt", "gte", "between"],
                           "condition_inputs": {
                               "between": "min, max가 양끝 포함 하한·상한. value:null은 미사용 자리이며 0이라는 뜻이 아님.",
                               "eq,lt,lte,gt,gte": "value를 사용하며 min/max:null은 미사용 자리.",
                               "target_range": "goals에 있어도 min/max 양끝 포함 between 필터로 실행하며 정렬에는 사용하지 않음.",
                           },
                           "goals": ["maximize", "minimize", "target_range"], "outputs": ["candidates"]},
        "compare_runs": {"description": "지정된 고정 Run들의 fields 값·절대 차이·범위·기준 대비 변화량과 plot_ids 그래프 제공. 두 Run 차이는 기본 계산한다.",
                         "fields": FIELD_META, "plot_ids": list(get_args(PlotId)),
                         "input_semantics": {
                             "runs": "candidate_group이면 검색 결과 전체를 비교. baseline:null은 기준 없는 비교.",
                             "fields": "등록된 Run별 특징값은 compare_runs 안에서 계산한다. fields에 목록을 전달하면 충분하며 별도 derive 단계는 필요 없다.",
                             "plot_ids": "같은 Run들의 분포를 보조 그래프로 제공. 검색 조건이나 비교 집합을 변경하지 않음.",
                         },
                         "outputs": "각 요청 field의 Run별 quantity 목록과 candidates 참조"},
        "derive": {"operations": list(get_args(Operation)),
                   "description": "values가 참조한 검증된 수치에 등록 연산을 적용. 후속 도구의 새 기준값 등에 사용.",
                   "output": "value: 단위가 있는 단일 quantity"},
        "await_input": {"confirmations": ["run_selection", "condition", "baseline", "trend_axis", "calculation_direction"],
                        "description": "미확정 입력을 사용자에게 묻고 정해진 입력으로 재개. selection_count는 검색 제한이 아닌 정확한 선택 개수.",
                        "outputs": {"run_selection": "selection: 고정 Run 참조 목록", "others": "value: 확인된 입력"}},
        "bindings": {
            "literal": "원문 수치·단위·source.quote. 단위 생략은 null이며 코드 기본 단위 적용.",
            "context_ref": "확인된 selected_runs 또는 R1 등 Run 별칭·고정 버전 참조. 측정값이 아님.",
            "result_ref": "step_id의 등록 field를 scope로 읽음. JSON 경로를 만드는 기능이 아님.",
            "quantity_units": "result_ref의 수치와 단위는 출처 결과에서 실행 시 함께 읽는다. max/min/mean은 입력 단위를 보존한다. 참조 객체에 미래 수치·리터럴 단위를 중복 기재하지 않아도 된다.",
            "scopes": {"scalar": "단일 값 또는 확인 단계의 selection", "candidate_group": "저장된 검색 후보 전체",
                       "context_selection": "key가 가리키는 선택 Run 전체의 field 값",
                       "confirmed_run": "key가 가리키는 한 Run의 field 값",
                       "confirmed_selection": "지정 확인 단계에서 사용자가 고른 Run들의 field 값"},
        },
    }


def build_plan_review_context(plan: PlanDraft, revision: int, question: str, input_history: list[dict],
                              confirmed_context: dict, completed_steps: dict) -> PlanReviewContext:
    if not question or revision < 1:
        raise ValueError("PLAN_REVIEW_INPUT_INVALID")
    meaning = {"question": question, "input_history": input_history, "confirmed_context": confirmed_context}
    context = {
        "schema_version": 2, **meaning, "plan_revision": revision, "plan": plan.model_dump(mode="json"),
        "check_specs": build_check_specs(plan.model_dump(mode="json")),
        "execution_view": execution_view(plan),
        "program_effects": program_effects(plan),
        "tool_contracts": tool_contracts(),
        "policy_context": {
            "default_units": UNITS,
            "numeric_ranges": "명시한 범위는 가깝게라고 해도 양끝 포함 between. 범위 밖 허용을 명시하면 그 지시를 따른다.",
            "ranking": "독립적인 높게/낮게 최적화·높은/낮은 순 요청은 maximize/minimize 정렬이다. 다른 Run보다 높음/낮음은 gt/lt 필터이며 정렬 요구가 아니다. 요청에 없는 정렬·top-N은 추가하지 않는다.",
            "both_runs": "둘 모두보다 높게=max 후 gt, 모두보다 낮게=min 후 lt, 평균보다=mean 기준 비교.",
            "comparison_scope": "조건으로 지정한 실험들 비교는 모두라는 단어가 없어도 후보 전체. 일부가 불명확하면 선택 확인.",
            "baseline": "기준 미지정이면 기준 없는 값·절대 차이·범위 비교. 사용자가 직접 고르면 baseline 확인을 계획.",
            "new_selection": "현재 질문에서 새 대상·기준을 직접 고르겠다고 하면 이전 문맥에 선택된 Run·baseline이 있어도 새 확인 단계를 계획하는 것이 맞다. 이전 선택을 강제로 재사용하지 않는다.",
            "units": "단위 표기 정규화 허용. 원문 리터럴 수치와 배율 보존. 실제 단위 변환은 코드가 수행.",
            "interpretation": "표·계산·그래프는 코드로 제공. 해석 요청은 interpretation_requested=true로 답변 단계가 처리.",
            "condition_review": "검색 필터·경계·정렬·요청 개수의 실행 효과를 검사한다. compare_runs.fields는 출력 특징값이고 plot_ids는 같은 대상의 보조 그래프이므로 검색 조건 추가가 아니다. null·빈 배열은 미사용 선택 항목이다.",
        },
        "completed_steps": {key: {"status": value.get("status"), "execution_id": value.get("executionId")}
                            for key, value in completed_steps.items()},
        "plan_digest": plan_digest(plan), "input_digest": digest(meaning), "prompt_version": PROMPT_VERSION,
    }
    # Freeze the reviewed input: later selection mutations must not alter a saved request.
    return json.loads(json.dumps(context, ensure_ascii=False, allow_nan=False))


def execution_view(plan: PlanDraft) -> list[dict]:
    rows = []
    for step in plan.steps:
        item = step.model_dump(mode="json")
        row = {"step": step.id, "kind": item["kind"],
               "action": item.get("tool", item.get("operation", item.get("confirmation"))),
               "depends_on": step.depends_on, "requires": item["requires"], "run_if": item["run_if"],
               "inputs": item["inputs"]}
        if item.get("tool") == "compare_runs":
            row["computed_outputs"] = {field: FIELD_META[field] for field in item["inputs"]["fields"]}
        rows.append(row)
    return rows


def _binding_text(value, field=None) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_binding_text(v, field) for v in value) + "]"
    if value is None:
        return "not specified"
    if value["kind"] == "literal":
        unit = value["unit"] or UNITS.get(field, "")
        text = f"{value['value']} {unit}".strip()
        if field in UNITS and unit != UNITS[field]:
            normalized = normalize_value(field, value["value"], unit)
            text += f" (= {normalized:g} {UNITS[field]})"
        return text
    if value["kind"] == "context_ref":
        return "context:" + value["key"]
    scope = value["scope"]
    if value["field"] == "selection" and scope["kind"] == "scalar":
        return f"{value['step_id']}.selection (ALL user-confirmed Runs)"
    group = {"scalar": "single output", "candidate_group": "ALL matching Runs",
             "context_selection": "ALL context:" + scope.get("key", ""),
             "confirmed_run": "one context:" + scope.get("key", ""),
             "confirmed_selection": "user selection from " + scope.get("step_id", "")}[scope["kind"]]
    return f"{value['step_id']}.{value['field']} ({group})"


def program_effects(plan: PlanDraft) -> list[str]:
    """Pretty-print executable operands, never infer meaning from the question."""
    operators = {"eq": "=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
    lines = []
    by_id = {step.id: step for step in plan.steps}
    for step in plan.steps:
        item = step.model_dump(mode="json")
        inputs = item["inputs"]
        if item.get("tool") == "reverse_search":
            predicates = []
            constraints = [*inputs["constraints"], *(
                {**goal, "operator": "between"} for goal in inputs["goals"]
                if goal["direction"] == "target_range"
            )]
            for c in constraints:
                field = c["field"]
                if c["operator"] == "between":
                    predicates.append(f"{_binding_text(c['min'], field)} <= {field} <= {_binding_text(c['max'], field)}")
                else:
                    predicates.append(f"{field} {operators[c['operator']]} {_binding_text(c['value'], field)}")
            text = "all stored Runs satisfying " + (" AND ".join(predicates) or "no numeric filter")
            rankings = [goal for goal in inputs["goals"] if goal["direction"] != "target_range"]
            if rankings:
                text += "; rank by " + json.dumps(rankings, ensure_ascii=False)
        elif item.get("tool") == "compare_runs":
            fields = ", ".join(f"{f} ({FIELD_META[f]['label']})" for f in inputs["fields"])
            text = f"compare_runs computes {fields} for EVERY Run in {_binding_text(inputs['runs'])}"
            text += f"; baseline={_binding_text(inputs['baseline'])}; trend_axis={_binding_text(inputs['trend_axis'])}"
            if inputs["plot_ids"]:
                text += "; supplementary plots=" + ",".join(inputs["plot_ids"])
        elif item["kind"] == "derive":
            text = f"{item['operation']}({_binding_text(inputs['values'])}); direction={inputs['direction']}"
        elif item["kind"] == "await_input":
            count = inputs["selection_count"]
            text = f"await user {item['confirmation']}" + (f" exactly {count}" if count else "")
            candidates = inputs["candidates"]
            if candidates is None and item["confirmation"] == "baseline":
                target = by_id[inputs["target_step_id"]].model_dump(mode="json")
                candidates = target["inputs"]["runs"]
            text += f" from {_binding_text(candidates)}; bind to {inputs['target_step_id']}.{inputs['field']}"
        else:
            text = "forward_lookup: " + json.dumps(inputs, ensure_ascii=False)
        lines.append(f"{step.id}: {text}")
    return lines


def parse_plan_review(data: dict, context: PlanReviewContext) -> PlanReviewResult:
    rows = data["answers"]
    by_name = {row["name"]: row for row in rows}
    specs = context["check_specs"]
    if len(rows) != len(specs) or set(by_name) != {spec["name"] for spec in specs}:
        raise ValueError("incomplete plan review")
    checks = []
    for spec in specs:
        row = by_name[spec["name"]]
        probabilities = row["probabilities"]
        probs = {item["value"]: item["probability"] for item in probabilities}
        allowed = choices_for(spec["kind"])
        if (row["type"] != "choice" or len(probabilities) != len(allowed)
                or set(probs) != set(allowed) or row["choice"] not in allowed):
            raise ValueError("invalid plan review probabilities or choice")
        issue = rejection_evidence(context, spec, row["choice"]) if row["choice"] != "match" else None
        checks.append(PlanReviewCheck(name=spec["name"], choice=row["choice"], kind=spec["kind"], issue=issue,
                                      probabilities=probs, confidence=row.get("confidence")))
    status = "ISSUE" if any(c.choice not in {"match", "unclear"} for c in checks) else (
        "UNCLEAR" if any(c.choice == "unclear" for c in checks) else "PASS")
    return review_result(context, status, checks=checks)


def review_result(context: PlanReviewContext, status, *, checks=None, reason=None) -> PlanReviewResult:
    return PlanReviewResult(status=status, checks=checks or [], reason=reason,
                            expected_check_names=[spec["name"] for spec in context["check_specs"]],
                            plan_revision=context["plan_revision"], plan_digest=context["plan_digest"],
                            input_digest=context["input_digest"], prompt_version=context["prompt_version"])


def matches_review_context(result: PlanReviewResult, context: PlanReviewContext) -> bool:
    if result.schema_version != 2 or result.expected_check_names != [s["name"] for s in context["check_specs"]]:
        return False
    if (result.plan_revision, result.plan_digest, result.input_digest, result.prompt_version) != (
            context["plan_revision"], context["plan_digest"], context["input_digest"], context["prompt_version"]):
        return False
    for check, spec in zip(result.checks, context["check_specs"], strict=False):
        expected_issue = rejection_evidence(context, spec, check.choice) if check.choice != "match" else None
        if check.name != spec["name"] or check.kind != spec["kind"] or check.issue != expected_issue:
            return False
    return True


def plan_review_feedback(result: PlanReviewResult) -> dict:
    return {"code": "PLAN_SEMANTIC_MISMATCH" if result.status == "ISSUE" else "PLAN_SEMANTIC_UNCLEAR",
            "plan_revision": result.plan_revision, "plan_digest": result.plan_digest,
            "failed_checks": {check.name: check.choice for check in result.checks if check.choice != "match"},
            "issues": [check.issue for check in result.checks if check.issue is not None],
            "instruction": "issues의 condition_id·원문 sources·실제 plan_values를 대조해 해당 부분만 수정한다. 불확실하면 await_input으로 묻는다. 조건을 버려 통과시키지 않는다."}
