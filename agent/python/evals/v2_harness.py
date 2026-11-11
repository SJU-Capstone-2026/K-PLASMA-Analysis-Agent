"""Score a real graph on artificial data with isolated in-memory journals."""

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from time import monotonic

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from kplasma_agent.domain.common import run_ref
from kplasma_agent.graphs.v2 import build_v2_graph

from .v2_cases import Case, runs


class EvaluationJournal:
    def __init__(self, source, records=()):
        self.source = source
        self.records = list(records)  # artificial decision records only
        self.steps = {}
        self.models = {}
        self.revisions = []

    def accept_plan(self, plan):
        self.revisions.append(plan.model_dump(mode="json"))
        return {"revision": len(self.revisions), "plan": self.revisions[-1]}

    def start_step(self, revision, step_id, inputs):
        key = f"execution-{revision}-{step_id}"
        if key in self.steps:
            return {"executionId": key, "callAllowed": False, "result": self.steps[key]["result"]}
        self.steps[key] = {"inputs": deepcopy(inputs), "result": None}
        return {"executionId": key, "callAllowed": True}

    def load_context(self, execution):
        wanted = self.steps[execution]["inputs"].get("runs")
        return deepcopy([r for r in self.source if not wanted or run_ref(r) in wanted])

    def decision_records(self, execution):
        return deepcopy(self.records)

    def comparison_outputs(self, execution, refs, plots):
        return []

    def save_result(self, result):
        self.steps[result.executionId]["result"] = result.model_dump(mode="json")
        return {"result": self.steps[result.executionId]["result"]}

    def reserve_model(self, kind, key):
        if key in self.models:
            return {"attemptId": key, "callAllowed": False, "outcome": self.models[key]["outcome"]}
        self.models[key] = {"kind": kind, "outcome": None}
        return {"attemptId": key, "callAllowed": True}

    def complete_model(self, attempt_id, outcome):
        self.models[attempt_id]["outcome"] = outcome
        return {"outcome": outcome}


class TimedModels:
    """Measure provider calls without changing the graph's durable call counts."""

    def __init__(self, models):
        self.models = models
        self.calls = []

    def __getattr__(self, name):
        value = getattr(self.models, name)
        if name not in {"submit_plan", "review_plan", "compose", "stream_compose", "review"}:
            return value

        def timed(*args, **kwargs):
            start = monotonic()
            try:
                return value(*args, **kwargs)
            finally:
                self.calls.append({"method": name, "seconds": monotonic() - start})
        return timed


def evaluate_case(case: Case, models, *, plan_review_enabled=True) -> dict:
    source = runs()
    journal = EvaluationJournal(source)
    entries = [{"ref": run_ref(run), "key": f"R{i}", "origin": {"kind": "run_tag"}}
               for i, run in enumerate(source[:2], start=1)] if case.selected else []
    timed = TimedModels(models)
    graph = build_v2_graph(timed, journal, InMemorySaver())
    config = {"configurable": {"thread_id": case.id}, "recursion_limit": 80}
    start = monotonic()
    try:
        state = graph.invoke({"request_id": case.id, "question": case.question,
                              "context": {"comparisonReference": {"entries": entries, "baselineKey": None}},
                              "input_history": [], "plan_review_enabled": plan_review_enabled}, config)
        interrupted = bool(state.get("__interrupt__"))
        if interrupted and case.blocked:
            state = graph.invoke(Command(resume={"type": "text", "text": "부분 결과로 마치기"}), config)
        snapshot = state.get("answer", {}).get("answerSnapshot", {})
        first = next(iter(journal.models.values()), {}).get("outcome") or {}
        plan = first.get("data") or {}
        failures = score_case(case, plan, snapshot, journal.steps, interrupted)
        return {"case": case.id, "question": case.question, "expected": asdict(case), "pass": not failures,
                "failures": failures, "plan": plan, "snapshot": snapshot,
                "seconds": monotonic() - start, **evaluation_details(journal, timed, state, plan_review_enabled)}
    except Exception as exc:
        return {"case": case.id, "question": case.question, "pass": False,
                "failures": {"execution": [f"runtime:{type(exc).__name__}"]},
                "seconds": monotonic() - start, **evaluation_details(journal, timed, {}, plan_review_enabled)}


