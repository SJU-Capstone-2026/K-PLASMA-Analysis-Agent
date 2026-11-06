"""Human-authored semantic pairs. All Run identities and data are artificial."""

from copy import deepcopy
from dataclasses import dataclass

from kplasma_agent.v2.contracts import PlanDraft


@dataclass
class ReviewCase:
    id: str
    question: str
    good: PlanDraft
    bad: PlanDraft
    context: dict


def literal(value, unit, question):
    return {"kind": "literal", "value": value, "unit": unit,
            "source": {"message_key": "question", "quote": question}}


def constraint(field, operator, value, unit, question):
    return {"field": field, "operator": operator, "value": literal(value, unit, question)}


def interval(low, high, question):
    return {"field": "meanIonEnergy", "operator": "between",
            "min": literal(low, "eV", question), "max": literal(high, "eV", question)}


def result_ref(step, field="candidates", kind="candidate_group"):
    return {"kind": "result_ref", "step_id": step, "field": field, "scope": {"kind": kind}}


def search(constraints, *, id="search", goals=None):
    return {"id": id, "kind": "tool", "tool": "reverse_search",
            "inputs": {"constraints": constraints, "goals": goals or []}}


def compare(ref, fields=None, depends=None):
    return {"id": "compare", "kind": "tool", "tool": "compare_runs", "depends_on": depends or [],
            "inputs": {"runs": ref, "fields": fields or ["pressure"]}}


def selected_context():
    entries = [{"key": f"R{i}", "ref": {"runId": f"SYN-{i}", "runVersionId": f"fixed-{i}"},
                "origin": {"kind": "run_tag"}} for i in (1, 2)]
    return {"selected_runs": [e["ref"] for e in entries], "comparison_entries": entries,
            **{e["key"]: e["ref"] for e in entries}}


def plan(question, steps):
    return PlanDraft.model_validate({"schema_version": 1, "request_mode": "data_request", "base_revision": None,
        "requirements": [{"id": "r", "text": question, "handled_by": [s["id"] for s in steps],
                          "sources": [{"message_key": "question", "quote": question}]}],
        "steps": [{**s, "requirement_ids": ["r"]} for s in steps]})


def nested(question, energy=False):
    measurement = compare({"kind": "context_ref", "key": "selected_runs"}, ["ionFlux"])
    calculation = {"id": "threshold", "kind": "derive", "operation": "max", "depends_on": ["compare"],
                   "requires": [{"step_id": "compare", "field": "ionFlux", "count": 2}],
                   "inputs": {"values": {"kind": "result_ref", "step_id": "compare", "field": "ionFlux",
                                          "scope": {"kind": "context_selection", "key": "selected_runs"}}}}
    query = search([{"field": "ionFlux", "operator": "gt", "value": result_ref("threshold", "value", "scalar")},
                    *([interval(150, 160, question)] if energy else [])])
    query["depends_on"] = ["threshold"]
    return [measurement, calculation, query]


