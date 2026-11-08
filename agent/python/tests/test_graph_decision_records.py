"""RECORD_REUSE graph flow. Every record and Run here is artificial test data."""

import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
import pytest

from fixtures import run
from kplasma_agent.answer_contracts import AnswerSnapshotV2
from kplasma_agent.config import Settings
from kplasma_agent.graphs.v1 import build_graph

SENTINEL = "SENTINEL-MEMO-비용초과-메모"


def ref(run_id):
    return {"runId": run_id, "runVersionId": f"synthetic-{run_id}-v1"}


def exp(record_id, *candidates):
    return {
        "version": 2,
        "reviewId": record_id,
        "id": record_id,
        "decision": "ADOPT",
        "question": "인공 후보 검토",
        "overallComment": "",
        "createdAt": "2026-09-20T00:00:00Z",
        "candidates": [
            {"runId": run_id, "runVersionId": f"synthetic-{run_id}-v0", "decision": decision, "note": note,
             "conditions": {"pressure": 6}}
            for run_id, decision, note in candidates
        ],
    }


RECORDS = [
    exp("EXP-1", ("SYN-A", "REJECT", f"비용이 높아 반려 {SENTINEL}"), ("SYN-B", "ADOPT", "채택")),
    exp("EXP-2", ("SYN-A", "REJECT", "예산 초과로 원가 부담"), ("SYN-C", "REJECT", "성능 부족")),
]


class Backend:
    def __init__(self, runs=(), records=RECORDS):
        self.runs = list(runs)
        self.records = records
        self.stages = []
        self.heartbeats = []
        self.record_reads = 0
        self.context_calls = []

    def context(self, refs=None, **kwargs):
        self.context_calls.append((refs, kwargs))
        referenced = [run(r["runId"]) for r in refs or []]
        return {"runs": self.runs, "referencedRuns": referenced, "context": {}}

    def decision_records(self):
        self.record_reads += 1
        return self.records

    def stage(self, value, **kwargs):
        self.stages.append(value)
        if kwargs:
            self.heartbeats.append({"stage": value, **kwargs})

    def attempt(self, stage):
        pass


class Model:
    def __init__(self, *selections):
        self.selections = list(selections)
        self.payloads = []

    def select_tool(self, instructions, payload):
        self.payloads.append(json.dumps(payload, ensure_ascii=False, default=str))
        name, arguments = self.selections.pop(0)
        return {"name": name, "arguments": arguments, "call_id": "call-1"}, {"model": "test", "responseItems": []}


def invoke(model, backend, question, context, thread="t"):
    graph = build_graph(model, backend, Settings(), InMemorySaver())
    config = {"configurable": {"thread_id": thread}}
    state = {"question": question, "request_id": thread, "context": context, "input_history": []}
    return graph, config, graph.invoke(state, config, durability="sync")


CANDIDATES = {"candidateReferences": [ref("SYN-A"), ref("SYN-B"), ref("SYN-C")]}


def snapshot(result):
    answer = result["answer"]
    AnswerSnapshotV2.model_validate(answer["answerSnapshot"])
    return answer


def test_view_returns_each_runs_records_without_excluding():
    backend = Backend()
    model = Model(("decision_records", {"action": "view"}))
    _, _, result = invoke(model, backend, "이 Run이 이전에 왜 그런 이유로 빠졌어?", {"activeRun": ref("SYN-A")})
    answer = snapshot(result)
    body = answer["answerSnapshot"]["result"]
    assert answer["intent"] == "RECORD_REUSE" and answer["status"] == "RECORDS_READY"
    assert body["threshold"] is None and body["excluded"] == [] and body["canUndo"] is False
    [row] = body["remaining"]
    assert row["runVersionId"] == "synthetic-SYN-A-v1" and row["count"] == 2
    assert [e["recordRunVersionId"] for e in row["entries"]] == ["synthetic-SYN-A-v0"] * 2
    assert "runVersionId" not in row["entries"][0]
    assert answer["usedRunRefs"] == [ref("SYN-A")]
    assert answer["answerSnapshot"]["contextProvenance"]["recordScope"] == "activeRun"
    assert backend.record_reads == 1


