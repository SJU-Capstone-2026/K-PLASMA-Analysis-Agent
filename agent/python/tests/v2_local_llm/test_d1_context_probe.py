"""Bounded artificial-corpus accounting; never calls a model."""

import json
from types import SimpleNamespace

import pytest
from evals import local_llm_d1_context_probe as probe


def case():
    return {"case": "P06.bad", "expected_status": "ISSUE", "primary_check": "filter.search.pressure",
            "primary_reason": "value_changed", "expected_checks": {"request.tasks": "match",
            "filter.search.pressure": "value_changed"}}


def test_wrong_item_or_reason_is_not_detection_and_extra_issue_breaks_strict_match():
    row = case()
    wrong = probe.score(row, {"status": "ISSUE", "checks": [
        {"name": "request.tasks", "choice": "unexpected"},
        {"name": "filter.search.pressure", "choice": "match"}]})
    assert wrong["status_correct"] and not wrong["item_detected"] and not wrong["reason_correct"]
    assert wrong["extra_nonmatches"] == {"request.tasks": "unexpected"}
    reason = probe.score(row, {"status": "ISSUE", "checks": [
        {"name": "request.tasks", "choice": "unexpected"},
        {"name": "filter.search.pressure", "choice": "unit_changed"}]})
    assert reason["item_detected"] and not reason["reason_correct"] and not reason["strict_match"]
    exact = probe.score(row, {"status": "ISSUE", "checks": [
        {"name": k, "choice": v} for k, v in row["expected_checks"].items()]})
    assert exact["reason_correct"] and exact["strict_match"]


def wire():
    meta = [{"question_id": "x", "action": "selected", "reason": None, "tool_ids": [],
             "metric_ids": [], "version": "1", "state_sha256": "a" * 64}]
    packs = [{"question_ids": ["x"], "sha256": "b" * 64}]
    counted = {"group_counts": [20], "group_question_ids": [["x"]], "pack_fingerprints": packs,
               "context": meta, "truncated": False}
    raw = {"usage": {"input_tokens": 20}, "local_metrics": {
        "released": True, "pack_fingerprints": packs, "context": meta}}
    return [{"path": p, "status": 200, "body": {"questions": {"x": {}}}, "result": r,
             "seconds": 0.2} for p, r in zip(["/v1/count", "/v1/systemone"], [counted, raw])]


def test_wire_requires_same_native_input_packing_selector_and_measured_usage():
    assert probe.audit_request(wire(), ["x"])["input_tokens"] == 20
    for target, key, value in [(0, "pack_fingerprints", []), (0, "context", []),
                               (0, "truncated", True)]:
        records = wire()
        records[target]["result"][key] = value
        with pytest.raises(ValueError):
            probe.audit_request(records, ["x"])
    records = wire()
    records[1]["result"]["usage"] = {}
    with pytest.raises(ValueError):
        probe.audit_request(records, ["x"])


@pytest.mark.parametrize("action", ["full", "fallback"])
def test_selected_only_audit_rejects_even_one_full_or_fallback(action):
    records = wire()
    records[0]["result"]["context"][0]["action"] = action
    with pytest.raises(ValueError, match="LOCAL_D1_CONTEXT_NOT_SELECTED"):
        probe.audit_request(records, ["x"], require_selected=True)


def test_selected_only_preflight_stops_before_models_if_one_rule_is_missing(monkeypatch):
    from .test_plan_review import example_context
    def unavailable(state, name, question):
        return state, question, {"action": "full", "reason": "missing_policy"}
    monkeypatch.setattr(probe, "project_check", unavailable)
    with pytest.raises(ValueError, match="LOCAL_D1_CONTEXT_NOT_SELECTED"):
        probe.selection_preflight([{"case": "artificial", "context": example_context()}],
                                  "en-compact-no-view")


def test_summary_keeps_failures_and_never_calls_no_regression_accurate():
    result = probe.summary([])
    assert result["completed"] == 0 and result["quality_goal_met"] is False
    assert result["totals"] is None


