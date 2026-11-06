import pytest

from kplasma_agent.v2.composition import assemble_answer
from kplasma_agent.v2.contracts import Evidence


def test_preview_and_final_use_the_same_value_reference_checks_and_units():
    from kplasma_agent.v2.composition import fill_value_references

    values = {"compare:O1": {"value": "0.000001 V", "percent": "12.5%"}}
    text = "차이는 {{value:compare:O1}}, 변화율은 {{value:compare:O1|percent}}입니다."
    evidence = [Evidence(id="compare:O1", executionId="compare", field="observation",
                         value="확인된 차이", unit=None)]
    draft = {"fact_ids": ["compare:O1"], "interpretations": [{"id": "I1", "evidence_ids": ["compare:O1"],
                                                             "text": text, "assumptions": []}], "limitations": []}
    preview = fill_value_references(text, ["compare:O1"], values, evidence_ids={"compare:O1"})
    rendered, saved = assemble_answer(draft, "data_request", evidence, numeric_values=values)
    assert preview == "차이는 0.000001 V, 변화율은 12.5%입니다."
    assert preview == saved["interpretations"][0]["text"]
    assert rendered.endswith(preview)


@pytest.mark.parametrize("text,cited,known,values,error", [
    ("{{value:O1}}", [], {"O1"}, {"O1": {"value": "1 V"}}, "not cited"),
    ("{{value:O1}}", ["O1"], set(), {"O1": {"value": "1 V"}}, "unknown evidence"),
    ("{{value:O1|maximum}}", ["O1"], {"O1"}, {"O1": {"value": "1 V"}}, "unavailable"),
    ("{{value:O1", ["O1"], {"O1"}, {"O1": {"value": "1 V"}}, "invalid value reference"),
])
def test_shared_value_validation_never_supplies_missing_defaults(text, cited, known, values, error):
    from kplasma_agent.v2.composition import fill_value_references

    with pytest.raises(ValueError, match=error):
        fill_value_references(text, cited, values, evidence_ids=known)
