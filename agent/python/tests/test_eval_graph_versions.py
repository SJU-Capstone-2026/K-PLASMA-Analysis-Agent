"""Synthetic evaluation routing never crosses the selected graph boundary."""

from importlib import import_module
from types import SimpleNamespace

import pytest

import json

import httpx

from evals import flow_grader, run_flow, run_v2, v2_harness
from evals.v2_cases import CASES, Case


@pytest.mark.parametrize("version,namespace", [
    ("v2", "kplasma_agent.v2"), ("v3", "kplasma_agent.v3"),
    ("v2_localLLM", "kplasma_agent.v2_local_llm"),
])
def test_runtime_uses_the_selected_namespace_and_builder(version, namespace):
    runtime = v2_harness.runtime_for_version(version)
    assert runtime.gateway.__module__.startswith(namespace)
    assert runtime.config.__module__.startswith(namespace if version != "v2" else "kplasma_agent.config")
    assert runtime.builder.__module__ == ("kplasma_agent.graphs.v2" if version == "v2" else namespace + ".graph")


def test_unknown_version_never_uses_v2():
    with pytest.raises(ValueError, match="graph version"):
        v2_harness.runtime_for_version("local")


def test_local_jobs_use_one_model_instead_of_cloud_matrix():
    rows = list(run_v2.jobs(1, None, 1, graph_version="v2_localLLM"))
    assert len(rows) == 1
    assert rows[0][:2] == ("mlx-community/Qwen3.5-9B-4bit", "none")
    assert len(list(run_v2.jobs(1, None, 1))) == 4


def test_local_live_configuration_cannot_bypass_readiness(monkeypatch):
    config = import_module("kplasma_agent.v2_local_llm.config")
    called = []
    monkeypatch.setattr(config.Settings, "from_env", lambda _: SimpleNamespace(
        readiness=lambda: {"ready": False, "blockers": ["LOCAL_EGRESS_POLICY_UNVERIFIED"]}))
    monkeypatch.setattr(v2_harness.runtime_for_version("v2_localLLM").gateway_settings,
                        "from_env", lambda _: called.append(True))
    with pytest.raises(ValueError, match="LOCAL_EGRESS_POLICY_UNVERIFIED"):
        v2_harness.live_configuration("v2_localLLM", "private.env")
    assert called == []


@pytest.mark.parametrize("version,namespace", [
    ("v2", "v2"), ("v3", "v3"), ("v2_localLLM", "v2_local_llm"),
])
def test_scripted_case_runs_owned_graph_and_rejects_wrong_identity(version, namespace):
    fixtures = import_module(f"{namespace}.test_graph")
    row = v2_harness.evaluate_case(Case("synthetic", "IED가 뭐야?", ()),
                                  fixtures.GeneralModel(), graph_version=version)
    assert row["graphVersion"] == version
    assert row["implementationId"] == version


def test_local_evaluation_requires_plan_review_even_with_scripted_models():
    with pytest.raises(ValueError, match="plan review"):
        v2_harness.evaluate_case(CASES[0], object(), graph_version="v2_localLLM", plan_review_enabled=False)


def test_harness_detects_an_accidentally_routed_v2_builder(monkeypatch):
    runtime = v2_harness.runtime_for_version("v2_localLLM")
    runtime.builder = v2_harness.runtime_for_version("v2").builder
    monkeypatch.setattr(v2_harness, "runtime_for_version", lambda _: runtime)
    # Give the misrouted v2 graph valid v2 responses so scoring reaches the identity check.
    fixture = import_module("v2.test_graph")
    row = v2_harness.evaluate_case(Case("synthetic", "IED가 뭐야?", ()),
                                  fixture.GeneralModel(), graph_version="v2_localLLM")
    assert row["pass"] is False
    assert "graph identity differs" in row["failures"]["execution"]


@pytest.mark.parametrize("version,module", [
    ("v2", "kplasma_agent.worker"), ("v3", "kplasma_agent.v3.worker"),
    ("v2_localLLM", "kplasma_agent.v2_local_llm.worker"),
])
def test_flow_worker_command_preserves_explicit_version_and_env_file(version, module):
    command = run_flow.worker_command(version, "private.env")
    assert command[1:] == ["-m", module, "--env-file", "private.env"]


