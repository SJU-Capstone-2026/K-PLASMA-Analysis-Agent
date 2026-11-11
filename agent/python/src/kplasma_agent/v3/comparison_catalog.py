"""Allowed comparison fields. Formulae and units are owned by code, not the model."""

from typing import Literal
from .metric_registry import LABELS, UNITS

PlotId = Literal["ied", "iad", "iead", "current", "potential", "density", "residual"]
ComparisonField = Literal[
    "ionFlux", "meanIonEnergy", "iedWidth", "pressure", "sourcePower", "biasPower",
    "current.maximum", "current.minimum", "current.peakToPeak", "current.halfPeakToPeak",
    "current.maximumPhase", "current.minimumPhase",
    "potential.maximum", "potential.minimum", "potential.peakToPeak", "potential.halfPeakToPeak",
    "potential.maximumPhase", "potential.minimumPhase",
    "ied.maximum", "ied.peakEnergy", "iad.maximum", "iad.peakAngle",
    "iead.maximum", "iead.peakEnergy", "iead.peakAngle",
    "density.maximum", "density.maximumPhase", "density.maximumDistance",
    "residual.maximum", "residual.maximumIteration", "residual.final", "residual.finalIteration",
]
FEATURE_POLICY = "source-features-1"
PLOT_NAMES = {
    "ied": "이온 에너지 분포", "iad": "이온 입사각 분포", "iead": "에너지·입사각 분포",
    "current": "RF 전류 밀도", "potential": "전극 전위", "density": "쉬스 이온 밀도",
    "residual": "수렴 잔차",
}
FIELD_META = {k: {"label": LABELS[k], "unit": UNITS[k], "plotId": None, "definition": "저장된 실험 수치"}
              for k in ("ionFlux", "meanIonEnergy", "iedWidth", "pressure", "sourcePower", "biasPower")}
for plot, unit in (("current", "statampere/cm²"), ("potential", "V")):
    for suffix, label, definition, field_unit in (
        ("maximum", "최댓값", "원본 관측 구간의 최대 y값", unit),
        ("minimum", "최솟값", "원본 관측 구간의 최소 y값", unit),
        ("peakToPeak", "첨두간 값", "최댓값 − 최솟값", unit),
        ("halfPeakToPeak", "반첨두간 진폭", "(최댓값 − 최솟값) / 2", unit),
        ("maximumPhase", "첫 최대 RF 위상", "공동 최대 중 첫 원본 위치", "RF cycle"),
        ("minimumPhase", "첫 최소 RF 위상", "공동 최소 중 첫 원본 위치", "RF cycle"),
    ):
        FIELD_META[f"{plot}.{suffix}"] = {"label": f"{PLOT_NAMES[plot]} {label}", "unit": field_unit,
                                         "plotId": plot, "definition": definition}
for field, label, unit in (
    ("ied.maximum", "IED 최대 강도", "a.u."), ("ied.peakEnergy", "IED 첫 최대 에너지", "eV"),
    ("iad.maximum", "IAD 최대 강도", "a.u."), ("iad.peakAngle", "IAD 첫 최대 입사각", "°"),
    ("iead.maximum", "IEAD 최대 강도", "원본 단위 미지정"),
    ("iead.peakEnergy", "IEAD 첫 최대 에너지", "eV"), ("iead.peakAngle", "IEAD 첫 최대 입사각", "°"),
    ("density.maximum", "쉬스 이온 밀도 최댓값", "원본 단위 미지정"),
    ("density.maximumPhase", "밀도 첫 최대 RF 위상", "RF cycle"),
    ("density.maximumDistance", "밀도 첫 최대 거리", "cm"),
    ("residual.maximum", "최대 잔차", "a.u."), ("residual.maximumIteration", "첫 최대 잔차 반복", "iteration"),
    ("residual.final", "마지막 잔차", "a.u."), ("residual.finalIteration", "마지막 반복", "iteration"),
):
    FIELD_META[field] = {"label": label, "unit": unit, "plotId": field.split('.')[0],
                         "definition": "전체 원본 격자에서 계산; 공동 극값 위치는 첫 원본 위치"}
COORDINATE_FIELDS = {k for k in FIELD_META if "." in k and k.endswith(("Phase", "Angle", "Energy", "Distance", "Iteration"))}


def comparison_plan(inputs):
    fields = list(inputs.get("comparison_fields") or inputs.get("metrics") or [])
    plots = list(inputs.get("plot_ids") or [])
    if not fields:
        fields = [k for k, meta in FIELD_META.items() if meta["plotId"] in plots] if plots else [
            "ionFlux", "meanIonEnergy", "iedWidth"
        ]
    if plots and not inputs.get("comparison_fields") and not inputs.get("metrics"):
        fields = list(dict.fromkeys([*( ["meanIonEnergy", "iedWidth"] if "ied" in plots else []), *fields]))
    needed = list(dict.fromkeys([*plots, *(FIELD_META[k]["plotId"] for k in fields if FIELD_META[k]["plotId"])]))
    return fields, plots, needed
