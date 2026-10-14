from copy import deepcopy
import pytest
from fixtures import run
from kplasma_agent.config import Settings
from kplasma_agent.worker import run_claim
from kplasma_agent.model_client import ModelError


class Killed(BaseException):
    pass


class Backend:
    def __init__(self, kill_stage=None):
        self.payload = self.answer = self.partial = self.stage_name = None
        self.kill_stage = kill_stage
        self.reads = 0
        self.errors = []
        self.stages = []

    def checkpoint(self):
        return deepcopy(self.payload)

    def save(self, payload):
        self.payload = deepcopy(payload)
        if self.kill_stage is not None and self.stage_name == self.kill_stage:
            self.kill_stage = None
            self.killed_payload = deepcopy(payload)
            raise Killed()

    def stage(self, stage=None, **kwargs):
        self.stage_name = stage
        self.stages.append(stage)

    def attempt(self, *args):
        pass

    def context(self, refs=None, **kwargs):
        self.reads += 1
        return {"runs": [], "referencedRuns": [run("A", flux=0), run("B", flux=4)]}

    def finalize(self, answer):
        self.answer = answer

    def fail(self, code, partial=None):
        self.errors.append(code)
        self.partial = partial

    def needs_input(self, pending):
        raise AssertionError("explicit comparison should not ask for Run selection")


class Model:
    def __init__(self, fail=False):
        self.selection_calls = self.answer_calls = 0
        self.fail = fail

    def select_tool(self, *args):
        self.selection_calls += 1
        return {
            "name": "compare_runs",
            "arguments": {"metrics": ["ionFlux"], "baseline_key": "R1"},
            "call_id": "synthetic-call",
        }, {"responseItems": []}

    def generate(self, prompt, payload, cls, **kwargs):
        self.answer_calls += 1
        if self.fail:
            raise ModelError("MODEL_OUTPUT_INVALID")
        return {
            "observationIds": [payload["evidence"]["observations"][0]["id"]],
            "interpretations": [],
            "limitations": [],
        }, {}


def claim():
    entries = [
        {
            "key": f"R{i + 1}",
            "ref": {k: r[k] for k in ("runId", "runVersionId")},
            "origin": {"kind": "run_tag", "turnId": "saved", "groupId": None, "pendingInputId": None},
        }
        for i, r in enumerate([run("A"), run("B")])
    ]
    return {
        "request": {"requestId": "synthetic-recovery", "question": "선택한 실험의 플럭스 차이를 설명해줘"},
        "context": {"comparisonReference": {"entries": entries, "baselineKey": "R1"}},
        "inputEvents": [],
    }


@pytest.mark.parametrize(
    "stage", ["calculate", "validate_result", "present"]
)
def test_reconstructed_comparison_preserves_numeric_work_and_native_call(stage):
    backend, model = Backend(stage), Model()
    with pytest.raises(Killed):
        run_claim(claim(), backend, model, Settings())
    backend.payload = backend.killed_payload
    run_claim(claim(), backend, model, Settings())
    assert not backend.errors and backend.answer is not None
    assert backend.reads == model.selection_calls == 1
    assert model.answer_calls == 0
    assert not {"generate_answer", "validate_answer"}.intersection(backend.stages)
    assert backend.answer["answerSnapshot"]["answer"] is None
    result = backend.answer["answerSnapshot"]["result"]
    assert result["comparisons"][0]["percentChange"]["reason"] == "ZERO_BASELINE"
    assert len(result["runs"]) == len(result["usedRunRefs"]) == 2


def test_comparison_completes_without_calling_a_failing_explanation_model():
    backend, model = Backend(), Model(fail=True)
    run_claim(claim(), backend, model, Settings())
    assert backend.answer is not None and backend.errors == [] and backend.partial is None
    assert model.answer_calls == 0 and model.selection_calls == backend.reads == 1
    snapshot = backend.answer["answerSnapshot"]
    assert snapshot["schemaVersion"] == 2 and snapshot["answer"] is None
    assert len(snapshot["result"]["runs"]) == len(snapshot["usedRunRefs"]) == 2
    assert snapshot["result"]["comparisons"][0]["difference"]["value"] == 4
