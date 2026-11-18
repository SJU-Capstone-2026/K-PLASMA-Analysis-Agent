import json
from types import SimpleNamespace
import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.metric_registry import UNITS, normalize_value
from kplasma_agent.v2_local_llm.core.model_gateway import (
    V2LocalLLMModelGateway, V2LocalLLMSettings, _plan_defaults, review_answer, submit_plan_tool_schema,
)


def test_local_planner_budgets_the_unchanged_native_tool_and_plan_instructions():
    from evals.local_llm_smoke import smoke_plan

    def request(_instructions, _input, tool, _span):
        assert tool == submit_plan_tool_schema()
        return {"output": [{"type": "function_call", "name": "submit_plan", "call_id": "synthetic",
                            "arguments": json.dumps(smoke_plan())}]}, None

    guarded = []
    gateway = SimpleNamespace(planner=SimpleNamespace(_tool_request=request),
                              input_guard=lambda *args: guarded.append(args))
    plan, _ = V2LocalLLMModelGateway.submit_plan(gateway, {"question": "인공 단위 검증"})
    assert plan == smoke_plan()
    assert guarded[0][0]["tools"] == [submit_plan_tool_schema()]
    assert "schema" not in guarded[0][0] and guarded[0][1] == "plan"


def test_replanning_receives_actual_invalid_json_in_the_existing_failure_contract():
    from kplasma_agent.v2_local_llm.graph import _generation_failure
    from kplasma_agent.v2_local_llm.model_client import ModelError

    raw = '{"schema_version":2,"steps":['
    gateway = SimpleNamespace(planner=SimpleNamespace(_tool_request=lambda *_: ({"sourceProtocol": "chat.completions.tool_calls", "output": [
            {"type": "function_call", "name": "submit_plan", "call_id": "synthetic", "arguments": raw}]},
            {"outputTokens": 17})), input_guard=lambda *_: None)
    with pytest.raises(ModelError) as raised:
        V2LocalLLMModelGateway.submit_plan(gateway, {"question": "인공 단위 검증"})
    failure = _generation_failure({"error": raised.value.code, "response": raised.value.response,
                                   "usage": raised.value.usage})
    assert failure["partial_arguments_tail"] == raw
    assert failure["usage"] == {"outputTokens": 17}
    assert raised.value.response["sourceProtocol"] == "chat.completions.tool_calls"


def test_planner_selects_explanation_instead_of_an_interpretation_boolean():
    schema = submit_plan_tool_schema()["parameters"]
    assert "interpretation_requested" not in schema["properties"]
    assert schema["$defs"]["ExplainInputs"]["properties"]["mode"]["enum"] == ["concept", "results"]


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


