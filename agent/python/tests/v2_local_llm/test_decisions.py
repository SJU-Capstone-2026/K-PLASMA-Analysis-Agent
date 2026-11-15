"""Artificial decision payloads; no model, experiment data, or network service."""

from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.core.model_gateway import (
    QUESTIONS, V2LocalLLMSettings, _decisions_response, review_answer, review_plan,
)
from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.plan_checks import review_questions
from kplasma_agent.v2_local_llm.network import local_http_client

from .test_plan_review import example_context


URL = "http://127.0.0.1:8083/v1/systemone"
PAYLOAD = {"interpretations": [{"text": "압력만이 플럭스 차이의 원인입니다."}], "evidence": []}


def settings(profile=None):
    base = Settings(d1_token="synthetic-d1-token", d1_url=URL)
    return V2LocalLLMSettings.from_env(replace(base, d1_input_profile=profile) if profile else base)


def response_body(questions=None, choice="overclaim"):
    questions = questions or {name: {"criteria": choices} for name, (_, choices) in QUESTIONS.items()}
    return {"answers": {name: {"type": "choice", "choice": choice,
        "probabilities": {label: 1 / len(question["criteria"]) for label in question["criteria"]},
        "confidence": 0.05} for name, question in questions.items()}}


def call_answer(body, *, raw=False):
    with local_http_client(URL, timeout=1, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=body) if raw else httpx.Response(200, json=body)
    )) as client:
        return review_answer(client, settings(), deepcopy(PAYLOAD))


@pytest.mark.parametrize("profile", ["ko-full", "en-compact-no-view"])
def test_native_payload_preserves_original_evidence_question_meaning_and_provider_choice(profile):
    original = deepcopy(PAYLOAD)
    requests = []
    usage = {"input_tokens": 57, "output_tokens": 0}

    def transport(request):
        requests.append(request)
        assert str(request.url) == URL
        assert request.headers["authorization"] == "Bearer synthetic-d1-token"
        body = json.loads(request.content)
        assert set(body) == {"state", "questions"}
        assert isinstance(body["state"], str) and json.loads(body["state"]) == original
        assert list(body["questions"]) == list(QUESTIONS)
        for name, (instructions, choices) in QUESTIONS.items():
            question = body["questions"][name]
            assert question["type"] == "choice" and list(question["criteria"]) == list(choices)
            if profile == "ko-full":
                assert question == {"type": "choice", "instructions": instructions, "criteria": choices}
            else:
                assert not any("가" <= char <= "힣" for char in json.dumps(question, ensure_ascii=False))
        result = response_body(body["questions"])
        result["answers"]["interpretation_scope"]["probabilities"] = {
            "within_evidence": 0.9, "overclaim": 0.05, "unassessable": 0.05}
        result["usage"] = usage
        return httpx.Response(200, json=result)

    with local_http_client(URL, timeout=1, headers={"Authorization": "Bearer synthetic-d1-token"},
                           transport=httpx.MockTransport(transport)) as client:
        outcome, returned_usage = review_answer(client, settings(profile), PAYLOAD)
    assert len(requests) == 1 and PAYLOAD == original
    assert outcome.status == "ISSUE" and outcome.answers[0].choice == "overclaim"
    assert outcome.answers[0].confidence == 0.05
    assert outcome.answers[0].probabilities == {"within_evidence": 0.9, "overclaim": 0.05, "unassessable": 0.05}
    assert returned_usage == usage


def test_missing_usage_and_confidence_stay_unavailable_instead_of_becoming_zero_or_one():
    body = response_body(choice="within_evidence")
    for row in body["answers"].values():
        row.pop("confidence")
    outcome, usage = call_answer(body)
    assert outcome.status == "PASS" and usage is None
    assert outcome.answers[0].confidence is None


@pytest.mark.parametrize("profile", ["ko-full", "en-compact-no-view"])
def test_dynamic_plan_questions_and_digests_survive_native_ordering(profile):
    payload = example_context()
    original = deepcopy(payload)
    questions = review_questions(payload)

    def transport(request):
        body = json.loads(request.content)
        state = json.loads(body["state"])
        if profile == "ko-full":
            assert state == payload
        else:
            assert not {"execution_view", "plan_digest", "input_digest"} & state.keys()
            for key in ("question", "input_history", "confirmed_context", "plan", "check_specs"):
                assert state[key] == payload[key]
        assert list(body["questions"]) == [question["name"] for question in questions]
        for question in questions:
            wire = body["questions"][question["name"]]
            assert wire["type"] == "choice"
            assert list(wire["criteria"]) == [item["value"] for item in question["choices"]]
            if profile == "ko-full":
                assert wire == {"type": "choice", "instructions": question["instructions"],
                                "criteria": {item["value"]: item["description"] for item in question["choices"]}}
            else:
                assert not any("가" <= char <= "힣" for char in json.dumps(wire, ensure_ascii=False))
        result = response_body(body["questions"], "match")
        result["answers"] = dict(reversed(list(result["answers"].items())))
        return httpx.Response(200, json=result)

    with local_http_client(URL, timeout=1, transport=httpx.MockTransport(transport)) as client:
        outcome, usage = review_plan(client, settings(profile), payload)
    assert outcome["status"] == "PASS" and usage is None
    assert [item["name"] for item in outcome["checks"]] == [question["name"] for question in questions]
    assert outcome["plan_digest"] == payload["plan_digest"]
    assert outcome["input_digest"] == payload["input_digest"] and payload == original


