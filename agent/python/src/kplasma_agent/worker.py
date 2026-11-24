"""Single-claim worker; PostgreSQL queue supports multiple independent processes."""

import argparse
import logging
import httpx
import signal
from threading import Event, Thread
import uuid

from langgraph.types import Command

from .backend_client import BackendClient, BackendError
from .config import Settings
from .graphs.registry import build_graph_for_version
from .v2.model_gateway import V2ModelGateway, V2Settings
from .v2.budget import check_payload
from .persistence.checkpointer import DurableSaver
from . import tracing
from .progress import ProgressReporter

LOG = logging.getLogger("kplasma.worker")


def _recovery_versions(v2_settings):
    return {
        "graphVersion": "v2", "graphBuildId": "v2-composite-1", "schemaVersion": "1",
        "planner": v2_settings.planner.model, "planEffort": v2_settings.planner.reasoning_effort,
        "writer": v2_settings.writer.model, "answerEffort": v2_settings.writer.reasoning_effort,
        "decisions": v2_settings.decisions_model,
    }


def run_claim(claim, backend, *, v2_models):
    request = claim.get("request") or {}
    if request.get("graphVersion") != "v2":
        backend.fail("GRAPH_VERSION_MISMATCH")
        return
    versions = _recovery_versions(v2_models.settings)
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
        observation.json_attribute("metadata", versions)
        _run_claim(claim, backend, observation, versions, v2_models=v2_models)


def _run_claim(claim, backend, observation, versions, *, v2_models):
    progress = getattr(backend, "progress", None) or ProgressReporter(None)
    check_id = progress.activity("QUESTION_CHECK")
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
        graph = build_graph_for_version("v2", backend, saver, v2_models=v2_models)
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
        if result.get("__interrupt__"):
            pending_value = result["__interrupt__"][0].value
            backend.needs_input(pending_value)
            observation.attribute("kplasma.outcome", "NEEDS_INPUT")
            observation.output(pending_value)
        else:
            backend.stage("commit")
            progress.activity("COMMIT")
            backend.finalize(result["answer"])
            observation.attribute("kplasma.outcome", "COMPLETED")
            observation.attribute("kplasma.result_status", result["answer"].get("status", ""))
            observation.output(result["answer"])
    except BackendError as error:
        # A lost write/lease must never turn into a fabricated success or an unfenced failure.
        if error.retryable or error.code in ("STALE_CLAIM", "STALE_CONTEXT", "REQUEST_NOT_FOUND"):
            raise
        observation.error(error)
        _fail_graph(backend, error)
    except Exception as error:
        observation.error(error)
        _fail_graph(backend, error)


def _fail_graph(backend, error):
    code = getattr(error, "code", None)
    if code is None:
        code = (
            str(error)
            if str(error).replace("_", "").isupper() and len(str(error)) <= 80
            else "GRAPH_EXECUTION_FAILED"
        )
    backend.fail(code)
    LOG.warning("request failed: %s", code)


def serve(settings, once=False):
    if not settings.worker_token:
        raise SystemExit("AGENT_WORKER_TOKEN must be configured in the backend and worker.")
    tracing.initialize(settings)
    client = BackendClient(settings)
    decisions = httpx.Client(timeout=settings.timeout, transport=httpx.HTTPTransport(retries=0))
    v2_models = V2ModelGateway(V2Settings.from_env(settings), decisions, check_payload)
    stopping = Event()
    worker_id = f"python-v2-{uuid.uuid4()}"

    def stop(*_):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("worker ready: graph=v2 planner=%s/%s",
             v2_models.settings.planner.model, v2_models.settings.planner.reasoning_effort)
    while not stopping.is_set():
        try:
            claim = client.claim(worker_id, ["v2"])
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
                run_claim(claim, backend, v2_models=v2_models)
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
    parser = argparse.ArgumentParser(description="K-PLASMA LangGraph v2 worker")
    parser.add_argument("--env-file")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # httpx/openai request logging can include remote URLs; keep routine logs minimal.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        serve(Settings.from_env(args.env_file), args.once)
    finally:
        tracing.shutdown()


if __name__ == "__main__":
    main()
