"""Local d1 wire representations preserve source data and review contracts."""

from copy import deepcopy
import json
import re

import pytest

from kplasma_agent.v2_local_llm.core.d1_input import PROFILES, prepare_d1_input
from kplasma_agent.v2_local_llm.core.d1_context import project_check
from kplasma_agent.v2_local_llm.core.decisions import native_request
from kplasma_agent.v2_local_llm.core.model_gateway import QUESTIONS
from kplasma_agent.v2_local_llm.core.plan_checks import review_questions
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context
from v2_local_llm.plan_review_cases import cases, interval, literal, plan, search


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


def without_citation_text(value):
    if isinstance(value, list):
        return [without_citation_text(item) for item in value]
    if isinstance(value, dict):
        ignored = {"text", "sources"} if "handled_by" in value else {"quote"}
        return {key: without_citation_text(item) for key, item in value.items() if key not in ignored}
    return value


def test_korean_view_preserves_instruction_language_and_source_snapshot():
    source = context()
    questions = review_questions(source)
    before = deepcopy((source, questions))
    payload, wire_questions = prepare_d1_input(source, questions, role="plan_review", profile="ko-full")
    assert source["question"] not in json.dumps(payload, ensure_ascii=False)
    assert payload["tool_contracts"] == source["tool_contracts"]
    assert [q["instructions"] for q in wire_questions] == [q["instructions"] for q in questions]
    assert payload is not source and wire_questions is not questions
    assert (source, questions) == before


@pytest.mark.parametrize("profile", PROFILES)
def test_wire_views_preserve_user_data_original_plan_and_question_identity(profile):
    source = context()
    questions = review_questions(source)
    before = deepcopy((source, questions))
    payload, wire_questions = prepare_d1_input(source, questions, role="plan_review", profile=profile)
    for key in ("input_history", "confirmed_context", "completed_steps", "check_specs"):
        assert payload[key] == source[key]
    assert without_citation_text(payload["plan"]) == without_citation_text(source["plan"])
    assert source["question"] not in json.dumps(payload, ensure_ascii=False)
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
        assert without_citation_text(new["inputs"]) == without_citation_text(old["inputs"])
        if "computed_outputs" in new:
            assert not re.search("[가-힣]", json.dumps(new["computed_outputs"], ensure_ascii=False))
    assert not re.search("[가-힣]", "\n".join(payload["program_effects"]))
    assert without_citation_text(payload["plan"]) == without_citation_text(source["plan"])


@pytest.mark.parametrize("case", cases(), ids=lambda case: case.id)
@pytest.mark.parametrize("bad", (False, True))
def test_every_existing_semantic_pair_keeps_all_checks_and_original_operands(case, bad):
    source = build_plan_review_context(case.bad if bad else case.good, 1, case.question, [], case.context, {})
    questions = review_questions(source)
    payload, translated = prepare_d1_input(
        source, questions, role="plan_review", profile="en-compact-no-view")
    assert without_citation_text(payload["plan"]) == without_citation_text(source["plan"])
    assert source["question"] not in json.dumps(payload, ensure_ascii=False)
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


def plan_wire(question, draft):
    source = build_plan_review_context(draft, 1, question, [], {}, {})
    view, questions = prepare_d1_input(
        source, review_questions(source), role="plan_review", profile="en-compact-no-view")
    return native_request({"input": [{"role": "user", "content": [{"type": "input_json", "data": view}]}],
                           "questions": questions})


def test_forward_filter_uses_its_own_original_citation_without_full_question():
    question = "압력 7 mTorr, 소스 전력 123 W, 바이어스 전력 456 W의 실제 Run을 조회해줘."
    draft = plan(question, [{"id": "s_forward", "kind": "tool", "tool": "forward_lookup",
                            "inputs": {"pressure": literal(7, "mTorr", question),
                                       "source_power": literal(125, "W", question),
                                       "bias_power": literal(456, "W", question)}}])
    wire = plan_wire(question, draft)
    name = "filter.s_forward.source_power"
    assert question not in wire["state"]
    state, _, trace = project_check(wire["state"], name, wire["questions"][name])
    assert trace["action"] == "selected"
    view = json.loads(state)
    assert set(view) == {"plan"}
    assert question not in state
    binding = view["plan"]["steps"][0]["inputs"]["source_power"]
    assert binding["value"] == 125
    assert binding["citation"]["quote"] == "소스 전력 123 W"
    assert draft.steps[0].inputs.source_power.source.quote == question


def test_reverse_ordering_citation_keeps_the_range_and_lookup_request():
    question = "평균 이온 에너지가 128 eV 이상 145 eV 이하인 실제 Run을 모두 찾아줘."
    draft = plan(question, [search([interval(128, 145, question)], id="s_search")])
    wire = plan_wire(question, draft)
    name = "ordering.s_search"
    assert question not in wire["state"]
    state, _, _ = project_check(wire["state"], name, wire["questions"][name])
    view = json.loads(state)
    quote = view["question"]
    assert quote == "128 eV 이상 145 eV 이하인 실제 Run을 모두 찾아줘."
    assert view["plan"]["requirements"][0]["sources"] == [{"message_key": "question", "quote": quote}]
    assert view["plan"]["steps"][0]["inputs"]["goals"] == []


def test_ordering_uses_specific_choice_descriptions_in_the_previous_order():
    question = "평균 이온 에너지가 128 eV 이상 145 eV 이하인 실제 Run을 모두 찾아줘."
    wire = plan_wire(question, plan(question, [search([interval(128, 145, question)], id="s_search")]))
    order = wire["questions"]["ordering.s_search"]["criteria"]
    assert list(order) == ["match", "direction_changed", "missing", "unexpected", "unclear"]
    assert "requested no sorting and the plan has no sorting" in order["match"]
    assert "sorts by the metric the user requested" in order["direction_changed"]
    assert "no sorting goal for that metric" in order["missing"]
    assert "filter-only lookup" in order["unexpected"]
    assert "Numeric bounds alone do not establish missing sorting" in order["unclear"]
    assert wire["questions"]["request.tasks"]["criteria"]["missing"] == (
        "The plan omits this item requested in the original")
