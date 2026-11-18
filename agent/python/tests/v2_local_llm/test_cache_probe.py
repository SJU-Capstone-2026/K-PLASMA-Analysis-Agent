import importlib


def assessment(rows, samples):
    assert importlib.util.find_spec("evals.local_llm_cache_probe") is not None, (
        "native cache probe is missing"
    )
    return importlib.import_module("evals.local_llm_cache_probe").assess_probe(rows, samples)


def rows(cached=80):
    return [
        {"kind": "plan", "valid": True, "input_tokens": 100, "cached_tokens": 0, "save": "saved"},
        {"kind": "review", "status": "PASS"},
        {
            "kind": "plan",
            "valid": True,
            "input_tokens": 100,
            "cached_tokens": cached,
            "restore": "disk",
            "save": "saved",
        },
        {"kind": "review", "status": "PASS"},
    ]


def test_cache_probe_requires_actual_reuse_not_just_restore_success():
    for cached in (0, None):
        result = assessment(rows(cached), [{"pressure": 1, "swap_bytes": 100, "resident_bytes": 1000}])
        assert result["protocol_passed"] is False
    assert (
        assessment(rows(), [{"pressure": 1, "swap_bytes": 100, "resident_bytes": 1000}])["protocol_passed"]
        is True
    )


def test_cache_probe_does_not_accept_missing_samples_warning_or_swap_growth():
    assert assessment(rows(), [])["memory_passed"] is False
    for second in (
        {"pressure": 2, "swap_bytes": 100, "resident_bytes": 1000},
        {"pressure": 1, "swap_bytes": 101, "resident_bytes": 1000},
    ):
        result = assessment(rows(), [{"pressure": 1, "swap_bytes": 100, "resident_bytes": 1000}, second])
        assert result["memory_passed"] is False


def test_probe_refuses_existing_application_cache_before_contacting_models(tmp_path, monkeypatch):
    import pytest
    from kplasma_agent.v2_local_llm.config import Settings

    module = importlib.import_module("evals.local_llm_cache_probe")
    folder = tmp_path / "cache"
    folder.mkdir()
    payload = folder / "cache.json"
    payload.write_text("existing application snapshot")
    monkeypatch.setattr(
        module, "verify_artifacts", lambda *_: pytest.fail("models contacted before protecting cache")
    )
    with pytest.raises(ValueError, match="LOCAL_CACHE_PROBE_REQUIRES_EMPTY_CACHE"):
        module.run_probe(Settings(qwen_plan_cache_enabled=True, qwen_plan_cache_dir=str(folder)))
    assert payload.read_text() == "existing application snapshot"


def test_probe_checks_the_actual_restored_lookup_conditions():
    import pytest
    from kplasma_agent.v2_local_llm.core.contracts import PlanDraft

    module = importlib.import_module("evals.local_llm_cache_probe")
    check = getattr(module, "validate_artificial_lookup", None)
    assert callable(check), "restored predicate validation is missing"

    def literal(value, unit):
        return {
            "kind": "literal",
            "value": value,
            "unit": unit,
            "source": {"message_key": "question", "quote": "인공"},
        }

    plan = PlanDraft.model_validate(
        {
            "schema_version": 2,
            "request_mode": "data_request",
            "base_revision": None,
            "requirements": [],
            "steps": [
                {
                    "id": "lookup",
                    "kind": "tool",
                    "tool": "forward_lookup",
                    "inputs": {
                        "pressure": literal(2, "mTorr"),
                        "source_power": literal(100, "W"),
                        "bias_power": literal(200, "W"),
                    },
                }
            ],
        }
    )
    check(plan, 100)
    with pytest.raises(ValueError, match="LOCAL_CACHE_PROBE_PLAN_MISMATCH"):
        check(plan, 150)
