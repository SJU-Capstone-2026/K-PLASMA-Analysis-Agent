"""Single-version v3 worker; frozen graph modules remain independent."""

import argparse
import logging
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
import httpx
import signal
from threading import Event, Thread
import uuid

from langgraph.types import Command

from .backend_client import BackendClient, BackendError
from .config import Settings
from .graph import build_v3_graph
from .core.backend import V3ExecutionPort
from .core.model_gateway import V3ModelGateway, V3Settings
from .core.budget import check_payload
from .persistence.checkpointer import DurableSaver
from . import tracing
from .progress import ProgressReporter

LOG = logging.getLogger("kplasma.v3.worker")


def resolve_env_file(value):
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("explicit v3 env file must be a regular file")
    return path


def runtime_versions(settings, models):
    root = Path(__file__).parent
    fields = {
        "graphVersion": "v3", "implementationId": "v3", "graphBuildId": settings.graph_build_id,
        "schemaVersion": "1", "planSchemaVersion": "2",
        "planner": models.planner.model, "planEffort": models.planner.reasoning_effort,
        "writer": models.writer.model, "answerEffort": models.writer.reasoning_effort,
        "decisions": models.decisions_model, "decisionsUrl": models.decisions_url,
        "planReviewEnabled": models.plan_review_enabled, "timeout": settings.timeout,
        "cloneManifestHash": hashlib.sha256((root / "clone-manifest.json").read_bytes()).hexdigest(),
        "budgetConfigHash": hashlib.sha256(json.dumps({
            k: v for k, v in os.environ.items() if k.startswith("AGENT_V3_")
        }, sort_keys=True).encode()).hexdigest(),
    }
    fields["configFingerprint"] = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
    return fields


def run_claim(claim, backend, settings, *, models):
    request = claim.get("request") or {}
    if request.get("graphVersion") != "v3":
        backend.fail("GRAPH_VERSION_MISMATCH")
        return
    request = claim.get("request") or {}
    with tracing.span(
        "agent.request",
        kind="AGENT",
        session_id=request.get("requestId"),
        inputs={
            "request": request,
            "context": claim.get("context"),
            "inputEvents": claim.get("inputEvents", []),
        },
        attributes={
            "kplasma.request_id": request.get("requestId", ""),
            "kplasma.claim_generation": claim.get("claimGeneration", 0),
            "kplasma.request_revision": claim.get("requestRevision", 0),
        },
    ) as observation:
        observation.json_attribute("metadata", runtime_versions(settings, models.settings))
        _run_claim(claim, backend, settings, observation, models=models)


def _run_claim(claim, backend, settings, observation, *, models):
    progress = getattr(backend, "progress", None) or ProgressReporter(None)
    check_id = progress.activity("QUESTION_CHECK")
    versions = runtime_versions(settings, models.settings)
    payload = backend.checkpoint()
    observation.attribute("kplasma.resumed", bool(payload))
    if payload and payload.get("versions") != versions:
        backend.fail("RECOVERY_VERSION_MISMATCH")
        observation.error(BackendError("RECOVERY_VERSION_MISMATCH"))
        return
    request = claim["request"]
    config = {"configurable": {"thread_id": request["requestId"]}, "recursion_limit": 80}
    try:
        saver = DurableSaver(
            (payload or {}).get("saver"), lambda data: backend.save({"versions": versions, "saver": data})
        )
        graph = build_v3_graph(models, V3ExecutionPort(backend), saver)
        saved = graph.get_state(config)
        progress.activity("QUESTION_CHECK", "completed", identity=check_id)
    except Exception:
        backend.fail("RECOVERY_STATE_INVALID")
        observation.error(BackendError("RECOVERY_STATE_INVALID"))
        return
    graph_input: Command | dict | None
    if saved.values:
        pending = any(task.interrupts for task in saved.tasks)
        if pending:
            history_size = len(saved.values.get("input_history", []))
            events = claim.get("inputEvents", [])
            if len(events) <= history_size:
                pending_value = next(item.value for task in saved.tasks for item in task.interrupts)
                backend.needs_input(pending_value)
                observation.attribute("kplasma.outcome", "NEEDS_INPUT")
                observation.output(pending_value)
                return
            graph_input = Command(resume=events[history_size]["input"])
        else:
            graph_input = None
    else:
        graph_input = {
            "request_id": request["requestId"],
            "question": request["question"],
            "context": claim.get("context") or {},
            "input_history": [],
        }
    try:
        result = (
            graph.invoke(graph_input, config, durability="sync")
            # Pending writes can make get_state().next empty before the next
            # superstep is materialized. Only a durable answer proves the graph
            # reached its terminal result; otherwise invoke reconciles writes.
            if saved.next or "answer" not in saved.values
            else saved.values
        )
        observation.attribute("kplasma.operation", result.get("operation", {}).get("kind", ""))
        if result.get("__interrupt__"):
            pending_value = result["__interrupt__"][0].value
            backend.needs_input(pending_value)
            observation.attribute("kplasma.outcome", "NEEDS_INPUT")
            observation.output(pending_value)
        else:
            backend.stage("commit")
            progress.activity("COMMIT")
            snapshot = result["answer"].get("answerSnapshot") or {}
            if (snapshot.get("graphVersion") != "v3"
                    or snapshot.get("implementationId") != "v3"):
                raise ValueError("GRAPH_VERSION_MISMATCH")
            backend.finalize(result["answer"])
            observation.attribute("kplasma.outcome", "COMPLETED")
            observation.attribute("kplasma.result_status", result["answer"].get("status", ""))
            observation.output(result["answer"])
    except BackendError as error:
        # A lost write/lease must never turn into a fabricated success or an unfenced failure.
        if error.retryable or error.code in ("STALE_CLAIM", "STALE_CONTEXT", "REQUEST_NOT_FOUND"):
            raise
        observation.error(error)
        _fail_graph(backend, graph, config, error)
    except Exception as error:
        observation.error(error)
        _fail_graph(backend, graph, config, error)


