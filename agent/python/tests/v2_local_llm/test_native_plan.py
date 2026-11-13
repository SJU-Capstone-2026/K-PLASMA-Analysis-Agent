"""Native plan submissions use one real function call, never message JSON."""

import copy
import json

import httpx
import pytest

from evals.local_llm_smoke import smoke_plan
from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.model_gateway import V2LocalLLMModelGateway, V2LocalLLMSettings
from kplasma_agent.v2_local_llm.model_client import ModelClient, ModelError


def native_reply(arguments=None):
    return {"id": "synthetic-native", "object": "chat.completion", "created": 0,
            "model": "mlx-community/Qwen3.5-9B-4bit", "choices": [{"index": 0,
            "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
            "tool_calls": [{"type": "function", "id": "synthetic-call", "function": {
                "name": "submit_plan", "arguments": json.dumps(
                    smoke_plan() if arguments is None else arguments, ensure_ascii=False)}}]}}],
            "usage": {"prompt_tokens": 31, "completion_tokens": 97, "total_tokens": 128}}


def invoke(response):
    requests = []
    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/v1/chat/completions"
        assert body["tool_choice"] == "required" and body["parallel_tool_calls"] is False
        assert len(body["tools"]) == 1 and body["tools"][0]["function"]["name"] == "submit_plan"
        assert "response_format" not in body and "text" not in body
        from kplasma_agent.v2_local_llm.core.model_gateway import submit_plan_tool_schema
        assert body["tools"][0]["function"]["parameters"] == submit_plan_tool_schema()["parameters"]
        return httpx.Response(200, json=response)
    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
        settings = V2LocalLLMSettings.from_env(Settings(api_key="synthetic-local"))
        gateway = V2LocalLLMModelGateway(settings, client, lambda *_: None)
        gateway.planner.client.close()
        gateway.planner = ModelClient(settings.planner, http_client=client)
        try:
            result = gateway.submit_plan({"messages": {"question": "인공 단위 검사"}})
        finally:
            gateway.writer.client.close()
    return result, requests


def test_native_plan_returns_the_existing_plan_and_real_usage():
    (plan, usage), requests = invoke(native_reply())
    assert plan == smoke_plan()
    assert usage["inputTokens"] == 31 and usage["outputTokens"] == 97
    assert len(requests) == 1


def test_json_encoded_top_level_lists_are_decoded_without_changing_the_plan():
    plan = smoke_plan()
    plan["steps"] = json.dumps(plan["steps"], ensure_ascii=False)
    plan["requirements"] = json.dumps(plan["requirements"], ensure_ascii=False)
    (actual, _), _ = invoke(native_reply(plan))
    assert actual == smoke_plan()


@pytest.mark.parametrize("encoded", ['[{"id":"broken"}', '"not a list"', '{"not":"a list"}'])
def test_invalid_encoded_lists_are_rejected_without_repair(encoded):
    plan = smoke_plan()
    plan["steps"] = encoded
    with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID"):
        invoke(native_reply(plan))


@pytest.mark.parametrize("bad", ["message", "other_tool", "two_calls", "empty_id", "invalid_json"])
def test_bad_native_envelopes_never_fall_back_to_content_or_execute(bad):
    response = native_reply()
    message = response["choices"][0]["message"]
    call = message["tool_calls"][0]
    if bad == "message":
        message["tool_calls"] = []
        message["content"] = json.dumps(smoke_plan())
        response["choices"][0]["finish_reason"] = "stop"
    elif bad == "other_tool":
        call["function"]["name"] = "reverse_search"
    elif bad == "two_calls":
        message["tool_calls"].append(copy.deepcopy(call))
    elif bad == "empty_id":
        call["id"] = ""
    else:
        call["function"]["arguments"] = "not JSON"
    with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID"):
        invoke(response)


