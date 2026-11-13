from copy import deepcopy
from importlib import import_module
from importlib.util import find_spec
from types import SimpleNamespace

import pytest

from kplasma_agent.v2_local_llm.config import Settings


def worker():
    assert find_spec("kplasma_agent.v2_local_llm.worker"), "independent local worker is missing"
    return import_module("kplasma_agent.v2_local_llm.worker")


class Backend:
    def __init__(self):
        self.errors = []
        self.payload = None
        self.reads = 0
        self.answer = None

    def fail(self, code, partial=None):
        self.errors.append(code)

    def checkpoint(self):
        self.reads += 1
        return deepcopy(self.payload)

    def save(self, payload):
        self.payload = deepcopy(payload)

    def stage(self, *args, **kwargs):
        pass

    def finalize(self, answer):
        self.answer = deepcopy(answer)


@pytest.mark.parametrize("version", [None, "v1", "v2", "v3"])
def test_private_worker_rejects_wrong_or_missing_graph_before_state_access(version):
    module = worker()
    backend = Backend()
    request = {"requestId": "synthetic"}
    if version:
        request["graphVersion"] = version
    module.run_claim({"request": request}, backend, None, models=None)
    assert backend.errors == ["GRAPH_VERSION_MISMATCH"]
    assert backend.reads == 0


def test_same_request_uuid_cannot_reuse_a_cloud_checkpoint_or_pass():
    module = worker()
    backend = Backend()
    backend.payload = {"versions": {"graphVersion": "v2", "configFingerprint": "same-digest"},
                       "saver": {"PASS": True}}
    module.run_claim({"request": {"requestId": "same-uuid", "graphVersion": "v2_localLLM"}},
                     backend, Settings(), models=SimpleNamespace())
    assert backend.errors == ["RECOVERY_VERSION_MISMATCH"]


def test_unverified_readiness_stops_before_any_client_is_constructed(monkeypatch):
    module = worker()
    clients = []
    monkeypatch.setattr(module, "BackendClient", lambda *a, **kw: clients.append(a))
    with pytest.raises(SystemExit, match="LOCAL_RUNTIME_NOT_READY") as raised:
        module.serve(Settings(), once=True)
    assert "LOCAL_TOKENS_NOT_CONFIGURED" in str(raised.value)
    assert not clients


@pytest.mark.parametrize("blocker", ["LOCAL_MODEL_RUNTIME_BUSY", "LOCAL_MEMORY_PRESSURE"])
def test_idle_worker_waits_for_transient_readiness_without_claiming_a_request(blocker, tmp_path, monkeypatch):
    from kplasma_agent.v2_local_llm import runtime

    module = worker()
    states = iter([{"ready": True, "blockers": []}, {"ready": False, "blockers": [blocker]},
                   {"ready": True, "blockers": []}])
    checked = []
    claims = []

    def readiness(_):
        status = next(states)
        checked.append(status)
        return status

    def claim(*_):
        assert len(checked) == 3 and checked[-1]["ready"]
        claims.append(True)
        return {"request": None}

    monkeypatch.setattr(Settings, "readiness", readiness)
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(module, "BackendClient", lambda *_: SimpleNamespace(claim=claim))
    monkeypatch.setattr(module, "local_http_client", lambda *a, **kw: object())
    monkeypatch.setattr(module, "V2LocalLLMModelGateway", lambda *_: object())
    monkeypatch.setattr(module.signal, "signal", lambda *_: None)
    module.serve(Settings(worker_token="synthetic", poll_seconds=0), once=True)
    assert claims == [True]


def test_worker_releases_owned_qwen_after_a_request_while_still_holding_the_model_lease(tmp_path, monkeypatch):
    from kplasma_agent.v2_local_llm import runtime

    module = worker()
    events = []

    def release(role):
        with pytest.raises(runtime.ModelRuntimeBusy), runtime.model_lease():
            pass
        events.append(role)

    backend = SimpleNamespace(claim=lambda *_: {"request": {"requestId": "synthetic"}},
                              bind=lambda *_: SimpleNamespace(stage=lambda: None))
    monkeypatch.setattr(Settings, "readiness", lambda _: {"ready": True, "blockers": []})
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(runtime, "ModelRuntime", lambda *_: SimpleNamespace(prepare=release))
    monkeypatch.setattr(module, "BackendClient", lambda *_: backend)
    monkeypatch.setattr(module, "local_http_client", lambda *a, **kw: object())
    monkeypatch.setattr(module, "V2LocalLLMModelGateway", lambda *_: object())
    monkeypatch.setattr(module.signal, "signal", lambda *_: None)
    monkeypatch.setattr(module, "run_claim", lambda *a, **kw: events.append("graph"))
    module.serve(Settings(worker_token="synthetic"), once=True)
    assert events == ["graph", "plan_review"]


def test_check_is_sanitized_and_cannot_be_promoted_by_ready_true(tmp_path, monkeypatch, capsys):
    module = worker()
    import os
    for key in os.environ:
        if key.startswith(("OPENAI_", "AGENT_", "PHOENIX_", "OTEL_", "LANGCHAIN_", "LANGSMITH_")) or key.upper().endswith("_PROXY"):
            monkeypatch.delenv(key, raising=False)
    env = tmp_path / "local.env"
    env.write_text("AGENT_V2_LOCAL_LLM_READY=true\nAGENT_V2_LOCAL_LLM_QWEN_TOKEN=synthetic-secret\n")
    monkeypatch.setattr("sys.argv", ["worker", "--env-file", str(env), "--check"])
    assert module.main() == 2
    text = capsys.readouterr().out
    import json
    assert json.loads(text)["ready"] is False
    assert "synthetic-secret" not in text and str(env) not in text


def test_recovery_fingerprint_covers_model_revision_quantization_runtime_and_budget():
    from dataclasses import replace
    settings = Settings()
    original = settings.versions()
    assert original["graphVersion"] == original["implementationId"] == "v2_localLLM"
    assert original["quantization"] == "Q4_K_M" and original["d1Quantization"] == "Q8_0"
    for changed in [replace(settings, model_revision="different"), replace(settings, d1_revision="different"),
                    replace(settings, runtime_version="different"), replace(settings, context_tokens=40000)]:
        assert changed.versions()["configFingerprint"] != original["configFingerprint"]


def test_worker_commits_a_real_owned_graph_and_recovers_without_repeating_models(monkeypatch):
    from .test_graph import GeneralModel, Journal
    module = worker()
    journal, models, backend = Journal(), GeneralModel(), Backend()
    monkeypatch.setattr(module, "V2LocalLLMExecutionPort", lambda backend: journal)
    claim = {"request": {"requestId": "synthetic-recovery", "question": "IED가 뭐야?", "graphVersion": "v2_localLLM"}}
    module.run_claim(claim, backend, Settings(), models=models)
    assert backend.errors == []
    assert backend.answer["answerSnapshot"]["graphVersion"] == "v2_localLLM"
    assert backend.answer["answerSnapshot"]["implementationId"] == "v2_localLLM"
    assert journal.calls == ["PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE"]
    original = deepcopy(backend.answer)
    module.run_claim(claim, backend, Settings(), models=models)
    assert backend.answer == original
    assert journal.calls == ["PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE"]
