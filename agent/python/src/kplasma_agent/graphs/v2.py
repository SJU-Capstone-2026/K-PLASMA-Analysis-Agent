"""V2 orchestration. Models propose plans and prose, while code runs registered steps."""

import json
import time
from typing import Hashable, Literal, TypedDict
from uuid import NAMESPACE_URL, uuid5

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from ..model_client import ModelError
from ..metric_registry import CONDITION_KEYS
from ..progress import ProgressReporter
from ..v2.bindings import BlockedInput, resolve_comparison_entries, resolve_inputs, should_run
from ..v2.composition import (
    assemble_answer, collect_comparison_coverage, collect_evidence, collect_numeric_values, collect_search_evidence, facts_only,
    interpretation_review_payload,
)
from ..v2.contracts import (
    AwaitInputStep, BudgetState, CandidateScope, CompareStep, DataAnswerDraft, GeneralAnswerDraft,
    GraphV2AnswerSnapshotV1, PlanDraft, ResultRef, ReviewDecision, StepResult,
)
from ..v2.executor import SequentialExecutor
from ..v2.plan_validation import InvalidPlan, validate_plan
from ..v2.plan_review import (
    PROMPT_VERSION, PlanReviewResult, build_plan_review_context, digest, plan_digest,
    plan_review_feedback, review_result,
)


class State(TypedDict, total=False):
    request_id: str
    question: str
    context: dict
    input_history: list[dict]
    plan_draft: dict | None
    plan: dict
    plan_revision: int
    step_results: dict
    durable_steps: list[str]
    step_inputs: dict
    waiting_step: str | None
    replacement_pending: bool
    pending: dict
    failure: str | None
    feedback: str | None
    route: str
    mode: str
    draft: dict | None
    last_draft: dict | None
    rendered: str
    evidence: list[dict]
    review: dict
    plan_review: dict | None
    plan_review_input: dict
    plan_review_feedback: dict | None
    plan_review_enabled: bool
    plan_review_binding_digest: str | None
    replans: int
    rewrites: int
    model_requests: int
    tool_requests: int
    elapsed: float
    partial_composes: int
    answer: dict


def _binding_context(context):
    selection = context.get("comparisonReference") or {}
    entries = selection.get("entries", [])
    values = {entry["key"]: entry["ref"] for entry in entries}
    values.update(selected_runs=[entry["ref"] for entry in entries], comparison_entries=entries)
    for key in ("activeRun", "selectedRunRef"):
        if context.get(key):
            values[key] = context[key]
    if selection.get("baselineKey"):
        values["baseline"] = selection["baselineKey"]
    values.update(context.get("v2ConfirmedInputs", {}))
    return values


def _budget(state, **extra):
    values = {
        "replans_used": state.get("replans", 0),
        "answer_rewrites_used": state.get("rewrites", 0),
        "partial_finalizations_used": state.get("partial_composes", 0),
        "model_requests_used": state.get("model_requests", 0),
        "tool_invocations_used": state.get("tool_requests", 0),
        "active_elapsed_seconds": state.get("elapsed", 0.0),
    }
    return BudgetState(**{**values, **extra})


def _issue(reason):
    if not reason:
        return None
    if reason in {"PLAN_SEMANTIC_MISMATCH", "PLAN_SEMANTIC_UNCLEAR"}:
        return "질문의 조건에 맞는 처리 계획을 확정하지 못해 더 진행하지 않았습니다."
    if reason == "PLAN_REVIEW_UNAVAILABLE":
        return "작업 계획 검토를 완료하지 못해 실행을 중단했습니다."
    if reason == "PLAN_REVIEW_INPUT_INVALID":
        return "계획 검토에 필요한 정보를 구성하지 못해 실행하지 않았습니다."
    if reason == "STALE_PLAN_REVIEW":
        return "질문 또는 선택 정보가 변경되어 이전 검토로 실행할 수 없습니다."
    if reason == "INSUFFICIENT_CANDIDATES":
        return "검색 결과에서 비교에 필요한 수의 Run을 확보하지 못했습니다."
    if reason.startswith("MISSING_INPUT:"):
        return f"필수 입력 또는 측정값이 없어 후속 작업을 완료하지 못했습니다. ({reason.split(':', 1)[1]})"
    return "요청을 모두 완료하지 못했습니다. 확인된 결과를 표시합니다."


