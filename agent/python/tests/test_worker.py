from copy import deepcopy
from types import SimpleNamespace
import httpx
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

    def context(self, refs=None, **kwargs):
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

    def select_tool(self, *args):
        self.calls += 1
        return {
            "name": "forward_lookup",
            "call_id": "test-call",
            "arguments": {
                "conditions": {
                    "pressure": {"value": 10, "unit": "mTorr"},
                    "sourcePower": {"value": 300, "unit": "W"},
                }
            },
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
    claim = {
        "request": {"requestId": "synthetic-trace", "question": "압력 10 mTorr 소스 300 W 조건 조회"},
        "context": {},
        "inputEvents": [],
        "claimGeneration": 1,
        "requestRevision": 0,
    }
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
    provider.add_span_processor(
        BatchSpanProcessor(
            BlockedExporter(),
            schedule_delay_millis=1,
            max_export_batch_size=1,
            max_queue_size=32,
        )
    )
    monkeypatch.setattr(tracing, "_tracer", provider.get_tracer("synthetic-export"))
    backend, model = Backend(), Model()
    claim = {
        "request": {"requestId": "synthetic-export", "question": "압력 10 mTorr 소스 300 W 조건 조회"},
        "context": {},
        "inputEvents": [],
    }

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


def test_model_timeout_defaults_to_90_seconds_and_honors_env_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("")
    monkeypatch.delenv("AGENT_MODEL_TIMEOUT_SECONDS", raising=False)
    assert Settings().timeout == 90
    assert Settings.from_env(env).timeout == 90
    monkeypatch.setenv("AGENT_MODEL_TIMEOUT_SECONDS", "120")
    assert Settings.from_env(env).timeout == 120


@pytest.mark.parametrize("timeout,expected", [(90, 90), (15, 15), (120, 120)])
def test_worker_decisions_timeout_matches_model_setting(timeout, expected, monkeypatch):
    from kplasma_agent import worker

    clients = []

    def gateway(settings, client, guard):
        clients.append(client)
        return SimpleNamespace(settings=settings)

    monkeypatch.setattr(worker, "BackendClient", lambda _: SimpleNamespace(claim=lambda *_: {"request": None}))
    monkeypatch.setattr(worker, "V2ModelGateway", gateway)
    monkeypatch.setattr(worker.signal, "signal", lambda *_: None)
    try:
        worker.serve(Settings(worker_token="test", timeout=timeout), once=True)
        assert clients[0].timeout.read == expected
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize("code,diagnostic", [
    ("MODEL_TIMEOUT", "시간"),
    ("MODEL_CONNECTION", "연결"),
    ("MODEL_RATE_LIMITED", "요청 한도"),
    ("MODEL_HTTP_401", "모델 API"),
    ("MODEL_STREAM_ERROR", "스트림"),
    ("MODEL_API_ERROR", "모델 API"),
])
def test_specific_model_failure_codes_reach_the_request_with_a_readable_message(code, diagnostic):
    from kplasma_agent.backend_client import BackendClient

    requests = []

    def transport(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = BackendClient(Settings(), transport=httpx.MockTransport(transport))
    try:
        backend = client.bind({"request": {"requestId": "synthetic"}, "claimGeneration": 1, "requestRevision": 0})
        backend.fail(code)
    finally:
        client.client.close()
    assert requests[0]["error"]["code"] == code
    assert diagnostic in requests[0]["error"]["message"]
