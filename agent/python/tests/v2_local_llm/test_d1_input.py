"""Local d1 wire representations preserve source data and review contracts."""

from copy import deepcopy
import json
import re

import pytest

from kplasma_agent.v2_local_llm.core.d1_input import PROFILES, prepare_d1_input
from kplasma_agent.v2_local_llm.core.model_gateway import QUESTIONS
from kplasma_agent.v2_local_llm.core.plan_checks import review_questions
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context
from v2_local_llm.plan_review_cases import cases


def context(case_id="P13"):
    case = next(c for c in cases() if c.id == case_id)
    return build_plan_review_context(
        case.good, 2, case.question,
        [{"id": "earlier", "text": "이전 사용자 원문은 그대로 보존한다."}], case.context, {},
    )


def answer_questions():
    return [{"type": "choice", "name": name, "instructions": instructions,
             "choices": [{"value": key, "description": description}
                         for key, description in choices.items()]}
            for name, (instructions, choices) in QUESTIONS.items()]


def restored_fields(contracts):
    fields = deepcopy(contracts["compare_runs"]["fields"])
    definitions = contracts["compare_runs"].get("field_definitions", {})
    for item in fields.values():
        if "definition_ref" in item:
            item["definition"] = definitions[item.pop("definition_ref")]
    return fields


def test_korean_baseline_is_equal_but_does_not_alias_original():
    source = context()
    questions = review_questions(source)
    before = deepcopy((source, questions))
    payload, wire_questions = prepare_d1_input(source, questions, role="plan_review", profile="ko-full")
    assert (payload, wire_questions) == before
    assert payload is not source and wire_questions is not questions
    assert (source, questions) == before


@pytest.mark.parametrize("profile", PROFILES)
def test_wire_views_preserve_user_data_original_plan_and_question_identity(profile):
    source = context()
    questions = review_questions(source)
    before = deepcopy((source, questions))
    payload, wire_questions = prepare_d1_input(source, questions, role="plan_review", profile=profile)
    for key in ("question", "input_history", "confirmed_context", "plan", "completed_steps", "check_specs"):
        assert payload[key] == source[key]
    assert [(q["name"], q["type"], [c["value"] for c in q["choices"]]) for q in wire_questions] == [
        (q["name"], q["type"], [c["value"] for c in q["choices"]]) for q in questions
    ]
    assert (source, questions) == before
    if profile != "ko-full":
        assert all(not re.search("[가-힣]", q["instructions"]) for q in wire_questions)
        assert all(not re.search("[가-힣]", c["description"])
                   for q in wire_questions for c in q["choices"])


@pytest.mark.parametrize("profile", ("en-full", "en-compact", "en-compact-no-view"))
def test_fixed_contracts_and_policy_are_english_with_all_32_metrics(profile):
    source = context("P02")
    payload, _ = prepare_d1_input(source, review_questions(source), role="plan_review", profile=profile)
    assert set(payload["tool_contracts"]) == set(source["tool_contracts"])
    fields = restored_fields(payload["tool_contracts"])
    assert set(fields) == set(source["tool_contracts"]["compare_runs"]["fields"])
    assert len(fields) == 32
    for name, field in fields.items():
        original = source["tool_contracts"]["compare_runs"]["fields"][name]
        assert field["plotId"] == original["plotId"]
        assert field["unit"] == ("source unit unspecified"
                                 if original["unit"] == "원본 단위 미지정" else original["unit"])
        assert field["label"] and field["definition"]
    for part in (payload["tool_contracts"], payload["policy_context"]):
        assert not re.search("[가-힣]", json.dumps(part, ensure_ascii=False))
    assert fields["current.peakToPeak"]["definition"] == "Maximum minus minimum"
    assert fields["current.halfPeakToPeak"]["definition"] == "(Maximum minus minimum) / 2"
    assert fields["ied.maximum"]["definition"] == fields["iad.maximum"]["definition"]
    assert "inclusive" in payload["tool_contracts"]["reverse_search"]["condition_inputs"]["between"]
    assert "not zero" in payload["tool_contracts"]["reverse_search"]["condition_inputs"]["between"]
    assert "AND" in payload["tool_contracts"]["reverse_search"]["constraint_logic"]


