import json

import pytest


def selection():
    from kplasma_agent.v2_local_llm.core.selected_values import SelectedValues

    return SelectedValues({"evidence": [{"id": "exec:energy", "value_parts": ["value", "percent"]}]})


def draft():
    return {"fact_ids": ["E1"], "interpretations": [{"id": "i1", "evidence_ids": ["E1"],
        "segments": [{"kind": "text", "text": "값은 "}, {"kind": "evidence", "ref": "V1"}],
        "assumptions": [[{"kind": "text", "text": "변화율은 "}, {"kind": "evidence", "ref": "V2"}]]}],
        "limitations": [{"id": "l1", "evidence_ids": [], "segments": [
            {"kind": "text", "text": "최댓값은 "}, {"kind": "evidence", "ref": "V1"}]}]}


def test_code_builds_references_for_interpretations_assumptions_and_limits():
    values = selection()
    result = values.compile(draft())
    assert result == {"fact_ids": ["exec:energy"], "interpretations": [{"id": "i1", "evidence_ids": ["exec:energy"],
        "text": "값은 {{value:exec:energy|value}}", "assumptions": ["변화율은 {{value:exec:energy|percent}}"]}],
        "limitations": [{"id": "l1", "evidence_ids": ["exec:energy"], "text": "최댓값은 {{value:exec:energy|value}}"}]}


@pytest.mark.parametrize("corruption", ["unknown", "old_marker", "number_instead_of_ref"])
def test_writer_cannot_invent_refs_or_put_reference_syntax_in_text(corruption):
    data = draft()
    segments = data["interpretations"][0]["segments"]
    if corruption == "unknown":
        segments[1]["ref"] = "V9"
    elif corruption == "number_instead_of_ref":
        segments[1]["ref"] = "12 eV"
    else:
        segments[0]["text"] = "{{value:exec:energy|12 eV}}"
    with pytest.raises(ValueError):
        selection().compile(data)


def test_choice_schema_is_limited_to_this_requests_available_values():
    from kplasma_agent.v2_local_llm.core.selected_values import SelectedValues
    from kplasma_agent.v2_local_llm.model_client import strict_schema

    values = selection()
    schema = strict_schema(values.output_model)
    assert schema["$defs"]["EvidenceSegment"]["properties"]["ref"]["enum"] == ["V1", "V2"]
    empty = SelectedValues({"evidence": []})
    assert "EvidenceSegment" not in strict_schema(empty.output_model).get("$defs", {})
    with pytest.raises(ValueError):
        empty.compile(draft())


@pytest.mark.parametrize("group", ["fact_ids", "interpretations", "limitations"])
@pytest.mark.parametrize("invalid", ["E9", "exec:energy", "exec:changed"])
def test_all_citation_lists_reject_unknown_choices_and_raw_ids(group, invalid):
    data = draft()
    if group == "fact_ids":
        data[group] = [invalid]
    else:
        data[group][0]["evidence_ids"] = [invalid]
    with pytest.raises(ValueError):
        selection().compile(data)


def test_evidence_choice_schema_and_non_numeric_citations_use_the_same_catalog():
    from kplasma_agent.v2_local_llm.core.selected_values import SelectedValues
    from kplasma_agent.v2_local_llm.model_client import strict_schema

    values = SelectedValues({"evidence": [{"id": "exec:energy", "value_parts": ["value"]},
                                         {"id": "exec:observation"}]})
    assert values.evidence_choices == [{"ref": "E1", "evidence_id": "exec:energy"},
                                       {"ref": "E2", "evidence_id": "exec:observation"}]
    schema = strict_schema(values.output_model)
    assert schema["properties"]["fact_ids"]["items"]["enum"] == ["E1", "E2"]
    for name in ("SelectedInterpretation", "SelectedLimitation"):
        assert schema["$defs"][name]["properties"]["evidence_ids"]["items"]["enum"] == ["E1", "E2"]
    data = draft()
    data["fact_ids"] = ["E2", "E1"]
    data["interpretations"][0]["evidence_ids"] = ["E2", "E1"]
    data["interpretations"][0]["assumptions"] = []
    compiled = values.compile(data)
    assert compiled["fact_ids"] == ["exec:observation", "exec:energy"]
    assert compiled["interpretations"][0]["evidence_ids"] == ["exec:observation", "exec:energy"]


def test_no_evidence_allows_empty_citation_lists_only():
    from kplasma_agent.v2_local_llm.core.selected_values import SelectedValues

    values = SelectedValues({"evidence": []})
    data = {"fact_ids": [], "interpretations": [], "limitations": [
        {"id": "l1", "evidence_ids": [], "segments": [{"kind": "text", "text": "근거 부족"}]}]}
    assert values.compile(data)["limitations"][0] == {"id": "l1", "evidence_ids": [], "text": "근거 부족"}
    data["fact_ids"] = ["E1"]
    with pytest.raises(ValueError):
        values.compile(data)


def test_split_literal_reference_is_rejected_and_never_streamed():
    data = draft()
    data["interpretations"][0]["segments"] = [
        {"kind": "text", "text": "{{val"}, {"kind": "text", "text": "ue:exec:energy|value}}"}]
    values = selection()
    observed = []
    projector = values.projector(lambda _key, text: observed.append(text),
                                numeric_values={"exec:energy": {"value": "12 eV", "percent": "5%"}})
    for char in json.dumps(data, ensure_ascii=False):
        projector.feed(char)
    assert "{{" not in "".join(observed)
    with pytest.raises(ValueError):
        values.compile(data)


def test_stream_resolves_selected_values_and_keeps_the_public_block_names():
    values = selection()
    blocks = {}
    projector = values.projector(lambda key, text: blocks.__setitem__(key, blocks.get(key, "") + text),
        numeric_values={"exec:energy": {"value": "12 eV", "percent": "5%"}})
    raw = json.dumps(draft(), ensure_ascii=False)
    for char in raw:
        projector.feed(char)
    assert blocks == {"interpretations.0.text": "값은 12 eV", "interpretations.0.assumptions.0": "변화율은 5%",
                      "limitations.0.text": "최댓값은 12 eV"}
    assert not any("V1" in text or "{{value:" in text for text in blocks.values())
