"""Fixed artificial Qwen save/sleep/d1/restore probe; no experimental input files."""

import argparse
import json
from pathlib import Path
from threading import Event, Thread
from time import monotonic

import httpx

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.bindings import resolve_inputs
from kplasma_agent.v2_local_llm.core.budget import make_d1_counter, make_input_guard, make_qwen_counter
from kplasma_agent.v2_local_llm.core.contracts import ForwardStep, PlanDraft
from kplasma_agent.v2_local_llm.core.model_gateway import (
    PLAN_INSTRUCTIONS,
    V2LocalLLMModelGateway,
    V2LocalLLMSettings,
    submit_plan_tool_schema,
)
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context
from kplasma_agent.v2_local_llm.core.plan_validation import validate_plan
from kplasma_agent.v2_local_llm.network import local_http_client
from kplasma_agent.v2_local_llm.metric_registry import normalize_value
from kplasma_agent.v2_local_llm.prompt_cache import QwenPlanCache
from kplasma_agent.v2_local_llm.runtime import (
    ModelRuntime,
    live_facts,
    memory_sample,
    model_lease,
    pressure_allowed,
    valid_cache_review,
    verify_artifacts,
)


def assess_probe(rows, samples, *, memory_policy="strict"):
    plans = [row for row in rows if row.get("kind") == "plan"]
    reviews = [row for row in rows if row.get("kind") == "review"]
    reused = plans[-1].get("cached_tokens") if plans else None
    protocol = (
        len(plans) == 2
        and all(row.get("valid") is True and row.get("save") == "saved" for row in plans)
        and len(reviews) == 2
        and all(valid_cache_review(row) for row in reviews)
        and not any(row.get("kind") == "error" for row in rows)
        and plans[-1].get("restore") == "disk"
        and type(reused) is int
        and 0 < reused <= plans[-1]["input_tokens"]
    )
    memory = bool(samples) and all(pressure_allowed(sample["pressure"], memory_policy) for sample in samples)
    growth = (
        max(0, max(sample["swap_bytes"] for sample in samples) - samples[0]["swap_bytes"])
        if samples
        else None
    )
    return {
        "protocol_passed": protocol,
        "semantic_review_passed": (len(reviews) == 2 and all(
            valid_cache_review(row) and row["status"] == "PASS" for row in reviews)),
        "memory_passed": memory and (memory_policy == "development" or growth == 0),
        "swap_growth_bytes": growth,
        "peak_resident_bytes": max(sample["resident_bytes"] for sample in samples) if samples else None,
    }


def assert_probe_cache_empty(settings):
    root = Path(settings.qwen_plan_cache_dir)
    if root.exists() and any(p.name == "cache.json" or p.name.startswith("kv-") for p in root.iterdir()):
        raise ValueError("LOCAL_CACHE_PROBE_REQUIRES_EMPTY_CACHE")


def validate_artificial_lookup(plan, power):
    lookups = [step for step in plan.steps if isinstance(step, ForwardStep)]
    expected = {"pressure": 2, "sourcePower": power, "biasPower": 200}
    if len(lookups) != 1:
        raise ValueError("LOCAL_CACHE_PROBE_PLAN_MISMATCH")
    conditions = resolve_inputs(lookups[0], {}, {})["conditions"]
    if any(normalize_value(key, conditions[key]["value"], conditions[key]["unit"]) != value
           for key, value in expected.items()):
        raise ValueError("LOCAL_CACHE_PROBE_PLAN_MISMATCH")


