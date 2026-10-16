import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run import summarize, verify
from seed import make_run, dataset_indices, query_for
from kplasma_agent.domain import lookup_forward
import pytest


def test_failures_are_counted_and_percentile_is_nearest_rank():
    records = [{"ok": True, "totalMs": i} for i in range(1, 21)]
    records += [{"ok": False, "error": "timeout"}]
    result = summarize(records)
    assert (
        result["samples"] == 21
        and result["successes"] == 20
        and result["failures"] == 1
    )
    assert result["meanMs"] == 10.5 and result["p95Ms"] == 19
    assert summarize([{"ok": False}])["meanMs"] is None


def test_aggregate_preserves_missing_scales_as_missing(tmp_path):
    from report import build

    result, markdown = build(tmp_path)
    assert result["1000000"]["m2"]["a"]["meanMs"] is None
    assert result["1000000"]["m2"]["a"]["samples"] == 0
    assert "미완료" in markdown


def test_independent_oracle_catches_wrong_source_even_if_replay_passes():
    row = make_run(dataset_indices(150)[0])
    query = query_for(row)
    actual_source = {**row, "metrics": {**row["metrics"], "ionFlux": 999}}
    result = lookup_forward(query, [actual_source])
    with pytest.raises(AssertionError):
        verify(query, result, [actual_source], row)


def test_supplement_requires_same_data_and_cannot_replace_existing_samples(tmp_path):
    import json
    from report import supplement_samples

    original, extra = tmp_path / "original", tmp_path / "extra"
    original.mkdir()
    extra.mkdir()
    dataset = {
        "size": 150,
        "inputHash": "same",
        "corpus": [{"expected": "independent"}],
    }
    runtime = {
        "baseCommit": "same",
        "python": "same",
        "platform": "same",
        "requestDeadlineSeconds": 60,
        "java": {
            "java": "21",
            "maxHeapBytes": 4_294_967_296,
            "database": "forward_lookup_bench",
        },
    }
    for directory in (original, extra):
        (directory / "dataset.json").write_text(json.dumps(dataset))
        (directory / "runtime.json").write_text(json.dumps(runtime))
    sample = json.dumps({"method": "b", "ok": True, "totalMs": 2}) + "\n"
    (extra / "m2.jsonl").write_text(sample)
    rows, methods = supplement_samples(original, extra)
    assert len(rows) == 1 and methods == ["b"]
    (original / "m2.jsonl").write_text(sample)
    with pytest.raises(ValueError, match="replace or mix"):
        supplement_samples(original, extra)
    (extra / "dataset.json").write_text(
        json.dumps({**dataset, "inputHash": "different"})
    )
    with pytest.raises(ValueError, match="dataset differs"):
        supplement_samples(original, extra)