def _fail_graph(backend, graph, config, error):
    code = getattr(error, "code", None)
    if code is None:
        code = (
            str(error)
            if str(error).replace("_", "").isupper() and len(str(error)) <= 80
            else "GRAPH_EXECUTION_FAILED"
        )
    try:
        state = graph.get_state(config).values
    except Exception:
        state = {}
    partial = None
    if state.get("verified") and state.get("operation", {}).get("kind") in ("explain_change", "compare_runs"):
        partial = {**state["result"], "explanationComplete": False}
        if state["operation"]["kind"] == "compare_runs":
            partial["schemaVersion"] = 3 if "featurePolicyVersion" in partial else 2
    backend.fail(code, partial)
    LOG.warning("request failed: %s", code)


def serve(settings, once=False):
    if not settings.worker_token:
        raise SystemExit("AGENT_WORKER_TOKEN must be configured in the backend and worker.")
    tracing.initialize(settings)
    client = BackendClient(settings)
    decisions = httpx.Client(timeout=settings.timeout, transport=httpx.HTTPTransport(retries=0))
    models = V3ModelGateway(V3Settings.from_env(settings), decisions, check_payload)
    stopping = Event()
    worker_id = f"python-v3-{uuid.uuid4()}"

    def stop(*_):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("worker ready: graph=v3 planner=%s/%s",
             models.settings.planner.model, models.settings.planner.reasoning_effort)
    while not stopping.is_set():
        try:
            claim = client.claim(worker_id, ["v3"])
            if claim.get("request") is None:
                if once:
                    return
                stopping.wait(settings.poll_seconds)
                continue
            backend = client.bind(claim)
            heartbeat_stop = Event()

            def heartbeat(bound_backend=backend, stop_event=heartbeat_stop):
                while not stop_event.wait(10):
                    try:
                        bound_backend.stage()
                    except BackendError:
                        # Subsequent checkpoint/finalization is still fenced server-side.
                        return

            pulse = Thread(target=heartbeat, daemon=True)
            pulse.start()
            try:
                run_claim(claim, backend, settings, models=models)
            finally:
                heartbeat_stop.set()
                pulse.join(timeout=1)
        except BackendError as error:
            LOG.warning("worker transport: %s", error.code)
            if error.code in ("UNAUTHORIZED", "WORKER_NOT_CONFIGURED"):
                raise SystemExit(error.code) from None
            if not once:
                stopping.wait(3)
        if once:
            return


def main():
    parser = argparse.ArgumentParser(description="K-PLASMA independent v3 worker")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        env_file = resolve_env_file(args.env_file)
    except (OSError, ValueError):
        parser.error("--env-file must select an existing regular file")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # httpx/openai request logging can include remote URLs; keep routine logs minimal.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        serve(replace(Settings.from_env(env_file), graph_build_id="v3-composite-1"), args.once)
    finally:
        tracing.shutdown()


if __name__ == "__main__":
    main()
