"""Manual local v2 evaluation: the same external 40-case bank in web and API."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid

import httpx

from . import flow_grader
from .flow_recovery import classify
from .v2_harness import GRAPH_VERSIONS, live_configuration

REPO = Path(__file__).resolve().parents[3]
ROOT = API = WEB = CLIENT = None
HEADLESS = False
GRAPH_VERSION = "v2"


def worker_command(graph_version, env_file=None):
    if graph_version not in GRAPH_VERSIONS:
        raise ValueError("unsupported graph version")
    if graph_version != "v2" and env_file is None:
        raise ValueError("an explicit env file is required")
    module = {"v2": "kplasma_agent.worker", "v3": "kplasma_agent.v3.worker",
              "v2_localLLM": "kplasma_agent.v2_local_llm.worker"}[graph_version]
    return [sys.executable, "-m", module, *(["--env-file", str(env_file)] if env_file else [])]


def bootstrap_local_session(client, web, token, *, session_cookie=None):
    """Consume one bootstrap before any data API call; retain the HttpOnly session in the client."""
    if client.cookies.get("KPLASMA_LOCAL_SESSION"):
        raise ValueError("LOCAL_SESSION_ALREADY_BOOTSTRAPPED")
    client.headers["Origin"] = local_origin(web)
    client.headers["Sec-Fetch-Site"] = "same-site"
    if session_cookie is not None:
        match = re.fullmatch(r"KPLASMA_LOCAL_SESSION=([A-Za-z0-9_-]{32,128})", session_cookie)
        if match is None:
            raise ValueError("LOCAL_SESSION_INVALID")
        client.cookies.set("KPLASMA_LOCAL_SESSION", match[1], domain=client.base_url.host, path="/api")
        return
    if not isinstance(token, str) or len(token) < 16:
        raise ValueError("LOCAL_BOOTSTRAP_REQUIRED")
    response = client.post("/api/local-runtime/session", headers={"X-Local-Bootstrap": token})
    response.raise_for_status()
    if not client.cookies.get("KPLASMA_LOCAL_SESSION"):
        raise ValueError("LOCAL_SESSION_NOT_ESTABLISHED")


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def request(method, path, body=None):
    response = CLIENT.request(
        method, path, json=body, headers={"Idempotency-Key": str(uuid.uuid4())} if method == "POST" else {}
    )
    response.raise_for_status()
    return response.json()


def prepare(case, catalog):
    old = request("GET", "/api/workspace")
    if old.get("activeAgentRequest"):
        raise RuntimeError("An active request remains; preserve it rather than changing conversations.")
    workspace = request("POST", "/api/workspace/new-conversation", {"stateToken": old["stateToken"]})
    refs = [{"runId": run, "runVersionId": catalog[run]["runVersionId"]} for run in case.get("selected", [])]
    baseline = next((ref for ref in refs if ref["runId"] == case.get("baseline")), None)
    if refs:
        reference = {"kind": "단일 Run" if len(refs) == 1 else "후보 집합", "runs": refs, "catalogRefs": refs}
        workspace = request(
            "PUT",
            "/api/workspace/reference",
            {"stateToken": workspace["stateToken"], "candidateReference": reference, "activeRun": baseline},
        )
    return workspace, refs, baseline


def cancel(view):
    if view and view.get("status") in ("QUEUED", "RUNNING", "NEEDS_INPUT"):
        return request("POST", f"/api/agent/requests/{view['requestId']}/cancel")
    return view


def comparison_input(pending, action, mapping):
    value = {"type": "comparison_options"}
    fields = pending.get("fields", [])
    if any(field not in ("baselineKey", "trendAxis") for field in fields):
        raise ValueError("unsupported comparison option field")
    if "baselineKey" in fields:
        baseline = action.get("baselineRunId")
        if not baseline:
            raise ValueError("expected baseline unavailable")
        allowed = pending.get("allowedRunKeys", [])
        options = pending.get("options", [])
        if options:
            pattern = rf"(?<![A-Za-z0-9_-]){re.escape(baseline)}(?![A-Za-z0-9_-])"
            keys = {
                option.get("input", {}).get("baselineKey")
                for option in options
                if option.get("input", {}).get("baselineKey") in allowed
                and re.search(pattern, option.get("label", ""))
            }
        else:
            keys = {key for key in allowed if mapping.get(key) == baseline}
        if len(keys) != 1:
            raise ValueError("expected baseline unavailable or ambiguous")
        value["baselineKey"] = keys.pop()
    if "trendAxis" in fields:
        if action.get("trendAxis") not in pending.get("allowedTrendAxes", []):
            raise ValueError("expected trend axis unavailable")
        value["trendAxis"] = action["trendAxis"]
    return value


def run_api(case, workspace, refs, baseline, directory):
    body = {
        "text": case["question"],
        "stateToken": workspace["stateToken"],
        "graphVersion": GRAPH_VERSION,
        "attachedRunRefs": refs,
        "referenceOrigins": [
            {"ref": ref, "kind": "catalog_tag", "turnId": None, "groupId": None} for ref in refs
        ],
    }
    if baseline:
        body["baseline"] = baseline
    view = request("POST", "/api/agent/requests", body)
    dump(directory / "accepted.json", view)
    interactions = []
    mapping = {f"R{i}": ref["runId"] for i, ref in enumerate(refs, 1)}
    start = time.monotonic()
    handled = set()
    while time.monotonic() - start < 900:
        view = request("GET", f"/api/agent/requests/{view['requestId']}")
        if view["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return {"view": view, "requestId": view["requestId"], "interactions": interactions}
        if view["status"] == "NEEDS_INPUT":
            pending = view["pendingInput"]
            if pending["id"] in handled:
                time.sleep(0.3)
                continue
            actions = case.get("hitl", [])
            if len(interactions) >= len(actions):
                return {
                    "view": cancel(view),
                    "requestId": view["requestId"],
                    "interactions": interactions,
                    "harnessIssue": "unexpected user input request",
                    "pending": pending,
                }
            action = actions[len(interactions)]
            if action["type"] != pending.get("type"):
                return {
                    "view": cancel(view),
                    "requestId": view["requestId"],
                    "interactions": interactions,
                    "harnessIssue": "user input type differs",
                    "pending": pending,
                }
            options = None
            if action["type"] == "run_selection":
                options = request(
                    "GET",
                    f"/api/agent/requests/{view['requestId']}/run-options?pendingInputId={pending['id']}",
                )
                mapping.update({option["key"]: option["ref"]["runId"] for option in options["options"]})
                keys = []
                for run_id in action["runIds"]:
                    candidates = [
                        o for o in options["options"] if o["ref"]["runId"] == run_id and o.get("selectable")
                    ]
                    if len(candidates) != 1:
                        return {
                            "view": cancel(view),
                            "requestId": view["requestId"],
                            "interactions": interactions,
                            "harnessIssue": "expected selectable Run unavailable",
                            "pending": pending,
                            "options": options,
                        }
                    keys.append(candidates[0]["key"])
                base = action.get("baselineRunId")
                selected_base = next((key for key in keys if mapping[key] == base), None) if base else None
                value = {"type": "run_selection", "runKeys": keys, "baselineKey": selected_base}
            elif action["type"] == "comparison_options":
                try:
                    value = comparison_input(pending, action, mapping)
                except ValueError as error:
                    return {
                        "view": cancel(view),
                        "requestId": view["requestId"],
                        "interactions": interactions,
                        "harnessIssue": str(error),
                        "pending": pending,
                    }
            else:
                return {
                    "view": cancel(view),
                    "requestId": view["requestId"],
                    "interactions": interactions,
                    "harnessIssue": "unsupported input",
                    "pending": pending,
                }
            interactions.append(
                {"type": action["type"], "pending": pending, "options": options, "input": value}
            )
            handled.add(pending["id"])
            payload = {
                "expectedRequestRevision": view["requestRevision"],
                "pendingInputId": pending["id"],
                "input": value,
            }
            try:
                view = request("POST", f"/api/agent/requests/{view['requestId']}/resume", payload)
            except httpx.HTTPStatusError as error:
                return {
                    "view": cancel(view),
                    "requestId": view["requestId"],
                    "interactions": interactions,
                    "harnessIssue": f"resume rejected HTTP {error.response.status_code}",
                }
        time.sleep(0.3)
    return {
        "view": cancel(view),
        "requestId": view["requestId"],
        "interactions": interactions,
        "harnessIssue": "900-second trial timeout",
    }


class Browser:
    def __init__(self):
        self.log = (ROOT / "browser.stderr.log").open("a")
        self.process = subprocess.Popen(
            ["node", str(REPO / "scripts/agent/flow-browser.mjs")],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            bufsize=1,
        )
        try:
            response = self.send(
                {"cmd": "init", "api": API, "web": WEB, "output": str(ROOT), "headless": HEADLESS,
                 "graphVersion": GRAPH_VERSION,
                 "sessionCookie": ("KPLASMA_LOCAL_SESSION=" + CLIENT.cookies.get("KPLASMA_LOCAL_SESSION"))
                    if GRAPH_VERSION == "v2_localLLM" else None}
            )
            if not response.get("ok"):
                raise RuntimeError("Browser initialization failed; inspect browser.stderr.log")
        except BaseException:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.log.close()
            raise

    def send(self, message, timeout=950):
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], timeout)
        if not ready:
            raise TimeoutError("Browser bridge did not return before its deadline")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("Browser bridge exited; inspect local stderr")
        return json.loads(line)

    def close(self):
        try:
            self.send({"cmd": "close"}, timeout=10)
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.log.close()


def local_origin(value):
    url = urlsplit(value)
    if (
        url.scheme not in ("http", "https")
        or url.hostname not in ("localhost", "127.0.0.1", "::1")
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
    ):
        raise ValueError("Evaluation requires local server origins without credentials or paths")
    return value.rstrip("/")


def build_jobs(cases, *, mode="both", limit=40):
    if len(cases) != 40 or len({case["id"] for case in cases}) != 40:
        raise ValueError("Expected the frozen 40-question bank")
    if any(not re.fullmatch(r"[A-Z][0-9]{2}", case["id"]) for case in cases):
        raise ValueError("Case IDs must use a letter and two digits")
    if mode not in {"both", "browser", "api"} or type(limit) is not int or not 1 <= limit <= 40:
        raise ValueError("Invalid evaluation mode or limit")
    return [(case, trial, selected) for trial, selected in ((1, "browser"), (2, "api"))
            if mode in {"both", selected} for case in cases[:limit]]


def export_request(container, request_id, directory):
    request_id = str(uuid.UUID(request_id))
    result = {}
    for name, table, key in [
        ("models", "agent_v2_model_attempt", "request_id"),
        ("plans", "agent_v2_plan_revision", "request_id"),
        ("steps", "agent_step_execution", "request_id"),
        ("inputs", "agent_input_event", "request_id"),
    ]:
        sql = f"select row_to_json(t) from (select * from {table} where {key}='{request_id}'::uuid) t;"
        response = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-U",
                "kplasma",
                "-d",
                "kplasma",
                "-v",
                "ON_ERROR_STOP=1",
                "-At",
            ],
            input=sql,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        result[name] = [json.loads(line) for line in response.stdout.splitlines() if line.strip()]
    dump(directory / "execution-records.json", result)
    return result


def summarize(rows):
    modes = {}
    for mode in ("browser", "api"):
        items = [row for row in rows if row["mode"] == mode]
        modes[mode] = {
            "trials": len(items),
            "deterministicPass": sum(row["grade"]["pass"] for row in items),
            "answerReviewRequired": sum(row["grade"]["answerReviewRequired"] for row in items),
            "provisionalRecovery": dict(Counter(row["recovery"]["category"] for row in items)),
        }
    return {
        "completed": len(rows),
        "byMode": modes,
        "browserAutomatedUiPass": sum(row.get("uiPass") is True for row in rows if row["mode"] == "browser"),
        "gradingStage": "deterministic_only",
        "humanExpertReviewPerformed": False,
        "warning": "Answer review flags and visual artifacts require independent review before final content/UI claims.",
    }


def main():
    global ROOT, API, WEB, CLIENT, HEADLESS, GRAPH_VERSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", required=True, type=Path, help="Private frozen cases and oracle JSON directory"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="New directory outside the repository and bundle"
    )
    parser.add_argument(
        "--connection", type=Path, help="Private api/web/container/workerToken JSON for a dedicated app"
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--graph-version", choices=GRAPH_VERSIONS, default="v2")
    parser.add_argument(
        "--live", action="store_true", help="Submit selected Agent questions; absent means offline preflight"
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--mode", choices=("both", "browser", "api"), default="both")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    GRAPH_VERSION = args.graph_version
    ROOT = args.output.expanduser().resolve()
    bundle = args.bundle.expanduser().resolve()
    if ROOT.is_relative_to(REPO) or ROOT.is_relative_to(bundle) or ROOT.exists():
        parser.error("Output must be a NEW directory outside the repository and input bundle")
    flow_grader.configure(bundle)
    cases = flow_grader.load_cases()
    try:
        jobs = build_jobs(cases, mode=args.mode, limit=args.limit)
    except ValueError as error:
        parser.error(str(error))
    manifest = {
        "graphVersion": GRAPH_VERSION, "expectedImplementationId": GRAPH_VERSION,
        "evaluationMode": "real_model" if args.live else "offline_preflight", "concurrency": 1,
        "settings": {"planReviewEnabled": True, "modelTimeoutSeconds": 90},
        "planned": {mode: sum(selected == mode for _, _, selected in jobs) for mode in ("browser", "api")},
        "maxReplans": 2,
        "maxAnswerRewrites": 1,
        "inputSha256": {
            name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
            for name in (
                "cases.json",
                "runs.json",
                "wave-expected.json",
                "distribution-expected.json",
                "oracle-overrides.json",
            )
            if (bundle / name).exists()
        },
    }
    if args.live:
        if not args.connection:
            parser.error("--live requires a dedicated local app --connection")
        connection = json.loads(args.connection.read_text())
        API, WEB = local_origin(connection["api"]), local_origin(connection["web"])
        container = connection["container"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container):
            parser.error("Invalid database container name")
        try:
            settings, configured = live_configuration(GRAPH_VERSION, args.env_file)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        if not connection.get("workerToken"):
            parser.error("Live evaluation requires a matching backend workerToken")
        if GRAPH_VERSION == "v2_localLLM" and (settings.backend_url != API
                                               or settings.worker_token != connection["workerToken"]):
            parser.error("LOCAL_CONNECTION_PROFILE_MISMATCH")
        manifest["settings"].update(
            planner=configured.planner.model,
            planEffort=configured.planner.reasoning_effort,
            writer=configured.writer.model,
            answerEffort=configured.writer.reasoning_effort,
            decisions=configured.decisions_model,
            phoenixEnabled=bool(settings.phoenix_endpoint and settings.phoenix_api_key),
            phoenixProject=settings.phoenix_project_name,
        )
        if GRAPH_VERSION == "v2_localLLM":
            from kplasma_agent.v2_local_llm.network import local_http_client

            CLIENT = local_http_client(API, timeout=30)
            bootstrap_local_session(CLIENT, WEB, connection.get("bootstrapToken"),
                                    session_cookie=connection.get("sessionCookie"))
        else:
            CLIENT = httpx.Client(base_url=API, timeout=30, transport=httpx.HTTPTransport(retries=0))
        catalog = {
            row["runId"]: row for row in request("GET", "/api/runs") if row.get("catalogStatus") == "READY"
        }
        oracle = flow_grader.load_oracle()["byId"]
        fields = ("runVersionId", "pressure", "sourcePower", "biasPower", "metrics", "units", "analysis")
        if catalog.keys() != oracle.keys() or any(
            catalog[rid].get(field) != oracle[rid].get(field) for rid in oracle for field in fields
        ):
            parser.error("Backend catalog differs from the frozen oracle; no questions submitted")
        if request("GET", "/api/workspace").get("activeAgentRequest"):
            parser.error("An active request exists; no worker started or questions submitted")
        active = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "psql",
                "-U",
                "kplasma",
                "-d",
                "kplasma",
                "-Atc",
                "select count(*) from agent_request where status in ('QUEUED','RUNNING','NEEDS_INPUT')",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        if active != "0":
            parser.error(
                "Dedicated database has unfinished requests; no worker started or questions submitted"
            )
    ROOT.mkdir(parents=True)
    dump(
        ROOT / "matrix.json",
        [{"case": case["id"], "trial": trial, "mode": mode} for case, trial, mode in jobs],
    )
    dump(ROOT / "manifest.json", manifest)
    if not args.live:
        print(
            f"Offline preflight: {manifest['planned']['browser']} browser + {manifest['planned']['api']} API questions; no servers, workers, browsers or models called."
        )
        return
    HEADLESS = args.headless
    worker = browser = None
    rows = []
    worker_env = {**os.environ, "PYTHONPATH": str(REPO / "agent/python/src")}
    if GRAPH_VERSION != "v2_localLLM":
        worker_env.update(AGENT_BACKEND_URL=API, AGENT_WORKER_TOKEN=connection["workerToken"],
                          AGENT_MODEL_TIMEOUT_SECONDS="90")
        worker_env["AGENT_V3_PLAN_REVIEW_ENABLED" if GRAPH_VERSION == "v3" else "AGENT_V2_PLAN_REVIEW_ENABLED"] = "true"
    manifest["startedAt"] = datetime.now(timezone.utc).isoformat()
    manifest["sourceSha256"] = {
        str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((REPO / "agent/python/src").rglob("*.py"))
    }
    dump(ROOT / "manifest.json", manifest)
    try:
        with (ROOT / "worker.log").open("w") as log, (ROOT / "results.jsonl").open("x") as output:
            worker = subprocess.Popen(
                worker_command(GRAPH_VERSION, args.env_file),
                cwd=REPO,
                env=worker_env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            for index, (case, trial, mode) in enumerate(jobs, 1):
                if worker.poll() is not None:
                    raise RuntimeError(
                        "Evaluation worker exited; preserve accepted requests and inspect local worker.log"
                    )
                directory = ROOT / "trials" / f"{case['id']}-{trial}"
                directory.mkdir(parents=True)
                workspace, refs, baseline = prepare(case, catalog)
                start = time.monotonic()
                if mode == "browser":
                    if browser is None:
                        browser = Browser()
                    outcome = browser.send({"cmd": "run", "case": case, "output": str(directory)})
                else:
                    if browser is not None:
                        browser.close()
                        browser = None
                    outcome = run_api(case, workspace, refs, baseline, directory)
                view = outcome.get("view")
                if not view or not outcome.get("requestId"):
                    dump(directory / "harness-error.json", outcome)
                    raise RuntimeError(
                        "Harness failed; preserve accepted.json and do not resubmit automatically"
                    )
                checked = flow_grader.grade(case, view, outcome.get("interactions", []), graph_version=GRAPH_VERSION)
                records = export_request(container, outcome["requestId"], directory)
                if not records["models"]:
                    raise RuntimeError(
                        "No model journal found in the supplied database; stop before another question"
                    )
                if (view.get("answerSnapshot") or {}).get("stepResults") and not any(
                    attempt["kind"] == "PLAN_REVIEW" for attempt in records["models"]
                ):
                    raise RuntimeError("Executed data steps without a plan review; stop evaluation")
                row = {
                    "expectedGraphVersion": GRAPH_VERSION, "evaluationMode": "real_model",
                    "case": case["id"],
                    "category": case["category"],
                    "trial": trial,
                    "mode": mode,
                    "seconds": time.monotonic() - start,
                    "grade": checked,
                    **outcome,
                    "recovery": classify(records["models"], checked["pass"]),
                }
                dump(directory / "result.json", row)
                output.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                output.flush()
                rows.append(row)
                dump(ROOT / "summary.json", summarize(rows))
                print(
                    json.dumps(
                        {
                            "completed": index,
                            "total": len(jobs),
                            "case": case["id"],
                            "mode": mode,
                            "deterministicPass": checked["pass"],
                            "answerReviewRequired": checked["answerReviewRequired"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    finally:
        try:
            if browser is not None:
                browser.close()
        finally:
            try:
                if worker is not None and worker.poll() is None:
                    # Stop only this evaluator's current request and worker; keep every accepted artifact.
                    try:
                        active = request("GET", "/api/workspace").get("activeAgentRequest")
                        owned = {
                            json.loads(path.read_text()).get("requestId")
                            for path in ROOT.glob("trials/*/accepted.json")
                        }
                        if active and active["requestId"] in owned:
                            cancel(active)
                    finally:
                        worker.terminate()
                        try:
                            worker.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            worker.kill()
                            worker.wait()
            finally:
                CLIENT.close()
    if len(rows) != len(jobs) or len({row["requestId"] for row in rows}) != len(jobs):
        raise RuntimeError(
            "Evaluation did not finish the selected distinct requests; never add replacements automatically"
        )
    print(f"Finished exactly {len(jobs)} questions. Review answers and screenshots before reporting final quality.")


if __name__ == "__main__":
    main()