def test_corpus_hash_rejects_mutation_before_parsing(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text("[]")
    with pytest.raises(ValueError, match="CORPUS"):
        probe.load_corpus(p)


def test_preflight_failure_is_saved_exclusively_with_zero_attempts(tmp_path):
    output = tmp_path / "result.json"
    with pytest.raises(ValueError):
        probe.run(SimpleNamespace(d1_context_mode="full"), tmp_path / "missing.json", output)
    report = json.loads(output.read_text())
    assert report["attempted_reviews"] == 0 and report["inference_calls"] == 0 and report["error"]
    assert output.stat().st_mode & 0o777 == 0o600
    original = output.read_bytes()
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        probe.run(SimpleNamespace(), tmp_path / "missing.json", output)
    assert output.read_bytes() == original


@pytest.mark.parametrize("fail_at", [None, 4])
def test_runner_has_exactly_ten_calls_or_preserves_transport_failure_attempt(tmp_path, monkeypatch, fail_at):
    from contextlib import nullcontext
    import httpx

    cases = [{"case": f"artificial-{i}", "context": {"i": i}, "expected_status": "PASS",
              "expected_checks": {"x": "match"}, "primary_check": None, "primary_reason": None}
             for i in range(10)]
    monkeypatch.setattr(probe, "load_corpus", lambda _: cases)
    monkeypatch.setattr(probe, "source_identity", lambda: "fixed")
    monkeypatch.setattr(probe, "review_questions", lambda _: [{"name": "x"}])
    monkeypatch.setattr(probe, "graph_review_state", lambda _: {"plan_review_enabled": True})
    monkeypatch.setattr(probe, "verify_artifacts", lambda _: None)
    monkeypatch.setattr(probe, "verify_memory_report", lambda _: None)
    monkeypatch.setattr(probe, "live_facts", lambda _: "live")
    monkeypatch.setattr(probe, "runtime_profile", lambda _: {"mode": "full"})
    monkeypatch.setattr(probe, "model_lease", nullcontext)
    monkeypatch.setattr(probe, "make_input_guard", lambda *a, **kw: None)
    monkeypatch.setattr(probe, "make_d1_counter", lambda *a: None)
    monkeypatch.setattr(probe, "ModelRuntime", lambda *a: SimpleNamespace(prepare=None))
    monkeypatch.setattr(probe, "ProbeMemory", lambda _: SimpleNamespace(
        monitor=SimpleNamespace(start=lambda: None), check=lambda: None,
        finish=lambda: {"passed": True}))
    settings = SimpleNamespace(d1_context_mode="full", d1_input_profile="en-compact-no-view",
        d1_precision="q8", d1_engine="mlx", d1_model="LiquidAI/d1-2B:MLX8", d1_group_size=1,
        d1_independent_batch_size=1, qwen_plan_cache_enabled=False, memory_policy="development",
        d1_url="http://localhost/v1/systemone", model_url="http://localhost/v1", d1_token="", api_key="")
    monkeypatch.setattr(probe.V2LocalLLMSettings, "from_env", lambda _: settings)
    calls = {"infer": 0}

    def respond(request):
        index = 0 if request.url.path == "/v1/count" else 1
        if index == 1:
            calls["infer"] += 1
            if calls["infer"] == fail_at:
                raise httpx.ConnectError("artificial interruption")
        return httpx.Response(200, json=wire()[index]["result"])

    monkeypatch.setattr(probe, "local_http_client", lambda *a, **kw:
                        httpx.Client(transport=httpx.MockTransport(respond)))

    class Gateway:
        def __init__(self, settings, client, guard):
            self.client = client
            self.planner = self.writer = SimpleNamespace(client=None)

        def review_plan(self, context):
            self.client.post("http://localhost/v1/count", json={"state": "unchanged"})
            self.client.post("http://localhost/v1/systemone", json={"state": "unchanged"})
            return {"status": "PASS", "checks": [{"name": "x", "choice": "match"}]}, {"input_tokens": 20}

    monkeypatch.setattr(probe, "V2LocalLLMModelGateway", Gateway)
    output = tmp_path / "result.json"
    if fail_at:
        with pytest.raises(ValueError):
            probe.run(settings, "unused", output)
    else:
        report = probe.run(settings, "unused", output)
        assert report["summary"]["quality_goal_met"]
    report = json.loads(output.read_text())
    assert report["inference_calls"] == (fail_at or 10)
    assert report["count_calls"] == (fail_at or 10)
    assert report["attempted_reviews"] == (fail_at or 10)
    assert len(report["rows"]) == (fail_at - 1 if fail_at else 10)
