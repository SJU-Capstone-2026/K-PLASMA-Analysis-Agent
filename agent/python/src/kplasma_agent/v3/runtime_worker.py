"""V3-owned request execution; the shared worker only dispatches by version."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from threading import Event, Thread

import httpx
from langgraph.types import Command

from . import tracing
from .backend_client import BackendClient, BackendError
from .config import Settings
from .core.backend import V3ExecutionPort
from .core.budget import check_payload
from .core.model_gateway import V3ModelGateway, V3Settings
from .graph import build_v3_graph
from .persistence.checkpointer import DurableSaver
from .runtime import normalize_mode
from .decision_rag.embedding import MODEL_ID, MODEL_FILES, REVISION
from .decision_rag.evidence_selection import EVIDENCE_SELECTION_POLICY
from .decision_rag.policy import RECORD_POLICY_VERSION

LOG = logging.getLogger("kplasma.v3.worker")


def source_digest():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def versions_for_request(settings, mode):
    fields = {
        "graphVersion": "v3", "graphBuildId": "v3-our-decision-rag-2", "schemaVersion": "1",
        "sourceDigest": source_digest(), "planner": settings.planner.model,
        "planEffort": settings.planner.reasoning_effort, "writer": settings.writer.model,
        "answerEffort": settings.writer.reasoning_effort, "decisions": settings.decisions_model,
        "decisionsUrl": settings.decisions_url, "planReviewEnabled": settings.plan_review_enabled,
        "timeout": settings.planner.timeout, "executionMode": mode,
        "retrievalProfile": {"model": MODEL_ID, "revision": REVISION,
                             "fileHashes": {name: value[1] for name, value in MODEL_FILES.items()},
                             "minScore": 0.78, "relativeMargin": 0.08, "topK": 5,
                             "selectionPolicy": EVIDENCE_SELECTION_POLICY,
                             "recordPolicy": RECORD_POLICY_VERSION,
                             "rerankerEnabled": False, "experimentalFacets": False},
    }
    fields["configFingerprint"] = hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return fields


def execute_claim(claim, backend, models):
    request = claim["request"]
    mode = normalize_mode(request.get("v3Options"))
    if not models.settings.plan_review_enabled:
        backend.fail("V3_PLAN_REVIEW_REQUIRED")
        return
    versions = versions_for_request(models.settings, mode)
    payload = backend.checkpoint()
    if payload and payload.get("versions") != versions:
        backend.fail("RECOVERY_VERSION_MISMATCH")
        return
    config = {"configurable": {"thread_id": request["requestId"]}, "recursion_limit": 80}
    progress = backend.progress
    check_id = progress.activity("QUESTION_CHECK")
    try:
        saver = DurableSaver((payload or {}).get("saver"),
                             lambda data: backend.save({"versions": versions, "saver": data}))
        graph = build_v3_graph(models, V3ExecutionPort(backend), saver)
        saved = graph.get_state(config)
        if saved.values and saved.values.get("execution_mode") != mode:
            backend.fail("RECOVERY_VERSION_MISMATCH")
            return
        progress.activity("QUESTION_CHECK", "completed", identity=check_id)
        graph_input: Command | dict | None
        if saved.values:
            if any(task.interrupts for task in saved.tasks):
                count = len(saved.values.get("input_history", []))
                events = claim.get("inputEvents", [])
                if len(events) <= count:
                    backend.needs_input(next(item.value for task in saved.tasks for item in task.interrupts))
                    return
                graph_input = Command(resume=events[count]["input"])
            else:
                graph_input = None
        else:
            graph_input = {"request_id": request["requestId"], "question": request["question"],
                           "context": claim.get("context") or {}, "input_history": [],
                           "execution_mode": mode, "plan_review_enabled": True}
        result = (graph.invoke(graph_input, config, durability="sync")
                  if saved.next or "answer" not in saved.values else saved.values)
        if result.get("__interrupt__"):
            backend.needs_input(result["__interrupt__"][0].value)
        else:
            progress.activity("COMMIT")
            backend.stage("commit")
            backend.finalize(result["answer"])
    except BackendError as error:
        if error.retryable or error.code in {"STALE_CLAIM", "STALE_REQUEST", "STALE_CONTEXT"}:
            raise
        backend.fail(error.code)
        LOG.warning("request failed: %s", error.code)
    except Exception as error:
        code = getattr(error, "code", "GRAPH_EXECUTION_FAILED")
        backend.fail(code)
        LOG.warning("request failed: %s (%s)", code, type(error).__name__)


def run_v3_claim(claim):
    """Use V3-owned transports, checkpoint adapter, models and graph for a V3 claim."""
    if claim.get("request", {}).get("graphVersion") != "v3":
        raise ValueError("V3_REQUEST_REQUIRED")
    settings = Settings.from_env()
    client = BackendClient(settings)
    decisions = httpx.Client(timeout=settings.timeout, transport=httpx.HTTPTransport(retries=0))
    backend = client.bind(claim)
    stop = Event()

    def heartbeat():
        while not stop.wait(10):
            try:
                backend.stage()
            except BackendError:
                return

    pulse = Thread(target=heartbeat, daemon=True)
    try:
        mode = normalize_mode(claim["request"].get("v3Options"))
        models = V3ModelGateway(V3Settings.from_env(settings), decisions, check_payload, execution_mode=mode)
        pulse.start()
        with tracing.span("agent.v3.request", kind="AGENT", session_id=claim["request"]["requestId"],
                          attributes={"kplasma.graph_version": "v3", "kplasma.mode_digest": mode["configDigest"]}):
            execute_claim(claim, backend, models)
    except BackendError as error:
        LOG.warning("worker transport: %s", error.code)
    except ValueError:
        backend.fail("INVALID_V3_OPTIONS")
    finally:
        stop.set()
        if pulse.is_alive():
            pulse.join(timeout=3)
        decisions.close()
        client.client.close()
