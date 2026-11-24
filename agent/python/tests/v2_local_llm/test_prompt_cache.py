"""Qwen disk cache safety with real files and a fake native HTTP boundary."""

from dataclasses import replace
import importlib
import json
from pathlib import Path

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.network import local_http_client


def cache_class():
    assert importlib.util.find_spec("kplasma_agent.v2_local_llm.prompt_cache") is not None, (
        "QwenPlanCache is not implemented"
    )
    return importlib.import_module("kplasma_agent.v2_local_llm.prompt_cache").QwenPlanCache


class NativeCache:
    def __init__(self, folder):
        self.folder = folder
        self.calls = []
        self.slot = {"id": 0, "n_prompt_tokens": 42, "id_task": 7, "prompt": "synthetic prefix"}
        self.fail = None

    def handle(self, request):
        self.calls.append((request.method, request.url.path, request.url.query))
        if request.url.path == "/slots":
            return httpx.Response(200, json=[self.slot])
        assert request.url.path == "/slots/0"
        action = request.url.params["action"]
        if self.fail == action:
            return httpx.Response(500, json={"error": {"message": "private server details"}})
        if action == "erase":
            self.slot = {"id": 0}
            return httpx.Response(200, json={"id_slot": 0, "n_erased": 42})
        filename = json.loads(request.content)["filename"]
        assert "/" not in filename and ".." not in filename
        if action == "save":
            data = b"synthetic KV checkpoint"
            (self.folder / filename).write_bytes(data)
            return httpx.Response(200, json={"id_slot": 0, "n_saved": 42, "n_written": len(data)})
        assert action == "restore"
        data = (self.folder / filename).read_bytes()
        self.slot = {"id": 0, "n_prompt_tokens": 42, "id_task": 7, "prompt": "synthetic prefix"}
        return httpx.Response(200, json={"id_slot": 0, "n_restored": 42, "n_read": len(data)})


def create(tmp_path, **changes):
    root = tmp_path / "cache"
    settings = replace(Settings(qwen_plan_cache_enabled=True, qwen_plan_cache_dir=str(root)), **changes)
    native = NativeCache(root)
    client = local_http_client(settings.model_url, timeout=5, transport=httpx.MockTransport(native.handle))
    return cache_class()(settings, client), native, settings


def test_cache_persists_then_restores_after_native_slot_is_lost(tmp_path):
    cache, native, settings = create(tmp_path)
    cache.prepare()
    assert cache.restore() == "miss"
    assert cache.save() == "saved"
    assert all(p.stat().st_mode & 0o077 == 0 for p in Path(settings.qwen_plan_cache_dir).iterdir())
    native.slot = {"id": 0}
    cache.prepare()
    assert cache.restore() == "disk"
    assert any(call[2] == b"action=restore" for call in native.calls)


def test_live_plan_cache_is_not_overwritten_by_disk_restore(tmp_path):
    cache, native, _ = create(tmp_path)
    cache.prepare()
    cache.save()
    cache.prepare()
    assert cache.restore() == "ram"
    assert not any(call[2] == b"action=restore" for call in native.calls)


@pytest.mark.parametrize("change", ["corrupt", "fingerprint", "missing"])
def test_unusable_cache_is_a_miss_without_a_native_restore(tmp_path, change):
    cache, native, settings = create(tmp_path)
    cache.prepare()
    cache.save()
    meta = Path(settings.qwen_plan_cache_dir) / "cache.json"
    value = json.loads(meta.read_text())
    if change == "corrupt":
        (meta.parent / value["filename"]).write_bytes(b"bad")
    elif change == "missing":
        (meta.parent / value["filename"]).unlink()
    else:
        value["fingerprint"] = "other"
        meta.write_text(json.dumps(value))
    native.slot = {"id": 0}
    other = cache_class()(settings, cache.client)
    other.prepare()
    assert other.restore() == "miss"
    assert not any(call[2] == b"action=restore" for call in native.calls)


def test_failed_save_keeps_the_previous_published_cache(tmp_path):
    cache, native, settings = create(tmp_path)
    cache.prepare()
    cache.save()
    meta = Path(settings.qwen_plan_cache_dir) / "cache.json"
    before = meta.read_bytes()
    native.fail = "save"
    assert cache.save() == "miss"
    assert meta.read_bytes() == before


def test_restore_failure_clears_the_slot_before_falling_back(tmp_path):
    cache, native, _ = create(tmp_path)
    cache.prepare()
    cache.save()
    native.slot = {"id": 0}
    cache.prepare()
    native.fail = "restore"
    assert cache.restore() == "miss"
    assert native.calls[-1][2] == b"action=erase"


def test_disabled_cache_never_creates_files_or_sends_requests(tmp_path):
    cache, native, settings = create(tmp_path, qwen_plan_cache_enabled=False)
    cache.prepare()
    assert cache.restore() == "off" and cache.save() == "off"
    assert not native.calls and not Path(settings.qwen_plan_cache_dir).exists()


def test_cache_directory_symlink_is_rejected(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / "cache").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="LOCAL_CACHE_DIRECTORY_UNSAFE"):
        create(tmp_path)
    assert not list(target.iterdir())


def test_replacing_a_snapshot_keeps_only_the_latest_owned_payload(tmp_path):
    cache, native, settings = create(tmp_path)
    cache.prepare()
    cache.save()
    cache.save()
    folder = Path(settings.qwen_plan_cache_dir)
    value = json.loads((folder / "cache.json").read_text())
    assert [p.name for p in folder.glob("kv-*.bin")] == [value["filename"]]


