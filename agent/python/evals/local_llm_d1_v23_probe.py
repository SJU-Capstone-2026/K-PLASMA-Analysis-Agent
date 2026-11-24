"""One pass over five artificial plans; no Qwen generation or hidden warmups."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from threading import Event, Thread
import time
from types import SimpleNamespace


from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.core.budget import make_d1_counter, make_input_guard
from kplasma_agent.v2_local_llm.core.model_gateway import V2LocalLLMModelGateway, V2LocalLLMSettings
from kplasma_agent.v2_local_llm.core.plan_checks import review_questions
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context
from kplasma_agent.v2_local_llm.network import local_http_client
from kplasma_agent.v2_local_llm.runtime import (
    ModelRuntime,
    live_facts,
    memory_sample,
    model_lease,
    pressure_allowed,
    runtime_profile,
    verify_artifacts,
)
from .local_llm_measure import error_code, make_process_sampler

PHASES = [
    {"phase": "bf16-baseline", "precision": "bf16", "input_profile": "ko-full"},
    {"phase": "q8-baseline", "precision": "q8", "input_profile": "ko-full"},
    {"phase": "q8-english", "precision": "q8", "input_profile": "en-full"},
    {"phase": "q8-compact", "precision": "q8", "input_profile": "en-compact"},
    {"phase": "q8-no-view", "precision": "q8", "input_profile": "en-compact-no-view"},
]


def review_cases():
    from tests.v2_local_llm.plan_review_cases import cases, compare, literal, plan, selected_context

    bank = {case.id: case for case in cases()}
    rows = []

    def add(name, question, draft, expected, context=None, intended=None):
        rows.append(
            {
                "case": name,
                "expected": expected,
                "intended": intended,
                "payload": build_plan_review_context(draft, 1, question, [], context or {}, {}),
            }
        )

    question = "압력 4 mTorr, 소스 300 W, 바이어스 600 W 조건의 Run을 찾아줘."
    draft = plan(
        question,
        [
            {
                "id": "lookup",
                "kind": "tool",
                "tool": "forward_lookup",
                "inputs": {
                    "pressure": literal(4, "mTorr", question),
                    "source_power": literal(300, "W", question),
                    "bias_power": literal(600, "W", question),
                },
            }
        ],
    )
    add("good_lookup", question, draft, "PASS")
    case = bank["P08"]
    add("good_compare", case.question, case.good, "PASS", case.context)
    case = bank["P06"]
    add(
        "bad_unit",
        case.question,
        case.bad,
        "ISSUE",
        case.context,
        {"check": "filter.search.pressure", "choices": ["value_changed", "unit_changed"]},
    )
    case = bank["P10"]
    add(
        "bad_sort_direction",
        case.question,
        case.bad,
        "ISSUE",
        case.context,
        {"check": "ordering.search", "choices": ["direction_changed"]},
    )
    question = "선택한 두 Run의 RF 전류 밀도 첨두간 값을 비교해줘."
    draft = plan(
        question, [compare({"kind": "context_ref", "key": "selected_runs"}, ["current.halfPeakToPeak"])]
    )
    add(
        "bad_metric_definition",
        question,
        draft,
        "ISSUE",
        selected_context(),
        {"check": "outputs.compare", "choices": ["missing", "unexpected"]},
    )
    return rows


def measurements(rows):
    counts = [row["check_count"] for row in rows]
    if not counts or any(type(n) is not int or n <= 0 for n in counts):
        raise ValueError("LOCAL_D1_CHECK_COUNT_INVALID")
    total = sum(counts)
    tokens = [row.get("input_tokens") for row in rows]
    measured = all(type(n) is int and n > 0 for n in tokens)
    seconds = sum(row["seconds"] for row in rows)
    return {
        "checks": total,
        "input_tokens": sum(tokens) if measured else None,
        "average_tokens_per_check": sum(tokens) / total if measured else None,
        "seconds": seconds,
        "seconds_per_check": seconds / total,
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def graph_review_state(settings):
    from langgraph.checkpoint.memory import InMemorySaver
    from kplasma_agent.v2_local_llm.graph import build_v2_local_llm_graph

    graph = build_v2_local_llm_graph(SimpleNamespace(settings=settings), object(), InMemorySaver())
    config = {"configurable": {"thread_id": "d1-v23-preflight"}}
    graph.invoke({"plan_review_enabled": settings.plan_review_enabled}, config, interrupt_before=["plan"])
    snapshot = graph.get_state(config)
    if snapshot.values.get("plan_review_enabled") is not True or snapshot.next != ("plan",):
        raise ValueError("LOCAL_REQUIRED_BUDGET_OR_REVIEW_CHANGED")
    return {"plan_review_enabled": True}


def docker_sample():
    def command(*args):
        return subprocess.check_output(["docker", *args], text=True, timeout=10).strip()

    config = Path.home() / "Library/Group Containers/group.com.docker/settings-store.json"
    databases = [
        line.split()[0]
        for line in command("ps", "--format", "{{.ID}} {{.Image}}").splitlines()
        if len(line.split()) == 2 and line.split()[1].startswith("postgres:")
    ]
    oom = {}
    for container in databases:
        events = dict(
            line.split()
            for line in command("exec", container, "cat", "/sys/fs/cgroup/memory.events").splitlines()
        )
        oom[container] = int(events["oom_kill"])
    return {
        "limit_mib": json.loads(config.read_text())["MemoryMiB"],
        "mem_total_bytes": int(command("info", "--format", "{{.MemTotal}}")),
        "db_oom": oom,
    }


class ProbeMemory:
    def __init__(self, settings):
        self.policy = settings.memory_policy
        self.samples = []
        self.process_sample = make_process_sampler(settings)
        self.stop = Event()
        self.stage = "prepare"
        self.before = docker_sample()
        if self.before["limit_mib"] != 1536 or not self.before["db_oom"]:
            raise ValueError("LOCAL_DOCKER_LIMIT_MISMATCH")
        self.capture()
        self.monitor = Thread(target=self.sample, daemon=True)

    def capture(self):
        try:
            value = {**memory_sample(), "process_rss_bytes": self.process_sample()}
        except Exception:
            value = {"pressure": None, "swap_bytes": 0, "resident_bytes": 0}
        self.samples.append({**value, "stage": self.stage, "time": time.time()})

    def sample(self):
        while not self.stop.wait(0.5):
            self.capture()

    def check(self):
        self.capture()
        if any(not pressure_allowed(row["pressure"], self.policy) for row in self.samples):
            raise ValueError("LOCAL_MEMORY_PRESSURE")

    def finish(self):
        self.stop.set()
        self.monitor.join(timeout=10)
        self.capture()
        try:
            after = docker_sample()
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            after = None
        valid = (
            self.before == after
            and 1400 * 1024**2 < after["mem_total_bytes"] < 1536 * 1024**2
            and all(n == 0 for n in after["db_oom"].values())
            and all(pressure_allowed(row["pressure"], self.policy) for row in self.samples)
        )
        growth = max(0, max(row["swap_bytes"] for row in self.samples) - self.samples[0]["swap_bytes"])
        return {
            "passed": bool(valid and (self.policy == "development" or not growth)),
            "samples": self.samples,
            "docker_before": self.before,
            "docker_after": after,
            "peak_resident_bytes": max(row["resident_bytes"] for row in self.samples),
            "swap_growth_bytes": growth,
            "warning_samples": sum(row["pressure"] == 2 for row in self.samples),
        }


def run(settings, phase, output):
    expected = next(p for p in PHASES if p["phase"] == phase)
    if (settings.d1_precision, settings.d1_input_profile) != (
        expected["precision"],
        expected["input_profile"],
    ):
        raise ValueError("LOCAL_D1_PROBE_PROFILE_MISMATCH")
    output = Path(output)
    if output.exists():
        raise ValueError("LOCAL_D1_PROBE_OUTPUT_EXISTS")
    model_settings = V2LocalLLMSettings.from_env(settings)
    review_state = graph_review_state(model_settings)
    monitor = ProbeMemory(settings)
    monitor.monitor.start()
    rows, audit = [], []
    failure = None
    profile = None

    def capture(response):
        if response.request.url.path in {"/v1/count", "/v1/systemone"}:
            response.read()
            audit.append(
                {
                    "path": response.request.url.path,
                    "body": json.loads(response.request.content),
                    "status": response.status_code,
                    "result": response.json(),
                }
            )

    try:
        with (
            model_lease(),
            local_http_client(
                settings.d1_url, timeout=90, headers={"Authorization": "Bearer " + settings.d1_token}
            ) as client,
            local_http_client(
                settings.model_url, timeout=90, headers={"Authorization": "Bearer " + settings.api_key}
            ) as control,
        ):
            verify_artifacts(settings)
            facts = live_facts(settings)
            profile = runtime_profile(settings)
            client.event_hooks["response"].append(capture)
            runtime = ModelRuntime(settings, control, client)
            guard = make_input_guard(
                settings, d1_count=make_d1_counter(settings, client), prepare=runtime.prepare
            )
            gateway = V2LocalLLMModelGateway(model_settings, client, guard)
            try:
                for case in review_cases():
                    monitor.stage = case["case"]
                    monitor.check()
                    before = len(audit)
                    started = time.monotonic()
                    result, usage = gateway.review_plan(case["payload"])
                    elapsed = time.monotonic() - started
                    requests = audit[before:]
                    if (
                        [r["path"] for r in requests] != ["/v1/count", "/v1/systemone"]
                        or any(r["status"] != 200 for r in requests)
                        or requests[0]["body"] != requests[1]["body"]
                    ):
                        raise ValueError("LOCAL_D1_COUNT_WIRE_MISMATCH")
                    counted, raw = [r["result"] for r in requests]
                    check_count = len(review_questions(case["payload"]))
                    if (
                        sum(counted["group_counts"]) != raw["usage"]["input_tokens"]
                        or len(counted["group_counts"]) != check_count
                        or any(len(ids) != 1 for ids in counted["group_question_ids"])
                        or raw["local_metrics"].get("released") is not True
                    ):
                        raise ValueError("LOCAL_D1_PACK_MISMATCH")
                    answers = {a["name"]: a["choice"] for a in result.get("checks", [])}
                    intended = case["intended"]
                    correct = result["status"] == case["expected"]
                    reason_correct = correct and (
                        intended is None or answers.get(intended["check"]) in intended["choices"]
                    )
                    row = {
                        "case": case["case"],
                        "expected": case["expected"],
                        "status": result["status"],
                        "status_correct": correct,
                        "intended_reason_correct": reason_correct,
                        "checks": answers,
                        "seconds": elapsed,
                        "check_count": check_count,
                        "input_tokens": raw["usage"]["input_tokens"],
                        "usage": usage,
                        "local_metrics": raw["local_metrics"],
                        "original_digest": digest(case["payload"]),
                        "count_matches_inference": True,
                    }
                    rows.append(row)
                    monitor.check()
                    print(
                        json.dumps({key: row[key] for key in ("case", "status", "seconds", "input_tokens")}),
                        flush=True,
                    )
                    if result["status"] == "UNAVAILABLE":
                        raise ValueError("LOCAL_D1_REVIEW_UNAVAILABLE")
                if live_facts(settings) != facts:
                    raise ValueError("LOCAL_RUNTIME_PROFILE_MISMATCH")
            finally:
                for model in (gateway.planner, gateway.writer):
                    if model.client is not None:
                        model.client.close()
    except Exception as error:
        failure = error_code(error)
    finally:
        memory = monitor.finish()
    report = {
        **expected,
        "synthetic_only": True,
        "repetitions": 1,
        "review_state": review_state,
        "memory_policy": settings.memory_policy,
        "rows": rows,
        "memory": memory,
        "error": failure,
        "runtime_profile": profile,
        "inference_calls": sum(r["path"] == "/v1/systemone" for r in audit),
        "totals": measurements(rows) if rows else None,
        "audit": audit,
    }
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(report, handle, indent=2)
    if failure or len(rows) != 5 or not memory["passed"]:
        raise ValueError(failure or "LOCAL_D1_COMPARISON_INCOMPLETE")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--phase", choices=[p["phase"] for p in PHASES], required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(Settings.from_env(args.env_file), args.phase, args.output)
