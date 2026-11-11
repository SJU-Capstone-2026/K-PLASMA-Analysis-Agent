"""v2 decision_records step. Every record and Run here is artificial test data."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from evals.v2_cases import runs
from evals.v2_harness import EvaluationJournal
from kplasma_agent.domain import decision_records as records
from kplasma_agent.graphs.v1 import _record_result
from kplasma_agent.graphs.v2 import build_v2_graph
from kplasma_agent.v2.bindings import resolve_inputs
from kplasma_agent.v2.composition import collect_evidence
from kplasma_agent.v2.contracts import CompareStep, DecisionRecordStep, PlanDraft, StepResult
from kplasma_agent.v2.executor import SequentialExecutor
from kplasma_agent.v2.plan_review import parse_plan_review
from kplasma_agent.v2.plan_validation import InvalidPlan, MissingRecordStep, validate_plan
from .test_plan_review import answers

SENTINEL = "SENTINEL-V2-메모-인공"
EXCLUDE = "에너지 40 eV 이상 찾되 비용 때문에 반려된 건 빼고 남은 후보끼리 압력 비교해줘"
MANY = "에너지 40 eV 이상 찾되 비용 반려가 많은 후보는 제외해줘"


def ref(run):
    return {"runId": run["runId"], "runVersionId": run["runVersionId"]}


def record(record_id, run_id, decision, note):
    return {"version": 2, "reviewId": record_id, "id": record_id, "decision": decision, "question": "인공 검토",
            "overallComment": "", "createdAt": "2026-11-01T00:00:00Z",
            "candidates": [{"runId": run_id, "runVersionId": f"{run_id}-recorded", "decision": decision,
                            "note": note, "conditions": {}}]}


RECORDS = [
    record("EXP-1", "SYN-C", "REJECT", f"비용이 높아 반려 {SENTINEL}"),
    record("EXP-2", "SYN-B", "REJECT", "비용은 문제없음, 수율 때문에 보류"),
]


def literal(value, quote):
    return {"kind": "literal", "value": value, "unit": None, "source": {"message_key": "question", "quote": quote}}


def group(step_id):
    return {"kind": "result_ref", "step_id": step_id, "field": "candidates", "scope": {"kind": "candidate_group"}}


def plan(question, steps, interpretation=False):
    return {"schema_version": 1, "request_mode": "data_request", "base_revision": None,
            "interpretation_requested": interpretation,
            "requirements": [{"id": "r", "text": question, "handled_by": [s["id"] for s in steps],
                              "sources": [{"message_key": "question", "quote": question}]}],
            "steps": [{"requirement_ids": ["r"], **s} for s in steps]}


def search_step(quote="40 eV 이상"):
    return {"id": "search", "kind": "tool", "tool": "reverse_search", "inputs": {"constraints": [
        {"field": "meanIonEnergy", "operator": "gte", "value": literal(40, quote)}]}}


def records_step(runs_binding, action="exclude", depends_on=("search",), threshold=None):
    return {"id": "records", "kind": "tool", "tool": "decision_records", "depends_on": list(depends_on),
            "inputs": {"action": action, "runs": runs_binding, "threshold": threshold}}


def compare_step():
    return {"id": "compare", "kind": "tool", "tool": "compare_runs", "depends_on": ["records"],
            "inputs": {"runs": group("records"), "fields": ["pressure"]}}


class Models:
    def __init__(self, plans, review=False, draft=None):
        self.plans = plans
        self.settings = SimpleNamespace(plan_review_enabled=review)
        self.draft = draft
        self.inputs = []

    def submit_plan(self, context):
        self.inputs.append(("plan", deepcopy(context)))
        chosen = deepcopy(self.plans[min(len([i for i in self.inputs if i[0] == "plan"]) - 1, len(self.plans) - 1)])
        chosen["base_revision"] = context["base_revision"]
        return chosen, {}

    def review_plan(self, context):
        self.inputs.append(("plan_review", deepcopy(context)))
        return parse_plan_review({"answers": answers("match", context)}, context).model_dump(mode="json"), {}

    def compose(self, context):
        self.inputs.append(("compose", deepcopy(context)))
        if self.draft is None:
            raise AssertionError("data-only results must not invoke the writer")
        return self.draft(context), {}

    def review(self, context):
        self.inputs.append(("review", deepcopy(context)))
        raise AssertionError("no interpretation to review")


def run_graph(question, models, port=None, context=None, checkpointer=None, config=None):
    port = port or EvaluationJournal(runs(), RECORDS)
    graph = build_v2_graph(models, port, checkpointer)
    state = graph.invoke({"request_id": "records", "question": question, "context": context or {},
                          "input_history": []}, config or {"recursion_limit": 100})
    return graph, state, port


def test_search_then_exclusion_then_comparison_of_the_remaining_runs():
    source = runs()
    models = Models([plan(EXCLUDE, [search_step(), records_step(group("search")), compare_step()])])
    _, state, port = run_graph(EXCLUDE, models)

    search, kept, compare = (port.steps[f"execution-1-{s}"] for s in ("search", "records", "compare"))
    assert kept["inputs"] == {"action": "exclude", "runs": [ref(r) for r in source[1:]], "threshold": 1,
                              "notice": None, "candidateExecutionId": "execution-1-search"}
    result = kept["result"]
    assert [r["runId"] for r in result["outputs"]["candidates"]] == ["SYN-B", "SYN-D"]
    assert [r["runId"] for r in result["outputs"]["excluded"]] == ["SYN-C"]
    assert result["groupId"] == "records" and result["reason"] == "EXCLUSION_APPLIED"
    # The comparison reads the whole remaining group, in the search order.
    assert compare["inputs"]["runs"] == [ref(source[1]), ref(source[3])]
    assert compare["inputs"]["candidateExecutionId"] == "execution-1-records"
    answer = state["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == "COMPLETE"
    assert "제외한 후보 1개: SYN-C" in answer["answer"] and SENTINEL not in answer["answer"]
    assert "SYN-C" not in {r["runId"] for r in compare["result"]["runRefs"]}


def test_v2_records_step_matches_agent_v1_for_the_same_input():
    source = runs()
    refs = [ref(r) for r in source]
    step = DecisionRecordStep.model_validate(records_step({"kind": "context_ref", "key": "candidate_references"},
                                                          depends_on=()))

    port = EvaluationJournal(source, RECORDS)
    result = SequentialExecutor(port).execute(1, step, {"candidate_references": refs}, {},
                                              question="이 후보 중 비용 때문에 반려된 건 빼줘")
    expected = _record_result({"action": "exclude", "threshold": 1, "refs": refs}, RECORDS)
    assert result.outputs["toolResult"] == expected
    assert [r.model_dump() for r in result.runRefs] == expected["usedRunRefs"]


@pytest.mark.parametrize(("reply", "threshold"), [
    ({"type": "decision_threshold", "threshold": 1}, 1),
    ({"type": "text", "text": "2건"}, 2),
])
def test_ambiguous_threshold_is_confirmed_without_another_model_call(reply, threshold):
    models = Models([plan(MANY, [search_step(), records_step(group("search"))])])
    config = {"configurable": {"thread_id": f"many-{threshold}"}, "recursion_limit": 100}
    graph, state, port = run_graph(MANY, models, checkpointer=InMemorySaver(), config=config)
    pending = state["__interrupt__"][0].value
    assert pending["type"] == "decision_threshold"
    assert [o["input"] for o in pending["options"]] == [
        {"type": "decision_threshold", "threshold": n} for n in (1, 2)]
    assert "execution-1-records" not in port.steps

    state = graph.invoke(Command(resume=reply), config)
    assert [kind for kind, _ in models.inputs] == ["plan"]
    assert port.steps["execution-1-records"]["inputs"]["threshold"] == threshold
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "COMPLETE"


def test_invalid_threshold_reply_ends_with_the_prototype_notice():
    models = Models([plan(MANY, [search_step(), records_step(group("search"))])])
    config = {"configurable": {"thread_id": "many-invalid"}, "recursion_limit": 100}
    graph, _, port = run_graph(MANY, models, checkpointer=InMemorySaver(), config=config)
    state = graph.invoke(Command(resume={"type": "text", "text": "많이"}), config)
    answer = state["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == "PARTIAL"
    assert records.NOTICES["THRESHOLD"] in answer["answer"]
    assert port.steps["execution-1-records"]["result"]["reason"] == "RECORD_NOTICE:THRESHOLD"


def test_notice_in_a_records_only_plan_is_partial_and_reads_no_records():
    question = "이 후보들 중 성능 때문에 반려된 건 빼줘"
    source = runs()
    models = Models([plan(question, [records_step({"kind": "context_ref", "key": "candidate_references"},
                                                  depends_on=())])])

    class Port(EvaluationJournal):
        def decision_records(self, execution):
            raise AssertionError("a notice must not read decision records")

    _, state, port = run_graph(question, models, port=Port(source, RECORDS),
                               context={"candidateReferences": [ref(r) for r in source[:2]]})
    answer = state["answer"]["answerSnapshot"]
    assert answer["executionStatus"] == "PARTIAL"
    assert records.NOTICES["COST_ONLY"] in answer["answer"]
    assert port.steps["execution-1-records"]["result"]["status"] == "failed"


def test_empty_confirmed_selection_ends_with_the_scope_notice():
    question = "이 후보들 중 비용 때문에 반려된 건 빼줘"
    step = DecisionRecordStep.model_validate(records_step({"kind": "context_ref", "key": "selected_runs"},
                                                          depends_on=()))
    port = EvaluationJournal(runs(), RECORDS)
    result = SequentialExecutor(port).execute(1, step, {"selected_runs": []}, {}, question=question)
    assert result.status == "failed" and result.reason == "RECORD_NOTICE:SCOPE"


def test_empty_search_leaves_an_empty_records_group_without_reading_records():
    port = EvaluationJournal(runs(), RECORDS)
    port.decision_records = lambda execution: pytest.fail("no Run, no records read")
    step = DecisionRecordStep.model_validate(records_step(group("search")))
    search = StepResult(executionId="saved-search", stepId="search", status="empty",
                        outputs={"candidates": []})
    result = SequentialExecutor(port).execute(1, step, {}, {"search": search}, question=EXCLUDE)
    assert result.status == "empty" and result.outputs["candidates"] == []


def test_notes_never_reach_a_model():
    def draft(context):
        fact = next(row["id"] for row in context["evidence"] if row["field"] == "recordSummary")
        return {"fact_ids": [fact], "interpretations": [], "limitations": []}

    models = Models([plan(EXCLUDE, [search_step(), records_step(group("search")), compare_step()], True)],
                    review=True, draft=draft)
    _, state, _ = run_graph(EXCLUDE, models)
    assert {kind for kind, _ in models.inputs} == {"plan", "plan_review", "compose"}
    payload = json.dumps([context for _, context in models.inputs], ensure_ascii=False)
    assert SENTINEL not in payload and "수율" not in payload
    assert state["answer"]["answerSnapshot"]["executionStatus"] == "COMPLETE"


def test_record_evidence_holds_counts_and_run_ids_only():
    raw = records.build_result("exclude", 1, [ref(r) for r in runs()[1:]], RECORDS)
    result = StepResult(executionId="e", stepId="records", status="verified",
                        outputs={"toolResult": raw, "candidates": [], "excluded": []})
    evidence = {row.id: row.value for row in collect_evidence([result])}
    assert evidence["e:SYN-C:costRejections"] == 1 and evidence["e:SYN-B:costRejections"] == 0
    assert evidence["e:excludedRuns"] == ["SYN-C"] and evidence["e:remainingRuns"] == ["SYN-B", "SYN-D"]
    assert SENTINEL not in json.dumps(evidence, ensure_ascii=False)


def test_comparison_after_records_reads_the_remaining_group():
    step = CompareStep.model_validate(compare_step())
    kept = StepResult(executionId="saved-records", stepId="records", status="verified",
                      outputs={"candidates": [ref(r) for r in runs()[:2]]})
    inputs = resolve_inputs(step, {}, {"records": kept})
    assert inputs["candidateExecutionId"] == "saved-records"


def validate(question, steps, context_keys=frozenset()):
    return validate_plan(PlanDraft.model_validate(plan(question, steps)), messages={"question": question},
                         context_keys=set(context_keys))


def test_plan_without_the_requested_exclusion_is_rejected():
    with pytest.raises(MissingRecordStep):
        validate(EXCLUDE, [search_step()])
    with pytest.raises(MissingRecordStep):
        validate(EXCLUDE, [search_step(), records_step(group("search"), action="view")])


@pytest.mark.parametrize(("runs_binding", "keys"), [
    (literal("SYN-A", "40 eV"), ()),
    ({"kind": "context_ref", "key": "R1"}, {"R1"}),
    ({"kind": "result_ref", "step_id": "search", "field": "candidates", "scope": {"kind": "scalar"}}, ()),
])
def test_records_targets_must_be_a_confirmed_or_whole_group_source(runs_binding, keys):
    with pytest.raises(InvalidPlan):
        validate(EXCLUDE, [search_step(), records_step(runs_binding), compare_step()], keys)


def test_forward_lookup_candidates_are_not_a_record_group():
    lookup = {"id": "search", "kind": "tool", "tool": "forward_lookup", "inputs": {}}
    with pytest.raises(InvalidPlan):
        validate(EXCLUDE, [lookup, records_step(group("search"))])


def test_candidate_references_are_only_a_records_target():
    question = "현재 후보 Run끼리 압력 비교해줘"
    compare = {"id": "compare", "kind": "tool", "tool": "compare_runs",
               "inputs": {"runs": {"kind": "context_ref", "key": "candidate_references"}, "fields": ["pressure"]}}
    with pytest.raises(InvalidPlan, match="candidate_references"):
        validate(question, [compare], {"candidate_references"})


def test_threshold_literal_must_match_the_question():
    question = "에너지 40 eV 이상 찾되 비용 반려 2건 이상인 후보는 빼줘"
    steps = [search_step(), records_step(group("search"), threshold=literal(2, "2건 이상"))]
    assert validate(question, steps).steps[1].inputs.threshold.value == 2
    with pytest.raises(InvalidPlan, match="threshold"):
        validate(question, [search_step(), records_step(group("search"), threshold=literal(3, "2건 이상"))])
    with pytest.raises(InvalidPlan, match="threshold"):
        validate(EXCLUDE, [search_step(), records_step(group("search"), threshold=literal(1, "반려된"))])
