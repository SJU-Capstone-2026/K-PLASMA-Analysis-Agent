import json
import httpx
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
