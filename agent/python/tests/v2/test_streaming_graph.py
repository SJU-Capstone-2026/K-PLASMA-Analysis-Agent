"""Graph/public-preview integration with artificial runs and durable in-memory outcomes."""

from copy import deepcopy
import json

from fixtures import run
from kplasma_agent.answer_stream import AnswerStreamProjector
from kplasma_agent.graphs.v2 import build_v2_graph
from kplasma_agent.progress import ProgressReporter


class DurablePort:
    def __init__(self, runs=()):
        self.runs = list(runs)
        self.events = []
        self.revision = 0
        self.model_reservations = []
        self.model_outcomes = {}
        self.step_reservations = []
        self.step_results = {}
        self.progress = ProgressReporter(self)

    def public_event(self, kind, payload, key):
        payload = deepcopy(payload)
        if kind == "answer.start":
            self.revision += 1
            payload["answerRevision"] = self.revision
        if kind == "results.ready":
            for execution_id in payload["executionIds"]:
                assert execution_id in self.step_results, "only saved results may become public"
                assert self.step_results[execution_id]["status"] in {"verified", "partial", "empty"}
        event = {"seq": len(self.events) + 1, "kind": kind, "payload": payload, "key": key}
        self.events.append(event)
        return deepcopy(event)

    def reserve_model(self, kind, key):
        self.model_reservations.append(kind)
        attempt_id = f"{kind}:{key}"
        saved = self.model_outcomes.get(attempt_id)
        return {"attemptId": attempt_id, "callAllowed": saved is None, "outcome": deepcopy(saved)}

    def complete_model(self, attempt_id, outcome):
        assert attempt_id not in self.model_outcomes
        self.model_outcomes[attempt_id] = deepcopy(outcome)
        return {"outcome": deepcopy(outcome)}

    def accept_plan(self, plan):
        return {"revision": 1, "plan": plan.model_dump(mode="json")}

    def start_step(self, revision, step_id, inputs):
        assert revision == 1
        self.step_reservations.append((step_id, deepcopy(inputs)))
        execution_id = f"execution-{step_id}"
        saved = self.step_results.get(execution_id)
        return {"executionId": execution_id, "callAllowed": saved is None, "result": deepcopy(saved)}

    def load_context(self, execution_id):
        assert execution_id == "execution-compare"
        return deepcopy(self.runs)

    def save_result(self, result):
        assert result.executionId not in self.step_results
        self.step_results[result.executionId] = result.model_dump(mode="json")
        return {"result": deepcopy(self.step_results[result.executionId])}


class StreamingModels:
    def __init__(self, port, *, interpretation=None, review_choices=("within_evidence",), invalid=False):
        self.port = port
        self.interpretation = interpretation
        self.review_choices = list(review_choices)
        self.invalid = invalid
        self.provider_calls = []
        self.drafts = []
        self.before_return = []

    def submit_plan(self, context):
        self.provider_calls.append("plan")
        plan = {"schema_version": 1, "request_mode": "general_only", "base_revision": None,
                "interpretation_requested": False, "requirements": [], "steps": []}
        if self.interpretation is not None:
            question = context["messages"]["question"]
            plan.update(request_mode="data_request", interpretation_requested=self.interpretation,
                        requirements=[{"id": "request", "text": question,
                                       "sources": [{"message_key": "question", "quote": question}],
                                       "handled_by": ["compare"]}],
                        steps=[{"id": "compare", "kind": "tool", "tool": "compare_runs",
                                "requirement_ids": ["request"], "inputs": {
                                    "runs": {"kind": "context_ref", "key": "selected_runs"},
                                    "fields": ["pressure"]}}])
        return plan, {"inputTokens": 1, "outputTokens": 1}

    def review_plan(self, context):
        from runtime_v2_worker import matching_plan_review
        return matching_plan_review(context)

    def compose(self, context):
        raise AssertionError("a public stream must use the existing writer's streaming capability")

    def stream_compose(self, context, *, on_block, numeric_values=None):
        self.provider_calls.append("writer")
        attempt = self.provider_calls.count("writer")
        if context["mode"] == "general_only":
            draft = {"paragraphs": ["이온 에너지 분포를 설명합니다.", "분포의 폭은 별도 지표입니다."], "sources": []}
        else:
            evidence = next(row for row in context["evidence"]
                            if row["field"] == "pressure" and row["runRef"]["runId"] == "A")
            identifier = evidence["id"]
            if self.invalid:
                text = "측정값은 {{value:missing-evidence}}입니다."
            else:
                prefix = "압력만이 차이의 유일한 원인입니다. " if attempt == 1 else "관찰만으로 원인을 단정할 수 없습니다. "
                text = prefix + "압력은 {{value:" + identifier + "}}입니다."
            draft = {"fact_ids": [identifier], "interpretations": [{"id": "interpretation",
                      "evidence_ids": [identifier], "text": text, "assumptions": []}], "limitations": []}
        self.drafts.append(deepcopy(draft))
        projection = AnswerStreamProjector(context["mode"], on_block,
                                           evidence_ids={row["id"] for row in context["evidence"]},
                                           numeric_values=numeric_values)
        raw = json.dumps(draft, ensure_ascii=True)
        before = len(self.port.events)
        for start in range(0, len(raw), 7):
            projection.feed(raw[start:start + 7])
        # The actual ProgressReporter must publish while this writer invocation is still running.
        delivered = [event for event in self.port.events[before:] if event["kind"] == "answer.delta"]
        assert delivered, "no public delta arrived until after stream_compose returned"
        self.before_return.append(delivered)
        return draft, {"inputTokens": 1, "outputTokens": 1}

    def review(self, context):
        self.provider_calls.append("review")
        index = self.provider_calls.count("review") - 1
        choice = self.review_choices[min(index, len(self.review_choices) - 1)]
        assert "{{value:" not in json.dumps(context["interpretations"])
        return {"status": "ISSUE" if choice == "overclaim" else "PASS", "reason": None,
                "answers": [{"name": "interpretation_scope", "choice": choice, "confidence": 1.0,
                             "probabilities": {name: float(name == choice) for name in
                                               ("within_evidence", "overclaim", "unassessable")}}]}, {}