def test_local_models_are_fixed_to_qwen_and_d1(monkeypatch):
    for name in ("AGENT_V2_LOCAL_LLM_PLAN_MODEL", "AGENT_V2_LOCAL_LLM_PLAN_REASONING_EFFORT", "AGENT_V2_LOCAL_LLM_ANSWER_MODEL",
                 "AGENT_V2_LOCAL_LLM_ANSWER_REASONING_EFFORT", "AGENT_V2_LOCAL_LLM_DECISIONS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    base = Settings()
    settings = V2LocalLLMSettings.from_env(base)
    assert (settings.planner.model, settings.planner.reasoning_effort) == ("unsloth/Qwen3.5-9B-GGUF:Q4_K_M", "medium")
    assert settings.planner.model == settings.writer.model
    assert settings.decisions_model == "LiquidAI/d1-2B-GGUF:Q8_0"
    assert settings.decisions_url == "http://127.0.0.1:8081/v1/systemone"


def test_decisions_sends_only_the_interpretation_question_and_uses_choice():
    requests = []
    payload = {"interpretations": [{"text": "압력이 플럭스 차이의 유일한 원인입니다."}], "evidence": []}

    def transport(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.url.path == "/v1/systemone"
        assert json.loads(body["state"]) == payload
        assert list(body["questions"]) == ["interpretation_scope"]
        answers = {}
        for name, question in body["questions"].items():
            choice = "overclaim"
            answers[name] = {"type": "choice", "choice": choice,
                             "probabilities": {label: 0.05 if label == choice else 0.95 / (len(question["criteria"]) - 1)
                                               for label in question["criteria"]}, "confidence": 0.05}
        return httpx.Response(200, json={"answers": answers})

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        settings = V2LocalLLMSettings.from_env(Settings())
        outcome, _ = review_answer(client, settings, payload)
    assert len(requests) == 1
    assert outcome.status == "ISSUE"
    assert outcome.answers[-1].choice == "overclaim"


def test_writer_schema_puts_complete_evidence_before_text():
    from kplasma_agent.v2_local_llm.model_client import strict_schema
    from kplasma_agent.v2_local_llm.core.contracts import DataAnswerDraft

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
        assert request.url.path == "/v1/systemone"
        assert json.loads(body["state"]) == payload
        assert list(body["questions"]) == [s["name"] for s in payload["check_specs"]]
        assert all({"match", "unclear"} <= set(q["criteria"]) for q in body["questions"].values())
        rows = answers()
        rows[1] = answers("missing")[1]
        native = {row["name"]: {"type": "choice", "choice": row["choice"], "confidence": row["confidence"],
                               "probabilities": {p["value"]: p["probability"] for p in row["probabilities"]}}
                  for row in rows}
        return httpx.Response(200, json={"answers": native, "usage": {"input_tokens": 100}})

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        gateway = V2LocalLLMModelGateway(V2LocalLLMSettings.from_env(Settings()), client,
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

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        gateway = V2LocalLLMModelGateway(V2LocalLLMSettings.from_env(Settings()), client, lambda *_: None)
        result, usage = (gateway.review_plan(example_context()) if kind == "plan"
                         else gateway.review({"interpretations": [], "evidence": []}))
    assert len(calls) == 1
    assert result["status"] == "UNAVAILABLE" and result["reason"] == reason
    assert usage is None
    assert "private message" not in json.dumps(result)


def test_local_plan_review_remains_enabled(monkeypatch):
    monkeypatch.delenv("AGENT_V2_LOCAL_LLM_PLAN_REVIEW_ENABLED", raising=False)
    assert V2LocalLLMSettings.from_env(Settings()).plan_review_enabled is True
    monkeypatch.setenv("AGENT_V2_LOCAL_LLM_PLAN_REVIEW_ENABLED", "true")
    assert V2LocalLLMSettings.from_env(Settings()).plan_review_enabled is True
    monkeypatch.setenv("AGENT_V2_LOCAL_LLM_PLAN_REVIEW_ENABLED", "false")
    assert V2LocalLLMSettings.from_env(Settings()).plan_review_enabled is True


def test_oversized_plan_review_never_reaches_the_provider():
    from kplasma_agent.v2_local_llm.model_client import ModelError
    from .test_plan_review import example_context

    def reject(*_):
        raise ValueError("v2 input budget exceeded")

    def transport(_):
        raise AssertionError("invalid review input reached provider")

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        gateway = V2LocalLLMModelGateway(V2LocalLLMSettings.from_env(Settings()), client, reject)
        with pytest.raises(ModelError, match="PLAN_REVIEW_INPUT_INVALID"):
            gateway.review_plan(example_context())


def test_gateway_streams_safe_prose_before_provider_completion_with_one_writer_request():
    from kplasma_agent.v2_local_llm.model_client import ModelClient
    from kplasma_agent.v2_local_llm.core.composition import assemble_answer
    from kplasma_agent.v2_local_llm.core.contracts import Evidence

    observed, requests, guards = [], [], []
    execution_id = "00000000-0000-0000-0000-000000000012"
    evidence_id = execution_id + ":O12"
    draft = {"fact_ids": [evidence_id], "interpretations": [{"id": "private-I1",
              "evidence_ids": [evidence_id], "text": "차이는 {{value:" + evidence_id + "|value}}입니다.",
              "assumptions": ["동일한 조건입니다."]}], "limitations": []}
    raw = json.dumps(draft, ensure_ascii=False)
    response = {"id": "synthetic", "object": "chat.completion.chunk", "created": 0,
                "model": "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"}

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            yield encode({**response, "choices": [{"index": 0, "delta": {"content": raw}, "finish_reason": None}]})
            assert observed == [("interpretations.0.text", "차이는 12 V입니다."),
                                ("interpretations.0.assumptions.0", "동일한 조건입니다.")]
            yield encode({**response, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            yield b"data: [DONE]\n\n"

    def encode(event):
        return ("data: " + json.dumps(event) + "\n\n").encode()

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["stream"] is True
        assert "numeric_values" not in json.loads(body["messages"][1]["content"])
        assert "{{value:" + evidence_id + "|value}}" in body["messages"][0]["content"]
        assert "{{value:compare:O7" not in body["messages"][0]["content"]
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Body())

    settings = V2LocalLLMSettings.from_env(Settings(api_key="test"))
    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as http_client:
        gateway = V2LocalLLMModelGateway(settings, http_client, lambda payload, role: guards.append(role))
        gateway.writer = ModelClient(settings.writer, http_client=http_client)
        evidence = Evidence(id=evidence_id, executionId=execution_id, field="observation",
                            value="검증된 값", unit=None)
        context = {"mode": "data_request", "evidence": [{**evidence.model_dump(mode="json"),
                                                          "value_parts": ["value"]}]}
        values = {evidence_id: {"value": "12 V"}}
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
    from .artificial_harness import EvaluationJournal
    from kplasma_agent.v2_local_llm.graph import build_v2_local_llm_graph
    from kplasma_agent.v2_local_llm.model_client import ModelClient

    requests = []

    def transport(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-provider-body", request=request)
        if isinstance(failure, str):
            return httpx.Response(200, json={
                "id": "synthetic", "object": "chat.completion", "created": 0,
                "model": "unsloth/Qwen3.5-9B-GGUF:Q4_K_M",
                "usage": {"prompt_tokens": 11, "completion_tokens": 6000, "total_tokens": 6011,
                          "completion_tokens_details": {"reasoning_tokens": 5900}} if failure == "max_output_tokens" else None,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": None,
                             "tool_calls": [{"type": "function", "id": "synthetic", "function": {
                                 "name": "submit_plan", "arguments": "PARTIAL MODEL OUTPUT"}}]},
                             "finish_reason": {"max_output_tokens": "length", "content_filter": "content_filter"}.get(failure)}],
                "error": {"code": "server_error", "message": "private-provider-body"} if failure == "failed" else None,
            })
        return httpx.Response(failure, json={"error": {"message": "private-provider-body"}})

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        settings = V2LocalLLMSettings.from_env(Settings(api_key="private-api-key"))
        gateway = V2LocalLLMModelGateway(settings, client, lambda *_: None)
        gateway.planner = ModelClient(settings.planner, http_client=client)
        journal = EvaluationJournal([])
        state = build_v2_local_llm_graph(gateway, journal, None).invoke({"request_id": "synthetic", "question": "조회",
                    "context": {}, "input_history": []}, {"recursion_limit": 80})
    attempts = list(journal.models.values())
    expected_calls = 3 if failure == "max_output_tokens" else 1
    assert len(attempts) == expected_calls
    attempt = attempts[-1]
    outcome = attempt["outcome"]
    assert outcome["data"] is None and outcome["error"] == code
    if failure == "max_output_tokens":
        assert outcome["usage"]["outputTokens"] == outcome["usage"]["maxOutputTokens"] == 6000
        assert outcome["usage"]["rawUsage"]["completion_tokens_details"]["reasoning_tokens"] == 5900
        assert outcome["response"]["output"][0]["arguments"] == "PARTIAL MODEL OUTPUT"
    elif outcome["usage"] is not None:
        assert outcome["usage"]["usageAvailable"] is False
        assert outcome["usage"]["inputTokens"] is outcome["usage"]["outputTokens"] is None
        assert outcome["response"]["status"] in {"failed", "incomplete"}
    else:
        assert "response" not in outcome
    assert len(requests) == expected_calls and not journal.steps
    assert state.get("replans", 0) == expected_calls - 1
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "FAILED"
    assert "private" not in json.dumps(attempt["outcome"])


def test_plan_cache_wraps_the_existing_guard_and_submission(tmp_path):
    from .test_prompt_cache import create
    from evals.local_llm_smoke import smoke_plan
    cache,native,_=create(tmp_path)
    payload={'question':'인공 캐시 계획'}
    guarded=[]
    def request(instructions,text,tool,span):
        assert json.loads(text)==payload
        return {'output':[{'type':'function_call','name':'submit_plan','call_id':'synthetic',
                           'arguments':json.dumps(smoke_plan())}]},{'inputTokens':10}
    gateway=SimpleNamespace(planner=SimpleNamespace(_tool_request=request),plan_cache=cache,
                            input_guard=lambda *args:guarded.append(args))
    plan,usage=V2LocalLLMModelGateway.submit_plan(gateway,payload)
    assert plan==smoke_plan() and usage['inputTokens']==10
    assert any(x[2]==b'action=save' for x in native.calls)
    assert len(guarded)==1 and guarded[0][1]=='plan'
    assert usage['planCache']['save']=='saved'


def test_overflow_never_restores_or_saves_a_plan_cache(tmp_path):
    from .test_prompt_cache import create
    cache,native,_=create(tmp_path)
    def reject(*_):raise ValueError('LOCAL_INPUT_TOO_LARGE')
    gateway=SimpleNamespace(plan_cache=cache,input_guard=reject)
    with pytest.raises(ValueError,match='LOCAL_INPUT_TOO_LARGE'):
        V2LocalLLMModelGateway.submit_plan(gateway,{'question':'인공 초과 입력'})
    assert not native.calls


def test_cached_replan_preserves_the_new_question_rejected_plan_and_feedback(tmp_path):
    from .test_prompt_cache import create
    from evals.local_llm_smoke import smoke_plan

    cache, native, _ = create(tmp_path)
    cache.prepare()
    assert cache.save() == "saved"
    native.slot = {"id": 0}
    payload = {
        "messages": {"question": "인공 변경: 소스 전력 150 W를 조회해줘."},
        "previous_plan": {"source_power": 100},
        "rejected_plan": {"source_power": 100},
        "validation_error": "인공 오류: 이전 질문의 100 W를 재사용했습니다.",
        "plan_review_feedback": {"status": "ISSUE", "required_source_power": 150},
    }
    seen = []

    def request(instructions, text, tool, span):
        seen.append(json.loads(text))
        assert cache.stats["restore"] == "disk"
        return {"output": [{"type": "function_call", "name": "submit_plan", "call_id": "synthetic",
                            "arguments": json.dumps(smoke_plan())}]}, {"inputTokens": 100}

    gateway = SimpleNamespace(planner=SimpleNamespace(_tool_request=request), plan_cache=cache,
                              input_guard=lambda body, role: seen.append(json.loads(body["input"])))
    V2LocalLLMModelGateway.submit_plan(gateway, payload)
    assert seen == [payload, payload]
