from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from kplasma_agent.persistence.checkpointer import DurableSaver
from copy import deepcopy
import pytest
from kplasma_agent.config import Settings
from kplasma_agent.worker import run_claim


class State(TypedDict):
    count: int


def test_checkpoint_restores_graph_after_new_worker_and_rejects_stale_write():
    storage = {}
    generation = [1]

    def save(payload):
        assert generation[0] == 1, "stale lease"
        storage["payload"] = payload

    saver = DurableSaver(None, save)
    graph = StateGraph(State)
    graph.add_node("increment", lambda state: {"count": state["count"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    config = {"configurable": {"thread_id": "request-test"}}
    graph.compile(checkpointer=saver).invoke({"count": 4}, config, durability="sync")
    fresh = DurableSaver(storage["payload"], save)
    assert graph.compile(checkpointer=fresh).get_state(config).values["count"] == 5
    generation[0] = 2
    try:
        graph.compile(checkpointer=fresh).invoke({"count": 8}, config, durability="sync")
    except AssertionError:
        pass
    else:
        raise AssertionError("stale writer must fail")


class SimulatedProcessKill(BaseException):
    pass


@pytest.mark.parametrize("kind", ["forward_lookup", "reverse_search"])
def test_pending_numeric_writes_reconcile_edges_before_finalization_after_process_loss(kind):
    from fixtures import run

    class Backend:
        payload = None
        current_stage = None
        crash = True
        answer = None
        failures = []
        context_reads = 0

        def checkpoint(self):
            return deepcopy(self.payload)

        def save(self, payload):
            self.payload = deepcopy(payload)
            if self.crash and self.current_stage == ("forward" if kind == "forward_lookup" else "reverse"):
                self.crash = False
                self.killed_payload = deepcopy(payload)
                raise SimulatedProcessKill()

        def stage(self, stage=None, **kwargs):
            self.current_stage = stage

        def attempt(self, stage):
            pass

        def context(self, refs=None, **options):
            self.context_reads += 1
            return {"runs": [run("A")] if kind == "reverse_search" else [], "referencedRuns": [], "context": {}}

        def finalize(self, answer):
            self.answer = answer

        def fail(self, code, partial=None):
            self.failures.append(code)

    class Model:
        calls = 0

        def generate(self, *args):
            self.calls += 1
            return {
                "status": "resolved",
                "operations": [
                    {
                        "kind": kind,
                        "inputs": {
                            "conditions": {
                                "pressure": {"value": 10, "unit": "mTorr"},
                                "sourcePower": {"value": 300, "unit": "W"},
                                "biasPower": {"value": 100, "unit": "W"},
                            }
                        }
                        if kind == "forward_lookup"
                        else {"goals": [{"metric": "ionFlux", "direction": "maximize"}]},
                    }
                ],
            }, {}

    backend, model = Backend(), Model()
    claim = {
        "request": {
            "requestId": "numeric-pending-write",
            "question": "압력10mTorr 소스300W 바이어스100W 조회"
            if kind == "forward_lookup"
            else "이온 플럭스 높은 순으로 찾아줘",
        },
        "context": {},
        "inputEvents": [],
    }
    with pytest.raises(SimulatedProcessKill):
        run_claim(claim, backend, model, Settings())
    # Executor shutdown may flush later in-memory writes after the test exception.
    # A real SIGKILL cannot do that: restore only bytes saved at the kill boundary.
    backend.payload = backend.killed_payload
    run_claim(claim, backend, model, Settings())
    assert backend.failures == []
    assert backend.answer["status"] == ("NO_DATA" if kind == "forward_lookup" else "MATCH")
    assert backend.context_reads == 1
    if kind == "reverse_search":
        assert backend.answer["answerSnapshot"]["result"]["commonRunIds"] == ["A"]
        assert backend.answer["answerSnapshot"]["result"]["goalResults"] == []
    assert model.calls == 1
