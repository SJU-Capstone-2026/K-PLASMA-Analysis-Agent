import pytest

from kplasma_agent.v3.core.budget import check_payload


def test_plan_review_uses_the_same_context_override_as_planning(monkeypatch):
    monkeypatch.setenv("AGENT_V3_PLAN_CONTEXT_TOKENS", "6500")
    with pytest.raises(ValueError, match="input budget exceeded"):
        check_payload({"question": "whole original", "plan": {}}, "plan_review", count=lambda _: [])


def test_full_review_is_rejected_without_truncating_original_input():
    payload = {"question": "original", "plan": {"steps": ["large step"]}}
    with pytest.raises(ValueError, match="input budget exceeded"):
        check_payload(payload, "plan_review", count=lambda _: range(24000))
    assert payload["question"] == "original" and payload["plan"]["steps"] == ["large step"]
