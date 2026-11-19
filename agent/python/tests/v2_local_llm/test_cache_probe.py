import importlib

import pytest


def review_row(choice="match"):
    from kplasma_agent.v2_local_llm.core.plan_review import parse_plan_review
    from .test_plan_review import answers, example_context

    context = example_context()
    data = answers(context=context)
    data[0]["choice"] = choice
    result = parse_plan_review({"answers": data}, context).model_dump(mode="json")
    return {"kind": "review", "status": result["status"], "result": result}


def assessment(rows, samples):
    assert importlib.util.find_spec("evals.local_llm_cache_probe") is not None, (
        "native cache probe is missing"
    )
    return importlib.import_module("evals.local_llm_cache_probe").assess_probe(rows, samples)


def rows(cached=80):
    return [
        {"kind": "plan", "valid": True, "input_tokens": 100, "cached_tokens": 0, "save": "saved"},
        review_row(),
        {
            "kind": "plan",
            "valid": True,
            "input_tokens": 100,
            "cached_tokens": cached,
            "restore": "disk",
            "save": "saved",
        },
        review_row(),
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


@pytest.mark.parametrize("choice", ["match", "missing", "unclear"])
def test_cache_protocol_accepts_valid_review_without_hiding_its_semantic_verdict(choice):
    from copy import deepcopy

    values = rows()
    values[-1] = review_row(choice)
    before = deepcopy(values)
    result = assessment(values, [{"pressure": 1, "swap_bytes": 100, "resident_bytes": 1000}])
    assert result["protocol_passed"] is True
    assert result["semantic_review_passed"] is (choice == "match")
    assert values == before


@pytest.mark.parametrize("corruption", ["missing", "incomplete", "conflict", "unavailable", "skipped"])
def test_cache_protocol_still_rejects_missing_or_invalid_d1_review(corruption):
    values = rows()
    review = values[-1]
    if corruption == "missing":
        review.pop("result")
    elif corruption == "incomplete":
        review["result"]["checks"].pop()
    elif corruption == "conflict":
        review["result"]["status"] = "ISSUE"
    else:
        review["status"] = review["result"]["status"] = corruption.upper()
    result = assessment(values, [{"pressure": 1, "swap_bytes": 100, "resident_bytes": 1000}])
    assert result["protocol_passed"] is False


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
