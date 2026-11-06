import pytest

from kplasma_agent.v2.contracts import Quantity
from kplasma_agent.v2.derivations import compute_derived


def flux(value, unit, evidence):
    return Quantity(value=value, unit=unit, field="ionFlux", evidence_ids=[evidence])


def test_max_uses_canonical_units_and_keeps_both_sources():
    result = compute_derived("max", [flux(1.2e19, "m^-2 s^-1", "a"), flux(18, "10¹⁸ m⁻²s⁻¹", "b")])
    assert (result.value, result.unit, result.evidence_ids) == (18, "10¹⁸ m⁻²s⁻¹", ["a", "b"])


def test_invalid_ratio_and_mixed_dimensions_block_calculation():
    with pytest.raises(ValueError, match="zero"):
        compute_derived("ratio", [flux(18, "10¹⁸ m⁻²s⁻¹", "a"), flux(0, "10¹⁸ m⁻²s⁻¹", "b")])
    with pytest.raises(ValueError, match="physical quantity"):
        compute_derived("max", [
            flux(18, "10¹⁸ m⁻²s⁻¹", "a"), Quantity(value=3, field="iedWidth", unit="eV"),
        ])