def evaluation_details(journal, timed, state, enabled):
    metrics = {}
    for attempt, call in zip(journal.models.values(), timed.calls):
        metric = metrics.setdefault(attempt["kind"], {"calls": 0, "seconds": 0})
        metric["calls"] += 1
        metric["seconds"] += call["seconds"]
    reviews = [(item.get("outcome") or {}).get("data") for item in journal.models.values()
               if item["kind"] == "PLAN_REVIEW"]
    if not enabled and state.get("plan_review"):
        reviews.append(state["plan_review"])
    return {"model_attempts": list(journal.models.values()), "accepted_plans": journal.revisions,
            "plan_reviews": reviews, "plan_review_enabled": enabled,
            "replans": state.get("replans", 0), "stage_metrics": metrics}


def score_case(case, plan, snapshot, steps, interrupted):
    failures: dict[str, list[str]] = {}

    def fail(phase, reason):
        failures.setdefault(phase, []).append(reason)

    planned = plan.get("steps") or []
    tools = tuple(s["tool"] for s in planned if s.get("kind") == "tool")
    operations = tuple(s["operation"] for s in planned if s.get("kind") == "derive")
    if Counter(tools) != Counter(case.tools):
        fail("first_plan", "tool set differs")
    if operations != case.derivations:
        fail("first_plan", "derived operation differs")
    if plan.get("request_mode") != ("data_request" if case.tools else "general_only"):
        fail("first_plan", "request mode differs")

    results = snapshot.get("stepResults", [])
    found = [s["outputs"]["toolResult"] for s in results if "toolResult" in s["outputs"]]
    if case.blocked:
        if not interrupted or any(r["kind"] == "reverse_search" for r in found):
            fail("execution", "missing value did not block dependent search")
        if snapshot.get("executionStatus") != "PARTIAL":
            fail("answer", "missing value not reported as partial")
    elif Counter(r["kind"] for r in found) != Counter(case.tools):
        fail("execution", "executed tool set differs")
    if not snapshot.get("answer"):
        fail("answer", "no displayed answer")
    review_status = snapshot.get("review", {}).get("status")
    has_interpretations = bool((snapshot.get("draft") or {}).get("interpretations"))
    if has_interpretations and review_status not in {"PASS", "ISSUE"}:
        fail("review", "interpretation review unavailable")
    if not has_interpretations and review_status != "SKIPPED":
        fail("review", "answer without interpretations did not skip review")
    if not case.blocked and snapshot.get("executionStatus") != "COMPLETE":
        fail("answer", "answer is not complete")

    groups = []
    for result in found:
        if result["kind"] == "reverse_search":
            groups.append(tuple(sorted(result["commonRunIds"])))
        elif result["kind"] == "forward_lookup":
            groups.append(tuple(sorted(r["runId"] for r in result["usedRunRefs"])))
    if Counter(groups) != Counter(case.candidate_groups):
        fail("execution", "candidate groups differ")
    for field in case.comparisons:
        if not any(field in r.get("metricIds", []) for r in found if r["kind"] == "compare_runs"):
            fail("execution", f"missing comparison field: {field}")
    for metric, operator, value in case.predicates:
        if not any(row.get("metric") == metric and row.get("operator") == operator and row.get("value") == value
                   for step in steps.values() for row in step["inputs"].get("constraints", [])):
            fail("execution", f"missing {metric} {operator} {value}")
    if case.tools and not any(key in failures for key in ("execution", "answer")):
        draft = snapshot.get("draft")
        if case.candidate_groups and draft and not any(
            identifier.endswith(":candidates") for identifier in draft.get("fact_ids", [])
        ):
            fail("answer", "verified candidate facts omitted from displayed text")
    return failures
