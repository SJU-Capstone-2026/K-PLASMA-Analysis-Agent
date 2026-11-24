import httpx
from kplasma_agent.backend_client import BackendClient
from kplasma_agent.config import Settings


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


def test_transport_reads_decision_records_with_the_claim_fence():
    calls = []

    def handle(request):
        import json

        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"records": [{"reviewId": "EXP-1"}]})

    client = BackendClient(Settings(), transport=httpx.MockTransport(handle))
    backend = client.bind({"request": {"requestId": "scoped"}, "claimGeneration": 2, "requestRevision": 3})
    assert backend.decision_records() == [{"reviewId": "EXP-1"}]
    assert calls == [("/internal/agent/requests/scoped/decision-records", {"claimGeneration": 2, "requestRevision": 3})]
