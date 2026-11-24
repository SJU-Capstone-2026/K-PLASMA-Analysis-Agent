"""The public dispatcher routes identities; each worker still owns its graph."""

from importlib import import_module

import pytest

from kplasma_agent.graphs.registry import build_graph_for_version


@pytest.mark.parametrize("version,module,builder,keyword", [
    ("v3", "kplasma_agent.v3.graph", "build_v3_graph", "v3_models"),
    ("v2_localLLM", "kplasma_agent.v2_local_llm.graph", "build_v2_local_llm_graph", "local_models"),
])
def test_registry_requires_explicit_owned_models_for_each_variant(version, module, builder, keyword, monkeypatch):
    models, backend, saver, result = object(), object(), object(), object()
    with pytest.raises(ValueError):
        build_graph_for_version(version, None, backend, None, saver)
    own = import_module(module)
    calls = []
    monkeypatch.setattr(own, builder, lambda m, port, s: calls.append((m, port, s)) or result)
    try:
        actual = build_graph_for_version(version, None, backend, None, saver, **{keyword: models})
    except TypeError as error:
        pytest.fail(f"registry cannot configure independent {version}: {error}")
    assert actual is result
    assert calls[0][0] is models and calls[0][2] is saver
    assert type(calls[0][1]).__module__.startswith(module.rpartition(".")[0])


@pytest.mark.parametrize("version", ["v4", "v2_localllm", "local", ""])
def test_unknown_graph_id_never_falls_back(version):
    with pytest.raises(ValueError):
        build_graph_for_version(version, None, None, None, None)