@pytest.mark.parametrize("encoded,expected", [("None", None), ("null", None), ("1", 1)])
def test_native_nullable_scalar_encoding_is_decoded_only_for_revision(encoded, expected):
    plan = smoke_plan()
    plan["base_revision"] = encoded
    plan["requirements"][0]["text"] = "None null 1"
    (actual, _), _ = invoke(native_reply(plan))
    assert actual["base_revision"] == expected
    assert actual["requirements"][0]["text"] == "None null 1"


@pytest.mark.parametrize("bad", [True, 0, -1, "0", "01", "1.0", "true", "garbage"])
def test_invalid_revision_values_are_not_silently_coerced(bad):
    plan = smoke_plan()
    plan["base_revision"] = bad
    with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID"):
        invoke(native_reply(plan))


@pytest.mark.parametrize("bad,path,error_type", [
    ("field", "/steps/0/ExplainStep/confirmation", "extra_forbidden"),
    ("json", "/steps", "json_invalid"),
])
def test_argument_validation_reaches_replanning_with_its_exact_path_and_original_arguments(bad, path, error_type):
    from kplasma_agent.v2_local_llm.graph import _generation_failure

    plan = smoke_plan()
    if bad == "field":
        plan["steps"][0]["confirmation"] = "baseline"
    else:
        plan["steps"] = '[{"id":"broken"}'
    reply = native_reply(plan)
    with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID") as raised:
        invoke(reply)
    error = raised.value
    failure = _generation_failure({"error": error.code, "response": error.response, "usage": error.usage})
    issues = failure["validation_error"]["errors"]
    assert any(item["path"] == path and item["type"] == error_type for item in issues)
    original = reply["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert error.response["output"][0]["arguments"] == original
    assert failure["partial_arguments_tail"] == original[-500:]


def test_existing_graph_replans_with_native_validation_details_before_review_and_composition():
    from .test_graph import GeneralModel, Journal
    from kplasma_agent.v2_local_llm.graph import build_v2_local_llm_graph

    class Models(GeneralModel):
        def __init__(self):
            self.contexts = []

        def submit_plan(self, context):
            self.contexts.append(copy.deepcopy(context))
            plan = smoke_plan()
            if len(self.contexts) == 1:
                plan["steps"][0]["confirmation"] = "baseline"
            return invoke(native_reply(plan))[0]

    models, journal = Models(), Journal()
    question = smoke_plan()["requirements"][0]["sources"][0]["quote"]
    state = build_v2_local_llm_graph(models, journal, None).invoke({
        "request_id": "synthetic-native-replan", "question": question, "context": {}, "input_history": []})
    errors = models.contexts[1]["generation_failure"]["validation_error"]["errors"]
    assert any(item["path"] == "/steps/0/ExplainStep/confirmation" for item in errors)
    assert journal.calls == ["PLAN_INITIAL", "REPLAN", "PLAN_REVIEW", "COMPOSE"]
    assert state["replans"] == 1 and state["answer"]["answerSnapshot"]["executionStatus"] == "COMPLETE"


@pytest.mark.parametrize("bad", ["choice", "message", "calls", "call", "function", "missing_function", "arguments", "id"])
def test_malformed_native_envelopes_are_sanitized_for_the_existing_replan_contract(bad):
    response = native_reply()
    message = response["choices"][0]["message"]
    call = message["tool_calls"][0]
    if bad == "choice":
        response["choices"][0] = None
    elif bad == "message":
        response["choices"][0]["message"] = None
    elif bad == "calls":
        message["tool_calls"] = "invalid"
    elif bad == "call":
        message["tool_calls"][0] = None
    elif bad == "function":
        call["function"] = None
    elif bad == "missing_function":
        del call["function"]
    elif bad == "arguments":
        call["function"]["arguments"] = {"unexpected": "object"}
    else:
        call["id"] = 123
    with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID") as raised:
        invoke(response)
    if raised.value.response:
        assert all(isinstance(item["arguments"], str) for item in raised.value.response["output"])
