import pytest

from kplasma_agent.metric_registry import NumericError, normalize_value, format_value


def test_unit_conversion_once_and_default_units():
    assert normalize_value("pressure", 0.01, "Torr") == 10
    assert normalize_value("ionFlux", 3e18, "m⁻²s⁻¹") == 3
    assert normalize_value("ionFlux", 3, "10¹⁸ m⁻²s⁻¹") == 3
    assert normalize_value("pressure", 10) == 10


@pytest.mark.parametrize("metric", ["sourcePower", "biasPower"])
@pytest.mark.parametrize("unit", ["와트", "watt", "Watts", "w"])
def test_written_watt_names_preserve_power_values(metric, unit):
    assert normalize_value(metric, 300, unit) == normalize_value(metric, 300, "W")


@pytest.mark.parametrize("unit", ["킬로와트", "밀리와트", "kW"])
def test_scaled_watt_units_are_not_treated_as_watts(unit):
    with pytest.raises(NumericError, match="UNIT_NOT_COMPARABLE"):
        normalize_value("sourcePower", 300, unit)


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
