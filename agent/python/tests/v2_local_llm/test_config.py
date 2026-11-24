from pathlib import Path

import pytest

from kplasma_agent.v2_local_llm.config import Settings


def clean_env(monkeypatch):
    import os
    for key in os.environ:
        if key.startswith(("OPENAI_", "AGENT_", "PHOENIX_", "OTEL_", "LANGCHAIN_", "LANGSMITH_")) or key.upper().endswith("_PROXY"):
            monkeypatch.delenv(key, raising=False)


def test_v24_context_mode_defaults_full_and_binds_recovery_identity(tmp_path, monkeypatch):
    from dataclasses import replace
    clean_env(monkeypatch)
    path = tmp_path / "local.env"
    path.write_text("")
    full = Settings.from_env(path)
    assert full.d1_context_mode == "full"
    selected = replace(full, d1_context_mode="per_check")
    assert full.versions()["d1Context"]["mode"] == "full"
    assert selected.versions()["d1Context"]["mode"] == "per_check"
    assert full.versions()["configFingerprint"] != selected.versions()["configFingerprint"]


@pytest.mark.parametrize("mode", ["auto", "per-check", "FULL", "disabled"])
def test_invalid_context_mode_is_rejected_before_models(tmp_path, monkeypatch, mode):
    clean_env(monkeypatch)
    path = tmp_path / "local.env"
    path.write_text(f"AGENT_V2_LOCAL_LLM_D1_CONTEXT_MODE={mode}\n")
    with pytest.raises(ValueError, match="LOCAL_D1_CONTEXT_CONFIG_INVALID"):
        Settings.from_env(path)


@pytest.mark.parametrize("engine,group,size", [("mlx",16,1),("mlx",1,4),("llama.cpp",1,1),("mlx",1,2)])
def test_d1_requires_singleton_mlx_profile(tmp_path, monkeypatch, engine, group, size):
    clean_env(monkeypatch)
    path = tmp_path / "local.env"
    path.write_text(f"AGENT_V2_LOCAL_LLM_D1_ENGINE={engine}\nAGENT_V2_LOCAL_LLM_D1_GROUP_SIZE={group}\n"
                    f"AGENT_V2_LOCAL_LLM_D1_INDEPENDENT_BATCH_SIZE={size}\n")
    with pytest.raises(ValueError, match="LOCAL_D1_GROUP_CONFIG_INVALID"):
        Settings.from_env(path)


