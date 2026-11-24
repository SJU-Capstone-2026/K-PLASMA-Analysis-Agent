"""Private local worker; no shared graph dispatcher or cloud fallback."""

import argparse
import logging
import json
import signal
from threading import Event, Thread
import uuid

from langgraph.types import Command

from .backend_client import BackendClient, BackendError
from .config import Settings
from .graph import build_v2_local_llm_graph
from .core.backend import V2LocalLLMExecutionPort
from .network import local_http_client
from .core.model_gateway import V2LocalLLMModelGateway, V2LocalLLMSettings
from .persistence.checkpointer import DurableSaver
from . import tracing
from .progress import ProgressReporter
from .prompt_cache import QwenPlanCache

LOG = logging.getLogger("kplasma.v2_local_llm.worker")


def run_claim(claim, backend, settings, *, models):
    request = claim.get("request") or {}
    if request.get("graphVersion") != "v2_localLLM":
        backend.fail("GRAPH_VERSION_MISMATCH")
        return
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
        _run_claim(claim, backend, settings, observation, models=models)


def _run_claim(claim, backend, settings, observation, *, models):
    progress = getattr(backend, "progress", None) or ProgressReporter(None)
    check_id = progress.activity("QUESTION_CHECK")
    versions = settings.versions()
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
        graph = build_v2_local_llm_graph(models, V2LocalLLMExecutionPort(backend), saver)
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
            if (snapshot.get("graphVersion") != "v2_localLLM"
                    or snapshot.get("implementationId") != "v2_localLLM"):
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
    status = settings.readiness()
    if not status["ready"]:
        raise SystemExit("LOCAL_RUNTIME_NOT_READY:" + ",".join(status.get("blockers", [])))
    from .core.budget import make_input_guard, make_d1_counter, make_qwen_counter
    from .runtime import ModelRuntime, ModelRuntimeBusy, model_lease

    if not settings.worker_token:
        raise SystemExit("LOCAL_WORKER_TOKEN_REQUIRED")
    tracing.initialize(settings)
    client = BackendClient(settings)
    decisions = local_http_client(settings.d1_url, timeout=settings.timeout,
                                  headers={"Authorization": "Bearer " + settings.d1_token})
    control = local_http_client(settings.model_url, timeout=settings.timeout,
                                headers={"Authorization": "Bearer " + settings.api_key})
    runtime = ModelRuntime(settings, control, decisions)
    cache_options = {"plan_cache": QwenPlanCache(settings, control)} if settings.qwen_plan_cache_enabled else {}
    models = V2LocalLLMModelGateway(V2LocalLLMSettings.from_env(settings), decisions,
                                  make_input_guard(settings, qwen_count=make_qwen_counter(settings, control),
                                                   d1_count=make_d1_counter(settings, decisions),
                                                   prepare=runtime.prepare), **cache_options)
    stopping = Event()
    worker_id = f"python-v2-local-llm-{uuid.uuid4()}"

    def stop(*_):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("worker ready: graph=v2_localLLM")
    while not stopping.is_set():
        status = settings.readiness()
        if status.get("blockers") in (["LOCAL_MODEL_RUNTIME_BUSY"], ["LOCAL_MEMORY_PRESSURE"]):
            stopping.wait(settings.poll_seconds)
            continue
        if not status["ready"]:
            raise SystemExit("LOCAL_RUNTIME_NOT_READY:" + ",".join(status.get("blockers", [])))
        try:
            with model_lease():
                claim = client.claim(worker_id, ["v2_localLLM"])
                if claim.get("request") is None:
                    if once:
                        return
                else:
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
                        runtime.prepare("plan_review")
            if claim.get("request") is None:
                stopping.wait(settings.poll_seconds)
        except ModelRuntimeBusy:
            stopping.wait(settings.poll_seconds)
            continue
        except BackendError as error:
            LOG.warning("worker transport: %s", error.code)
            if error.code in ("UNAUTHORIZED", "WORKER_NOT_CONFIGURED"):
                raise SystemExit(error.code) from None
            if not once:
                stopping.wait(3)
        if once:
            return


def main():
    parser = argparse.ArgumentParser(description="K-PLASMA independent local worker")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings.from_env(args.env_file)
    except (OSError, ValueError, TypeError):
        print(json.dumps({"graphVersion": "v2_localLLM", "ready": False,
                          "blockers": ["LOCAL_CONFIG_INVALID"]}))
        return 2
    status = settings.readiness()
    if args.check or not status["ready"]:
        print(json.dumps({"graphVersion": "v2_localLLM", **status}))
        return 0 if status["ready"] else 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        serve(settings, args.once)
    finally:
        tracing.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
