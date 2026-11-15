from dataclasses import replace
import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.budget import make_d1_counter, make_input_guard
from kplasma_agent.v2_local_llm.runtime import ModelRuntime


def selected():
    return replace(
        Settings(),
        d1_engine="mlx",
        d1_group_size=1,
        d1_precision="bf16",
        d1_input_profile="ko-full",
        d1_model="LiquidAI/d1-2B:BF16",
        d1_runtime_version="mlx-decision-1.3.0",
    )


def payload():
    return {
        "input": {"question": "synthetic"},
        "questions": {name: ("test", {"match": "same", "changed": "different"}) for name in ["q1", "q2"]},
    }


def test_mlx_counter_checks_full_packs_and_all_question_ids():
    s = selected()
    seen = []

    def respond(request):
        seen.append(str(request.url))
        assert set(json.loads(request.content)) == {"state", "questions"}
        return httpx.Response(
            200,
            json={
                "schema_version": 1,
                "group_counts": [123,124],
                "group_question_ids": [["q1"],["q2"]],
                "group_size": 1,
                "policy": "sorted-greedy-full-pack-v1",
                "input_limit": 16000,
                "truncated": False,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        guard = make_input_guard(s, d1_count=make_d1_counter(s, client))
        guard(payload(), "plan_review")
    assert seen == ["http://127.0.0.1:8083/v1/count"]


@pytest.mark.parametrize("ids", [[["q1"]], [["q1", "q1"]], [["q1", "q2", "extra"]]])
def test_mlx_budget_rejects_missing_duplicate_extra_checks(ids):
    s = selected()

    def count(*_):
        return {
            "schema_version": 1,
            "group_counts": [123,124],
            "group_question_ids": ids,
            "group_size": 1,
            "policy": "sorted-greedy-full-pack-v1",
            "input_limit": 16000,
            "truncated": False,
        }

    with pytest.raises(ValueError, match="LOCAL_TOKEN_COUNT_INVALID"):
        make_input_guard(s, d1_count=count)(payload(), "plan_review")


def test_mlx_profile_reports_actual_precision():
    versions = selected().versions()
    assert versions["d1Quantization"] == "BF16"
    assert versions["d1Engine"] == "mlx" and versions["d1GroupSize"] == 1


def test_only_singleton_mlx_profiles_are_accepted(monkeypatch):
    from kplasma_agent.v2_local_llm import runtime
    monkeypatch.setattr(runtime, "_mlx_libraries", lambda *_: "a" * 64)
    monkeypatch.setattr(Settings,"versions",lambda *_:{key:"synthetic" for key in [
        "planner","writer","decisions","quantization","d1Quantization","runtimeManifestHash","qwenGeneration"]})
    for changes in [{"d1_group_size":16}, {"d1_independent_batch_size":4}, {"d1_engine":"llama.cpp"}]:
        with pytest.raises(ValueError,match="LOCAL_D1_GROUP_CONFIG_INVALID"):
            runtime.runtime_profile(replace(selected(),**changes))


def test_q8_service_identity_is_bound_to_precision_and_loader_bytes(tmp_path,monkeypatch):
    from kplasma_agent.v2_local_llm import runtime
    from pathlib import Path
    s=replace(Settings(), d1_model_path=str(tmp_path), d1_runtime_version="pinned",d1_revision="rev",
              d1_token="local-d1")
    key=tmp_path/"key"
    key.write_text(s.d1_token)
    config=tmp_path/"service.json"
    config.write_text(json.dumps({"model_path":str(tmp_path),"precision":"q8","group_size":1,
        "independent_batch_size":1,"port":8083,"token_file":str(key)}))
    manifest=json.loads(Path(runtime.__file__).with_name("runtime-manifest.json").read_text())
    monkeypatch.setattr(runtime,"_mlx_variant",lambda *_:{"manifestSha256":"e"*64},raising=False)
    monkeypatch.setattr(runtime,"_mlx_libraries",lambda *_:"a"*64)
    monkeypatch.setattr(runtime,"_hash",lambda p:"e"*64 if p.name=="kplasma-manifest.json" else "a"*64)
    def output(args,**kwargs):
        if args[0].endswith("lsof"):
            return "p123\n"
        return f'/synthetic/python {runtime._mlx_script()} --config {config}'
    monkeypatch.setattr(runtime.subprocess,"check_output",output)
    facts={"engine":"mlx-decision","runtime_version":"pinned","source_commit":manifest["d1MLX"]["sourceCommit"],
        "model":s.d1_model,"revision":"rev","precision":"q8","dtype":"mixed-affine8-bf16",
        "offline":True,"device":"gpu","group_size":1,"group_policy":"sorted-greedy-full-pack-v1",
        "independent_batch_size":1,"input_limit":16000,"service_sha256":"a"*64,
        "weights_sha256":"a"*64,"libraries_sha256":"a"*64,"integrity_sha256":"a"*64,
        "manifest_sha256":"e"*64,"model_path":str(tmp_path),"pid":123}
    with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=facts)),trust_env=False) as client:
        assert runtime._mlx_server_facts(s,client)
        for changed in [{"precision":"bf16"},{"weights_sha256":"b"*64},{"dtype":"bfloat16"}]:
            original=dict(facts)
            facts.update(changed)
            with pytest.raises(ValueError,match="LOCAL_RUNTIME_PROFILE_MISMATCH"):
                runtime._mlx_server_facts(s,client)
            facts.clear()
            facts.update(original)
        config.write_text(json.dumps({"model_path":str(tmp_path),"precision":"bf16","group_size":1,
            "independent_batch_size":1,"port":8083,"token_file":str(key)}))
        with pytest.raises(ValueError,match="LOCAL_RUNTIME_PROFILE_MISMATCH"):
            runtime._mlx_server_facts(s,client)


