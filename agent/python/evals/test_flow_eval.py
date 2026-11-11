import json
import subprocess
from collections import Counter
from functools import lru_cache
from types import SimpleNamespace

import httpx
import pytest

from kplasma_agent.config import Settings
from . import flow_grader, run_flow
from .flow_recovery import classify


def cases():
    return [
        {"id": f"Q{index:02}", "category": "synthetic", "question": f"Synthetic question {index}"}
        for index in range(1, 41)
    ]


def arguments(monkeypatch, tmp_path, *, live=False):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "cases.json").write_text(json.dumps(cases()))
    connection = tmp_path / "connection.json"
    connection.write_text(
        json.dumps(
            {
                "api": "http://127.0.0.1:8089",
                "web": "http://127.0.0.1:5179",
                "container": "synthetic-eval",
                "workerToken": "synthetic-token",
            }
        )
    )
    output = tmp_path / "output"
    argv = ["run_flow", "--bundle", str(bundle), "--output", str(output)]
    if live:
        argv += ["--live", "--connection", str(connection)]
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(flow_grader, "load_cases", cases)
    return bundle, output


def test_matrix_is_exactly_40_web_then_40_api_without_replacements():
    jobs = run_flow.build_jobs(cases())
    assert len(jobs) == 80
    assert Counter(mode for _, _, mode in jobs) == {"browser": 40, "api": 40}
    assert jobs[:40] == [(case, 1, "browser") for case in cases()]
    assert jobs[40:] == [(case, 2, "api") for case in cases()]


@pytest.mark.parametrize(
    "bad",
    [
        cases()[:-1],
        cases() + [cases()[0]],
        [{**case, "id": "../outside"} if index == 0 else case for index, case in enumerate(cases())],
    ],
)
def test_bad_matrix_is_rejected(bad):
    with pytest.raises(ValueError):
        run_flow.build_jobs(bad)


@pytest.mark.parametrize(
    "url",
    [
        "https://remote.example",
        "http://user:private@localhost",
        "http://localhost/path",
        "http://localhost?token=private",
    ],
)
def test_only_local_origins_are_accepted(url):
    with pytest.raises(ValueError):
        run_flow.local_origin(url)


def test_preflight_does_not_start_servers_workers_browsers_or_models(monkeypatch, tmp_path):
    _, output = arguments(monkeypatch, tmp_path)
    monkeypatch.setattr(run_flow.httpx, "Client", lambda **_: pytest.fail("preflight used HTTP"))
    monkeypatch.setattr(
        run_flow.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("preflight started a process")
    )
    run_flow.main()
    assert len(json.loads((output / "matrix.json").read_text())) == 80
    assert not (output / "results.jsonl").exists()


def test_existing_output_is_preserved(monkeypatch, tmp_path):
    _, output = arguments(monkeypatch, tmp_path)
    output.mkdir()
    (output / "keep.txt").write_text("preserve")
    with pytest.raises(SystemExit) as failure:
        run_flow.main()
    assert failure.value.code == 2 and (output / "keep.txt").read_text() == "preserve"


def test_live_disabled_review_stops_before_http_or_worker(monkeypatch, tmp_path):
    arguments(monkeypatch, tmp_path, live=True)
    monkeypatch.setattr(run_flow.Settings, "from_env", lambda _: Settings(api_key="synthetic"))
    monkeypatch.setenv("AGENT_V2_PLAN_REVIEW_ENABLED", "false")
    monkeypatch.setattr(run_flow.httpx, "Client", lambda **_: pytest.fail("disabled evaluation used HTTP"))
    with pytest.raises(SystemExit) as failure:
        run_flow.main()
    assert failure.value.code == 2


@pytest.mark.parametrize("mismatch,active_count", [(True, "0"), (False, "1")])
def test_catalog_mismatch_and_unfinished_database_stop_before_question_submission(
    monkeypatch, tmp_path, mismatch, active_count
):
    _, output = arguments(monkeypatch, tmp_path, live=True)
    monkeypatch.setattr(run_flow.Settings, "from_env", lambda _: Settings(api_key="synthetic"))
    monkeypatch.setenv("AGENT_V2_PLAN_REVIEW_ENABLED", "true")
    run = {"runId": "ART-A", "runVersionId": "synthetic-v1", "catalogStatus": "READY"}
    monkeypatch.setattr(flow_grader, "load_oracle", lru_cache(maxsize=1)(lambda: {"byId": {"ART-A": run}}))
    observed = []

    def transport(request):
        observed.append((request.method, request.url.path))
        assert request.method == "GET"
        return (
            httpx.Response(200, json=[] if mismatch else [run])
            if request.url.path == "/api/runs"
            else httpx.Response(200, json={})
        )

    with httpx.Client(base_url="http://127.0.0.1:8089", transport=httpx.MockTransport(transport)) as client:
        monkeypatch.setattr(run_flow.httpx, "Client", lambda **_: client)
        monkeypatch.setattr(
            run_flow.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(stdout=active_count)
        )
        monkeypatch.setattr(
            run_flow.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("unsafe preflight started worker")
        )
        with pytest.raises(SystemExit) as failure:
            run_flow.main()
    assert failure.value.code == 2 and not output.exists()
    assert all(method == "GET" for method, _ in observed)