@pytest.mark.parametrize("kind", [
    "missing_answers", "array_answers", "missing_question", "unknown_question", "wrong_type", "unknown_choice",
    "missing_label", "extra_label", "nonunit_sum", "negative", "above_one", "nan", "infinity", "string", "boolean",
    "confidence_negative", "confidence_above_one", "confidence_nan", "confidence_boolean", "usage_array",
])
def test_malformed_native_decisions_are_unavailable(kind):
    body = response_body()
    row = body["answers"]["interpretation_scope"]
    if kind == "missing_answers":
        body.pop("answers")
    elif kind == "array_answers":
        body["answers"] = list(body["answers"].values())
    elif kind == "missing_question":
        body["answers"] = {}
    elif kind == "unknown_question":
        body["answers"]["unknown"] = deepcopy(row)
    elif kind == "wrong_type":
        row["type"] = "score"
    elif kind == "unknown_choice":
        row["choice"] = "unknown"
    elif kind == "missing_label":
        row["probabilities"].pop("overclaim")
    elif kind == "extra_label":
        row["probabilities"]["unknown"] = 0
    elif kind == "nonunit_sum":
        row["probabilities"] = {key: 0.1 for key in row["probabilities"]}
    elif kind == "usage_array":
        body["usage"] = []
    else:
        value = {"negative": -0.1, "above_one": 1.1, "nan": float("nan"), "infinity": float("inf"),
                 "string": "0.3", "boolean": True, "confidence_negative": -0.1,
                 "confidence_above_one": 1.1, "confidence_nan": float("nan"), "confidence_boolean": True}[kind]
        if kind.startswith("confidence_"):
            row["confidence"] = value
        else:
            row["probabilities"]["overclaim"] = value
    outcome, _ = call_answer(json.dumps(body).encode(), raw=True)
    assert outcome.status == "UNAVAILABLE" and outcome.reason == "DECISIONS_INVALID_RESPONSE"


@pytest.mark.parametrize("raw", [
    '{"answers":{},"answers":{}}',
    '{"answers":{"interpretation_scope":{},"interpretation_scope":{}}}',
    '{"answers":{"interpretation_scope":{"type":"choice","choice":"overclaim",'
    '"probabilities":{"overclaim":0.5,"overclaim":0.5}}}}',
    'not-json', '[]',
])
def test_duplicate_keys_and_nonobjects_cannot_become_valid_decisions(raw):
    outcome, _ = call_answer(raw.encode(), raw=True)
    assert outcome.status == "UNAVAILABLE" and outcome.reason == "DECISIONS_INVALID_RESPONSE"


@pytest.mark.parametrize("failure,reason", [
    ("http", "DECISIONS_HTTP_503"), ("timeout", "DECISIONS_TIMEOUT"), ("connection", "DECISIONS_CONNECTION"),
])
def test_transport_failures_preserve_existing_review_semantics(failure, reason):
    def transport(request):
        if failure == "http":
            return httpx.Response(503, text="synthetic unavailable")
        error = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        raise error("synthetic transport failure", request=request)
    with local_http_client(URL, timeout=1, transport=httpx.MockTransport(transport)) as client:
        outcome, _ = review_answer(client, settings(), PAYLOAD)
    assert outcome.status == "UNAVAILABLE" and outcome.reason == reason


@pytest.mark.parametrize("duplicate", ["question", "label"])
def test_duplicate_input_questions_or_labels_are_rejected_before_http(duplicate):
    question = {"name": "q", "type": "choice", "instructions": "synthetic",
                "choices": [{"value": "yes", "description": "yes"}, {"value": "no", "description": "no"}]}
    questions = [question, deepcopy(question)] if duplicate == "question" else [question]
    if duplicate == "label":
        question["choices"].append(deepcopy(question["choices"][0]))
    def transport(_):
        raise AssertionError("invalid payload reached HTTP")
    body = {"input": [{"role": "user", "content": [{"type": "input_json", "data": PAYLOAD}]}],
            "questions": questions}
    with local_http_client(URL, timeout=1, transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(ValueError):
            _decisions_response(client, settings(), body)
