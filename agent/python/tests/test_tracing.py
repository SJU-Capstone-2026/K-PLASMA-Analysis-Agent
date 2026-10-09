import json

import pytest

from kplasma_agent import tracing
from kplasma_agent.config import Settings


def test_phoenix_configuration_does_not_change_recovery_versions(tmp_path, monkeypatch):
    for key in ("PHOENIX_API_KEY", "PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_PROJECT_NAME"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "PHOENIX_API_KEY=test-private-key\n"
        "PHOENIX_COLLECTOR_ENDPOINT=https://app.phoenix.arize.com/s/example\n"
        "PHOENIX_PROJECT_NAME=K-PLASMA\n"
    )
    settings = Settings.from_env(env)
    assert settings.phoenix_api_key == "test-private-key"
    assert settings.phoenix_project_name == "K-PLASMA"
    assert "test-private-key" not in repr(settings)
    assert settings.versions() == Settings().versions()


def test_register_uses_space_http_endpoint_and_batch_without_global_instrumentation(monkeypatch):
    calls = []

    class Provider:
        def get_tracer(self, name):
            return object()

    monkeypatch.setattr(tracing, "_register", lambda **kwargs: calls.append(kwargs) or Provider())
    monkeypatch.setattr(tracing, "_tracer", None)
    monkeypatch.setattr(tracing, "_provider", None)
    assert tracing.initialize(Settings(
        phoenix_api_key="test-private-key",
        phoenix_endpoint="https://app.phoenix.arize.com/s/example/",
        phoenix_project_name="K-PLASMA",
    ))
    assert calls[0]["endpoint"] == "https://app.phoenix.arize.com/s/example/v1/traces"
    assert calls[0]["protocol"] == "http/protobuf"
    assert calls[0]["batch"] is True
    assert calls[0]["set_global_tracer_provider"] is False
    assert calls[0]["auto_instrument"] is False
    assert calls[0]["api_key"] == "test-private-key"


@pytest.mark.parametrize("endpoint", ["", "https://host.test/?key=private", "https://user:pass@host.test",
                                      "https://[broken"])
def test_incomplete_or_unsafe_configuration_leaves_worker_usable(endpoint, monkeypatch, caplog):
    monkeypatch.setattr(tracing, "_tracer", None)
    monkeypatch.setattr(tracing, "_provider", None)
    assert not tracing.initialize(Settings(phoenix_api_key="test-private-key", phoenix_endpoint=endpoint))
    with tracing.span("still-runs", inputs={"value": 0}) as observed:
        observed.output({"value": 0})
    assert "test-private-key" not in caplog.text
    assert "user:pass" not in caplog.text


def test_full_values_and_zero_survive_but_credentials_are_redacted(trace_capture):
    value = {"zero": 0, "missing": None, "long": "한" * 12000, "api_key": "test-private-key"}
    with tracing.span("node", inputs=value) as observed:
        observed.output({"answer": "result test-private-key", "conditions": value})
    span = trace_capture.get_finished_spans()[0]
    decoded = json.loads(span.attributes["input.value"])
    assert decoded["zero"] == 0 and decoded["missing"] is None
    assert len(decoded["long"]) == 12000
    assert decoded["api_key"] == "[REDACTED]"
    assert "test-private-key" not in json.dumps(dict(span.attributes))


def test_exporter_or_span_setup_failure_never_repeats_or_swallows_business_work(monkeypatch):
    class BrokenTracer:
        def start_as_current_span(self, *args, **kwargs):
            raise RuntimeError("test-private-key")

    monkeypatch.setattr(tracing, "_tracer", BrokenTracer())
    calls = []
    with pytest.raises(ValueError, match="business failed"):
        with tracing.span("broken"):
            calls.append(1)
            raise ValueError("business failed")
    assert calls == [1]


def test_lazy_trace_value_failure_does_not_fail_business_work(trace_capture):
    with tracing.span("safe-value") as observation:
        observation.output(lambda: 1 / 0)
        answer = 4
    assert answer == 4
    assert trace_capture.get_finished_spans()[0].status.status_code.name == "OK"


def test_error_records_safe_type_instead_of_provider_body(trace_capture):
    with pytest.raises(ValueError):
        with tracing.span("failing"):
            raise ValueError("provider body test-private-key")
    span = trace_capture.get_finished_spans()[0]
    assert span.status.status_code.name == "ERROR"
    assert span.attributes["error.code"] == "ValueError"
    assert "test-private-key" not in str(span.attributes) + str(span.events)


def test_error_status_also_redacts_known_credentials(trace_capture, monkeypatch):
    monkeypatch.setattr(tracing, "_secrets", ("PRIVATE_KEY",))

    class Failure(RuntimeError):
        code = "PRIVATE_KEY"

    with pytest.raises(Failure):
        with tracing.span("safe-error"):
            raise Failure()
    span = trace_capture.get_finished_spans()[0]
    assert span.attributes["error.code"] == "[REDACTED]"
    assert "PRIVATE_KEY" not in span.status.description


def test_register_failure_does_not_prevent_worker_work(monkeypatch, caplog):
    def failing_register(**kwargs):
        raise RuntimeError("provider test-private-key")

    monkeypatch.setattr(tracing, "_register", failing_register)
    monkeypatch.setattr(tracing, "_tracer", None)
    monkeypatch.setattr(tracing, "_provider", None)
    assert not tracing.initialize(Settings(
        phoenix_api_key="test-private-key", phoenix_endpoint="https://phoenix.test",
    ))
    with tracing.span("work"):
        result = 2 + 2
    assert result == 4 and "test-private-key" not in caplog.text


def test_backend_context_records_normalized_query_and_response_without_auth(trace_capture):
    import httpx
    from kplasma_agent.backend_client import BackendClient

    settings = Settings(worker_token="test-private-key")
    backend = BackendClient(settings, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"runs": [{"runId": "SYNTHETIC-A", "ionFlux": 0}]})
    )).bind({"request": {"requestId": "synthetic"}, "claimGeneration": 2, "requestRevision": 1})
    query = {"constraints": [], "goals": [{"metric": "ionFlux", "direction": "maximize"}]}
    with tracing.span("parent"):
        assert backend.context(reverse_query=query)["runs"][0]["ionFlux"] == 0
    spans = {s.name: s for s in trace_capture.get_finished_spans()}
    child = spans["backend.context"]
    assert json.loads(child.attributes["input.value"])["reverseQuery"] == query
    assert json.loads(child.attributes["output.value"])["runs"][0]["ionFlux"] == 0
    assert child.parent.span_id == spans["parent"].context.span_id
    assert "test-private-key" not in str(child.attributes)
