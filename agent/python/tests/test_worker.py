from copy import deepcopy
import pytest
from kplasma_agent.config import Settings
from kplasma_agent.worker import run_claim


class Backend:
    def __init__(self):
        self.payload = None
        self.answer = None
        self.pending = None
        self.errors = []

    def checkpoint(self):
        return deepcopy(self.payload)

    def save(self, payload):
        self.payload = deepcopy(payload)

    def context(self, refs=None):
        return {"runs": [], "referencedRuns": [], "context": {}}

    def stage(self, *args, **kwargs):
        pass

    def attempt(self, stage):
        pass

    def needs_input(self, pending):
        self.pending = pending

    def finalize(self, answer):
        self.answer = answer

    def fail(self, code, partial=None):
        self.errors.append(code)


class Model:
    calls = 0

    def generate(self, *args):
        self.calls += 1
        return {
            "status": "resolved",
            "operations": [
                {
                    "kind": "forward_lookup",
                    "inputs": {"conditions": {"pressure": {"value": 10, "unit": "mTorr"},
                                              "sourcePower": {"value": 300, "unit": "W"}}},
                }
            ],
        }, {}


def test_worker_reconstructs_interrupted_graph_and_finalizes_once_after_resume():
    backend = Backend()
    model = Model()
    claim = {
        "request": {"requestId": "test", "question": "압력 10 mTorr 소스 300 W 조건 조회"},
        "context": {},
        "inputEvents": [],
    }
    run_claim(claim, backend, model, Settings())
    assert backend.pending and backend.answer is None and backend.payload
    claim["inputEvents"] = [{"input": {"conditions": {"biasPower": {"value": 100, "unit": "W"}}}}]
    run_claim(claim, backend, model, Settings())
    assert backend.answer["status"] == "NO_DATA" and model.calls == 1
    assert not backend.errors


def test_worker_refuses_recovery_under_different_config():
    backend = Backend()
    backend.payload = {"versions": {"model": "different"}}
    run_claim({}, backend, Model(), Settings())
    assert backend.errors == ["RECOVERY_VERSION_MISMATCH"]


def test_corrupt_checkpoint_fails_only_the_request():
    backend = Backend()
    backend.payload = {"versions": Settings().versions(), "saver": {"format": "langgraph-memory-v1"}}
    run_claim({"request": {"requestId": "broken"}}, backend, Model(), Settings())
    assert backend.errors == ["RECOVERY_STATE_INVALID"]


def test_trace_groups_resume_and_expected_input_wait_without_error(trace_capture):
    import json

    backend = Backend()
    model = Model()
    claim = {"request": {"requestId": "synthetic-trace", "question": "압력 10 mTorr 소스 300 W 조건 조회"},
             "context": {}, "inputEvents": [], "claimGeneration": 1, "requestRevision": 0}
    run_claim(claim, backend, model, Settings())
    claim["inputEvents"] = [{"input": {"conditions": {"biasPower": {"value": 100, "unit": "W"}}}}]
    claim["claimGeneration"] = 2
    run_claim(claim, backend, model, Settings())
    spans = trace_capture.get_finished_spans()
    roots = [s for s in spans if s.name == "agent.request"]
    assert len(roots) == 2 and all(s.attributes["session.id"] == "synthetic-trace" for s in roots)
    assert [s.attributes["kplasma.outcome"] for s in roots] == ["NEEDS_INPUT", "COMPLETED"]
    assert roots[1].attributes["kplasma.resumed"] is True
    assert json.loads(roots[1].attributes["output.value"])["status"] == "NO_DATA"
    nodes = [s for s in spans if s.name.startswith("graph.")]
    assert nodes and all(s.parent for s in nodes)
    assert all(s.status.status_code.name != "ERROR" for s in nodes)
    assert "graph.wait_input" in {s.name for s in nodes}
    assert "graph.present" in {s.name for s in nodes}


def test_blocked_failed_cloud_export_cannot_block_graph_or_repeat_model(monkeypatch):
    pytest.importorskip("opentelemetry.sdk")
    from threading import Event, Thread
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
    from kplasma_agent import tracing

    exporting, release, business_done = Event(), Event(), Event()
    business_errors = []

    class BlockedExporter(SpanExporter):
        def export(self, spans):
            exporting.set()
            release.wait()
            return SpanExportResult.FAILURE

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(
        BlockedExporter(), schedule_delay_millis=1, max_export_batch_size=1, max_queue_size=32,
    ))
    monkeypatch.setattr(tracing, "_tracer", provider.get_tracer("synthetic-export"))
    backend, model = Backend(), Model()
    claim = {"request": {"requestId": "synthetic-export", "question": "압력 10 mTorr 소스 300 W 조건 조회"},
             "context": {}, "inputEvents": []}

    def execute_claim():
        try:
            run_claim(claim, backend, model, Settings())
        except Exception as error:
            business_errors.append(error)
        finally:
            business_done.set()

    worker = Thread(target=execute_claim, daemon=True)
    try:
        worker.start()
        assert exporting.wait(3)
        assert business_done.wait(3) and not release.is_set()
        assert not business_errors
        assert backend.pending and backend.payload and not backend.errors
        claim["inputEvents"] = [{"input": {"conditions": {"biasPower": {"value": 100, "unit": "W"}}}}]
        run_claim(claim, backend, model, Settings())
        assert backend.answer["status"] == "NO_DATA" and model.calls == 1
    finally:
        release.set()
        worker.join(timeout=3)
        provider.shutdown()