def test_session_bootstrap_precedes_data_and_is_consumed_once():
    calls = []

    def transport(request):
        calls.append(request.url.path)
        assert request.headers["Origin"] == "http://127.0.0.1:5173"
        if request.url.path == "/api/local-runtime/session":
            assert request.headers["X-Local-Bootstrap"] == "synthetic-bootstrap"
            return httpx.Response(204, headers={"Set-Cookie": "KPLASMA_LOCAL_SESSION=synthetic-session; Path=/api; HttpOnly; SameSite=Strict"})
        assert request.headers["Cookie"] == "KPLASMA_LOCAL_SESSION=synthetic-session"
        assert "X-Local-Bootstrap" not in request.headers
        return httpx.Response(200, json={})

    with httpx.Client(base_url="http://127.0.0.1:8080", transport=httpx.MockTransport(transport), trust_env=False) as client:
        run_flow.bootstrap_local_session(client, "http://127.0.0.1:5173", "synthetic-bootstrap")
        client.get("/api/workspace")
        with pytest.raises(ValueError, match="ALREADY_BOOTSTRAPPED"):
            run_flow.bootstrap_local_session(client, "http://127.0.0.1:5173", "synthetic-bootstrap")
    assert calls == ["/api/local-runtime/session", "/api/workspace"]


@pytest.mark.parametrize("version", v2_harness.GRAPH_VERSIONS)
def test_flow_grader_rejects_cross_version_snapshot(version, monkeypatch):
    monkeypatch.setattr(flow_grader, "load_oracle", lambda: {"hashes": {}, "byId": {}, "features": {}})
    case = {"expected": {}, "sourceOracle": {"files": {}}, "hitl": []}
    snapshot = {"graphVersion": version, "implementationId": "v2" if version != "v2" else "v3", "answer": "인공 답변"}
    result = flow_grader.grade_raw(case, {"status": "COMPLETED", "graphVersion": version,
                                         "answerSnapshot": snapshot}, [], graph_version=version)
    check = next(check for check in result["checks"] if check["name"] == "implementation_identity")
    assert check["pass"] is False
    assert result["pass"] is False


@pytest.mark.parametrize("version,namespace", [("v3", "v3"), ("v2_localLLM", "v2_local_llm")])
def test_scripted_worker_calls_only_matching_production_worker(version, namespace, monkeypatch):
    scripted = import_module(f"{namespace}.runtime_worker")
    calls = []
    backend = object()

    class Client:
        def __init__(self, settings):
            assert type(settings).__module__ == f"kplasma_agent.{namespace}.config"

        def claim(self, worker_id, versions):
            assert versions == [version]
            return {"request": {"graphVersion": version, "requestId": "synthetic"}}

        def bind(self, claim):
            return backend

    monkeypatch.setattr(scripted.worker, "BackendClient", Client)
    monkeypatch.setattr(scripted.worker, "run_claim", lambda claim, bound, settings, *, models:
                        calls.append((claim, bound, settings, models)))
    connection = {"url": "http://127.0.0.1:8080", "workerToken": "synthetic", "data": "artificial-only",
                  "graphVersion": version, "evaluationMode": "synthetic"}
    scripted.serve(connection, once=True)
    assert len(calls) == 1 and calls[0][1] is backend
    assert type(calls[0][3]).__module__ == f"{namespace}.runtime_worker"
    with pytest.raises(ValueError, match="SYNTHETIC_CONNECTION_REQUIRED"):
        scripted.serve({**connection, "evaluationMode": "real_model"}, once=True)


def test_local_dry_run_contains_no_cloud_model_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["eval", "--graph-version", "v2_localLLM", "--output", str(tmp_path),
                                     "--dry-run", "--limit", "1", "--repeat", "1"])
    run_v2.main()
    rows = json.loads((tmp_path / "matrix.json").read_text())
    assert len(rows) == 1
    assert rows[0]["graphVersion"] == "v2_localLLM"
    assert rows[0]["evaluationMode"] == "offline_preflight"
    assert rows[0]["model"] == "mlx-community/Qwen3.5-9B-4bit"


def test_local_cli_rejects_concurrency_two_before_creating_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["eval", "--graph-version", "v2_localLLM", "--output", str(tmp_path), "--workers", "2"])
    with pytest.raises(SystemExit) as error:
        run_v2.main()
    assert error.value.code == 2
    assert not (tmp_path / "matrix.json").exists()
