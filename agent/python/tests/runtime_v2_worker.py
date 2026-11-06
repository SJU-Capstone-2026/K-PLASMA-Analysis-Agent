"""Test-only model replies for the artificial v2 browser comparison."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

from kplasma_agent import worker
from kplasma_agent.config import Settings
from kplasma_agent.v2.model_gateway import QUESTIONS
from kplasma_agent.v2.plan_review import PLAN_REVIEW_QUESTIONS, PlanReviewCheck, review_result

CONCEPT = "IED가 뭐야? 이온 에너지 분포라는 개념을 간단히 설명해줘."
STRICT = "이온 플럭스가 40보다 높은 실제 Run을 모두 찾아줘."
NESTED = "비교할 두 Run은 내가 고를게. 선택한 두 Run 모두보다 이온 플럭스가 높은 후보를 찾아줘."


class ScriptedGateway:
    def __init__(self, settings, decisions, input_guard):
        self.settings = settings

    def review_plan(self, payload):
        return matching_plan_review(payload)

    def submit_plan(self, payload):
        question = payload["messages"]["question"]
        source = {"message_key": "question", "quote": question}
        if question == CONCEPT:
            return {"schema_version": 1, "request_mode": "general_only",
                    "base_revision": payload["base_revision"], "requirements": [], "steps": []}, {}
        if question == STRICT:
            steps = [{
                "id": "search", "kind": "tool", "tool": "reverse_search",
                "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt",
                           "value": {"kind": "literal", "value": 40, "unit": None, "source": source}}]},
            }]
        elif question == NESTED:
            steps = [
                {"id": "compare", "kind": "tool", "tool": "compare_runs",
                 "inputs": {"runs": {"kind": "context_ref", "key": "selected_runs"}, "fields": ["ionFlux"]}},
                {"id": "max", "kind": "derive", "operation": "max", "depends_on": ["compare"],
                 "requires": [{"step_id": "compare", "field": "ionFlux", "count": 2}],
                 "inputs": {"values": {"kind": "result_ref", "step_id": "compare", "field": "ionFlux",
                                       "scope": {"kind": "context_selection", "key": "selected_runs"}}}},
                {"id": "search", "kind": "tool", "tool": "reverse_search", "depends_on": ["max"],
                 "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt",
                            "value": {"kind": "result_ref", "step_id": "max", "field": "value",
                                      "scope": {"kind": "scalar"}}}]}},
            ]
        else:
            raise AssertionError("Unhandled artificial v2 question")
        return {"schema_version": 1, "request_mode": "data_request", "base_revision": payload["base_revision"],
                "requirements": [{"id": "r", "sources": [source], "text": question,
                                  "handled_by": [step["id"] for step in steps]}],
                "steps": [{**step, "requirement_ids": ["r"]} for step in steps]}, {}

    def compose(self, payload):
        if payload["mode"] == "general_only":
            return {"paragraphs": ["IED는 이온 에너지 분포입니다."], "sources": []}, {}
        return {"fact_ids": [row["id"] for row in payload["evidence"]], "interpretations": [], "limitations": []}, {}

    def review(self, payload):
        return {"status": "PASS", "reason": None, "answers": [
            {"name": name, "choice": next(iter(choices)),
             "probabilities": {choice: float(choice == next(iter(choices))) for choice in choices},
             "confidence": 1.0}
            for name, (_, choices) in QUESTIONS.items()
        ]}, {}


def matching_plan_review(payload):
    checks = [PlanReviewCheck(name=name, choice="match", probabilities={"match": 1.0, "mismatch": 0.0, "unclear": 0.0},
                              confidence=1.0) for name in PLAN_REVIEW_QUESTIONS]
    return review_result(payload, "PASS", checks=checks).model_dump(mode="json"), {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connection", type=Path, required=True)
    args = parser.parse_args()
    connection = json.loads(args.connection.read_text())
    worker.V2ModelGateway = ScriptedGateway
    worker.serve(replace(Settings(), backend_url=connection["url"], worker_token=connection["token"]))


if __name__ == "__main__":
    main()
