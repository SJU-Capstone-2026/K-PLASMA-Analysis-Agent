from dataclasses import replace
from types import SimpleNamespace

from kplasma_agent.v3.config import Settings
from kplasma_agent.v3.core.model_gateway import V3Settings
from kplasma_agent.v3 import runtime_worker
from kplasma_agent.v3.runtime import normalize_mode


class Backend:
    def __init__(self, payload=None):
        self.payload, self.failed, self.saved_answer = payload, None, None
        self.progress = SimpleNamespace(activity=lambda *a, **kw: "activity")

    def checkpoint(self):
        return self.payload

    def fail(self, code):
        self.failed = code

    def stage(self, stage):
        pass

    def finalize(self, answer):
        self.saved_answer = answer


def claim():
    return {"request": {"requestId": "request-test", "graphVersion": "v3", "question": "조회",
                        "v3Options": normalize_mode({"rulesEnabled": True, "ragEnabled": True})}}


def models():
    return SimpleNamespace(settings=V3Settings.from_env(Settings()), execution_mode=claim()["request"]["v3Options"])


def test_checkpoint_fingerprint_includes_modes_and_retrieval_profile():
    configured = models().settings
    mode = claim()["request"]["v3Options"]
    on = runtime_worker.versions_for_request(configured, mode)
    off = runtime_worker.versions_for_request(configured, normalize_mode({"rulesEnabled": True, "ragEnabled": False}))
    assert on["configFingerprint"] != off["configFingerprint"]
    assert on["retrievalProfile"]["topK"] == 5
    assert on["retrievalProfile"]["experimentalFacets"] is False


def test_actual_v3_execution_rejects_disabled_decisions_before_loading_checkpoint():
    configured = models()
    configured.settings = replace(configured.settings, plan_review_enabled=False)
    backend = Backend()
    runtime_worker.execute_claim(claim(), backend, configured)
    assert backend.failed == "V3_PLAN_REVIEW_REQUIRED"
    assert backend.saved_answer is None


def test_changed_checkpoint_configuration_does_not_execute_the_graph(monkeypatch):
    monkeypatch.setattr(runtime_worker, "build_v3_graph", lambda *_: (_ for _ in ()).throw(AssertionError("executed")))
    backend = Backend({"versions": {"graphVersion": "v2"}})
    runtime_worker.execute_claim(claim(), backend, models())
    assert backend.failed == "RECOVERY_VERSION_MISMATCH"


def test_saved_mode_mismatch_is_not_resumed(monkeypatch):
    graph = SimpleNamespace(get_state=lambda _: SimpleNamespace(values={"execution_mode": normalize_mode()}, next=()))
    monkeypatch.setattr(runtime_worker, "build_v3_graph", lambda *_: graph)
    backend = Backend()
    runtime_worker.execute_claim(claim(), backend, models())
    assert backend.failed == "RECOVERY_VERSION_MISMATCH"


def test_new_request_stores_enabled_review_and_an_independent_mode_copy(monkeypatch):
    request = claim()
    captured = {}

    def invoke(value, config, **kwargs):
        captured.update(value)
        request["request"]["v3Options"]["ragEnabled"] = False
        return {"answer": {"answerSnapshot": {"graphVersion": "v3"}}}

    graph = SimpleNamespace(get_state=lambda _: SimpleNamespace(values={}, next=("plan",)), invoke=invoke)
    monkeypatch.setattr(runtime_worker, "build_v3_graph", lambda *_: graph)
    backend = Backend()
    runtime_worker.execute_claim(request, backend, models())
    assert captured["plan_review_enabled"] is True
    assert captured["execution_mode"]["ragEnabled"] is True
    assert backend.saved_answer["answerSnapshot"]["graphVersion"] == "v3"