def run_probe(settings):
    if not settings.qwen_plan_cache_enabled:
        raise ValueError("LOCAL_CACHE_PROBE_REQUIRES_ENABLED_PROFILE")
    assert_probe_cache_empty(settings)
    # Like the existing synthetic memory measurement, this produces evidence, not a worker permit.
    verify_artifacts(settings)
    live_facts(settings)
    rows, samples = [], [memory_sample()]
    if not pressure_allowed(samples[0]["pressure"], settings.memory_policy):
        raise ValueError("LOCAL_MEMORY_PRESSURE")
    stop = Event()

    def sample():
        while not stop.wait(1):
            try:
                samples.append(memory_sample())
            except ValueError:
                samples.append({"pressure": 4, "swap_bytes": samples[-1]["swap_bytes"], "resident_bytes": 0})

    monitor = Thread(target=sample, daemon=True)
    monitor.start()
    models = None
    try:
        with (
            local_http_client(
                settings.model_url,
                timeout=settings.timeout,
                headers={"Authorization": "Bearer " + settings.api_key},
            ) as control,
            local_http_client(
                settings.d1_url,
                timeout=settings.timeout,
                headers={"Authorization": "Bearer " + settings.d1_token},
            ) as decisions,
        ):
            runtime = ModelRuntime(settings, control, decisions)
            guard = make_input_guard(
                settings,
                qwen_count=make_qwen_counter(settings, control),
                d1_count=make_d1_counter(settings, decisions),
                prepare=runtime.prepare,
            )
            cache = QwenPlanCache(settings, control)
            models = V2LocalLLMModelGateway(V2LocalLLMSettings.from_env(settings), decisions, guard)
            for index, power in enumerate((100, 150)):
                if any(not pressure_allowed(item["pressure"], settings.memory_policy) for item in samples):
                    raise ValueError("LOCAL_MEMORY_PRESSURE")
                question = (
                    f"인공 검증: 압력 2 mTorr, 소스 전력 {power} W, 바이어스 전력 200 W인 "
                    "Run의 기본 지표를 조회해줘."
                )
                messages = {"question": question}
                payload = {
                    "messages": messages,
                    "context_keys": ["comparison_entries"],
                    "confirmed_run_keys": [],
                    "base_revision": None,
                    "previous_plan": None,
                    "rejected_plan": None,
                    "validation_error": None,
                    "generation_failure": None,
                    "feedback": None,
                    "plan_review_feedback": None,
                    "verified_results": {},
                }
                if index == 0:
                    guard(
                        {
                            "instructions": PLAN_INSTRUCTIONS,
                            "input": json.dumps(payload, ensure_ascii=False),
                            "tools": [submit_plan_tool_schema()],
                        },
                        "plan",
                    )
                    erased = control.post(
                        httpx.URL(settings.model_url).copy_with(path="/slots/0", query=b"action=erase"),
                        timeout=5,
                    )
                    erased.raise_for_status()
                    cache.prepare()
                else:
                    models.plan_cache = cache
                started = monotonic()
                plan, usage = models.submit_plan(payload)
                if index == 0:
                    cache.save()
                row = {
                    "kind": "plan",
                    "seconds": round(monotonic() - started, 3),
                    "input_tokens": usage["inputTokens"],
                    "cached_tokens": (usage.get("rawUsage", {}).get("prompt_tokens_details") or {}).get(
                        "cached_tokens"
                    ),
                    "timings": usage.get("nativeTimings"),
                    **cache.stats,
                    "valid": False,
                }
                rows.append(row)
                valid = validate_plan(
                    PlanDraft.model_validate(plan),
                    messages=messages,
                    context_keys={"comparison_entries"},
                    data_required=True,
                )
                validate_artificial_lookup(valid, power)
                row["valid"] = True
                if any(not pressure_allowed(item["pressure"], settings.memory_policy) for item in samples):
                    raise ValueError("LOCAL_MEMORY_PRESSURE")
                reviewed, _ = models.review_plan(
                    build_plan_review_context(valid, 1, question, [], {"comparison_entries": []}, {})
                )
                rows.append({"kind": "review", "status": reviewed["status"], "result": reviewed})
                runtime.prepare("plan")
    except Exception as error:
        rows.append({"kind": "error", "code": getattr(error, "code", type(error).__name__)})
    finally:
        stop.set()
        monitor.join(timeout=6)
        samples.append(memory_sample())
        if models is not None:
            for model in (models.planner, models.writer):
                if model.client is not None:
                    model.client.close()
    return {"synthetic_only": True, "memory_policy": settings.memory_policy, "rows": rows, "samples": samples,
            **assess_probe(rows, samples, memory_policy=settings.memory_policy)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    settings = Settings.from_env(args.env_file)
    with model_lease():
        result = run_probe(settings)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    output.chmod(0o600)
    print(json.dumps({key: result[key] for key in (
        "protocol_passed", "memory_passed", "semantic_review_passed", "swap_growth_bytes")}))
    return 0 if result["protocol_passed"] and result["memory_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
