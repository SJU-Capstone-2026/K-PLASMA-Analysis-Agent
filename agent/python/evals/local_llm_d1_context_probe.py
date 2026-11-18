"""One frozen ten-case pass in one context mode; no warmups or retries."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
from typing import Any

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.budget import make_d1_counter, make_input_guard
from kplasma_agent.v2_local_llm.core.d1_context import project_check
from kplasma_agent.v2_local_llm.core.d1_input import prepare_d1_input
from kplasma_agent.v2_local_llm.core.decisions import native_request
from kplasma_agent.v2_local_llm.core.model_gateway import V2LocalLLMModelGateway, V2LocalLLMSettings
from kplasma_agent.v2_local_llm.core.plan_checks import review_questions
from kplasma_agent.v2_local_llm.network import local_http_client
from kplasma_agent.v2_local_llm.runtime import (
    ModelRuntime, live_facts, model_lease, runtime_profile, verify_artifacts, verify_memory_report,
)
from .local_llm_d1_v23_probe import ProbeMemory, digest, graph_review_state, measurements
from .local_llm_measure import error_code

CORPUS_SHA256 = "c27853259c724b75e8851af094974b5b3b4ef0256c728f8182510e1136a98c87"
EXPECTED = {
    "P05": ("filter.search.ionFlux", "boundary_changed"),
    "P06": ("filter.search.pressure", "value_changed"),
    "P08": ("targets.compare", "target_changed"),
    "P10": ("ordering.search", "direction_changed"),
    "B01": ("baseline.compare", "target_changed"),
}


def load_corpus(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CORPUS_SHA256:
        raise ValueError("LOCAL_D1_CONTEXT_CORPUS_MISMATCH")
    cases = json.loads(raw)
    names = [f"{pair}.{kind}" for pair in EXPECTED for kind in ("good", "bad")]
    if [case["case"] for case in cases] != names:
        raise ValueError("LOCAL_D1_CONTEXT_CORPUS_MISMATCH")
    for case in cases:
        bad = case["kind"] == "bad"
        intended = EXPECTED[case["pair"]] if bad else (None, None)
        checks = review_questions(case["context"])
        if (case["expected_status"] != ("ISSUE" if bad else "PASS")
                or (case["primary_check"], case["primary_reason"]) != intended
                or list(case["expected_checks"]) != [q["name"] for q in checks]
                or any(value != (intended[1] if key == intended[0] else "match")
                       for key, value in case["expected_checks"].items())):
            raise ValueError("LOCAL_D1_CONTEXT_CORPUS_MISMATCH")
    if sum(len(case["expected_checks"]) for case in cases) != 62:
        raise ValueError("LOCAL_D1_CONTEXT_CORPUS_MISMATCH")
    return cases


def score(case, result):
    checks = {row["name"]: row["choice"] for row in result.get("checks", [])}
    primary = case["primary_check"]
    choice = checks.get(primary)
    return {
        "status_correct": result["status"] == case["expected_status"],
        "item_detected": primary is not None and choice not in {None, "match", "unclear"},
        "reason_correct": primary is not None and choice == case["primary_reason"],
        "strict_match": (result["status"] == case["expected_status"]
                         and checks == case["expected_checks"]
                         and len(checks) == len(result.get("checks", []))),
        "extra_nonmatches": {key: value for key, value in checks.items()
                             if value != "match" and key != primary},
        "checks": checks,
    }


def selection_preflight(cases, profile):
    """Require every real plan check to select before making any model request."""
    manifests = {}
    for case in cases:
        view, questions = prepare_d1_input(case["context"], review_questions(case["context"]),
                                           role="plan_review", profile=profile)
        native = native_request({"input": [{"role": "user", "content": [
            {"type": "input_json", "data": view}]}], "questions": questions})
        projected = {}
        for name, question in native["questions"].items():
            _, _, trace = project_check(native["state"], name, question)
            if trace["action"] != "selected":
                raise ValueError("LOCAL_D1_CONTEXT_NOT_SELECTED")
            projected[name] = trace["state_sha256"]
        manifests[case["case"]] = projected
    return manifests


def audit_request(records, question_ids, *, require_selected=False):
    if ([r["path"] for r in records] != ["/v1/count", "/v1/systemone"]
            or any(r["status"] != 200 for r in records)
            or records[0]["body"] != records[1]["body"]):
        raise ValueError("LOCAL_D1_COUNT_WIRE_MISMATCH")
    question_ids = sorted(question_ids)
    counted, raw = [r["result"] for r in records]
    metrics = raw.get("local_metrics", {})
    counts = counted.get("group_counts", [])
    packs = counted.get("pack_fingerprints", [])
    context = counted.get("context", [])
    tokens = raw.get("usage", {}).get("input_tokens")
    if (counted.get("truncated") is not False
            or counted.get("group_question_ids") != [[name] for name in question_ids]
            or len(counts) != len(question_ids)
            or any(type(n) is not int or not 0 < n <= 16000 for n in counts)
            or type(tokens) is not int or tokens <= 0 or sum(counts) != tokens
            or len(packs) != len(question_ids) or packs != metrics.get("pack_fingerprints")
            or [p.get("question_ids") for p in packs] != [[name] for name in question_ids]
            or any(not isinstance(p.get("sha256"), str) or len(p["sha256"]) != 64 for p in packs)
            or len(context) != len(question_ids) or context != metrics.get("context")
            or [c.get("question_id") for c in context] != question_ids
            or any(not {"action", "reason", "tool_ids", "metric_ids", "version", "state_sha256"} <= c.keys()
                   for c in context)
            or metrics.get("released") is not True):
        raise ValueError("LOCAL_D1_PACK_MISMATCH")
    if require_selected and any(c["action"] != "selected" for c in context):
        raise ValueError("LOCAL_D1_CONTEXT_NOT_SELECTED")
    return {"input_tokens": tokens, "group_counts": counts, "context": context,
            "pack_fingerprints": packs, "count_seconds": records[0]["seconds"],
            "local_metrics": metrics, "count_matches_inference": True}


def summary(rows):
    good = [r for r in rows if r["expected"] == "PASS"]
    bad = [r for r in rows if r["expected"] == "ISSUE"]
    return {
        "completed": len(rows), "good_pass": sum(r["status"] == "PASS" for r in good),
        "bad_issue": sum(r["status"] == "ISSUE" for r in bad),
        "status_correct": sum(r["status_correct"] for r in rows),
        "item_detected": sum(r["item_detected"] for r in bad),
        "exact_reason": sum(r["reason_correct"] for r in bad),
        "strict_match": sum(r["strict_match"] for r in rows),
        "false_rejections": [r["case"] for r in good if r["status"] == "ISSUE"],
        "false_acceptances": [r["case"] for r in bad if r["status"] == "PASS"],
        "unclear_unavailable": [r["case"] for r in rows if r["status"] in {"UNCLEAR", "UNAVAILABLE"}],
        "unresolved_cases": [r["case"] for r in rows if not r["strict_match"]],
        "quality_goal_met": len(rows) == 10 and all(r["strict_match"] for r in rows),
        "totals": measurements(rows) if rows else None,
        "request_seconds_mean": statistics.mean(r["seconds"] for r in rows) if rows else None,
        "request_seconds_median": statistics.median(r["seconds"] for r in rows) if rows else None,
        "selector_actions": dict(Counter(c["action"] for r in rows for c in r.get("context", []))),
        "selector_reasons": dict(Counter(c["reason"] for r in rows for c in r.get("context", [])
                                         if c.get("reason") is not None)),
        "backend_seconds": {key: (sum(r["local_metrics"][key] for r in rows)
                                  if rows and all(key in r["local_metrics"] for r in rows) else None)
                            for key in ("seconds", "load_seconds", "release_seconds")},
        "count_seconds": sum(r["count_seconds"] for r in rows),
    }


def source_identity():
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted((root / "src/kplasma_agent/v2_local_llm").rglob("*.py")),
             root / "runtimes/d1_mlx/service.py", Path(__file__).resolve()]
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def run(settings, corpus_path, output):
    output = Path(output)
    try:
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("LOCAL_D1_PROBE_OUTPUT_EXISTS") from None
    report: dict[str, Any] = {"synthetic_only": True, "repetitions": 1, "mode": getattr(settings, "d1_context_mode", None),
              "corpus_sha256": CORPUS_SHA256, "rows": [], "audit": [], "attempted_reviews": 0,
              "inference_calls": 0, "count_calls": 0, "error": None, "memory": None}
    monitor = None
    gateway = None
    starts = {}

    def capture_request(request):
        if request.url.path in {"/v1/count", "/v1/systemone"}:
            key = "count_calls" if request.url.path == "/v1/count" else "inference_calls"
            report[key] += 1
            if report[key] > 10:
                raise ValueError("LOCAL_D1_CONTEXT_CALL_BUDGET")
            starts[id(request)] = time.monotonic()

    def capture_response(response):
        if response.request.url.path in {"/v1/count", "/v1/systemone"}:
            response.read()
            report["audit"].append({"path": response.request.url.path,
                "body": json.loads(response.request.content), "status": response.status_code,
                "result": response.json(), "seconds": time.monotonic() - starts[id(response.request)]})

    try:
        cases = load_corpus(corpus_path)
        if (settings.d1_context_mode not in {"full", "per_check"}
                or settings.d1_input_profile != "en-compact-no-view"
                or settings.d1_precision != "q8" or settings.d1_engine != "mlx"
                or settings.d1_model != "LiquidAI/d1-2B:MLX8"
                or settings.d1_group_size != 1 or settings.d1_independent_batch_size != 1
                or settings.qwen_plan_cache_enabled):
            raise ValueError("LOCAL_D1_PROBE_PROFILE_MISMATCH")
        model_settings = V2LocalLLMSettings.from_env(settings)
        if settings.d1_context_mode == "per_check":
            report["selection_preflight"] = selection_preflight(cases, settings.d1_input_profile)
        report["review_state"] = graph_review_state(model_settings)
        report["memory_policy"] = settings.memory_policy
        report["source_identity"] = source_identity()
        monitor = ProbeMemory(settings)
        monitor.monitor.start()
        with (model_lease(),
              local_http_client(settings.d1_url, timeout=90,
                                headers={"Authorization": "Bearer " + settings.d1_token}) as client,
              local_http_client(settings.model_url, timeout=90,
                                headers={"Authorization": "Bearer " + settings.api_key}) as control):
            verify_artifacts(settings)
            verify_memory_report(settings)
            facts = live_facts(settings)
            report["instance_facts_before"] = facts
            report["runtime_profile"] = runtime_profile(settings)
            client.event_hooks["request"].append(capture_request)
            client.event_hooks["response"].append(capture_response)
            runtime = ModelRuntime(settings, control, client)
            guard = make_input_guard(settings, d1_count=make_d1_counter(settings, client), prepare=runtime.prepare)
            gateway = V2LocalLLMModelGateway(model_settings, client, guard)
            for case in cases:
                if source_identity() != report["source_identity"]:
                    raise ValueError("LOCAL_RUNTIME_PROFILE_MISMATCH")
                graph_review_state(model_settings)
                monitor.stage = case["case"]
                monitor.check()
                before = len(report["audit"])
                report["attempted_reviews"] += 1
                started = time.monotonic()
                original_digest = digest(case["context"])
                result, usage = gateway.review_plan(case["context"])
                elapsed = time.monotonic() - started
                measured = audit_request(report["audit"][before:],
                    [q["name"] for q in review_questions(case["context"])],
                    require_selected=settings.d1_context_mode == "per_check")
                if settings.d1_context_mode == "per_check" and {
                    c["question_id"]: c["state_sha256"] for c in measured["context"]
                } != report["selection_preflight"][case["case"]]:
                    raise ValueError("LOCAL_D1_CONTEXT_NOT_SELECTED")
                row = {"case": case["case"], "expected": case["expected_status"], "status": result["status"],
                       **score(case, result), **measured, "seconds": elapsed,
                       "check_count": len(case["expected_checks"]), "usage": usage,
                       "original_digest": original_digest, "first_request": not report["rows"]}
                report["rows"].append(row)
                if original_digest != digest(case["context"]) or digest(load_corpus(corpus_path)) != digest(cases):
                    raise ValueError("LOCAL_D1_CONTEXT_INPUT_CHANGED")
                monitor.check()
                if result["status"] == "UNAVAILABLE":
                    raise ValueError("LOCAL_D1_REVIEW_UNAVAILABLE")
            report["instance_facts_after"] = live_facts(settings)
            if (report["instance_facts_after"] != facts
                    or runtime_profile(settings) != report["runtime_profile"]
                    or source_identity() != report["source_identity"]):
                raise ValueError("LOCAL_RUNTIME_PROFILE_MISMATCH")
    except Exception as error:
        report["error"] = error_code(error)
    finally:
        if gateway is not None:
            for model in (gateway.planner, gateway.writer):
                if model.client is not None:
                    try:
                        model.client.close()
                    except Exception as error:
                        report["error"] = report["error"] or error_code(error)
        if monitor is not None:
            try:
                report["memory"] = monitor.finish()
            except Exception as error:
                report["error"] = report["error"] or error_code(error)
        report["summary"] = summary(report["rows"])
        with os.fdopen(fd, "w") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
    if (report["error"] or len(report["rows"]) != 10 or not report["memory"]
            or not report["memory"]["passed"]):
        raise ValueError(report["error"] or "LOCAL_D1_COMPARISON_INCOMPLETE")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(Settings.from_env(args.env_file), args.corpus, args.output)
