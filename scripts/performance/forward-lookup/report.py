"""Aggregate only observed samples; missing measurements remain visibly missing."""

import argparse
import json
from pathlib import Path
import re
import statistics

from run import summarize
from seed import SIZES


def records(path):
    return (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )


def number(value):
    return "미완료" if value is None else f"{value:,.3f}"


def supplement_samples(directory, supplement):
    """Only fill unmeasured methods on an identical dataset; never replace failed evidence."""
    original = records(directory / "m2.jsonl")
    additional = records(supplement / "m2.jsonl") if supplement else []
    if not additional:
        return original, []
    left = json.loads((directory / "dataset.json").read_text())
    right = json.loads((supplement / "dataset.json").read_text())
    for key in ("size", "inputHash", "corpus"):
        if left[key] != right[key]:
            raise ValueError("Supplementary dataset differs: " + key)
    first = json.loads((directory / "runtime.json").read_text())
    second = json.loads((supplement / "runtime.json").read_text())
    for key in ("baseCommit", "python", "platform", "requestDeadlineSeconds"):
        if first[key] != second[key]:
            raise ValueError("Supplementary runtime differs: " + key)
    for key in ("java", "maxHeapBytes", "database"):
        if first["java"][key] != second["java"][key]:
            raise ValueError("Supplementary Java runtime differs: " + key)
    methods = sorted({row["method"] for row in additional})
    if {row["method"] for row in original}.intersection(methods):
        raise ValueError("Refusing to replace or mix existing method samples")
    return original + additional, methods


