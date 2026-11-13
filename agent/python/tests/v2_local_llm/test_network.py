"""Local transport must reject a destination before bytes reach the transport."""

from importlib import import_module
from importlib.util import find_spec

import httpx
import pytest


def network():
    assert find_spec("kplasma_agent.v2_local_llm.network"), "local transport guard is missing"
    return import_module("kplasma_agent.v2_local_llm.network")


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://localhost:1234", "http://127.1:1234",
    "http://127.0.0.1:1234@evil.example", "http://127.0.0.1:1234?token=secret",
    "http://127.0.0.1:1234/#fragment", "file:///tmp/model", "http://0.0.0.0:1234"])
def test_only_literal_loopback_origins_can_be_configured(url):
    with pytest.raises(ValueError, match="LOCAL_ENDPOINT_INVALID"):
        network().validate_endpoint(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:1234/v1", "http://[::1]:8081/v1/systemone"])
def test_explicit_loopback_ports_are_valid(url):
    assert network().validate_endpoint(url) == url


def test_no_proxy_redirect_or_other_loopback_port_can_forward_payload(monkeypatch):
    module = network()
    seen = []
    def receive(request):
        seen.append(request.url)
        return httpx.Response(302, headers={"Location": "https://outside.invalid/steal"})
    monkeypatch.setenv("HTTPS_PROXY", "http://outside.invalid:9999")
    with module.local_http_client("http://127.0.0.1:1234/v1", timeout=1,
                                  transport=httpx.MockTransport(receive)) as client:
        response = client.post("/v1/responses", json={"input": "synthetic canary"})
        assert response.status_code == 302
        for url in ["https://outside.invalid/steal", "http://127.0.0.1:9999/proxy", "http://[::1]:1234/"]:
            with pytest.raises(ValueError, match="LOCAL_DESTINATION_DENIED"):
                client.post(url, json={"input": "synthetic canary"})
    assert len(seen) == 1
