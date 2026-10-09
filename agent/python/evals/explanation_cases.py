"""Forty distinct qualitative packets derived from artificial scalar fixtures."""

from dataclasses import dataclass

from kplasma_agent.domain.compare import compare_selected


@dataclass(frozen=True)
class ExplanationCase:
    id: str
    kind: str
    scenario: str
    evidence: dict
    question: str = ""


def synthetic_run(name, *, pressure=10, source=300, bias=100, energy=20, flux=2, width=5):
    return {
        "runId": name,
        "runVersionId": f"synthetic-{name}-version",
        "pressure": pressure,
        "sourcePower": source,
        "biasPower": bias,
        "metrics": {"meanIonEnergy": energy, "ionFlux": flux, "iedWidth": width},
        "units": {
            "pressure": "mTorr",
            "sourcePower": "W",
            "biasPower": "W",
            "meanIonEnergy": "eV",
            "ionFlux": "10¹⁸ m⁻²s⁻¹",
            "iedWidth": "eV",
        },
        "qualityStatus": "VERIFIED",
        "convergenceStatus": "CONVERGED",
        "catalogStatus": "READY",
    }


def build_cases():
    cases = []
    pairs = [
        ("source higher / flux higher", {}, {"source": 500, "flux": 3}, ["ionFlux"]),
        ("source lower / flux lower", {}, {"source": 200, "flux": 1}, ["ionFlux"]),
        ("bias higher / energy higher", {}, {"bias": 200, "energy": 30}, ["meanIonEnergy"]),
        ("bias lower / energy lower", {}, {"bias": 50, "energy": 10}, ["meanIonEnergy"]),
        ("pressure higher / width wider", {}, {"pressure": 15, "width": 8}, ["iedWidth"]),
        ("pressure lower / width narrower", {}, {"pressure": 5, "width": 3}, ["iedWidth"]),
        ("source higher / energy lower", {}, {"source": 500, "energy": 15}, ["meanIonEnergy"]),
        ("source higher / flux lower countertrend", {}, {"source": 500, "flux": 1}, ["ionFlux"]),
        ("bias higher / width wider", {}, {"bias": 200, "width": 8}, ["iedWidth"]),
        ("bias higher / width narrower", {}, {"bias": 200, "width": 3}, ["iedWidth"]),
        (
            "source and bias changed",
            {},
            {"source": 500, "bias": 200, "flux": 3, "energy": 30},
            ["ionFlux", "meanIonEnergy"],
        ),
        (
            "pressure and source changed / mixed results",
            {},
            {"pressure": 15, "source": 500, "flux": 1, "energy": 30},
            ["ionFlux", "meanIonEnergy"],
        ),
        (
            "all three operating conditions changed",
            {},
            {"pressure": 15, "source": 200, "bias": 50, "flux": 3, "width": 3},
            ["ionFlux", "iedWidth"],
        ),
        ("same recorded conditions / flux changed", {}, {"flux": 3}, ["ionFlux"]),
        ("no observed change", {}, {}, ["meanIonEnergy", "ionFlux", "iedWidth"]),
        (
            "all requested result scalars missing",
            {"energy": None, "flux": None, "width": None},
            {"source": 500, "energy": None, "flux": None, "width": None},
            ["meanIonEnergy", "ionFlux", "iedWidth"],
        ),
        (
            "width missing but flux comparison available",
            {"width": None},
            {"source": 500, "flux": 3, "width": None},
            ["ionFlux", "iedWidth"],
        ),
        (
            "pressure missing / condition comparison incomplete",
            {"pressure": None},
            {"source": 500, "flux": 3},
            ["ionFlux"],
        ),
        (
            "zero baseline flux / percent unavailable",
            {"flux": 0},
            {"bias": 50, "flux": 3, "energy": 10},
            ["ionFlux", "meanIonEnergy"],
        ),
        (
            "zero to zero with missing width / no measured change",
            {"flux": 0, "width": None},
            {"flux": 0, "width": None},
            ["ionFlux", "iedWidth"],
        ),
    ]
    for index, (scenario, baseline, target, metrics) in enumerate(pairs, 1):
        runs = [synthetic_run("BASELINE", **baseline), synthetic_run("TARGET", **target)]
        entries = [
            {"key": f"R{i + 1}", "ref": {k: r[k] for k in ("runId", "runVersionId")}, "run": r}
            for i, r in enumerate(runs)
        ]
        result = compare_selected({"metrics": metrics, "baseline_key": "R1"}, entries)
        question = f"R1을 기준으로 R2의 {', '.join(metrics)} 차이가 나는 가능한 이유를 설명해줘."
        cases.append(ExplanationCase(f"change-{index:02}", "compare_runs", scenario, result, question))
    concepts = [
        (["ionFlux"], "definition"),
        (["meanIonEnergy"], "definition"),
        (["iedWidth"], "definition"),
        (["ied"], "definition"),
        (["sourcePower"], "definition"),
        (["biasPower"], "definition"),
        (["pressure"], "definition"),
        (["electronDensity"], "definition"),
        (["electronTemperature"], "definition"),
        (["sheath"], "definition"),
        (["plasma"], "definition"),
        (["ionFlux", "meanIonEnergy"], "difference"),
        (["sourcePower", "biasPower"], "difference"),
        (["electronDensity", "electronTemperature"], "difference"),
        (["ied", "iedWidth"], "difference"),
        (["sourcePower", "ionFlux"], "relationship"),
        (["biasPower", "meanIonEnergy"], "relationship"),
        (["pressure", "iedWidth"], "relationship"),
        (["sheath", "meanIonEnergy"], "relationship"),
        (["electronTemperature", "electronDensity"], "relationship"),
    ]
    for index, (topics, aspect) in enumerate(concepts, 1):
        cases.append(
            ExplanationCase(
                f"concept-{index:02}",
                "generate_answer",
                f"{aspect}: {' / '.join(topics)}",
                {},
                f"{', '.join(topics)}의 {aspect}을 일반 물리 지식으로 설명해줘.",
            )
        )
    assert len(cases) == 40
    return cases


EXPLANATION_CASES = build_cases()
