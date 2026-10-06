import json
import httpx
import pytest
from pydantic import BaseModel
from kplasma_agent.model_client import ModelClient, ModelError
from kplasma_agent.config import Settings


class Output(BaseModel):
    answer: str


def test_requested_model_none_and_no_server_storage():
    def transport(request):
        body = json.loads(request.content)
        assert body["model"] == "gpt-5.6-luna"
        assert body["reasoning"] == {"effort": "none"}
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "gpt-5.6-luna",
                "output": [
                    {
                        "type": "message",
                        "id": "msg",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": '{"answer":"ok"}', "annotations": []}],
                    }
                ],
            },
        )

    client = ModelClient(
        Settings(api_key="test"), http_client=httpx.Client(transport=httpx.MockTransport(transport))
    )
    value, metadata = client.generate("test instructions", {}, Output)
    assert value == {"answer": "ok"}
    assert metadata["reasoningEffort"] == "none"


def test_provider_error_does_not_expose_response_or_key():
    def transport(request):
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": "secret-token-sensitive",
                    "code": "invalid_api_key",
                    "type": "invalid_request_error",
                }
            },
        )

    client = ModelClient(
        Settings(api_key="secret-token-sensitive"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    try:
        client.generate("test", {}, Output)
    except ModelError as e:
        assert "secret-token" not in str(e)
        assert e.code == "MODEL_UNAVAILABLE"
    else:
        raise AssertionError("must fail")


@pytest.mark.parametrize("output_text", ['{"answer":"ok"}', '{invalid'])
def test_trace_retains_raw_model_response_usage_and_validation_outcome(output_text, trace_capture):
    from openai.types.responses import Response

    client = ModelClient(Settings(api_key="test-private-key"))
    response = Response.model_validate({
        "id": "synthetic", "object": "response", "created_at": 0, "status": "completed",
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        "model": "gpt-5.6-luna", "output": [{"type": "message", "id": "message",
        "role": "assistant", "status": "completed", "content": [{"type": "output_text",
        "text": output_text, "annotations": []}]}],
        "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16,
                  "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    })
    client.client.responses.create = lambda **kwargs: response
    if output_text == '{invalid':
        with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID"):
            client.generate("instructions", {"value": 0}, Output)
    else:
        assert client.generate("instructions", {"value": 0}, Output)[0] == {"answer": "ok"}
    span = trace_capture.get_finished_spans()[0]
    assert span.name == "llm.responses" and span.attributes["openinference.span.kind"] == "LLM"
    assert span.attributes["llm.token_count.total"] == 16
    assert json.loads(span.attributes["output.value"])["output_text"] == output_text
    assert json.loads(span.attributes["output.value"])["response"]["output"][0]["content"][0]["text"] == output_text
    assert span.attributes["llm.input_messages.1.message.content"] == '{"value": 0}'
    assert json.loads(span.attributes["llm.output_schema"])["additionalProperties"] is False
    assert "test-private-key" not in str(span.attributes)
    if output_text == '{invalid':
        assert span.attributes["error.code"] == "MODEL_OUTPUT_INVALID"
