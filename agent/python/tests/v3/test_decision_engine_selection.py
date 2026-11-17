"""Decision-record engine selection: default, validation, fingerprint freezing and lazy creation.

All records and engines below are artificial; no model or embedding file is loaded.
"""
from types import SimpleNamespace
from uuid import UUID

import pytest

from kplasma_agent.v3 import decision_engines, runtime_worker
from kplasma_agent.v3.config import Settings
from kplasma_agent.v3.core.contracts import DecisionRecordStep
from kplasma_agent.v3.core.executor import SequentialExecutor
from kplasma_agent.v3.core.model_gateway import V3Settings
from kplasma_agent.v3.decision_engines import DecisionEngineError, ENGINE_ENV
from kplasma_agent.v3.runtime import normalize_mode

REFS = [{"runId": "RUN-ONE", "runVersionId": str(UUID(int=1))}]
MODE = normalize_mode({"rulesEnabled": True, "ragEnabled": False})


class FakeEngine:
    created = []

    def __init__(self, execution_mode):
        self.execution_mode = execution_mode
        self.calls = []
        FakeEngine.created.append(self)

    def execute(self, action, question, refs, records, threshold=None):
        self.calls.append((action, question, refs, records, threshold))
        evidence = {"status": "ANSWERED"}
        return {"candidates": refs, "decisionEvidence": evidence, "rules": {}, "retrieval": {},
                "callCounts": {"rules": 1, "rag": 0}}


@pytest.fixture
def fake_engine(monkeypatch):
    FakeEngine.created = []
    monkeypatch.setitem(decision_engines.ENGINES, "fake",
                        (lambda: {"model": None, "recordPolicy": "fake-policy"}, FakeEngine))
    return FakeEngine


def settings(monkeypatch, value=None):
    if value is None:
        monkeypatch.delenv(ENGINE_ENV, raising=False)
    else:
        monkeypatch.setenv(ENGINE_ENV, value)
    return V3Settings.from_env(Settings())


def test_default_engine_is_the_existing_pr36_engine_with_its_unchanged_profile(monkeypatch):
    configured = settings(monkeypatch)
    assert configured.decision_engine == "rag4"
    profile = runtime_worker.versions_for_request(configured, MODE)["retrievalProfile"]
    assert profile["engine"] == "rag4"
    assert (profile["minScore"], profile["relativeMargin"], profile["topK"]) == (0.78, 0.08, 5)
    assert profile["recordPolicy"] == "cost-regex-2"
    assert profile["rerankerEnabled"] is False and profile["experimentalFacets"] is False


@pytest.mark.parametrize("value", ["  ", ""])
def test_blank_setting_falls_back_to_the_default(monkeypatch, value):
    assert settings(monkeypatch, value).decision_engine == "rag4"


@pytest.mark.parametrize("value", ["RAG4", "unknown", "rag4 "])
def test_unknown_engine_is_rejected_instead_of_silently_using_another(monkeypatch, value):
    if value == "rag4 ":
        # Surrounding whitespace is trimmed; only exact registered ids are accepted.
        assert settings(monkeypatch, value).decision_engine == "rag4"
        return
    with pytest.raises(DecisionEngineError) as error:
        settings(monkeypatch, value)
    assert error.value.code == "INVALID_V3_DECISION_ENGINE"


def test_engine_choice_changes_the_request_fingerprint(monkeypatch, fake_engine):
    default = runtime_worker.versions_for_request(settings(monkeypatch), MODE)
    other = runtime_worker.versions_for_request(settings(monkeypatch, "fake"), MODE)
    assert other["retrievalProfile"] == {"engine": "fake", "model": None, "recordPolicy": "fake-policy"}
    assert default["configFingerprint"] != other["configFingerprint"]


def test_paused_request_does_not_resume_on_a_different_engine(monkeypatch, fake_engine):
    saved = {"versions": runtime_worker.versions_for_request(settings(monkeypatch), MODE)}
    failed = []
    backend = SimpleNamespace(checkpoint=lambda: saved, fail=failed.append)
    models = SimpleNamespace(settings=settings(monkeypatch, "fake"))
    claim = {"request": {"requestId": "request-test", "graphVersion": "v3", "question": "조회",
                         "v3Options": MODE}}
    runtime_worker.execute_claim(claim, backend, models)
    assert failed == ["RECOVERY_VERSION_MISMATCH"]


def test_executor_creates_only_the_selected_engine_lazily(fake_engine):
    executions = SimpleNamespace(decision_records=lambda execution: [{"reviewId": "a"}])
    executor = SequentialExecutor(executions, MODE, engine_id="fake")
    assert fake_engine.created == []
    step = DecisionRecordStep.model_validate({
        "id": "records", "kind": "tool", "tool": "decision_records", "requirement_ids": ["r"],
        "inputs": {"action": "cost_exclusion", "query": "비용 반려 1건 이상 제외",
                   "source": {"message_key": "question", "quote": "비용 반려 1건 이상 제외"},
                   "runs": {"kind": "context_ref", "key": "selected_runs"},
                   "threshold": {"kind": "literal", "value": 1, "unit": None,
                                 "source": {"message_key": "question", "quote": "비용 반려 1건 이상 제외"}}}})
    inputs = {"action": "cost_exclusion", "query": "비용 반려 1건 이상 제외", "runs": REFS, "threshold": 1}
    result = executor._calculate("exec-1", step, inputs, [])
    assert len(fake_engine.created) == 1
    assert fake_engine.created[0].execution_mode == MODE
    assert fake_engine.created[0].calls == [("cost_exclusion", "비용 반려 1건 이상 제외", REFS,
                                             [{"reviewId": "a"}], 1)]
    assert result.status == "verified"


def test_executor_rejects_an_unregistered_engine_id():
    with pytest.raises(DecisionEngineError):
        SequentialExecutor(SimpleNamespace(), MODE, engine_id="missing")


def test_rules3_engine_changes_only_the_record_policy_in_its_profile():
    rag4, rules3 = decision_engines.engine_profile("rag4"), decision_engines.engine_profile("rules3-rag4")
    assert rules3["recordPolicy"] == "cost-regex-3"
    assert {k: v for k, v in rules3.items() if k not in {"engine", "recordPolicy"}} == \
        {k: v for k, v in rag4.items() if k not in {"engine", "recordPolicy"}}


def test_rules3_engine_counts_with_cost_regex_3_and_rag4_keeps_cost_regex_2():
    query = "선택한 후보 중 비용 반려 1건 이상 후보를 제외해줘."
    ref = REFS[0]
    records = [{"reviewId": "ART-UNDETERMINED", "targetRunId": ref["runId"], "targetRunRef": ref,
                "comparedRunRefs": [], "decision": "REJECT", "createdAt": "2026-01-01T00:00:00Z",
                "comment": "가격이 비싸지만 다른 평가 내용도 있어 사유를 단정하지 않았다.", "runSnapshots": [ref]}]
    old = decision_engines.create_engine("rag4", MODE).execute("cost_exclusion", query, REFS, records, 1)
    new = decision_engines.create_engine("rules3-rag4", MODE).execute("cost_exclusion", query, REFS, records, 1)
    assert old["rules"]["policy"] == "cost-regex-2" and old["rules"]["excludedRunIds"] == ["RUN-ONE"]
    assert new["rules"]["policy"] == "cost-regex-3" and new["rules"]["excludedRunIds"] == []
    assert new["rules"]["perRun"][0]["status"] == "사유 확인 필요"
    assert new["decisionEvidence"]["citations"] == []
