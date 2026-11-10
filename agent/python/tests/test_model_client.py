import json
import httpx
import pytest
from pydantic import BaseModel
from kplasma_agent.model_client import ModelClient, ModelError
from kplasma_agent.config import Settings


class Output(BaseModel):
    answer: str


def streamed_response(text, *, status="completed", refusal=False, before_terminal=None, terminal=True,
                      error=False, sdk_error=False, usage=None, incomplete_reason=None):
    response = {
        "id": "synthetic", "object": "response", "created_at": 0, "status": status,
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [], "model": "gpt-5.6-luna",
        "output": [], "usage": usage,
        "incomplete_details": {"reason": incomplete_reason} if incomplete_reason else None,
    }
    message = {"type": "message", "id": "message", "role": "assistant", "status": "in_progress",
               "content": []}
    part = {"type": "output_text", "text": "", "annotations": []}

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            events = [
                {"type": "response.created", "response": {**response, "status": "in_progress"}},
                {"type": "response.output_item.added", "output_index": 0, "item": message},
                {"type": "response.content_part.added", "output_index": 0, "content_index": 0,
                 "item_id": "message", "part": part},
            ]
            for sequence, event in enumerate(events):
                yield encode(event, sequence)
            yield encode({"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                          "item_id": "message", "delta": text, "logprobs": []}, 3)
            if before_terminal:
                before_terminal()
            if error:
                yield encode({"type": "error", "code": "server_error", "message": "private-provider-body",
                              "param": None}, 4)
            if sdk_error:
                yield encode({"error": {"message": "private-provider-body"}}, 4)
            if terminal:
                content = ([{"type": "refusal", "refusal": "synthetic refusal"}] if refusal else
                           [{**part, "text": text}])
                yield encode({"type": "response." + status,
                              "response": {**response, "output": [{**message, "status": "completed",
                                                                     "content": content}]}}, 5)

    def encode(event, sequence):
        return ("data: " + json.dumps({**event, "sequence_number": sequence}) + "\n\n").encode()

    return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Body())


def test_generate_delivers_delta_while_the_provider_terminal_event_is_withheld():
    observed = []
    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["stream"] is True
        assert body["text"]["format"]["strict"] is True
        assert "text_format" not in body
        return streamed_response('{"answer":"한국어 😀"}',
                                 before_terminal=lambda: observed == ['{"answer":"한국어 😀"}'] or
                                 pytest.fail("the first text must arrive before response.completed"))

    client = ModelClient(Settings(api_key="test"),
                         http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    value, _ = client.generate("instructions", {}, Output, on_text_delta=observed.append)
    assert value == {"answer": "한국어 😀"}
    assert len(requests) == 1


@pytest.mark.parametrize("status,refusal,terminal,code", [
    ("incomplete", False, True, "MODEL_RESPONSE_INCOMPLETE"),
    ("failed", False, True, "MODEL_RESPONSE_FAILED"),
    ("completed", True, True, "MODEL_REFUSED"),
    ("completed", False, False, "MODEL_STREAM_INTERRUPTED"),
])
def test_stream_preserves_terminal_validation(status, refusal, terminal, code):
    client = ModelClient(Settings(api_key="test"), http_client=httpx.Client(transport=httpx.MockTransport(
        lambda request: streamed_response('{"answer":"draft"}', status=status,
                                          refusal=refusal, terminal=terminal))))
    with pytest.raises(ModelError, match=code):
        client.generate("instructions", {}, Output, on_text_delta=lambda text: None)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status,reason,code", [
    ("incomplete", "max_output_tokens", "MODEL_OUTPUT_TRUNCATED"),
    ("incomplete", "content_filter", "MODEL_CONTENT_FILTERED"),
    ("incomplete", None, "MODEL_RESPONSE_INCOMPLETE"),
    ("incomplete", "private-provider-reason", "MODEL_RESPONSE_INCOMPLETE"),
    ("failed", None, "MODEL_RESPONSE_FAILED"),
])
def test_provider_terminal_status_and_safe_reason_are_distinct(stream, status, reason, code, trace_capture):
    requests = []
    usage = {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33}

    def transport(request):
        requests.append(request)
        if stream:
            return streamed_response('{"answer":"draft"}', status=status, incomplete_reason=reason, usage=usage)
        return httpx.Response(200, json={
            "id": "synthetic", "object": "response", "created_at": 0, "status": status,
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "model": "gpt-5.6-luna", "output": [], "usage": usage,
            "incomplete_details": {"reason": reason} if reason else None,
            "error": {"code": "server_error", "message": "private-provider-body"} if status == "failed" else None,
        })

    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        client = ModelClient(Settings(api_key="test"), http_client=http_client)
        with pytest.raises(ModelError) as error:
            client.generate("instructions", {}, Output, on_text_delta=(lambda text: None) if stream else None)
    assert error.value.code == code and error.value.retryable is False
    assert len(requests) == 1 and "private-provider" not in str(error.value)
    span = trace_capture.get_finished_spans()[0]
    assert span.attributes["error.code"] == code
    assert "private-provider" not in str(span.attributes)
    assert span.attributes["llm.token_count.prompt"] == 11
    assert span.attributes["llm.token_count.completion"] == 22
    assert span.attributes["llm.token_count.total"] == 33


