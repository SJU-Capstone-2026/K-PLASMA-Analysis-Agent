"""V1 graph streaming preserves its existing tool continuation and schema repair budget."""

from copy import deepcopy

from kplasma_agent.backend_client import RequestBackend
from kplasma_agent.config import Settings
from kplasma_agent.graphs.v1 import build_graph
from kplasma_agent.model_client import ModelError


class LocalClient:
    def __init__(self):
        self.events = []
        self.attempts = []
        self.revision = 0

    def call(self, method, path, **kwargs):
        assert method == "POST" and path.startswith("requests/synthetic/")
        body = deepcopy(kwargs["json"])
        assert body["claimGeneration"] == 1 and body["requestRevision"] == 1
        if path.endswith("/events"):
            payload = body["payload"]
            if body["type"] == "answer.start":
                self.revision += 1
                payload["answerRevision"] = self.revision
            event = {"seq": len(self.events) + 1, "kind": body["type"], "payload": payload}
            self.events.append(event)
            return deepcopy(event)
        if path.endswith("/attempt"):
            self.attempts.append(body["stage"])
            return {}
        assert path.endswith("/heartbeat")
        return {}


class StreamingModel:
    def __init__(self, client, *, invalid_first=False):
        self.client = client
        self.invalid_first = invalid_first
        self.selection_calls = 0
        self.writer_calls = 0

    def select_tool(self, instructions, payload):
        self.selection_calls += 1
        return {"name": "generate_answer", "arguments": {}, "call_id": "native-call"}, {
            "responseItems": [{"type": "function_call", "name": "generate_answer", "arguments": "{}",
                               "call_id": "native-call"}],
        }

    def answer(self, instructions, payload, **kwargs):
        raise AssertionError("the graph must call the existing writer's streaming entrypoint")

    def stream_answer(self, instructions, payload, *, on_text_delta, tool_context=None):
        self.writer_calls += 1
        assert tool_context["call_id"] == "native-call"
        assert tool_context["responseItems"][0]["type"] == "function_call"
        text = "잘못된 초안" if self.invalid_first and self.writer_calls == 1 else "IED는 이온 에너지 분포입니다."
        before = len(self.client.events)
        on_text_delta(text[:4])
        assert any(event["kind"] == "answer.delta" for event in self.client.events[before:])
        on_text_delta(text[4:])
        if self.invalid_first and self.writer_calls == 1:
            raise ModelError("MODEL_OUTPUT_INVALID")
        if self.invalid_first:
            assert payload["repair_error"].startswith("Invalid schema")
        return text, {"model": "synthetic"}


def execute(*, invalid_first=False):
    client = LocalClient()
    backend = RequestBackend(client, {"request": {"requestId": "synthetic", "graphVersion": "v1"},
                                      "claimGeneration": 1, "requestRevision": 1})
    model = StreamingModel(client, invalid_first=invalid_first)
    result = build_graph(model, backend, Settings(), None).invoke({
        "request_id": "synthetic", "question": "IED가 뭐야?", "context": {}, "input_history": [],
    })
    return result["answer"]["answerSnapshot"], model, client


def test_v1_public_text_arrives_before_the_existing_general_writer_returns():
    snapshot, model, client = execute()
    assert model.selection_calls == model.writer_calls == 1
    assert client.attempts == ["interpret", "explain"]
    deltas = [event["payload"] for event in client.events if event["kind"] == "answer.delta"]
    assert {row["blockId"] for row in deltas} == {"paragraphs.0"}
    assert {row["answerRevision"] for row in deltas} == {1}
    assert "".join(row["text"] for row in deltas) == snapshot["result"]["markdown"]
    assert snapshot["result"]["usedRunRefs"] == []


def test_v1_schema_repair_resets_the_failed_preview_and_streams_the_replacement():
    snapshot, model, client = execute(invalid_first=True)
    assert model.selection_calls == 1 and model.writer_calls == 2
    assert client.attempts == ["interpret", "explain", "explain"]
    resets = [event for event in client.events if event["kind"] == "answer.reset"]
    assert len(resets) == 1 and resets[0]["payload"]["reason"] == "WRITER_FAILED"
    starts = [event for event in client.events if event["kind"] == "answer.start"]
    assert [row["payload"]["answerRevision"] for row in starts] == [1, 2]
    assert starts[0]["seq"] < resets[0]["seq"] < starts[1]["seq"]
    replacement = "".join(event["payload"]["text"] for event in client.events
                          if event["kind"] == "answer.delta" and event["payload"]["answerRevision"] == 2)
    assert replacement == snapshot["result"]["markdown"]
    assert "잘못된 초안" not in replacement
