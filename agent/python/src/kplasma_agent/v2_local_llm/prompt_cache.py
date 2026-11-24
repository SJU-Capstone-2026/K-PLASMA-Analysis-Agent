"""Private, optional Qwen planner slot snapshots; never reuse model decisions."""

import hashlib
from contextlib import contextmanager, suppress
import json
import os
from pathlib import Path
import re
import shutil
import stat
from time import monotonic
from typing import Any
import uuid

import httpx

from .model_client import ModelError

MAX_FILE_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 4 * 1024**3
CACHE_TIMEOUT = 5
FILENAME = re.compile(r"kv-[a-f0-9]{32}\.bin")
MARKER = ".qwen-plan-cache"
MARKER_CONTENT = "K-PLASMA Qwen plan KV cache v1\n"


class QwenPlanCache:
    def __init__(self, settings, client):
        self.client = client
        self.enabled = settings.qwen_plan_cache_enabled
        self.root = Path(settings.qwen_plan_cache_dir)
        self.base_url = httpx.URL(settings.model_url)
        self.fingerprint = settings.versions()["configFingerprint"]
        self.candidate = None
        self.resident = None
        self.stats: dict[str, Any] = {key: 0.0 for key in ("prepare_ms", "restore_ms", "save_ms", "hash_ms")}
        if self.enabled:
            with suppress(OSError):
                self._directory()

    def _directory(self):
        if self.root in {Path(self.root.anchor), Path.home(), Path(__file__).resolve().parents[5]}:
            raise ValueError("LOCAL_CACHE_DIRECTORY_UNSAFE")
        for path in (self.root, *self.root.parents):
            if path.is_symlink():
                raise ValueError("LOCAL_CACHE_DIRECTORY_UNSAFE")
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("LOCAL_CACHE_DIRECTORY_UNSAFE")
        marker = self.root / MARKER
        entries = list(self.root.iterdir())
        if marker.exists():
            info = marker.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                    or info.st_size != len(MARKER_CONTENT) or marker.read_text() != MARKER_CONTENT):
                raise ValueError("LOCAL_CACHE_DIRECTORY_UNSAFE")
            for entry in entries:
                info = entry.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or not (entry.name in {MARKER, "cache.json"} or FILENAME.fullmatch(entry.name)
                                or re.fullmatch(r"meta-[a-f0-9]{32}\.json", entry.name))):
                    raise ValueError("LOCAL_CACHE_DIRECTORY_UNSAFE")
        elif entries:
            raise ValueError("LOCAL_CACHE_DIRECTORY_UNSAFE")
        self.root.chmod(0o700)
        if not marker.exists():
            with open(marker, "x", opener=lambda p, flags: os.open(p, flags | os.O_NOFOLLOW, 0o600)) as stream:
                stream.write(MARKER_CONTENT)

    def _url(self, path, action=None):
        return self.base_url.copy_with(path=path, query=("action=" + action).encode() if action else None)

    @contextmanager
    def _measure(self, key):
        started = monotonic()
        try:
            yield
        finally:
            self.stats[key] += (monotonic() - started) * 1000

    def _hash(self, path):
        with self._measure("hash_ms"), path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def _read_metadata(self):
        path = self.root / "cache.json"
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 65536:
            raise ValueError("LOCAL_CACHE_INVALID")
        data = json.loads(path.read_text())
        if (not isinstance(data, dict) or set(data) != {"format", "fingerprint", "filename", "size", "sha256", "tokens"}
                or data["format"] != 1 or data["fingerprint"] != self.fingerprint
                or not isinstance(data["filename"], str) or not FILENAME.fullmatch(data["filename"])
                or type(data["size"]) is not int or not 0 < data["size"] <= MAX_FILE_BYTES
                or type(data["tokens"]) is not int or data["tokens"] <= 0
                or not isinstance(data["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", data["sha256"])):
            raise ValueError("LOCAL_CACHE_INVALID")
        return data

    def _file(self, metadata):
        path = self.root / metadata["filename"]
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or info.st_size != metadata["size"]):
            raise ValueError("LOCAL_CACHE_INVALID")
        return path, (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def prepare(self):
        """Validate disk state before token counting, keeping I/O out of the idle window."""
        self.candidate = None
        self.stats = {key: 0.0 for key in ("prepare_ms", "restore_ms", "save_ms", "hash_ms")}
        self.stats.update(restore="off" if not self.enabled else "miss", save="off" if not self.enabled else "miss")
        if not self.enabled:
            return
        with self._measure("prepare_ms"):
            try:
                self._directory()
                metadata = self._read_metadata()
                path, identity = self._file(metadata)
                if self._hash(path) != metadata["sha256"]:
                    return
                self.candidate = (metadata, identity)
            except (OSError, ValueError, TypeError, KeyError):
                return

    def _slot(self):
        response = self.client.get(self._url("/slots"), timeout=CACHE_TIMEOUT)
        response.raise_for_status()
        slots = response.json()
        if (not isinstance(slots, list) or len(slots) != 1 or not isinstance(slots[0], dict)
                or type(slots[0].get("id")) is not int or slots[0]["id"] != 0 or slots[0].get("is_processing")):
            raise ValueError("LOCAL_CACHE_INVALID")
        slot = slots[0]
        prompt = slot.get("prompt")
        if not isinstance(prompt, str) or not slot.get("n_prompt_tokens"):
            return None
        # Native state, rather than elapsed client time, detects sleep and writer overwrites.
        return (slot.get("id_task"), slot["n_prompt_tokens"], hashlib.sha256(prompt.encode()).hexdigest())

    def restore(self):
        if not self.enabled:
            return "off"
        with self._measure("restore_ms"):
            return self._restore()

    def _restore(self):
        try:
            current = self._slot()
            if current is not None and current == self.resident:
                self.stats["restore"] = "ram"
                return "ram"
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return "miss"
        if self.candidate is None:
            return "miss"
        metadata, identity = self.candidate
        try:
            if self._file(metadata)[1] != identity:
                return "miss"
            response = self.client.post(self._url("/slots/0", "restore"),
                                        json={"filename": metadata["filename"]}, timeout=CACHE_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            if (not isinstance(data, dict) or type(data.get("n_restored")) is not int
                    or type(data.get("n_read")) is not int
                    or data["n_restored"] != metadata["tokens"] or data["n_read"] != metadata["size"]):
                raise ValueError("LOCAL_CACHE_INVALID")
            self.stats["restore"] = "disk"
            return "disk"
        except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError):
            self.resident = None
            try:
                cleared = self.client.post(self._url("/slots/0", "erase"), timeout=CACHE_TIMEOUT)
                cleared.raise_for_status()
                data = cleared.json()
                if not isinstance(data, dict) or type(data.get("id_slot")) is not int or data["id_slot"] != 0:
                    raise ValueError("LOCAL_CACHE_INVALID")
            except (httpx.HTTPError, ValueError, TypeError):
                raise ModelError("LOCAL_CACHE_STATE_UNCERTAIN") from None
            return "miss"

    def save(self):
        if not self.enabled:
            return "off"
        with self._measure("save_ms"):
            return self._save()

    def _prune(self, active):
        for path in self.root.iterdir():
            if (path.name != active and stat.S_ISREG(path.lstat().st_mode)
                    and (FILENAME.fullmatch(path.name) or re.fullmatch(r"meta-[a-f0-9]{32}\.json", path.name))):
                path.unlink()

    def _save(self):
        self.stats["save"] = "miss"
        filename = "kv-" + uuid.uuid4().hex + ".bin"
        path = self.root / filename
        temporary = self.root / ("meta-" + uuid.uuid4().hex + ".json")
        try:
            self._directory()
            # Fence late native writes before reclaiming unpublished snapshots.
            self._slot()
            active = None
            with suppress(OSError, ValueError, TypeError, KeyError):
                data = json.loads((self.root / "cache.json").read_text())
                if isinstance(data, dict) and isinstance(data.get("filename"), str) and FILENAME.fullmatch(data["filename"]):
                    active = data["filename"]
            self._prune(active)
            occupied = sum(p.lstat().st_size for p in self.root.iterdir() if stat.S_ISREG(p.lstat().st_mode))
            if occupied + MAX_FILE_BYTES > MAX_TOTAL_BYTES or shutil.disk_usage(self.root).free < MAX_FILE_BYTES:
                return "miss"
            # Keep this private placeholder after timeout: a queued native write may still open it.
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
            response = self.client.post(self._url("/slots/0", "save"), json={"filename": filename}, timeout=CACHE_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            info = path.lstat()
            if (not isinstance(data, dict) or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or not 0 < info.st_size <= MAX_FILE_BYTES or data.get("n_written") != info.st_size
                    or type(data.get("n_saved")) is not int or data["n_saved"] <= 0):
                raise ValueError("LOCAL_CACHE_INVALID")
            path.chmod(0o600)
            self.resident = self._slot()
            metadata = {"format": 1, "fingerprint": self.fingerprint, "filename": filename,
                        "size": info.st_size, "sha256": self._hash(path), "tokens": data["n_saved"]}
            with open(temporary, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
                json.dump(metadata, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.root / "cache.json")
            self.stats.update(save="saved", bytes=info.st_size)
            with suppress(OSError):
                self._prune(filename)
            return "saved"
        except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError, ModelError):
            return "miss"
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def writer_used(self):
        self.resident = None
