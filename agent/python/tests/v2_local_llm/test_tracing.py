import pytest

from kplasma_agent.v2_local_llm import tracing
from kplasma_agent.v2_local_llm.config import Settings


def test_local_tracing_cannot_construct_a_cloud_exporter(monkeypatch):
    exports = []
    monkeypatch.setattr(tracing, "_register", lambda **kw: exports.append(kw))
    with pytest.raises(ValueError, match="LOCAL_TRACING_DISABLED"):
        tracing.initialize(Settings(phoenix_endpoint="https://outside.invalid", phoenix_api_key="synthetic"))
    assert not exports
    assert tracing.initialize(Settings()) is False
