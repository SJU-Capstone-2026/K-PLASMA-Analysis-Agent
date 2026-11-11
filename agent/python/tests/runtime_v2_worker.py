"""Test-only model replies for the artificial v2 browser comparison."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

from kplasma_agent import worker
from kplasma_agent.config import Settings
from kplasma_agent.v2.model_gateway import QUESTIONS
from kplasma_agent.v2.plan_checks import review_questions
from kplasma_agent.v2.plan_review import parse_plan_review

CONCEPT = "IED가 뭐야? 이온 에너지 분포라는 개념을 간단히 설명해줘."
MIXED = "이온 플럭스가 40보다 높은 실제 Run을 찾고, 이온 플럭스의 개념도 설명해줘."
STRICT = "이온 플럭스가 40보다 높은 실제 Run을 모두 찾아줘."
NESTED = "비교할 두 Run은 내가 고를게. 선택한 두 Run 모두보다 이온 플럭스가 높은 후보를 찾아줘."


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
        return (add_explanation(plan, question) if question == MIXED else plan), {}

    def compose(self, payload):
        if payload["mode"] == "general_only":
            text = "이온 플럭스는 단위 면적·시간당 입자 수입니다." if payload["question"] == MIXED else "IED는 이온 에너지 분포입니다."
            return {"paragraphs": [text], "sources": []}, {}
        return {"fact_ids": [row["id"] for row in payload["evidence"]], "interpretations": [], "limitations": []}, {}

    def review(self, payload):
        return {"status": "PASS", "reason": None, "answers": [
            {"name": name, "choice": next(iter(choices)),
             "probabilities": {choice: float(choice == next(iter(choices))) for choice in choices},
             "confidence": 1.0}
            for name, (_, choices) in QUESTIONS.items()
        ]}, {}


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
