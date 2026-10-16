"""M3: real submission, claim, durable graph and finalization; only tool LLM is fixed."""

import argparse
from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import sys
from threading import Event, Thread
import time
import uuid

import httpx

from seed import ROOT
from run import URL, append, identity, timeout_handler

sys.path.insert(0, str(Path(os.environ.get("REVERSE_AGENT_ROOT", str(ROOT))) / "agent/python/src"))
from kplasma_agent.backend_client import BackendClient
from kplasma_agent.config import Settings
from kplasma_agent.worker import run_claim
from kplasma_agent import tracing


class FixedSelection:
    def __init__(self, query):
        self.query = query

    def select_tool(self, instructions, payload):
        return {
            "name": "reverse_search",
            "arguments": self.query,
            "call_id": "benchmark-fixed",
        }, {"model": "benchmark-fixed", "responseItems": []}


def one(output, index, phoenix_env=None, scenario="match"):
    item = json.loads((output / "dataset.json").read_text())["corpus"][index]
    if scenario != "match":
        from run import query
        item["query"] = query("no_match") if scenario == "no_match" else {
            "constraints": [
                {"metric":"meanIonEnergy","operator":"between","min":150,"max":152,"unit":"eV"},
                {"metric":"iedWidth","operator":"eq","value":699.99,"unit":"eV"}
            ], "goals":[{"metric":"ionFlux","direction":"maximize","unit":"10¹⁸ m⁻²s⁻¹"}]
        }
    captured = {}
    from kplasma_agent.backend_client import RequestBackend
    old_context, old_save = RequestBackend.context, RequestBackend.save
    def context(self, *args, **kwargs):
        value = old_context(self, *args, **kwargs); captured["manifest"] = value; return value
    def save(self, payload):
        captured["checkpoint"] = payload; return old_save(self, payload)
    RequestBackend.context, RequestBackend.save = context, save
    settings = Settings(backend_url=URL, worker_token="benchmark-local-only")
    if phoenix_env is not None:
        from dotenv import dotenv_values

        values = dotenv_values(phoenix_env)
        settings = replace(
            settings,
            phoenix_endpoint=values.get("PHOENIX_COLLECTOR_ENDPOINT") or "",
            phoenix_api_key=values.get("PHOENIX_API_KEY") or "",
            phoenix_project_name=values.get("PHOENIX_PROJECT_NAME") or "K-PLASMA",
        )
        if not tracing.initialize(settings):
            raise RuntimeError(
                "Phoenix diagnostic was requested but tracing could not initialize"
            )
    backend = BackendClient(settings)
    events = []
    original_span = tracing.span

    def capture_error(response):
        if response.is_error:
            response.read()
            events.append(
                {
                    "name": "http.error",
                    "elapsedMs": 0,
                    "path": response.request.url.path,
                    "status": response.status_code,
                    "requestBytes": len(response.request.content),
                    "errorBody": response.text[:1500],
                }
            )

    backend.client.event_hooks["response"].append(capture_error)

    @contextmanager
    def timed_span(name, *args, **kwargs):
        start = time.perf_counter_ns()
        trace_id = None
        if phoenix_env is not None:
            kwargs["attributes"] = {
                **kwargs.get("attributes", {}),
                "benchmark.synthetic": True,
                "benchmark.phase": "reverse-lookup-M3-diagnostic",
            }
        try:
            with original_span(name, *args, **kwargs) as observation:
                if name == "agent.request" and observation.raw is not None:
                    trace_id = format(
                        observation.raw.get_span_context().trace_id, "032x"
                    )
                yield observation
        finally:
            event = {"name": name, "elapsedMs": (time.perf_counter_ns() - start) / 1e6}
            if trace_id:
                event["traceId"] = trace_id
            events.append(event)

    tracing.span = timed_span
    with httpx.Client(base_url=URL, timeout=60) as client:
        identity(client)
        # Each request starts with equivalent empty conversation state; reset is outside timing.
        token = client.get("/api/workspace").json()["stateToken"]
        cleared = client.post("/api/workspace/reset", json={"stateToken": token})
        cleared.raise_for_status()
        question = {
            "match":"평균 이온 에너지 150–160 eV, 이온 플럭스 높은 순 후보 조회",
            "no_match":"평균 이온 에너지 1000000000000–1000000000010 eV 후보 조회",
            "independent":"평균 이온 에너지 150–152 eV, IED 폭 699.99 eV와 같은 후보를 이온 플럭스 높은 순으로 조회",
        }[scenario]
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, 60)
        start = time.perf_counter_ns()
        record = {
            "index": index,
            "scenario": scenario,
            "ok": False,
            "phoenixEnabled": phoenix_env is not None,
        }
        stop = Event()
        try:
            submitted = client.post(
                "/api/agent/requests",
                json={"stateToken": cleared.json()["stateToken"], "text": question},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            submitted.raise_for_status()
            request_id = submitted.json()["requestId"]
            record["requestId"] = request_id
            claim = backend.claim("reverse-benchmark")
            assert claim["request"]["requestId"] == request_id
            bound = backend.bind(claim)

            def heartbeat():
                while not stop.wait(10):
                    try:
                        bound.stage()
                    except Exception:
                        return

            Thread(target=heartbeat, daemon=True).start()
            run_claim(claim, bound, FixedSelection(item["query"]), settings)
            finished = client.get("/api/agent/requests/" + request_id)
            finished.raise_for_status()
            value = finished.json()
            record.update(
                requestId=request_id, status=value["status"], error=value.get("error")
            )
            if value["status"] == "COMPLETED":
                result = value["answerSnapshot"]["result"]
                from seed import make_run
                expected_indices = list(reversed(range(5))) if scenario == "match" else []
                expected = [make_run(i)["runVersionId"] for i in expected_indices]
                common = result.get("commonRunRefs") or result.get("candidates", [])
                assert [r["runVersionId"] for r in common] == expected
                snapshots = result.get("runsByVersion")
                values = [snapshots[ref["runVersionId"]] for ref in common] if snapshots is not None else common
                assert [r["metrics"] for r in values] == [make_run(i)["metrics"] for i in expected_indices]
                if scenario != "match":
                    assert result["resultStatus"] == "NO_MATCH"
                    expected_pool = [] if scenario == "no_match" else [make_run(i)["runVersionId"] for i in range(3)]
                    # This functional gate uses the 150-row fixture; larger Q6 sets are checked by scenarios.py.
                    assert set(result.get("runsByVersion", {})) == set(expected_pool)
                record["ok"] = True
        except Exception as error:
            record.update(error=type(error).__name__, detail=str(error)[:500])
        finally:
            stop.set()
            signal.setitimer(signal.ITIMER_REAL, 0)
            record["totalMs"] = (time.perf_counter_ns() - start) / 1e6
            manifest = captured.get("manifest", {})
            record["manifestBytes"] = len(json.dumps(manifest, ensure_ascii=False).encode())
            record["manifestRuns"] = len(manifest.get("runs", []))
            record["catalogRefs"] = len(manifest.get("catalogRunRefs", []))
            record["checkpointBytes"] = len(json.dumps(captured.get("checkpoint", {}), ensure_ascii=False).encode())
            record["spans"] = events
            append(output / "m3.jsonl", record)
            print(
                json.dumps({k: v for k, v in record.items() if k != "spans"}),
                flush=True,
            )
            tracing.span = original_span
            backend.client.close()
            if phoenix_env is not None:
                tracing.shutdown()
    return record["ok"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument(
        "--phoenix-env",
        type=Path,
        help="Explicit optional env file; only Phoenix fields are read",
    )
    parser.add_argument("--scenario", choices=["match","no_match","independent"], default="match")
    args = parser.parse_args()
    raise SystemExit(0 if one(args.output, args.index, args.phoenix_env, args.scenario) else 1)
