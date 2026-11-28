"""Deterministic first-plan grading for the automatic-improvement dataset."""

from collections import Counter
from itertools import permutations
import json
from pathlib import Path
import re

from pydantic import ValidationError

from kplasma_agent.v2.contracts import PlanDraft
from kplasma_agent.v2.plan_validation import InvalidPlan, validate_plan

from . import flow_grader

SPLIT_COUNTS = {
    "learning": {1: 10, 2: 20, 3: 35, 4: 35},
    "evaluation": {1: 5, 2: 10, 3: 17, 4: 18},
}


def step_kind(step):
    return step.get("tool", step["kind"])


def binding_signature(value, names, *, metric=None):
    if value is None:
        return None
    kind = value["kind"]
    if kind == "literal":
        if metric is not None:
            return ("literal", flow_grader.canonical(metric, value["value"], value["unit"]))
        return ("literal", value["value"])
    if kind == "context_ref":
        key = value["key"]
        return ("context", "selected_runs" if key == "comparison_entries" else key)
    scope = value["scope"]
    scope_key = names[scope["step_id"]] if "step_id" in scope else scope.get("key")
    return ("result", names[value["step_id"]], value["field"], scope["kind"], scope_key)


def search_signature(inputs, names):
    literals, references = [], []
    for condition in inputs["constraints"]:
        field = condition["field"]
        operator = condition["operator"]
        bounds = ("min", "max") if operator == "between" else ("value",)
        bindings = [binding_signature(condition[key], names, metric=field) for key in bounds]
        if any(binding[0] != "literal" for binding in bindings):
            references.append((field, operator, *bindings))
            continue
        literals.append({"field": field, "operator": operator,
                         **{key: binding[1] for key, binding in zip(bounds, bindings, strict=True)}})
    intervals = {field: [None if isinstance(value, float) and abs(value) == float("inf") else value
                         for value in flow_grader.interval(literals, field)]
                 for field in sorted({item["field"] for item in literals})}
    goals = [(goal["field"], goal["direction"],
              binding_signature(goal["min"], names, metric=goal["field"]),
              binding_signature(goal["max"], names, metric=goal["field"])) for goal in inputs["goals"]]
    return {"literalFilters": intervals, "referencedFilters": sorted(references, key=repr), "goals": goals}


def step_signature(step, names, selected):
    inputs = step["inputs"]
    kind = step_kind(step)
    if kind == "forward_lookup":
        return {key: binding_signature(inputs[key], names, metric=metric) for key, metric in (
            ("pressure", "pressure"), ("source_power", "sourcePower"), ("bias_power", "biasPower"))}
    if kind == "reverse_search":
        return search_signature(inputs, names)
    if kind == "compare_runs":
        return {"runs": binding_signature(inputs["runs"], names),
                "fields": sorted(inputs["fields"]), "plots": sorted(inputs["plot_ids"]),
                "baseline": binding_signature(inputs["baseline"], names),
                "trendAxis": binding_signature(inputs["trend_axis"], names)}
    if kind == "await_input":
        return {"confirmation": step["confirmation"], "count": inputs["selection_count"],
                "target": (names[inputs["target_step_id"]], inputs["field"]),
                "candidates": binding_signature(inputs["candidates"], names)}
    if kind == "derive":
        values = inputs["values"] if isinstance(inputs["values"], list) else [inputs["values"]]
        sources = []
        for value in values:
            signature = binding_signature(value, names)
            if signature[0] == "result" and signature[3:] == ("context_selection", "selected_runs"):
                sources.extend((*signature[:3], "confirmed_run", key) for key in selected)
            else:
                sources.append(signature)
        if step["operation"] in {"min", "max", "mean"}:
            sources.sort(key=repr)
        return {"operation": step["operation"], "values": sources, "direction": inputs["direction"]}
    return {"mode": inputs["mode"]}


