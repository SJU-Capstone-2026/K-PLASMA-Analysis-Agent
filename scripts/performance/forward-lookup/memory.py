"""Separate RSS diagnostic; never mix ps sampling overhead into M2 latency results."""

import argparse
import json
import os
from pathlib import Path
import subprocess
from threading import Event, Thread

import httpx
from run import URL, append, identity, sample


def rss(pids):
    text = subprocess.check_output(
        ["ps", "-o", "pid=,rss=", "-p", ",".join(map(str, pids))], text=True
    )
    return {
        int(parts[0]): int(parts[1]) * 1024
        for line in text.splitlines()
        if len(parts := line.split()) == 2
    }


def memory(output, method, rep):
    corpus = json.loads((output / "dataset.json").read_text())["corpus"]
    with httpx.Client(base_url=URL, timeout=60) as client:
        java = identity(client)["pid"]
        for item in corpus[:5]:
            record = sample(client, method, item)
            if not record["ok"]:
                append(
                    output / "memory.jsonl",
                    {
                        "method": method,
                        "rep": rep,
                        "ok": False,
                        "phase": "warmup",
                        "error": record,
                    },
                )
                return 1
        pids = (os.getpid(), java)
        baseline = rss(pids)
        peaks = baseline.copy()
        stop = Event()

        def poll():
            while not stop.wait(0.1):
                for pid, value in rss(pids).items():
                    peaks[pid] = max(peaks.get(pid, 0), value)

        thread = Thread(target=poll, daemon=True)
        thread.start()
        try:
            result = sample(client, method, corpus[5])
        finally:
            stop.set()
            thread.join(timeout=2)
            for pid, value in rss(pids).items():
                peaks[pid] = max(peaks.get(pid, 0), value)
        append(
            output / "memory.jsonl",
            {
                "method": method,
                "rep": rep,
                "ok": result["ok"],
                "sampleIntervalMs": 100,
                "pythonBaselineBytes": baseline.get(pids[0]),
                "pythonPeakBytes": peaks.get(pids[0]),
                "javaBaselineBytes": baseline.get(java),
                "javaPeakBytes": peaks.get(java),
            },
        )
        return 0 if result["ok"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method", choices=["a", "b", "c"], required=True)
    parser.add_argument("--rep", type=int, required=True)
    args = parser.parse_args()
    raise SystemExit(memory(args.output, args.method, args.rep))
