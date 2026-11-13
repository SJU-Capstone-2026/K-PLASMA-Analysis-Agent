"""An explicit loopback allowlist at the transport, independent of proxy settings."""

from urllib.parse import urlsplit

import httpx


def validate_endpoint(value):
    try:
        url = urlsplit(value)
        valid = (url.scheme == "http" and url.hostname in {"127.0.0.1", "::1"} and url.port
                 and not (url.username or url.password or url.query or url.fragment)
                 and not any(char.isspace() for char in value))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("LOCAL_ENDPOINT_INVALID")
    return value


class LoopbackTransport(httpx.BaseTransport):
    def __init__(self, origin, transport=None):
        parsed = httpx.URL(validate_endpoint(origin))
        self.origin = (parsed.scheme, parsed.host, parsed.port)
        self.transport = transport if transport is not None else httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request):
        url = request.url
        if (url.scheme, url.host, url.port) != self.origin:
            raise ValueError("LOCAL_DESTINATION_DENIED")
        return self.transport.handle_request(request)

    def close(self):
        self.transport.close()


def local_http_client(url, *, timeout, headers=None, transport=None):
    validate_endpoint(url)
    return httpx.Client(base_url=url, timeout=timeout, headers=headers,
                        transport=LoopbackTransport(url, transport), trust_env=False, follow_redirects=False)