def test_mlx8_single_and_english_compact_remain_the_v24_defaults(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    path=tmp_path / "local.env"
    path.write_text("")
    settings=Settings.from_env(path)
    assert settings.d1_engine == "mlx"
    assert settings.d1_precision == "q8"
    assert settings.d1_model == "LiquidAI/d1-2B:MLX8"
    assert settings.d1_url == "http://127.0.0.1:8083/v1/systemone"
    assert settings.d1_group_size == settings.d1_independent_batch_size == 1
    assert settings.d1_input_profile == "en-compact-no-view"
    assert "v2.4" in settings.graph_build_id


def test_bf16_single_remains_an_explicit_comparison_profile(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    path=tmp_path / "local.env"
    path.write_text("AGENT_V2_LOCAL_LLM_D1_PRECISION=bf16\nAGENT_V2_LOCAL_LLM_D1_INPUT_PROFILE=ko-full\n")
    settings=Settings.from_env(path)
    assert settings.d1_precision == "bf16"
    assert settings.d1_model == "LiquidAI/d1-2B:BF16"
    assert settings.d1_input_profile == "ko-full"


def test_flash_mlx4_is_a_pinned_singleton_review_profile(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    path = tmp_path / "local.env"
    path.write_text("AGENT_V2_LOCAL_LLM_D1_PRECISION=q4\n")
    settings = Settings.from_env(path)
    assert settings.d1_model == "perplexity-ai/pplx-decider-flash-v1.2:MLX4"
    assert settings.d1_group_size == settings.d1_independent_batch_size == 1
    assert settings.versions()["d1Quantization"] == "MLX-affine4-g64"

    with path.open("a") as env:
        env.write("AGENT_V2_LOCAL_LLM_D1_MODEL=LiquidAI/d1-2B:MLX8\n")
    with pytest.raises(ValueError, match="LOCAL_D1_PRECISION_CONFIG_INVALID"):
        Settings.from_env(path)


@pytest.mark.parametrize("key,value", [("D1_PRECISION","q6"),("D1_INPUT_PROFILE","english"),
                                        ("D1_PRECISION","BF16-bad"),("D1_MODEL","LiquidAI/d1-2B-GGUF:Q8_0")])
def test_unsupported_d1_precision_and_input_profiles_fail_closed(tmp_path, monkeypatch, key, value):
    clean_env(monkeypatch)
    path=tmp_path / "local.env"
    path.write_text(f"AGENT_V2_LOCAL_LLM_{key}={value}\n")
    with pytest.raises(ValueError, match="LOCAL_D1_(PRECISION|INPUT)_CONFIG_INVALID"):
        Settings.from_env(path)


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
    assert selected.decisions_model == "LiquidAI/d1-2B:MLX8"
    assert selected.decisions_url == "http://127.0.0.1:8083/v1/systemone"
    assert selected.plan_review_enabled is True


def test_plan_cache_defaults_off_and_anchors_paths_to_the_checkout(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    path=tmp_path/'private.env'
    path.write_text('')
    before=Settings.from_env(path)
    monkeypatch.chdir(tmp_path)
    after=Settings.from_env(path)
    assert before.qwen_plan_cache_enabled is False
    assert before.qwen_plan_cache_dir == after.qwen_plan_cache_dir
    assert Path(after.qwen_plan_cache_dir).is_absolute()
    assert Path(after.qwen_plan_cache_dir).parts[-4:] == ('.local','cache','v2_localLLM','qwen-plan-cache-KV')


def test_plan_cache_settings_are_explicit_and_fingerprinted(tmp_path, monkeypatch):
    from dataclasses import replace
    clean_env(monkeypatch)
    path=tmp_path/'private.env'
    cache=tmp_path/'private-cache'
    path.write_text(f'AGENT_V2_LOCAL_LLM_QWEN_PLAN_CACHE_ENABLED=true\nAGENT_V2_LOCAL_LLM_QWEN_PLAN_CACHE_DIR={cache}\n')
    settings=Settings.from_env(path)
    assert settings.qwen_plan_cache_enabled is True
    assert settings.qwen_plan_cache_dir == str(cache)
    assert settings.versions()['configFingerprint'] != replace(settings,qwen_plan_cache_enabled=False).versions()['configFingerprint']
    assert not cache.exists(), 'reading settings must not create cache files'


def test_plan_cache_rejects_unrecognized_boolean(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    path=tmp_path/'private.env'
    path.write_text('AGENT_V2_LOCAL_LLM_QWEN_PLAN_CACHE_ENABLED=maybe\n')
    with pytest.raises(ValueError,match='LOCAL_CACHE_CONFIG_INVALID'):
        Settings.from_env(path)


def test_precision_and_input_representation_are_fingerprinted():
    from dataclasses import replace
    from kplasma_agent.v2_local_llm.core.d1_input import VERSION
    settings=Settings()
    versions=settings.versions()
    assert versions['d1Precision']=='q8'
    assert versions['d1Input']['profile']=='en-compact-no-view'
    assert versions['d1Input']['version']==VERSION
    assert len(versions['d1Input']['sha256'])==64
    assert versions['configFingerprint']!=replace(settings,d1_input_profile='ko-full').versions()['configFingerprint']
    assert versions['configFingerprint']!=replace(settings,d1_precision='bf16',
        d1_model='LiquidAI/d1-2B:BF16').versions()['configFingerprint']
