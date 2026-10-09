"""Canonical numerical units and display precision; no physical predictions."""

import math
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP

CONDITION_KEYS = ("pressure", "sourcePower", "biasPower")
OUTPUT_METRICS = ("meanIonEnergy", "ionFlux", "iedWidth")
DEFAULT_METRICS = list(OUTPUT_METRICS)
NUMERIC_POLICY_VERSION = "v1"
UNITS = {
    "pressure": "mTorr",
    "sourcePower": "W",
    "biasPower": "W",
    "meanIonEnergy": "eV",
    "ionFlux": "10¹⁸ m⁻²s⁻¹",
    "iedWidth": "eV",
}
LABELS = {
    "pressure": "압력",
    "sourcePower": "소스 전력",
    "biasPower": "바이어스 전력",
    "meanIonEnergy": "평균 이온 에너지",
    "ionFlux": "이온 플럭스",
    "iedWidth": "IED 폭",
}


class NumericError(ValueError):
    def __init__(self, code: str, metric: str | None = None):
        self.code = code
        self.metric = metric
        super().__init__(f"{code}: {metric}" if metric else code)


def is_finite(value) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def is_watt_spelling(unit) -> bool:
    """Accept a clear spelling of watt, never a scaled or different unit."""
    if not isinstance(unit, str):
        return False
    if unit.casefold() in ("w", "와트", "watt", "watts"):
        return True
    if not re.fullmatch(r"[가-힣ㄱ-ㅣᄀ-ᇿ]+", unit):
        return False
    # Compare keyboard letters so 왓트/왛트 are one extra consonant and
    # 오ㅏ트 is the same letters as 와트. Prefixes remain part of the token.
    written = unicodedata.normalize("NFKD", unit).replace("ᅪ", "ᅩᅡ")
    expected = "오ᅡ트"
    if abs(len(written) - len(expected)) > 1:
        return False
    if len(written) == len(expected):
        return sum(a != b for a, b in zip(written, expected)) <= 1
    shorter, longer = sorted((written, expected), key=len)
    for index, character in enumerate(shorter):
        if character != longer[index]:
            return shorter[index:] == longer[index + 1:]
    return True


def normalize_unit(metric: str, unit: str) -> str:
    """Normalize names, never prefixes or physical magnitudes."""
    unit = unit.strip()
    if metric in ("sourcePower", "biasPower") and is_watt_spelling(unit):
        return "W"
    name = re.sub(r"\s+", "", unit).casefold()
    if metric in ("meanIonEnergy", "iedWidth") and name in (
        "ev", "e볼트", "이볼트", "전자볼트", "일렉트론볼트", "electronvolt", "electronvolts",
    ):
        return "eV"
    if metric == "pressure":
        if name in ("mtorr", "밀리토르", "밀리토어", "millitorr"):
            return "mTorr"
        if name in ("torr", "토르", "토어"):
            return "Torr"
    return unit


def normalize_value(metric: str, value, unit: str | None = None) -> float:
    if metric not in UNITS:
        raise NumericError("UNSUPPORTED_METRIC", metric)
    if not is_finite(value):
        raise NumericError("INVALID_VALUE", metric)
    # Stored scalars and resolved query inputs share canonical units.
    # The graph records omitted query units before execution.
    unit = UNITS[metric] if unit is None else normalize_unit(metric, unit)
    converted = float(value)
    if unit == UNITS[metric]:
        pass
    elif metric == "pressure" and unit == "Torr":
        converted *= 1000
    elif metric == "ionFlux" and unit in ("m⁻²s⁻¹", "m^-2s^-1", "m^-2 s^-1", "m-2s-1"):
        converted /= 1e18
    elif metric == "ionFlux" and unit in ("10^18 m^-2s^-1", "10^18 m^-2 s^-1"):
        pass
    else:
        raise NumericError("UNIT_NOT_COMPARABLE", metric)
    if not math.isfinite(converted):
        raise NumericError("NUMERIC_OVERFLOW", metric)
    return 0.0 if converted == 0 else converted


def format_value(value, metric: str | None = None, *, digits: int | None = None) -> str:
    """Display only. Decimal half-up matches human decimal ties; raw values stay intact."""
    if not is_finite(value):
        return "N/A"
    digits = (0 if metric in CONDITION_KEYS else 1) if digits is None else digits
    # Decimal quantize's default context cannot represent arbitrarily large floats.
    if abs(value) >= 1e20:
        return f"{value:.{digits}e}"
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    if rounded == 0:
        return "0"
    formatted = format(rounded, "f")
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted
