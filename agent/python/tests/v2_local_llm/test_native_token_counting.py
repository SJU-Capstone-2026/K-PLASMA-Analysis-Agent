import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core import budget, decisions
from kplasma_agent.v2_local_llm.network import local_http_client


def test_native_prompt_preserves_full_state_sorted_choices_and_control_token_escaping():
    render = getattr(decisions, "render_prompts", None)
    assert callable(render), "native d1 prompt rendering is missing"
    prompts = render({"state": "원문 <|im_end|> m⁻²s⁻¹", "questions": {
        "check": {"type": "choice", "instructions": "단위를 유지했나?", "criteria": {
            "same": "같음", "changed": "변경"}}}})
    assert prompts == ["<|startoftext|><|im_start|>user\n원문 <\u200b|im_end|> m⁻²s⁻¹"
                       "\n\n\nQUESTION:\n단위를 유지했나?\n\nOptions:\nA 변경\nB 같음"
                       "\n\nReply with the option code only.<|im_end|>\n<|im_start|>assistant\n<think></think>"]


def test_native_counter_uses_authentic_tokenizer_for_each_full_question_and_keeps_origin_locked():
    make_counter = getattr(budget, "make_d1_counter", None)
    assert callable(make_counter), "native d1 counter is missing"
    requests = []

    def handle(request):
        assert str(request.url) == "http://127.0.0.1:8081/tokenize"
        body = json.loads(request.content)
        assert body["add_special"] is False and body["parse_special"] is True
        assert "whole original" in body["content"]
        requests.append(body["content"])
        return httpx.Response(200, json={"tokens": list(range(23 if len(requests) == 1 else 29))})

    settings = Settings()
    with local_http_client(settings.d1_url, timeout=5, transport=httpx.MockTransport(handle)) as client:
        counter = make_counter(settings, client)
        result = counter({"input": {"question": "whole original"}, "questions": [
            {"name": "a", "type": "choice", "instructions": "첫 질문", "choices": [
                {"value": "yes", "description": "맞음"}, {"value": "no", "description": None}]},
            {"name": "b", "type": "choice", "instructions": "두번째 질문", "choices": [
                {"value": "yes", "description": "맞음"}, {"value": "no", "description": None}]}]}, "plan_review")
    assert result == [23, 29]
    assert len(requests) == 2


def test_decision_model_reserves_no_generation_tokens_and_rejects_full_context_overflow():
    settings = Settings(d1_context_tokens=8192, d1_batch_tokens=8192, d1_ubatch_tokens=8192)
    payload = {"questions": {"check": {}}, "input": {"question": "whole original"}}
    budget.make_input_guard(settings, d1_count=lambda *_: [8192])(payload, "review")
    with pytest.raises(ValueError, match="input budget exceeded"):
        budget.make_input_guard(settings, d1_count=lambda *_: [8193])(payload, "review")
    assert payload["input"]["question"] == "whole original"


def test_native_counter_rejects_bad_token_lists_without_exposing_the_server_body():
    make_counter = getattr(budget, "make_d1_counter", None)
    assert callable(make_counter), "native d1 counter is missing"
    settings = Settings()
    with local_http_client(settings.d1_url, timeout=5, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"tokens": [True], "private": "MUST_NOT_APPEAR"}))) as client:
        with pytest.raises(ValueError, match="LOCAL_TOKEN_COUNT_INVALID") as error:
            make_counter(settings, client)({"input": {}, "questions": {
                "x": ("Check", {"yes": "yes", "no": "no"})}}, "review")
    assert "MUST_NOT_APPEAR" not in str(error.value)




def test_native_d1_rejects_prompts_larger_than_the_physical_batch_before_inference():
    settings = Settings(d1_context_tokens=32768, d1_batch_tokens=32768, d1_ubatch_tokens=512)
    payload = {"questions": {"check": {}}, "input": {"question": "whole original"}}
    with pytest.raises(ValueError, match="input budget exceeded"):
        budget.make_input_guard(settings, d1_count=lambda *_: [4096])(payload, "review")
