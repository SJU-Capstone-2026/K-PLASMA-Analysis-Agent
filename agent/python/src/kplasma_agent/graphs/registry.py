"""Dispatch only to the graph version pinned by the server."""

from .v1 import build_graph
from .v2 import build_v2_graph


def build_graph_for_version(version, model, backend, settings, saver, *, v2_models=None):
    if version == "v1":
        return build_graph(model, backend, settings, saver)
    if version == "v2" and v2_models is not None:
        from ..v2.backend import V2ExecutionPort

        return build_v2_graph(v2_models, V2ExecutionPort(backend), saver)
    raise ValueError("unsupported or unconfigured graph version")
