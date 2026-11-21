"""Check explicit Run targets and search order against the accepted plan."""

import re
from typing import Literal, TypedDict

from ..domain.grounding import _ALIASES, _NUMBER, _UNIT
from .bindings import BlockedInput, resolve_comparison_entries
from .contracts import CompareStep

_METRIC = "|".join(f"(?:{aliases})" for aliases in _ALIASES.values())
_METRIC_PATTERNS = {field: re.compile(aliases, re.I) for field, aliases in _ALIASES.items()}
_VALUE = rf"{_NUMBER}(?:\s*(?:×\s*)?{_UNIT})?"
_BOUND = r"(?:[을를]\s*)?(?:엄격히\s*)?(?:이상|이하|미만|초과|보다\s*(?:크고|작은|높고|낮은))"
_OPERAND = rf"(?:{_NUMBER}\s*[~–—-]\s*{_VALUE}|{_VALUE}(?:\s*{_BOUND}(?:\s+{_VALUE}\s*{_BOUND})?)?)"
_CONDITION = rf"(?:{_METRIC})(?:[이가은는])?\s+{_OPERAND}"
_FILTER = rf"{_CONDITION}(?:(?:\s|,|이고|이며|하고|고|와|과|및)+{_CONDITION}){{0,4}}"
_RUNS = r"(?:실제\s+)?Runs?"
_FIND = r"(?:찾아\s*줘|검색해\s*줘|보여\s*줘)"
_RUN_OBJECT = rf"{_RUNS}(?:을|만)(?:\s*모두)?"
_ORDER = (rf"(?P<metric>{_METRIC})(?:[이가의])?\s*"
          r"(?:(?P<descending>높은\s*순|내림차순)|낮은\s*순|오름차순)(?:으로|로)")
_SEARCH = re.compile(
    rf"(?:{_FILTER}(?:인|는)?\s*)?{_RUN_OBJECT}\s*"
    rf"(?:(?:찾아서,?\s*)?{_ORDER}\s*(?:정렬해\s*줘|{_FIND})|{_FIND})",
    re.I,
)
_ENDPOINTS = re.compile(rf"{_VALUE}\s*(?:와|과)\s*{_VALUE}[은는]\s*둘\s*다\s*제외해\s*줘", re.I)
_ITEM = (rf"(?:{_METRIC}|(?:전극\s*전위\s*)?(?:최댓값|최솟값|첨두간\s*값)"
         r"|(?:IEAD|IAD|IED)\s*최대\s*강도|피크\s*(?:에너지·각도|에너지|입사각|각도))")
_FIELDS = rf"{_ITEM}(?:\s*(?:,|와|과|및|그리고)\s*{_ITEM}){{0,6}}(?:을|를|만)?"
_COMPARE = (rf"{_FIELDS}\s*(?:(?:현재 지정된 )?기준(?: Run)? 대비(?: 부호 있는 차이와 변화율로)?\s*"
            r"|공정 조건에 따른 경향으로\s*)?"
            r"(?:비교해\s*줘|비교해서\s*각 항목의 절대 차이를 보여\s*줘|차이를 보여\s*줘)")
_SELECTED = re.compile(rf"(?:이미\s*)?선택한\s*(?:두|2개(?:의)?)\s*{_RUNS}의\s*{_COMPARE}", re.I)
_WHOLE_GROUP = re.compile(
    rf"{_FILTER}(?:인|는)?\s*(?:모든\s*{_RUNS}의\s*"
    rf"|{_RUNS}을\s*모두\s*찾아(?:서|내고),?\s*(?:찾은\s*)?전체(?:\s*{_RUNS})?의\s*){_COMPARE}",
    re.I,
)
_CHOOSE_AXIS = re.compile(r"경향을 볼 공정 조건 축은 내가 직접 선택하게 해\s*줘")


class CodeCheck(TypedDict):
    choice: Literal["match", "missing", "unexpected", "direction_changed", "target_changed"]
    path: str
    actual: list | dict
    allowed: list | dict
    message: str


def code_plan_checks(question: str, plan: dict, confirmed_context: dict, input_history: list[dict],
                     *, flash: bool = False) -> dict[str, CodeCheck]:
    checks = _explicit_plan_checks(question, plan, confirmed_context, input_history)
    if flash:
        checks.update(_flash_checks(question, plan, input_history))
    return checks