def restrictions(step, names):
    """Detect gates that can block complete candidate sets or fabricate cardinality."""
    result = []
    for requirement in step["requires"]:
        if requirement["field"] == "candidates" and requirement["count"] is not None:
            result.append((names[requirement["step_id"]], "exact_count", requirement["count"]))
        if requirement["field"] in {"candidates", "selection"} and (
            requirement["unit"] is not None or requirement["value_type"] in {"quantity", "quantities"}
        ):
            result.append((names[requirement["step_id"]], "invalid_run_reference_requirements",
                           requirement["value_type"], requirement["unit"]))
    for condition in step["run_if"]:
        operator = condition["operator"]
        value = condition["value"]
        if condition["field"] == "candidate_count" and not (
            (operator == "gte" and value <= 2) or (operator == "gt" and value < 2)
        ):
            result.append((names[condition["step_id"]], "candidate_count", operator, value))
        if condition["field"] == "status" and (operator != "eq" or value != "verified"):
            result.append((names[condition["step_id"]], "step_status", operator, value))
    return sorted(result, key=repr)


def structural_view(case, raw, *, initial):
    plan = PlanDraft.model_validate(raw)
    selected = {f"R{index}" for index in range(1, len(case.get("selected", [])) + 1)}
    context = selected | {"selected_runs", "comparison_entries"}
    if case.get("baseline"):
        context |= {"baseline", "activeRun"}
    normalized = validate_plan(plan, messages={"question": case["question"]}, context_keys=context,
                               base_revision=None if initial else plan.base_revision,
                               selected_run_keys=selected)
    prepared = {step.id: step.model_dump(mode="json") for step in normalized.steps}
    # Mirror only the option bindings that the runtime itself rewrites before execution.
    original = plan.model_dump(mode="json")
    for step in original["steps"]:
        if step["id"] not in prepared:
            continue
        normalized_inputs = prepared[step["id"]]["inputs"]
        if step_kind(step) == "compare_runs":
            for key in ("baseline", "trend_axis"):
                step["inputs"][key] = normalized_inputs[key]
        elif step.get("confirmation") in {"baseline", "trend_axis"}:
            step["inputs"]["candidates"] = normalized_inputs["candidates"]
    return original, sorted(selected)


def grade_plan(case, raw, *, initial=True):
    if raw is None:
        return {"pass": False, "failures": [{"check": "plan_missing"}]}
    try:
        plan, selected = structural_view(case, raw, initial=initial)
        wanted, _ = structural_view(case, case["referencePlan"], initial=True)
    except (ValidationError, InvalidPlan, ValueError) as error:
        return {"pass": False, "failures": [{"check": "invalid_plan", "detail": str(error)[:900]}]}

    failures = []
    if plan["request_mode"] != wanted["request_mode"]:
        failures.append({"check": "request_mode", "expected": wanted["request_mode"], "actual": plan["request_mode"]})
    expected_kinds = Counter(map(step_kind, wanted["steps"]))
    actual_kinds = Counter(map(step_kind, plan["steps"]))
    if expected_kinds != actual_kinds:
        failures.append({"check": "step_kinds", "expected": dict(expected_kinds), "actual": dict(actual_kinds)})
        return {"pass": False, "failures": failures}

    # Match logical steps by their input provenance. IDs and independent step order may differ.
    expected_steps = wanted["steps"]
    expected_names = {step["id"]: step["id"] for step in expected_steps}
    closest = None
    for ordered in permutations(plan["steps"]):
        pairs = list(zip(expected_steps, ordered, strict=True))
        if any(step_kind(expect) != step_kind(actual) for expect, actual in pairs):
            continue
        names = {actual["id"]: expect["id"] for expect, actual in pairs}
        differences = []
        for expect, actual in pairs:
            try:
                left = step_signature(expect, expected_names, selected)
                right = step_signature(actual, names, selected)
            except (TypeError, ValueError, KeyError) as error:
                differences.append({"check": "invalid_binding", "step": expect["id"], "detail": str(error)})
                continue
            for key, expected_value in left.items():
                if right[key] != expected_value:
                    differences.append({"check": key, "step": expect["id"],
                                        "expected": expected_value, "actual": right[key]})
            unexpected = restrictions(actual, names)
            if unexpected:
                differences.append({"check": "unexpected_execution_gate", "step": expect["id"], "actual": unexpected})
        if closest is None or len(differences) < len(closest):
            closest = differences
        if not differences:
            break
    failures.extend(closest or [])
    return {"pass": not failures, "failures": failures}


