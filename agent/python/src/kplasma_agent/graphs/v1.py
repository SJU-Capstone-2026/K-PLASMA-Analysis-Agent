"""v1: one native tool selection, deterministic execution, optional grounded answer."""

from copy import deepcopy
import re
import time
from typing import TypedDict
from pydantic import ValidationError
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from .. import tracing
from ..tools import TOOL_MODELS, SELECTION_PROMPT, GENERAL_PROMPT
from ..model_client import ModelError
from ..answer_contracts import AnswerSnapshotV2, GeneralAnswerResult
from ..domain import lookup_forward, search_reverse, validate_result
from ..domain.compare import compare_selected
from ..domain.common import DomainError
from ..domain.grounding import validate_grounding, validate_native_comparison_metrics
from ..explanations.answers import COMPARISON_PROMPT, validate_answer, comparison_draft_model
from ..metric_registry import CONDITION_KEYS, LABELS, UNITS, NumericError, normalize_value

# Import compatibility for evaluation clients; production selection uses native tools.
INTERPRET_PROMPT = SELECTION_PROMPT
EXPLAIN_PROMPT = COMPARISON_PROMPT


class GraphState(TypedDict, total=False):
    request_id: str
    question: str
    context: dict
    input_history: list
    interpretation: dict
    tool_selection: dict
    native_items: list
    selection_payload: dict
    operation: dict
    route: str
    pending: dict
    reply: dict
    manifest: dict
    source: list
    inputs: dict
    result: dict
    verified: bool
    evidence: dict
    draft: dict
    repair_error: str
    explanation_repairs: int
    model_metadata: dict
    context_provenance: dict
    answer: dict
    comparison_answer: dict
    comparison_reference: dict
    unit_assumptions: list


def _request_input(state, message, reason, fields=None, options=None):
    return {
        "route": "wait",
        "pending": {
            "type": "text",
            "id": f"{state['request_id']}:{len(state.get('input_history', []))}:{reason}",
            "message": message,
            "reason": reason,
            "fields": fields or [],
            "options": options or [],
        },
    }


def _picker(state, baseline_required=False):
    pending = {
        "type": "run_selection",
        "id": f"{state['request_id']}:{len(state.get('input_history', []))}:runs",
        "message": "비교할 실제 실험을 두 개 이상 선택해 주세요. 대화 속 표현만으로 실험을 추정하지 않습니다.",
        "minSelections": 2,
        "baselineRequired": baseline_required,
    }
    pending["optionsUrl"] = (
        f"/api/agent/requests/{state['request_id']}/run-options?pendingInputId={pending['id']}"
    )
    return {"route": "wait", "pending": pending}


def _scope_choices(question):
    # Detect explicit independent lookup/search + comparison commands, not comparison + explanation.
    patterns = {
        "forward_lookup": r"조회(?:해|하)|\b(?:look\s*up|retrieve)\b",
        "reverse_search": r"후보[^.!?\n]{0,30}(?:찾|탐색)|\bsearch\b",
        "compare_runs": r"비교(?:해|하)|\bcompare\b",
    }
    choices = [kind for kind, pattern in patterns.items() if re.search(pattern, question, re.IGNORECASE)]
    return choices if "compare_runs" in choices and len(choices) > 1 else []


def _context_refs(context):
    refs = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("runId") and value.get("runVersionId"):
                refs.append(value)
            else:
                for nested in value.values():
                    visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for key in ("activeRun", "selectedRunRef", "candidateReferences", "comparisonContext"):
        visit(context.get(key))
    return refs