def test_worker_is_stopped_even_when_browser_and_cleanup_http_both_fail(monkeypatch, tmp_path):
    arguments(monkeypatch, tmp_path, live=True)
    monkeypatch.setattr(run_flow.Settings, "from_env", lambda _: Settings(api_key="synthetic"))
    monkeypatch.setenv("AGENT_V2_PLAN_REVIEW_ENABLED", "true")
    run = {"runId": "ART-A", "runVersionId": "synthetic-v1", "catalogStatus": "READY"}
    monkeypatch.setattr(flow_grader, "load_oracle", lru_cache(maxsize=1)(lambda: {"byId": {"ART-A": run}}))
    workspace_reads = 0

    def transport(request):
        nonlocal workspace_reads
        if request.url.path == "/api/runs":
            return httpx.Response(200, json=[run])
        workspace_reads += 1
        return httpx.Response(200 if workspace_reads == 1 else 500, json={})

    class Worker:
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, **_):
            return 0

    class BrokenBrowser:
        def send(self, *_):
            raise RuntimeError("synthetic browser failure")

        def close(self):
            raise RuntimeError("synthetic browser close failure")

    worker = Worker()
    with httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(transport)) as client:
        monkeypatch.setattr(run_flow.httpx, "Client", lambda **_: client)
        monkeypatch.setattr(run_flow.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(stdout="0"))
        monkeypatch.setattr(run_flow.subprocess, "Popen", lambda *_a, **_kw: worker)
        monkeypatch.setattr(run_flow, "Browser", BrokenBrowser)
        monkeypatch.setattr(run_flow, "prepare", lambda *_: ({"stateToken": {}}, [], None))
        with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
            run_flow.main()
        assert worker.stopped and client.is_closed


@pytest.mark.parametrize("key_mode", ["original", "new_keys", "reused_keys"])
def test_api_hitl_uses_actual_options_and_same_request_revision(monkeypatch, tmp_path, key_mode):
    request_id = "00000000-0000-4000-8000-000000000001"
    revision = 0
    posts = []
    options = [
        {"key": key, "ref": {"runId": rid, "runVersionId": key}, "selectable": True}
        for key, rid in [("R1", "ART-A"), ("R2", "ART-B")]
    ]

    def view(status):
        result = {"requestId": request_id, "status": status, "requestRevision": revision}
        if status == "NEEDS_INPUT":
            result["pendingInput"] = (
                {"id": "pick", "type": "run_selection"}
                if revision == 0
                else {
                    "id": "baseline",
                    "type": "comparison_options",
                    "fields": ["baselineKey"],
                    "allowedRunKeys": ["S1", "S2"] if key_mode == "new_keys" else ["R1", "R2"],
                    "options": []
                    if key_mode == "original"
                    else [
                        {
                            "label": "ART-B",
                            "input": {"baselineKey": "S1" if key_mode == "new_keys" else "R1"},
                        },
                        {
                            "label": "ART-A",
                            "input": {"baselineKey": "S2" if key_mode == "new_keys" else "R2"},
                        },
                    ],
                }
            )
        return result

    def transport(request):
        nonlocal revision
        if request.method == "POST":
            body = json.loads(request.content)
            posts.append((request.url.path, body))
            if request.url.path.endswith("/resume"):
                assert body["expectedRequestRevision"] == revision
                revision += 1
            return httpx.Response(200, json=view("QUEUED"))
        if request.url.path.endswith("/run-options"):
            return httpx.Response(200, json={"options": options})
        return httpx.Response(200, json=view("COMPLETED" if revision == 2 else "NEEDS_INPUT"))

    with httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(transport)) as client:
        monkeypatch.setattr(run_flow, "CLIENT", client)
        monkeypatch.setattr(run_flow.time, "sleep", lambda _: None)
        outcome = run_flow.run_api(
            {
                "question": "synthetic",
                "hitl": [
                    {"type": "run_selection", "runIds": ["ART-A", "ART-B"]},
                    {"type": "comparison_options", "baselineRunId": "ART-B"},
                ],
            },
            {"stateToken": {}},
            [],
            None,
            tmp_path,
        )
    assert "harnessIssue" not in outcome
    assert outcome["requestId"] == request_id and outcome["view"]["status"] == "COMPLETED"
    assert len(posts) == 3 and len(outcome["interactions"]) == 2
    assert posts[1][1]["input"]["runKeys"] == ["R1", "R2"]
    assert posts[2][1]["input"] == {
        "type": "comparison_options",
        "baselineKey": "R2" if key_mode == "original" else "S1" if key_mode == "new_keys" else "R1",
    }
    assert json.loads((tmp_path / "accepted.json").read_text())["requestId"] == request_id


