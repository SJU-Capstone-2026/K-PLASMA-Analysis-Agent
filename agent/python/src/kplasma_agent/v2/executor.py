"""Execute a verified v2 step against the same numerical tools as v1."""

from pydantic import ValidationError

from ..backend_client import BackendError
from ..comparison_catalog import comparison_plan
from ..domain.common import DomainError
from ..domain.compare import compare_selected
from ..domain.forward import lookup_forward
from ..domain.reverse import search_reverse
from ..domain.validation import validate_result
from ..metric_registry import UNITS
from ..progress import ProgressReporter
from .bindings import BlockedInput, resolve_inputs, should_run
from .contracts import CompareStep, DeriveStep, ForwardStep, Quantity, StepResult
from .derivations import compute_derived


class SequentialExecutor:
    def __init__(self, executions):
        self.executions = executions
        self.progress = getattr(executions, "progress", None) or ProgressReporter(None)

    def execute(self, revision, step, context, results):
        try:
            if not should_run(step, results):
                return StepResult(executionId=f"skipped:{step.id}", stepId=step.id, status="skipped", outputs={})
            inputs = resolve_inputs(step, context, results)
        except BlockedInput as error:
            return StepResult(executionId=f"blocked:{step.id}", stepId=step.id, status="blocked",
                              outputs={}, reason=f"MISSING_INPUT:{error.field}")
        except (ValidationError, ValueError):
            return StepResult(executionId=f"blocked:{step.id}", stepId=step.id, status="blocked",
                              outputs={}, reason="INVALID_STEP_INPUT")

        defaulted = _apply_default_units(inputs)
        permit = self.executions.start_step(revision, step.id, inputs)
        execution = permit["executionId"]
        if permit.get("result") is not None:
            self.progress.activity("REUSE_RESULT", "reused", identity=f"reuse:{execution}", stepId=step.id)
            return StepResult.model_validate(permit["result"])
        if not permit["callAllowed"]:
            return StepResult(executionId=execution, stepId=step.id, status="failed", outputs={},
                              reason="EXECUTION_OUTCOME_UNKNOWN")
        code = {"forward_lookup": "FORWARD_LOOKUP", "reverse_search": "REVERSE_SEARCH",
                "compare_runs": "COMPARE_RUNS"}.get(getattr(step, "tool", None), "DERIVE")
        fields = {"stepId": step.id}
        if isinstance(step, CompareStep):
            fields.update(runCount=len(inputs["runs"]), metricIds=step.inputs.fields)
        self.progress.activity(code, identity=execution, **fields)
        try:
            result = self._calculate(execution, step, inputs, defaulted)
        except BackendError as error:
            if error.code in {"STALE_CLAIM", "STALE_REQUEST", "CONTEXT_CLEARED"}:
                raise
            result = StepResult(executionId=execution, stepId=step.id, status="failed", outputs={},
                                reason=error.code)
        except DomainError as error:
            result = StepResult(executionId=execution, stepId=step.id, status="failed", outputs={}, reason=error.code)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            result = StepResult(executionId=execution, stepId=step.id, status="failed", outputs={},
                                reason="STEP_VALIDATION_FAILED")
        saved = StepResult.model_validate(self.executions.save_result(result)["result"])
        self.progress.activity(code, "completed", identity=execution, **fields)
        if saved.status in {"verified", "empty", "partial"} and code in {"FORWARD_LOOKUP", "REVERSE_SEARCH"}:
            count = len(saved.outputs.get("candidates", []))
            self.progress.activity("SEARCH_COMPLETE" if count else "SEARCH_EMPTY", "completed",
                                   identity=f"found:{execution}", runCount=count)
        return saved

    def _calculate(self, execution, step, inputs, defaulted):
        if isinstance(step, DeriveStep):
            quantity = compute_derived(step.operation, [Quantity.model_validate(v) for v in inputs["values"]],
                                       direction=inputs["direction"])
            return StepResult(executionId=execution, stepId=step.id, status="verified",
                              outputs={"value": quantity.model_dump(mode="json")})

        source = self.executions.load_context(execution)
        if isinstance(step, CompareStep):
            opts = inputs["options"]
            _, _, plots = comparison_plan(opts)
            by_ref = {(run["runId"], run["runVersionId"]): run for run in source}
            entries = [
                {**entry, "run": by_ref[entry["ref"]["runId"], entry["ref"]["runVersionId"]]}
                for entry in inputs["entries"]
            ]
            metadata = []
            if plots:
                refs = inputs["runs"]
                for start in range(0, len(refs), 25):
                    metadata.extend(self.executions.comparison_outputs(execution, refs[start:start + 25], plots))
            with self.progress.work("RESULT_VALIDATE", identity=f"verify:{execution}", stepId=step.id):
                raw = compare_selected(opts, entries, metadata)
                if not validate_result(opts, raw, {"entries": entries, "outputs": metadata})["valid"]:
                    raise ValueError("comparison result source mismatch")
            outputs = {"toolResult": raw}
            for field in step.inputs.fields:
                values = []
                for row in raw["runs"]:
                    value = row["metrics"].get(field) or row["conditions"].get(field)
                    values.append(Quantity(
                        value=value["value"], field=field, unit=value["unit"], run_ref=row["ref"],
                        evidence_ids=[f"{execution}:{row['key']}:{field}"],
                    ).model_dump(mode="json") if value and value["status"] == "AVAILABLE" else None)
                outputs[field] = values
            ready = raw["resultStatus"] == "COMPARISON_READY"
            return StepResult(executionId=execution, stepId=step.id, status="verified" if ready else "partial",
                              outputs=outputs, runRefs=raw["usedRunRefs"], groupId="comparison",
                              reason=None if ready else raw["resultStatus"])

        raw = lookup_forward(inputs, source) if isinstance(step, ForwardStep) else search_reverse(inputs, source)
        with self.progress.work("RESULT_VALIDATE", identity=f"verify:{execution}", stepId=step.id):
            if not validate_result(inputs, raw, source)["valid"]:
                raise ValueError("lookup result source mismatch")
        raw["defaultedUnits"] = defaulted
        candidates = raw.get("commonRunRefs", raw["usedRunRefs"])
        return StepResult(executionId=execution, stepId=step.id, status="verified" if candidates else "empty",
                          outputs={"toolResult": raw, "candidates": candidates}, runRefs=raw["usedRunRefs"],
                          groupId="common", reason=raw["resultStatus"])


def _apply_default_units(inputs):
    """Domain tools require explicit units even where the question omitted them."""
    defaults = []
    quantities = list(inputs.get("conditions", {}).items())
    quantities.extend((row["metric"], row) for group in ("constraints", "goals")
                      for row in inputs.get(group, []))
    for metric, row in quantities:
        if not row.get("unit") and any(row.get(key) is not None for key in ("value", "min", "max")):
            row["unit"] = UNITS[metric]
            defaults.append(metric)
    return list(dict.fromkeys(defaults))
