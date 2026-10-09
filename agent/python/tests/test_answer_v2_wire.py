import json
from copy import deepcopy
from pathlib import Path
import pytest
from pydantic import ValidationError
from kplasma_agent.answer_contracts import AnswerSnapshotV2, ComparisonResultV2

WIRE = json.loads((Path(__file__).resolve().parents[2] / "tests/support/answer-v2-wire.json").read_text())


@pytest.mark.parametrize("key", ["comparison", "general", "forward", "reverse"])
def test_public_wire_fixture_roundtrips_without_dropping_nulls_or_zero(key):
    assert AnswerSnapshotV2.model_validate(WIRE[key]).model_dump() == WIRE[key]


def test_incomplete_or_inconsistent_scalar_and_reference_inventory_are_rejected():
    for change in ("missing", "infinity", "inventory", "wrong_tool"):
        value = deepcopy(WIRE["comparison"])
        datum = value["result"]["runs"][0]["metrics"]["ionFlux"]
        if change == "missing":
            del datum["sourceValue"]
        elif change == "infinity":
            datum["value"] = float("inf")
        elif change == "inventory":
            value["result"]["usedRunRefs"].reverse()
        else:
            value["toolSelection"]["name"] = "generate_answer"
        with pytest.raises(ValidationError):
            AnswerSnapshotV2.model_validate(value)


def test_failed_partial_has_the_entire_validated_numeric_result():
    value = {k: v for k, v in WIRE["partial"].items() if k not in ("schemaVersion", "explanationComplete")}
    assert ComparisonResultV2.model_validate(value).model_dump() == WIRE["comparison"]["result"]