def test_cost_exclusion_at_threshold_one_uses_candidate_scope_in_order():
    backend = Backend()
    model = Model(("decision_records", {"action": "exclude"}))
    _, _, result = invoke(model, backend, "이 후보들 중 비용 반려 1건 이상 제외해줘", CANDIDATES)
    answer = snapshot(result)
    body = answer["answerSnapshot"]["result"]
    assert answer["status"] == "EXCLUSION_APPLIED" and body["threshold"] == 1 and body["canUndo"] is True
    assert [r["runId"] for r in body["excluded"]] == ["SYN-A"]
    assert [r["runId"] for r in body["remaining"]] == ["SYN-B", "SYN-C"]
    assert answer["answerSnapshot"]["summary"] == "비용 반려 1건 이상이 확인된 후보 1개를 제외했습니다."
    assert answer["usedRunRefs"] == [ref("SYN-B"), ref("SYN-C"), ref("SYN-A")]


def test_threshold_above_counts_reports_no_exclusion():
    model = Model(("decision_records", {"action": "exclude"}))
    _, _, result = invoke(model, Backend(), "비용 반려가 3건 이상인 후보 빼줘", CANDIDATES)
    answer = snapshot(result)
    assert answer["status"] == "NO_EXCLUSION"
    assert answer["answerSnapshot"]["summary"] == "비용 반려 3건 이상이 확인된 후보는 없습니다."


@pytest.mark.parametrize(
    ("reply", "status"),
    [
        ({"type": "decision_threshold", "threshold": 2}, "EXCLUSION_APPLIED"),
        ({"text": "3건"}, "NO_EXCLUSION"),
        ({"text": "많이"}, "NOTICE"),
        ({"type": "decision_threshold", "threshold": 0}, "NOTICE"),
    ],
)
def test_vague_threshold_asks_and_resumes_without_the_model(reply, status):
    model = Model(("decision_records", {"action": "exclude"}))
    graph, config, result = invoke(model, Backend(), "비용 반려가 많은 후보 제외해줘", CANDIDATES)
    assert "__interrupt__" in result
    pending = result["pending"]
    assert pending["type"] == "decision_threshold" and pending["reason"] == "DECISION_THRESHOLD"
    assert [o["input"] for o in pending["options"]] == [
        {"type": "decision_threshold", "threshold": 1},
        {"type": "decision_threshold", "threshold": 2},
    ]
    result = graph.invoke(Command(resume=reply), config, durability="sync")
    answer = snapshot(result)
    assert answer["status"] == status and len(model.payloads) == 1
    if status == "NOTICE":
        assert answer["answerSnapshot"]["result"]["notice"].startswith("제외 기준은 1건 이상의 정수")


@pytest.mark.parametrize(
    ("question", "context", "notice"),
    [
        ("성능 때문에 반려된 후보 제외해줘", CANDIDATES, "현재 시연에서는 비용 사유가 명확한"),
        ("비용 반려 1.5건 이상 제외", CANDIDATES, "제외 기준은 1건 이상의 정수"),
        ("이 후보들의 과거 기록 보여줘", {}, "먼저 후보 탐색을 실행하거나"),
    ],
)
def test_notices_answer_without_reading_records(question, context, notice):
    backend = Backend()
    model = Model(("decision_records", {"action": "exclude" if "제외" in question else "view"}))
    _, _, result = invoke(model, backend, question, context)
    answer = snapshot(result)
    body = answer["answerSnapshot"]["result"]
    assert answer["status"] == "NOTICE" and body["notice"].startswith(notice)
    assert body["remaining"] == body["excluded"] == answer["usedRunRefs"] == []
    assert backend.record_reads == 0 and backend.context_calls == []


def test_numeric_exclusion_routed_to_records_is_a_notice():
    model = Model(("decision_records", {"action": "exclude"}))
    _, _, result = invoke(model, Backend(), "Flux가 500 이상인 후보를 찾되, 비용 때문에 반려된 건 제외해줘", {})
    body = snapshot(result)["answerSnapshot"]["result"]
    assert body["notice"].startswith("수치 조건을 해석하지 못했습니다")


