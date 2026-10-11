"""Re-run C through the real Agent flow using PR #15's isolated M3 harness.

Only the LLM selection is fixed, exactly as in the existing A measurements.
Requires a separate checkout of benchmark commit fe8463e and its marked DB.
Never reads the service .env or uses its database.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--classpath", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[150, 10000, 100000, 1000000])
    parser.add_argument("--index", type=int, help="Internal: one fresh Python request")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    bench = args.benchmark_root.resolve()
    expected_commit = "fe8463e5c7dbe3ed2919bb43bad850f3292906c9"
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=bench, text=True).strip() == expected_commit
    sys.path.insert(0, str(bench / "scripts/performance/forward-lookup"))
    import seed

    # The seed fixture remains the identical benchmark fixture. Every Agent import
    # must resolve to this product checkout, not the old harness checkout.
    seed.ROOT = root
    import current_path
    import kplasma_agent.graphs.v1 as graph
    assert Path(graph.__file__).resolve().is_relative_to(root)
    seed.check_isolation()

    if args.index is not None:
        from kplasma_agent.backend_client import RequestBackend

        captured = {}
        original_context, original_save = RequestBackend.context, RequestBackend.save

        def context(self, *values, **options):
            result = original_context(self, *values, **options)
            captured["manifest"] = result
            return result

        def save(self, payload):
            captured["checkpoint"] = payload
            return original_save(self, payload)

        RequestBackend.context, RequestBackend.save = context, save
        ok = current_path.one(args.output, args.index)
        last = json.loads((args.output / "m3.jsonl").read_text().splitlines()[-1])
        if ok:
            # Finalization purges transient DB rows. Retain object references only
            # during execution, then compute sizes after the recorded end time.
            manifest = captured["manifest"]
            diagnostic = {
                "requestId": last["requestId"],
                "manifestRuns": len(manifest["runs"]),
                "catalogRefs": len(manifest["catalogRunRefs"]),
                "manifestBytes": len(json.dumps(manifest, ensure_ascii=False).encode()),
                "checkpointBytes": len(json.dumps(captured["checkpoint"], ensure_ascii=False).encode()),
            }
            assert diagnostic["manifestRuns"] == diagnostic["catalogRefs"] == 1
            current_path.append(args.output / "state-sizes.jsonl", {"index": args.index, **diagnostic})
        return 0 if ok else 1

    import suite
    # Reuse the original server, JVM flags and SQL counter. Only its application
    # classpath changes. SQL fixtures still come from the benchmark checkout.
    suite.ROOT = bench
    suite.LOCAL = args.classpath.parent
    if args.classpath.name != "classpath.txt":
        raise ValueError("Use a dedicated directory containing classpath.txt")
    args.output.mkdir(parents=True, exist_ok=True)
    for size in args.sizes:
        directory = args.output / str(size)
        if (directory / "m3.jsonl").exists():
            raise ValueError("Refusing to overwrite measurements: " + str(directory))
        generated = seed.seed(size, directory)
        previous = json.loads((bench / f".local/performance/forward-lookup/run-20261010/{size}/dataset.json").read_text())
        assert generated["inputHash"] == previous["inputHash"]
        assert generated["corpus"] == previous["corpus"]
        print(f"PRODUCT C SCALE {size}", flush=True)
        for index in range(10):
            server = suite.Server(directory / f"server-{index}.log")
            try:
                server.start()
                result = subprocess.run([
                    sys.executable, __file__, "--benchmark-root", str(bench),
                    "--classpath", str(args.classpath), "--output", str(directory), "--index", str(index),
                ], env=os.environ.copy(), timeout=90, check=False)
                if result.returncode:
                    raise RuntimeError(f"C failed at {size}/{index}; preserve diagnostics before retrying")
            finally:
                server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
