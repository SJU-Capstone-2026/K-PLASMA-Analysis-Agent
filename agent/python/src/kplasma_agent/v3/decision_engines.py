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


def _rag4_profile():
    # Imported lazily so selecting another engine never loads this engine's modules.
    from .decision_rag.embedding import MODEL_FILES, MODEL_ID, REVISION
    from .decision_rag.evidence_selection import EVIDENCE_SELECTION_POLICY
    from .decision_rag.policy import RECORD_POLICY_VERSION
    return {"model": MODEL_ID, "revision": REVISION,
            "fileHashes": {name: value[1] for name, value in MODEL_FILES.items()},
            "minScore": 0.78, "relativeMargin": 0.08, "topK": 5,
            "selectionPolicy": EVIDENCE_SELECTION_POLICY, "recordPolicy": RECORD_POLICY_VERSION,
            "rerankerEnabled": False, "experimentalFacets": False}


def _rag4_create(execution_mode):
    from .decision_rag.runtime import DecisionRecordEngine
    return DecisionRecordEngine(execution_mode)


# Engine id -> (profile factory, engine factory). The first entry is the PR #36 engine.
ENGINES = {"rag4": (_rag4_profile, _rag4_create)}


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
