"""Sequential orchestration: no simultaneous benchmarks or hidden service workloads."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
from seed import ROOT, SIZES, seed, check_isolation
from run import URL, append

HERE = Path(__file__).parent
LOCAL = ROOT / ".local/performance/forward-lookup"


class Server:
    def __init__(self, log):
        self.log = log
        self.process = None

    def start(self):
        java = Path(os.environ["JAVA_HOME"]) / "bin/java"
        classpath = (LOCAL / "classpath.txt").read_text()
        self.output = self.log.open("a")
        self.process = subprocess.Popen(
            [
                str(java),
                "-Xms256m",
                "-Xmx4g",
                "-XX:+ExitOnOutOfMemoryError",
                "-Xlog:gc:file=" + str(self.log) + ".gc:time,uptime,level,tags",
                "-cp",
                classpath,
                "com.kplasma.analysisagent.performance.ForwardLookupBenchmarkSupport",
            ],
            cwd=ROOT / "backend",
            stdout=self.output,
            stderr=subprocess.STDOUT,
        )
        for _ in range(120):
            if self.process.poll() is not None:
                raise RuntimeError("Benchmark Java server exited; see " + str(self.log))
            try:
                data = httpx.get(URL + "/benchmark/identity", timeout=1).json()
                if data.get("pid") != self.process.pid:
                    raise RuntimeError("Port already belongs to another server")
                return
            except (httpx.HTTPError, ValueError):
                time.sleep(0.5)
        raise RuntimeError("Benchmark server readiness timeout")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if hasattr(self, "output"):
            self.output.close()


def command(module, *args, timeout=3600):
    return subprocess.run(
        [sys.executable, str(HERE / module), *map(str, args)], cwd=ROOT, timeout=timeout
    ).returncode


def suite(output, sizes, skip_pgbench=False):
    check_isolation()
    output.mkdir(parents=True, exist_ok=True)
    for size in sizes:
        directory = output / str(size)
        server = Server(directory / "server.log")
        directory.mkdir(exist_ok=True)
        if not (directory / "dataset.json").exists():
            seed(size, directory)
        else:
            # Resume only after confirming the current database still has this exact dataset size.
            from seed import sql

            assert int(sql("select count(*) from run;")) == size
        print(f"SCALE {size}", flush=True)
        try:
            if not (directory / "explain-c-4.json").exists():
                assert command("run.py", "explain", "--output", directory) == 0
            if not (directory / "m2-summary.json").exists():
                server.start()
                code = command("run.py", "measure", "--output", directory, timeout=3660)
                append(
                    directory / "execution.jsonl", {"phase": "M2", "returncode": code}
                )
                server.stop()
                if code:
                    raise RuntimeError("M2 failed: resolve the error before continuing")
            # Fresh Java + Python process per M3 request: no previous turn/checkpoint accumulation.
            if not (directory / "m3.jsonl").exists():
                for index in range(10):
                    server.start()
                    try:
                        code = command(
                            "current_path.py",
                            "--output",
                            directory,
                            "--index",
                            index,
                            timeout=90,
                        )
                    except subprocess.TimeoutExpired:
                        append(
                            directory / "m3.jsonl",
                            {
                                "index": index,
                                "ok": False,
                                "error": "process_timeout",
                                "totalMs": 90000,
                            },
                        )
                        code = 1
                    finally:
                        server.stop()
                    if code:
                        append(
                            directory / "execution.jsonl",
                            {
                                "phase": "M3",
                                "stoppedAfterIndex": index,
                                "reason": "failure; no automatic retry",
                            },
                        )
                        break
            if not (directory / "memory.jsonl").exists():
                for method in "abc":
                    for rep in range(1, 4):
                        server.start()
                        try:
                            code = command(
                                "memory.py",
                                "--output",
                                directory,
                                "--method",
                                method,
                                "--rep",
                                rep,
                                timeout=420,
                            )
                        except subprocess.TimeoutExpired:
                            append(
                                directory / "memory.jsonl",
                                {
                                    "method": method,
                                    "rep": rep,
                                    "ok": False,
                                    "error": "process_timeout",
                                },
                            )
                            code = 1
                        finally:
                            server.stop()
                        if code:
                            break
            if not skip_pgbench and not all(
                (directory / f"pgbench-{m}-{r}.txt").exists()
                for m in "abc"
                for r in range(1, 4)
            ):
                assert (
                    command("run.py", "pgbench", "--output", directory, timeout=1800)
                    == 0
                )
        finally:
            server.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", choices=SIZES, default=SIZES)
    parser.add_argument("--skip-pgbench", action="store_true")
    args = parser.parse_args()
    suite(args.output.resolve(), args.sizes, args.skip_pgbench)