def cases():
    bank = []

    def pair(id, question, steps, change, *, selected=False):
        bad = deepcopy(steps)
        change(bad)
        bank.append(ReviewCase(id, question, plan(question, steps), plan(question, bad),
                               selected_context() if selected else {}))

    q = "선택한 두 Run의 플럭스를 비교하고, 두 Run 모두보다 플럭스가 높고 평균 이온 에너지가 150–160 eV인 Run을 찾아줘."
    pair("P01", q, nested(q, True), lambda s: s[-1]["inputs"]["constraints"].__setitem__(1,
         constraint("meanIonEnergy", "gt", 0, "eV", q)), selected=True)

    q = "평균 이온 에너지가 150–160 eV인 모든 실제 Run의 IEAD 최대 강도와 피크 에너지·각도를 비교해줘."
    comparison = compare(result_ref("search"), ["iead.maximum", "iead.peakEnergy", "iead.peakAngle"], ["search"])
    comparison["inputs"]["plot_ids"] = ["iead"]
    pair("P02", q, [search([interval(150, 160, q)]), comparison],
         lambda s: s[0]["inputs"].__setitem__("constraints", [constraint("meanIonEnergy", "eq", 0, "eV", q)]))

    q = "평균 이온 에너지가 9999–10000 eV인 실제 Run을 모두 찾아줘."
    pair("P03", q, [search([interval(9999, 10000, q)])],
         lambda s: s[0]["inputs"].__setitem__("constraints", [constraint("meanIonEnergy", "eq", 9999, "eV", q)]))

    q = "압력이 8 mTorr 이상이며 이온 플럭스가 50 이상인 Run을 모두 찾아줘."
    pair("P04", q, [search([constraint("pressure", "gte", 8, "mTorr", q),
                           constraint("ionFlux", "gte", 50, None, q)])],
         lambda s: s[0]["inputs"]["constraints"].pop(0))

    q = "이온 플럭스가 50 이상인 Run을 모두 찾아줘."
    pair("P05", q, [search([constraint("ionFlux", "gte", 50, None, q)])],
         lambda s: s[0]["inputs"]["constraints"][0].__setitem__("operator", "gt"))

    q = "압력이 0.008 Torr인 실제 Run을 찾아줘."
    pair("P06", q, [search([constraint("pressure", "eq", 0.008, "Torr", q)])],
         lambda s: s[0]["inputs"]["constraints"][0]["value"].__setitem__("value", 8))

    q = "선택한 두 Run 모두보다 이온 플럭스가 높은 후보를 찾아줘."
    pair("P07", q, nested(q), lambda s: s[1].__setitem__("operation", "mean"), selected=True)

    q = "이온 플럭스가 50 이상인 Run을 모두 찾고 검색 결과 전체의 압력을 비교해줘."
    pair("P08", q, [search([constraint("ionFlux", "gte", 50, None, q)]),
                     compare(result_ref("search"), depends=["search"])],
         lambda s: s[1]["inputs"].__setitem__("runs", {"kind": "context_ref", "key": "selected_runs"}), selected=True)

    q = "이온 플럭스 50 이상인 후보를 찾아줘. 그중 두 개는 내가 고를 테니 압력을 비교해줘."
    choose = {"id": "choose", "kind": "await_input", "confirmation": "run_selection", "depends_on": ["search"],
              "inputs": {"target_step_id": "compare", "field": "runs", "selection_count": 2,
                         "candidates": result_ref("search")}}
    def skip_choice(steps):
        steps.pop(1)
        steps[-1]["depends_on"] = ["search"]
        steps[-1]["inputs"]["runs"] = result_ref("search")
    pair("P09", q, [search([constraint("ionFlux", "gte", 50, None, q)]), choose,
                     compare(result_ref("choose", "selection", "scalar"), depends=["choose"])], skip_choice)

    q = "평균 이온 에너지가 150–160 eV인 범위 안에서 이온 플럭스 높은 순으로 후보를 찾아줘."
    pair("P10", q, [search([interval(150, 160, q)], goals=[{"field": "ionFlux", "direction": "maximize"}])],
         lambda s: s[0]["inputs"]["goals"][0].__setitem__("direction", "minimize"))

    q = "선택한 두 Run의 압력을 기준 대비 비교해줘. 기준 Run은 내가 직접 고를 테니 먼저 선택하게 해줘."
    baseline = {"id": "baseline", "kind": "await_input", "confirmation": "baseline",
                "inputs": {"target_step_id": "compare", "field": "baseline"}}
    def pick_baseline(steps):
        steps.pop(0)
        steps[0]["depends_on"] = []
        steps[0]["inputs"]["baseline"] = {"kind": "context_ref", "key": "R1"}
    pair("P11", q, [baseline, compare({"kind": "context_ref", "key": "selected_runs"}, depends=["baseline"])],
         pick_baseline, selected=True)

    q = "평균 이온 에너지가 140–149 eV인 Run과 150–160 eV인 Run을 각각 찾아줘."
    def intersect_groups(steps):
        steps[0]["inputs"]["constraints"].extend(steps.pop(1)["inputs"]["constraints"])
    pair("P12", q, [search([interval(140, 149, q)], id="low"), search([interval(150, 160, q)], id="high")],
         intersect_groups)

    q = "평균 이온 에너지가 150–160 eV인 Run을 이온 플럭스 높은 순으로 찾아줘. 그중 정확히 두 개는 내가 고를 테니 압력을 비교해줘. 비교 기준도 내가 고를게."
    choose["depends_on"] = ["search"]
    baseline["depends_on"] = ["choose"]
    pair("P13", q, [search([constraint("meanIonEnergy", "gte", 150, "eV", q),
                            constraint("meanIonEnergy", "lte", 160, "eV", q)],
                           goals=[{"field": "ionFlux", "direction": "maximize"}]),
                    choose, baseline,
                    compare(result_ref("choose", "selection", "scalar"), depends=["choose", "baseline"])],
         lambda s: s[1]["inputs"].__setitem__("selection_count", 3), selected=True)
    bank[-1].context["baseline"] = "R2"
    return bank
