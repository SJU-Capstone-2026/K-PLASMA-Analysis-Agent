"""Small artificial fixtures; these are not physical observations."""


def run(
    run_id="A", *, energy=20, flux=2, width=5, pressure=10, source=300, bias=100, score=100, version=None
):
    return {
        "runId": run_id,
        "runVersionId": version or f"synthetic-{run_id}-v1",
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
        "presentationScore": score,
        "analysis": {"hasDistribution": width is not None},
        "sourceFileCount": 2,
    }
