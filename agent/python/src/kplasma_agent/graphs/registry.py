"""Dispatch only to the graph version pinned by the server."""

from .v2 import build_v2_graph


def build_graph_for_version(version, backend, saver, *, v2_models=None, local_models=None):
    if version == "v2" and v2_models is not None:
        from ..v2.backend import V2ExecutionPort

        return build_v2_graph(v2_models, V2ExecutionPort(backend), saver)
    if version == "v2_localLLM" and local_models is not None:
        from ..v2_local_llm.graph import build_v2_local_llm_graph
        from ..v2_local_llm.core.backend import V2LocalLLMExecutionPort

        return build_v2_local_llm_graph(local_models, V2LocalLLMExecutionPort(backend), saver)
    raise ValueError("unsupported or unconfigured graph version")
