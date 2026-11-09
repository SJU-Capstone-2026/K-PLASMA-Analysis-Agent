import json
import httpx
import pytest

from kplasma_agent.config import Settings
from kplasma_agent.metric_registry import UNITS, normalize_value
from kplasma_agent.v2.model_gateway import (
    V2ModelGateway, V2Settings, _plan_defaults, review_answer, submit_plan_tool_schema,
)


def test_planner_must_decide_whether_the_user_requested_interpretation():
    schema = submit_plan_tool_schema()["parameters"]
    assert "interpretation_requested" in schema["required"]
    assert schema["properties"]["interpretation_requested"] == {"type": "boolean"}


def test_planner_literal_units_are_closed_choices_and_preserve_scale():
    unit = submit_plan_tool_schema()["parameters"]["$defs"]["LiteralInput"]["properties"]["unit"]
    assert set(unit["enum"]) == {*UNITS.values(), "Torr", "m⁻²s⁻¹", "unsupported", None}
    assert "mtorr}},{" not in unit["enum"]
    assert normalize_value("pressure", 0.008, "Torr") == 8
    assert normalize_value("ionFlux", 50e18, "m⁻²s⁻¹") == 50


def test_planner_schema_requires_the_bound_for_each_operator():
    scalar, interval = submit_plan_tool_schema()["parameters"]["$defs"]["ConstraintInput"]["anyOf"]
    for variant, operators, bounds in (
        (scalar, {"eq", "lt", "lte", "gt", "gte"}, {"value"}),
        (interval, {"between"}, {"min", "max"}),
    ):
        properties = variant["properties"]
        assert set(properties["operator"]["enum"]) == operators
        assert set(variant["required"]) == set(properties)
        for key in {"value", "min", "max"}:
            if key in bounds:
                assert all("$ref" in item for item in properties[key]["anyOf"])
            else:
                assert properties[key] == {"type": "null"}


def test_between_drops_only_a_repeated_bound():
    low = {"kind": "literal", "value": 150, "unit": "eV"}
    high = {**low, "value": 160}
    constraint = {"operator": "between", "min": low, "max": high, "value": low}
    assert _plan_defaults(constraint)["value"] is None
    contradictory = {**constraint, "value": {**low, "value": 155}}
    assert _plan_defaults(contradictory)["value"] == contradictory["value"]
    missing = {**constraint, "max": None}
    assert _plan_defaults(missing)["value"] == low


