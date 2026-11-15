"""Conservative per-check wire projection; original review snapshots stay intact."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from ..comparison_catalog import FIELD_META
from .contracts import PlanDraft
from .d1_input import _fixed_english
from .plan_checks import KINDS, build_check_specs
from .plan_review import tool_contracts

VERSION = "d1-context-2"
_PROCESS = {"pressure", "sourcePower", "biasPower"}
_OUTPUT = {"ionFlux", "meanIonEnergy", "iedWidth"}
_KNOWN_METRICS = set("""ionFlux meanIonEnergy iedWidth pressure sourcePower biasPower
    current.maximum current.minimum current.peakToPeak current.halfPeakToPeak
    current.maximumPhase current.minimumPhase potential.maximum potential.minimum
    potential.peakToPeak potential.halfPeakToPeak potential.maximumPhase potential.minimumPhase
    ied.maximum ied.peakEnergy iad.maximum iad.peakAngle iead.maximum iead.peakEnergy
    iead.peakAngle density.maximum density.maximumPhase density.maximumDistance
    residual.maximum residual.maximumIteration residual.final residual.finalIteration""".split())


def context_identity(mode: str) -> dict:
    """Pin the files actually imported by the worker and model service."""
    if mode not in {"full", "per_check"}:
        raise ValueError("LOCAL_D1_CONTEXT_CONFIG_INVALID")
    core = Path(__file__).resolve().parent
    dependencies = {name: sha256((core.parent / name).read_bytes()).hexdigest()
                    for name in ("metric_registry.py", "contracts.py", "core/contracts.py",
                                 "core/plan_checks.py", "core/plan_review.py")}
    return {"mode": mode, "version": VERSION,
            "selector_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "registry_sha256": sha256((core.parent / "comparison_catalog.py").read_bytes()).hexdigest(),
            "projection_sha256": sha256((core / "d1_input.py").read_bytes()).hexdigest(),
            "dependency_sha256": sha256(json.dumps(dependencies, sort_keys=True).encode()).hexdigest()}


def _known_contracts(contracts):
    if set(FIELD_META) != _KNOWN_METRICS or not isinstance(contracts, dict):
        return False
    restored = deepcopy(contracts)
    comparison = restored["compare_runs"]
    definitions = comparison.pop("field_definitions", {})
    refs = set()
    for item in comparison["fields"].values():
        if "definition_ref" in item:
            if "definition" in item:
                return False
            ref = item.pop("definition_ref")
            refs.add(ref)
            item["definition"] = definitions[ref]
    if set(definitions) != refs:
        return False
    original = tool_contracts()
    return restored == original or restored == _fixed_english(original)


def project_state(state: str, check_name: str) -> tuple[str, dict]:
    """Copy only known contracts, returning the byte-exact wire state on uncertainty."""
    def result(value, action, reason, tools=(), metrics=()):
        return value, {"action": action, "reason": reason, "tool_ids": sorted(tools),
                       "metric_ids": sorted(metrics), "version": VERSION,
                       "state_sha256": sha256(value.encode()).hexdigest()}

    try:
        payload = json.loads(state)
    except json.JSONDecodeError:
        return result(state, "full", "not_plan_review")
    if not isinstance(payload, dict) or "check_specs" not in payload:
        return result(state, "full", "not_plan_review")
    try:
        specs = payload["check_specs"]
        if not isinstance(specs, list) or not all(isinstance(item, dict) for item in specs):
            return result(state, "fallback", "unresolved_check")
        matching = [item for item in specs if item.get("name") == check_name]
        if len(matching) != 1:
            return result(state, "fallback", "unresolved_check")
        spec = matching[0]
        if spec.get("kind") not in KINDS:
            return result(state, "fallback", "unsupported_context")
        if payload.get("schema_version") != 2:
            return result(state, "fallback", "unsupported_context")
        plan = payload["plan"]
        PlanDraft.model_validate(plan)
        if specs != build_check_specs(plan):
            return result(state, "fallback", "unresolved_check")
        contracts = payload["tool_contracts"]
        if not _known_contracts(contracts):
            return result(state, "fallback", "unsupported_context")
        steps = {step["id"]: step for step in plan["steps"]}
        if len(steps) != len(plan["steps"]):
            return result(state, "fallback", "unresolved_check")
        tools = {"bindings"}
        metrics = set()
        visited = set()

        def metric(name):
            name = {"source_power": "sourcePower", "bias_power": "biasPower"}.get(name, name)
            if name not in _KNOWN_METRICS:
                raise ValueError("unresolved_metric")
            plot = FIELD_META[name]["plotId"]
            metrics.update({key for key, meta in FIELD_META.items() if meta["plotId"] == plot}
                           if plot else _PROCESS if name in _PROCESS else _OUTPUT)

        def context(key):
            if key not in payload["confirmed_context"] or payload["confirmed_context"][key] is None:
                raise ValueError("unresolved_reference")

        def references(value):
            if isinstance(value, list):
                for item in value:
                    references(item)
            elif isinstance(value, dict):
                kind = value.get("kind")
                if kind == "context_ref":
                    context(value["key"])
                elif kind == "result_ref":
                    visit(value["step_id"])
                    field = value["field"]
                    if field in _KNOWN_METRICS:
                        metric(field)
                    elif field not in {"candidates", "selection", "value"}:
                        raise ValueError("unresolved_reference")
                elif kind in {"context_selection", "confirmed_run"}:
                    context(value["key"])
                elif kind == "confirmed_selection":
                    visit(value["step_id"])
                for item in value.values():
                    references(item)

        def visit(step_id):
            if step_id in visited:
                return
            step = steps[step_id]
            visited.add(step_id)
            tool = step.get("tool") if step["kind"] == "tool" else step["kind"]
            if tool not in contracts:
                raise ValueError("unresolved_reference")
            tools.add(tool)
            inputs = step["inputs"]
            if tool == "reverse_search":
                for row in inputs["constraints"] + inputs["goals"]:
                    metric(row["field"])
            elif tool == "forward_lookup":
                metrics.update(_PROCESS | _OUTPUT)
            elif tool == "compare_runs":
                for field in inputs["fields"]:
                    metric(field)
                for plot in inputs["plot_ids"]:
                    group = [key for key, meta in FIELD_META.items() if meta["plotId"] == plot]
                    if not group:
                        raise ValueError("unresolved_metric")
                    metrics.update(group)
                axis = inputs["trend_axis"]
                if axis is not None:
                    metrics.update(_PROCESS)
            elif tool == "await_input":
                visit(inputs["target_step_id"])
            for prior in step["depends_on"]:
                visit(prior)
            references(inputs)
            for prior in step["required_prior_outputs"] + step["run_if"]:
                visit(prior["step_id"])
                if prior["field"] in _KNOWN_METRICS:
                    metric(prior["field"])

        kind = spec["kind"]
        if kind == "tasks":
            tools.update(contracts)
            metrics.update(_KNOWN_METRICS)
        elif kind == "filter_coverage":
            tools.update({"forward_lookup", "reverse_search"})
            metrics.update(_PROCESS | _OUTPUT)
        elif kind == "confirmation_coverage":
            tools.update({"await_input", "compare_runs"})
        elif kind == "outputs":
            tools.add("compare_runs")
            metrics.update(_KNOWN_METRICS)
        elif kind == "selection_count":
            tools.add("await_input")
        else:
            visit(spec["step_ids"][0])
            if kind == "ordering":
                metrics.update(_PROCESS | _OUTPUT)
            if spec["metric"] is not None:
                metric(spec["metric"])
        if metrics:
            tools.add("compare_runs")
        selected = {name: deepcopy(value) for name, value in contracts.items() if name in tools}
        if "compare_runs" in selected:
            comparison = selected["compare_runs"]
            if not metrics:
                del comparison["fields"]
            else:
                comparison["fields"] = {name: value for name, value in comparison["fields"].items()
                                        if name in metrics}
            if kind == "tasks":
                for item in comparison["fields"].values():
                    item.pop("definition", None)
                    item.pop("definition_ref", None)
            if "field_definitions" in comparison:
                needed = {item["definition_ref"] for item in comparison.get("fields", {}).values()
                          if "definition_ref" in item}
                if needed:
                    comparison["field_definitions"] = {name: value for name, value in comparison[
                        "field_definitions"].items() if name in needed}
                else:
                    del comparison["field_definitions"]
        if selected == contracts:
            return result(state, "full", "no_reduction")
        payload["tool_contracts"] = selected
        projected = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(projected.encode()) >= len(state.encode()):
            return result(state, "full", "no_reduction")
        return result(projected, "selected", "known_contracts", tools - {"bindings"}, metrics)
    except (KeyError, TypeError, IndexError, ValueError):
        return result(state, "fallback", "unsupported_context")
