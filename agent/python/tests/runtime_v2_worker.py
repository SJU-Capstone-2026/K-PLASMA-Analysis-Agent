"""Test-only model replies for the artificial v2 browser comparison."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re

from kplasma_agent import worker
from kplasma_agent.config import Settings
from kplasma_agent.v2.model_gateway import QUESTIONS
from kplasma_agent.v2.plan_checks import review_questions
from kplasma_agent.v2.plan_review import parse_plan_review

CONCEPT = "IED가 뭐야? 이온 에너지 분포라는 개념을 간단히 설명해줘."
MIXED = "이온 플럭스가 40보다 높은 실제 Run을 찾고, 이온 플럭스의 개념도 설명해줘."
STRICT = "이온 플럭스가 40보다 높은 실제 Run을 모두 찾아줘."
NESTED = "비교할 두 Run은 내가 고를게. 선택한 두 Run 모두보다 이온 플럭스가 높은 후보를 찾아줘."
DECISION_PREFIX = "등록된 실제 Run에서 다음 조건을 모두 만족하는 후보 전체를 검색해줘. "
DECISION_SUFFIX = ". 조건은 모두 필수야."
NUMBER = r"([+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?)"
FLUX_UNIT = "10¹⁸ m⁻²s⁻¹"


def decision_constraints(question, source):
    """Parse the demo's confirmed conditions for the isolated synthetic worker."""
    criteria, separator, _ = question.removeprefix(DECISION_PREFIX).partition(DECISION_SUFFIX)
    conditions = criteria.split(", ")
    if not separator or len(conditions) != 4:
        raise AssertionError("Invalid scripted decision search")

    def values(value, pattern):
        match = re.fullmatch(pattern, value)
        if not match:
            raise AssertionError("Invalid scripted decision constraint")
        return [float(item) for item in match.groups()]

    def literal(value, unit):
        return {"kind": "literal", "value": value, "unit": unit, "source": source}

    pressure, = values(conditions[0], rf"압력 {NUMBER} mTorr 정확히")
    power, = values(conditions[1], rf"소스 전력 {NUMBER} W 정확히")
    damage = conditions[2].startswith("평균 이온 에너지 ")
    energy, = values(conditions[2 if damage else 3], rf"평균 이온 에너지 {NUMBER} eV 이하")
    if damage:
        low, high = values(conditions[3], rf"이온 플럭스 {NUMBER} 이상 {NUMBER} 이하 \({FLUX_UNIT}\)")
        flux = {"operator": "between", "min": literal(low, FLUX_UNIT), "max": literal(high, FLUX_UNIT)}
    else:
        minimum, = values(conditions[2], rf"이온 플럭스 {NUMBER} {FLUX_UNIT} 이상")
        flux = {"operator": "gte", "value": literal(minimum, FLUX_UNIT)}
    return [
        {"field": "pressure", "operator": "eq", "value": literal(pressure, "mTorr")},
        {"field": "sourcePower", "operator": "eq", "value": literal(power, "W")},
        {"field": "meanIonEnergy", "operator": "lte", "value": literal(energy, "eV")},
        {"field": "ionFlux", **flux},
    ]


def add_explanation(plan, question, mode="concept"):
    plan["requirements"].append({"id": "explanation", "text": question,
        "sources": [{"message_key": "question", "quote": question}], "handled_by": ["explain"]})
    plan["steps"].append({"id": "explain", "kind": "tool", "tool": "explain_answer",
        "requirement_ids": ["explanation"], "depends_on": [step["id"] for step in plan["steps"]],
        "inputs": {"mode": mode}})
    return plan


