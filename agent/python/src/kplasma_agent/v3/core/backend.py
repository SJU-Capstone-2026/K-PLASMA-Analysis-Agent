"""Step-scoped operations over the existing fenced worker transport."""

from .contracts import PlanDraft, StepResult


class V3ExecutionPort:
    def __init__(self, backend):
        self.backend = backend
        self.progress = getattr(backend, "progress", None)

    def accept_plan(self, plan: PlanDraft):
        return self.backend.post("plans", payload=plan.model_dump(mode="json"))

    def start_step(self, revision, step_id, inputs):
        return self.backend.post("steps", planRevision=revision, stepId=step_id, payload=inputs)

    def load_context(self, execution_id):
        return self.backend.post(f"steps/{execution_id}/context")["runs"]

    def comparison_outputs(self, execution_id, refs, plots):
        return self.backend.post(f"steps/{execution_id}/comparison-outputs", runRefs=refs, plotIds=plots)["outputs"]

    def save_result(self, result: StepResult):
        return self.backend.post(f"steps/{result.executionId}/result", payload=result.model_dump(mode="json"))

    def reserve_model(self, kind, key):
        return self.backend.post("model-attempts", kind=kind, key=key)

    def complete_model(self, attempt_id, outcome):
        return self.backend.post(f"model-attempts/{attempt_id}/complete", payload=outcome)
