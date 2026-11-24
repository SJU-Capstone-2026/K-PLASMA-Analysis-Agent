"""Real local wire contracts, using artificial HTTP replies only."""

import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.contracts import GeneralAnswerDraft
from kplasma_agent.v2_local_llm.model_client import ModelClient, ModelError


def reply(text='{"paragraphs":["m⁻²s⁻¹"],"sources":[]}', *, finish="stop", usage=True):
    return {"id": "synthetic-chat", "object": "chat.completion", "created": 0,
            "model": "unsloth/Qwen3.5-9B-GGUF:Q4_K_M",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17} if usage else None}


def test_schema_request_uses_local_chat_json_and_keeps_native_usage():
    def handle(request):
        body = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:8082/v1/chat/completions"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["messages"] == [{"role": "system", "content": "인공 검증"},
                                    {"role": "user", "content": '{"question": "단위"}'}]
        assert body["reasoning_effort"] == "none" and body["max_tokens"] == 3000
        return httpx.Response(200, json=reply())

    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as http:
        model = ModelClient(Settings(api_key="synthetic", reasoning_effort="none"), http_client=http)
        result, usage = model.generate("인공 검증", {"question": "단위"}, GeneralAnswerDraft)
    assert result == {"paragraphs": ["m⁻²s⁻¹"], "sources": []}
    assert usage["rawUsage"]["prompt_tokens"] == 10 and usage["inputTokens"] == 10


@pytest.mark.parametrize("kind,code", [("length", "MODEL_OUTPUT_TRUNCATED"),
                                      ("reasoning_only", "MODEL_OUTPUT_INVALID"),
                                      ("refusal", "MODEL_REFUSED"),
                                      ("multiple", "MODEL_OUTPUT_INVALID")])
def test_chat_never_promotes_reasoning_refusals_truncation_or_extra_choices(kind, code):
    data = reply(finish="length" if kind == "length" else "stop")
    if kind == "reasoning_only":
        data["choices"][0]["message"].update(content="", reasoning_content=data["choices"][0]["message"]["content"])
    elif kind == "refusal":
        data["choices"][0]["message"]["refusal"] = "synthetic refusal"
    elif kind == "multiple":
        data["choices"] *= 2
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)),
                      trust_env=False) as http:
        model = ModelClient(Settings(api_key="synthetic", reasoning_effort="none"), http_client=http)
        with pytest.raises(ModelError, match=code):
            model.generate("인공 검증", {}, GeneralAnswerDraft)


@pytest.mark.parametrize("complete", [True, False])
def test_chat_stream_requires_finish_and_preserves_exact_json_deltas(complete):
    text = reply()["choices"][0]["message"]["content"]
    chunks = [{"id": "synthetic-chat", "object": "chat.completion.chunk", "created": 0,
               "model": "unsloth/Qwen3.5-9B-GGUF:Q4_K_M", "choices": [{"index": 0,
               "delta": {"content": text}, "finish_reason": None}]}]
    if complete:
        chunks += [{**chunks[0], "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]
    events = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, text=events, headers={"Content-Type": "text/event-stream"})), trust_env=False) as http:
        model = ModelClient(Settings(api_key="synthetic", reasoning_effort="none"), http_client=http)
        fragments = []
        if complete:
            result, usage = model.generate("인공 검증", {}, GeneralAnswerDraft, on_text_delta=fragments.append)
            assert result["paragraphs"] == ["m⁻²s⁻¹"] and "".join(fragments) == text
            assert usage["usageAvailable"] is False and usage["inputTokens"] is None
        else:
            with pytest.raises(ModelError, match="MODEL_STREAM_INTERRUPTED"):
                model.generate("인공 검증", {}, GeneralAnswerDraft, on_text_delta=fragments.append)
