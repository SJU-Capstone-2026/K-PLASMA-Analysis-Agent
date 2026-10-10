"""M1/M2/pgbench runner. Results contain artificial data and stay local."""

import argparse
import gc
import json
import math
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys
import time

import httpx

from seed import ROOT, SEED, CONTAINER, check_isolation, sql

sys.path.insert(0, str(ROOT / "agent/python/src"))
from kplasma_agent.domain import lookup_forward, validate_result
from kplasma_agent.domain.common import public_run

URL = "http://127.0.0.1:18085"
ORDERS = ("abc", "bca", "cab", "acb", "cba")


def verify(query, result, rows, expected):
    assert result["resultStatus"] == "EXACT", result["resultStatus"]
    assert result["run"] == public_run(expected), (
        "Independent generator oracle mismatch"
    )
    assert result["usedRunRefs"] == [
        {"runId": expected["runId"], "runVersionId": expected["runVersionId"]}
    ]
    assert not result["excludedRuns"]
    assert validate_result(query, result, rows)["valid"], "Source replay mismatch"


def summarize(records):
    success = [r["totalMs"] for r in records if r["ok"]]
    return {
        "samples": len(records),
        "successes": len(success),
        "failures": len(records) - len(success),
        "meanMs": statistics.mean(success) if success else None,
        "medianMs": statistics.median(success) if success else None,
        "p95Ms": sorted(success)[math.ceil(0.95 * len(success)) - 1]
        if success
        else None,
        "maxMs": max(success) if success else None,
    }


def identity(client):
    response = client.get("/benchmark/identity")
    response.raise_for_status()
    data = response.json()
    assert data["marker"] == "forward-lookup-synthetic-only"
    assert data["database"] == "forward_lookup_bench"
    return data


def append(path, row):
    with path.open("a") as file:
        file.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def timeout_handler(*_):
    raise TimeoutError("60-second request deadline exceeded")


def sample(client, method, item):
    row = item["expected"]
    params = {
        "method": method,
        "pressure": row["pressure"],
        "source": row["sourcePower"],
        "bias": row["biasPower"],
    }
    start = time.perf_counter_ns()
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, 60)
    try:
        response = client.get("/benchmark/lookup", params=params)
        response.raise_for_status()
        received = time.perf_counter_ns()
        rows = response.json()["runs"]
        decoded = time.perf_counter_ns()
        result = lookup_forward(item["query"], rows)
        computed = time.perf_counter_ns()
        verify(item["query"], result, rows, row)
        end = time.perf_counter_ns()
        return {
            "ok": True,
            "totalMs": (end - start) / 1e6,
            "httpMs": (received - start) / 1e6,
            "decodeMs": (decoded - received) / 1e6,
            "computeMs": (computed - decoded) / 1e6,
            "validationMs": (end - computed) / 1e6,
            "rows": len(rows),
            "bytes": len(response.content),
            "sqlCount": int(response.headers["X-Bench-Queries"]),
            "javaFetchMs": float(response.headers["X-Bench-Fetch-Ms"]),
            "javaMappingMs": float(response.headers["X-Bench-Mapping-Ms"]),
            "javaSerializeMs": float(response.headers["X-Bench-Serialize-Ms"]),
        }
    except AssertionError:
        raise  # Invalid numerical results stop the benchmark, not just one sample.
    except Exception as error:
        return {
            "ok": False,
            "totalMs": (time.perf_counter_ns() - start) / 1e6,
            "error": type(error).__name__,
            "detail": str(error)[:500],
        }
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def measure(output, rounds=5, methods=("a", "b", "c")):
    dataset = json.loads((output / "dataset.json").read_text())
    corpus = dataset["corpus"]
    path = output / "m2.jsonl"
    if path.exists():
        raise RuntimeError("Use a new output directory; never overwrite prior samples")
    deadline = time.monotonic() + 3600
    disabled = set()
    with httpx.Client(base_url=URL, timeout=60) as client:
        runtime = identity(client)
        (output / "runtime.json").write_text(
            json.dumps(
                {
                    "java": runtime,
                    "python": sys.version,
                    "platform": platform.platform(),
                    "baseCommit": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                    "pid": os.getpid(),
                    "cache": "fixed warmup; no application result cache",
                    "requestDeadlineSeconds": 60,
                    "phaseBudgetSeconds": 3600,
                    "methods": list(methods),
                },
                indent=2,
            )
        )
        for method in methods:
            for item in corpus[:5]:
                record = sample(client, method, item)
                append(output / "warmup.jsonl", {"method": method, **record})
                if not record["ok"]:
                    disabled.add(method)
                    append(
                        output / "incomplete.jsonl",
                        {"method": method, "reason": "warmup failure", "error": record},
                    )
                    break
        for round_no, order in enumerate(ORDERS[:rounds]):
            for method in order:
                if method not in methods or method in disabled:
                    continue
                print(
                    f"M2 N={dataset['size']} round={round_no + 1} method={method}",
                    flush=True,
                )
                for item in corpus:
                    if time.monotonic() >= deadline:
                        append(
                            output / "incomplete.jsonl",
                            {"method": method, "reason": "scale time budget"},
                        )
                        return
                    record = sample(client, method, item)
                    append(
                        path,
                        {
                            "method": method,
                            "round": round_no + 1,
                            "index": item["index"],
                            **record,
                        },
                    )
                    if not record["ok"]:
                        disabled.add(method)
                        break
                gc.collect()  # Outside recorded request time, between method batches only.
        records = (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )
        summary = {
            m: summarize([r for r in records if r["method"] == m]) for m in "abc"
        }
        summary["disabledAfterFailure"] = sorted(disabled)
        (output / "m2-summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)


def rendered(method, row):
    text = (Path(__file__).parent / "sql" / f"{method}.sql").read_text()
    for key, value in [
        ("pressure", row["pressure"]),
        ("source", row["sourcePower"]),
        ("bias", row["biasPower"]),
    ]:
        text = text.replace(":" + key, str(int(value)))
    return text


def explain(output):
    dataset = json.loads((output / "dataset.json").read_text())
    for method in "abc":
        for index, item in enumerate(dataset["corpus"][:5]):
            text = sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                + rendered(method, item["expected"])
            )
            (output / f"explain-{method}-{index}.json").write_text(text)
    sizes = sql(
        "select json_agg(t) from (select relname,pg_table_size(oid) as table_bytes,pg_indexes_size(oid) as index_bytes from pg_class where relname in ('run','run_version','source_set','source_file')) t;"
    )
    (output / "table-sizes.json").write_text(sizes)
    settings = sql(
        "select json_agg(t) from (select name,setting,unit from pg_settings where name in ('shared_buffers','work_mem','max_parallel_workers_per_gather','effective_cache_size','random_page_cost','jit','server_version')) t;"
    )
    (output / "postgres-settings.json").write_text(settings)


