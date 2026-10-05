from copy import deepcopy

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from fixtures import run
from kplasma_agent.backend_client import BackendClient
from kplasma_agent.config import Settings
from kplasma_agent.graphs.v1 import build_graph
from test_graph_v1 import Backend, Model


def test_transport_sends_scoped_query_and_reference_only_option():
    calls = []

    def handle(request):
        import json

        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"runs": []})

    client = BackendClient(Settings(), transport=httpx.MockTransport(handle))
    backend = client.bind({"request": {"requestId": "scoped"}, "claimGeneration": 2, "requestRevision": 3})
    query = {
        "constraints": [{"metric": "pressure", "operator": "lte", "value": 10, "unit": "mTorr"}],
        "goals": [],
    }
    backend.context(references_only=True)
    backend.context(reverse_query=query)
    assert calls[0]["referencesOnly"] is True
    assert calls[1]["reverseQuery"] == query
    assert calls[1]["claimGeneration"] == 2
    assert calls[1]["requestRevision"] == 3


class ScopedBackend(Backend):
    def __init__(self, rows, context=None):
        super().__init__()
        self.rows = rows
        self.saved_context = context or {}
        self.queries = []

    def context(self, refs=None, *, reverse_query=None, references_only=False):
        self.queries.append((deepcopy(reverse_query), references_only))
        return {
            "runs": [] if references_only else self.rows,
            "referencedRuns": self.rows,
            "context": self.saved_context,
        }


def invoke(question, inputs, backend):
    model = Model([{"status": "resolved", "operations": [{"kind": "reverse_search", "inputs": inputs}]}])
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    return graph.invoke(
        {"question": question, "request_id": "scoped", "context": {}, "input_history": []},
        {"configurable": {"thread_id": "scoped"}},
    )


def test_reverse_gather_sends_normalized_conditions_and_ordered_goals():
    backend = ScopedBackend([run("A", energy=155)])
    result = invoke(
        "압력 0.01 Torr 이하, 평균 이온 에너지 150–160 eV 중 이온 플럭스 높은 순으로 찾아줘",
        {
            "constraints": [
                {"metric": "pressure", "operator": "lte", "value": 0.01, "unit": "Torr"},
                {"metric": "meanIonEnergy", "operator": "between", "min": 150, "max": 160, "unit": "eV"},
            ],
            "goals": [{"metric": "ionFlux", "direction": "maximize"}],
        },
        backend,
    )
    assert result["answer"]["status"] == "MATCH"
    assert len(backend.queries) == 1
    query, references_only = backend.queries[0]
    assert not references_only
    assert query["constraints"][0] == {
        "metric": "pressure",
        "operator": "lte",
        "value": 10.0,
        "unit": "mTorr",
    }
    assert query["goals"] == [{"metric": "ionFlux", "direction": "maximize", "unit": "10¹⁸ m⁻²s⁻¹"}]


def test_context_rule_reads_reference_before_querying_derived_bounds():
    baseline = run("A", energy=100)
    target = run("B", energy=105)
    backend = ScopedBackend(
        [baseline, target], {"activeRun": {"runId": "A", "runVersionId": baseline["runVersionId"]}}
    )
    result = invoke(
        "이 Run보다 에너지를 조금 더 높인 후보를 찾아줘",
        {"context_rules": ["energy_slightly_higher"]},
        backend,
    )
    assert result["answer"]["status"] == "MATCH"
    assert backend.queries[0] == (None, True)
    query, references_only = backend.queries[1]
    assert not references_only
    assert query["constraints"]
    assert query["constraints"][0]["metric"] == "meanIonEnergy"
    assert "context_rules" not in query