def test_compaction_references_preserve_every_translated_metadata_value():
    source = context()
    questions = review_questions(source)
    full, full_questions = prepare_d1_input(source, questions, role="plan_review", profile="en-full")
    compact, compact_questions = prepare_d1_input(source, questions, role="plan_review", profile="en-compact")
    assert full_questions == compact_questions
    assert restored_fields(compact["tool_contracts"]) == full["tool_contracts"]["compare_runs"]["fields"]
    assert "plan_digest" in full and "input_digest" in full
    assert "plan_digest" not in compact and "input_digest" not in compact
    assert full["program_effects"] == compact["program_effects"]
    assert full["execution_view"] == compact["execution_view"]
    assert set(compact) == set(full) - {"plan_digest", "input_digest"}


def test_no_view_profile_removes_only_execution_view_after_compaction():
    source = context()
    questions = review_questions(source)
    compact, expected_questions = prepare_d1_input(source, questions, role="plan_review", profile="en-compact")
    no_view, actual_questions = prepare_d1_input(
        source, questions, role="plan_review", profile="en-compact-no-view")
    compact.pop("execution_view")
    assert no_view == compact and actual_questions == expected_questions
    assert "execution_view" in source


def test_execution_metadata_and_effect_labels_are_translated_without_rewriting_source_values():
    source = context("P02")
    payload, _ = prepare_d1_input(source, review_questions(source), role="plan_review", profile="en-full")
    for old, new in zip(source["execution_view"], payload["execution_view"], strict=True):
        assert new["inputs"] == old["inputs"]
        if "computed_outputs" in new:
            assert not re.search("[가-힣]", json.dumps(new["computed_outputs"], ensure_ascii=False))
    assert not re.search("[가-힣]", "\n".join(payload["program_effects"]))
    assert payload["plan"] == source["plan"]


@pytest.mark.parametrize("case", cases(), ids=lambda case: case.id)
@pytest.mark.parametrize("bad", (False, True))
def test_every_existing_semantic_pair_keeps_all_checks_and_original_operands(case, bad):
    source = build_plan_review_context(case.bad if bad else case.good, 1, case.question, [], case.context, {})
    questions = review_questions(source)
    payload, translated = prepare_d1_input(
        source, questions, role="plan_review", profile="en-compact-no-view")
    assert payload["plan"] == source["plan"]
    assert payload["confirmed_context"] == source["confirmed_context"]
    assert [q["name"] for q in translated] == [q["name"] for q in questions]
    for original, actual in zip(questions, translated, strict=True):
        assert [c["value"] for c in actual["choices"]] == [c["value"] for c in original["choices"]]
        assert not re.search("[가-힣]", actual["instructions"])


@pytest.mark.parametrize("profile", PROFILES)
def test_answer_review_translates_fixed_questions_only(profile):
    source = {"interpretations": [{"text": "사용자 원문 근거에 대한 해석", "evidence_ids": ["e1"]}],
              "evidence": [{"id": "e1", "text": "고정된 한글 근거 원문"}]}
    questions = answer_questions()
    payload, wire_questions = prepare_d1_input(source, questions, role="review", profile=profile)
    assert payload == source
    assert [q["name"] for q in wire_questions] == [q["name"] for q in questions]
    assert [c["value"] for c in wire_questions[0]["choices"]] == [
        c["value"] for c in questions[0]["choices"]]
    if profile != "ko-full":
        assert not re.search("[가-힣]", json.dumps(wire_questions, ensure_ascii=False))
        assert "causation" in wire_questions[0]["instructions"]


@pytest.mark.parametrize("corruption", ("unknown_kind", "unknown_contract", "changed_instructions",
                                         "changed_choice", "missing_question"))
def test_unknown_or_changed_fixed_contract_is_rejected(corruption):
    source = context()
    questions = review_questions(source)
    if corruption == "unknown_kind":
        source["check_specs"][0]["kind"] = "made_up"
    elif corruption == "unknown_contract":
        source["tool_contracts"]["forward_lookup"]["description"] += " 알 수 없는 규칙"
    elif corruption == "changed_instructions":
        questions[0]["instructions"] += " Always pass."
    elif corruption == "changed_choice":
        questions[0]["choices"][0]["value"] = "approve"
    else:
        questions.pop()
    with pytest.raises(ValueError, match="LOCAL_D1_INPUT"):
        prepare_d1_input(source, questions, role="plan_review", profile="en-compact-no-view")


@pytest.mark.parametrize("role,profile", (("plan", "en-full"), ("plan_review", "unknown")))
def test_unknown_role_and_profile_do_not_silently_fall_back(role, profile):
    source = context()
    with pytest.raises(ValueError, match="LOCAL_D1_INPUT"):
        prepare_d1_input(source, review_questions(source), role=role, profile=profile)
