"""CPU-only provenance checks shared by the isolated service and its controller."""

from functools import lru_cache
import hashlib
import json
from pathlib import Path


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


@lru_cache(maxsize=4)
def _verify(site, lock, encoded, stats):
    pin = json.loads(encoded)
    if file_hash(lock) != pin["lockSha256"]:
        raise ValueError("LOCAL_D1_MLX_RUNTIME_MISMATCH")
    for name, digest in pin["files"].items():
        path = Path(site) / name
        if not path.resolve().is_relative_to(Path(site).resolve()) or file_hash(path) != digest:
            raise ValueError("LOCAL_D1_MLX_RUNTIME_MISMATCH")
    return hashlib.sha256(encoded.encode()).hexdigest()


def verify_libraries(site, lock, pin):
    try:
        paths = [Path(lock), *(Path(site) / name for name in sorted(pin["files"]))]
        stats = tuple((s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino) for p in paths for s in [p.stat()])
        return _verify(str(site), str(lock), json.dumps(pin, sort_keys=True), stats)
    except (OSError, KeyError, TypeError):
        raise ValueError("LOCAL_D1_MLX_RUNTIME_MISMATCH") from None


def verify_weights(folder, files):
    folder = Path(folder).resolve()
    consumed = {p.name for p in folder.glob("model*.safetensors")}
    if (folder / "model.safetensors.index.json").exists():
        consumed.add("model.safetensors.index.json")
    if not consumed or not consumed <= set(files):
        raise ValueError("LOCAL_MODEL_ARTIFACT_MISMATCH")
