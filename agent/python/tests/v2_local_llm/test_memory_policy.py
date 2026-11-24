"""Development warnings stay observable; strict evidence and critical guards stay closed."""

from dataclasses import replace
import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm import runtime
from .test_config import clean_env
from .test_cache_probe import rows as cache_rows
from .test_readiness import memory_rows


@pytest.fixture(autouse=True)
def fixed_libraries(monkeypatch):
    monkeypatch.setattr(runtime, "_mlx_libraries", lambda *_: "a" * 64)


def test_memory_policy_is_explicit_closed_and_fingerprinted(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    env = tmp_path / "local.env"
    env.write_text("")
    strict = Settings.from_env(env)
    assert strict.memory_policy == "strict"
    env.write_text("AGENT_V2_LOCAL_LLM_MEMORY_POLICY=development\n")
    dev = Settings.from_env(env)
    assert dev.memory_policy == "development"
    assert dev.versions()["memoryPolicy"] == "development"
    assert dev.versions()["configFingerprint"] != strict.versions()["configFingerprint"]
    assert runtime.runtime_profile(dev) != runtime.runtime_profile(strict)
    env.write_text("AGENT_V2_LOCAL_LLM_MEMORY_POLICY=ignore\n")
    with pytest.raises(ValueError, match="LOCAL_MEMORY_POLICY_INVALID"):
        Settings.from_env(env)


@pytest.mark.parametrize("policy,pressure,expected", [
    ("strict", 1, True), ("strict", 2, False), ("strict", 4, False),
    ("development", 1, True), ("development", 2, True), ("development", 4, False),
    ("development", 3, False), ("development", 0, False), ("development", True, False),
])
def test_only_development_accepts_a_real_warning(policy, pressure, expected):
    allowed = getattr(runtime, "pressure_allowed", None)
    assert callable(allowed), "shared pressure policy is missing"
    assert allowed(pressure, policy) is expected


def memory_report(settings, pressure=2, growth=100):
    return {
        "schema_version": 2, "synthetic_only": True, "full_stack": True,
        "memory_policy": settings.memory_policy,
        "runtime_profile": runtime.runtime_profile(settings),
        "instance_facts_before": "a" * 64, "instance_facts_after": "a" * 64,
        "samples": [{"pressure": 1, "swap_bytes": 100, "resident_bytes": 1000},
                    {"pressure": pressure, "swap_bytes": 100 + growth, "resident_bytes": 1200},
                    {"pressure": 1, "swap_bytes": 100 + growth, "resident_bytes": 1100}],
        "results": memory_rows(),
    }


def test_development_evidence_keeps_warning_and_swap_but_cannot_authorize_strict(tmp_path):
    path = tmp_path / "measured.json"
    settings = Settings(memory_policy="development", measurement_path=str(path))
    report = memory_report(settings)
    path.write_text(json.dumps(report))
    assert runtime.verify_memory_report(settings)
    assert report["samples"][1]["pressure"] == 2 and report["samples"][-1]["swap_bytes"] == 200
    with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        runtime.verify_memory_report(replace(settings, memory_policy="strict"))
    for key in ("critical", "missing_policy"):
        bad = memory_report(settings, pressure=4 if key == "critical" else 2)
        if key == "missing_policy":
            del bad["memory_policy"]
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
            runtime.verify_memory_report(settings)


def test_development_start_allows_warning_but_blocks_critical(tmp_path, monkeypatch):
    for name in ("verify_artifacts", "verify_memory_report", "live_facts"):
        monkeypatch.setattr(runtime, name, lambda *_: "fixed")
    monkeypatch.setattr(runtime, "_VERIFIED_CONTRACTS", {("fixed", "fixed", "fixed")})
    settings = Settings(memory_policy="development", api_key="local", d1_token="local", worker_token="local",
                        model_path=str(tmp_path), d1_model_path=str(tmp_path), measurement_path=str(tmp_path),
                        model_revision="fixed", d1_revision="fixed", runtime_version="fixed", d1_runtime_version="fixed")
    monkeypatch.setattr(runtime, "memory_sample", lambda: {"pressure": 2})
    assert runtime.check_readiness(settings) == {"ready": True, "blockers": []}
    monkeypatch.setattr(runtime, "memory_sample", lambda: {"pressure": 4})
    assert runtime.check_readiness(settings) == {"ready": False, "blockers": ["LOCAL_MEMORY_CRITICAL"]}


def test_development_cache_evidence_keeps_its_policy_and_rejects_nested_critical(tmp_path):
    path = tmp_path / "cache-memory.json"
    settings = Settings(memory_policy="development", qwen_plan_cache_enabled=True, measurement_path=str(path))
    report = memory_report(settings)
    report["qwen_plan_cache"] = {"synthetic_only": True, "memory_policy": "development",
                                 "rows": cache_rows(), "samples": [dict(r) for r in report["samples"]]}
    path.write_text(json.dumps(report))
    assert runtime.verify_memory_report(settings)
    report["qwen_plan_cache"]["memory_policy"] = "strict"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        runtime.verify_memory_report(settings)
    report["qwen_plan_cache"]["memory_policy"] = "development"
    report["qwen_plan_cache"]["samples"][1]["pressure"] = 4
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        runtime.verify_memory_report(settings)


def test_development_stability_accepts_sleeping_models_at_warning(monkeypatch):
    from kplasma_agent.v2_local_llm.network import local_http_client
    settings = Settings(memory_policy="development")
    ticks = iter(range(100))
    monkeypatch.setattr(runtime.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(runtime.time, "sleep", lambda _: None)
    monkeypatch.setattr(runtime, "memory_sample", lambda **_: {"pressure": 2})
    monkeypatch.setattr(runtime, "local_http_client", lambda url, **kw: local_http_client(
        url, **kw, transport=httpx.MockTransport(lambda request: httpx.Response(200,
            json={"released":True,"loaded":False} if request.url.path=="/runtime" else {"is_sleeping":True}))))
    runtime.wait_for_stability(settings)


def test_development_critical_pressure_blocks_each_new_model_stage(monkeypatch):
    settings = Settings(memory_policy="development")
    monkeypatch.setattr(runtime, "memory_sample", lambda: {"pressure": 4})
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("critical reached native model"))) as client:
        with pytest.raises(ValueError, match="LOCAL_MEMORY_CRITICAL"):
            runtime.ModelRuntime(settings, client, client).prepare("plan")


