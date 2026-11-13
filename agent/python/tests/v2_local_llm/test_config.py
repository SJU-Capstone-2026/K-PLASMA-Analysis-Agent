from pathlib import Path

import pytest

from kplasma_agent.v2_local_llm.config import Settings


def clean_env(monkeypatch):
    import os
    for key in os.environ:
        if key.startswith(("OPENAI_", "AGENT_", "PHOENIX_", "OTEL_", "LANGCHAIN_", "LANGSMITH_")) or key.upper().endswith("_PROXY"):
            monkeypatch.delenv(key, raising=False)


def test_explicit_local_settings_do_not_load_root_env_or_mutate_process(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    path = tmp_path / "private.env"
    path.write_text("AGENT_V2_LOCAL_LLM_WORKER_TOKEN=synthetic-worker\n"
                    "AGENT_V2_LOCAL_LLM_QWEN_TOKEN=synthetic-model\n"
                    "AGENT_V2_LOCAL_LLM_BACKEND_URL=http://127.0.0.1:8090\n")
    monkeypatch.setenv("AGENT_V2_LOCAL_LLM_QWEN_TOKEN", "explicit-local")
    settings = Settings.from_env(path)
    assert settings.model == "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"
    assert settings.context_tokens == Settings().context_tokens == 24576
    assert settings.d1_context_tokens == 32768
    assert settings.api_key == "explicit-local"
    assert settings.backend_url == "http://127.0.0.1:8090"
    assert not settings.phoenix_endpoint
    assert "explicit-local" not in repr(settings)
    import os
    assert "AGENT_V2_LOCAL_LLM_WORKER_TOKEN" not in os.environ


@pytest.mark.parametrize("key", ["OPENAI_API_KEY", "OPENAI_BASE_URL", "HTTPS_PROXY", "PHOENIX_API_KEY",
    "OTEL_EXPORTER_OTLP_ENDPOINT", "LANGSMITH_API_KEY", "AGENT_V2_PLAN_MODEL", "AGENT_V3_PLAN_MODEL"])
def test_inherited_cloud_credentials_and_destinations_are_rejected(tmp_path, monkeypatch, key):
    clean_env(monkeypatch)
    path = tmp_path / "private.env"
    path.write_text("")
    monkeypatch.setenv(key, "synthetic-contamination")
    with pytest.raises(ValueError, match="LOCAL_ENV_CONTAMINATION"):
        Settings.from_env(path)


def test_missing_explicit_file_does_not_fall_back_to_repository_dotenv(monkeypatch):
    clean_env(monkeypatch)
    with pytest.raises(ValueError, match="LOCAL_ENV_FILE_REQUIRED"):
        Settings.from_env()
    with pytest.raises(ValueError, match="LOCAL_ENV_FILE_REQUIRED"):
        Settings.from_env(Path("/nonexistent/synthetic-local.env"))


def test_native_physical_batch_can_be_small_without_reducing_the_context_window(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    path = tmp_path / "local.env"
    path.write_text("AGENT_V2_LOCAL_LLM_D1_CONTEXT_TOKENS=32768\n"
                    "AGENT_V2_LOCAL_LLM_D1_UBATCH_TOKENS=512\n")
    settings = Settings.from_env(path)
    assert settings.d1_context_tokens == 32768 and settings.d1_ubatch_tokens == 512


def test_runtime_checks_do_not_treat_a_ready_flag_or_json_claim_as_evidence(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    path = tmp_path / "private.env"
    path.write_text("AGENT_V2_LOCAL_LLM_READY=true\n")
    settings = Settings.from_env(path)
    assert hasattr(settings, "readiness"), "a local profile needs measured readiness checks"
    status = settings.readiness()
    assert status["ready"] is False
    assert "LOCAL_MODELS_NOT_PREPARED" in status["blockers"]
    assert "LOCAL_MEMORY_EVIDENCE_REQUIRED" in status["blockers"]
    assert "LOCAL_EGRESS_POLICY_UNVERIFIED" not in status["blockers"]


def test_gateway_uses_only_the_selected_local_models_and_keeps_review_enabled(monkeypatch):
    from kplasma_agent.v2_local_llm.core.model_gateway import V2LocalLLMSettings
    monkeypatch.setenv("AGENT_V2_LOCAL_LLM_PLAN_REVIEW_ENABLED", "false")
    monkeypatch.setenv("AGENT_V2_PLAN_MODEL", "cloud-model")
    selected = V2LocalLLMSettings.from_env(Settings(api_key="synthetic-qwen", d1_token="synthetic-d1"))
    assert selected.planner.model == selected.writer.model == "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"
    assert selected.decisions_model == "LiquidAI/d1-2B-GGUF:Q8_0"
    assert selected.decisions_url == "http://127.0.0.1:8081/v1/systemone"
    assert selected.plan_review_enabled is True