def _explicit_plan_checks(question, plan, confirmed_context, input_history):
    # Full clauses avoid treating an unrecognized qualifier or selection as absent.
    if input_history or len(question) > 512:
        return {}
    clauses = re.split(r"[.!?](?:\s+|$)", " ".join(question.split()).strip())
    orders = []
    targets = []
    preceding = ""
    for clause in filter(None, clauses):
        search = _SEARCH.fullmatch(clause)
        if search:
            metric = search["metric"]
            direction = "maximize" if search["descending"] else "minimize"
            orders.append([{"field": field, "direction": direction}
                           for field, pattern in _METRIC_PATTERNS.items() if metric and pattern.fullmatch(metric)])
            if metric and len(orders[-1]) != 1:
                return {}
            preceding = "search"
        elif preceding == "search" and _ENDPOINTS.fullmatch(clause):
            preceding = ""
        elif _SELECTED.fullmatch(clause):
            targets.append("selected")
            preceding = "selected"
        elif preceding == "selected" and _CHOOSE_AXIS.fullmatch(clause):
            preceding = ""
        elif _WHOLE_GROUP.fullmatch(clause):
            orders.append([])
            targets.append("search")
            preceding = "group"
        else:
            return {}

    steps = plan["steps"]
    searches = [(index, step) for index, step in enumerate(steps) if step.get("tool") == "reverse_search"]
    comparisons = [(index, step) for index, step in enumerate(steps) if step.get("tool") == "compare_runs"]
    checks: dict[str, CodeCheck] = {}
    if len(orders) == len(searches) == 1:
        index, step = searches[0]
        expected = orders[0]
        actual = [{"field": goal["field"], "direction": goal["direction"]}
                  for goal in step["inputs"]["goals"] if goal["direction"] != "target_range"]
        checks[f"ordering.{step['id']}"] = {
            "choice": ("match" if actual == expected else "unexpected" if not expected
                       else "missing" if not actual else "direction_changed"),
            "path": f"/steps/{index}/inputs/goals", "actual": actual, "allowed": expected,
            "message": "goals의 정렬 지표와 방향을 allowed대로 수정한다. target_range 필터는 보존한다.",
        }

    if len(targets) == len(comparisons) == 1:
        index, step = comparisons[0]
        runs = step["inputs"]["runs"]
        if targets[0] == "search":
            if len(searches) != 1 or len(orders) != 1:
                return checks
            expected_runs = {"kind": "result_ref", "step_id": searches[0][1]["id"], "field": "candidates",
                             "scope": {"kind": "candidate_group"}}
            matched = runs == expected_runs and expected_runs["step_id"] in step["depends_on"]
        else:
            selected = confirmed_context.get("selected_runs", [])
            expected_refs = {ref["runVersionId"] for ref in selected}
            if len(selected) != 2 or len(expected_refs) != 2:
                return checks
            expected_runs = {"kind": "context_ref", "key": "selected_runs"}
            try:
                entries = resolve_comparison_entries(CompareStep.model_validate(step), confirmed_context, {})
                matched = {entry["ref"]["runVersionId"] for entry in entries} == expected_refs
            except BlockedInput:
                matched = False
        checks[f"targets.{step['id']}"] = {
            "choice": "match" if matched else "target_changed",
            "path": f"/steps/{index}/inputs/runs", "actual": runs, "allowed": expected_runs,
            "message": "runs를 allowed의 비교 대상으로 연결한다. 결과 참조면 해당 단계에 의존하도록 연결한다.",
        }
    return checks


def _flash_checks(question, plan, input_history) -> dict[str, CodeCheck]:
    steps = plan["steps"]
    sources = {step["id"]: step for step in steps}
    checks = {}
    for index, step in enumerate(steps):
        if step.get("tool") != "compare_runs":
            continue
        prerequisites = step["required_prior_outputs"]
        allowed = []
        for requirement in prerequisites:
            source = sources.get(requirement["step_id"], {})
            run_list = (
                source.get("tool") == "reverse_search" and requirement["field"] == "candidates"
                or source.get("confirmation") == "run_selection" and requirement["field"] == "selection"
            )
            allowed.append({**requirement, "unit": None, "value_type": "run_refs"}
                           if run_list and requirement["unit"] is not None else requirement)
        if allowed != prerequisites:
            checks[f"execution_guards.{step['id']}"] = {
                "choice": "unexpected", "path": f"/steps/{index}/required_prior_outputs",
                "actual": prerequisites, "allowed": allowed,
                "message": "Run 참조 목록에는 물리 단위가 없다. 실행 전제에서 해당 물리 단위를 제거한다.",
            }

    # Only a fully recognized, standalone search can prove that no dialog or comparison was requested.
    if input_history or len(question) > 512 or not _SEARCH.fullmatch(" ".join(question.split()).rstrip(".!?")):
        return checks
    confirmations = [step["confirmation"] for step in steps if step["kind"] == "await_input"]
    if confirmations:
        checks["request.confirmation_coverage"] = {
            "choice": "unexpected", "path": "/steps", "actual": confirmations, "allowed": [],
            "message": "사용자가 요청한 조회·정렬을 바로 수행하고, 요청하지 않은 확인 단계를 제거한다.",
        }
    for index, step in enumerate(steps):
        if step.get("tool") == "compare_runs":
            checks[f"targets.{step['id']}"] = {
                "choice": "unexpected", "path": f"/steps/{index}/inputs/runs",
                "actual": step["inputs"]["runs"], "allowed": [],
                "message": "사용자가 요청한 조회·정렬을 보존하고, 요청하지 않은 비교 단계를 제거한다.",
            }
    return checks
