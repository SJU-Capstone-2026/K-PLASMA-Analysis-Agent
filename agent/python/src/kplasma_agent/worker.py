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
from .model_client import ModelClient
from .persistence.checkpointer import DurableSaver
from . import tracing
from .progress import ProgressReporter

LOG = logging.getLogger("kplasma.worker")


def run_claim(claim, backend, model, settings, *, v2_models=None):
    request = claim.get("request") or {}
    if request.get("graphVersion") == "v3":
        from .v3.runtime_worker import run_v3_claim

        return run_v3_claim(claim)
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
        observation.json_attribute("metadata", settings.versions())
        _run_claim(claim, backend, model, settings, observation, v2_models=v2_models)


def _run_claim(claim, backend, model, settings, observation, *, v2_models=None):
    progress = getattr(backend, "progress", None) or ProgressReporter(None)
    check_id = progress.activity("QUESTION_CHECK")
    version = (claim.get("request") or {}).get("graphVersion", "v1")
    versions = settings.versions()
    if version == "v2" and v2_models is not None:
        v2 = v2_models.settings
        versions = {
            "graphVersion": "v2", "graphBuildId": "v2-composite-1", "schemaVersion": "1",
            "planner": v2.planner.model, "planEffort": v2.planner.reasoning_effort,
            "writer": v2.writer.model, "answerEffort": v2.writer.reasoning_effort,
            "decisions": v2.decisions_model,
        }
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
        graph = build_graph_for_version(version, model, backend, settings, saver, v2_models=v2_models)
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
                pending_value = (next(item.value for task in saved.tasks for item in task.interrupts)
                                 if version == "v2" else saved.values["pending"])
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
            pending_value = result["__interrupt__"][0].value if version == "v2" else result["pending"]
            backend.needs_input(pending_value)
            observation.attribute("kplasma.outcome", "NEEDS_INPUT")
            observation.output(pending_value)
        else:
            backend.stage("commit")
            if version == "v2":
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
    model = ModelClient(settings)
    decisions = httpx.Client(timeout=settings.timeout, transport=httpx.HTTPTransport(retries=0))
    v2_models = V2ModelGateway(V2Settings.from_env(settings), decisions, check_payload)
    stopping = Event()
    worker_id = f"python-v1-v2-{uuid.uuid4()}"

    def stop(*_):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("worker ready: graphs=v1,v2,v3 v1_model=%s v2_planner=%s/%s",
             settings.model, v2_models.settings.planner.model, v2_models.settings.planner.reasoning_effort)
    while not stopping.is_set():
        try:
            claim = client.claim(worker_id, ["v1", "v2", "v3"])
            if claim.get("request") is None:
                if once:
                    return
                stopping.wait(settings.poll_seconds)
                continue
            if claim["request"].get("graphVersion") == "v3":
                from .v3.runtime_worker import run_v3_claim

                run_v3_claim(claim)
                if once:
                    return
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
                run_claim(claim, backend, model, settings, v2_models=v2_models)
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
    parser = argparse.ArgumentParser(description="K-PLASMA LangGraph v1 and v2 worker")
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
