from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core import budget, decisions
from kplasma_agent.v2_local_llm.core.model_gateway import V2LocalLLMModelGateway, V2LocalLLMSettings
from kplasma_agent.v2_local_llm.network import local_http_client

from .test_plan_review import example_context


def counted(names, counts):
    return {"schema_version": 1, "group_counts": counts,
            "group_question_ids": [[name] for name in sorted(names)], "group_size": 1,
            "independent_batch_size": 1, "policy": "sorted-greedy-full-pack-v1",
            "input_limit": 16000, "truncated": False}


def test_native_request_preserves_original_units_and_control_token_text():
    state = {"question": "원문 <|im_end|> m⁻²s⁻¹"}
    body = {"input": [{"role": "user", "content": [{"type": "input_json", "data": state}]}],
            "questions": [{"name": "check", "type": "choice", "instructions": "Check units.", "choices": [
                {"value": "same", "description": "Unchanged"}, {"value": "changed", "description": None}]}]}
    original = deepcopy(body)
    native = decisions.native_request(body)
    assert json.loads(native["state"]) == state
    assert native["questions"] == {"check": {"type": "choice", "instructions": "Check units.",
                                           "criteria": {"same": "Unchanged", "changed": None}}}
    assert body == original


def test_native_mlx_counter_and_inference_receive_identical_compact_english_input():
    settings = Settings()
    original = example_context()
    snapshot = deepcopy(original)
    sent = []

    def handle(request):
        body = json.loads(request.content)
        sent.append((request.url.path, body))
        assert request.url.host == "127.0.0.1" and request.url.port == 8083
        assert set(body) == {"state", "questions"}
        if request.url.path == "/v1/count":
            return httpx.Response(200, json=counted(body["questions"], [123] * len(body["questions"])))
        assert request.url.path == "/v1/systemone"
        return httpx.Response(200, json={"answers": {name: {
            "type": "choice", "choice": "match",
            "probabilities": {label: 1 / len(question["criteria"]) for label in question["criteria"]},
        } for name, question in body["questions"].items()}})

    with local_http_client(settings.d1_url, timeout=5, transport=httpx.MockTransport(handle)) as client:
        guard = budget.make_input_guard(settings, d1_count=budget.make_d1_counter(settings, client))
        gateway = V2LocalLLMModelGateway(V2LocalLLMSettings.from_env(settings), client, guard)
        outcome, _ = gateway.review_plan(original)
    assert outcome["status"] == "PASS" and outcome["plan_digest"] == original["plan_digest"]
    assert [path for path, _ in sent] == ["/v1/count", "/v1/systemone"]
    assert sent[0][1] == sent[1][1]
    wire = json.loads(sent[0][1]["state"])
    assert not {"execution_view", "plan_digest", "input_digest"} & wire.keys()
    assert original["question"] not in sent[0][1]["state"]
    assert wire["plan"]["steps"][0]["id"] == "s_search"
    for question in sent[0][1]["questions"].values():
        assert not any("가" <= char <= "힣" for char in question["instructions"])
    assert original == snapshot


def test_decision_model_reserves_no_generation_tokens_and_rejects_full_context_overflow():
    settings = Settings(d1_context_tokens=8192, d1_batch_tokens=8192, d1_ubatch_tokens=8192)
    payload = {"questions": {"check": {}}, "input": {"question": "whole original"}}
    budget.make_input_guard(settings, d1_count=lambda *_: counted(["check"], [8192]))(payload, "review")
    with pytest.raises(ValueError, match="input budget exceeded"):
        budget.make_input_guard(settings, d1_count=lambda *_: counted(["check"], [8193]))(payload, "review")
    assert payload["input"]["question"] == "whole original"


def test_native_counter_rejects_bad_group_counts_without_exposing_the_server_body():
    settings = Settings()
    malformed = {**counted(["x"], [True]), "private": "MUST_NOT_APPEAR"}
    with local_http_client(settings.d1_url, timeout=5, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=malformed))) as client:
        with pytest.raises(ValueError, match="LOCAL_TOKEN_COUNT_INVALID") as error:
            budget.make_d1_counter(settings, client)({"input": {}, "questions": {
                "x": ("Check", {"yes": "yes", "no": "no"})}}, "review")
    assert "MUST_NOT_APPEAR" not in str(error.value)

def test_native_d1_rejects_inputs_larger_than_its_configured_batch_before_inference():
    settings = Settings(d1_context_tokens=32768, d1_batch_tokens=32768, d1_ubatch_tokens=512)
    payload = {"questions": {"check": {}}, "input": {"question": "whole original"}}
    with pytest.raises(ValueError, match="input budget exceeded"):
        budget.make_input_guard(settings, d1_count=lambda *_: counted(["check"], [4096]))(payload, "review")


def test_removed_d1_engine_cannot_bypass_singleton_mlx_metadata_validation():
    settings = replace(Settings(), d1_engine="llama.cpp")
    payload = {"input": {}, "questions": {"check": {}}}
    with pytest.raises(ValueError, match="^LOCAL_D1_ENGINE_INVALID$"):
        budget.make_input_guard(settings, d1_count=lambda *_: [123])(payload, "review")