def test_cleanup_permission_error_does_not_override_a_cache_miss(tmp_path, monkeypatch):
    cache, native, _ = create(tmp_path)
    native.fail = "save"
    original = Path.unlink

    def denied(path, *args, **kwargs):
        if path.parent == cache.root:
            raise PermissionError("synthetic write-protected cache")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    assert cache.save() == "miss"


@pytest.mark.parametrize("filename", ["../outside.bin", "/absolute.bin", "kv-not-a-uuid.bin"])
def test_untrusted_metadata_cannot_select_another_file(tmp_path, filename):
    cache, native, settings = create(tmp_path)
    cache.prepare()
    cache.save()
    meta = Path(settings.qwen_plan_cache_dir) / "cache.json"
    value = json.loads(meta.read_text())
    value["filename"] = filename
    meta.write_text(json.dumps(value))
    native.slot = {"id": 0}
    cache.prepare()
    assert cache.restore() == "miss"
    assert not any(x[2] == b"action=restore" for x in native.calls)


def test_oversized_snapshot_is_not_published(tmp_path, monkeypatch):
    module = importlib.import_module("kplasma_agent.v2_local_llm.prompt_cache")
    cache, native, settings = create(tmp_path)
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 10)
    assert cache.save() == "miss"
    assert not (Path(settings.qwen_plan_cache_dir) / "cache.json").exists()


def test_file_replaced_after_prepare_is_not_restored(tmp_path):
    cache, native, settings = create(tmp_path)
    cache.prepare()
    cache.save()
    native.slot = {"id": 0}
    cache.prepare()
    meta = json.loads((Path(settings.qwen_plan_cache_dir) / "cache.json").read_text())
    (cache.root / meta["filename"]).write_bytes(b"synthetic modified checkpoint")
    assert cache.restore() == "miss"
    assert not any(x[2] == b"action=restore" for x in native.calls)


def test_temporary_storage_unavailability_falls_back_without_restore(tmp_path, monkeypatch):
    cache, native, _ = create(tmp_path)

    def unavailable():
        raise OSError("synthetic volume unavailable")

    monkeypatch.setattr(cache, "_directory", unavailable)
    cache.prepare()
    assert cache.restore() == "miss" and cache.save() == "miss"


def test_foreign_directory_is_rejected_without_chmod_or_replacement(tmp_path):
    folder = tmp_path / "cache"
    folder.mkdir(mode=0o755)
    existing = folder / "cache.json"
    existing.write_text("unrelated user data")
    before_mode = folder.stat().st_mode
    with pytest.raises(ValueError, match="LOCAL_CACHE_DIRECTORY_UNSAFE"):
        create(tmp_path)
    assert folder.stat().st_mode == before_mode
    assert existing.read_text() == "unrelated user data"


def test_owned_orphans_are_pruned_before_the_quota_check(tmp_path, monkeypatch):
    module = importlib.import_module("kplasma_agent.v2_local_llm.prompt_cache")
    cache, native, _ = create(tmp_path)
    cache.prepare()
    assert cache.save() == "saved"
    orphan = cache.root / ("kv-" + "a" * 32 + ".bin")
    orphan.write_bytes(b"x" * 8192)
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 512)
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 4096)
    cache.prepare()
    assert cache.save() == "saved"
    assert not orphan.exists()


def test_payload_is_private_before_native_write_and_timeout_keeps_the_private_placeholder(tmp_path):
    cache, native, _ = create(tmp_path)
    captured = []
    original = native.handle

    def handler(request):
        if request.url.params.get("action") == "save":
            filename = json.loads(request.content)["filename"]
            file = cache.root / filename
            captured.append(file)
            assert file.exists() and file.stat().st_mode & 0o777 == 0o600
            raise httpx.ReadTimeout("synthetic late write", request=request)
        return original(request)

    cache.client.close()
    cache.client = local_http_client(
        "http://127.0.0.1:8082/v1", timeout=5, transport=httpx.MockTransport(handler)
    )
    assert cache.save() == "miss"
    assert captured[0].exists()
    captured[0].write_bytes(b"late native write")
    assert captured[0].stat().st_mode & 0o777 == 0o600
    assert not (cache.root / "cache.json").exists()


@pytest.mark.parametrize("action", ["save", "restore", "erase", "slots"])
def test_malformed_native_json_is_safe_and_restore_is_cleared(tmp_path, action):
    from kplasma_agent.v2_local_llm.model_client import ModelError

    cache, native, _ = create(tmp_path)
    cache.prepare()
    assert cache.save() == "saved"
    native.slot = {"id": 0}
    cache.prepare()
    original = native.handle

    def handler(request):
        current = request.url.params.get("action")
        if action == "slots" and request.url.path == "/slots":
            return httpx.Response(200, json=[None])
        if current == action:
            return httpx.Response(200, json=[])
        if action == "erase" and current == "restore":
            return httpx.Response(500, json={"error": {}})
        return original(request)

    cache.client.close()
    cache.client = local_http_client(
        "http://127.0.0.1:8082/v1", timeout=5, transport=httpx.MockTransport(handler)
    )
    if action == "erase":
        with pytest.raises(ModelError, match="LOCAL_CACHE_STATE_UNCERTAIN"):
            cache.restore()
    elif action == "save":
        assert cache.save() == "miss"
    else:
        assert cache.restore() == "miss"
        if action == "restore":
            assert native.calls[-1][2] == b"action=erase"


def test_cache_overheads_are_measured_separately_from_generation(tmp_path):
    import math

    cache, native, _ = create(tmp_path)
    cache.prepare()
    cache.restore()
    cache.save()
    for key in ("prepare_ms", "restore_ms", "save_ms", "hash_ms"):
        assert type(cache.stats[key]) is float and math.isfinite(cache.stats[key]) and cache.stats[key] >= 0