def test_development_warning_is_logged_without_stopping_the_model_stage(monkeypatch, caplog):
    settings = Settings(memory_policy="development", model_path="/synthetic/qwen.gguf")
    monkeypatch.setattr(runtime, "memory_sample", lambda: {"pressure": 2})
    data = {"model_path": settings.model_path, "total_slots": 1, "is_sleeping": True,
            "default_generation_settings": {"n_ctx": settings.context_tokens}}
    def respond(request):
        if request.url.path=="/unload":
            return httpx.Response(200,json={"engine":"mlx-decision","released":True,"loaded":False,
                "memory":{"active_bytes":100,"cache_bytes":0},"idle_active_bytes":100})
        return httpx.Response(200,json=data)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime.ModelRuntime(settings, client, client).prepare("plan")
    assert any("pressure=2" in record.message and "plan" in record.message for record in caplog.records)


def test_cache_probe_uses_the_same_development_policy_without_hiding_swap():
    from evals.local_llm_cache_probe import assess_probe
    samples = [{"pressure": 1, "swap_bytes": 100, "resident_bytes": 1000},
               {"pressure": 2, "swap_bytes": 200, "resident_bytes": 1200}]
    result = assess_probe(cache_rows(), samples, memory_policy="development")
    assert result["protocol_passed"] and result["memory_passed"]
    assert result["swap_growth_bytes"] == 100
    samples[-1]["pressure"] = 4
    assert not assess_probe(cache_rows(), samples, memory_policy="development")["memory_passed"]
