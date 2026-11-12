"""Feature isolation and real step orchestration; all records/models below are artificial."""
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from kplasma_agent.v3.core.bindings import resolve_inputs
from kplasma_agent.v3.core.contracts import DecisionRecordStep, PlanDraft
from kplasma_agent.v3.core.executor import SequentialExecutor
from kplasma_agent.v3.core.model_gateway import planner_instructions, submit_plan_tool_schema
from kplasma_agent.v3.core.plan_validation import InvalidPlan, validate_plan
from kplasma_agent.v3.decision_rag import policy
from kplasma_agent.v3.decision_rag.runtime import DecisionRecordEngine
from kplasma_agent.v3.graph import build_v3_graph
from kplasma_agent.v3.runtime import normalize_mode

REFS = [{"runId": "RUN-ONE", "runVersionId": str(UUID(int=1))},
        {"runId": "RUN-TWO", "runVersionId": str(UUID(int=2))}]
QUERY = "선택한 후보 중 비용 반려 2건 이상 후보를 제외해줘."


def mode(rules=True, rag=False):
    return normalize_mode({"rulesEnabled": rules, "ragEnabled": rag})


def record(identifier, ref, note, decision="REJECT"):
    return {"reviewId": identifier, "targetRunId": ref["runId"], "targetRunRef": ref,
            "comparedRunRefs": [], "decision": decision, "comment": note,
            "createdAt": "2026-01-01T00:00:00Z", "runSnapshots": [ref]}


def step(action="cost_exclusion", query=QUERY):
    return DecisionRecordStep.model_validate({"id": "records", "kind": "tool", "tool": "decision_records",
        "requirement_ids": ["records_req"], "inputs": {
            "action": action, "query": query, "source": {"message_key": "question", "quote": query},
            "runs": {"kind": "context_ref", "key": "selected_runs"},
            "threshold": {"kind": "literal", "value": 2, "unit": None,
                          "source": {"message_key": "question", "quote": query}} if action == "cost_exclusion" else None}})


def plan(action="cost_exclusion", query=QUERY):
    return PlanDraft.model_validate({"schema_version": 2, "request_mode": "data_request", "base_revision": None,
        "requirements": [{"id": "records_req", "text": query,
                          "sources": [{"message_key": "question", "quote": query}], "handled_by": ["records"]}],
        "steps": [step(action, query).model_dump(mode="json")]})


def test_mode_digest_is_canonical_and_rejects_tampering():
    current = mode()
    assert normalize_mode(dict(reversed(list(current.items())))) == current
    with pytest.raises(ValueError, match="DIGEST"):
        normalize_mode({**current, "ragEnabled": True})
    with pytest.raises(ValueError):
        normalize_mode({"rulesEnabled": "false", "ragEnabled": False})


@pytest.mark.parametrize("rules,rag,actions", [(False,False,[]),(True,False,["cost_exclusion"]),
                                             (False,True,["search"]),(True,True,["search","cost_exclusion"])])
def test_off_tools_and_actions_are_absent_from_the_actual_submit_schema(rules, rag, actions):
    schema = submit_plan_tool_schema(mode(rules, rag))["parameters"]
    raw = json.dumps(schema)
    if not actions:
        assert "decision_records" not in raw
        assert "DecisionRecordStep" not in raw
        assert "저장된 판단 기록 도구" not in planner_instructions(mode(rules, rag))
    else:
        assert schema["$defs"]["DecisionRecordInputs"]["properties"]["action"]["enum"] == actions


def test_disabled_actions_do_not_read_records_reserve_steps_or_initialize_an_encoder():
    class NoCalls:
        progress = None
        def __getattr__(self, name):
            raise AssertionError("disabled feature attempted " + name)
    result = SequentialExecutor(NoCalls(), mode(False, False)).execute(1, step(), {}, {})
    assert result.status == "blocked"
    with pytest.raises(ValueError, match="DISABLED"):
        DecisionRecordEngine(mode(False, False)).execute("search", "q", REFS, [])


def test_cost_exclusion_counts_all_unique_records_but_never_assigns_shared_notes():
    records = [record("a", REFS[0], "비용이 높아 반려"), record("b", REFS[0], "가격이 비싸서 반려"),
               record("c", REFS[1], "비용과 무관하며 성능 부족"),
               {"id":"shared", "version":2, "decision":"ADOPT", "createdAt":"2026-01-01T00:00:00Z",
                "candidates":[{**ref,"decision":"REJECT","note":""} for ref in REFS],
                "overallComment":"비용이 매우 비싸서 반려"}]
    outputs = DecisionRecordEngine(mode()).execute("cost_exclusion", QUERY, REFS, records, 2)
    assert outputs["candidates"] == [REFS[1]]
    assert outputs["rules"]["perRun"][0]["costRejectionRecordIds"] == ["a","b"]
    assert outputs["rules"]["perRun"][1]["count"] == 0
    assert outputs["callCounts"] == {"rules":1,"rag":0}
    assert len(outputs["decisionEvidence"]["citations"]) == 2
    assert "embedding" not in outputs["retrieval"]


