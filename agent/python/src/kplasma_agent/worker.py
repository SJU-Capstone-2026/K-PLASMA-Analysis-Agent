"""Single-claim worker; PostgreSQL queue supports multiple independent processes."""

import argparse
import logging
import signal
from threading import Event, Thread
import uuid

from langgraph.types import Command

from .backend_client import BackendClient, BackendError
from .config import Settings
from .graphs.v1 import build_graph
from .model_client import ModelClient
from .persistence.checkpointer import DurableSaver

LOG = logging.getLogger("kplasma.worker")


def run_claim(claim, backend, model, settings):
    versions = settings.versions()
    payload = backend.checkpoint()
    if payload and payload.get("versions") != versions:
        backend.fail("RECOVERY_VERSION_MISMATCH")
        return
    request = claim["request"]
    config = {"configurable": {"thread_id": request["requestId"]}, "recursion_limit": 80}
    try:
        saver = DurableSaver(
            (payload or {}).get("saver"), lambda data: backend.save({"versions": versions, "saver": data})
        )
        graph = build_graph(model, backend, settings, saver)
        saved = graph.get_state(config)
    except Exception:
        backend.fail("RECOVERY_STATE_INVALID")
        return
    if saved.values:
        pending = any(task.interrupts for task in saved.tasks)
        if pending:
            history_size = len(saved.values.get("input_history", []))
            events = claim.get("inputEvents", [])
            if len(events) <= history_size:
                backend.needs_input(saved.values["pending"])
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
            backend.needs_input(result["pending"])
        else:
            backend.stage("commit")
            backend.finalize(result["answer"])
    except BackendError as error:
        # A lost write/lease must never turn into a fabricated success or an unfenced failure.
        if error.retryable or error.code in ("STALE_CLAIM", "STALE_CONTEXT", "REQUEST_NOT_FOUND"):
            raise
        _fail_graph(backend, graph, config, error)
    except Exception as error:
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
    if state.get("verified") and state.get("operation", {}).get("kind") == "explain_change":
        partial = {**state["result"], "explanationComplete": False}
    backend.fail(code, partial)
    LOG.warning("request failed: %s", code)


def serve(settings, once=False):
    if not settings.worker_token:
        raise SystemExit("AGENT_WORKER_TOKEN must be configured in the backend and worker.")
    client = BackendClient(settings)
    model = ModelClient(settings)
    stopping = Event()
    worker_id = f"python-v1-{uuid.uuid4()}"

    def stop(*_):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("worker ready: graph=v1 model=%s reasoning=%s", settings.model, settings.reasoning_effort)
    while not stopping.is_set():
        try:
            claim = client.claim(worker_id)
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
                run_claim(claim, backend, model, settings)
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
    parser = argparse.ArgumentParser(description="K-PLASMA LangGraph v1 worker")
    parser.add_argument("--env-file")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # httpx/openai request logging can include remote URLs; keep routine logs minimal.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    serve(Settings.from_env(args.env_file), args.once)


if __name__ == "__main__":
    main()
