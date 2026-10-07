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

    def select_tool(self, _instructions, payload):
        operation = self.interpret(payload)["operations"][0]
        if operation["kind"] in ("compare_runs", "explain_change"):
            entries = payload.get("explicitReferences", {}).get("entries", [])
            wanted = re.findall(r"RUN-[A-Za-z0-9_-]+", payload["question"])
            keys = [e["key"] for e in entries if not wanted or e["ref"]["runId"] in wanted]
            operation = {
                "kind": "compare_runs",
                "inputs": {
                    "ref_keys": keys or None,
                    "metrics": ["meanIonEnergy", "ionFlux"],
                    "analysis": "interpretation" if "이유" in payload["question"] else "differences",
                    "baseline_key": keys[0] if len(keys) >= 2 else None,
                },
            }
        elif operation["kind"] == "explain_concept":
            operation = {"kind": "generate_answer", "inputs": {}}
        from kplasma_agent.tools import TOOL_MODELS

        inputs = TOOL_MODELS[operation["kind"]].model_validate(operation["inputs"]).model_dump()
        return {"call_id": "offline-call", "name": operation["kind"], "arguments": inputs}, {
            "model": "test-v1-deterministic",
            "responseItems": [],
        }

    def generate(self, _instructions, payload, output_model, **kwargs):
        refs = [
            item["id"]
            for item in payload["evidence"]["observations"]
            if item["source"]["kind"] == "comparison"
        ]
        value = {
            "observationIds": refs or [payload["evidence"]["observations"][0]["id"]],
            "interpretations": [
                {
                    "text": "관찰된 차이는 입자 생성과 손실의 변화에 관련됐을 수 있습니다.",
                    "observationIds": refs or [payload["evidence"]["observations"][0]["id"]],
                    "assumptions": ["일반적인 플라즈마 지식에 따른 가능한 해석입니다."],
                }
            ],
            "limitations": ["관찰된 차이만으로 원인을 확정할 수 없습니다."],
        }
        return output_model.model_validate(value).model_dump(), {"model": "test-v1-deterministic"}

    def answer(self, _instructions, payload, **kwargs):
        return (
            "평균 이온 에너지는 이온 에너지 분포의 평균입니다. 이온 에너지는 개별 이온의 에너지를 의미할 수 있습니다.",
            {"model": "test-v1-deterministic"},
        )

    @staticmethod
    def interpret(payload):
        question = payload["question"]
        ids = re.findall(r"RUN-[A-Za-z0-9_-]+", question)
        if len(ids) == 2 or (
            len(payload.get("explicitReferences", {}).get("entries", [])) >= 2
            and any(word in question for word in ("차이", "비교", "이유"))
        ):
            operation = {
                "kind": "explain_change" if "이유" in question else "compare_runs",
                "inputs": {
                    "baseline": {"kind": "run_id", "run_id": ids[0]} if ids else None,
                    "target": {"kind": "run_id", "run_id": ids[1]} if ids else None,
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
