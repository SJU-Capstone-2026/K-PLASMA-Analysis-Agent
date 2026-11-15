"""rules3-kosr engine: ko-sroberta retrieval settings and cost-regex-3 rules. All records are artificial."""
import os
from pathlib import Path
from uuid import UUID

import pytest

from kplasma_agent.v3 import decision_engines
from kplasma_agent.v3.decision_rag.embedding import E5_SMALL, KO_SROBERTA
from kplasma_agent.v3.runtime import normalize_mode

REF = {"runId": "RUN-KOSR-A", "runVersionId": str(UUID(int=11))}
RAG = normalize_mode({"rulesEnabled": False, "ragEnabled": True})


def record(identifier, note):
    return {"reviewId": identifier, "targetRunId": REF["runId"], "targetRunRef": REF, "comparedRunRefs": [],
            "decision": "REJECT", "comment": note, "createdAt": "2026-01-01T00:00:00Z", "runSnapshots": [REF]}


def test_kosr_profile_pins_model_thresholds_and_rule_version():
    profile = decision_engines.engine_profile("rules3-kosr")
    assert profile["engine"] == "rules3-kosr"
    assert profile["model"] == "jhgan/ko-sroberta-multitask"
    assert profile["revision"] == KO_SROBERTA.revision
    assert profile["fileHashes"] == {name: value[1] for name, value in KO_SROBERTA.files.items()}
    assert (profile["minScore"], profile["relativeMargin"], profile["topK"]) == (0.47, 0.02, 5)
    assert profile["recordPolicy"] == "cost-regex-3"
    assert profile["modelDirEnv"] == "AGENT_V3_RAG_KOSR_MODEL_DIR"
    assert decision_engines.engine_profile("rag4")["minScore"] == 0.78


def test_e5_spec_keeps_the_pr36_input_format():
    assert (E5_SMALL.dimension, E5_SMALL.max_tokens, E5_SMALL.pad_token, E5_SMALL.prefixes) == \
        (384, 512, "<pad>", ("query: ", "passage: "))
    assert (KO_SROBERTA.dimension, KO_SROBERTA.max_tokens, KO_SROBERTA.pad_token, KO_SROBERTA.prefixes) == \
        (768, 128, "[PAD]", ("", ""))


def test_kosr_search_requires_its_own_model_directory(monkeypatch):
    pytest.importorskip("numpy")  # the search path imports the local index before checking settings
    monkeypatch.delenv("AGENT_V3_RAG_KOSR_MODEL_DIR", raising=False)
    monkeypatch.setenv("AGENT_V3_RAG_MODEL_DIR", "./some-e5-directory")  # the E5 setting must not be borrowed
    engine = decision_engines.create_engine("rules3-kosr", RAG)
    with pytest.raises(Exception) as error:
        engine.execute("search", "성능 부족으로 반려한 메모를 찾아줘.", [REF], [record("own", "성능이 부족하여 반려했다.")])
    assert getattr(error.value, "code", None) == "DECISION_RAG_NOT_CONFIGURED"


def test_kosr_search_uses_its_thresholds_and_reports_its_profile(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    from kplasma_agent.v3.decision_rag import service as rag_service
    seen = {}
    real = rag_service.RagService

    class SpyService(real):
        def __init__(self, *args, **kwargs):
            seen.update(min_score=kwargs["min_score"], relative_margin=kwargs["relative_margin"])
            super().__init__(*args, **kwargs)

    class Encoder:
        metadata = {"model": "ARTIFICIAL_V3_UNIT_TEST", "dimension": 3, "local": True}

        def encode(self, texts, *, kind="query"):
            return np.asarray([[1, 0, 0] for _ in texts], dtype=np.float32).reshape((-1, 3))

    monkeypatch.setattr(rag_service, "RagService", SpyService)
    engine = decision_engines.create_engine("rules3-kosr", RAG)
    engine.encoder, engine.index_dir, engine.synthetic = Encoder(), tmp_path, True
    outputs = engine.execute("search", "성능 부족으로 반려한 메모를 찾아줘.", [REF],
                             [record("own", "성능이 부족하여 반려했다.")])
    assert seen == {"min_score": 0.47, "relative_margin": 0.02}
    assert outputs["retrieval"]["profile"]["embedding"] == f"{KO_SROBERTA.model_id}@{KO_SROBERTA.revision}"
    assert outputs["retrieval"]["profile"]["minScore"] == 0.47
    assert [c["recordId"] for c in outputs["decisionEvidence"]["citations"]] == ["own"]


def test_local_kosr_model_matches_the_pinned_format_when_downloaded():
    directory = os.getenv("AGENT_V3_RAG_KOSR_MODEL_DIR", "")
    if not directory or not Path(directory, "model.onnx").is_file():
        pytest.skip("ko-sroberta model files are not downloaded")
    pytest.importorskip("onnxruntime")
    from kplasma_agent.v3.decision_rag.embedding import LocalEncoder
    encoder = LocalEncoder(Path(directory), spec=KO_SROBERTA)
    vectors = encoder.encode(["비용 때문에 반려된 기록", "원가 부담이 커서 반려했다."], kind="passage")
    assert vectors.shape == (2, 768)
    assert encoder.metadata["model"] == KO_SROBERTA.model_id and encoder.metadata["prefixes"] == ["", ""]