def test_plain_general_answer_stream_keeps_native_tool_continuation():
    observed = []
    context = {"input": {"question": "synthetic"}, "responseItems": [], "call_id": "call",
               "output": {"verified": True}}

    def transport(request):
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["input"][-1]["call_id"] == "call"
        assert "text" not in body
        return streamed_response("일반 설명", before_terminal=lambda: observed == ["일반 설명"] or
                                 pytest.fail("plain answer was buffered until provider completion"))

    client = ModelClient(Settings(api_key="test"),
                         http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    assert client.stream_answer("instructions", {}, on_text_delta=observed.append,
                                tool_context=context)[0] == "일반 설명"


def test_streamed_structured_output_still_requires_final_pydantic_validation():
    client = ModelClient(Settings(api_key="test"), http_client=httpx.Client(transport=httpx.MockTransport(
        lambda request: streamed_response('{"answer":null}'))))
    with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID"):
        client.generate("instructions", {}, Output, on_text_delta=lambda text: None)


@pytest.mark.parametrize("sdk_error", [False, True])
def test_provider_error_event_cannot_turn_into_a_successful_answer(sdk_error):
    requests = []

    def transport(request):
        requests.append(request)
        return streamed_response('{"answer":"draft"}', error=not sdk_error, sdk_error=sdk_error)

    client = ModelClient(Settings(api_key="test"),
                         http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    with pytest.raises(ModelError, match="MODEL_STREAM_ERROR") as error:
        client.generate("instructions", {}, Output, on_text_delta=lambda text: None)
    assert len(requests) == 1
    assert "private-provider-body" not in str(error.value)


def test_stream_keeps_final_usage_in_metadata_and_trace(trace_capture):
    usage = {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16,
             "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}
    client = ModelClient(Settings(api_key="test"), http_client=httpx.Client(transport=httpx.MockTransport(
        lambda request: streamed_response('{"answer":"ok"}', usage=usage))))
    value, metadata = client.generate("instructions", {}, Output, on_text_delta=lambda text: None)
    assert value == {"answer": "ok"}
    assert metadata["inputTokens"] == 12 and metadata["outputTokens"] == 4
    span = trace_capture.get_finished_spans()[0]
    assert span.attributes["llm.token_count.total"] == 16
    assert json.loads(span.attributes["output.value"])["response"]["usage"]["total_tokens"] == 16


def test_unsupported_stream_is_not_retried_as_another_model_call():
    requests = []

    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "private-endpoint-details",
                                                   "type": "invalid_request_error"}})

    client = ModelClient(Settings(api_key="test"),
                         http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    with pytest.raises(ModelError, match="MODEL_HTTP_400") as error:
        client.generate("instructions", {}, Output, on_text_delta=lambda text: None)
    assert len(requests) == 1 and requests[0]["stream"] is True
    assert error.value.retryable is False


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


def test_provider_error_does_not_expose_response_or_key(trace_capture):
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
    client.client.base_url = "https://private-user:private-password@models.invalid/v1/"
    with pytest.raises(ModelError) as error:
        client.generate("test", {}, Output)
    assert "secret-token" not in str(error.value)
    assert error.value.code == "MODEL_HTTP_401"
    span = trace_capture.get_finished_spans()[0]
    assert span.attributes["error.code"] == "MODEL_HTTP_401"
    assert not any(secret in str(span.attributes)
                   for secret in ("secret-token-sensitive", "private-user", "private-password"))


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


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("failure,code,retryable", [
    ("timeout", "MODEL_TIMEOUT", True),
    ("connection", "MODEL_CONNECTION", True),
    (400, "MODEL_HTTP_400", False),
    (401, "MODEL_HTTP_401", False),
    (403, "MODEL_HTTP_403", False),
    (404, "MODEL_HTTP_404", False),
    (408, "MODEL_HTTP_408", False),
    (429, "MODEL_RATE_LIMITED", True),
    (500, "MODEL_HTTP_500", True),
    (503, "MODEL_HTTP_503", True),
])
def test_sdk_errors_keep_safe_specific_codes_without_hidden_retries(streaming, failure, code, retryable):
    requests = []

    def transport(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-provider-body", request=request)
        if failure == "connection":
            raise httpx.ConnectError("private-provider-body", request=request)
        return httpx.Response(failure, json={"error": {"message": "private-provider-body"}})

    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        client = ModelClient(Settings(api_key="private-api-key"), http_client=http_client)
        client.client.base_url = "https://private-user:private-password@models.invalid/v1/"
        with pytest.raises(ModelError) as error:
            client.generate("instructions", {}, Output,
                            on_text_delta=(lambda _: None) if streaming else None)
    assert error.value.code == code
    assert error.value.retryable is retryable
    assert len(requests) == 1
    assert not any(secret in repr(error.value.__dict__) or secret in str(error.value)
                   for secret in ("private-api-key", "private-provider-body", "private-user", "private-password"))


@pytest.mark.parametrize("failure,code", [
    (httpx.ReadTimeout, "MODEL_TIMEOUT"),
    (httpx.ReadError, "MODEL_CONNECTION"),
])
def test_transport_failure_after_a_stream_delta_keeps_the_specific_code(failure, code):
    observed, requests = [], []

    def interrupt_stream():
        raise failure("private-provider-body")

    def transport(request):
        requests.append(request)
        return streamed_response('{"answer":"draft"}', before_terminal=interrupt_stream)

    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        client = ModelClient(Settings(api_key="test"), http_client=http_client)
        with pytest.raises(ModelError) as error:
            client.generate("instructions", {}, Output, on_text_delta=observed.append)
    assert observed == ['{"answer":"draft"}']
    assert error.value.code == code and error.value.retryable is True
    assert len(requests) == 1 and "private-provider-body" not in str(error.value)


def test_other_sdk_errors_use_a_safe_non_retryable_fallback():
    from openai import APIError

    client = ModelClient(Settings(api_key="test"))

    def fail(**_):
        raise APIError("private-provider-body", httpx.Request("POST", "https://private.invalid"),
                       body={"error": "private-provider-body"})

    client.client.responses.create = fail
    with pytest.raises(ModelError) as error:
        client.generate("instructions", {}, Output)
    assert error.value.code == "MODEL_API_ERROR" and error.value.retryable is False
    assert "private" not in str(error.value)
