"""Fixed artificial data and human-authored expectations for Graph v2."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from kplasma_agent.metric_registry import UNITS


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    tools: tuple[str, ...]
    candidate_groups: tuple[tuple[str, ...], ...] = ()
    derivations: tuple[str, ...] = ()
    repeated: bool = False
    selected: bool = False
    blocked: bool = False
    comparisons: tuple[str, ...] = ()
    predicates: tuple[tuple[str, str, float], ...] = ()


def runs():
    return [
        {"runId": run, "runVersionId": str(uuid5(NAMESPACE_URL, "v2-eval:" + run)),
         "pressure": pressure, "sourcePower": 300, "biasPower": 600, "units": dict(UNITS),
         "metrics": {"ionFlux": flux, "meanIonEnergy": energy, "iedWidth": width},
         "qualityStatus": "VERIFIED", "convergenceStatus": "CONVERGED", "catalogStatus": "READY"}
        for run, pressure, flux, energy, width in (
            ("SYN-A", 4, 10, 30, 8), ("SYN-B", 6, 20, 40, None),
            ("SYN-C", 8, 20, 50, 6), ("SYN-D", 10, 40, 60, 4),
        )
    ]


S = "reverse_search"
F = "forward_lookup"
C = "compare_runs"
CASES = (
    Case("concept-ied", "IED가 뭐야? 이온 에너지 분포 개념을 쉽게 설명해줘.", ()),
    Case("concept-flux", "이온 플럭스와 이온 에너지의 개념 차이를 설명해줘.", ()),
    Case("forward-a", "압력 4 mTorr, 소스 300 W, 바이어스 600 W 조건의 Run을 찾아줘.", (F,), (("SYN-A",),)),
    Case("forward-c", "압력 8 mTorr, 소스 300 W, 바이어스 600 W 결과를 보여줘.", (F,), (("SYN-C",),)),
    Case("flux-over-20", "이온 플럭스가 20보다 큰 실제 Run을 모두 찾아줘.", (S,), (("SYN-D",),),
         repeated=True, predicates=(("ionFlux", "gt", 20),)),
    Case("flux-at-least-20", "이온 플럭스가 20 이상인 실제 Run을 모두 찾아줘.", (S,), (("SYN-B", "SYN-C", "SYN-D"),),
         predicates=(("ionFlux", "gte", 20),)),
    Case("flux-under-20", "이온 플럭스가 20 미만인 실제 Run을 모두 찾아줘.", (S,), (("SYN-A",),),
         predicates=(("ionFlux", "lt", 20),)),
    Case("flux-20-exact", "이온 플럭스가 정확히 20인 Run을 찾아줘.", (S,), (("SYN-B", "SYN-C"),),
         predicates=(("ionFlux", "eq", 20),)),
    Case("energy-range", "평균 이온 에너지가 40~50 eV 범위인 실제 Run을 모두 보여줘.", (S,), (("SYN-B", "SYN-C"),)),
    Case("no-match", "이온 플럭스가 100보다 큰 Run을 모두 찾아줘.", (S,), ((),),
         repeated=True, predicates=(("ionFlux", "gt", 100),)),
    Case("width-strict", "IED 폭이 6 eV보다 좁은 실제 Run을 찾아줘.", (S,), (("SYN-D",),)),
    Case("torr-pressure", "압력이 0.008 Torr와 같은 실제 Run을 찾아줘.", (S,), (("SYN-C",),)),
    Case("two-filters", "이온 플럭스 20 이상이고 평균 이온 에너지가 50 eV보다 작은 Run을 찾아줘.",
         (S,), (("SYN-B",),)),
    Case("independent", "이온 플럭스가 15 미만인 후보와 평균 이온 에너지가 55 eV 초과인 후보를 각각 찾아줘.",
         (S, S), (("SYN-A",), ("SYN-D",)), repeated=True),
    Case("compare-flux", "선택한 두 Run의 이온 플럭스 값을 비교해줘.", (C,), selected=True, comparisons=("ionFlux",)),
    Case("compare-energy", "선택한 두 Run의 평균 이온 에너지를 비교해줘.", (C,), selected=True,
         comparisons=("meanIonEnergy",)),
    Case("compare-missing", "선택한 두 Run의 IED 폭을 비교하고 값이 없으면 알려줘.", (C,), selected=True,
         repeated=True, comparisons=("iedWidth",)),
    Case("nested-max", "선택한 두 Run 모두보다 이온 플럭스가 높은 후보를 찾아줘.", (C, S), (("SYN-D",),), ("max",),
         repeated=True, selected=True, comparisons=("ionFlux",), predicates=(("ionFlux", "gt", 20),)),
    Case("nested-mean", "선택한 두 Run의 이온 플럭스 평균보다 높은 후보를 모두 찾아줘.", (C, S),
         (("SYN-B", "SYN-C", "SYN-D"),), ("mean",), repeated=True, selected=True, comparisons=("ionFlux",),
         predicates=(("ionFlux", "gt", 15),)),
    Case("nested-min", "선택한 두 Run 모두보다 이온 플럭스가 낮은 후보를 찾아줘.", (C, S), ((),), ("min",),
         repeated=True, selected=True, comparisons=("ionFlux",), predicates=(("ionFlux", "lt", 10),)),
    Case("nested-missing", "선택한 두 Run 모두보다 IED 폭이 좁은 후보를 찾아줘.", (C, S), (), ("min",),
         repeated=True, selected=True, blocked=True, comparisons=("iedWidth",)),
    Case("mixed", "이온 플럭스가 20보다 큰 실제 Run을 찾고, 이온 플럭스가 어떤 개념인지도 설명해줘.",
         (S,), (("SYN-D",),), predicates=(("ionFlux", "gt", 20),)),
    Case("concept-with-tags", "이온 플럭스의 정의만 쉽게 설명해줘.", (), selected=True),
    Case("energy-high", "평균 이온 에너지가 50 eV 이상인 실제 Run을 모두 찾아줘.", (S,), (("SYN-C", "SYN-D"),)),
)
