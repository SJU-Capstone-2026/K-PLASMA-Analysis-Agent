"""Score a real graph on artificial data with isolated in-memory journals."""

from collections import Counter
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from dataclasses import asdict
from importlib import import_module
from time import monotonic
from types import SimpleNamespace

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from kplasma_agent.domain.common import run_ref

from .v2_cases import Case, runs

GRAPH_VERSIONS = ("v2", "v2_localLLM")


def runtime_for_version(graph_version="v2"):
    """Select an owned implementation; unknown versions never fall back."""
    if graph_version not in GRAPH_VERSIONS:
        raise ValueError("unsupported graph version")
    namespace = {"v2": "kplasma_agent", "v2_localLLM": "kplasma_agent.v2_local_llm"}[graph_version]
    core = namespace + (".v2" if graph_version == "v2" else ".core")
    gateway = import_module(core + ".model_gateway")
    graph = import_module("kplasma_agent.graphs.v2" if graph_version == "v2" else namespace + ".graph")
    suffix = {"v2": "V2", "v2_localLLM": "V2LocalLLM"}[graph_version]
    return SimpleNamespace(
        config=import_module(namespace + ".config").Settings,
        gateway=getattr(gateway, suffix + "ModelGateway"),
        gateway_settings=getattr(gateway, suffix + "Settings"),
        builder=getattr(graph, {"v2": "build_v2_graph",
                                "v2_localLLM": "build_v2_local_llm_graph"}[graph_version]),
        budget=import_module(core + ".budget"), contracts=import_module(core + ".contracts"),
        validation=import_module(core + ".plan_validation"),
        review=import_module(core + ".plan_review"), tracing=import_module(namespace + ".tracing"),
    )


def live_configuration(graph_version, env_file):
    runtime = runtime_for_version(graph_version)
    if graph_version != "v2" and env_file is None:
        raise ValueError("an explicit env file is required for this graph version")
    base = runtime.config.from_env(env_file)
    if graph_version == "v2_localLLM":
        status = base.readiness()
        if status.get("ready") is not True or status.get("blockers"):
            raise ValueError("LOCAL_RUNTIME_NOT_READY:" + ",".join(status.get("blockers", [])))
    elif not base.api_key:
        raise ValueError("live evaluation requires OPENAI_API_KEY")
    configured = runtime.gateway_settings.from_env(base)
    if not configured.plan_review_enabled:
        flag = {"v2": "AGENT_V2_PLAN_REVIEW_ENABLED",
                "v2_localLLM": "AGENT_V2_LOCAL_LLM_PLAN_REVIEW_ENABLED"}[graph_version]
        raise ValueError(f"live evaluation requires {flag}=true")
    if base.timeout != 90:
        raise ValueError("live evaluation requires the fixed 90-second model timeout")
    return base, configured


@contextmanager
def open_gateway(graph_version, base, configured):
    runtime = runtime_for_version(graph_version)
    cache_options = {}
    if graph_version == "v2_localLLM":
        # Recheck immediately before constructing clients; an earlier status is not a permit.
        status = base.readiness()
        if status.get("ready") is not True or status.get("blockers"):
            raise ValueError("LOCAL_RUNTIME_NOT_READY:" + ",".join(status.get("blockers", [])))
        from kplasma_agent.v2_local_llm.network import local_http_client

        client = local_http_client(base.d1_url, timeout=base.timeout,
                                   headers={"Authorization": "Bearer " + base.d1_token})
        from kplasma_agent.v2_local_llm.runtime import ModelRuntime, model_lease
        control = local_http_client(base.model_url, timeout=base.timeout,
                                    headers={"Authorization": "Bearer " + base.api_key})
        model_runtime = ModelRuntime(base, control, client)
        if base.qwen_plan_cache_enabled:
            from kplasma_agent.v2_local_llm.prompt_cache import QwenPlanCache
            cache_options["plan_cache"] = QwenPlanCache(base, control)
        guard = runtime.budget.make_input_guard(base, qwen_count=runtime.budget.make_qwen_counter(base, control),
                                                d1_count=runtime.budget.make_d1_counter(base, client),
                                                prepare=model_runtime.prepare)
    else:
        client = httpx.Client(timeout=base.timeout, transport=httpx.HTTPTransport(retries=0))
        guard = runtime.budget.check_payload
    with ExitStack() as stack:
        stack.enter_context(client)
        if graph_version == "v2_localLLM":
            stack.enter_context(control)
            stack.enter_context(model_lease())
        models = runtime.gateway(configured, client, guard, **cache_options)
        try:
            yield models
        finally:
            for name in ("planner", "writer"):
                client = getattr(getattr(models, name, None), "client", None)
                if client is not None:
                    client.close()


class EvaluationJournal:
    def __init__(self, source):
        self.source = source
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


def evaluate_case(case: Case, models, *, plan_review_enabled=True, graph_version="v2") -> dict:
    runtime = runtime_for_version(graph_version)
    if graph_version == "v2_localLLM" and not plan_review_enabled:
        raise ValueError("local evaluation requires plan review")
    source = runs()
    journal = EvaluationJournal(source)
    entries = [{"ref": run_ref(run), "key": f"R{i}", "origin": {"kind": "run_tag"}}
               for i, run in enumerate(source[:2], start=1)] if case.selected else []
    timed = TimedModels(models)
    graph = runtime.builder(timed, journal, InMemorySaver())
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
        actual_version = snapshot.get("graphVersion")
        implementation = snapshot.get("implementationId")
        if actual_version != graph_version or implementation != graph_version:
            failures.setdefault("execution", []).append("graph identity differs")
        return {"case": case.id, "question": case.question, "expected": asdict(case), "pass": not failures,
                "expectedGraphVersion": graph_version, "graphVersion": actual_version,
                "implementationId": implementation,
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
    tools = tuple(s["tool"] for s in planned if s.get("kind") == "tool" and s.get("tool") != "explain_answer")
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
