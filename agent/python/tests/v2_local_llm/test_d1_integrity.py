import json

import pytest


def integrity():
    from kplasma_agent.v2_local_llm import runtime_integrity as module
    return module


def test_library_bytes_are_checked_even_when_metadata_is_unchanged(tmp_path):
    m = integrity()
    site = tmp_path / "site"
    site.mkdir()
    (site / "engine.py").write_text("original")
    lock = tmp_path / "uv.lock"
    lock.write_text("pinned")
    pin = {"lockSha256": m.file_hash(lock), "files": {"engine.py": m.file_hash(site / "engine.py")}}
    before = m.verify_libraries(site, lock, pin)
    (site / "engine.py").write_text("modified")
    with pytest.raises(ValueError, match="LOCAL_D1_MLX_RUNTIME_MISMATCH"):
        m.verify_libraries(site, lock, pin)
    assert before


@pytest.mark.parametrize("extra", ["model_backup.safetensors", "model.safetensors.index.json"])
def test_unlisted_loader_consumed_model_files_are_rejected(tmp_path, extra):
    m = integrity()
    (tmp_path / "model.safetensors").write_text("pinned")
    files = {"model.safetensors": m.file_hash(tmp_path / "model.safetensors")}
    m.verify_weights(tmp_path, files)
    (tmp_path / extra).write_text(json.dumps({}))
    with pytest.raises(ValueError, match="LOCAL_MODEL_ARTIFACT_MISMATCH"):
        m.verify_weights(tmp_path, files)