def _resolve(selector, manifest, context):
    if not selector:
        return None
    kind = selector["kind"]
    if kind == "run_id":
        ref = {"runId": selector["run_id"], "runVersionId": selector.get("run_version_id")}
    elif kind in ("comparison_baseline", "comparison_target"):
        previous = (context.get("comparisonContext") or {}).get("result", {})
        previous = previous.get("comparison", previous)
        ref = previous.get("baseline" if kind == "comparison_baseline" else "target")
    else:
        ref = context.get("activeRun" if kind == "reference_run" else "selectedRunRef")
    if not isinstance(ref, dict):
        return None
    candidates = manifest.get("runs", []) + manifest.get("referencedRuns", [])
    candidates = [
        run
        for run in candidates
        if run["runId"] == ref.get("runId")
        and (not ref.get("runVersionId") or run["runVersionId"] == ref["runVersionId"])
    ]
    unique = {run["runVersionId"]: run for run in candidates}
    # A unique captured version takes precedence over current catalog data.
    if not ref.get("runVersionId"):
        captured = {r["runVersionId"] for r in _context_refs(context) if r["runId"] == ref["runId"]}
        if captured:
            return unique.get(next(iter(captured))) if len(captured) == 1 else None
        latest = [run for run in manifest.get("runs", []) if run["runId"] == ref["runId"]]
        return latest[0] if len(latest) == 1 else None
    return next(iter(unique.values())) if len(unique) == 1 else None


