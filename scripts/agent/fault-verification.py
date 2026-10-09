"""Crash/reclaim tests against an isolated synthetic Spring + PostgreSQL runtime.

No live model is used. Child processes execute the real graph and HTTP saver and
receive SIGKILL at selected boundaries. Only count/status summaries are printed.
The connection file must come from dev-verification.mjs; stop its live worker
before running this harness (the supervisor must remain alive).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "agent/python/src"))

import kplasma_agent.worker as worker_module
from kplasma_agent.backend_client import BackendClient, BackendError, RequestBackend
from kplasma_agent.config import Settings
from kplasma_agent.persistence.checkpointer import DurableSaver
from kplasma_agent.worker import run_claim


def connection(path):
    path = Path(path).resolve()
    runtime = (REPO / "agent/python/.runtime").resolve()
    if not path.is_relative_to(runtime) or not path.parent.name.startswith(
        "integration-"
    ):
        raise ValueError("Only an isolated integration runtime is permitted")
    metadata = json.loads(path.read_text())
    if (
        Path(metadata["output"]).resolve() != path.parent
        or not (path.parent / "synthetic").is_dir()
    ):
        raise ValueError("Synthetic runtime marker is missing")
    parsed = urlparse(metadata["url"])
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Only a local isolated backend is permitted")
    return metadata


def emit(path, event, **fields):
    with open(path, "a") as output:
        output.write(json.dumps({"event": event, **fields}) + "\n")
        output.flush()


class Crash:
    def __init__(self, spec):
        self.phase = spec.get("phase", "")
        self.events = spec["events"]

    def at(self, phase):
        if phase == self.phase:
            emit(self.events, "killed", phase=phase)
            os.kill(os.getpid(), signal.SIGKILL)


class DeterministicModel:
    def __init__(self, spec, crash):
        self.spec, self.crash = spec, crash

    def generate(self, instructions, payload, cls):
        name = cls.__name__
        emit(self.spec["events"], "model", stage=name)
        if name == "Interpretation":
            response = self.spec["interpretation"]
        elif name == "ConceptDraft":
            response = {
                "status": "answered",
                "sections": [
                    {
                        "topic_refs": ["ionFlux"],
                        "text": "이온 플럭스는 표면에 도달하는 이온의 양을 나타냅니다.",
                    }
                ],
                "limitations": ["일반 지식에 따른 설명입니다."],
            }
        else:
            response = {
                "status": "answered",
                "interpretations": [
                    {
                        "text": "관찰된 차이는 플라즈마 상태 변화와 관련될 수 있습니다.",
                        "observation_refs": ["metric_ionFlux"],
                        "assumptions": ["그 외 장비 조건이 같다고 가정합니다."],
                    }
                ],
                "limitations": ["일반 지식이며 인과관계를 확정할 수 없습니다."],
                "suggested_checks": ["나머지 운전 조건을 확인하세요."],
            }
        self.crash.at("after_model:" + name)
        return response, {"model": "deterministic-fault-test"}


class FaultBackend(RequestBackend):
    def __init__(self, client, claim, spec, crash):
        super().__init__(client, claim)
        self.crash, self.spec = crash, spec
        self.current_stage = "resume" if claim["inputEvents"] else "initial"
        self.request_id = claim["request"]["requestId"]

    def stage(self, stage=None, **fields):
        if stage:
            self.current_stage = stage
        return self.post("heartbeat", stage=stage, leaseSeconds=5, **fields)

    def checkpoint(self):
        self.crash.at("before_checkpoint_read")
        return super().checkpoint()

    def save(self, payload):
        self.crash.at("before_save:" + self.current_stage)
        answer = super().save(payload)
        self.crash.at("after_save:" + self.current_stage)
        if self.crash.phase == "after_input_checkpoint":
            saver = DurableSaver(payload["saver"], lambda _: None)
            state = saver.get_tuple({"configurable": {"thread_id": self.request_id}})
            if (
                state
                and len(
                    state.checkpoint.get("channel_values", {}).get("input_history", [])
                )
                == 1
            ):
                self.crash.at("after_input_checkpoint")
        return answer

    def needs_input(self, pending):
        self.crash.at("before_needs_input")
        answer = super().needs_input(pending)
        self.crash.at("after_needs_input")
        return answer

    def finalize(self, answer):
        self.crash.at("before_finalize")
        value = super().finalize(answer)
        self.crash.at("after_finalize")
        return value


def child(args):
    meta = connection(args.connection)
    spec = json.loads(Path(args.child).read_text())
    settings = Settings(backend_url=meta["url"], worker_token=meta["workerToken"])
    if spec.get("mismatch"):
        settings = replace(
            settings, graph_build_id="intentionally-incompatible-fault-test"
        )
    client = BackendClient(settings)
    claim = client.call(
        "POST", "claim", json={"workerId": "fault-test-child", "leaseSeconds": 5}
    )
    if claim.get("request") is None:
        emit(spec["events"], "no_work")
        return
    if claim["request"]["requestId"] != spec["requestId"]:
        raise RuntimeError(
            "Another worker/request is interfering with the isolated test"
        )
    emit(spec["events"], "claim", generation=claim["claimGeneration"])
    crash = Crash(spec)
    original_fail = worker_module._fail_graph

    def diagnostic_failure(backend, graph, config, error):
        # Local synthetic diagnostics only. No provider/network payloads are read.
        emit(
            spec["events"],
            "failure",
            errorType=type(error).__name__,
            message=str(error)[:300],
        )
        return original_fail(backend, graph, config, error)

    worker_module._fail_graph = diagnostic_failure
    run_claim(
        claim,
        FaultBackend(client, claim, spec, crash),
        DeterministicModel(spec, crash),
        settings,
    )
    emit(spec["events"], "returned")


class Harness:
    def __init__(self, path):
        self.connection = str(Path(path).resolve())
        self.meta = connection(path)
        self.api = httpx.Client(base_url=self.meta["url"], timeout=30)
        self.internal = BackendClient(
            Settings(
                backend_url=self.meta["url"], worker_token=self.meta["workerToken"]
            )
        )
        self.output = Path(self.meta["output"]) / ("fault-" + str(int(time.time())))
        self.output.mkdir()
        self.results = []
        # Catalog identifiers are local artificial fixtures, not evidence of physics.
        self.runs = self.get("/api/runs")
        if len(self.runs) != 3 or sorted(run["pressure"] for run in self.runs) != [
            2,
            4,
            6,
        ]:
            raise ValueError("Expected the dedicated three-Run synthetic runtime")
        # Clear only the verified ephemeral synthetic conversation; source Runs stay.
        state = self.get("/api/workspace")
        self.post(
            "/api/workspace/new-conversation", {"stateToken": state["stateToken"]}
        )

    def get(self, path):
        response = self.api.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path, body, key=None):
        response = self.api.post(
            path, json=body, headers={"Idempotency-Key": key or str(uuid4())}
        )
        response.raise_for_status()
        return response.json()

    def submit(self, kind="forward_lookup", missing=False):
        state = self.get("/api/workspace")
        if state.get("activeAgentRequest"):
            raise RuntimeError(
                "Isolated backend already has an active request; stop its worker first"
            )
        baseline, target = self.runs[:2]
        if kind == "forward_lookup":
            conditions = {
                key: {
                    "value": baseline[key],
                    "unit": "mTorr" if key == "pressure" else "W",
                }
                for key in ("pressure", "sourcePower", "biasPower")
                if not (missing and key == "biasPower")
            }
            inputs = {"conditions": conditions}
            question = (
                " ".join(
                    f"{key} {value['value']} {value['unit']}"
                    for key, value in conditions.items()
                )
                + " 결과를 조회해줘"
            )
        elif kind == "explain_change":
            inputs = {
                "baseline": {"kind": "run_id", "run_id": baseline["runId"]},
                "target": {"kind": "run_id", "run_id": target["runId"]},
                "metrics": ["ionFlux"],
            }
            question = f"{baseline['runId']} 기준으로 {target['runId']}의 플럭스 변화 이유를 설명해줘"
        elif kind == "reverse_search":
            inputs = {"goals": [{"metric": "ionFlux", "direction": "maximize"}]}
            question = "이온 플럭스가 가장 높은 Run을 찾아줘"
        else:
            inputs = {"topics": ["ionFlux"], "aspect": "definition"}
            question = "이온 플럭스가 뭐야?"
        accepted = self.post(
            "/api/agent/requests", {"text": question, "stateToken": state["stateToken"]}
        )
        expected = []
        if kind == "forward_lookup":
            expected = [baseline]
        elif kind == "reverse_search":
            expected = sorted(self.runs, key=lambda run: -run["metrics"]["ionFlux"])
        return {
            "requestId": accepted["requestId"],
            "expectedRuns": expected,
            "interpretation": {
                "status": "resolved",
                "operations": [{"kind": kind, "inputs": inputs}],
            },
        }

    def run_child(self, spec, phase="", mismatch=False):
        spec = {**spec, "phase": phase, "mismatch": mismatch}
        path = self.output / (spec["requestId"] + ".json")
        path.write_text(json.dumps(spec))
        path.chmod(0o600)
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--connection",
                self.connection,
                "--child",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
        if phase:
            assert result.returncode == -signal.SIGKILL, (
                f"{phase}: expected SIGKILL, got {result.returncode}; {result.stderr[-300:]}"
            )
        else:
            assert result.returncode == 0, (
                f"recovery failed ({result.returncode}): {result.stderr[-300:]}"
            )
        return result

    def state(self, spec):
        return self.get("/api/agent/requests/" + spec["requestId"])

    def recover(self, spec):
        # Test leases are shortened through the real heartbeat API, never SQL edits.
        time.sleep(5.2)
        self.run_child(spec)

    def assert_completed_once(self, spec, inputs=0):
        state = self.state(spec)
        assert state["status"] == "COMPLETED", (
            f"expected completion, got {state['status']}: {(state.get('error') or {}).get('code')}"
        )
        turns = self.get("/api/workspace")["conversation"]["turns"]
        turns = [turn for turn in turns if turn["id"] == spec["requestId"]]
        assert len(turns) == 1
        assert len(turns[0]["answerSnapshot"]["inputHistory"]) == inputs
        result = turns[0]["answerSnapshot"]["result"]
        expected = spec.get("expectedRuns", [])
        if expected:
            actual = result["candidates"]
            assert len(actual) == len(expected), "Recovered candidate count changed"
            for actual_run, expected_run in zip(actual, expected, strict=True):
                for field in (
                    "runId",
                    "runVersionId",
                    "pressure",
                    "sourcePower",
                    "biasPower",
                ):
                    assert actual_run[field] == expected_run[field], (
                        f"Recovered {field} changed"
                    )
                for metric in ("meanIonEnergy", "ionFlux", "iedWidth"):
                    assert actual_run["metrics"].get(metric) == expected_run[
                        "metrics"
                    ].get(metric), f"Recovered {metric} changed"
        return state

    def publish_changed_versions(self):
        """Change only this disposable runtime's synthetic source and re-import publicly."""
        source = Path(self.meta["output"]) / "synthetic"
        changes = [
            (
                2,
                "AVERAGE ION ENERGY AT THE SUBSTRATE",
                f"{999 + len(self.results)} # synthetic recovery probe",
            ),
            (6, "ION FLUX AT THE SHEATH EDGE", "1.e10"),
        ]
        for pressure, heading, replacement in changes:
            path = source / f"artificial-{pressure}/0d_result/log/solver.log"
            text = path.read_text()
            pattern = r"(\[" + re.escape(heading) + r"\][\s\S]*?\nAr\+ )[^\n]+"
            changed, count = re.subn(
                pattern, lambda match, value=replacement: match[1] + value, text, count=1
            )
            assert count == 1
            path.write_text(changed)
        files = sorted(path for path in source.rglob("*") if path.is_file())
        entries = [
            {"partName": f"file{i}", "relativePath": str(path.relative_to(source))}
            for i, path in enumerate(files)
        ]
        parts = {
            entry["partName"]: ("file", path.read_bytes(), "application/octet-stream")
            for entry, path in zip(entries, files, strict=True)
        }
        parts["manifest"] = (
            None,
            json.dumps({"mode": "FOLDER", "entries": entries}),
            "application/json",
        )
        response = self.api.post(
            "/api/import-batches",
            files=parts,
            headers={"Idempotency-Key": str(uuid4())},
        )
        response.raise_for_status()
        batch_id = response.json()["batchId"]
        for _ in range(120):
            batch = self.get("/api/import-batches/" + batch_id)
            if batch["status"] in ("SUCCESS", "PARTIAL_SUCCESS", "FAILED"):
                assert batch["status"] == "SUCCESS"
                return self.get("/api/runs")
            time.sleep(0.1)
        raise AssertionError("Synthetic version publication timed out")

    def pinned_numeric_recovery(self, kind):
        spec = self.submit(kind)
        name = "pinned_versions_and_" + (
            "scalars" if kind == "forward_lookup" else "candidate_order"
        )
        spec["events"] = str(self.output / (name + ".jsonl"))
        self.run_child(
            spec, "after_save:" + ("forward" if kind == "forward_lookup" else "reverse")
        )
        latest = self.publish_changed_versions()
        before = {run["runId"]: run for run in self.runs}
        assert any(
            run["runVersionId"] != before[run["runId"]]["runVersionId"]
            for run in latest
        )
        if kind == "reverse_search":
            assert [
                run["runId"]
                for run in sorted(latest, key=lambda run: -run["metrics"]["ionFlux"])
            ] != [run["runId"] for run in spec["expectedRuns"]]
        self.recover(spec)
        self.assert_completed_once(spec)
        self.results.append({"case": name, "status": "PASS"})
        # Keep captured catalog inputs for later requests aligned with the live fixture.
        self.runs = latest

    def events(self, spec):
        path = Path(spec["events"])
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def case(self, name, phase, kind="forward_lookup", expect_model_calls=None):
        spec = self.submit(kind)
        spec["events"] = str(self.output / (name + ".jsonl"))
        self.run_child(spec, phase)
        if self.state(spec)["status"] != "COMPLETED":
            self.recover(spec)
        self.assert_completed_once(spec)
        if expect_model_calls is not None:
            calls = sum(event["event"] == "model" for event in self.events(spec))
            assert calls == expect_model_calls, (
                f"{name}: expected {expect_model_calls} model calls, got {calls}"
            )
        self.results.append({"case": name, "status": "PASS"})

    def interrupt_case(self, name, phase, resume_phase=""):
        spec = self.submit(missing=True)
        spec["events"] = str(self.output / (name + ".jsonl"))
        if phase:
            self.run_child(spec, phase)
        else:
            self.run_child(spec)
        if self.state(spec)["status"] != "NEEDS_INPUT":
            self.recover(spec)
        state = self.state(spec)
        assert state["status"] == "NEEDS_INPUT"
        reply = {
            "expectedRequestRevision": state["requestRevision"],
            "pendingInputId": state["pendingInput"]["id"],
            "input": {
                "conditions": {
                    "biasPower": {"value": self.runs[0]["biasPower"], "unit": "W"}
                }
            },
        }
        key = str(uuid4())
        path = "/api/agent/requests/" + spec["requestId"] + "/resume"
        self.post(path, reply, key)
        self.post(path, reply, key)
        if resume_phase:
            self.run_child(spec, resume_phase)
            self.recover(spec)
        else:
            self.run_child(spec)
        self.assert_completed_once(spec, inputs=1)
        assert sum(event["event"] == "model" for event in self.events(spec)) == 1
        self.results.append({"case": name, "status": "PASS"})

    def stale_generation(self):
        spec = self.submit()
        spec["events"] = str(self.output / "stale-generation.jsonl")
        old = self.internal.call(
            "POST", "claim", json={"workerId": "old-test-worker", "leaseSeconds": 5}
        )
        stale = self.internal.bind(old)
        stale.save({"versions": Settings().versions(), "saver": None})
        time.sleep(5.2)
        fresh = self.internal.call(
            "POST", "claim", json={"workerId": "new-test-worker", "leaseSeconds": 5}
        )
        assert fresh["claimGeneration"] > old["claimGeneration"]
        try:
            stale.save({"corrupt": True})
        except BackendError as error:
            assert error.code == "STALE_CLAIM"
        else:
            raise AssertionError("Stale worker checkpoint was accepted")
        selected = self.runs[0]
        ref = {key: selected[key] for key in ("runId", "runVersionId")}
        try:
            stale.finalize(
                {
                    "intent": "FORWARD_LOOKUP",
                    "status": "SUCCESS",
                    "candidates": [],
                    "usedRunRefs": [ref],
                    "answerSnapshot": {
                        "implementationId": "v1",
                        "kind": "forward_lookup",
                        "summary": "synthetic stale worker",
                        "result": {"run": selected},
                    },
                }
            )
        except BackendError as error:
            assert error.code == "STALE_CLAIM"
        else:
            raise AssertionError("Stale worker finalization was accepted")
        assert self.state(spec)["status"] == "RUNNING"
        assert all(
            turn["id"] != spec["requestId"]
            for turn in self.get("/api/workspace")["conversation"]["turns"]
        )
        backend = self.internal.bind(fresh)
        run_claim(fresh, backend, DeterministicModel(spec, Crash(spec)), Settings())
        self.assert_completed_once(spec)
        self.results.append(
            {"case": "stale_generation_checkpoint_and_finalize_fence", "status": "PASS"}
        )

    def mismatch(self):
        spec = self.submit()
        spec["events"] = str(self.output / "version-mismatch.jsonl")
        self.run_child(spec, "after_save:forward")
        time.sleep(5.2)
        self.run_child(spec, mismatch=True)
        state = self.state(spec)
        assert (
            state["status"] == "FAILED"
            and state["error"]["code"] == "RECOVERY_VERSION_MISMATCH"
        )
        self.results.append({"case": "configuration_mismatch", "status": "PASS"})

    def run(self):
        self.case("before_numeric_checkpoint", "before_save:forward")
        self.case(
            "after_numeric_checkpoint", "after_save:forward", expect_model_calls=1
        )
        self.case(
            "model_return_before_draft_checkpoint",
            "after_model:ConceptDraft",
            "explain_concept",
            expect_model_calls=3,
        )
        self.case(
            "after_draft_checkpoint",
            "after_save:generate_explanation",
            "explain_concept",
            expect_model_calls=2,
        )
        self.case(
            "after_explanation_validation",
            "after_save:validate_explanation",
            "explain_concept",
            expect_model_calls=2,
        )
        self.case(
            "change_after_draft_checkpoint",
            "after_save:generate_explanation",
            "explain_change",
            expect_model_calls=2,
        )
        self.case("before_finalize", "before_finalize", expect_model_calls=1)
        self.case(
            "finalize_committed_response_lost", "after_finalize", expect_model_calls=1
        )
        self.interrupt_case("interrupt_checkpoint_before_status", "before_needs_input")
        self.interrupt_case("saved_input_before_apply", "", "before_checkpoint_read")
        self.interrupt_case("saved_input_after_apply", "", "after_input_checkpoint")
        self.stale_generation()
        self.mismatch()
        self.pinned_numeric_recovery("reverse_search")
        self.pinned_numeric_recovery("forward_lookup")
        report = {
            "model": "deterministic mock (no provider calls)",
            "persistence": "Spring HTTP + PostgreSQL",
            "processFault": "SIGKILL + lease expiry + fresh process",
            "cases": self.results,
        }
        (self.output / "summary.json").write_text(json.dumps(report, indent=2))
        print(
            json.dumps(
                {
                    "passed": len(self.results),
                    "failed": 0,
                    "summary": str(self.output / "summary.json"),
                }
            )
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connection", required=True)
    parser.add_argument("--child")
    args = parser.parse_args()
    if args.child:
        child(args)
    else:
        Harness(args.connection).run()


if __name__ == "__main__":
    main()