def test_plan_review_reports_its_real_activity_without_starting_an_interpretation_stream():
    port = DurablePort([{"runId": "A", "runVersionId": "A-v1", "pressure": 2},
                        {"runId": "B", "runVersionId": "B-v1", "pressure": 4}])
    invoke(StreamingModels(port, interpretation=False), port)
    activities = [e["payload"]["code"] for e in port.events if e["kind"] == "activity"]
    assert activities.count("PLAN_REVIEW") == 2
    assert "INTERPRET" not in activities
    assert not any(e["kind"] == "answer.start" for e in port.events)


def invoke(models, port):
    entries = [{"key": f"R{index}", "ref": {key: row[key] for key in ("runId", "runVersionId")}}
               for index, row in enumerate(port.runs, 1)]
    context = {"comparisonReference": {"entries": entries}} if entries else {}
    question = "선택한 두 Run의 압력을 비교하고 의미를 설명해줘." if entries else "IED가 뭐야?"
    return build_v2_graph(models, port, None).invoke({
        "request_id": "synthetic-request", "question": question, "context": context, "input_history": [],
    })["answer"]["answerSnapshot"]


def events(port, kind):
    return [event for event in port.events if event["kind"] == kind]


def preview_text(port, revision):
    blocks = {}
    for event in events(port, "answer.delta"):
        payload = event["payload"]
        if payload["answerRevision"] == revision:
            block = payload["blockId"]
            blocks[block] = blocks.get(block, "") + payload["text"]
    return "\n\n".join(blocks.values())


def test_general_graph_publishes_during_the_writer_with_the_same_two_model_roles():
    port = DurablePort()
    models = StreamingModels(port)
    snapshot = invoke(models, port)
    assert port.model_reservations == ["PLAN_INITIAL", "COMPOSE"]
    assert models.provider_calls == ["plan", "writer"]
    assert len(models.before_return) == 1
    assert preview_text(port, 1) == snapshot["answer"]
    assert snapshot["review"]["status"] == "SKIPPED"
    assert snapshot["budget"]["model_requests_used"] == 2
    assert not events(port, "answer.reset")


def test_successful_plan_validation_finishes_its_public_activity_before_writing():
    port = DurablePort()
    invoke(StreamingModels(port), port)
    validations = [event for event in events(port, "activity")
                   if event["payload"]["code"] == "PLAN_VALIDATE"]
    assert [event["payload"]["phase"] for event in validations] == ["started", "completed"]
    assert validations[0]["payload"]["activityId"] == validations[1]["payload"]["activityId"]
    assert validations[1]["seq"] < events(port, "answer.start")[0]["seq"]


def test_data_only_graph_publishes_saved_tool_results_without_a_writer_or_review():
    port = DurablePort([run("A", pressure=8), run("B", pressure=12)])
    models = StreamingModels(port, interpretation=False)
    snapshot = invoke(models, port)
    assert port.model_reservations == ["PLAN_INITIAL", "PLAN_REVIEW"]
    assert models.provider_calls == ["plan"]
    ready = events(port, "results.ready")[-1]
    assert ready["payload"]["executionIds"] == ["execution-compare"]
    assert snapshot["stepResults"][0] == port.step_results["execution-compare"]
    assert snapshot["draft"] is None and snapshot["executionStatus"] == "COMPLETE"
    assert snapshot["review"]["status"] == "SKIPPED"
    assert not events(port, "answer.start") and not events(port, "answer.delta")