def test_export_rejects_non_uuid_before_running_sql(monkeypatch, tmp_path):
    monkeypatch.setattr(
        run_flow.subprocess, "run", lambda *_a, **_kw: pytest.fail("unsafe identifier reached SQL")
    )
    with pytest.raises(ValueError):
        run_flow.export_request("synthetic", "not-a-uuid';drop table agent_request", tmp_path)


def test_database_export_has_a_finite_deadline_and_stops_on_timeout(monkeypatch, tmp_path):
    commands = []

    def stalled(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] == 30
        assert "where request_id='00000000-0000-4000-8000-000000000001'::uuid" in kwargs["input"]
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(run_flow.subprocess, "run", stalled)
    with pytest.raises(subprocess.TimeoutExpired):
        run_flow.export_request("synthetic", "00000000-0000-4000-8000-000000000001", tmp_path)
    assert len(commands) == 1 and not (tmp_path / "execution-records.json").exists()


@pytest.mark.parametrize("labels", [["ART-BB"], ["ART-B", "ART-B"]])
def test_api_comparison_baseline_must_match_one_exact_offered_run(labels):
    pending = {
        "fields": ["baselineKey"],
        "allowedRunKeys": ["R1", "R2"],
        "options": [
            {"label": label, "input": {"baselineKey": f"R{index + 1}"}} for index, label in enumerate(labels)
        ],
    }
    with pytest.raises(ValueError):
        run_flow.comparison_input(pending, {"baselineRunId": "ART-B"}, {"R1": "ART-B"})


def test_recovery_requires_issue_before_replan_and_independent_final_pass():
    def attempt(index, kind, status=None):
        return {
            "id": str(index),
            "attempt_key": str(index),
            "kind": kind,
            "deadline": f"2026-01-01T00:00:{index:02}+00:00",
            "outcome": {"data": {"status": status}},
        }

    sequence = [attempt(1, "PLAN_INITIAL"), attempt(2, "PLAN_REVIEW", "ISSUE"), attempt(3, "REPLAN")]
    assert classify(sequence, True)["decisionsReplanRecovered"] is True
    assert classify(sequence, False)["decisionsReplanRecovered"] is False
    assert (
        classify([attempt(1, "PLAN_INITIAL"), attempt(2, "REPLAN"), attempt(3, "PLAN_REVIEW", "PASS")], True)[
            "category"
        ]
        == "passed_after_other_replan"
    )


def test_independent_oracle_keeps_strict_and_inclusive_boundaries_distinct():
    assert flow_grader.canonical("ionFlux", 2e20, "m^-2 s^-1") == 200
    strict = flow_grader.interval(
        [{"field": "meanIonEnergy", "operator": "gt", "value": 10, "unit": "eV"}], "meanIonEnergy"
    )
    inclusive = flow_grader.interval(
        [{"field": "meanIonEnergy", "operator": "gte", "value": 10, "unit": "eV"}], "meanIonEnergy"
    )
    assert strict[:2] == (10, False) and inclusive[:2] == (10, True)


def test_same_run_cannot_be_graded_as_two_comparison_endpoints(monkeypatch):
    monkeypatch.setattr(
        flow_grader, "grade_raw", lambda *_: {"pass": True, "checks": [], "humanReviewRequired": False}
    )
    monkeypatch.setattr(flow_grader, "load_overrides", lambda: {"overrides": {}})
    tool = {
        "kind": "compare_runs",
        "runs": [{"key": key, "ref": {"runId": "ART-A"}} for key in ["R1", "R2"]],
        "comparisons": [{"leftKey": "R1", "rightKey": "R2"}],
    }
    result = flow_grader.grade(
        {"id": "Q01"}, {"answerSnapshot": {"stepResults": [{"outputs": {"toolResult": tool}}]}}, []
    )
    assert result["pass"] is False
    assert result["checks"][0]["detail"]["errors"][0]["reason"] == "self_comparison"


def test_summary_keeps_modes_review_requirements_and_ui_separate():
    rows = [
        {
            "mode": mode,
            "grade": {"pass": passed, "answerReviewRequired": review},
            "recovery": {"category": category},
            "uiPass": ui,
        }
        for mode, passed, review, category, ui in [
            ("browser", False, False, "failed", True),
            ("api", True, True, "passed_after_decisions_replan", None),
        ]
    ]
    result = run_flow.summarize(rows)
    assert result["byMode"]["browser"]["deterministicPass"] == 0
    assert result["browserAutomatedUiPass"] == 1
    assert result["byMode"]["api"]["answerReviewRequired"] == 1
    assert result["gradingStage"] == "deterministic_only" and "contentPass" not in result
