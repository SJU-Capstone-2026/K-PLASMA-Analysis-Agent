"""Select the V3 decision-record engine; the choice is frozen into each request's version fingerprint.

Every engine implements ``execute(action, question, refs, records, threshold)`` and returns the same
``decisionEvidence`` contract, so the server validator, screen and plan contract stay shared.
"""
import os

ENGINE_ENV = "AGENT_V3_DECISION_ENGINE"
DEFAULT_ENGINE = "rag4"


class DecisionEngineError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _rag4_profile(record_policy=None):
    # Imported lazily so selecting another engine never loads this engine's modules.
    from .decision_rag.embedding import MODEL_FILES, MODEL_ID, REVISION
    from .decision_rag.evidence_selection import EVIDENCE_SELECTION_POLICY
    from .decision_rag.policy import RECORD_POLICY_VERSION
    return {"model": MODEL_ID, "revision": REVISION,
            "fileHashes": {name: value[1] for name, value in MODEL_FILES.items()},
            "minScore": 0.78, "relativeMargin": 0.08, "topK": 5,
            "selectionPolicy": EVIDENCE_SELECTION_POLICY, "recordPolicy": record_policy or RECORD_POLICY_VERSION,
            "rerankerEnabled": False, "experimentalFacets": False}


def _rag4_create(execution_mode):
    from .decision_rag.runtime import DecisionRecordEngine
    return DecisionRecordEngine(execution_mode)


def _rules3_profile():
    from .decision_rag.policy import COST_REGEX_3
    return _rag4_profile(COST_REGEX_3)


def _rules3_create(execution_mode):
    # Rules: cost-regex-3. Search: the rag4 retrieval until a replacement retriever is chosen.
    from .decision_rag.policy import COST_REGEX_3
    from .decision_rag.runtime import DecisionRecordEngine
    return DecisionRecordEngine(execution_mode, record_policy=COST_REGEX_3)


# ko-sroberta thresholds were tuned on the dev half of docs/evaluations/v3-embedding-candidates
# (strict explicit-support selection kept); its similarity scale is lower than E5's.
KOSR_MODEL_DIR_ENV = "AGENT_V3_RAG_KOSR_MODEL_DIR"
KOSR_MIN_SCORE, KOSR_RELATIVE_MARGIN = 0.47, 0.02


def _kosr_retrieval(spec):
    return {"policy": "kosr-1.strict-support.ko-sroberta-" + spec.revision[:7],
            "embedding": f"{spec.model_id}@{spec.revision}", "minScore": KOSR_MIN_SCORE,
            "relativeMargin": KOSR_RELATIVE_MARGIN, "topK": 5, "rerankerEnabled": False, "experimentalFacets": False}


def _kosr_profile():
    from .decision_rag.embedding import KO_SROBERTA
    from .decision_rag.evidence_selection import EVIDENCE_SELECTION_POLICY
    from .decision_rag.policy import COST_REGEX_3
    return {"model": KO_SROBERTA.model_id, "revision": KO_SROBERTA.revision,
            "fileHashes": {name: value[1] for name, value in KO_SROBERTA.files.items()},
            "modelDirEnv": KOSR_MODEL_DIR_ENV, "minScore": KOSR_MIN_SCORE, "relativeMargin": KOSR_RELATIVE_MARGIN,
            "topK": 5, "selectionPolicy": EVIDENCE_SELECTION_POLICY, "recordPolicy": COST_REGEX_3,
            "rerankerEnabled": False, "experimentalFacets": False}


def _kosr_create(execution_mode):
    # Rules: cost-regex-3. Search: ko-sroberta with the unchanged strict explicit-support selection.
    from .decision_rag.embedding import KO_SROBERTA
    from .decision_rag.policy import COST_REGEX_3
    from .decision_rag.runtime import DecisionRecordEngine
    return DecisionRecordEngine(execution_mode, record_policy=COST_REGEX_3, encoder_spec=KO_SROBERTA,
                                model_dir_env=KOSR_MODEL_DIR_ENV, min_score=KOSR_MIN_SCORE,
                                relative_margin=KOSR_RELATIVE_MARGIN, profile=_kosr_retrieval(KO_SROBERTA))


# Engine id -> (profile factory, engine factory). The first entry is the PR #36 engine.
ENGINES = {"rag4": (_rag4_profile, _rag4_create), "rules3-rag4": (_rules3_profile, _rules3_create),
           "rules3-kosr": (_kosr_profile, _kosr_create)}


def require_engine(engine_id):
    if engine_id not in ENGINES:
        raise DecisionEngineError("INVALID_V3_DECISION_ENGINE")
    return engine_id


def engine_from_env():
    return require_engine(os.getenv(ENGINE_ENV, "").strip() or DEFAULT_ENGINE)


def engine_profile(engine_id):
    return {"engine": require_engine(engine_id), **ENGINES[engine_id][0]()}


def create_engine(engine_id, execution_mode):
    return ENGINES[require_engine(engine_id)][1](execution_mode)
