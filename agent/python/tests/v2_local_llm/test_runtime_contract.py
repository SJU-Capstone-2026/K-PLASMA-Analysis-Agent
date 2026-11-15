"""Synthetic protocol checks; these tests never contact a model or attest privacy."""

import json

import httpx
import pytest

from evals.local_llm_smoke import (
    SmokeError, decisions_response, plan_response, run_smoke, smoke_plan,
    validate_endpoint, writer_response,
)


@pytest.fixture(autouse=True)
def isolated_model_ownership(tmp_path, monkeypatch):
    from kplasma_agent.v2_local_llm import runtime
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))


def test_smoke_cannot_send_requests_while_another_model_operation_owns_the_servers():
    from kplasma_agent.v2_local_llm.runtime import model_lease, ModelRuntimeBusy

    def handle(_):
        pytest.fail("busy model ownership must stop smoke before inference")
    with model_lease(), httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
        with pytest.raises(ModelRuntimeBusy):
            run_smoke({"PLAN_REVIEW_ENABLED": "true", "QWEN_URL": "http://127.0.0.1:8082/v1",
                "D1_URL": "http://127.0.0.1:8081/v1/systemone", "QWEN_TOKEN": "local-qwen",
                "D1_TOKEN": "local-d1"}, client=client)


def plan_reply(plan=None):
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text",
            "text": json.dumps(plan or smoke_plan(), ensure_ascii=False)}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}


def writer_reply():
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text",
            "text": json.dumps({"paragraphs": ["인공 검증: m⁻²s⁻¹"], "sources": []}, ensure_ascii=False)}]}],
            "usage": {"input_tokens": 11, "output_tokens": 6}}


def events():
    value = writer_reply()
    text = value["output"][0]["content"][0]["text"]
    common = {"id": "synthetic", "object": "chat.completion.chunk", "created": 0, "model": "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"}
    rows = ["data: " + json.dumps({**common, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}), "",
            "data: " + json.dumps({**common, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}), "",
            "data: [DONE]", ""]
    return rows


def decision_reply():
    return {"answers": {"unit": {"type": "choice", "choice": "same",
            "probabilities": {"same": 0.9, "changed": 0.1}, "confidence": 0.9}}}


def test_smoke_blocks_nonliteral_loopback_targets_before_network_io():
    for value in ("https://api.openai.com/v1", "http://localhost:1234/v1", "http://127.0.0.1.evil/v1",
                  "http://token@127.0.0.1:8082/v1", "http://127.0.0.1:8082/v1?secret=x"):
        with pytest.raises(SmokeError, match="SMOKE_ENDPOINT_INVALID"):
            validate_endpoint(value, "/v1")
    assert validate_endpoint("http://127.0.0.1:8082/v1", "/v1") == "http://127.0.0.1:8082/v1"
    assert validate_endpoint("http://[::1]:1234/v1", "/v1") == "http://[::1]:1234/v1"


@pytest.mark.parametrize("kind", ["empty", "multiple", "wrong", "truncated", "incomplete"])
def test_plan_probe_rejects_invalid_or_incomplete_single_plan_contract(kind):
    reply = plan_reply()
    if kind == "empty":
        reply["output"] = []
    elif kind == "multiple":
        reply["output"] *= 2
    elif kind == "wrong":
        reply["output"][0]["type"] = "function_call"
    elif kind == "truncated":
        reply["output"][0]["content"][0]["text"] = '{"private":"MUST_NOT_APPEAR"'
    else:
        reply["status"] = "incomplete"
    with pytest.raises(SmokeError, match="SMOKE_PLAN_INVALID") as error:
        plan_response(reply)
    assert "MUST_NOT_APPEAR" not in str(error.value)


def test_plan_and_writer_probe_preserve_unicode_and_reject_extra_json_fields():
    assert plan_response(plan_reply()) == {"input_tokens": 10, "output_tokens": 5}
    assert writer_response(writer_reply()) == {"input_tokens": 11, "output_tokens": 6}
    reply = writer_reply()
    text = json.loads(reply["output"][0]["content"][0]["text"])
    text["unwanted"] = True
    reply["output"][0]["content"][0]["text"] = json.dumps(text)
    with pytest.raises(SmokeError, match="SMOKE_WRITER_INVALID"):
        writer_response(reply)


@pytest.mark.parametrize("kind", ["missing", "extra", "choice", "wrong_known_choice", "sum", "nan", "negative"])
def test_decision_probe_rejects_incomplete_or_invalid_native_probabilities(kind):
    reply = decision_reply()
    row = reply["answers"]["unit"]
    if kind == "missing":
        reply["answers"] = {}
    elif kind == "extra":
        row["probabilities"]["unknown"] = 0.0
    elif kind == "choice":
        row["choice"] = "unknown"
    elif kind == "wrong_known_choice":
        row["choice"] = "changed"
    elif kind == "sum":
        row["probabilities"] = {"same": 0.1, "changed": 0.1}
    elif kind == "nan":
        row["probabilities"]["same"] = float("nan")
    else:
        row["probabilities"] = {"same": 1.1, "changed": -0.1}
    with pytest.raises(SmokeError, match="SMOKE_DECISIONS_INVALID"):
        decisions_response(reply)