def test_qwen_cannot_wake_until_mlx_reports_real_release(monkeypatch):
    s = selected()
    calls = []
    monkeypatch.setattr(ModelRuntime, "_models", lambda *_: None)

    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"engine": "mlx-decision", "released": False, "loaded": True})

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with pytest.raises(ValueError, match="LOCAL_D1_MEMORY_NOT_RELEASED"):
            ModelRuntime(s, client, client).prepare("plan")
    assert calls == [("POST", "/unload")]


def test_mlx_memory_evidence_requires_new_schema_and_release_proof(tmp_path, monkeypatch):
    from kplasma_agent.v2_local_llm import runtime

    monkeypatch.setattr(runtime, "_mlx_libraries", lambda *_: "a" * 64)

    s = replace(selected(), measurement_path=str(tmp_path / "memory.json"))
    rows = [
        {
            "role": r,
            "target": t,
            "counted": t,
            "input_tokens": t,
            "passed": True,
            "seconds": 3,
            "reasoning_present": r == "qwen_plan",
        }
        for r, t in [(r, t) for r in ("qwen", "d1") for t in (256, 4096, 15500)] + [("qwen_plan", 15500)]
    ]
    for row in rows:
        if row["role"] == "d1":
            row.update(
                group_counts=[row["target"]]*3,
                group_question_ids=[["one"],["three"],["two"]],
                input_tokens=row["target"]*3,
                released=True,
                release_memory={"active_bytes": 0, "cache_bytes": 0, "idle_active_bytes": 0},
            )
    report = {
        "schema_version": 2,
        "synthetic_only": True,
        "full_stack": True,
        "runtime_profile": runtime.runtime_profile(s),
        "results": rows,
        "instance_facts_before": "a" * 64,
        "instance_facts_after": "a" * 64,
        "samples": [{"pressure": 1, "swap_bytes": 0, "resident_bytes": 100}] * 3,
    }
    Path = __import__("pathlib").Path
    Path(s.measurement_path).write_text(json.dumps(report))
    assert runtime.verify_memory_report(s)
    monkeypatch.setattr(runtime, "_mlx_libraries", lambda *_: "b" * 64)
    with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        runtime.verify_memory_report(s)
    monkeypatch.setattr(runtime, "_mlx_libraries", lambda *_: "a" * 64)
    report["schema_version"] = 1
    Path(s.measurement_path).write_text(json.dumps(report))
    with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        runtime.verify_memory_report(s)
    report["schema_version"] = 2
    next(r for r in rows if r["role"] == "d1")["released"] = False
    Path(s.measurement_path).write_text(json.dumps(report))
    with pytest.raises(ValueError, match="LOCAL_MEMORY_EVIDENCE_INVALID"):
        runtime.verify_memory_report(s)


@pytest.mark.parametrize("header", [False, True])
def test_decision_adapter_rejects_truncation_even_with_valid_choices(header):
    from types import SimpleNamespace
    from kplasma_agent.v2_local_llm.core.model_gateway import _decisions_response

    request = {
        "input": [{"role": "user", "content": [{"type": "input_json", "data": {"question": "synthetic"}}]}],
        "questions": [
            {
                "name": "q",
                "type": "choice",
                "instructions": "test",
                "choices": [
                    {"value": "match", "description": "same"},
                    {"value": "changed", "description": "different"},
                ],
            }
        ],
    }

    def respond(_):
        return httpx.Response(
            200,
            json={
                "truncated": not header,
                "answers": {
                    "q": {"type": "choice", "choice": "match", "probabilities": {"match": 1, "changed": 0}}
                },
            },
            headers={"X-MLX-Decision-Truncated": "true"} if header else {},
        )

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with pytest.raises(ValueError, match="DECISIONS_INPUT_TRUNCATED"):
            _decisions_response(
                client,
                SimpleNamespace(
                    decisions_url="http://127.0.0.1:8083/v1/systemone", decisions_model="synthetic"
                ),
                request,
            )
