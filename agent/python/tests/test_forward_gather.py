import json

import httpx
from kplasma_agent.backend_client import BackendClient
from kplasma_agent.config import Settings


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
