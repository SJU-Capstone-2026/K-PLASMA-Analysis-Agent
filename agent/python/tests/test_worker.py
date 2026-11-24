from types import SimpleNamespace
import httpx
import pytest
from kplasma_agent.config import Settings
from kplasma_agent.v2.model_gateway import V2Settings
from kplasma_agent.worker import run_claim


class Backend:
    def __init__(self):
        self.payload = None
        self.errors = []

    def checkpoint(self):
        return self.payload

    def fail(self, code, partial=None):
        self.errors.append(code)


@pytest.mark.parametrize("version", [None, "v1", "v2_localLLM"])
def test_standard_worker_rejects_other_graphs_before_checkpoint(version):
    backend = Backend()
    backend.checkpoint = lambda: pytest.fail("foreign graph must not reach checkpoint")
    request = {"requestId": "synthetic", "graphVersion": version}
    run_claim({"request": request}, backend, v2_models=None)
    assert backend.errors == ["GRAPH_VERSION_MISMATCH"]


def test_worker_refuses_recovery_under_different_config():
    backend = Backend()
    backend.payload = {"versions": {"model": "different"}}
    v2_models = SimpleNamespace(settings=V2Settings.from_env(Settings()))
    run_claim({"request": {"graphVersion": "v2"}}, backend, v2_models=v2_models)
    assert backend.errors == ["RECOVERY_VERSION_MISMATCH"]


def test_corrupt_checkpoint_fails_only_the_request():
    backend = Backend()
    v2_models = SimpleNamespace(settings=V2Settings(
        planner=Settings(model="planner", reasoning_effort="low"),
        writer=Settings(model="writer", reasoning_effort="low"),
        decisions_model="reviewer", decisions_url="https://provider.example/v1/decisions",
    ))
    backend.payload = {
        # Existing v2 checkpoints have this metadata even as the legacy worker path is removed.
        "versions": {"graphVersion": "v2", "graphBuildId": "v2-composite-1", "schemaVersion": "1",
                     "planner": "planner", "planEffort": "low", "writer": "writer", "answerEffort": "low",
                     "decisions": "reviewer"},
        "saver": {"format": "langgraph-memory-v1"},
    }
    run_claim({"request": {"requestId": "broken", "graphVersion": "v2"}}, backend, v2_models=v2_models)
    assert backend.errors == ["RECOVERY_STATE_INVALID"]


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

    def claim(worker_id, versions):
        assert worker_id.startswith("python-v2-")
        assert versions == ["v2"]
        return {"request": None}

    monkeypatch.setattr(worker, "BackendClient", lambda _: SimpleNamespace(claim=claim))
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
    ("MODEL_OUTPUT_TRUNCATED", "출력 길이"),
    ("MODEL_RESPONSE_INCOMPLETE", "미완료"),
    ("MODEL_RESPONSE_FAILED", "공급자"),
    ("MODEL_CONTENT_FILTERED", "콘텐츠 필터"),
    ("MODEL_STREAM_INTERRUPTED", "종료 신호"),
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
