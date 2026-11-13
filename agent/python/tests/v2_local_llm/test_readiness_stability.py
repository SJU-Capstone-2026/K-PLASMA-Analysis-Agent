import httpx
import pytest

from kplasma_agent.v2_local_llm import runtime
from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.network import local_http_client


def clock_and_clients(monkeypatch, *, pressure, sleeping=lambda *_: True, failed_port=None):
    clock = [0.0]
    requests = []
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runtime.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(runtime, "memory_sample", lambda **_: {"pressure": pressure(clock[0])})

    def respond(request):
        assert request.method == "GET" and request.url.path == "/props"
        assert request.headers["Authorization"] in {"Bearer synthetic-qwen", "Bearer synthetic-d1"}
        requests.append(request.url.port)
        return httpx.Response(503 if request.url.port == failed_port else 200,
                              json={"is_sleeping": sleeping(request.url.port, clock[0])})

    def client(url, **kwargs):
        return local_http_client(url, **kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(runtime, "local_http_client", client)
    return clock, requests


def settings():
    return Settings(api_key="synthetic-qwen", d1_token="synthetic-d1")


def test_warning_and_relapse_require_five_continuous_normal_seconds(monkeypatch):
    clock, requests = clock_and_clients(monkeypatch, pressure=lambda t: 2 if t < 1 or t == 3 else 1)
    runtime.wait_for_stability(settings())
    assert clock[0] == 9
    assert set(requests) == {8081, 8082}


@pytest.mark.parametrize("port", [8081, 8082])
def test_normal_pressure_is_not_enough_until_both_models_sleep(monkeypatch, port):
    clock, _ = clock_and_clients(monkeypatch, pressure=lambda _: 1,
                                sleeping=lambda selected, t: selected != port or t >= 3)
    runtime.wait_for_stability(settings())
    assert clock[0] == 8


def test_persistent_warning_stops_at_sixty_seconds(monkeypatch):
    clock, _ = clock_and_clients(monkeypatch, pressure=lambda _: 2)
    with pytest.raises(ValueError, match="LOCAL_MEMORY_PRESSURE"):
        runtime.wait_for_stability(settings())
    assert clock[0] == 60


@pytest.mark.parametrize("state", [False, "true", None])
def test_sleep_state_must_be_true_for_the_entire_stable_window(monkeypatch, state):
    clock, _ = clock_and_clients(monkeypatch, pressure=lambda _: 1, sleeping=lambda *_: state)
    with pytest.raises(ValueError, match="LOCAL_MEMORY_PRESSURE"):
        runtime.wait_for_stability(settings())
    assert clock[0] == 60


def test_critical_pressure_fails_immediately(monkeypatch):
    clock, requests = clock_and_clients(monkeypatch, pressure=lambda _: 4)
    with pytest.raises(ValueError, match="LOCAL_MEMORY_CRITICAL"):
        runtime.wait_for_stability(settings())
    assert clock[0] == 0 and requests == []


def test_unreachable_model_cannot_become_ready(monkeypatch):
    clock, _ = clock_and_clients(monkeypatch, pressure=lambda _: 1, failed_port=8081)
    with pytest.raises(ValueError, match="LOCAL_MODEL_RUNTIME_UNAVAILABLE"):
        runtime.wait_for_stability(settings())
    assert clock[0] == 0


def test_malformed_success_response_is_a_runtime_blocker(monkeypatch):
    clock, _ = clock_and_clients(monkeypatch, pressure=lambda _: 1)
    def client(url, **kwargs):
        return local_http_client(url, **kwargs,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"invalid-json")))
    monkeypatch.setattr(runtime, "local_http_client", client)
    with pytest.raises(ValueError, match="LOCAL_MODEL_RUNTIME_UNAVAILABLE"):
        runtime.wait_for_stability(settings())
    assert clock[0] == 0


def test_expired_wait_does_not_start_another_memory_sample(monkeypatch):
    clock, _ = clock_and_clients(monkeypatch, pressure=lambda _: 2)
    calls = []
    def sample(**kwargs):
        calls.append(clock[0])
        return {"pressure": 2}
    monkeypatch.setattr(runtime, "memory_sample", sample)
    with pytest.raises(ValueError, match="LOCAL_MEMORY_PRESSURE"):
        runtime.wait_for_stability(settings())
    assert max(calls) == 59


def test_each_memory_command_uses_only_the_remaining_deadline(monkeypatch):
    clock = [0.0]
    timeouts = []
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock[0])
    def run(_args, **kwargs):
        timeouts.append(kwargs["timeout"])
        clock[0] += kwargs["timeout"]
        if len(timeouts) == 2:
            raise runtime.subprocess.TimeoutExpired(_args, kwargs["timeout"])
        return type("Output", (), {"stdout": ""})()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(ValueError, match="LOCAL_MEMORY_PRESSURE"):
        runtime.memory_sample(deadline=6)
    assert timeouts == [5, 1] and clock[0] == 6
