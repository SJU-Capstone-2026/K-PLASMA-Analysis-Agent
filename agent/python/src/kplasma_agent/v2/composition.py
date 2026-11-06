"""Render numerical facts from saved steps and validate the model's prose."""

import re
from collections import Counter
from typing import Any, cast

from ..domain.common import scalar
from ..domain.reverse import check_rule
from ..metric_registry import CONDITION_KEYS, LABELS, OUTPUT_METRICS, UNITS, format_value, is_finite
from .contracts import DataAnswerDraft, Evidence, GeneralAnswerDraft, Quantity, StepResult


VALUE_REFERENCE = re.compile(r"\{\{value:([^{}|]+)(?:\|([^{}|]+))?\}\}")


def collect_evidence(results: list[StepResult]) -> list[Evidence]:
    entries = []
    for result in results:
        for field, values in result.outputs.items():
            if field in {"toolResult", "candidates"}:
                continue
            for value in values if isinstance(values, list) else [values]:
                if not isinstance(value, dict) or "value" not in value:
                    continue
                quantity = Quantity.model_validate(value)
                source_ids = quantity.evidence_ids
                ref = quantity.run_ref
                identifier = source_ids[0] if ref and source_ids else f"{result.executionId}:{field}"
                entries.append(Evidence(id=identifier, executionId=result.executionId,
                                        field=quantity.field, value=quantity.value, unit=quantity.unit, runRef=ref))
        raw = result.outputs.get("toolResult")
        if isinstance(raw, dict):
            for observation in cast(list[dict[str, Any]], raw.get("observations", [])):
                entries.append(Evidence(id=f"{result.executionId}:{observation['id']}",
                                        executionId=result.executionId, field="observation",
                                        value=observation["text"], unit=None))
        candidates = result.outputs.get("candidates")
        if isinstance(candidates, list):
            names = [ref["runId"] for ref in candidates if isinstance(ref, dict) and isinstance(ref.get("runId"), str)]
            entries.append(Evidence(id=f"{result.executionId}:candidates", executionId=result.executionId,
                                    field="candidates", value=names, unit=None))
    return entries



def collect_search_evidence(results: list[StepResult]) -> list[dict[str, Any]]:
    """Project the applied filters and measured values from saved search results."""
    searches = []
    for result in results:
        raw = cast(dict[str, Any], result.outputs.get("toolResult"))
        if result.status not in {"verified", "empty"} or not isinstance(raw, dict):
            continue
        if raw.get("kind") == "forward_lookup":
            candidates = []
            for run in raw["candidates"]:
                measurements = []
                for metric in (*CONDITION_KEYS, *OUTPUT_METRICS):
                    value, reason = scalar(run, metric)
                    measurements.append({"metric": metric, "value": value, "unit": UNITS[metric], "reason": reason})
                candidates.append({"runRef": {"runId": run["runId"], "runVersionId": run["runVersionId"]},
                                   "measurements": measurements})
            searches.append({
                "stepId": result.stepId, "executionId": result.executionId, "status": result.status,
                "resultStatus": raw["resultStatus"],
                "requestedConditions": {
                    metric: {"value": value, "unit": UNITS[metric]}
                    for metric, value in raw["requestedConditions"].items()
                },
                "candidates": candidates,
            })
            continue
        if raw.get("kind") != "reverse_search":
            continue
        constraints = raw["constraints"]
        goals = raw["goals"]
        candidates = []
        for ref in raw["commonRunRefs"]:
            run = raw["runsByVersion"].get(ref["runVersionId"])
            measurements = []
            for rule in constraints:
                value, reason = scalar(run, rule["metric"]) if run else (None, "MISSING_RUN")
                measurements.append({
                    "metric": rule["metric"], "operator": rule["operator"], "value": value, "unit": rule["unit"],
                    "satisfied": check_rule(value, rule) if value is not None else None, "reason": reason,
                })
            for goal in goals:
                value, reason = scalar(run, goal["metric"]) if run else (None, "MISSING_RUN")
                measurements.append({
                    "metric": goal["metric"], "direction": goal["direction"],
                    "value": value, "unit": goal["unit"], "reason": reason,
                })
            candidates.append({"runRef": ref, "measurements": measurements})
        searches.append({"stepId": result.stepId, "executionId": result.executionId, "status": result.status,
                         "constraints": constraints, "goals": goals, "candidates": candidates})
    return searches


def collect_comparison_coverage(results: list[StepResult]) -> list[dict[str, Any]]:
    coverage = []
    for result in results:
        raw = cast(dict[str, Any], result.outputs.get("toolResult"))
        if not isinstance(raw, dict) or raw.get("kind") != "compare_runs":
            continue
        runs = raw["runs"]
        available_values = {}
        raw_values = {}
        for metric in raw["metricIds"]:
            values = [run["metrics"][metric] for run in runs]
            available_values[metric] = sum(datum["status"] == "AVAILABLE" for datum in values)
            count = sum(
                datum["status"] == "UNAVAILABLE" and (datum.get("sourceValue") or {}).get("value") is not None
                for datum in values
            )
            if count:
                raw_values[metric] = count
        outputs = raw.get("outputs", [])
        coverage.append({
            "executionId": result.executionId,
            "runCount": len(runs),
            "availableRunValues": available_values,
            "rawRunValues": raw_values,
            "plotOutputs": {
                plot: dict(Counter(
                    row["reason"] or row["status"] for row in outputs if row["outputId"] == plot
                ))
                for plot in raw.get("plotIds", [])
            },
        })
    return coverage


