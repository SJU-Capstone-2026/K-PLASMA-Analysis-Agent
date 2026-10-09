"""Observation sentences are computed by code, never supplied by the model."""

from ..metric_registry import LABELS, format_value


def display(datum):
    return (
        f"{format_value(datum['value'], digits=2)} {datum['unit']}"
        if datum["status"] == "AVAILABLE"
        else (f"비가용 ({datum['reason']})")
    )


def observations(result):
    output: list[dict] = []

    def add(kind, key, metric, text):
        output.append(
            {
                "id": f"O{len(output) + 1}",
                "source": {"kind": kind, "key": key, "metric": metric},
                "text": text,
            }
        )

    for row in result["runs"]:
        for metric, value in row["metrics"].items():
            add(
                "run",
                row["key"],
                metric,
                f"{row['key']} ({row['ref']['runId']})의 {LABELS[metric]}: {display(value)}.",
            )
    for row in result["comparisons"]:
        metric = row["metric"]
        absolute = row["kind"] == "absolute_difference"
        text = f"{row['leftKey']} → {row['rightKey']}의 {LABELS[metric]} {'절대 차이' if absolute else '변화량'}: {display(row['difference'])}."
        if row["percentChange"] is not None:
            text += f" 기준 대비 변화율: {display(row['percentChange'])}."
        add("comparison", row["id"], metric, text)
    for row in result["summaries"]:
        add(
            "summary",
            row["id"],
            row["metric"],
            f"선택한 Run의 {LABELS[row['metric']]} 최솟값: {display(row['minimum'])}, "
            f"최댓값: {display(row['maximum'])}, 범위 폭: {display(row['range'])}. "
            f"가용 Run {row['availableCount']}개.",
        )
    direction_labels = {
        "increasing": "증가",
        "decreasing": "감소",
        "constant": "일정",
        "non_monotonic": "비단조",
        "insufficient_data": "자료 부족",
        "unavailable": "축값 중복 또는 데이터 비가용",
    }
    for row in result["trends"]:
        add(
            "trend",
            row["id"],
            row["metric"],
            f"다른 공정 조건이 같은 집합({', '.join(row['orderedKeys'])})의 {LABELS[row['axis']]} 순 "
            f"{LABELS[row['metric']]} 경향: {direction_labels[row['direction']]}. 관찰된 지점만 설명하며 인과를 확정하지 않습니다.",
        )
    return output
