"""Real-model, synthetic full-graph scenarios; local evidence and Phoenix only."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from dataclasses import replace
import json
from pathlib import Path
import time

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from kplasma_agent import tracing
from kplasma_agent.config import Settings
from kplasma_agent.graphs.v1 import build_graph
from kplasma_agent.model_client import ModelClient
from .cases import ACCEPTANCE_CASES, _refs
from .judge import judge


def synthetic_runs():
    return [
        {
            "runId": f"SYNTHETIC-{i}",
            "runVersionId": f"synthetic-{i}",
            "pressure": 8,
            "sourcePower": 300 + i * 100,
            "biasPower": 600,
            "metrics": {"ionFlux": i * 10, "meanIonEnergy": 154 + i, "iedWidth": 20 + i},
            "units": {
                "pressure": "mTorr",
                "sourcePower": "W",
                "biasPower": "W",
                "ionFlux": "10¹⁸ m⁻²s⁻¹",
                "meanIonEnergy": "eV",
                "iedWidth": "eV",
            },
            "convergenceStatus": "CONVERGED",
            "qualityStatus": "VERIFIED",
            "catalogStatus": "READY",
            "presentationScore": 100,
            "analysis": {"hasDistribution": False},
            "sourceFileCount": 0,
        }
        for i in range(5)
    ]


class Backend:
    def __init__(self):
        self.reads = 0
        self.stages = []

    def stage(self, stage, **kwargs):
        self.stages.append(stage)

    def attempt(self, *args):
        pass

    def context(self, refs=None, **kwargs):
        self.reads += 1
        runs = synthetic_runs()
        if refs:
            return {
                "runs": [],
                "referencedRuns": [r for r in runs if {k: r[k] for k in ("runId", "runVersionId")} in refs],
            }
        return {"runs": runs, "referencedRuns": [], "context": {}}


class RecordingModel:
    def __init__(self, settings):
        self.client = ModelClient(settings)
        self.api_calls = 0
        self.usage = []

    def call(self, method, *args, **kwargs):
        self.api_calls += 1
        value, metadata = getattr(self.client, method)(*args, **kwargs)
        self.usage.append({"role": method, **{k: v for k, v in metadata.items() if k != "responseItems"}})
        return value, metadata

    def select_tool(self, *args, **kwargs):
        return self.call("select_tool", *args, **kwargs)

    def generate(self, *args, **kwargs):
        return self.call("generate", *args, **kwargs)

    def answer(self, *args, **kwargs):
        return self.call("answer", *args, **kwargs)


def attempt(case, repeat, settings):
    started = time.monotonic()
    backend = Backend()
    request_id = f"synthetic-acceptance-{case.id}-{repeat}"
    model = RecordingModel(settings)
    graph = build_graph(model, backend, settings, InMemorySaver())
    config = {"configurable": {"thread_id": request_id}, "recursion_limit": 80}
    record = {"caseId": case.id, "repeat": repeat, "question": case.question, "passed": False}
    try:
        with tracing.span(
            "eval.full_graph",
            kind="AGENT",
            session_id=request_id,
            inputs={"question": case.question, "synthetic": True},
        ) as span:
            result = graph.invoke(
                {
                    "request_id": request_id,
                    "question": case.question,
                    "context": {"comparisonReference": {"entries": case.references, "baselineKey": None}},
                    "input_history": [],
                },
                config,
            )
            record["selectionAssessment"] = judge(case, result["tool_selection"])
            pending = []
            for _ in range(4):
                if not result.get("__interrupt__"):
                    break
                item = result["pending"]
                pending.append(item)
                if item["type"] == "run_selection":
                    entries = [
                        {
                            **e,
                            "origin": {
                                "kind": "hitl",
                                "turnId": None,
                                "groupId": None,
                                "pendingInputId": item["id"],
                            },
                        }
                        for e in _refs[:2]
                    ]
                    reply = {
                        "type": "run_selection",
                        "runKeys": ["R1", "R2"],
                        "baselineKey": "R1" if item["baselineRequired"] else None,
                        "comparisonReference": {
                            "entries": entries,
                            "baselineKey": "R1" if item["baselineRequired"] else None,
                        },
                    }
                elif item["type"] == "comparison_options":
                    reply = {
                        "type": "comparison_options",
                        **{
                            field: "R1" if field == "baselineKey" else "sourcePower"
                            for field in item["fields"]
                        },
                    }
                else:
                    reply = {
                        "type": "text",
                        "text": "소스 전력 단위는 와트입니다"
                        if case.id == "AE2"
                        else "평균 이온 에너지 단위는 e볼트입니다",
                    }
                result = graph.invoke(Command(resume=reply), config)
            snapshot = result.get("answer", {}).get("answerSnapshot")
            record.update(
                pending=pending,
                snapshot=snapshot,
                metadata=result.get("model_metadata"),
                passed=bool(snapshot) and record["selectionAssessment"]["passed"],
            )
            if snapshot:
                expected_refs = case.references if len(case.references) >= 2 else _refs[:2]
                if case.kind == "compare_runs":
                    record["passed"] &= snapshot["usedRunRefs"] == [e["ref"] for e in expected_refs]
                if case.kind == "generate_answer":
                    record["passed"] &= backend.reads == 0 and snapshot["originalQuestion"] == case.question
                if case.id in ("AE2", "AE4"):
                    record["passed"] &= bool(pending) and pending[0].get("reason") == "MISSING_UNIT"
            span.output(record)
    except Exception as error:
        record["errorCode"] = getattr(error, "code", type(error).__name__)
    record.update(
        contextReads=backend.reads,
        stages=backend.stages,
        apiCalls=model.api_calls,
        usage=model.usage,
        elapsedSeconds=round(time.monotonic() - started, 3),
    )
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3, choices=range(1, 4))
    parser.add_argument("--concurrency", type=int, default=3, choices=range(1, 5))
    args = parser.parse_args()
    settings = replace(Settings.from_env(), model="gpt-5.6-luna", reasoning_effort="none")
    if not settings.api_key:
        parser.error("OPENAI_API_KEY is not configured")
    destination = (
        Path(__file__).resolve().parents[1]
        / ".runtime"
        / "full-graph-evals"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    destination.mkdir(parents=True)
    traced = tracing.initialize(settings)
    records = []
    try:
        with (
            (destination / "attempts.jsonl").open("w") as stream,
            ThreadPoolExecutor(max_workers=args.concurrency) as executor,
        ):
            futures = [
                executor.submit(attempt, case, repeat, settings)
                for repeat in range(1, args.repeat + 1)
                for case in ACCEPTANCE_CASES
            ]
            for future in as_completed(futures):
                record = future.result()
                records.append(record)
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
    finally:
        tracing.shutdown()
    summary = {
        "attempts": len(records),
        "passed": sum(r["passed"] for r in records),
        "phoenixEnabled": traced,
        "model": settings.model,
        "reasoningEffort": settings.reasoning_effort,
        "inputTokens": sum(m.get("inputTokens", 0) for r in records for m in r["usage"]),
        "outputTokens": sum(m.get("outputTokens", 0) for r in records for m in r["usage"]),
        "apiCalls": sum(r["apiCalls"] for r in records),
        "failures": [
            {"caseId": r["caseId"], "repeat": r["repeat"], "errorCode": r.get("errorCode")}
            for r in records
            if not r["passed"]
        ],
        "scope": "Synthetic full graph; scientific explanation correctness still requires semantic review.",
        "localOutputDirectory": str(destination),
    }
    (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == summary["attempts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