def build(root, supplement_root=None):
    result = {}
    lines = [
        "# 순방향 조회 벤치마크 측정 집계",
        "",
        "인공 데이터, 단일 요청. 제품 조회 코드 적용 전의 접근 방식 비교이며 Agent 전체 개선율이 아니다.",
        "",
        "## 조회 구간 M2",
        "",
        "| Run 수 | 방식 | 성공 / 측정 | 평균 ms | p95 ms | 반환 행 | 응답 MiB | SQL 수 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for size in SIZES:
        directory = root / str(size)
        supplement = supplement_root / str(size) if supplement_root else None
        samples, supplemented = supplement_samples(directory, supplement)
        result[str(size)] = {
            "m2": {},
            "m1": {},
            "pgbench": {},
            "memory": {},
            "m3": {},
            "incomplete": records(directory / "incomplete.jsonl"),
            "warmupFailures": [
                r for r in records(directory / "warmup.jsonl") if not r["ok"]
            ],
            "execution": records(directory / "execution.jsonl"),
            "pgbenchAttempts": records(directory / "pgbench-runs.jsonl"),
            "supplementedMethods": supplemented,
        }
        if supplemented:
            result[str(size)]["supplementWarmupFailures"] = [
                r for r in records(supplement / "warmup.jsonl") if not r["ok"]
            ]
        for method in "abc":
            selected = [row for row in samples if row["method"] == method]
            good = [row for row in selected if row["ok"]]
            summary = summarize(selected)
            for metric in (
                "rows",
                "bytes",
                "sqlCount",
                "httpMs",
                "decodeMs",
                "computeMs",
                "validationMs",
                "javaFetchMs",
                "javaMappingMs",
                "javaSerializeMs",
            ):
                summary[metric] = (
                    statistics.mean([r[metric] for r in good]) if good else None
                )
            result[str(size)]["m2"][method] = summary
            mib = summary["bytes"] / 1024**2 if summary["bytes"] is not None else None
            lines.append(
                f"| {size:,} | {method.upper()} | {summary['successes']} / {summary['samples']} | {number(summary['meanMs'])} | {number(summary['p95Ms'])} | {number(summary['rows'])} | {number(mib)} | {number(summary['sqlCount'])} |"
            )
            plans = [
                json.loads(path.read_text())[0]
                for path in sorted(directory.glob(f"explain-{method}-*.json"))
            ]
            if plans:
                result[str(size)]["m1"][method] = {
                    "samples": len(plans),
                    "meanMs": statistics.mean(p["Execution Time"] for p in plans),
                    "returnedRows": plans[0]["Plan"]["Actual Rows"],
                    "sharedHitBlocks": statistics.mean(
                        p["Plan"].get("Shared Hit Blocks", 0) for p in plans
                    ),
                    "sharedReadBlocks": statistics.mean(
                        p["Plan"].get("Shared Read Blocks", 0) for p in plans
                    ),
                    "tempReadBlocks": statistics.mean(
                        p["Plan"].get("Temp Read Blocks", 0) for p in plans
                    ),
                    "tempWrittenBlocks": statistics.mean(
                        p["Plan"].get("Temp Written Blocks", 0) for p in plans
                    ),
                }
            pg = []
            for path in sorted(directory.glob(f"pgbench-{method}-*.txt")):
                text = path.read_text()
                count = re.search(
                    r"number of transactions actually processed: (\d+)", text
                )
                latency = re.search(r"latency average = ([\d.]+) ms", text)
                tps = re.search(r"tps = ([\d.]+)", text)
                failures = re.search(r"number of failed transactions: (\d+)", text)
                if all((count, latency, tps, failures)):
                    pg.append(
                        {
                            "transactions": int(count[1]),
                            "latencyMs": float(latency[1]),
                            "tps": float(tps[1]),
                            "failures": int(failures[1]),
                        }
                    )
            result[str(size)]["pgbench"][method] = pg
            memory = [
                r for r in records(directory / "memory.jsonl") if r["method"] == method
            ]
            result[str(size)]["memory"][method] = memory
        m3 = records(directory / "m3.jsonl")
        result[str(size)]["m3"] = {
            "samples": len(m3),
            "successes": sum(r["ok"] for r in m3),
            "meanMs": statistics.mean([r["totalMs"] for r in m3 if r["ok"]])
            if any(r["ok"] for r in m3)
            else None,
            "failures": [
                {k: v for k, v in r.items() if k != "spans"} for r in m3 if not r["ok"]
            ],
        }
    lines += [
        "",
        "## SQL 실행 계획 M1",
        "",
        "| Run 수 | 방식 | 계획 표본 | 평균 실행 ms | 반환 행 | shared hit | shared read |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for size, summary in result.items():
        for method, row in summary["m1"].items():
            lines.append(
                f"| {int(size):,} | {method.upper()} | {row['samples']} | {number(row['meanMs'])} | {number(row['returnedRows'])} | {number(row['sharedHitBlocks'])} | {number(row['sharedReadBlocks'])} |"
            )
    lines += [
        "",
        "## pgbench 반복 조회",
        "",
        "| Run 수 | 방식 | 완료 라운드 | 라운드 평균 지연의 중앙값 ms | 평균 처리율 tx/s | 실패 tx |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for size, summary in result.items():
        for method, rows in summary["pgbench"].items():
            if rows:
                lines.append(
                    f"| {int(size):,} | {method.upper()} | {len(rows)} | {number(statistics.median(r['latencyMs'] for r in rows))} | {number(statistics.mean(r['tps'] for r in rows))} | {sum(r['failures'] for r in rows)} |"
                )
    lines += [
        "",
        "## 현재 Agent 경로 M3",
        "",
        "| Run 수 | 성공 / 실행 | 성공 표본 평균 ms |",
        "|---:|---:|---:|",
    ]
    for size, summary in result.items():
        row = summary["m3"]
        lines.append(
            f"| {int(size):,} | {row['successes']} / {row['samples']} | {number(row['meanMs'])} |"
        )
    lines += [
        "",
        "M3는 새로운 Java/Python 프로세스와 빈 대화에서 수행한 비용 진단이다. M2의 준비된 조회 지연과 직접 비교하지 않는다.",
        "실패 원문·미완료 이유·메모리·세부 구간은 로컬 집계 JSON과 원자료를 함께 확인한다. 누락값을 0으로 해석하지 않는다.",
        "",
    ]
    for size, summary in result.items():
        if summary["supplementedMethods"]:
            lines.append(
                f"{int(size):,}건 M2 {', '.join(summary['supplementedMethods']).upper()}는 원 실행에서 측정되지 않아 같은 데이터·설정의 새 JVM 실행으로 보충했다. 원 준비 실패 기록은 보존했다."
            )
    return result, "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--supplement-root", type=Path)
    args = parser.parse_args()
    result, markdown = build(args.output, args.supplement_root)
    (args.output / "aggregate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    (args.output / "aggregate.md").write_text(markdown)
    print(markdown)
