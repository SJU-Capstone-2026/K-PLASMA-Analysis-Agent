"""Activation checks; the frozen v3 clone and its guards remain unchanged."""

from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

import pytest


def worker():
    assert find_spec("kplasma_agent.v3.worker"), "v3 needs its own worker entry point"
    from kplasma_agent.v3 import worker as module
    return module


class Backend:
    def __init__(self):
        self.errors = []
        self.reads = 0
        self.payload = None
        self.answer = None

    def fail(self, code, partial=None):
        self.errors.append(code)

    def checkpoint(self):
        self.reads += 1
        return self.payload

    def save(self, payload):
        from copy import deepcopy
        self.payload = deepcopy(payload)

    def stage(self, *args, **kwargs):
        pass

    def finalize(self, answer):
        self.answer = answer


@pytest.mark.parametrize("version", [None, "v1", "v2", "v2_localLLM"])
def test_private_worker_rejects_other_graphs_before_reading_state(version):
    module = worker()
    backend = Backend()
    request = {"requestId": "synthetic"}
    if version is not None:
        request["graphVersion"] = version
    module.run_claim({"request": request}, backend, None, models=None)
    assert backend.errors == ["GRAPH_VERSION_MISMATCH"]
    assert backend.reads == 0


def test_worker_requires_explicit_existing_env_file(tmp_path, monkeypatch):
    module = worker()
    monkeypatch.setattr("sys.argv", ["worker"])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    monkeypatch.setattr("sys.argv", ["worker", "--env-file", str(tmp_path / "missing")])
    with pytest.raises(SystemExit):
        module.main()


def test_selected_env_file_is_resolved_and_versions_identify_v3(tmp_path, monkeypatch):
    module = worker()
    from kplasma_agent.v3.core.model_gateway import V3Settings
    env = tmp_path / "v3.env"
    env.write_text("AGENT_WORKER_TOKEN=synthetic\nAGENT_V3_PLAN_MODEL=v3-test\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["worker", "--env-file", "v3.env", "--once"])
    seen = []
    monkeypatch.setattr(module, "serve", lambda settings, once=False: seen.append((settings, once, V3Settings.from_env(settings))))
    with patch.dict("os.environ"):
        import os
        os.environ.pop("AGENT_WORKER_TOKEN", None)
        os.environ.pop("AGENT_V3_PLAN_MODEL", None)
        module.main()
    settings, once, configured = seen[0]
    assert once
    assert settings.graph_build_id.startswith("v3-")
    assert settings.worker_token == "synthetic"
    assert module.resolve_env_file("v3.env") == Path(env).resolve()
    versions = module.runtime_versions(settings, configured)
    assert versions["graphVersion"] == "v3"
    assert versions["implementationId"] == "v3"
    assert versions["planner"] == "v3-test"
    assert versions["cloneManifestHash"]
    assert versions["configFingerprint"]


def test_v2_checkpoint_is_not_read_as_v3_state():
    module = worker()
    from kplasma_agent.v3.config import Settings
    from kplasma_agent.v3.core.model_gateway import V3Settings
    from types import SimpleNamespace
    settings = Settings()
    backend = Backend()
    backend.payload = {"versions": {"graphVersion": "v2"}, "saver": {}}
    module.run_claim({"request": {"requestId": "synthetic", "graphVersion": "v3"}},
                     backend, settings, models=SimpleNamespace(settings=V3Settings.from_env(settings)))
    assert backend.errors == ["RECOVERY_VERSION_MISMATCH"]


def test_worker_commits_the_snapshot_identity_of_a_real_v3_graph(monkeypatch):
    from .test_graph import GeneralModel, Journal
    from kplasma_agent.v3.config import Settings
    from kplasma_agent.v3.core.model_gateway import V3Settings
    module = worker()
    journal, models, backend, settings = Journal(), GeneralModel(), Backend(), Settings()
    models.settings = V3Settings.from_env(settings)
    monkeypatch.setattr(module, "V3ExecutionPort", lambda backend: journal)
    module.run_claim({"request": {"requestId": "synthetic", "question": "IED가 뭐야?", "graphVersion": "v3"}},
                     backend, settings, models=models)
    assert backend.errors == []
    assert backend.answer["answerSnapshot"]["graphVersion"] == "v3"
    assert journal.calls == ["PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE"]
