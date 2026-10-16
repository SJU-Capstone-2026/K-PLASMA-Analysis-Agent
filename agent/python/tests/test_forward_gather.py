from copy import deepcopy
import json

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from fixtures import run
from kplasma_agent.backend_client import BackendClient
from kplasma_agent.config import Settings
from kplasma_agent.graphs.v1 import build_graph
from test_graph_v1 import Backend, Model


class ForwardBackend(Backend):
    def __init__(self):
        super().__init__()
        self.saved = run("RUN-P08-S300-B0000", pressure=8, source=300, bias=0)
        self.queries = []

    def context(self, refs=None, *, forward_query=None, references_only=False):
        self.queries.append((deepcopy(forward_query), references_only))
        return {
            "runs": [] if references_only else [self.saved],
            "referencedRuns": [self.saved] if references_only else [],
            "context": {"selectedRunRef": {k: self.saved[k] for k in ("runId", "runVersionId")}},
        }


def invoke(inputs, backend, question):
    model = Model([{"operations": [{"kind": "forward_lookup", "inputs": inputs}]}])
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    return graph.invoke(
        {"question": question, "request_id": "forward", "context": {}, "input_history": []},
        {"configurable": {"thread_id": "forward"}},
    )


def test_forward_queries_canonical_conditions_and_preserves_zero():
    backend = ForwardBackend()
    state = invoke({"conditions": {
        "pressure": {"value": 0.008, "unit": "Torr"},
        "sourcePower": {"value": 300, "unit": "와트"},
        "biasPower": {"value": 0, "unit": "W"},
    }}, backend, "압력 0.008 Torr 소스 300 와트 바이어스 0 W 조회")
    assert backend.queries == [({"pressure": 8.0, "sourcePower": 300.0, "biasPower": 0.0}, False)]
    assert state["answer"]["status"] == "EXACT"
    assert len(state["source"]) == 1


def test_forward_context_resolves_reference_before_querying_conditions():
    backend = ForwardBackend()
    state = invoke({"context_rules": ["selected_run_conditions"]}, backend, "이 Run 결과 조회해줘")
    assert state["answer"]["status"] == "EXACT"
    assert backend.queries == [(None, True), ({"pressure": 8.0, "sourcePower": 300.0, "biasPower": 0.0}, False)]


def test_worker_sends_forward_query_with_fence():
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"runs": []})

    client = BackendClient(Settings(), transport=httpx.MockTransport(handle))
    bound = client.bind({"request": {"requestId": "forward"}, "claimGeneration": 2, "requestRevision": 3})
    query = {"pressure": 8, "sourcePower": 300, "biasPower": 0}
    bound.context(forward_query=query)
    assert sent == [{"claimGeneration": 2, "requestRevision": 3, "requiredRunRefs": [], "forwardQuery": query}]
    client.client.close()
