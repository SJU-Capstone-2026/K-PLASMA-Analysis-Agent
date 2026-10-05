"""Offline model fixture for the isolated v1 HTTP/PG/browser gate.

This module is test-only and is never selected by the production worker. It
recognizes the explicit artificial queries in agent-v1-live.spec.ts; numerical
results, Run selection, checkpoints and finalization use the real v1 graph.
"""

import argparse
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import re

from kplasma_agent.config import Settings
from kplasma_agent import worker

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_CONDITIONS = {
    "pressure": rf"압력\s*({_NUMBER})\s*(mTorr|Torr|Pa)",
    "sourcePower": rf"소스\s*(?:전력\s*)?({_NUMBER})\s*(kW|W)",
    "biasPower": rf"바이어스\s*(?:전력\s*)?({_NUMBER})\s*(kW|W)",
}


class RuntimeTestModel:
    """Explicit test replies, not a runtime heuristic fallback."""

    def __init__(self, _settings):
        pass

    def generate(self, _instructions, payload, output_model):
        if output_model.__name__ == "Interpretation":
            value = self.interpret(payload)
        elif output_model.__name__ == "ChangeDraft":
            evidence = payload["evidence"]
            refs = [
                item["id"]
                for item in evidence["observations"]
                if item["available"] and item["id"].startswith("metric_")
            ]
            value = {
                "status": "answered" if refs else "insufficient_knowledge",
                "interpretations": (
                    [
                        {
                            "text": "관찰된 차이는 플라즈마 내부의 입자 생성과 손실 변화에 관련됐을 수 있습니다.",
                            "observation_refs": refs[:3],
                            "assumptions": ["세부 메커니즘은 추가 관찰로 확인해야 합니다."],
                        }
                    ]
                    if refs
                    else []
                ),
                "limitations": ["일반 지식에 따른 가능한 해석이며 원인을 확정할 수 없습니다."],
                "suggested_checks": [],
            }
        elif output_model.__name__ == "ConceptDraft":
            definitions = {
                "meanIonEnergy": "평균 이온 에너지는 입사 이온이 지닌 에너지의 평균을 나타내는 지표입니다.",
                "ionFlux": "이온 플럭스는 단위 면적에 도달하는 이온의 유량을 나타내는 지표입니다.",
                "iedWidth": "이온 에너지 분포의 폭은 입사 이온들의 에너지가 퍼진 정도를 나타냅니다.",
            }
            topics = payload["evidence"]["topics"]
            value = {
                "status": "answered",
                "sections": [
                    {
                        "topic_refs": [topic],
                        "text": definitions.get(
                            topic, "공정 조건과 플라즈마 상태를 설명하기 위한 일반적인 개념입니다."
                        ),
                    }
                    for topic in topics
                ],
                "limitations": ["검토된 문헌을 조회하지 않은 일반 지식 설명입니다."],
            }
        else:
            raise AssertionError(f"Unexpected test model schema: {output_model.__name__}")
        # The same strict application contracts still validate every fixture reply.
        value = output_model.model_validate(value).model_dump(exclude_none=True)
        return value, {
            "model": "test-v1-deterministic",
            "reasoningEffort": "none",
            "inputTokens": 0,
            "outputTokens": 0,
        }

    @staticmethod
    def interpret(payload):
        question = payload["question"]
        ids = re.findall(r"RUN-[A-Za-z0-9_-]+", question)
        if len(ids) == 2:
            operation = {
                "kind": "explain_change" if "이유" in question else "compare_runs",
                "inputs": {
                    "baseline": {"kind": "run_id", "run_id": ids[0]},
                    "target": {"kind": "run_id", "run_id": ids[1]},
                    "metrics": ["meanIonEnergy", "ionFlux"],
                },
            }
        elif "정의" in question or "무엇" in question or "뭐야" in question:
            topic = "ionFlux" if "플럭스" in question else "meanIonEnergy"
            operation = {"kind": "explain_concept", "inputs": {"topics": [topic], "aspect": "definition"}}
        elif "Ion Flux는 높게, Mean Ion Energy는" in question:
            bounds = re.search(r"([\d.]+)–([\d.]+) eV", question)
            assert bounds is not None
            operation = {
                "kind": "reverse_search",
                "inputs": {
                    "constraints": [
                        {
                            "metric": "meanIonEnergy",
                            "operator": "between",
                            "min": float(bounds[1]),
                            "max": float(bounds[2]),
                            "unit": "eV",
                        }
                    ],
                    "goals": [{"metric": "ionFlux", "direction": "maximize"}],
                },
            }
        elif "최대화" in question and "플럭스" in question:
            operation = {
                "kind": "reverse_search",
                "inputs": {"goals": [{"metric": "ionFlux", "direction": "maximize"}]},
            }
        else:
            prior = payload.get("prior_interpretation") or {}
            previous = prior.get("operations", [])
            conditions = deepcopy(previous[0]["inputs"].get("conditions", {})) if len(previous) == 1 else {}
            text = (
                question + " " + " ".join(item.get("text", "") for item in payload.get("input_history", []))
            )
            for key, pattern in _CONDITIONS.items():
                matches = list(re.finditer(pattern, text))
                if matches:
                    match = matches[-1]
                    conditions[key] = {"value": float(match[1]), "unit": match[2]}
            if "biasPower" not in conditions and payload.get("input_history"):
                reply = payload["input_history"][-1].get("text", "").strip()
                match = re.fullmatch(rf"({_NUMBER})\s*(kW|W)", reply)
                if match:
                    conditions["biasPower"] = {"value": float(match[1]), "unit": match[2]}
            if not conditions:
                raise AssertionError("The offline fixture received a query outside the v1-live scenarios.")
            operation = {"kind": "forward_lookup", "inputs": {"conditions": conditions}}
        return {"status": "resolved", "operations": [operation]}


def main():
    parser = argparse.ArgumentParser(description="Offline model fixture for isolated v1 acceptance tests")
    parser.add_argument(
        "--connection", required=True, help="Ignored local JSON file containing url and token"
    )
    args = parser.parse_args()
    connection = json.loads(Path(args.connection).read_text())
    settings = replace(
        Settings(),
        backend_url=connection["url"],
        worker_token=connection["token"],
        model="test-v1-deterministic",
        reasoning_effort="none",
    )
    worker.ModelClient = RuntimeTestModel
    worker.serve(settings)


if __name__ == "__main__":
    main()