def test_v2_models_default_to_gpt6_without_changing_v1_settings(monkeypatch):
    for name in ("AGENT_V2_PLAN_MODEL", "AGENT_V2_PLAN_REASONING_EFFORT", "AGENT_V2_ANSWER_MODEL",
                 "AGENT_V2_ANSWER_REASONING_EFFORT", "AGENT_V2_DECISIONS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    base = Settings(model="gpt-5.6-luna", reasoning_effort="none")
    settings = V2Settings.from_env(base)
    assert (settings.planner.model, settings.planner.reasoning_effort) == ("gpt-6-luna", "low")
    assert settings.planner.model == settings.writer.model == settings.decisions_model == "gpt-6-luna"
    assert settings.writer.reasoning_effort == "none"
    assert base.model == "gpt-5.6-luna"


def test_decisions_sends_only_the_interpretation_question_and_uses_choice():
    requests = []
    payload = {"interpretations": [{"text": "압력이 플럭스 차이의 유일한 원인입니다."}], "evidence": []}

    def transport(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.url.path == "/v1/decisions"
        assert body["input"][0]["content"][0]["data"] == payload
        assert [question["name"] for question in body["questions"]] == ["interpretation_scope"]
        answers = []
        for question in body["questions"]:
            choice = "overclaim" if question["name"] == "interpretation_scope" else question["choices"][0]["value"]
            answers.append({"type": "choice", "name": question["name"], "choice": choice,
                            "probabilities": [{"value": c["value"], "probability": 0.05 if c["value"] == choice
                                               else 0.95 / (len(question["choices"]) - 1)}
                                              for c in question["choices"]], "confidence": 0.05})
        return httpx.Response(200, json={"answers": answers})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        settings = V2Settings.from_env(Settings())
        outcome, _ = review_answer(client, settings, payload)
    assert len(requests) == 1
    assert outcome.status == "ISSUE"
    assert outcome.answers[-1].choice == "overclaim"


def test_writer_schema_puts_complete_evidence_before_text():
    from kplasma_agent.model_client import strict_schema
    from kplasma_agent.v2.contracts import DataAnswerDraft

    schema = strict_schema(DataAnswerDraft)
    for name in ("Interpretation", "Limitation"):
        fields = list(schema["$defs"][name]["properties"])
        assert fields.index("evidence_ids") < fields.index("text")


def test_plan_review_has_condition_questions_in_one_request_and_preserves_low_confidence_choice():
    from .test_plan_review import answers, example_context

    guarded = []
    payload = example_context()

    def transport(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/decisions"
        assert body["input"][0]["content"][0]["data"] == payload
        assert [q["name"] for q in body["questions"]] == [s["name"] for s in payload["check_specs"]]
        assert all({"match", "unclear"} <= {c["value"] for c in q["choices"]} for q in body["questions"])
        rows = answers()
        rows[1] = answers("missing")[1]
        return httpx.Response(200, json={"answers": rows, "usage": {"input_tokens": 100}})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        gateway = V2ModelGateway(V2Settings.from_env(Settings()), client,
                                 lambda body, role: guarded.append((body, role)))
        result, usage = gateway.review_plan(payload)
    assert result["status"] == "ISSUE"
    assert result["checks"][1]["choice"] == "missing"
    assert result["checks"][1]["confidence"] == 0.05
    assert usage == {"input_tokens": 100}
    assert len(guarded) == 1 and guarded[0][1] == "plan_review"


@pytest.mark.parametrize("failure,reason", [
    ("timeout", "DECISIONS_TIMEOUT"), ("connection", "DECISIONS_CONNECTION"),
    (429, "DECISIONS_HTTP_429"), (401, "DECISIONS_HTTP_401"),
    (500, "DECISIONS_HTTP_500"), ("missing", "DECISIONS_INVALID_RESPONSE"),
])
@pytest.mark.parametrize("kind", ["plan", "answer"])
def test_decisions_outage_is_classified_and_never_retries(failure, reason, kind):
    from .test_plan_review import example_context

    calls = []

    def transport(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private message", request=request)
        if failure == "connection":
            raise httpx.ConnectError("private message", request=request)
        return httpx.Response(failure if isinstance(failure, int) else 200, json={"answers": []})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        gateway = V2ModelGateway(V2Settings.from_env(Settings()), client, lambda *_: None)
        result, usage = (gateway.review_plan(example_context()) if kind == "plan"
                         else gateway.review({"interpretations": [], "evidence": []}))
    assert len(calls) == 1
    assert result["status"] == "UNAVAILABLE" and result["reason"] == reason
    assert usage is None
    assert "private message" not in json.dumps(result)


def test_plan_review_defaults_to_enabled_and_can_be_explicitly_disabled(monkeypatch):
    monkeypatch.delenv("AGENT_V2_PLAN_REVIEW_ENABLED", raising=False)
    assert V2Settings.from_env(Settings()).plan_review_enabled is True
    monkeypatch.setenv("AGENT_V2_PLAN_REVIEW_ENABLED", "true")
    assert V2Settings.from_env(Settings()).plan_review_enabled is True
    monkeypatch.setenv("AGENT_V2_PLAN_REVIEW_ENABLED", "false")
    assert V2Settings.from_env(Settings()).plan_review_enabled is False


def test_oversized_plan_review_never_reaches_the_provider():
    from kplasma_agent.model_client import ModelError
    from .test_plan_review import example_context

    def reject(*_):
        raise ValueError("v2 input budget exceeded")

    def transport(_):
        raise AssertionError("invalid review input reached provider")

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        gateway = V2ModelGateway(V2Settings.from_env(Settings()), client, reject)
        with pytest.raises(ModelError, match="PLAN_REVIEW_INPUT_INVALID"):
            gateway.review_plan(example_context())


def test_gateway_streams_safe_prose_before_provider_completion_with_one_writer_request():
    from kplasma_agent.model_client import ModelClient
    from kplasma_agent.v2.composition import assemble_answer
    from kplasma_agent.v2.contracts import Evidence

    observed, requests, guards = [], [], []
    draft = {"fact_ids": ["compare:O12"], "interpretations": [{"id": "private-I1",
              "evidence_ids": ["compare:O12"], "text": "차이는 {{value:compare:O12}}입니다.",
              "assumptions": ["동일한 조건입니다."]}], "limitations": []}
    raw = json.dumps(draft, ensure_ascii=False)
    response = {"id": "synthetic", "object": "response", "created_at": 0, "status": "in_progress",
                "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
                "model": "gpt-5.6-luna", "output": []}
    message = {"type": "message", "id": "message", "role": "assistant", "status": "in_progress",
               "content": []}
    part = {"type": "output_text", "text": "", "annotations": []}

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            events = [
                {"type": "response.created", "response": response},
                {"type": "response.output_item.added", "output_index": 0, "item": message},
                {"type": "response.content_part.added", "output_index": 0, "content_index": 0,
                 "item_id": "message", "part": part},
                {"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                 "item_id": "message", "delta": raw, "logprobs": []},
            ]
            for sequence, event in enumerate(events):
                yield encode(event, sequence)
            assert observed == [("interpretations.0.text", "차이는 12 V입니다."),
                                ("interpretations.0.assumptions.0", "동일한 조건입니다.")]
            yield encode({"type": "response.completed", "response": {
                **response, "status": "completed", "output": [
                    {**message, "status": "completed", "content": [{**part, "text": raw}]}]}}, 4)

    def encode(event, sequence):
        return ("data: " + json.dumps({**event, "sequence_number": sequence}) + "\n\n").encode()

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["stream"] is True
        assert "numeric_values" not in json.loads(body["input"])
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Body())

    settings = V2Settings.from_env(Settings(api_key="test"))
    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        gateway = V2ModelGateway(settings, http_client, lambda payload, role: guards.append(role))
        gateway.writer = ModelClient(settings.writer, http_client=http_client)
        evidence = Evidence(id="compare:O12", executionId="compare", field="observation",
                            value="검증된 값", unit=None)
        context = {"mode": "data_request", "evidence": [evidence.model_dump(mode="json")]}
        values = {"compare:O12": {"value": "12 V"}}
        final, _ = gateway.stream_compose(context, on_block=lambda block, text: observed.append((block, text)),
                                          numeric_values=values)
        rendered, saved = assemble_answer(final, "data_request", [evidence], numeric_values=values)
    assert len(requests) == 1
    assert guards == ["answer"]
    assert rendered.endswith("차이는 12 V입니다.\n\n동일한 조건입니다.")
    assert saved["interpretations"][0]["text"] == observed[0][1]


@pytest.mark.parametrize("failure,code", [("timeout", "MODEL_TIMEOUT"), (429, "MODEL_RATE_LIMITED"),
                                        (503, "MODEL_HTTP_503"), ("failed", "MODEL_RESPONSE_FAILED"),
                                        ("incomplete", "MODEL_RESPONSE_INCOMPLETE"),
                                        ("max_output_tokens", "MODEL_OUTPUT_TRUNCATED"),
                                        ("content_filter", "MODEL_CONTENT_FILTERED")])
def test_model_failure_code_is_preserved_in_the_existing_outcome_error(failure, code):
    from evals.v2_harness import EvaluationJournal
    from kplasma_agent.graphs.v2 import build_v2_graph
    from kplasma_agent.model_client import ModelClient

    requests = []

    def transport(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-provider-body", request=request)
        if isinstance(failure, str):
            return httpx.Response(200, json={
                "id": "synthetic", "object": "response", "created_at": 0,
                "status": "failed" if failure == "failed" else "incomplete", "model": "gpt-6-luna",
                "output": [], "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
                "incomplete_details": {"reason": failure} if failure in ("max_output_tokens", "content_filter") else None,
                "error": {"code": "server_error", "message": "private-provider-body"} if failure == "failed" else None,
            })
        return httpx.Response(failure, json={"error": {"message": "private-provider-body"}})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        settings = V2Settings.from_env(Settings(api_key="private-api-key"))
        gateway = V2ModelGateway(settings, client, lambda *_: None)
        gateway.planner = ModelClient(settings.planner, http_client=client)
        journal = EvaluationJournal([])
        state = build_v2_graph(gateway, journal, None).invoke({"request_id": "synthetic", "question": "조회",
                    "context": {}, "input_history": []}, {"recursion_limit": 80})
    attempt, = journal.models.values()
    assert attempt["outcome"] == {"data": None, "usage": None, "error": code}
    assert len(requests) == 1 and not journal.steps
    assert state.get("replans", 0) == 0
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "FAILED"
    assert "private" not in json.dumps(attempt["outcome"])