def interpretation_review_payload(draft: DataAnswerDraft, evidence: list[dict], results: list[StepResult]) -> dict:
    cited_ids = {identifier for item in draft.interpretations for identifier in item.evidence_ids}
    cited = [row for row in evidence if row["id"] in cited_ids]
    payload = {"interpretations": [item.model_dump(mode="json") for item in draft.interpretations],
               "evidence": cited}
    search_ids = {row["executionId"] for row in cited if row["field"] == "candidates"}
    if search_ids:
        payload["search_evidence"] = collect_search_evidence([step for step in results if step.executionId in search_ids])
    return payload


def _display_number(value, unit):
    number = format_value(value, digits=2)
    if value != 0 and number == "0":
        number = f"{value:.6g}"
    if unit == "%":
        return f"{number}%"
    return f"{number} {unit}" if unit and unit != "1" else number


def collect_numeric_values(results: list[StepResult], evidence: list[Evidence]) -> dict[str, dict[str, str]]:
    """Make numeric parts of existing evidence addressable without parsing observation prose."""
    values = {item.id: {"value": _display_number(item.value, item.unit)}
              for item in evidence if is_finite(item.value)}
    for result in results:
        raw = cast(dict[str, Any], result.outputs.get("toolResult"))
        if not isinstance(raw, dict) or raw.get("kind") != "compare_runs":
            continue
        runs = {row["key"]: {**row["conditions"], **row["metrics"]} for row in raw.get("runs", [])}
        comparisons = {row["id"]: {"value": row["difference"], "percent": row.get("percentChange")}
                       for row in raw.get("comparisons", [])}
        summaries = {row["id"]: {field: row[field] for field in ("minimum", "maximum", "range")}
                     for row in raw.get("summaries", [])}
        for observation in raw.get("observations", []):
            source = observation.get("source", {})
            kind, key = source.get("kind"), source.get("key")
            if kind == "run":
                parts = {"value": runs.get(key, {}).get(source.get("metric"))}
            elif kind == "comparison":
                parts = comparisons.get(key, {})
            else:
                parts = summaries.get(key, {}) if kind == "summary" else {}
            numbers = {field: _display_number(datum["value"], datum["unit"]) for field, datum in parts.items()
                       if datum and datum["status"] == "AVAILABLE" and is_finite(datum["value"])}
            if numbers:
                values[f"{result.executionId}:{observation['id']}"] = numbers
    return values


def _render_fact(evidence: Evidence) -> str:
    if evidence.field == "observation":
        return str(evidence.value)
    if evidence.field == "candidates" and isinstance(evidence.value, list):
        return f"검색 결과 {len(evidence.value)}개" if evidence.value else "조건에 맞는 후보가 없습니다."
    label = LABELS.get(evidence.field, evidence.field)
    prefix = f"{evidence.runRef.runId}의 " if evidence.runRef else "계산된 "
    unit = f" {evidence.unit}" if evidence.unit and evidence.unit != "1" else ""
    return f"{prefix}{label}: {evidence.value}{unit}"


def fill_value_references(text, cited_ids, numeric_values=None, *, evidence_ids=None):
    """Resolve only complete, cited references using the code-formatted saved values."""
    def substitute(match):
        identifier, part = match[1], match[2] or "value"
        if evidence_ids is not None and identifier not in evidence_ids:
            raise ValueError("answer references unknown evidence")
        if identifier not in cited_ids:
            raise ValueError(f"value reference not cited in evidence_ids: {identifier}")
        value = (numeric_values or {}).get(identifier, {}).get(part)
        if value is None:
            raise ValueError(f"value reference unavailable: {identifier}|{part}")
        return value

    text = VALUE_REFERENCE.sub(substitute, text)
    if "{{value:" in text:
        raise ValueError("invalid value reference format")
    return text


def assemble_answer(draft, mode, evidence, issue=None, *, numeric_values=None):
    if mode == "general_only":
        general = GeneralAnswerDraft.model_validate(draft)
        return "\n\n".join(general.paragraphs), general.model_dump(mode="json")
    data = DataAnswerDraft.model_validate(draft)
    by_id = {item.id: item for item in evidence}
    references = [*data.fact_ids,
                  *(identifier for item in data.interpretations for identifier in item.evidence_ids),
                  *(identifier for item in data.limitations for identifier in item.evidence_ids)]
    if any(identifier not in by_id for identifier in references):
        raise ValueError("answer references unknown evidence")
    if evidence and not data.fact_ids:
        raise ValueError("data answer must show selected facts")
    for item in [*data.interpretations, *data.limitations]:
        item.text = fill_value_references(item.text, item.evidence_ids, numeric_values, evidence_ids=by_id)
    for item in data.interpretations:
        item.assumptions = [fill_value_references(text, item.evidence_ids, numeric_values, evidence_ids=by_id)
                            for text in item.assumptions]
    free_text = [text for item in data.interpretations for text in [item.text, *item.assumptions]]
    free_text.extend(item.text for item in data.limitations)
    rendered = [_render_fact(by_id[identifier]) for identifier in dict.fromkeys(data.fact_ids)]
    return "\n\n".join([*rendered, *free_text, *([issue] if issue else [])]), data.model_dump(mode="json")


def facts_only(evidence, issue):
    return "\n\n".join([*map(_render_fact, evidence), *([issue] if issue else [])]) or "확인된 결과가 없습니다."