class ScriptedGateway:
    def __init__(self, settings, decisions, input_guard):
        self.settings = replace(settings, plan_review_enabled=True) if settings is not None else None

    def review_plan(self, payload):
        return matching_plan_review(payload)

    def submit_plan(self, payload):
        question = payload["messages"]["question"]
        source = {"message_key": "question", "quote": question}
        if question == CONCEPT:
            return add_explanation({"schema_version": 2, "request_mode": "general_only",
                    "base_revision": payload["base_revision"], "requirements": [], "steps": []}, question), {}
        if question in (STRICT, MIXED):
            steps = [{
                "id": "search", "kind": "tool", "tool": "reverse_search",
                "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt",
                           "value": {"kind": "literal", "value": 40, "unit": None, "source": source}}]},
            }]
        elif question.startswith(DECISION_PREFIX):
            steps = [{"id": "search", "kind": "tool", "tool": "reverse_search",
                      "inputs": {"constraints": decision_constraints(question, source)}}]
        elif question == NESTED:
            steps = [
                {"id": "choose", "kind": "await_input", "confirmation": "run_selection",
                 "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2}},
                {"id": "compare", "kind": "tool", "tool": "compare_runs",
                 "depends_on": ["choose"],
                 "inputs": {"runs": {"kind": "result_ref", "step_id": "choose", "field": "selection",
                                     "scope": {"kind": "scalar"}}, "fields": ["ionFlux"]}},
                {"id": "max", "kind": "derive", "operation": "max", "depends_on": ["compare"],
                 "requires": [{"step_id": "compare", "field": "ionFlux", "count": 2}],
                 "inputs": {"values": {"kind": "result_ref", "step_id": "compare", "field": "ionFlux",
                                       "scope": {"kind": "confirmed_selection", "step_id": "choose"}}}},
                {"id": "search", "kind": "tool", "tool": "reverse_search", "depends_on": ["max"],
                 "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt",
                            "value": {"kind": "result_ref", "step_id": "max", "field": "value",
                                      "scope": {"kind": "scalar"}}}]}},
            ]
        else:
            raise AssertionError("Unhandled artificial v2 question")
        plan = {"schema_version": 2, "request_mode": "data_request", "base_revision": payload["base_revision"],
                "requirements": [{"id": "r", "sources": [source], "text": question,
                                  "handled_by": [step["id"] for step in steps]}],
                "steps": [{**step, "requirement_ids": ["r"]} for step in steps]}
        if question.startswith(DECISION_PREFIX):
            return add_explanation(plan, question, mode="results"), {}
        return (add_explanation(plan, question) if question == MIXED else plan), {}

    def compose(self, payload):
        if payload["mode"] == "general_only":
            text = "이온 플럭스는 단위 면적·시간당 입자 수입니다." if payload["question"] == MIXED else "IED는 이온 에너지 분포입니다."
            return {"paragraphs": [text], "sources": []}, {}
        if payload["question"].startswith(DECISION_PREFIX):
            return decision_answer(payload), {}
        return {"fact_ids": [row["id"] for row in payload["evidence"]], "interpretations": [], "limitations": []}, {}

    def review(self, payload):
        return {"status": "PASS", "reason": None, "answers": [
            {"name": name, "choice": next(iter(choices)),
             "probabilities": {choice: float(choice == next(iter(choices))) for choice in choices},
             "confidence": 1.0}
            for name, (_, choices) in QUESTIONS.items()
        ]}, {}


def decision_answer(payload):
    evidence = payload["evidence"]
    facts = [row["id"] for row in evidence if row["field"] == "candidates"]
    by_run = {}
    for row in evidence:
        if row["runRef"] and row["field"] in {"ionFlux", "meanIonEnergy", "biasPower"}:
            by_run.setdefault(row["runRef"]["runVersionId"], {})[row["field"]] = row
    if not by_run:
        return {"fact_ids": facts, "interpretations": [], "limitations": [
            {"id": "empty", "text": "승인한 목표를 만족하는 후보가 없어 바이어스 변경의 관찰 근거를 비교할 수 없습니다.",
             "evidence_ids": facts},
        ]}
    rows = sorted(by_run.values(), key=lambda row: row["biasPower"]["value"])
    cited = [item["id"] for row in rows for item in row.values()]
    if "\n후속 질문 " in payload["question"]:
        text = ("평균 이온 에너지가 가장 낮은 조건부터 고를 필요는 없어요. "
                "이 비교만으로 식각이 충분히 진행되는지 판단하기 어렵기 때문에 선택한 조건에서 실제 결과를 확인해 보세요.")
    else:
        energy = [row["meanIonEnergy"]["value"] for row in rows]
        flux = [row["ionFlux"]["value"] for row in rows]
        bias = [row["biasPower"]["value"] for row in rows]
        text = "압력과 소스 전력이 같은 후보에서는 바이어스 전력에 따른 측정값을 비교할 수 있어요."
        if len(rows) > 1:
            if len(set(flux)) == 1:
                text += " 표에 있는 후보의 이온 플럭스는 모두 같았습니다."
            if len(set(bias)) == len(rows) and all(a < b for a, b in zip(energy, energy[1:], strict=False)):
                text += " 바이어스 전력이 낮은 후보일수록 평균 이온 에너지도 낮게 관찰됐어요."
    return {"fact_ids": facts, "interpretations": [
        {"id": "observation", "text": text, "evidence_ids": cited, "assumptions": []},
    ], "limitations": []}


def matching_plan_review(payload):
    answers = [{"name": q["name"], "type": "choice", "choice": "match", "confidence": 1.0,
                "probabilities": [{"value": c["value"], "probability": float(c["value"] == "match")}
                                  for c in q["choices"]]} for q in review_questions(payload)]
    return parse_plan_review({"answers": answers}, payload).model_dump(mode="json"), {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connection", type=Path, required=True)
    args = parser.parse_args()
    connection = json.loads(args.connection.read_text())
    worker.V2ModelGateway = ScriptedGateway
    worker.serve(replace(Settings(), backend_url=connection["url"], worker_token=connection["token"]))


if __name__ == "__main__":
    main()
