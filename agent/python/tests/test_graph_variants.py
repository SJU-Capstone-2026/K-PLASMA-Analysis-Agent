"""The public dispatcher routes identities; each worker still owns its graph."""

from importlib import import_module

import pytest

from kplasma_agent.graphs.registry import build_graph_for_version


def test_registry_requires_explicit_owned_local_models(monkeypatch):
    models, backend, saver, result = object(), object(), object(), object()
    with pytest.raises(ValueError):
        build_graph_for_version("v2_localLLM", backend, saver)
    own = import_module("kplasma_agent.v2_local_llm.graph")
    calls = []
    monkeypatch.setattr(own, "build_v2_local_llm_graph", lambda m, port, s: calls.append((m, port, s)) or result)
    actual = build_graph_for_version("v2_localLLM", backend, saver, local_models=models)
    assert actual is result
    assert calls[0][0] is models and calls[0][2] is saver
    assert type(calls[0][1]).__module__ == "kplasma_agent.v2_local_llm.core.backend"


@pytest.mark.parametrize("version", ["v1", "v3", "v4", "v2_localllm", "local", ""])
def test_unknown_graph_id_never_falls_back(version):
    with pytest.raises(ValueError):
        build_graph_for_version(version, None, None)
