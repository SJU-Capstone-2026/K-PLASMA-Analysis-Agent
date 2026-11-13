from dataclasses import replace
import json
import os

import pytest

from kplasma_agent.v2_local_llm import runtime
from kplasma_agent.v2_local_llm.config import Settings


def test_measured_preparation_can_become_ready_and_live_memory_pressure_revokes_it(tmp_path, monkeypatch):
    check = getattr(runtime, "check_readiness", None)
    assert callable(check), "readiness is still a permanent placeholder"
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(runtime, "_VERIFIED_CONTRACTS", set())
    for name in ("verify_artifacts", "verify_memory_report", "live_facts"):
        monkeypatch.setattr(runtime, name, lambda *_: "fixed-profile")
    probes = []
    waits = []
    monkeypatch.setattr(runtime, "contract_probe", lambda *_: probes.append(True))
    monkeypatch.setattr(runtime, "wait_for_stability", lambda *_: waits.append(True))
    monkeypatch.setattr(runtime, "memory_sample", lambda: {"pressure": 1})
    settings = Settings(api_key="local-qwen", d1_token="local-d1", worker_token="local-worker",
                        model_path=str(tmp_path), d1_model_path=str(tmp_path), tokenizer_path=str(tmp_path),
                        measurement_path=str(tmp_path), model_revision="fixed", d1_revision="fixed",
                        runtime_version="fixed", d1_runtime_version="fixed")
    with runtime.model_lease():
        assert check(settings) == {"ready": False, "blockers": ["LOCAL_MODEL_RUNTIME_BUSY"]}
        assert probes == []
    assert check(settings) == {"ready": True, "blockers": []}
    assert check(settings) == {"ready": True, "blockers": []}
    assert len(probes) == 1
    assert len(waits) == 1
    monkeypatch.setattr(runtime, "memory_sample", lambda: {"pressure": 2})
    assert check(settings) == {"ready": False, "blockers": ["LOCAL_MEMORY_PRESSURE"]}


def test_ready_flags_and_old_os_filter_claims_cannot_replace_measurements(tmp_path):
    verify = getattr(runtime, "verify_memory_report", None)
    assert callable(verify), "measured memory evidence is missing"
    path = tmp_path / "ready.json"
    path.write_text(json.dumps({"ready": True, "passed": True, "egress_verified": True}))
    with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        verify(replace(Settings(), measurement_path=str(path)))


@pytest.mark.parametrize("code", ["LOCAL_MEMORY_PRESSURE", "LOCAL_MEMORY_CRITICAL"])
def test_failed_stability_is_not_cached_or_reported_as_a_model_format_failure(tmp_path, monkeypatch, code):
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(runtime, "_VERIFIED_CONTRACTS", set())
    for name in ("verify_artifacts", "verify_memory_report", "live_facts"):
        monkeypatch.setattr(runtime, name, lambda *_: "fixed-profile")
    monkeypatch.setattr(runtime, "memory_sample", lambda: {"pressure": 1})
    monkeypatch.setattr(runtime, "contract_probe", lambda *_: None)
    def fail(_):
        raise ValueError(code)
    monkeypatch.setattr(runtime, "wait_for_stability", fail)
    settings = Settings(api_key="local-qwen", d1_token="local-d1", worker_token="local-worker",
        model_path=str(tmp_path), d1_model_path=str(tmp_path), measurement_path=str(tmp_path),
        model_revision="fixed", d1_revision="fixed", runtime_version="fixed", d1_runtime_version="fixed")
    assert runtime.check_readiness(settings) == {"ready": False, "blockers": [code]}
    assert not runtime._VERIFIED_CONTRACTS


def test_memory_evidence_is_recomputed_and_bound_to_the_exact_runtime_profile(tmp_path):
    verify = getattr(runtime, "verify_memory_report", None)
    assert callable(verify), "measured memory evidence is missing"
    settings = Settings()
    profile = runtime.runtime_profile(settings)
    report = {"schema_version": 1, "synthetic_only": True, "full_stack": True, "runtime_profile": profile,
              "created_at": 1, "passed": True, "swap_growth_bytes": 0,
              "instance_facts_before":"a"*64,"instance_facts_after":"a"*64,
              "samples": [{"pressure": 1, "swap_bytes": 100, "resident_bytes": 1000}] * 3,
              "results": [{"role": role, "target": target, "counted": target, "input_tokens":target,"question_counts":[target],
                           "reasoning_present":False,"passed": True, "seconds": 3}
                          for target in (256, 4096, 15500) for role in ("qwen", "d1")] + [
                  {"role":"qwen_plan","target":15500,"counted":15500,"input_tokens":15500,"reasoning_present":True,"passed":True,"seconds":3}]}
    path = tmp_path / "measured.json"
    path.write_text(json.dumps(report))
    selected = replace(settings, measurement_path=str(path))
    assert verify(selected)
    report["samples"][-1] = {"pressure": 1, "swap_bytes": 200, "resident_bytes": 1000}
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        verify(selected)
    report["samples"] = [{"pressure": 1, "swap_bytes": 100, "resident_bytes": 1000}] * 3
    path.write_text(json.dumps(report))
    assert verify(selected)
    with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        verify(replace(selected, d1_ubatch_tokens=512))


def test_wrong_model_files_fail_before_any_runtime_request(tmp_path, monkeypatch):
    verify = getattr(runtime, "verify_artifacts", None)
    assert callable(verify), "model artifact verification is missing"
    path = tmp_path / "not-the-pinned-model.gguf"
    path.write_text("synthetic wrong model")
    manifest = json.loads(runtime.Path(runtime.__file__).with_name("runtime-manifest.json").read_text())
    with pytest.raises(ValueError, match="LOCAL_MODEL_ARTIFACT_MISMATCH"):
        verify(Settings(d1_model_path=str(path), model_path=str(tmp_path), tokenizer_path=str(tmp_path),
            model_revision=manifest["qwen"]["revision"], d1_revision=manifest["d1"]["revision"],
            runtime_version=manifest["qwenRuntimeVersion"], d1_runtime_version=manifest["d1"]["runtimeVersion"]))


def test_model_hash_cache_detects_same_size_updates_with_preserved_modified_time(tmp_path):
    path = tmp_path / "weights"
    path.write_bytes(b"first")
    original = path.stat()
    first = runtime._hash(path)
    path.write_bytes(b"other")
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert runtime._hash(path) != first


@pytest.mark.parametrize("role", ["qwen", "qwen_plan", "d1"])
def test_memory_evidence_rejects_mismatched_observed_token_counts(tmp_path, role):
    settings=Settings()
    rows=[{"role":r,"target":t,"counted":t,"input_tokens":t,"question_counts":[t],
           "reasoning_present":r=="qwen_plan","passed":True,"seconds":3}
          for r,t in [(r,t) for r in ("qwen","d1") for t in (256,4096,15500)]+[("qwen_plan",15500)]]
    next(r for r in rows if r["role"]==role)["input_tokens"]+=1
    report={"schema_version":1,"synthetic_only":True,"full_stack":True,
            "runtime_profile":runtime.runtime_profile(settings),"results":rows,
            "samples":[{"pressure":1,"swap_bytes":0,"resident_bytes":100}]*3,
            "instance_facts_before":"a"*64,"instance_facts_after":"a"*64}
    path=tmp_path/"measurement.json"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError,match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        runtime.verify_memory_report(replace(settings,measurement_path=str(path)))
