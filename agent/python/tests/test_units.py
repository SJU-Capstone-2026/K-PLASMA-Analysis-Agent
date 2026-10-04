import pytest

from kplasma_agent.metric_registry import NumericError, normalize_value, format_value


def test_unit_conversion_once_and_default_units():
    assert normalize_value("pressure", 0.01, "Torr") == 10
    assert normalize_value("ionFlux", 3e18, "m⁻²s⁻¹") == 3
    assert normalize_value("ionFlux", 3, "10¹⁸ m⁻²s⁻¹") == 3
    assert normalize_value("pressure", 10) == 10


@pytest.mark.parametrize(
    "value,unit,code",
    [
        (True, "mTorr", "INVALID_VALUE"),
        (float("nan"), "mTorr", "INVALID_VALUE"),
        (1, "Pa", "UNIT_NOT_COMPARABLE"),
        (1e308, "Torr", "NUMERIC_OVERFLOW"),
    ],
)
def test_invalid_input_is_not_silently_normalized(value, unit, code):
    with pytest.raises(NumericError) as error:
        normalize_value("pressure", value, unit)
    assert error.value.code == code


def test_display_rounding_does_not_round_search_values():
    assert format_value(-0.0001, "meanIonEnergy") == "0"
    assert format_value(20.25, "meanIonEnergy") == "20.3"
    assert normalize_value("meanIonEnergy", 20.25) == 20.25