def test_rag_only_does_not_call_cost_aggregation_and_never_reads_other_run_as_subject(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    class Encoder:
        metadata = {"model":"ARTIFICIAL_V3_UNIT_TEST","dimension":3,"local":True}
        def encode(self, texts, *, kind="query"):
            return np.asarray([[1,0,0] for _ in texts], dtype=np.float32).reshape((-1,3))
    def no_rule_calls(*args):
        raise AssertionError("RAG-only called cost aggregation")
    monkeypatch.setattr(policy, "summarize", no_rule_calls)
    engine=DecisionRecordEngine(mode(False,True),encoder=Encoder(),index_dir=tmp_path,synthetic=True)
    records=[record("own",REFS[0],"성능이 부족하여 반려했다."),
             record("other",REFS[1],"성능이 부족하여 반려했다.")]
    outputs=engine.execute("search","성능 부족으로 반려한 메모를 찾아줘.",[REFS[0]],records)
    assert outputs["callCounts"] == {"rules":0,"rag":1}
    assert outputs["candidates"] == [REFS[0]]
    assert outputs["rules"]["policy"] == "disabled"
    citations=outputs["decisionEvidence"]["citations"]
    assert len(citations)==1 and citations[0]["recordId"]=="own"
    empty=engine.execute("search","관련 메모를 찾아줘.",[REFS[0]],[])
    assert empty["decisionEvidence"]["status"] == "NO_EVIDENCE"
    assert empty["decisionEvidence"]["citations"] == []
    assert empty["candidates"] == [REFS[0]]


def test_history_counts_are_by_run_id_even_when_two_versions_are_selected():
    older={**REFS[0],"runVersionId":str(UUID(int=3))}
    refs=[REFS[0],older,REFS[1]]
    outputs=DecisionRecordEngine(mode()).execute("cost_exclusion",QUERY,refs,
        [record("current",REFS[0],"가격이 비싸서 반려"),record("older",older,"비용이 높아 반려")],2)
    assert outputs["candidates"] == [REFS[1]]
    assert len(outputs["rules"]["perRun"]) == 2
    assert outputs["rules"]["perRun"][0]["count"] == 2
    assert outputs["decisionEvidence"]["scopeRunRefs"] == refs


def test_record_query_and_threshold_cannot_be_changed_by_the_plan():
    original = plan()
    validate_plan(original, messages={"question":QUERY}, context_keys={"selected_runs"})
    changed = original.model_dump(mode="json")
    changed["steps"][0]["inputs"]["threshold"]["value"] = 1
    with pytest.raises(InvalidPlan, match="threshold"):
        validate_plan(PlanDraft.model_validate(changed), messages={"question":QUERY}, context_keys={"selected_runs"})
    changed = original.model_dump(mode="json")
    changed["steps"][0]["inputs"]["query"] = "다른 질문"
    with pytest.raises(InvalidPlan, match="original"):
        validate_plan(PlanDraft.model_validate(changed), messages={"question":QUERY}, context_keys={"selected_runs"})


def test_context_scope_is_exact_and_unknown_run_cannot_be_bound():
    result = resolve_inputs(step(), {"selected_runs":REFS,"comparison_entries":[{"ref":r} for r in REFS]}, {})
    assert result["runs"] == REFS
    with pytest.raises(ValueError, match="selected_runs"):
        resolve_inputs(step(), {"selected_runs":REFS,"comparison_entries":[{"ref":REFS[0]}]}, {})


def test_record_tool_is_a_real_durable_graph_step_and_mode_is_saved_in_answer():
    from v3.runtime_helpers import matching_plan_review
    class Models:
        execution_mode = mode()
        settings = SimpleNamespace(plan_review_enabled=True)
        def submit_plan(self, payload): return plan().model_dump(mode="json"), {}
        def review_plan(self, payload): return matching_plan_review(payload)
    class Port:
        def __init__(self): self.calls=[]
        def reserve_model(self, kind, key): return {"attemptId":key,"callAllowed":True,"outcome":None}
        def complete_model(self, key, data): return {"outcome":data}
        def accept_plan(self, draft): return {"plan":draft.model_dump(mode="json"),"revision":1}
        def start_step(self, revision, identifier, inputs):
            self.calls.append((identifier,inputs))
            return {"executionId":"saved-records","callAllowed":True}
        def decision_records(self, execution):
            return [record("a",REFS[0],"비용이 높아 반려"),record("b",REFS[0],"비용이 비싸서 반려")]
        def save_result(self, result): return {"result":result.model_dump(mode="json")}
    port=Port()
    graph=build_v3_graph(Models(),port,InMemorySaver())
    state=graph.invoke({"request_id":"record-test","question":QUERY,"input_history":[],"execution_mode":mode(),
        "context":{"comparisonReference":{"entries":[{"key":f"R{i}","ref":ref} for i,ref in enumerate(REFS)]}}},
        {"configurable":{"thread_id":"record-test"},"recursion_limit":100})
    answer=state["answer"]["answerSnapshot"]
    assert state["plan_review_enabled"] is True
    assert answer["executionMode"] == mode()
    assert answer["executionStatus"] == "COMPLETE"
    assert answer["stepResults"][0]["outputs"]["candidates"] == [REFS[1]]
    assert answer["decisionEvidence"][0]["rules"]["excludedRunIds"] == [REFS[0]["runId"]]
    assert len(port.calls) == 1
