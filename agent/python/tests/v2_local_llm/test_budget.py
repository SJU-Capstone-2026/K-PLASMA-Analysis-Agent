import pytest

from kplasma_agent.v2_local_llm.core import budget
from kplasma_agent.v2_local_llm.core.budget import check_payload
from kplasma_agent.v2_local_llm.config import Settings


def counted(names, counts):
    return {"schema_version": 1, "group_counts": counts,
            "group_question_ids": [[name] for name in sorted(names)], "group_size": 1,
            "independent_batch_size": 1, "policy": "sorted-greedy-full-pack-v1",
            "input_limit": 16000, "truncated": False}


@pytest.mark.parametrize("role", ["plan", "answer"])
def test_qwen_requires_an_explicit_native_counter(role):
    with pytest.raises(ValueError, match="^LOCAL_TOKEN_COUNTER_UNAVAILABLE$"):
        budget.make_input_guard(Settings())({"instructions": "인공", "input": "원문 유지"}, role)


def test_plan_review_uses_the_same_context_override_as_planning(monkeypatch):
    monkeypatch.setenv("AGENT_V2_LOCAL_LLM_PLAN_CONTEXT_TOKENS", "6500")
    with pytest.raises(ValueError, match="input budget exceeded"):
        check_payload({"question": "whole original", "plan": {}}, "plan_review", count=lambda _: [])


def test_full_review_is_rejected_without_truncating_original_input():
    payload = {"question": "original", "plan": {"steps": ["large step"]}}
    with pytest.raises(ValueError, match="input budget exceeded"):
        check_payload(payload, "plan_review", count=lambda _: range(24000))
    assert payload["question"] == "original" and payload["plan"]["steps"] == ["large step"]


def test_runtime_guard_has_a_settings_bound_factory():
    assert callable(getattr(budget, "make_input_guard", None))


def test_runtime_path_never_uses_the_cloud_encoding_or_a_json_size_fallback(monkeypatch):
    import tiktoken

    monkeypatch.setattr(tiktoken, "get_encoding", lambda _: pytest.fail("cloud tokenizer must not load"))
    with pytest.raises(ValueError, match="LOCAL_TOKEN_COUNTER_REQUIRED"):
        check_payload({"question": "인공 입력"}, "plan")


@pytest.mark.parametrize("role", ["plan", "answer"])
@pytest.mark.parametrize("context_tokens", [22000, 24576])
def test_qwen_uses_its_rendered_count_and_reserves_six_thousand_output_tokens(role, context_tokens):
    captured = []
    payload = {"instructions": "지시", "input": {"question": "m⁻²s⁻¹"}, "schema": {"type": "object"}}

    def qwen_count(value, selected_role):
        captured.append((value, selected_role))
        return 16000

    settings = Settings(context_tokens=context_tokens)
    budget.make_input_guard(settings, qwen_count=qwen_count)(payload, role)
    assert captured == [(payload, role)]
    with pytest.raises(ValueError, match="input budget exceeded"):
        budget.make_input_guard(Settings(context_tokens=21999), qwen_count=qwen_count)(payload, role)
    assert payload["input"]["question"] == "m⁻²s⁻¹"


@pytest.mark.parametrize("role", ["plan_review", "review"])
def test_d1_role_never_falls_back_to_qwen_or_raw_json(role):
    guard = budget.make_input_guard(Settings(), qwen_count=lambda *_: pytest.fail("Qwen counter used for d1"))
    with pytest.raises(ValueError, match="LOCAL_D1_TOKEN_COUNTER_UNAVAILABLE"):
        guard({"input": {"state": "원문"}, "questions": {"check": {"criteria": ["same", "changed"]}}}, role)


def test_every_native_d1_question_must_fit_its_full_context():
    fields = {"d1_context_tokens": 15999, "d1_batch_tokens": 16000, "d1_ubatch_tokens": 16000}
    payload = {"input": {"question": "원문 그대로"}, "questions": [{"name": "one"}, {"name": "two"}]}
    with pytest.raises(ValueError, match="input budget exceeded"):
        budget.make_input_guard(Settings(**fields), d1_count=lambda *_: counted(
            ["one", "two"], [200, 16000]))(payload, "plan_review")
    assert payload["input"]["question"] == "원문 그대로"


def test_d1_provider_covers_each_question_and_uses_d1_limits_not_qwen_limits():
    settings = Settings(context_tokens=6500, d1_context_tokens=30000,
                        d1_batch_tokens=16000, d1_ubatch_tokens=16000)
    payload = {"input": {"question": "인공 질문"}, "questions": [{"name": "a"}, {"name": "b"}]}
    budget.make_input_guard(settings, d1_count=lambda *_: counted(["a", "b"], [16000, 16000]))(payload, "review")
    with pytest.raises(ValueError, match="LOCAL_TOKEN_COUNT_INVALID"):
        budget.make_input_guard(settings, d1_count=lambda *_: counted(["a"], [10]))(payload, "review")


@pytest.mark.parametrize("value", [0, -1, True, 1.5, float("nan")])
def test_native_counter_results_must_be_positive_integer_token_counts(value):
    with pytest.raises(ValueError, match="LOCAL_TOKEN_COUNT_INVALID"):
        budget.make_input_guard(Settings(), qwen_count=lambda *_: value)({"input": "x"}, "plan")


@pytest.mark.parametrize("role", ["plan", "answer", "plan_review", "review"])
def test_24gb_profile_rejects_inputs_above_16k_without_truncation(role):
    payload = {"input": {"question": "complete original"}, "questions": [{"name": "one"}]}
    guard = budget.make_input_guard(Settings(d1_batch_tokens=32768, d1_ubatch_tokens=32768),
        qwen_count=lambda *_: 16001, d1_count=lambda *_: counted(["one"], [16001]))
    with pytest.raises(ValueError, match="input budget exceeded"):
        guard(payload, role)
    assert payload["input"]["question"] == "complete original"


@pytest.mark.parametrize("counter", [lambda *_: None, lambda *_: 1.5])
def test_invalid_native_count_provider_results_fail_closed(counter):
    with pytest.raises(ValueError, match="LOCAL_TOKEN_COUNT_INVALID"):
        budget.make_input_guard(Settings(), d1_count=counter)({"input": {}, "questions": {"a": {}}}, "review")


def test_native_count_provider_failure_does_not_expose_its_input_or_error_body():
    def failing(*_):
        raise RuntimeError("private original input MUST_NOT_APPEAR")

    for role, counters in [("plan", {"qwen_count": failing}), ("review", {"d1_count": failing})]:
        with pytest.raises(ValueError, match="LOCAL_TOKEN_COUNTER_UNAVAILABLE") as error:
            budget.make_input_guard(Settings(), **counters)({"input": {}, "questions": {"a": {}}}, role)
        assert "MUST_NOT_APPEAR" not in str(error.value)