def test_decision_usage_is_not_fabricated_when_native_server_omits_it():
    assert decisions_response(decision_reply()) is None


def test_probe_rejects_a_valid_plan_that_changes_the_artificial_source_quote():
    plan = smoke_plan()
    plan["requirements"][0]["sources"][0]["quote"] = "변경된 단위"
    with pytest.raises(SmokeError, match="SMOKE_PLAN_INVALID"):
        plan_response(plan_reply(plan))


@pytest.mark.parametrize("qwen_token", ["synthetic-qwen", "sk-lm-synthetic:local-only"])
@pytest.mark.parametrize("d1_model", ["LiquidAI/d1-2B:MLX8", "LiquidAI/d1-2B:BF16"])
def test_synthetic_smoke_exercises_pinned_schema_stream_and_decisions_without_attesting_readiness(qwen_token, d1_model):
    calls = []
    prepares = []

    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url, body))
        if request.url.path == "/v1/systemone":
            assert body["state"]["unit"] == "m⁻²s⁻¹"
            assert set(body["questions"]["unit"]["criteria"]) == {"same", "changed"}
            return httpx.Response(200, json=decision_reply())
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer " + qwen_token
        assert body["model"] == "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"
        assert body["store"] is False
        assert body["reasoning_effort"] == "none"
        if "tools" in body:
            assert body["tools"][0]["function"]["name"] == "submit_plan"
            assert "response_format" not in body
            from .test_native_plan import native_reply
            plan = smoke_plan()
            plan["base_revision"] = "None"
            return httpx.Response(200, json=native_reply(plan))
        assert body["response_format"]["json_schema"]["strict"] is True
        text = writer_reply()["output"][0]["content"][0]["text"]
        if body.get("stream"):
            return httpx.Response(200, text="\n".join(events()) + "\n",
                                  headers={"Content-Type": "text/event-stream"})
        from .test_chat_schema import reply
        return httpx.Response(200, json=reply(text))

    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
        result = run_smoke({"QWEN_URL": "http://127.0.0.1:8082/v1", "QWEN_TOKEN": qwen_token,
                            "D1_URL": "http://127.0.0.1:8081/v1/systemone", "D1_TOKEN": "synthetic-d1",
                            "PLAN_REVIEW_ENABLED": "true", "D1_MODEL": d1_model}, client=client, prepare=prepares.append)
    assert len(calls) == 4
    assert prepares == ["plan", "answer", "answer", "plan_review"]
    assert result["passed"] is True and result["synthetic_only"] is True
    assert result["runtime_ready"] is False
    assert result["usage"]["decisions"] is None
    assert result["requested_models"]["d1"] == d1_model
    assert result["remaining_checks"] == ["LOCAL_AUTHORITATIVE_READINESS_NOT_CHECKED", "LOCAL_ANALYSIS_QUALITY_UNVERIFIED"]


@pytest.mark.parametrize("qwen,d1", [("sk-proj-synthetic", "synthetic-d1"),
                                    ("sk-lm-synthetic:local-only", "sk-proj-synthetic")])
def test_smoke_rejects_cloud_credentials_before_contacting_local_models(qwen, d1):
    def handle(_):
        pytest.fail("cloud credentials must not be sent")

    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
        with pytest.raises(SmokeError, match="SMOKE_LOCAL_AUTH_REQUIRED"):
            run_smoke({"PLAN_REVIEW_ENABLED": "true", "QWEN_URL": "http://127.0.0.1:8082/v1",
                       "D1_URL": "http://127.0.0.1:8081/v1/systemone", "QWEN_TOKEN": qwen,
                       "D1_TOKEN": d1}, client=client)


def test_smoke_never_follows_external_redirects_or_prints_http_error_bodies():
    calls = []

    def handle(request):
        calls.append(request.url)
        return httpx.Response(307, headers={"Location": "https://external.invalid/private-MUST_NOT_APPEAR"},
                              text="secret-MUST_NOT_APPEAR")

    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False, trust_env=False) as client:
        with pytest.raises(SmokeError, match="MODEL_HTTP_307") as error:
            run_smoke({"QWEN_URL": "http://127.0.0.1:8082/v1", "QWEN_TOKEN": "synthetic-qwen",
                       "D1_URL": "http://127.0.0.1:8081/v1/systemone", "D1_TOKEN": "synthetic-d1",
                       "PLAN_REVIEW_ENABLED": "true"}, client=client)
    assert len(calls) == 1 and calls[0].host == "127.0.0.1"
    assert "MUST_NOT_APPEAR" not in str(error.value)


def test_smoke_refuses_disabled_review_before_any_model_request():
    def handle(_):
        pytest.fail("disabled review must not contact a model")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SmokeError, match="SMOKE_PLAN_REVIEW_REQUIRED"):
            run_smoke({"PLAN_REVIEW_ENABLED": "false"}, client=client)