def build_graph(model, backend, settings, checkpointer):
    def call_model(stage, fn, prompt, payload, *args, **kwargs):
        repaired = False
        for attempt in range(4):
            backend.attempt(stage)
            try:
                return fn(prompt, payload, *args, **kwargs)
            except ModelError as error:
                if error.code == "MODEL_OUTPUT_INVALID" and not repaired:
                    repaired = True
                    payload = {**payload, "repair_error": "Invalid schema. Return valid fields and types."}
                    continue
                if not error.retryable or attempt == 3:
                    raise
                time.sleep(min(2**attempt, 4))
        raise ModelError("MODEL_ATTEMPT_LIMIT")

    def select_tool(state):
        backend.stage("select_tool")
        context = state.get("context", {})
        payload = {
            "question": state["question"],
            "input_history": state.get("input_history", []),
            "prior_interpretation": state.get("interpretation"),
            "pending_question": state.get("pending"),
            "latest_reply": state.get("reply"),
            "explicitReferences": context.get("comparisonReference", {"entries": []}),
            "recentContext": context.get("recentContext", {}),
            "context_available": {
                "reference_run": bool(context.get("activeRun")),
                "selected_run": bool(context.get("selectedRunRef")),
            },
        }
        selection, metadata = call_model("interpret", model.select_tool, SELECTION_PROMPT, payload)
        kind = selection["name"]
        if kind not in TOOL_MODELS or not selection.get("call_id"):
            raise ModelError("MODEL_OUTPUT_INVALID")
        inputs = TOOL_MODELS[kind].model_validate(selection["arguments"]).model_dump(exclude_none=True)
        op = {"kind": kind, "inputs": inputs}
        bridge = {"status": "resolved", "operations": [op], "unresolved": []}
        metadata = deepcopy(metadata)
        native_items = metadata.pop("responseItems", [])
        return {
            "tool_selection": selection,
            "native_items": native_items,
            "selection_payload": payload,
            "operation": op,
            "inputs": inputs,
            "interpretation": bridge,
            "model_metadata": {"selection": metadata},
            "reply": {},
        }

    def guard(state):
        kind = state["operation"]["kind"]
        inputs = deepcopy(state["inputs"])
        backend.stage("guard", operationKind=kind, dependsOnContext=bool(inputs.get("context_rules")))
        scope_choices = _scope_choices(state["question"])
        if scope_choices:
            replies = [e.get("text", "") for e in state.get("input_history", []) if e.get("scope_reply")]
            chosen: list[str] = []
            if replies:
                text = replies[-1]
                for name, phrase in (
                    ("forward_lookup", r"조회|순방향|lookup|retrieve"),
                    ("reverse_search", r"후보|탐색|역방향|search"),
                    ("compare_runs", r"비교|compare"),
                ):
                    if re.search(phrase, text):
                        chosen.append(name)
            if chosen != [kind] or kind not in scope_choices:
                labels = {
                    "forward_lookup": "조건 조회",
                    "reverse_search": "후보 탐색",
                    "compare_runs": "실험 비교",
                }
                return _request_input(
                    state,
                    "조회·탐색과 비교를 각각 실행해야 하는 질문입니다. 먼저 처리할 작업 하나를 선택해 주세요.",
                    "MIXED_REQUEST",
                    options=[
                        {
                            "label": labels[name] + " 먼저",
                            "input": {"text": "먼저 " + labels[name] + "를 해줘"},
                        }
                        for name in scope_choices
                    ],
                )
        if kind == "generate_answer":
            return {"inputs": {}, "context_provenance": {}, "route": "answer"}
        if kind == "compare_runs":
            snapshot = (
                state.get("comparison_reference")
                or state.get("context", {}).get("comparisonReference")
                or {"entries": [], "baselineKey": None}
            )
            all_entries = snapshot["entries"]
            requested = inputs.get("ref_keys")
            allowed = {e["key"] for e in all_entries}
            baseline_required = bool(
                re.search(
                    r"변화율|퍼센트|%|대비",
                    state["question"],
                    re.IGNORECASE,
                )
                or (
                    re.search(
                        r"기준\s*(?:으로|Run|런|실험)|\bbaseline\b|\breference\s+run\b",
                        state["question"],
                        re.IGNORECASE,
                    )
                    and not re.search(
                        r"기준\s*(?:Run|런|실험)?\s*(?:없이|없|미지정)|\b(?:without\s+(?:a\s+)?|no\s+)baseline\b",
                        state["question"],
                        re.IGNORECASE,
                    )
                )
            )
            if requested and not set(requested) <= allowed:
                return _picker(state, baseline_required)
            entries = [e for e in all_entries if requested is None or e["key"] in requested]
            if len(entries) < 2:
                return _picker(state, baseline_required)
            try:
                validate_native_comparison_metrics(inputs, state["question"], state.get("input_history", []))
            except DomainError:
                return _request_input(
                    state,
                    "비교할 지표를 확인해 주세요. 평균 이온 에너지·이온 플럭스·IED 폭 중 원하는 지표를 알려 주세요.",
                    "UNGROUNDED_METRICS",
                    ["metrics"],
                )
            if len({(e["ref"]["runId"], e["ref"]["runVersionId"]) for e in entries}) != len(entries):
                raise DomainError("INVALID_COMPARISON_SELECTION")
            if not inputs.get("baseline_key") and snapshot.get("baselineKey"):
                inputs["baseline_key"] = snapshot["baselineKey"]
            if inputs.get("baseline_key") and inputs["baseline_key"] not in {e["key"] for e in entries}:
                raise DomainError("INVALID_BASELINE_KEY")
            baseline = inputs.get("baseline_key")
            baseline_confirmed = baseline == snapshot.get("baselineKey") or any(
                event.get("type") == "comparison_options" and event.get("baselineKey") == baseline
                for event in state.get("input_history", [])
            )
            if baseline and not baseline_confirmed:
                entry = next(e for e in entries if e["key"] == baseline)
                names = "|".join(re.escape(name) for name in (baseline, entry["ref"]["runId"]))
                text = "\n".join(
                    [state["question"], *(e.get("text", "") for e in state.get("input_history", []))]
                )
                baseline_confirmed = bool(
                    re.search(
                        rf"(?<![A-Za-z0-9_-])(?:{names})(?![A-Za-z0-9_-])\s*(?:을|를)?\s*기준"
                        rf"|(?:기준\s*[:=]\s*|\bbaseline\s*[:=]?\s*)(?:{names})(?![A-Za-z0-9_-])",
                        text,
                        re.IGNORECASE,
                    )
                )
            if (baseline_required and not baseline) or (baseline and not baseline_confirmed):
                request = _request_input(
                    state, "비교 기준으로 사용할 실험을 선택해 주세요.", "MISSING_BASELINE", ["baselineKey"]
                )
                request["pending"] = {
                    "type": "comparison_options",
                    "id": request["pending"]["id"],
                    "message": request["pending"]["message"],
                    "fields": ["baselineKey"],
                    "allowedRunKeys": [e["key"] for e in entries],
                    "allowedTrendAxes": list(CONDITION_KEYS),
                }
                return {
                    **request,
                    "inputs": {**inputs, "baseline_key": None},
                    "comparison_reference": {"entries": entries, "baselineKey": None},
                }
            return {
                "inputs": inputs,
                "comparison_reference": {"entries": entries, "baselineKey": inputs.get("baseline_key")},
                "route": "gather",
            }
        defaulted_units: list[str] = []
        try:
            validate_grounding(
                {"kind": kind, "inputs": inputs},
                state["question"],
                state.get("input_history", []),
                state.get("selection_payload", {}).get("prior_interpretation"),
                defaulted_units=defaulted_units,
            )
        except DomainError as error:
            if error.code == "MISSING_UNIT":
                metric = error.detail
                request = _request_input(
                    state,
                    f"{LABELS[metric]} 수치의 단위를 알려 주세요. 예: {UNITS[metric]}",
                    "MISSING_UNIT",
                    [metric] if kind == "forward_lookup" else ["constraints", "goals"],
                )
                request["pending"]["unitMetric"] = metric
                return request
            request = _request_input(
                state,
                "요청 조건을 확실히 연결하지 못했습니다. 지표별 수치·단위를 다시 알려 주세요.",
                error.code,
            )
            request["interpretation"] = {
                "status": "unsupported",
                "operations": [state["operation"]],
                "unresolved": [{"reason": error.code}],
            }
            return request
        proposed = list((inputs.get("conditions") or {}).items())
        proposed += [
            (item["metric"], item) for group in ("constraints", "goals") for item in inputs.get(group, [])
        ]
        for metric, scalar_value in proposed:
            if metric in defaulted_units and any(
                scalar_value.get(k) is not None for k in ("value", "min", "max")
            ):
                scalar_value["unit"] = UNITS[metric]
            try:
                normalize_value(metric, 0, scalar_value.get("unit"))
            except NumericError:
                request = _request_input(
                    state,
                    f"{LABELS[metric]} 단위를 확인해 주세요.",
                    "UNSUPPORTED_UNIT",
                    [metric] if kind == "forward_lookup" else ["constraints", "goals"],
                )
                request["pending"]["unitMetric"] = metric
                return request
        if kind == "forward_lookup" and not inputs.get("context_rules"):
            missing = [key for key in CONDITION_KEYS if not inputs.get("conditions", {}).get(key)]
            if missing:
                return _request_input(
                    state,
                    ", ".join(LABELS[k] for k in missing) + " 조건을 알려 주세요.",
                    "MISSING_CONDITIONS",
                    missing,
                )
        if kind == "reverse_search" and not any(
            inputs.get(k) for k in ("constraints", "goals", "context_rules")
        ):
            return _request_input(state, "찾을 지표와 목표 또는 범위를 알려 주세요.", "MISSING_OBJECTIVE")
        return {
            "route": "gather",
            "inputs": inputs,
            "unit_assumptions": [{"metric": metric, "unit": UNITS[metric]} for metric in defaulted_units],
        }

    def wait_input(state):
        reply = interrupt(state["pending"])
        if not isinstance(reply, dict):
            raise DomainError("INVALID_RESUME_INPUT")
        entry = deepcopy(reply)
        if state["pending"].get("reason") == "MIXED_REQUEST":
            entry["scope_reply"] = True
        if state["pending"].get("unitMetric"):
            entry["unit_metric"] = state["pending"]["unitMetric"]
        history = [*state.get("input_history", []), entry]
        pending_type = state["pending"].get("type", "text")
        if pending_type == "run_selection":
            snapshot = reply.get("comparisonReference")
            if reply.get("type") != pending_type or not snapshot or len(snapshot.get("entries", [])) < 2:
                raise DomainError("INVALID_COMPARISON_SELECTION")
            keys = [e["key"] for e in snapshot["entries"]]
            if keys != reply.get("runKeys") or any(
                e["origin"]["pendingInputId"] != state["pending"]["id"] for e in snapshot["entries"]
            ):
                raise DomainError("INVALID_COMPARISON_SELECTION")
            inputs = {**state["inputs"], "ref_keys": keys, "baseline_key": snapshot.get("baselineKey")}
            context = {**state.get("context", {}), "comparisonReference": snapshot}
            return {
                "input_history": history,
                "context": context,
                "comparison_reference": snapshot,
                "inputs": inputs,
                "route": "guard",
            }
        if pending_type == "comparison_options":
            if reply.get("type") != pending_type:
                raise DomainError("INVALID_RESUME_INPUT")
            inputs = deepcopy(state["inputs"])
            for wire, field in (("baselineKey", "baseline_key"), ("trendAxis", "trend_axis")):
                if reply.get(wire) is not None:
                    inputs[field] = reply[wire]
            return {"input_history": history, "inputs": inputs, "route": "guard"}
        if isinstance(reply.get("text"), str) and reply["text"].strip():
            return {"input_history": history, "reply": reply, "route": "select"}
        inputs = deepcopy(state["inputs"])
        try:
            allowed = set(state["pending"].get("fields", []))
            for key, val in reply.items():
                if key == "type":
                    continue
                if key == "conditions" and isinstance(val, dict) and set(val) <= allowed:
                    inputs.setdefault("conditions", {}).update(val)
                elif key in allowed:
                    inputs[key] = val
                else:
                    raise DomainError("INVALID_RESUME_FIELD")
            inputs = (
                TOOL_MODELS[state["operation"]["kind"]].model_validate(inputs).model_dump(exclude_none=True)
            )
        except (DomainError, ValidationError):
            request = _request_input(
                {**state, "input_history": history},
                "입력 형식을 확인해 다시 알려 주세요. " + state["pending"]["message"],
                "INVALID_RESUME_INPUT",
                state["pending"].get("fields"),
                state["pending"].get("options"),
            )
            if state["pending"].get("unitMetric"):
                request["pending"]["unitMetric"] = state["pending"]["unitMetric"]
            return {**request, "input_history": history}
        return {"input_history": history, "inputs": inputs, "reply": reply, "route": "guard"}

    def gather(state):
        backend.stage("gather")
        inputs = deepcopy(state["inputs"])
        kind = state["operation"]["kind"]
        if kind == "compare_runs":
            entries = state["comparison_reference"]["entries"]
            refs = [e["ref"] for e in entries]
            manifest = backend.context(refs, references_only=True)
            by_ref = {(r["runId"], r["runVersionId"]): r for r in manifest["referencedRuns"]}
            if set(by_ref) != {(r["runId"], r["runVersionId"]) for r in refs}:
                raise DomainError("RESULT_SOURCE_MISMATCH")
            source = [
                {**entry, "run": by_ref[(entry["ref"]["runId"], entry["ref"]["runVersionId"])]}
                for entry in entries
            ]
            if inputs.get("analysis") == "trend" and not inputs.get("trend_axis"):
                varying = [k for k in CONDITION_KEYS if len({r["run"].get(k) for r in source}) > 1]
                if len(varying) == 1:
                    inputs["trend_axis"] = varying[0]
                else:
                    request = _request_input(
                        state,
                        "경향을 볼 공정 조건을 선택해 주세요. 다른 조건이 같은 실험끼리 비교합니다.",
                        "MISSING_TREND_AXIS",
                        ["trendAxis"],
                    )
                    request["pending"] = {
                        "type": "comparison_options",
                        "id": request["pending"]["id"],
                        "message": request["pending"]["message"],
                        "fields": ["trendAxis"],
                        "allowedRunKeys": [e["key"] for e in entries],
                        "allowedTrendAxes": list(CONDITION_KEYS),
                    }
                    return {**request, "manifest": manifest}
            return {
                "manifest": manifest,
                "source": source,
                "inputs": inputs,
                "context_provenance": state["comparison_reference"],
                "route": "calculate",
            }
        if kind == "reverse_search":
            from ..domain.reverse import normalized_reverse_query

            manifest = (
                backend.context(references_only=True)
                if inputs.get("context_rules")
                else backend.context(reverse_query=normalized_reverse_query(inputs))
            )
        else:
            manifest = backend.context()
        context = manifest.get("context", state.get("context", {}))
        source = manifest["runs"]
        provenance = {}
        if inputs.get("context_rules"):
            from ..domain.context import apply_context_rules

            selected = _resolve({"kind": "selected_run"}, manifest, context)
            reference = _resolve({"kind": "reference_run"}, manifest, context)
            if "selected_run_conditions" not in inputs["context_rules"]:
                selected = (
                    None
                    if selected and reference and selected["runVersionId"] != reference["runVersionId"]
                    else selected or reference
                )
            try:
                provenance = apply_context_rules(
                    kind,
                    inputs,
                    state["question"]
                    + " "
                    + " ".join(x.get("text", "") for x in state.get("input_history", [])),
                    selected,
                )
                inputs = provenance["inputs"]
            except DomainError:
                return {
                    **_request_input(
                        state, "이어갈 기준 Run 또는 구체적인 조건을 알려 주세요.", "MISSING_CONTEXT"
                    ),
                    "manifest": manifest,
                }
            if kind == "reverse_search":
                manifest = backend.context(reverse_query=normalized_reverse_query(inputs))
                source = manifest["runs"]
        return {
            "manifest": manifest,
            "source": source,
            "inputs": inputs,
            "context_provenance": provenance,
            "route": "calculate",
        }

    def calculate(state):
        kind = state["operation"]["kind"]
        backend.stage("calculate")
        fn = (
            lookup_forward
            if kind == "forward_lookup"
            else search_reverse
            if kind == "reverse_search"
            else compare_selected
        )
        return {"result": fn(state["inputs"], state["source"]), "verified": False}

    def verify(state):
        backend.stage("validate_result")
        if state["operation"]["kind"] == "compare_runs":
            if state["result"] != compare_selected(state["inputs"], state["source"]):
                raise DomainError("RESULT_SOURCE_MISMATCH")
            return {"verified": True, "evidence": state["result"], "route": "answer"}
        if not validate_result(state["inputs"], state["result"], state["source"])["valid"]:
            raise DomainError("RESULT_SOURCE_MISMATCH")
        return {"verified": True, "route": "present"}

    def generate_answer(state):
        backend.stage("generate_answer")
        general = state["operation"]["kind"] == "generate_answer"
        payload = {
            "originalQuestion": state["question"],
            "resolvedInputs": state["inputs"],
            "recentContext": state.get("context", {}).get("recentContext", {}),
            "inputHistory": state.get("input_history", []),
            "repair_error": state.get("repair_error"),
        }
        if not general:
            payload["evidence"] = state["evidence"]
        tool_context = {
            "input": state["selection_payload"],
            "responseItems": state["native_items"],
            "call_id": state["tool_selection"]["call_id"],
            "output": {} if general else state["result"],
        }
        draft, metadata = call_model(
            "explain",
            model.answer if general else model.generate,
            GENERAL_PROMPT if general else COMPARISON_PROMPT,
            payload,
            *([] if general else [comparison_draft_model(state["result"])]),
            tool_context=tool_context,
        )
        return {
            "draft": {"markdown": draft} if general else draft,
            "model_metadata": {**state["model_metadata"], "answer": metadata},
        }

    def check_answer(state):
        backend.stage("validate_answer")
        if state["operation"]["kind"] == "generate_answer":
            result = GeneralAnswerResult.model_validate(
                {
                    "kind": "generate_answer",
                    "resultStatus": "ANSWER_READY",
                    "markdown": state["draft"]["markdown"],
                    "knowledgeBasis": "LLM_GENERAL_KNOWLEDGE",
                    "usedRunRefs": [],
                }
            ).model_dump()
            return {"result": result, "verified": True, "route": "present"}
        try:
            answer = validate_answer(state["draft"], state["result"])
            return {"comparison_answer": answer, "route": "present"}
        except (DomainError, ValidationError) as error:
            if state.get("explanation_repairs", 0) >= 1:
                raise
            return {
                "repair_error": getattr(error, "code", "ANSWER_SCHEMA_INVALID"),
                "explanation_repairs": 1,
                "route": "repair",
            }

    def present(state):
        backend.stage("present")
        kind = state["operation"]["kind"]
        result = deepcopy(state["result"])
        refs = list(result.get("usedRunRefs", []))
        search = kind in ("forward_lookup", "reverse_search")
        if search:
            evidence_refs = list(state.get("context_provenance", {}).get("usedRunRefs", []))
            evidence_refs += [
                {k: r[k] for k in ("runId", "runVersionId")} for r in result.get("excludedRuns", [])
            ]
            for ref in evidence_refs:
                if ref not in refs:
                    refs.append(ref)
        labels = {
            "EXACT": "입력 조건과 일치하는 실제 Run을 찾았습니다.",
            "NEAREST_ONLY": "정확히 일치하는 Run이 없어 근접 Run을 표시합니다.",
            "NO_DATA": "사용할 수 있는 실제 Run이 없습니다.",
            "MATCH": "요청 조건에 맞는 실제 Run 후보를 찾았습니다.",
            "NO_MATCH": "모든 조건을 만족하는 Run이 없습니다.",
            "COMPARISON_READY": "선택한 실제 실험을 비교했습니다.",
            "COMPARISON_PARTIAL": "비교 가능한 항목을 계산했습니다.",
            "NO_COMPARABLE_DATA": "비교 가능한 측정값이 부족합니다.",
            "ANSWER_READY": "일반 지식에 따른 답변입니다.",
        }
        summary = labels[result["resultStatus"]]
        snapshot = {
            "implementationId": "v1",
            "graphVersion": "v1",
            "schemaVersion": 2,
            "kind": kind,
            "summary": summary,
            "originalQuestion": state["question"],
            "toolSelection": state["tool_selection"],
            "resolvedInputs": state["inputs"],
            "result": result,
            "answer": state.get("comparison_answer") if kind == "compare_runs" else None,
            "contextProvenance": state.get("context_provenance", {}) if kind != "generate_answer" else {},
            "unitAssumptions": state.get("unit_assumptions", []) if search else [],
            "inputHistory": state.get("input_history", []),
            "usedRunRefs": refs,
            "versions": settings.versions(),
        }
        snapshot = AnswerSnapshotV2.model_validate(snapshot).model_dump()
        return {
            "answer": {
                "intent": {
                    "forward_lookup": "FORWARD_LOOKUP",
                    "reverse_search": "REVERSE_SEARCH",
                    "compare_runs": "RUN_COMPARISON",
                    "generate_answer": "GENERAL_ANSWER",
                }[kind],
                "status": result["resultStatus"],
                "candidates": [
                    {k: r[k] for k in ("runId", "runVersionId")} for r in result.get("candidates", [])
                ]
                if search
                else [],
                "explanation": None,
                "answerSnapshot": snapshot,
                "usedRunRefs": refs,
            }
        }

    builder = StateGraph(GraphState)
    for name, fn in [
        ("select_tool", select_tool),
        ("guard", guard),
        ("wait_input", wait_input),
        ("gather", gather),
        ("calculate", calculate),
        ("validate_result", verify),
        ("generate_answer", generate_answer),
        ("validate_answer", check_answer),
        ("present", present),
    ]:
        builder.add_node(name, tracing.node(name, fn))
    builder.add_edge(START, "select_tool")
    builder.add_edge("select_tool", "guard")
    builder.add_conditional_edges(
        "guard", lambda s: s["route"], {"wait": "wait_input", "gather": "gather", "answer": "generate_answer"}
    )
    builder.add_conditional_edges(
        "wait_input", lambda s: s["route"], {"select": "select_tool", "guard": "guard", "wait": "wait_input"}
    )
    builder.add_conditional_edges(
        "gather", lambda s: s["route"], {"wait": "wait_input", "calculate": "calculate"}
    )
    builder.add_edge("calculate", "validate_result")
    builder.add_conditional_edges(
        "validate_result", lambda s: s["route"], {"present": "present", "answer": "generate_answer"}
    )
    builder.add_edge("generate_answer", "validate_answer")
    builder.add_conditional_edges(
        "validate_answer", lambda s: s["route"], {"present": "present", "repair": "generate_answer"}
    )
    builder.add_edge("present", END)
    return builder.compile(checkpointer=checkpointer)
