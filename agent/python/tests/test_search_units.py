"""Unit spelling and grounding contracts using artificial values."""

import pytest

from kplasma_agent.domain import DomainError, lookup_forward, search_reverse
from kplasma_agent.domain.grounding import validate_grounding
from kplasma_agent.metric_registry import normalize_value


@pytest.mark.parametrize("metric", ["meanIonEnergy", "iedWidth"])
@pytest.mark.parametrize("unit", ["e볼트", "전자볼트", "전자 볼트", "electron volt", "electronvolts", "EV"])
def test_energy_unit_words_normalize_without_changing_magnitude(metric, unit):
    assert normalize_value(metric, 35, unit) == 35


def test_search_tools_reject_missing_numeric_units_before_execution():
    with pytest.raises(DomainError, match="MISSING_UNIT"):
        lookup_forward(
            {
                "conditions": {
                    "pressure": {"value": 8},
                    "sourcePower": {"value": 300, "unit": "W"},
                    "biasPower": {"value": 0, "unit": "W"},
                }
            },
            [],
        )
    with pytest.raises(DomainError, match="MISSING_UNIT"):
        search_reverse({"constraints": [{"metric": "meanIonEnergy", "operator": "lte", "value": 40}]}, [])


@pytest.mark.parametrize(
    "metric,word,unit",
    [
        ("pressure", "킬로 토르", "Torr"),
        ("meanIonEnergy", "킬로 전자 볼트", "eV"),
        ("meanIonEnergy", "킬로 e볼트", "eV"),
        ("sourcePower", "킬로 와트", "W"),
    ],
)
def test_written_unit_prefix_is_never_dropped(metric, word, unit):
    proposed = {
        "kind": "reverse_search",
        "inputs": {
            "constraints": [{"metric": metric, "operator": "lte", "value": 30, "unit": unit}],
        },
    }
    labels = {"pressure": "압력", "meanIonEnergy": "에너지", "sourcePower": "소스"}
    with pytest.raises(DomainError, match="UNGROUNDED_NUMBER"):
        validate_grounding(proposed, f"{labels[metric]} 30 {word} 이하 후보", [])
