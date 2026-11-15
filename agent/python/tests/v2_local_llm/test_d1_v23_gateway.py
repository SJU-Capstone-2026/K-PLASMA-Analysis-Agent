"""The actual gateway counts and sends the same projected d1 request."""

from copy import deepcopy
import json

import httpx

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.model_gateway import (
    V2LocalLLMModelGateway,
    V2LocalLLMSettings,
    review_plan,
)
from .test_plan_review import example_context


def native_answer(request):
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "answers": {
                name: {
                    "type": "choice",
                    "choice": "match",
                    "confidence": 1.0,
                    "probabilities": {key: float(key == "match") for key in q["criteria"]},
                }
                for name, q in body["questions"].items()
            },
            "usage": {"input_tokens": 100},
        },
    )


def test_final_plan_review_counts_exact_wire_and_preserves_original_snapshot():
    original = example_context()
    snapshot = deepcopy(original)
    counted = []
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return native_answer(request)

    def guard(body, role):
        assert role == "plan_review"
        counted.append(deepcopy(body))

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        settings = V2LocalLLMSettings.from_env(Settings())
        gateway = V2LocalLLMModelGateway(settings, client, guard)
        result, usage = gateway.review_plan(original)
    assert original == snapshot
    assert len(counted) == len(sent) == 1
    state = json.loads(sent[0]["state"])
    assert "execution_view" not in state
    assert "plan_digest" not in state and "input_digest" not in state
    assert state["plan"] == snapshot["plan"] and state["question"] == snapshot["question"]
    assert state == counted[0]["input"]
    qs = {q["name"]: q for q in counted[0]["questions"]}
    for name, native in sent[0]["questions"].items():
        assert native["instructions"] == qs[name]["instructions"]
        assert native["criteria"] == {x["value"]: x["description"] for x in qs[name]["choices"]}
    assert result["status"] == "PASS" and result["plan_digest"] == snapshot["plan_digest"]
    assert result["input_digest"] == snapshot["input_digest"]
    assert usage == {"input_tokens": 100}


def test_module_level_plan_review_uses_same_final_profile():
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return native_answer(request)

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        result, _ = review_plan(client, V2LocalLLMSettings.from_env(Settings()), example_context())
    assert result["status"] == "PASS"
    assert "execution_view" not in json.loads(sent[0]["state"])
