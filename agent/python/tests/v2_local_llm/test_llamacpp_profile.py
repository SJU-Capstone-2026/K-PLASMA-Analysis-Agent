"""The pinned llama.cpp profile keeps native contracts and role-specific thinking."""

import json
from dataclasses import replace

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.model_gateway import V2LocalLLMSettings
from .test_native_plan import invoke, native_reply


def test_llamacpp_alias_and_role_thinking_are_explicit():
    selected = V2LocalLLMSettings.from_env(Settings(api_key="synthetic-local"))
    assert selected.planner.model == selected.writer.model == "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"
    assert selected.planner.reasoning_effort == "medium"
    assert selected.writer.reasoning_effort == "none"
    assert selected.planner.model_url == "http://127.0.0.1:8082/v1"
    assert selected.decisions_url == "http://127.0.0.1:8081/v1/systemone"


def test_native_request_enables_thinking_without_promoting_reasoning_to_arguments():
    reply = native_reply()
    reply["choices"][0]["message"]["reasoning_content"] = "인공 검토 텍스트"
    (_, usage), requests = invoke(reply)
    body = requests[0]
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    assert body["reasoning_format"] == "deepseek"
    assert body["temperature"] == 0.6 and body["top_p"] == 0.95
    assert body["top_k"] == 20 and body["repeat_penalty"] == 1
    assert usage["inputTokens"] == 31
    assert usage["reasoningPresent"] is True


def test_reasoning_only_plan_is_rejected():
    from kplasma_agent.v2_local_llm.model_client import ModelError

    reply = native_reply()
    message = reply["choices"][0]["message"]
    message["reasoning_content"] = message.pop("tool_calls")[0]["function"]["arguments"]
    reply["choices"][0]["finish_reason"] = "stop"
    with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID"):
        invoke(reply)


def test_effective_thinking_and_sampling_are_fingerprinted_without_secrets():
    settings = Settings(api_key="secret-test-key", worker_token="secret-worker")
    versions = settings.versions()
    assert versions["qwenGeneration"]["planThinking"] is True
    assert versions["qwenGeneration"]["writerThinking"] is False
    assert versions["qwenGeneration"]["reasoningBudget"] == 2048
    assert versions["quantization"] == "Q4_K_M"
    assert "secret-test-key" not in json.dumps(versions)
    assert "secret-worker" not in json.dumps(versions)
    changed = replace(settings, reasoning_effort="none").versions()
    assert changed["configFingerprint"] != versions["configFingerprint"]


def test_writer_disables_thinking_and_never_streams_reasoning():
    from kplasma_agent.v2_local_llm.model_client import ModelClient
    from kplasma_agent.v2_local_llm import tracing

    seen = []
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id":"synthetic", "object":"chat.completion", "created":0,
            "model":"synthetic", "choices":[{"index":0,"finish_reason":"stop","message":{
                "role":"assistant","content":"{}","reasoning_content":"private synthetic reasoning"}}]})
    settings = V2LocalLLMSettings.from_env(Settings(api_key="synthetic-local")).writer
    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as http:
        model = ModelClient(settings, http_client=http)
        with tracing.span("synthetic.writer", kind="LLM") as span:
            text, metadata = model._json_request("인공", "인공", {"type":"object"}, span)
    assert text == "{}"
    assert metadata["reasoningPresent"] is True
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