def build_v2_graph(models, executions, checkpointer):
    executor = SequentialExecutor(executions)
    progress = getattr(executions, "progress", None) or ProgressReporter(None)

    def publish_results(values):
        progress.results([value["executionId"] for value in values.values()
                          if value.get("status") in {"verified", "partial", "empty"}
                          and value.get("outputs", {}).get("toolResult") is not None])

    def model_call(state, kind, key, fn, context, numeric_values=None):
        if state.get("elapsed", 0) >= 600 or state.get("model_requests", 0) >= 13:
            return None, "MODEL_BUDGET_EXHAUSTED", {}
        start = time.monotonic()
        permit = executions.reserve_model(kind, key)
        saved = permit.get("outcome")
        if saved is None and permit["callAllowed"]:
            code = {"PLAN_INITIAL": "PLAN", "REPLAN": "REPLAN", "PLAN_REVIEW": "PLAN_REVIEW", "REVIEW": "REVIEW",
                    "ANSWER_REWRITE": "REWRITE"}.get(kind, "GENERAL_ANSWER" if context.get("mode") == "general_only" else "INTERPRET")
            identity = str(permit["attemptId"])
            progress.activity(code, identity=identity)
            stream = None
            try:
                if kind in {"COMPOSE", "PARTIAL_COMPOSE", "ANSWER_REWRITE"} and progress.enabled:
                    stream = progress.start_answer("general" if context["mode"] == "general_only" else "interpretation",
                                                   rewrite=kind == "ANSWER_REWRITE")
                compose_stream = getattr(models, "stream_compose", None)
                if stream is not None and callable(compose_stream):
                    data, usage = compose_stream(context, on_block=stream.append, numeric_values=numeric_values)
                    stream.flush()
                else:
                    data, usage = fn(context)
                saved = {"data": data, "usage": usage, "error": None}
            except (ModelError, ValueError, TypeError) as error:
                if stream is not None:
                    stream.invalidate("writer_failed")
                saved = {"data": None, "usage": None, "error": getattr(error, "code", "MODEL_OUTPUT_INVALID")}
            if kind == "PLAN_REVIEW":
                saved["reviewInput"] = context
            saved = executions.complete_model(permit["attemptId"], saved)["outcome"]
            progress.activity(code, "completed", identity=identity)
        elif saved is not None:
            progress.activity("REUSE_RESULT", "reused", identity=f"model:{permit['attemptId']}")
        else:
            progress.activity("RECOVERING", identity=f"unknown:{permit['attemptId']}")
        updates = {
            "model_requests": state.get("model_requests", 0) + 1,
            "elapsed": state.get("elapsed", 0) + time.monotonic() - start,
        }
        if saved is None:
            return None, "MODEL_OUTCOME_UNKNOWN", updates
        return saved.get("data"), saved.get("error"), updates

    def request_plan(state, replan=False):
        history = state.get("input_history", [])
        messages = {"question": state["question"]}
        messages.update({f"input_{index}": item.get("text") or str(item)
                         for index, item in enumerate(history)})
        context = _binding_context(state.get("context", {}))
        payload = {
            "messages": messages, "context_keys": list(context),
            "confirmed_run_keys": [entry["key"] for entry in context["comparison_entries"]],
            "base_revision": state.get("plan_revision"),
            "previous_plan": state.get("plan"),
            "feedback": state.get("feedback"),
            "plan_review_feedback": state.get("plan_review_feedback"),
            "verified_results": {step: value.get("status")
                                 for step, value in state.get("step_results", {}).items()},
        }
        replan_number = state.get("replans", 0) + int(replan)
        data, error, counters = model_call(
            state, "REPLAN" if replan else "PLAN_INITIAL",
            f"plan:{replan_number}:{len(history)}", models.submit_plan, payload,
        )
        enabled = state.get("plan_review_enabled", getattr(getattr(models, "settings", None), "plan_review_enabled", True))
        return {**counters, "plan_draft": data, "feedback": error, "replans": replan_number,
                "plan_review_enabled": enabled}

    def plan(state):
        return request_plan(state)

    def replan(state):
        return request_plan(state, True)

    def validate_plan_state(state):
        incoming = state.get("plan_draft")
        if incoming is None:
            retry = state.get("feedback") == "MODEL_OUTPUT_INVALID" and state.get("replans", 0) < 2
            return {"route": "replan" if retry else "compose",
                    "failure": state.get("feedback") or "PLAN_UNAVAILABLE"}
        messages = {"question": state["question"]}
        messages.update({f"input_{i}": item.get("text") or str(item)
                         for i, item in enumerate(state.get("input_history", []))})
        context = _binding_context(state.get("context", {}))
        # Explicit selected Run requests must stay on the data path.
        question = state["question"].lower()
        data_required = any(term in question for term in ("run", "후보", "선택한 실험", "기준 실험")) and any(
            term in question for term in ("비교", "찾", "검색", "보다", "수치", "값")
        )
        try:
            accepted = validate_plan(PlanDraft.model_validate(incoming), messages=messages,
                                     context_keys=set(context), base_revision=state.get("plan_revision"),
                                     data_required=data_required,
                                     selected_run_keys={entry["key"] for entry in context["comparison_entries"]})
        except (ValidationError, InvalidPlan) as error:
            return {"route": "replan" if state.get("replans", 0) < 2 else "compose",
                    "failure": "INVALID_PLAN", "feedback": str(error)[:1600]}

        prior_steps = {step["id"]: step for step in state.get("plan", {}).get("steps", [])}
        previous = state.get("step_results", {})
        reusable: dict[str, dict] = {}
        used_inputs = {}
        for step in accepted.steps:
            if (step.id in previous and previous[step.id]["status"] in {"verified", "partial", "empty"}
                    and step.model_dump(mode="json") == prior_steps.get(step.id)
                    and set(step.depends_on) <= reusable.keys()):
                reusable[step.id] = previous[step.id]
                if step.id in state.get("step_inputs", {}):
                    used_inputs[step.id] = state["step_inputs"][step.id]
        stored = executions.accept_plan(accepted)
        return {"plan": stored["plan"], "plan_revision": stored["revision"], "mode": accepted.request_mode,
                "route": "plan_review" if accepted.steps else "compose", "failure": None, "feedback": None,
                "step_results": reusable, "step_inputs": used_inputs,
                "durable_steps": [key for key in reusable if key in state.get("durable_steps", [])],
                "draft": None, "last_draft": None, "plan_review": None, "plan_review_binding_digest": None}

    def validate(state):
        with progress.work("PLAN_VALIDATE"):
            return validate_plan_state(state)

    def binding_digest(state, *, history=None, context=None):
        return digest({"question": state["question"],
                       "input_history": state.get("input_history", []) if history is None else history,
                       "confirmed_context": _binding_context(state.get("context", {}) if context is None else context)})

    def review_plan(state):
        try:
            payload = build_plan_review_context(PlanDraft.model_validate(state["plan"]), state["plan_revision"],
                state["question"], state.get("input_history", []), _binding_context(state.get("context", {})),
                state.get("step_results", {}))
        except (ValueError, TypeError):
            return {"route": "compose", "failure": "PLAN_REVIEW_INPUT_INVALID"}
        if not state.get("plan_review_enabled", True):
            decision = review_result(payload, "SKIPPED", reason="PLAN_REVIEW_DISABLED")
            counts = {}
        else:
            key = f"plan-review:{state['plan_revision']}:{payload['input_digest']}:{payload['plan_digest'][:24]}:{PROMPT_VERSION}"
            data, error, counts = model_call(state, "PLAN_REVIEW", key, models.review_plan, payload)
            try:
                decision = PlanReviewResult.model_validate(data) if data else review_result(payload, "UNAVAILABLE", reason=error)
                if any(getattr(decision, key) != payload[key] for key in (
                    "plan_revision", "plan_digest", "input_digest", "prompt_version",
                )) or decision.status == "SKIPPED":
                    raise ValueError("plan review belongs to another input")
            except (ValueError, TypeError):
                decision = review_result(payload, "UNAVAILABLE", reason="DECISIONS_INVALID_RESPONSE")
        result = {**counts, "plan_review": decision.model_dump(mode="json"), "plan_review_input": payload,
                  "plan_review_binding_digest": binding_digest(state)}
        if decision.status in {"PASS", "SKIPPED"}:
            publish_results(state.get("step_results", {}))
            return {**result, "route": "execute", "failure": None, "plan_review_feedback": None}
        if decision.status in {"ISSUE", "UNCLEAR"}:
            feedback = plan_review_feedback(decision)
            return {**result, "route": "replan" if state.get("replans", 0) < 2 else "compose",
                    "failure": feedback["code"], "feedback": feedback["code"], "plan_review_feedback": feedback}
        failure = "PLAN_REVIEW_INPUT_INVALID" if decision.reason == "PLAN_REVIEW_INPUT_INVALID" else "PLAN_REVIEW_UNAVAILABLE"
        return {**result, "route": "compose", "failure": failure, "feedback": decision.reason}

    def approved_plan(state):
        if not state.get("plan_review_enabled", True):
            return True
        try:
            decision = PlanReviewResult.model_validate(state.get("plan_review"))
            return (decision.status == "PASS" and decision.plan_revision == state["plan_revision"]
                    and decision.plan_digest == plan_digest(state["plan"])
                    and decision.prompt_version == PROMPT_VERSION
                    and decision.input_digest == state["plan_review_input"]["input_digest"]
                    and state.get("plan_review_binding_digest") == binding_digest(state))
        except (ValueError, TypeError, KeyError):
            return False

    def execute(state):
        if not state.get("plan_review"):
            return {"route": "plan_review"}
        if not approved_plan(state):
            return {"route": "compose", "failure": "STALE_PLAN_REVIEW"}
        accepted = PlanDraft.model_validate(state["plan"])
        previous = {key: StepResult.model_validate(val) for key, val in state.get("step_results", {}).items()}
        current = next((s for s in accepted.steps if s.id not in previous), None)
        if current is None:
            return {"route": "compose"}
        if state.get("elapsed", 0) >= 600:
            return {"route": "compose", "failure": "TIME_BUDGET_EXHAUSTED"}
        context = _binding_context(state.get("context", {}))
        if isinstance(current, AwaitInputStep) and should_run(current, previous):
            return {"route": "await", "waiting_step": current.id}
        start = time.monotonic()
        result = executor.execute(state["plan_revision"], current, context, previous)
        elapsed = state.get("elapsed", 0) + time.monotonic() - start
        if result.status == "blocked":
            if result.reason == "MISSING_INPUT:INSUFFICIENT_CANDIDATES":
                return {"route": "compose", "failure": "INSUFFICIENT_CANDIDATES", "elapsed": elapsed}
            return {
                "route": "await" if result.reason and result.reason.startswith("MISSING_INPUT:") else "replan",
                "waiting_step": current.id, "failure": result.reason, "feedback": result.reason, "elapsed": elapsed,
            }
        steps = {**state.get("step_results", {}), current.id: result.model_dump(mode="json")}
        publish_results(steps)
        durable = not result.executionId.startswith(("skipped:", "blocked:")) and result.reason != "EXECUTION_OUTCOME_UNKNOWN"
        update: State = {
            "step_results": steps, "elapsed": elapsed,
            "durable_steps": state.get("durable_steps", []) + ([current.id] if durable else []),
            "tool_requests": state.get("tool_requests", 0) + int(current.kind == "tool" and durable),
            "route": "execute",
        }
        if result.status == "failed":
            update["route"] = "compose"
            update["failure"] = result.reason or "TOOL_EXECUTION_FAILED"
        return update

    def wait_for_input(state):
        accepted = PlanDraft.model_validate(state["plan"])
        step = next(s for s in accepted.steps if s.id == state["waiting_step"])
        failure = state.get("failure") or ""
        replacement = state.get("replacement_pending", False)
        selection = (replacement or isinstance(step, AwaitInputStep) and step.confirmation == "run_selection"
                     or failure == "MISSING_INPUT:selected_runs")
        pending_id = str(uuid5(NAMESPACE_URL, f"{state['request_id']}:{step.id}:{len(state.get('input_history', []))}"))
        pending = {"id": pending_id, "type": "run_selection", "message": "비교할 Run을 선택해 주세요.",
                   "minSelections": 2}
        if selection and isinstance(step, AwaitInputStep) and step.inputs.selection_count is not None:
            pending["minSelections"] = step.inputs.selection_count
            pending["maxSelections"] = step.inputs.selection_count
            pending["message"] = f"비교할 Run을 {step.inputs.selection_count}개 선택해 주세요."
        if not replacement and selection and isinstance(step, AwaitInputStep) and step.inputs.candidates is not None:
            previous = {key: StepResult.model_validate(val) for key, val in state.get("step_results", {}).items()}
            try:
                resolved = resolve_inputs(step, _binding_context(state.get("context", {})), previous)
            except BlockedInput:
                return {"route": "compose", "failure": "INSUFFICIENT_CANDIDATES"}
            candidates = resolved.get("candidates")
            if not isinstance(candidates, list) or len(candidates) < pending["minSelections"]:
                return {"route": "compose", "failure": "INSUFFICIENT_CANDIDATES"}
            pending["message"] = (
                f"검색 결과에서 비교할 Run을 {step.inputs.selection_count}개 선택해 주세요."
                if step.inputs.selection_count is not None else "검색 결과에서 비교할 Run을 선택해 주세요."
            )
            source = getattr(step.inputs.candidates, "step_id", None)
            if source:
                pending["sourceExecutionId"] = previous[source].executionId
        option_field = None
        if not selection and isinstance(step, AwaitInputStep):
            option_field = {"baseline": "baselineKey", "trend_axis": "trendAxis"}.get(step.confirmation)
        if option_field and isinstance(step, AwaitInputStep):
            context = _binding_context(state.get("context", {}))
            entries = context["comparison_entries"]
            if step.confirmation == "baseline":
                target = next((item for item in accepted.steps if item.id == step.inputs.target_step_id), None)
                if not isinstance(target, CompareStep):
                    return {"route": "replan", "failure": "INVALID_PLAN",
                            "feedback": "The baseline confirmation must target a compare_runs step."}
                previous = {key: StepResult.model_validate(val) for key, val in state.get("step_results", {}).items()}
                try:
                    entries = resolve_comparison_entries(target, context, previous)
                except BlockedInput as error:
                    if error.field == "INSUFFICIENT_CANDIDATES":
                        return {"route": "compose", "failure": error.field}
                    return {"route": "replan", "failure": "MISSING_INPUT:selected_runs",
                            "feedback": "Select the comparison Runs before asking the user to choose the baseline."}
            pending = {"id": pending_id, "type": "comparison_options",
                       "message": ("비교 기준으로 쓸 Run을 선택해 주세요." if step.confirmation == "baseline"
                                   else "비교 기준 또는 경향을 볼 공정 조건을 선택해 주세요."),
                       "fields": [option_field], "allowedRunKeys": [entry["key"] for entry in entries],
                       "allowedTrendAxes": list(CONDITION_KEYS)}
            if step.confirmation == "baseline":
                options = [
                    {"label": f"{entry['key']} · {entry['ref']['runId']}",
                     "input": {"type": "comparison_options", "baselineKey": entry["key"]}}
                    for entry in entries
                ]
                # Labels are optional when a large catalog approaches the pending payload limit.
                if len(json.dumps({**pending, "options": options})) <= 20_000:
                    pending["options"] = options
        elif not selection:
            pending = {"id": pending_id, "type": "text", "message": _issue(failure)
                       or "필수 입력을 확인해 주세요.",
                       "options": [
                           {"label": "부분 결과로 마치기", "input": {"type": "text", "text": "부분 결과로 마치기"}},
                           {"label": "다른 Run 선택", "input": {"type": "text", "text": "다른 Run 선택"}},
                       ]}
        user_input = interrupt(pending)
        history = [*state.get("input_history", []), user_input]
        if not replacement and user_input.get("text") == "다른 Run 선택":
            return {"pending": pending, "input_history": history, "route": "await", "replacement_pending": True}
        if option_field and user_input.get("type") == "comparison_options" and user_input.get(option_field):
            confirmation = StepResult(executionId=f"selection:{step.id}", stepId=step.id, status="verified",
                                      outputs={"value": user_input[option_field]})
            return {"pending": pending, "input_history": history, "route": "execute", "failure": None,
                    "plan_review_binding_digest": binding_digest(state, history=history),
                    "step_results": {**state.get("step_results", {}), step.id: confirmation.model_dump(mode="json")}}
        if not user_input.get("comparisonReference"):
            retry = isinstance(step, AwaitInputStep) and step.confirmation != "run_selection"
            retry = retry and user_input.get("text") not in {None, "부분 결과로 마치기"}
            return {"pending": pending, "input_history": history, "route": "replan" if retry else "compose",
                    "replacement_pending": False, "failure": failure or "MISSING_CONFIRMED_INPUT",
                    "feedback": "사용자가 입력을 확인했습니다. 새 입력에서 필수 조건을 확인하세요." if retry else failure}
        context = {**state.get("context", {}), "comparisonReference": user_input["comparisonReference"]}
        results = dict(state.get("step_results", {}))
        invalidated: set[str] = set()
        if replacement:
            for item in accepted.steps:
                if ((item.kind == "tool" and item.tool == "compare_runs")
                        or invalidated.intersection(item.depends_on)):
                    invalidated.add(item.id)
            results = {key: value for key, value in results.items() if key not in invalidated}
            publish_results(results)
        if isinstance(step, AwaitInputStep):
            results[step.id] = StepResult(
                executionId=f"selection:{step.id}", stepId=step.id, status="verified",
                outputs={"selection": _binding_context(context)["selected_runs"]},
            ).model_dump(mode="json")
        if replacement or not isinstance(step, AwaitInputStep):
            return {"pending": pending, "input_history": history, "context": context,
                    "replacement_pending": False, "route": "replan", "failure": "CONFIRMED_TARGETS_CHANGED",
                    "feedback": "사용자가 비교 대상을 새로 확인했습니다. 새 고정 참조를 유지해 계획을 제출하세요.",
                    "step_results": results, "plan_review": None, "plan_review_binding_digest": None,
                    "durable_steps": [key for key in state.get("durable_steps", []) if key not in invalidated]}
        return {"pending": pending, "input_history": history, "context": context,
                "replacement_pending": False, "route": "execute", "failure": None, "step_results": results,
                "plan_review_binding_digest": binding_digest(state, history=history, context=context),
                "durable_steps": [key for key in state.get("durable_steps", []) if key not in invalidated],
                "last_draft": None, "draft": None, "review": {}}

    def guard_replan(state):
        return {"route": "replan" if state.get("replans", 0) < 2 and state.get("elapsed", 0) < 600 else "compose"}

    def answer_evidence(state, results, evidence):
        if "plan" not in state:
            return evidence
        plan = PlanDraft.model_validate(state["plan"])
        bulk_steps = {
            step.id for step in plan.steps
            if isinstance(step, CompareStep) and isinstance(step.inputs.runs, ResultRef)
            and isinstance(step.inputs.runs.scope, CandidateScope)
        }
        summaries = {}
        for result in results:
            if result.stepId in bulk_steps and len(result.runRefs) > 2:
                summaries[result.executionId] = {
                    f"{result.executionId}:{row['id']}"
                    for row in result.outputs["toolResult"]["observations"]
                    if row["source"]["kind"] != "run"
                }
        return [row for row in evidence
                if row["executionId"] not in summaries or row["id"] in summaries[row["executionId"]]]

    def results_only(state):
        return (state.get("mode") == "data_request"
                and state.get("plan", {}).get("interpretation_requested") is False)

    def compose(state):
        mode = state.get("mode", "data_request")
        results = _results(state)
        evidence = collect_evidence(results)
        full_evidence = [entry.model_dump(mode="json") for entry in evidence]
        issue = _issue(state.get("failure"))
        review_blocked = state.get("failure") in {
            "PLAN_SEMANTIC_MISMATCH", "PLAN_SEMANTIC_UNCLEAR", "PLAN_REVIEW_UNAVAILABLE",
            "PLAN_REVIEW_INPUT_INVALID", "STALE_PLAN_REVIEW",
        }
        if "plan" not in state or results_only(state) or review_blocked:
            return {"route": "finalize", "rendered": facts_only(evidence, issue),
                    "evidence": full_evidence, "draft": None}
        numeric_values = collect_numeric_values(results, evidence) if mode == "data_request" else {}
        writer_evidence = [
            {**row, "value_parts": list(numeric_values[row["id"]])} if row["id"] in numeric_values else row
            for row in answer_evidence(state, results, full_evidence)
        ]
        payload = {"question": state["question"], "mode": mode,
                   "input_history": state.get("input_history", []),
                   "evidence": writer_evidence,
                   "search_evidence": collect_search_evidence(results),
                   "comparison_coverage": collect_comparison_coverage(results),
                   "step_statuses": [{"step": r.stepId, "status": r.status, "reason": r.reason} for r in results],
                   "issue": state.get("failure"), "feedback": state.get("feedback")}
        rewrite = state.get("route") == "rewrite"
        partial = bool(state.get("failure")) and not rewrite
        if partial and state.get("partial_composes", 0):
            return {"route": "finalize"}
        role = "ANSWER_REWRITE" if rewrite else "PARTIAL_COMPOSE" if partial else "COMPOSE"
        data, error, counts = model_call(state, role,
            f"{role}:{state.get('plan_revision')}:{len(state.get('input_history', []))}", models.compose, payload,
            numeric_values=numeric_values)
        changes: State = {**counts, "evidence": full_evidence, "draft": data,
                          "partial_composes": state.get("partial_composes", 0) + int(partial)}
        try:
            if error:
                raise ValueError(error)
            rendered, saved_draft = assemble_answer(data, mode, evidence, issue, numeric_values=numeric_values)
        except (ValueError, TypeError) as exc:
            progress.discard_answer("invalid_draft")
            if state.get("rewrites", 0) < 1 and not error and not partial:
                return {**changes, "route": "rewrite", "feedback": str(exc)[:600]}
            last = state.get("last_draft")
            return {**changes, "route": "finalize",
                    "rendered": assemble_answer(last, mode, evidence, issue)[0] if last else facts_only(evidence, issue),
                    "draft": last}
        if progress.enabled and (progress.current is None or progress.current.closed or not progress.current.chunks):
            # Saved outcomes restore at once; they never cause another writer call.
            stream = progress.start_answer("general" if mode == "general_only" else "interpretation", rewrite=rewrite)
            if mode == "general_only":
                for index, text in enumerate(saved_draft["paragraphs"]):
                    stream.append(f"paragraphs.{index}", text)
            else:
                for index, item in enumerate(saved_draft["interpretations"]):
                    stream.append(f"interpretations.{index}.text", item["text"])
                    for position, text in enumerate(item["assumptions"]):
                        stream.append(f"interpretations.{index}.assumptions.{position}", text)
                for index, item in enumerate(saved_draft["limitations"]):
                    stream.append(f"limitations.{index}.text", item["text"])
            stream.flush()
        return {**changes, "rendered": rendered, "draft": saved_draft, "last_draft": saved_draft,
                "route": "finalize" if mode == "general_only" else "review"}

    def rewrite(state):
        return {"rewrites": state.get("rewrites", 0) + 1, "route": "rewrite"}

    def review(state):
        draft = DataAnswerDraft.model_validate(state["draft"])
        if not draft.interpretations:
            return {"route": "finalize", "review": {"status": "SKIPPED", "answers": [], "reason": None}}
        payload = interpretation_review_payload(draft, state["evidence"], _results(state))
        data, error, counts = model_call(
            state, "REVIEW", f"interpretation-review:{state.get('plan_revision')}:{state.get('rewrites', 0)}:"
            f"{state.get('partial_composes', 0)}:{len(state.get('input_history', []))}", models.review, payload,
        )
        decision = (ReviewDecision.model_validate(data) if data else
                    ReviewDecision(status="UNAVAILABLE", answers=[], reason=error))
        choice = decision.answers[0].choice if decision.answers else None
        route = "rewrite" if choice == "overclaim" and state.get("rewrites", 0) < 1 else "finalize"
        return {**counts, "review": decision.model_dump(mode="json"), "route": route,
                "feedback": choice or error}

    def finalize(state):
        data = state.get("mode") != "general_only"
        outcome = state.get("review") or {"status": "SKIPPED", "answers": [], "reason": None}
        results = _results(state)
        refs = list({(r.runId, r.runVersionId): r.model_dump(mode="json")
                     for result in results for r in result.runRefs}.values())
        intent: Literal["COMPOSITE_ANSWER", "GENERAL_ANSWER"] = "COMPOSITE_ANSWER" if data else "GENERAL_ANSWER"
        failure = state.get("failure")
        draft = state.get("draft")
        incomplete_work = bool(failure) or any(
            result.status in {"partial", "blocked", "failed"} for result in results
        )
        completed = not failure and (
            draft is not None or (results_only(state) and bool(results) and not incomplete_work)
        )
        status: Literal["PARTIAL", "FAILED", "COMPLETE"] = "COMPLETE" if completed else "PARTIAL" if results else "FAILED"
        parsed_draft = (DataAnswerDraft if data else GeneralAnswerDraft).model_validate(draft) if draft else None
        snapshot = GraphV2AnswerSnapshotV1(
            implementationId="v2", graphVersion="v2", schemaVersion=1, intent=intent,
            question=state["question"], confirmedContext=state.get("context", {}).get("comparisonReference") or {},
            planRevision=state.get("plan_revision"), stepResults=results, evidence=state.get("evidence", []),
            draft=parsed_draft, answer=state.get("rendered") or "확인된 결과가 없습니다.",
            executionStatus=status, hasIncompleteWork=incomplete_work,
            review=ReviewDecision.model_validate(outcome), budget=_budget(state),
        )
        return {"answer": {"intent": intent, "status": status, "usedRunRefs": refs,
                           "answerSnapshot": snapshot.model_dump(mode="json")}}

    builder = StateGraph(State)
    for name, node in {
        "plan": plan, "validate_plan": validate, "review_plan": review_plan, "execute_step": execute, "await_input": wait_for_input,
        "guard_replan": guard_replan, "replan": replan, "compose_answer": compose,
        "guard_rewrite": rewrite, "review_answer": review, "finalize": finalize,
    }.items():
        builder.add_node(name, node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "validate_plan")
    builder.add_edge("replan", "validate_plan")
    builder.add_edge("guard_rewrite", "compose_answer")
    builder.add_edge("finalize", END)
    routes: dict[Hashable, str] = {"execute": "execute_step", "await": "await_input", "replan": "guard_replan",
              "plan_review": "review_plan",
              "compose": "compose_answer", "review": "review_answer", "rewrite": "guard_rewrite",
              "finalize": "finalize"}
    for name in ("validate_plan", "review_plan", "execute_step", "await_input", "compose_answer", "review_answer"):
        builder.add_conditional_edges(name, lambda s: s["route"], routes)
    builder.add_conditional_edges("guard_replan", lambda s: s["route"], {"replan": "replan", "compose": "compose_answer"})
    return builder.compile(checkpointer=checkpointer)


def _results(state):
    by_id = state.get("step_results", {})
    return [StepResult.model_validate(by_id[key]) for key in state.get("durable_steps", [])]