def load_sets(dataset, oracle):
    splits = {}
    seen_ids, seen_questions = set(), set()
    for split, counts in SPLIT_COUNTS.items():
        path = Path(dataset) / f"{split}.json"
        cases = json.loads(path.read_text())
        if Counter(case["steps"] for case in cases) != counts:
            raise ValueError(f"{split}: incorrect step distribution")
        prefix = split[0].upper()
        for case in cases:
            if not re.fullmatch(rf"{prefix}{case['steps']}[0-9]{{2}}", case["id"]):
                raise ValueError(f"{split}: invalid case ID")
            question = " ".join(case["question"].split())
            if not question or question in seen_questions or case["id"] in seen_ids:
                raise ValueError(f"{case['id']}: duplicate ID or question")
            if (case["sourceOracle"] != {"catalogCount": len(oracle["byId"]), "files": oracle["hashes"]}
                    or len(case["referencePlan"]["steps"]) != case["steps"]
                    or any(run not in oracle["byId"] for run in case["selected"])
                    or (case["baseline"] and case["baseline"] not in case["selected"])):
                raise ValueError(f"{case['id']}: invalid case context or frozen catalog")
            if not grade_plan(case, case["referencePlan"])["pass"]:
                raise ValueError(f"{case['id']}: reference plan fails deterministic grading")
            for search in case["expected"]["searches"]:
                if search["runIds"] != flow_grader.matching_ids(search, oracle):
                    raise ValueError(f"{case['id']}: search expectations do not match frozen catalog")
            seen_ids.add(case["id"])
            seen_questions.add(question)
        splits[split] = cases
    return splits


def first_plan_grade(case, attempts):
    initial = [row for row in attempts if row["kind"] == "PLAN_INITIAL"]
    if len(initial) != 1:
        return {"pass": False, "failures": [{"check": "initial_attempt_count", "actual": len(initial)}]}
    outcome = initial[0].get("outcome") or {}
    return {"attemptId": initial[0]["id"], "modelError": outcome.get("error"),
            **grade_plan(case, outcome.get("data"))}


def verify_graph_review(settings, cases):
    """Read the real graph's state at the review boundary without using a provider."""
    from langgraph.checkpoint.memory import InMemorySaver

    from kplasma_agent.graphs.v2 import build_v2_graph

    from .v2_harness import EvaluationJournal

    if settings.plan_review_enabled is not True:
        raise ValueError("Plan review is disabled in the model configuration")
    case = next(case for case in cases if case["expected"]["general"])

    class Probe:
        def __init__(self, configuration):
            self.settings = configuration

        def submit_plan(self, _context):
            return case["referencePlan"], None

    config = {"configurable": {"thread_id": "review-state-preflight"}}
    graph = build_v2_graph(Probe(settings), EvaluationJournal([]), InMemorySaver())
    graph.invoke({"request_id": "review-state-preflight", "question": case["question"], "context": {},
                  "input_history": []}, config, interrupt_before=["review_plan"])
    state = graph.get_state(config)
    if state.values.get("plan_review_enabled") is not True or "review_plan" not in state.next:
        raise ValueError("Could not verify the graph's plan review state")
    return True


def summarize(rows):
    def counts(items):
        return {"trials": len(items),
                "firstPlanPass": sum(row["firstPlan"]["pass"] for row in items),
                "finalDeterministicPass": sum(row["grade"]["pass"] for row in items),
                "wrongFirstPlanThenDecisionsReplanPass": sum(
                    not row["firstPlan"]["pass"] and row["recovery"]["decisionsReplanRecovered"] for row in items),
                "wrongFirstPlanThenOtherReplanPass": sum(
                    not row["firstPlan"]["pass"] and row["recovery"]["category"] == "passed_after_other_replan"
                    for row in items),
                "decisionsFlagged": sum(row["recovery"]["decisionsCaughtIssue"] for row in items),
                "finalDeterministicFail": sum(not row["grade"]["pass"] for row in items)}

    return {
        **counts(rows),
        "primaryMetric": "firstPlanPass",
        "bySteps": {str(size): counts([row for row in rows if row["steps"] == size]) for size in range(1, 5)},
        "firstPlanFailedChecks": dict(Counter(
            check["check"] for row in rows for check in row["firstPlan"]["failures"])),
        "answerReviewRequired": sum(row["grade"]["answerReviewRequired"] for row in rows),
    }
