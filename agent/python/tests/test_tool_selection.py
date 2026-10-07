import json

import httpx
import pytest

from kplasma_agent.config import Settings
from kplasma_agent.model_client import ModelClient, ModelError


def response(items):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "gpt-5.6-luna",
        "status": "completed",
        "output": items,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }


def call(name="forward_lookup", args=None, call_id="call_test"):
    return {
        "id": "fc_test",
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(args or {}, ensure_ascii=False),
        "status": "completed",
    }


def test_native_tools_and_original_units():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=response(
                [
                    call(
                        args={
                            "conditions": {
                                "pressure": {"value": 8, "unit": "mTorr"},
                                "sourcePower": {"value": 300, "unit": "W"},
                                "biasPower": {"value": 600, "unit": None},
                            },
                            "context_rules": [],
                        }
                    )
                ]
            ),
        )

    model = ModelClient(Settings(api_key="test"), httpx.Client(transport=httpx.MockTransport(handler)))
    selected, metadata = model.select_tool(
        "rules", {"question": "압력 8 mTorr, 소스 300 오ㅏ트, 바이어스 600"}
    )
    assert selected["name"] == "forward_lookup"
    assert selected["arguments"]["conditions"]["biasPower"]["unit"] is None
    body = captured[0]
    assert body["tool_choice"] == "required" and body["parallel_tool_calls"] is False
    assert {t["name"] for t in body["tools"]} == {
        "forward_lookup",
        "reverse_search",
        "compare_runs",
        "generate_answer",
    }
    assert all(t["strict"] and not t["parameters"]["additionalProperties"] for t in body["tools"])
    assert body["reasoning"] == {"effort": "none"} and body["store"] is False
    assert "text" not in body
    assert metadata["responseItems"][0]["call_id"] == "call_test"


@pytest.mark.parametrize(
    "items",
    [
        [],
        [call("explain_concept")],
        [call(), call()],
        [call("compare_runs", {"ref_keys": ["R1", "R1"]})],
        [call("generate_answer", {"question": "copied"})],
    ],
)
def test_invalid_call_never_dispatches(items):
    model = ModelClient(
        Settings(api_key="test"),
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response(items)))
        ),
    )
    with pytest.raises(ModelError, match="MODEL_OUTPUT_INVALID"):
        model.select_tool("rules", {"question": "original"})


def test_manual_tool_roundtrip_plain_answer_has_no_tools():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=response(
                [
                    {
                        "id": "msg",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "원문에 대한 자유 설명", "annotations": []}
                        ],
                    }
                ]
            ),
        )

    model = ModelClient(Settings(api_key="test"), httpx.Client(transport=httpx.MockTransport(handler)))
    context = {
        "input": {"question": "평균 에너지와 이온 에너지가 달라?"},
        "responseItems": [call("generate_answer")],
        "call_id": "call_test",
        "output": {"kind": "general"},
    }
    answer, _ = model.answer(
        "answer rules", {"originalQuestion": context["input"]["question"]}, tool_context=context
    )
    assert answer == "원문에 대한 자유 설명"
    body = captured[0]
    assert "tools" not in body and "previous_response_id" not in body
    assert body["input"][-1]["type"] == "function_call_output"
    assert body["input"][-1]["call_id"] == "call_test"
