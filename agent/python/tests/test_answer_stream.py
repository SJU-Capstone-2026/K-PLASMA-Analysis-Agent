import json

import pytest


def project(parts, *, mode="general_only", evidence_ids=(), numeric_values=None):
    from kplasma_agent.answer_stream import AnswerStreamProjector

    blocks = {}

    def append(block_id, text):
        blocks[block_id] = blocks.get(block_id, "") + text

    projector = AnswerStreamProjector(mode, append, evidence_ids=evidence_ids, numeric_values=numeric_values)
    for part in parts:
        projector.feed(part)
    return blocks


def test_general_body_is_visible_before_json_string_and_object_close():
    blocks = project(['{"paragraphs":["먼저 도착한 본문'])
    assert blocks == {"paragraphs.0": "먼저 도착한 본문"}


def test_only_allowed_fields_are_projected_at_every_unicode_and_escape_boundary():
    expected = {"paragraphs.0": '한국어 😀 "인용" \\ 경로\n새 줄', "paragraphs.1": "두 번째"}
    raw = json.dumps({"paragraphs": list(expected.values()), "sources": ["private:O12"]}, ensure_ascii=True)
    for split in range(len(raw) + 1):
        assert project([raw[:split], raw[split:]]) == expected
    assert project(list(raw)) == expected


def test_partial_evidence_identifier_never_authorizes_a_shorter_existing_identifier():
    from kplasma_agent.answer_stream import AnswerStreamProjector

    received = []
    projector = AnswerStreamProjector("data_request", lambda block, text: received.append((block, text)),
                                     evidence_ids={"compare:O1", "compare:O12"},
                                     numeric_values={"compare:O1": {"value": "1 V"},
                                                     "compare:O12": {"value": "12 V"}})
    projector.feed('{"fact_ids":["compare:O12"],"interpretations":[{"id":"private-id",'
                   '"text":"차이는 {{value:compare:O12}}입니다.","evidence_ids":["compare:O1')
    assert received == [("interpretations.0.text", "차이는 ")]
    projector.feed('2"')
    assert received == [("interpretations.0.text", "차이는 ")]
    projector.feed('],"assumptions":[]}],"limitations":[]}')
    assert received == [("interpretations.0.text", "차이는 "),
                        ("interpretations.0.text", "12 V입니다.")]


def test_split_placeholders_share_final_numeric_rendering_for_all_public_paths():
    raw = json.dumps({"fact_ids": ["compare:O12"], "interpretations": [{
        "id": "private-interpretation", "evidence_ids": ["compare:O12"],
        "text": "차이는 {{value:compare:O12}}입니다.",
        "assumptions": ["변화율은 {{value:compare:O12|percent}}입니다."],
    }], "limitations": [{"id": "private-limit", "evidence_ids": ["compare:O12"],
                          "text": "상한은 {{value:compare:O12}}입니다."}]}, ensure_ascii=False)
    expected = {"interpretations.0.text": "차이는 12 V입니다.",
                "interpretations.0.assumptions.0": "변화율은 25%입니다.",
                "limitations.0.text": "상한은 12 V입니다."}
    for split in range(len(raw) + 1):
        assert project([raw[:split], raw[split:]], mode="data_request", evidence_ids={"compare:O12"},
                       numeric_values={"compare:O12": {"value": "12 V", "percent": "25%"}}) == expected
    assert project(list(raw), mode="data_request", evidence_ids={"compare:O12"},
                   numeric_values={"compare:O12": {"value": "12 V", "percent": "25%"}}) == expected


@pytest.mark.parametrize("token,citations,values", [
    ("{{value:unknown}}", ["unknown"], {"unknown": {"value": "999 V"}}),
    ("{{value:compare:O12}}", ["compare:O1"], {"compare:O12": {"value": "12 V"}}),
    ("{{value:compare:O1|missing}}", ["compare:O1"], {"compare:O1": {"value": "1 V"}}),
    ("{{value:compare:O1", ["compare:O1"], {"compare:O1": {"value": "1 V"}}),
])
def test_unverified_or_incomplete_values_and_suffix_stay_private(token, citations, values):
    raw = json.dumps({"fact_ids": [], "interpretations": [{"id": "private", "evidence_ids": citations,
                                                          "text": "안전한 앞말 " + token + " 뒤쪽",
                                                          "assumptions": []}], "limitations": []})
    assert project(list(raw), mode="data_request", evidence_ids={"compare:O1", "compare:O12"},
                   numeric_values=values) == {"interpretations.0.text": "안전한 앞말 "}


def test_normal_empty_prose_does_not_invent_text():
    assert project(['{"fact_ids":[],"interpretations":[],"limitations":[]}'], mode="data_request") == {}


def test_field_names_and_private_nested_text_are_not_public():
    raw = json.dumps({"private": {"paragraphs": ["hidden"], "text": "hidden"}, "sources": ["hidden"],
                      "paragraphs": ["public"]})
    assert project(list(raw)) == {"paragraphs.0": "public"}