def test_exclusion_request_sent_to_another_tool_is_answered_as_records():
    backend = Backend()
    model = Model(("forward_lookup", {"conditions": {}}))
    _, _, result = invoke(model, backend, "이 후보들 중 비용 반려 1건 이상 제외해줘", CANDIDATES)
    answer = snapshot(result)
    selection = answer["answerSnapshot"]["toolSelection"]
    assert selection == {"call_id": "record-guard:call-1", "name": "decision_records", "arguments": {"action": "exclude"}}
    assert answer["status"] == "EXCLUSION_APPLIED"
    assert {"stage": "guard", "operationKind": "decision_records", "dependsOnContext": True} in backend.heartbeats


def test_reverse_search_excludes_cost_rejections_before_ranking():
    runs = [run("SYN-A", energy=39), run("SYN-B", energy=35), run("SYN-C", energy=20)]
    backend = Backend(runs)
    rule = {"metric": "meanIonEnergy", "operator": "gte", "value": 30, "unit": "eV"}
    model = Model(("reverse_search", {"constraints": [rule]}))
    _, _, result = invoke(model, backend, "에너지 30 eV 이상인 후보를 찾되, 비용 때문에 반려된 건 제외해줘", {})
    answer = snapshot(result)
    body = answer["answerSnapshot"]["result"]
    assert answer["intent"] == "REVERSE_SEARCH"
    assert [c["runId"] for c in answer["candidates"]] == ["SYN-B"]
    exclusion = body["recordExclusion"]
    assert exclusion["threshold"] == 1 and exclusion["canUndo"] is True
    assert [r["runId"] for r in exclusion["excluded"]] == ["SYN-A"]
    assert ref("SYN-A") in answer["usedRunRefs"]
    assert backend.record_reads == 1


def test_memo_text_never_reaches_the_model():
    model = Model(("decision_records", {"action": "view"}))
    graph, config, result = invoke(model, Backend(), "이 후보들의 과거 기록 보여줘", CANDIDATES)
    assert SENTINEL in json.dumps(result["answer"], ensure_ascii=False)
    assert all(SENTINEL not in payload for payload in model.payloads)
    assert SENTINEL not in result["answer"]["answerSnapshot"]["summary"]


WIRE = Path(__file__).resolve().parents[2] / "tests/support/answer-records-wire.json"


def wire_answers():
    """Artificial answers shared with the Java validator test, so both sides check one contract."""
    answers = {}
    _, _, result = invoke(Model(("decision_records", {"action": "exclude"})), Backend(),
                          "이 후보들 중 비용 반려 1건 이상 제외해줘", CANDIDATES, "wire-records")
    answers["records"] = result["answer"]
    _, _, result = invoke(Model(("decision_records", {"action": "exclude"})), Backend(),
                          "성능 때문에 반려된 후보 제외해줘", CANDIDATES, "wire-notice")
    answers["notice"] = result["answer"]
    runs = [run("SYN-A", energy=39), run("SYN-B", energy=35), run("SYN-C", energy=20)]
    rule = {"metric": "meanIonEnergy", "operator": "gte", "value": 30, "unit": "eV"}
    _, _, result = invoke(Model(("reverse_search", {"constraints": [rule]})), Backend(runs),
                          "에너지 30 eV 이상인 후보를 찾되, 비용 때문에 반려된 건 제외해줘", {}, "wire-reverse")
    answers["reverse"] = result["answer"]
    return answers


def _without_versions(answers):
    # Config and tool hashes change with unrelated settings; the record contract is what must match.
    for answer in answers.values():
        answer["answerSnapshot"].pop("versions")
    return answers


def test_shared_wire_fixture_matches_the_graph():
    expected = _without_versions(json.loads(WIRE.read_text(encoding="utf-8")))
    assert expected == _without_versions(json.loads(json.dumps(wire_answers())))
