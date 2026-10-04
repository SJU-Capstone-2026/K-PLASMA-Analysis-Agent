"""Reviewed synthetic questions and required slots, not physical observations.

140 distinct questions: 100 retrieval/comparison and 40 explanation routing.
These cases assess interpretation, grounding and clarification. They do not
certify the physical correctness of model-generated scientific explanations.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    question: str
    kind: str | None
    expected_inputs: dict = field(default_factory=dict)
    absent_slots: tuple[str, ...] = ()
    clarification: bool = False
    unsupported: bool = False
    context_available: dict = field(default_factory=dict)
    input_history: list = field(default_factory=list)
    prior_interpretation: dict | None = None


def scalar(value, unit=None):
    return {"value": value, **({"unit": unit} if unit else {})}


def conditions(pressure=None, source=None, bias=None, pressure_unit="mTorr"):
    return {
        key: scalar(value, unit)
        for key, value, unit in (
            ("pressure", pressure, pressure_unit),
            ("sourcePower", source, "W"),
            ("biasPower", bias, "W"),
        )
        if value is not None
    }


def constraint(metric, operator, value=None, *, low=None, high=None, unit=None):
    return {
        "metric": metric,
        "operator": operator,
        **({"min": low, "max": high} if operator == "between" else {"value": value}),
        **({"unit": unit} if unit else {}),
    }


def goal(metric, direction, low=None, high=None, unit=None):
    return {
        "metric": metric,
        "direction": direction,
        **({"min": low, "max": high} if direction == "target_range" else {}),
        **({"unit": unit} if unit else {}),
    }


def selector(run_id, version=None):
    return {"kind": "run_id", "run_id": run_id, **({"run_version_id": version} if version else {})}


def build_cases():
    cases = []

    def add(category, question, kind, expected=None, **kwargs):
        index = sum(case.category == category for case in cases) + 1
        cases.append(Case(f"{category}-{index:02}", category, question, kind, expected or {}, **kwargs))

    # Forward: varied word order, aliases, omitted units, missing slots and updates.
    for question, values in [
        ("압력 10 mTorr, 소스 300 W, 바이어스 100 W의 실제 결과를 보여줘.", conditions(10, 300, 100)),
        ("압력8mTorr 소스450W 바이어스600W 결과 조회", conditions(8, 450, 600)),
        ("바이어스 0 W와 소스 200 W, 압력 5 mTorr로 저장된 Run이 있어?", conditions(5, 200, 0)),
        (
            "pressure 12 mTorr, source power 250 W, bias power 50 W: show existing results",
            conditions(12, 250, 50),
        ),
        ("압력 0.01 Torr에서 소스 300 W, 바이어스 100 W인 Run을 조회해.", conditions(0.01, 300, 100, "Torr")),
        ("소스 전력은 350 W, 바이어스 전력은 80 W, 압력은 7 mTorr야. 결과 확인해줘.", conditions(7, 350, 80)),
        ("10 mTorr 압력, 300 W 소스, 100 W 바이어스의 결과 조회", conditions(10, 300, 100)),
        ("압력 6.5 mTorr / 소스 425 W / 바이어스 125 W 조건을 조회하고 싶어.", conditions(6.5, 425, 125)),
        ("Forward lookup: pressure=9 mTorr; source=275 W; bias=75 W.", conditions(9, 275, 75)),
        (
            "압력 2 mTorr, 소스 100 W, 바이어스 0 W 조건과 정확히 같은 저장 결과를 찾아줘.",
            conditions(2, 100, 0),
        ),
        (
            "source power 500 W, pressure 15 mTorr and bias power 200 W. Retrieve the measured result.",
            conditions(15, 500, 200),
        ),
        ("압력은 10 mTorr 아니고 20 mTorr, 소스300W 바이어스100W로 결과 보여줘.", conditions(20, 300, 100)),
        ("압력 0.005 Torr에 바이어스 40 W, 소스 180 W의 결과가 궁금해.", conditions(0.005, 180, 40, "Torr")),
        ("소스 1,000 W에 압력 18 mTorr, 바이어스 250 W를 적용한 기존 Run 조회", conditions(18, 1000, 250)),
        ("저장된 데이터에서 압력 3 mTorr / 소스 150 W / 바이어스 20 W를 조회해줘.", conditions(3, 150, 20)),
        ("소스파워 320 W와 바이어스파워 60 W, 압력 11 mTorr 결과 확인", conditions(11, 320, 60)),
        ("압력 4 mTorr 소스 220 W 바이어스 90 W 조건 조회 부탁해", conditions(4, 220, 90)),
        ("바이어스 140 W, 압력 13 mTorr, 소스 380 W로 등록된 결과만 알려줘.", conditions(13, 380, 140)),
        (
            "압력10 소스300 바이어스100의 결과를 조회해",
            {
                key: {"value": val}
                for key, val in [("pressure", 10), ("sourcePower", 300), ("biasPower", 100)]
            },
        ),
        (
            "pressure 1e-2 Torr, source 300 W, bias 100 W: existing Run lookup",
            conditions(0.01, 300, 100, "Torr"),
        ),
        ("압력 25 mTorr에 소스 650 W, 바이어스 350 W로 실행해 둔 결과 보여줘.", conditions(25, 650, 350)),
        ("압력 7.25 mTorr, 소스 333 W, 바이어스 77 W 조건 결과를 확인해줘.", conditions(7.25, 333, 77)),
    ]:
        add("forward", question, "forward_lookup", {"conditions": values})
    for question, supplied, missing in [
        ("압력 10 mTorr와 소스 300 W의 결과를 보여줘.", conditions(10, 300), "biasPower"),
        ("바이어스 100 W, 압력 8 mTorr로 조회해줘.", conditions(8, None, 100), "sourcePower"),
        ("소스 500 W 바이어스 200 W 조건의 결과가 궁금해.", conditions(None, 500, 200), "pressure"),
        ("압력 6 mTorr 결과 조회", conditions(6), "sourcePower"),
        ("소스 250 W 조건에서 실제 결과 보여줘.", conditions(None, 250), "pressure"),
    ]:
        add(
            "forward",
            question,
            "forward_lookup",
            {"conditions": supplied},
            absent_slots=(f"conditions.{missing}",),
            clarification=True,
        )
    add(
        "forward",
        "선택한 Run의 전체 결과를 다시 보여줘.",
        "forward_lookup",
        {"context_rules": ["selected_run_conditions"]},
        context_available={"selected_run": True},
    )
    prior = {
        "status": "needs_input",
        "operations": [{"kind": "forward_lookup", "inputs": {"conditions": conditions(10, 300)}}],
    }
    add(
        "forward",
        "압력 10 mTorr, 소스 300 W 결과 조회",
        "forward_lookup",
        {"conditions": conditions(10, 300, 100)},
        input_history=[{"text": "바이어스는 100 W야"}],
        prior_interpretation=prior,
    )
    add("forward", "새로운 실험을 지금 장비에서 직접 실행하고 압력을 조절해줘.", None, unsupported=True)

    # Reverse: distinct objectives, strict constraints, raw/scaled flux and scope.
    rows = [
        (
            "압력 10 mTorr 이하에서 이온 플럭스가 가장 높은 Run 찾아줘.",
            [constraint("pressure", "lte", 10, unit="mTorr")],
            [goal("ionFlux", "maximize")],
        ),
        (
            "압력10mTorr미만에서 평균 이온 에너지가 가장 낮은 후보",
            [constraint("pressure", "lt", 10, unit="mTorr")],
            [goal("meanIonEnergy", "minimize")],
        ),
        (
            "압력이 5 mTorr 이상이고 IED 폭이 가장 좁은 Run을 탐색해.",
            [constraint("pressure", "gte", 5, unit="mTorr")],
            [goal("iedWidth", "minimize")],
        ),
        (
            "소스 전력 300 W 초과 조건에서 플럭스 최대화",
            [constraint("sourcePower", "gt", 300, unit="W")],
            [goal("ionFlux", "maximize")],
        ),
        (
            "바이어스 전력 200 W 이하인 조건 중 에너지 최소화",
            [constraint("biasPower", "lte", 200, unit="W")],
            [goal("meanIonEnergy", "minimize")],
        ),
        (
            "에너지는 30~40 eV 범위여야 하고 플럭스는 최대인 Run",
            [constraint("meanIonEnergy", "between", low=30, high=40, unit="eV")],
            [goal("ionFlux", "maximize")],
        ),
        (
            "평균 이온 에너지가 50 eV 미만인 Run을 모두 찾아줘.",
            [constraint("meanIonEnergy", "lt", 50, unit="eV")],
            [],
        ),
        ("이온 에너지 25 eV 이상인 기존 후보 모두", [constraint("meanIonEnergy", "gte", 25, unit="eV")], []),
        (
            "IED 폭 8 eV 이하, 플럭스 최대화 조건 탐색",
            [constraint("iedWidth", "lte", 8, unit="eV")],
            [goal("ionFlux", "maximize")],
        ),
        (
            "IED width below 7 eV; maximize ion flux",
            [constraint("iedWidth", "lt", 7, unit="eV")],
            [goal("ionFlux", "maximize")],
        ),
        (
            "pressure at most 12 mTorr and mean ion energy between 20 and 35 eV",
            [
                constraint("pressure", "lte", 12, unit="mTorr"),
                constraint("meanIonEnergy", "between", low=20, high=35, unit="eV"),
            ],
            [],
        ),
        (
            "pressure under 9 mTorr, lowest IED width",
            [constraint("pressure", "lt", 9, unit="mTorr")],
            [goal("iedWidth", "minimize")],
        ),
        (
            "소스 400 W 이상, 바이어스 150 W 미만에서 플럭스가 가장 큰 Run",
            [constraint("sourcePower", "gte", 400, unit="W"), constraint("biasPower", "lt", 150, unit="W")],
            [goal("ionFlux", "maximize")],
        ),
        (
            "평균 이온 에너지 40 eV와 정확히 같은 Run 찾아줘.",
            [constraint("meanIonEnergy", "eq", 40, unit="eV")],
            [],
        ),
        (
            "압력 0.01 Torr 이하에서 플럭스 최대화",
            [constraint("pressure", "lte", 0.01, unit="Torr")],
            [goal("ionFlux", "maximize")],
        ),
        ("플럭스 2e18 m⁻²s⁻¹ 이상인 Run을 검색해.", [constraint("ionFlux", "gte", 2e18, unit="m⁻²s⁻¹")], []),
        (
            "이온 플럭스 2 10¹⁸ m⁻²s⁻¹ 이상, 에너지는 최소화",
            [constraint("ionFlux", "gte", 2, unit="10¹⁸ m⁻²s⁻¹")],
            [goal("meanIonEnergy", "minimize")],
        ),
        ("플럭스가 가장 높은 후보를 찾아줘.", [], [goal("ionFlux", "maximize")]),
        ("가장 낮은 평균 이온 에너지 Run은?", [], [goal("meanIonEnergy", "minimize")]),
        ("IED 폭을 최소화할 수 있는 기존 Run 찾아줘.", [], [goal("iedWidth", "minimize")]),
        (
            "플럭스 최대화를 우선하고 다음으로 에너지를 최소화해.",
            [],
            [goal("ionFlux", "maximize"), goal("meanIonEnergy", "minimize")],
        ),
        (
            "에너지 최소화를 우선하고 동률이면 플럭스 최대화로 탐색",
            [],
            [goal("meanIonEnergy", "minimize"), goal("ionFlux", "maximize")],
        ),
        (
            "압력 15 mTorr 이하에서 에너지 30~40 eV에 가깝게 찾아줘.",
            [constraint("pressure", "lte", 15, unit="mTorr")],
            [goal("meanIonEnergy", "target_range", 30, 40, "eV")],
        ),
        (
            "에너지 30~40 eV에 근접하는 것을 우선하고 다음으로 플럭스를 최대화해.",
            [],
            [goal("meanIonEnergy", "target_range", 30, 40, "eV"), goal("ionFlux", "maximize")],
        ),
        (
            "플럭스 최대화가 최우선이고 다음으로 에너지 30~40 eV에 가깝게",
            [],
            [goal("ionFlux", "maximize"), goal("meanIonEnergy", "target_range", 30, 40, "eV")],
        ),
        (
            "압력 3~8 mTorr 사이, 소스 300 W로 고정해서 후보 찾아줘.",
            [
                constraint("pressure", "between", low=3, high=8, unit="mTorr"),
                constraint("sourcePower", "eq", 300, unit="W"),
            ],
            [],
        ),
        (
            "바이어스 0 W와 같은 조건에서 이온 플럭스가 높은 Run을 찾아줘.",
            [constraint("biasPower", "eq", 0, unit="W")],
            [goal("ionFlux", "maximize")],
        ),
        ("에너지 0 eV 초과 조건만 만족하는 Run 검색", [constraint("meanIonEnergy", "gt", 0, unit="eV")], []),
        (
            "IED 폭 3~6 eV 범위 후보에서 플럭스를 최대화하고 싶어.",
            [constraint("iedWidth", "between", low=3, high=6, unit="eV")],
            [goal("ionFlux", "maximize")],
        ),
        (
            "source power at least 250 W and bias power above 50 W; minimize mean ion energy",
            [constraint("sourcePower", "gte", 250, unit="W"), constraint("biasPower", "gt", 50, unit="W")],
            [goal("meanIonEnergy", "minimize")],
        ),
        (
            "압력8mTorr이하 이온플럿스 최대인 후보 찾아줘",
            [constraint("pressure", "lte", 8, unit="mTorr")],
            [goal("ionFlux", "maximize")],
        ),
        (
            "에너지는30-40eV범위, 압력은10mTorr미만인 후보",
            [
                constraint("meanIonEnergy", "between", low=30, high=40, unit="eV"),
                constraint("pressure", "lt", 10, unit="mTorr"),
            ],
            [],
        ),
        (
            "플럭스 3 10¹⁸ m⁻²s⁻¹ 이하를 만족하면서 폭이 최소인 Run",
            [constraint("ionFlux", "lte", 3, unit="10¹⁸ m⁻²s⁻¹")],
            [goal("iedWidth", "minimize")],
        ),
        (
            "평균 이온 에너지 55 eV 초과이고 압력 20 mTorr 미만인 Run을 찾아줘.",
            [
                constraint("meanIonEnergy", "gt", 55, unit="eV"),
                constraint("pressure", "lt", 20, unit="mTorr"),
            ],
            [],
        ),
        (
            "이온 플럭스가 1.5 10¹⁸ m⁻²s⁻¹보다 크고 바이어스 100 W 이하인 Run",
            [
                constraint("ionFlux", "gt", 1.5, unit="10¹⁸ m⁻²s⁻¹"),
                constraint("biasPower", "lte", 100, unit="W"),
            ],
            [],
        ),
        (
            "압력 10 mTorr 이하가 아니라 10 mTorr 미만으로 플럭스 최대화 탐색해.",
            [constraint("pressure", "lt", 10, unit="mTorr")],
            [goal("ionFlux", "maximize")],
        ),
    ]
    for question, constraints_, goals_ in rows:
        add("reverse", question, "reverse_search", {"constraints": constraints_, "goals": goals_})
    for question, rule in [
        ("선택한 Run보다 에너지를 조금 더 높인 후보 찾아줘.", "energy_slightly_higher"),
        ("현재 선택한 Run 기준으로 에너지를 좀 올려줘.", "energy_slightly_higher"),
        ("선택한 Run의 플럭스는 유지하면서 IED 폭을 좁게 찾아줘.", "flux_maintained_and_width_lower"),
        (
            "Keep ion flux and lower IED width relative to the selected Run.",
            "flux_maintained_and_width_lower",
        ),
    ]:
        add(
            "reverse",
            question,
            "reverse_search",
            {"context_rules": [rule], "constraints": [], "goals": []},
            context_available={"selected_run": True},
        )
    add(
        "reverse",
        "에너지가 적당한 Run 찾아줘. 적당한 범위는 아직 정하지 않았어.",
        "reverse_search",
        clarification=True,
    )
    add(
        "reverse", "뭔가 좋은 후보를 찾고 싶은데 지표는 아직 못 골랐어.", "reverse_search", clarification=True
    )
    add("reverse", "전자 밀도를 최대화하는 Run을 찾아줘.", None, unsupported=True)
    add("reverse", "없는 조건의 실험 결과를 수치로 예측해서 후보 Run을 만들어줘.", None, unsupported=True)
    add(
        "reverse",
        "압력은 7 mTorr 이하, 소스는 200 W 이상, 바이어스는 80 W 이하이며 플럭스 최대인 후보",
        "reverse_search",
        {
            "constraints": [
                constraint("pressure", "lte", 7, unit="mTorr"),
                constraint("sourcePower", "gte", 200, unit="W"),
                constraint("biasPower", "lte", 80, unit="W"),
            ],
            "goals": [goal("ionFlux", "maximize")],
        },
    )

    # Compare: explicit role and metric order; values come only from real later lookups.
    compare_rows = [
        (
            "RUN-A를 기준으로 RUN-B의 에너지와 플럭스 차이 비교해줘.",
            "RUN-A",
            "RUN-B",
            ["meanIonEnergy", "ionFlux"],
        ),
        ("RUN-B 기준으로 RUN-A의 평균 이온 에너지 차이를 알려줘.", "RUN-B", "RUN-A", ["meanIonEnergy"]),
        ("RUN-C를 기준으로 RUN-D의 IED 폭 변화율을 계산해줘.", "RUN-C", "RUN-D", ["iedWidth"]),
        (
            "RUN-10을 기준으로 RUN-20의 플럭스와 에너지 순서로 비교해.",
            "RUN-10",
            "RUN-20",
            ["ionFlux", "meanIonEnergy"],
        ),
        ("Compare RUN-X against baseline RUN-Y for mean ion energy.", "RUN-Y", "RUN-X", ["meanIonEnergy"]),
        ("RUN-100을 기준으로 RUN-200의 이온 플럭스가 얼마나 달라?", "RUN-100", "RUN-200", ["ionFlux"]),
        ("RUN-E 기준 RUN-F의 폭과 플럭스를 비교해줘.", "RUN-E", "RUN-F", ["iedWidth", "ionFlux"]),
        (
            "RUN-G를 기준으로 RUN-H의 에너지, 플럭스, IED 폭 차이를 수치로 보여줘.",
            "RUN-G",
            "RUN-H",
            ["meanIonEnergy", "ionFlux", "iedWidth"],
        ),
        ("RUN-J 대비 RUN-K를 비교하되 기준은 RUN-J이고 플럭스만 볼게.", "RUN-J", "RUN-K", ["ionFlux"]),
        (
            "Use RUN-L as baseline and compare RUN-M for IED width and ion flux.",
            "RUN-L",
            "RUN-M",
            ["iedWidth", "ionFlux"],
        ),
        (
            "RUN-N을 기준으로 RUN-P의 에너지 차이만 계산하고 원인 설명은 빼줘.",
            "RUN-N",
            "RUN-P",
            ["meanIonEnergy"],
        ),
        ("RUN-Q가 기준이야. RUN-R의 플럭스 차이와 변화율을 알려줘.", "RUN-Q", "RUN-R", ["ionFlux"]),
        ("RUN-S 기준 RUN-T의 IED width 수치 비교", "RUN-S", "RUN-T", ["iedWidth"]),
        ("RUN-U를 기준 Run으로 삼고 RUN-V의 ion flux 차이를 구해줘.", "RUN-U", "RUN-V", ["ionFlux"]),
    ]
    for question, baseline, target, metrics in compare_rows:
        add(
            "compare",
            question,
            "compare_runs",
            {"baseline": selector(baseline), "target": selector(target), "metrics": metrics},
        )
    add(
        "compare",
        "RUN-A를 기준으로 RUN-B를 비교해줘.",
        "compare_runs",
        {"baseline": selector("RUN-A"), "target": selector("RUN-B")},
    )
    add(
        "compare",
        "기준 Run과 선택한 Run의 에너지 차이를 비교해줘.",
        "compare_runs",
        {
            "baseline": {"kind": "reference_run"},
            "target": {"kind": "selected_run"},
            "metrics": ["meanIonEnergy"],
        },
        context_available={"reference_run": True, "selected_run": True},
    )
    add(
        "compare",
        "방금 비교한 그 두 Run의 플럭스도 비교해줘.",
        "compare_runs",
        {
            "baseline": {"kind": "comparison_baseline"},
            "target": {"kind": "comparison_target"},
            "metrics": ["ionFlux"],
        },
        context_available={"comparison_pair": True},
    )
    add(
        "compare",
        "RUN-A 버전 synthetic-a-v1을 기준으로 RUN-B 버전 synthetic-b-v2의 플럭스를 비교해줘.",
        "compare_runs",
        {
            "baseline": selector("RUN-A", "synthetic-a-v1"),
            "target": selector("RUN-B", "synthetic-b-v2"),
            "metrics": ["ionFlux"],
        },
    )
    for question in [
        "이 두 Run 비교해줘. 어느 쪽을 기준으로 할지는 아직 정하지 않았어.",
        "RUN-A와 RUN-B를 비교하고 싶은데 기준은 나중에 고를게.",
        "선택한 Run의 플럭스를 다른 Run과 비교하고 싶어. 상대 Run은 아직 안 골랐어.",
        "기준 Run보다 얼마나 달라졌는지 알려줘. 대상 Run은 아직 없어.",
        "RUN-A 기준 RUN-B에서 어떤 지표를 볼지는 내가 아직 못 정했으니 먼저 물어봐줘.",
    ]:
        add("compare", question, "compare_runs", clarification=True)
    add("compare", "RUN-A 기준 RUN-B의 전자 밀도 차이를 계산해줘.", None, unsupported=True)
    add(
        "compare",
        "RUN-A 기준 RUN-B, RUN-C, RUN-D를 한 번에 수치 비교해줘.",
        "compare_runs",
        clarification=True,
    )

    # Explanation routing: general knowledge or observed comparison, never RAG.
    for question, baseline, target, metrics in [
        ("RUN-A를 기준으로 RUN-B의 플럭스가 왜 달라졌는지 설명해줘.", "RUN-A", "RUN-B", ["ionFlux"]),
        (
            "RUN-C를 기준으로 RUN-D의 평균 이온 에너지가 변한 이유가 궁금해.",
            "RUN-C",
            "RUN-D",
            ["meanIonEnergy"],
        ),
        ("RUN-E 기준 RUN-F의 IED 폭이 바뀐 가능한 이유를 설명해.", "RUN-E", "RUN-F", ["iedWidth"]),
        ("RUN-G 기준 RUN-H의 플럭스를 비교하고 그 이유도 설명해줘.", "RUN-G", "RUN-H", ["ionFlux"]),
        (
            "RUN-J를 기준으로 RUN-K의 에너지와 플럭스 변화 원인을 해석해줘.",
            "RUN-J",
            "RUN-K",
            ["meanIonEnergy", "ionFlux"],
        ),
        ("Why did ion flux change in RUN-X compared with baseline RUN-Y?", "RUN-Y", "RUN-X", ["ionFlux"]),
        (
            "RUN-10을 기준으로 RUN-20의 폭과 에너지 변화 이유를 알고 싶어.",
            "RUN-10",
            "RUN-20",
            ["iedWidth", "meanIonEnergy"],
        ),
        (
            "RUN-L을 기준으로 RUN-M의 에너지가 높아졌다는 내 생각이 맞는지 보고 이유를 설명해줘.",
            "RUN-L",
            "RUN-M",
            ["meanIonEnergy"],
        ),
        (
            "RUN-N 기준 RUN-P의 플럭스가 감소했다고 생각하는데 실제 비교 후 가능한 이유도 알려줘.",
            "RUN-N",
            "RUN-P",
            ["ionFlux"],
        ),
        ("RUN-Q를 기준으로 RUN-R의 IED 폭이 왜 이렇게 달라졌어?", "RUN-Q", "RUN-R", ["iedWidth"]),
        (
            "RUN-S 기준 RUN-T의 에너지 차이를 계산하고 물리적인 해석도 덧붙여줘.",
            "RUN-S",
            "RUN-T",
            ["meanIonEnergy"],
        ),
        (
            "RUN-U를 기준으로 RUN-V의 ion flux가 바뀐 원인을 가능한 수준으로 설명해.",
            "RUN-U",
            "RUN-V",
            ["ionFlux"],
        ),
    ]:
        add(
            "change",
            question,
            "explain_change",
            {"baseline": selector(baseline), "target": selector(target), "metrics": metrics},
        )
    add(
        "change",
        "기준 Run과 선택한 Run의 플럭스가 왜 달라?",
        "explain_change",
        {"baseline": {"kind": "reference_run"}, "target": {"kind": "selected_run"}, "metrics": ["ionFlux"]},
        context_available={"reference_run": True, "selected_run": True},
    )
    add(
        "change",
        "방금 비교한 결과가 왜 이렇게 달라졌어?",
        "explain_change",
        {"baseline": {"kind": "comparison_baseline"}, "target": {"kind": "comparison_target"}},
        context_available={"comparison_pair": True},
    )
    add(
        "change",
        "RUN-A 버전 synthetic-a-v1 기준 RUN-B 버전 synthetic-b-v2의 에너지 변화 이유를 설명해줘.",
        "explain_change",
        {
            "baseline": selector("RUN-A", "synthetic-a-v1"),
            "target": selector("RUN-B", "synthetic-b-v2"),
            "metrics": ["meanIonEnergy"],
        },
    )
    for question in [
        "이번 Run의 플럭스가 왜 달라졌어? 비교할 이전 Run은 지정하지 않았어.",
        "압력을 올렸더니 에너지가 바뀌었어. 관련된 Run을 아직 선택하지 않았는데 왜 그런지 설명해줘.",
        "RUN-A와 RUN-B의 변화 이유를 설명하고 싶은데 기준과 대상은 먼저 확인해줘.",
    ]:
        add("change", question, "explain_change", clarification=True)
    add(
        "change",
        "실행한 Run 없이 소스를 올릴 때 플럭스가 정확히 몇이 되는지 예측해서 설명해줘.",
        None,
        unsupported=True,
    )
    add(
        "change",
        "논문 URL을 직접 검색해서 RUN-A와 RUN-B의 변화 원인을 검증하고 인용해줘.",
        None,
        unsupported=True,
    )

    for question, topics, aspect in [
        ("이온 플럭스가 뭐야?", ["ionFlux"], "definition"),
        ("평균 이온 에너지의 의미를 설명해줘.", ["meanIonEnergy"], "definition"),
        ("IED 폭이라는 지표는 무엇을 뜻해?", ["iedWidth"], "definition"),
        ("IED 분포가 뭔지 개념만 알려줘.", ["ied"], "definition"),
        ("소스 전력이란 무엇인지 설명해.", ["sourcePower"], "definition"),
        ("바이어스 전력의 개념을 알고 싶어.", ["biasPower"], "definition"),
        ("플라즈마 공정에서 압력이 뜻하는 개념은?", ["pressure"], "definition"),
        ("전자 밀도의 정의가 궁금해.", ["electronDensity"], "definition"),
        ("전자 온도는 어떤 개념이야?", ["electronTemperature"], "definition"),
        ("쉬스가 뭔지 설명해줘.", ["sheath"], "definition"),
        ("플라즈마란 무엇이야?", ["plasma"], "definition"),
        ("이온 플럭스와 평균 이온 에너지는 어떻게 달라?", ["ionFlux", "meanIonEnergy"], "difference"),
        ("소스 전력과 바이어스 전력의 역할 차이를 알려줘.", ["sourcePower", "biasPower"], "difference"),
        ("전자 밀도와 전자 온도의 차이가 뭐야?", ["electronDensity", "electronTemperature"], "difference"),
        (
            "일반적으로 소스 전력과 이온 플럭스는 어떤 관계가 있어?",
            ["sourcePower", "ionFlux"],
            "relationship",
        ),
        (
            "바이어스 전력과 평균 이온 에너지의 일반적인 관계를 설명해줘.",
            ["biasPower", "meanIonEnergy"],
            "relationship",
        ),
        ("How are pressure and IED width generally related?", ["pressure", "iedWidth"], "relationship"),
        ("이온 플럿스라는 말의 뜻을 쉽게 설명해줘.", ["ionFlux"], "definition"),
    ]:
        add("concept", question, "explain_concept", {"topics": topics, "aspect": aspect})
    add(
        "concept", "그 개념 설명해줘. 어떤 개념인지는 아직 말 안 했어.", "explain_concept", clarification=True
    )
    add("concept", "전자기학 수식을 유도하고 구체적인 숫자 예제로 계산해줘.", None, unsupported=True)
    assert len(cases) == 140, len(cases)
    assert len({case.question for case in cases}) == 140
    return cases


CASES = build_cases()