def pgbench(output, seconds=60):
    check_isolation()
    corpus = json.loads((output / "dataset.json").read_text())["corpus"]
    for round_no, order in enumerate(ORDERS[:3]):
        for method in order:
            path = output / f"pgbench-{method}-{round_no + 1}.txt"
            if path.exists():
                raise RuntimeError("Refusing to overwrite pgbench evidence")
            lines = ["\\set pick random(0,39)"]
            for key, field in [
                ("pressure", "pressure"),
                ("source", "sourcePower"),
                ("bias", "biasPower"),
            ]:
                expression = (
                    "CASE "
                    + " ".join(
                        f"WHEN :pick = {index} THEN {item['expected'][field]}"
                        for index, item in enumerate(corpus)
                    )
                    + " END"
                )
                lines.append(f"\\set {key} {expression}")
            lines.append((Path(__file__).parent / "sql" / f"{method}.sql").read_text())
            script = "\n".join(lines)
            (output / f"pgbench-{method}.sql").write_text(script)
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    CONTAINER,
                    "sh",
                    "-c",
                    "cat > /tmp/forward-benchmark.sql",
                ],
                input=script,
                text=True,
                check=True,
            )
            command = [
                "docker",
                "exec",
                CONTAINER,
                "pgbench",
                "-U",
                "benchmark",
                "-d",
                "forward_lookup_bench",
                "-n",
                "-c",
                "1",
                "-j",
                "1",
                "-M",
                "simple",
                "--random-seed=" + str(SEED),
                "-T",
                str(seconds),
                "-f",
                "/tmp/forward-benchmark.sql",
            ]
            # Five untimed transactions warm the identical query path before each batch.
            warmup = command.copy()
            offset = warmup.index("-T")
            warmup[offset : offset + 2] = ["-t", "5"]
            warm = subprocess.run(warmup, capture_output=True, text=True, timeout=120)
            if warm.returncode:
                raise RuntimeError(warm.stderr)
            print(
                f"pgbench method={method} round={round_no + 1} duration={seconds}s",
                flush=True,
            )
            start = time.perf_counter()
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=seconds + 120
                )
                path.write_text(result.stdout + "\n" + result.stderr)
                append(
                    output / "pgbench-runs.jsonl",
                    {
                        "method": method,
                        "round": round_no + 1,
                        "elapsedSeconds": time.perf_counter() - start,
                        "returncode": result.returncode,
                    },
                )
                if result.returncode:
                    raise RuntimeError(result.stderr)
            except subprocess.TimeoutExpired:
                # Stop only this named benchmark container's pgbench process.
                subprocess.run(
                    ["docker", "exec", CONTAINER, "pkill", "-TERM", "pgbench"],
                    check=False,
                )
                path.write_text("TIMEOUT\n")
                append(
                    output / "pgbench-runs.jsonl",
                    {
                        "method": method,
                        "round": round_no + 1,
                        "elapsedSeconds": time.perf_counter() - start,
                        "error": "timeout",
                    },
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["measure", "explain", "pgbench"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=5, choices=range(1, 6))
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument(
        "--methods", nargs="+", choices=["a", "b", "c"], default=["a", "b", "c"]
    )
    args = parser.parse_args()
    if args.phase == "measure":
        measure(args.output, args.rounds, args.methods)
    elif args.phase == "explain":
        explain(args.output)
    else:
        pgbench(args.output, args.seconds)