def test_overclaim_rewrite_replaces_prose_in_a_new_version_and_keeps_verified_results():
    port = DurablePort([run("A", pressure=8), run("B", pressure=12)])
    models = StreamingModels(port, interpretation=True, review_choices=("overclaim", "within_evidence"))
    snapshot = invoke(models, port)
    assert port.model_reservations == ["PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE", "REVIEW", "ANSWER_REWRITE", "REVIEW"]
    assert models.provider_calls == ["plan", "writer", "review", "writer", "review"]
    assert len(port.step_reservations) == 1
    first, second = events(port, "answer.start")
    reset, = events(port, "answer.reset")
    assert first["payload"]["answerRevision"] == 1 and not first["payload"]["rewrite"]
    assert second["payload"]["answerRevision"] == 2 and second["payload"]["rewrite"]
    assert first["seq"] < reset["seq"] < second["seq"]
    assert reset["payload"]["streamId"] == first["payload"]["streamId"]
    assert first["payload"]["streamId"] != second["payload"]["streamId"]
    assert "유일한 원인" in preview_text(port, 1)
    assert "원인을 단정할 수 없습니다" in preview_text(port, 2)
    assert "유일한 원인" not in snapshot["answer"]
    assert "8 mTorr" in preview_text(port, 1) and "8 mTorr" in preview_text(port, 2)
    assert "{{value:" not in json.dumps([row["payload"] for row in events(port, "answer.delta")])
    assert snapshot["answer"].endswith(preview_text(port, 2))
    ready = [row for row in events(port, "results.ready") if row["payload"]["executionIds"]]
    assert len(ready) == 1 and ready[0]["seq"] < first["seq"]
    assert ready[0]["payload"]["executionIds"] == [snapshot["stepResults"][0]["executionId"]]
    assert snapshot["stepResults"][0] == port.step_results["execution-compare"]
    assert snapshot["budget"]["answer_rewrites_used"] == 1


def test_cached_writer_restores_the_complete_preview_without_another_provider_call():
    port = DurablePort()
    models = StreamingModels(port)
    original = invoke(models, port)
    assert models.provider_calls == ["plan", "writer"]
    port.events.clear()
    port.progress = ProgressReporter(port)
    restored = invoke(models, port)
    assert models.provider_calls == ["plan", "writer"]
    assert preview_text(port, 2) == restored["answer"] == original["answer"]
    assert restored["draft"] == original["draft"]
    assert len(events(port, "answer.start")) == 1
    reused = [event for event in events(port, "activity") if event["payload"]["code"] == "REUSE_RESULT"]
    assert len(reused) == 2 and all(event["payload"]["phase"] == "reused" for event in reused)
    assert not [event for event in events(port, "activity")
                if event["payload"]["code"] in {"PLAN", "GENERAL_ANSWER"}]


def test_cached_interpretation_resolves_saved_numeric_references_without_recalling_models():
    port = DurablePort([run("A", pressure=8), run("B", pressure=12)])
    models = StreamingModels(port, interpretation=True)
    original = invoke(models, port)
    assert models.provider_calls == ["plan", "writer", "review"]
    assert "{{value:" in json.dumps(models.drafts[0])
    port.events.clear()
    port.progress = ProgressReporter(port)
    restored = invoke(models, port)
    assert models.provider_calls == ["plan", "writer", "review"]
    assert restored["draft"] == original["draft"]
    assert restored["answer"] == original["answer"]
    preview = preview_text(port, 2)
    assert preview == restored["draft"]["interpretations"][0]["text"]
    assert "8 mTorr" in preview and "{{value:" not in preview
    assert port.step_results["execution-compare"] == restored["stepResults"][0]


def test_invalid_numeric_draft_clears_each_preview_and_keeps_only_verified_facts():
    port = DurablePort([run("A", pressure=8), run("B", pressure=12)])
    models = StreamingModels(port, interpretation=True, invalid=True)
    snapshot = invoke(models, port)
    assert port.model_reservations == ["PLAN_INITIAL", "PLAN_REVIEW", "COMPOSE", "ANSWER_REWRITE"]
    assert len(events(port, "answer.start")) == 2
    resets = events(port, "answer.reset")
    assert [row["payload"]["reason"] for row in resets] == ["INVALID_DRAFT", "INVALID_DRAFT"]
    assert [row["payload"]["answerRevision"] for row in resets] == [1, 2]
    assert all(preview_text(port, revision) == "측정값은 " for revision in (1, 2))
    assert "{{value:" not in json.dumps([row["payload"] for row in events(port, "answer.delta")])
    assert "측정값은" not in snapshot["answer"] and "missing-evidence" not in snapshot["answer"]
    assert snapshot["draft"] is None and snapshot["stepResults"]
