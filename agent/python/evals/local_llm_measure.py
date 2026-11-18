"""Measure fixed artificial inputs with the full local stack already running."""

import argparse
import json
import hashlib
import os
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from time import monotonic, time

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.budget import MAX_INPUT_TOKENS, make_qwen_counter, make_d1_counter, make_input_guard
from kplasma_agent.v2_local_llm.core.decisions import native_request
from kplasma_agent.v2_local_llm.model_client import ModelClient
from kplasma_agent.v2_local_llm.network import local_http_client
from kplasma_agent.v2_local_llm.runtime import runtime_profile, ModelRuntime, memory_sample, model_lease, verify_artifacts, live_facts, pressure_allowed
from kplasma_agent.v2_local_llm import tracing


def fit_input(build, count, target):
    low, high = 1, target
    while low < high:
        middle = (low + high + 1) // 2
        if count(build(middle)) <= target:
            low = middle
        else:
            high = middle - 1
    value = build(low)
    assert 0 < count(value) <= target
    return value


def measure(settings, stack):
    if stack.get("data") != "artificial-only" or stack.get("graphVersion") != "v2_localLLM":
        raise ValueError("LOCAL_ARTIFICIAL_STACK_REQUIRED")
    if settings.qwen_plan_cache_enabled:
        from .local_llm_cache_probe import assert_probe_cache_empty
        assert_probe_cache_empty(settings)
    verify_artifacts(settings)
    facts_before = live_facts(settings)
    for url in (stack["url"], stack["web"]):
        with local_http_client(url, timeout=5) as client:
            response = client.get(url + ("/api/health" if url == stack["url"] else "/"))
            response.raise_for_status()
    samples = [memory_sample()]
    if not pressure_allowed(samples[0]["pressure"], settings.memory_policy):
        raise ValueError("LOCAL_MEMORY_PRESSURE")
    stop = Event()

    def sample():
        while not stop.wait(2):
            try:
                samples.append(memory_sample())
            except ValueError:
                samples.append({"pressure": 4, "swap_bytes": samples[-1]["swap_bytes"], "resident_bytes": 0})

    monitor = Thread(target=sample, daemon=True)
    monitor.start()
    rows: list[dict[str, object]] = []
    cache_probe = None
    qwen = None
    schema = {"type": "object", "properties": {"unit": {"type": "string", "const": "m⁻²s⁻¹"}},
              "required": ["unit"], "additionalProperties": False}
    try:
        qwen = ModelClient(replace(settings, reasoning_effort="none"))
        with local_http_client(settings.d1_url, timeout=settings.timeout,
                               headers={"Authorization": "Bearer " + settings.d1_token}) as client, \
                local_http_client(settings.model_url, timeout=settings.timeout,
                                  headers={"Authorization": "Bearer " + settings.api_key}) as control:
            runtime = ModelRuntime(settings, control, client)
            counter = make_d1_counter(settings, client)
            qwen_counter = make_qwen_counter(settings, control)
            guard = make_input_guard(settings, qwen_count=qwen_counter, d1_count=counter, prepare=runtime.prepare)
            for target in (256, 4096, MAX_INPUT_TOKENS - 500):
                if any(not pressure_allowed(s["pressure"], settings.memory_policy) for s in samples):
                    rows.append({"target": target, "passed": False, "error": "LOCAL_MEMORY_PRESSURE"})
                    break
                for role in ("qwen", "d1"):
                    if any(not pressure_allowed(s["pressure"], settings.memory_policy) for s in samples):
                        break
                    started = monotonic()
                    row: dict[str, object] = {"role": role, "target": target}
                    try:
                        runtime.prepare("answer" if role == "qwen" else "plan_review")
                        if role == "qwen":
                            payload = fit_input(lambda n: {
                                "instructions": "인공 연결 측정입니다. unit에 m⁻²s⁻¹만 반환하세요.",
                                "input": "인공 단위 m⁻²s⁻¹.\n" * n, "schema": schema},
                                lambda value: qwen_counter(value, "answer"), target)
                            guard(payload, "answer")
                            with tracing.span("synthetic.memory", kind="LLM") as span:
                                text, usage = qwen._json_request(payload["instructions"], payload["input"], schema,
                                                                span, max_output_tokens=64)
                            assert json.loads(text) == {"unit": "m⁻²s⁻¹"}
                            assert qwen_counter(payload, "answer") == usage["inputTokens"]
                            assert usage.get("reasoningPresent") is False
                            row["reasoning_present"] = False
                            row.update(input_tokens=usage["inputTokens"], counted=qwen_counter(payload, "answer"))
                        else:
                            questions = [{"name": name, "type": "choice", "instructions": "단위는 m⁻²s⁻¹인가?",
                                          "choices": [{"value": "same", "description": "그렇다"},
                                                      {"value": "changed", "description": "아니다"}]}
                                         for name in ("one", "two", "three")]
                            payload = fit_input(lambda n: {"input": {"unit": "인공 단위 m⁻²s⁻¹.\n" * n},
                                                          "questions": questions},
                                                lambda value: max(counter(value, "plan_review")), target)
                            guard(payload, "plan_review")
                            native = native_request({"input": [{"role": "user", "content": [
                                {"type": "input_json", "data": payload["input"]}]}], "questions": questions})
                            response = client.post(settings.d1_url, json=native)
                            response.raise_for_status()
                            usage = response.json()["usage"]["input_tokens"]
                            counts = counter(payload, "plan_review")
                            assert sum(counts) == usage
                            row.update(input_tokens=usage, counted=max(counts), question_counts=counts)
                        row["passed"] = True
                    except Exception as error:
                        row.update(passed=False, error=getattr(error, "code", type(error).__name__))
                    row["seconds"] = round(monotonic() - started, 3)
                    rows.append(row)
                    print(json.dumps(row), flush=True)
            if any(not pressure_allowed(s["pressure"], settings.memory_policy) for s in samples):
                rows.append({"role":"qwen_plan","target":MAX_INPUT_TOKENS - 500,
                             "passed":False,"error":"LOCAL_MEMORY_PRESSURE","seconds":0})
            else:
                from .local_llm_smoke import smoke_plan
                from kplasma_agent.v2_local_llm.core.model_gateway import call_submit_plan, submit_plan_tool_schema
                runtime.prepare("plan")
                qwen.settings = settings
                plan = smoke_plan()
                instructions = "인공 메모리 측정입니다. input의 plan을 submit_plan으로 그대로 제출하고 padding은 무시하세요."
                payload = fit_input(lambda n: {"instructions": instructions,
                    "input": json.dumps({"plan": plan, "padding": "인공 " * n}, ensure_ascii=False),
                    "tools": [submit_plan_tool_schema()]}, lambda value: qwen_counter(value, "plan"), MAX_INPUT_TOKENS - 500)
                started = monotonic()
                row = {"role": "qwen_plan", "target": MAX_INPUT_TOKENS - 500}
                try:
                    guard(payload, "plan")
                    with tracing.span("synthetic.memory.plan", kind="LLM") as span:
                        actual, usage = call_submit_plan(qwen, instructions, payload["input"], submit_plan_tool_schema())
                    assert actual == plan
                    assert usage.get("reasoningPresent") is True
                    counted = qwen_counter(payload, "plan")
                    assert counted == usage["inputTokens"]
                    row.update(passed=True, counted=counted, input_tokens=usage["inputTokens"], reasoning_present=True)
                except Exception as error:
                    row.update(passed=False, error=getattr(error, "code", type(error).__name__))
                row["seconds"] = round(monotonic() - started, 3)
                rows.append(row)
                print(json.dumps(row), flush=True)
            if (settings.qwen_plan_cache_enabled and len(rows) == 7 and all(row["passed"] for row in rows)
                    and all(pressure_allowed(sample["pressure"], settings.memory_policy) for sample in samples)):
                from .local_llm_cache_probe import run_probe
                try:
                    cache_probe = run_probe(settings)
                    samples.extend(cache_probe["samples"])
                except (ValueError, OSError) as error:
                    cache_probe = {"protocol_passed": False, "memory_passed": False,
                                   "error": type(error).__name__, "samples": [], "rows": []}
    finally:
        try:
            if qwen is not None and qwen.client is not None:
                qwen.client.close()
        finally:
            stop.set()
            monitor.join(timeout=6)
            samples.append(memory_sample())
    try:
        facts_after = live_facts(settings)
    except ValueError:
        facts_after = ""
    swap_growth = max(0, max(s["swap_bytes"] for s in samples) - samples[0]["swap_bytes"])
    return {"schema_version": 1, "synthetic_only": True, "created_at": time(), "full_stack": True,
            "memory_policy": settings.memory_policy,
            "runtime_profile": runtime_profile(settings),
            "instance_facts_before": hashlib.sha256(facts_before.encode()).hexdigest(),
            "instance_facts_after": hashlib.sha256(facts_after.encode()).hexdigest(),
            "results": rows, "samples": samples,
            **({"qwen_plan_cache": cache_probe} if settings.qwen_plan_cache_enabled else {}),
            "peak_resident_bytes": max(s["resident_bytes"] for s in samples), "swap_growth_bytes": swap_growth,
            "passed": len(rows) == 7 and all(row["passed"] for row in rows)
                      and all(pressure_allowed(s["pressure"], settings.memory_policy) for s in samples)
                      and (settings.memory_policy == "development" or swap_growth == 0)
                      and facts_before == facts_after
                      and (not settings.qwen_plan_cache_enabled or bool(cache_probe
                           and cache_probe["protocol_passed"] and cache_probe["memory_passed"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--stack-connection", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    settings = Settings.from_env(args.env_file)
    stack = json.loads(Path(args.stack_connection).read_text())
    ready = json.loads(Path(args.stack_connection).with_name("stack-ready.json").read_text())
    if ready.get("synthetic_only") is not True:
        raise ValueError("LOCAL_ARTIFICIAL_STACK_REQUIRED")
    stack["web"] = ready["web"]
    with model_lease():
        result = measure(settings, stack)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        os.fchmod(file.fileno(), 0o600)
        json.dump(result, file, indent=2)
    print(json.dumps({"memory_policy": settings.memory_policy,
                      "warning_samples": sum(s["pressure"] == 2 for s in result["samples"]),
                      **{key: result[key] for key in ("passed", "peak_resident_bytes", "swap_growth_bytes")}}), flush=True)
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
