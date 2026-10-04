from copy import deepcopy
from kplasma_agent.config import Settings
from kplasma_agent.worker import run_claim


class Backend:
    def __init__(self):
        self.payload = None
        self.answer = None
        self.pending = None
        self.errors = []

    def checkpoint(self):
        return deepcopy(self.payload)

    def save(self, payload):
        self.payload = deepcopy(payload)

    def context(self, refs=None):
        return {"runs": [], "referencedRuns": [], "context": {}}

    def stage(self, *args, **kwargs):
        pass

    def attempt(self, stage):
        pass

    def needs_input(self, pending):
        self.pending = pending

    def finalize(self, answer):
        self.answer = answer

    def fail(self, code, partial=None):
        self.errors.append(code)


class Model:
    calls = 0

    def generate(self, *args):
        self.calls += 1
        return {
            "status": "resolved",
            "operations": [
                {
                    "kind": "forward_lookup",
                    "inputs": {"conditions": {"pressure": {"value": 10}, "sourcePower": {"value": 300}}},
                }
            ],
        }, {}


def test_worker_reconstructs_interrupted_graph_and_finalizes_once_after_resume():
    backend = Backend()
    model = Model()
    claim = {
        "request": {"requestId": "test", "question": "압력 10 소스 300 조건 조회"},
        "context": {},
        "inputEvents": [],
    }
    run_claim(claim, backend, model, Settings())
    assert backend.pending and backend.answer is None and backend.payload
    claim["inputEvents"] = [{"input": {"conditions": {"biasPower": {"value": 100, "unit": "W"}}}}]
    run_claim(claim, backend, model, Settings())
    assert backend.answer["status"] == "NO_DATA" and model.calls == 1
    assert not backend.errors


def test_worker_refuses_recovery_under_different_config():
    backend = Backend()
    backend.payload = {"versions": {"model": "different"}}
    run_claim({}, backend, Model(), Settings())
    assert backend.errors == ["RECOVERY_VERSION_MISMATCH"]


def test_corrupt_checkpoint_fails_only_the_request():
    backend = Backend()
    backend.payload = {"versions": Settings().versions(), "saver": {"format": "langgraph-memory-v1"}}
    run_claim({"request": {"requestId": "broken"}}, backend, Model(), Settings())
    assert backend.errors == ["RECOVERY_STATE_INVALID"]
