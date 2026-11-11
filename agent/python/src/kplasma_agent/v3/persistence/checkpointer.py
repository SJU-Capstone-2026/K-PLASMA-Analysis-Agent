"""LangGraph saver whose synchronous writes are fenced by Spring/PostgreSQL.

The memory implementation supplies LangGraph's versioned channel semantics. Every
write is serialized as inert JSON/base64 and committed to the backend before the
saver returns. Memory alone is never the production durability boundary.
"""

from base64 import b64encode, b64decode
from threading import RLock
from langgraph.checkpoint.memory import InMemorySaver


def pack(value):
    if isinstance(value, bytes):
        return {"bytes": b64encode(value).decode("ascii")}
    if isinstance(value, tuple):
        return {"tuple": [pack(x) for x in value]}
    if isinstance(value, dict):
        return {"map": [[pack(k), pack(v)] for k, v in value.items()]}
    if isinstance(value, list):
        return [pack(x) for x in value]
    return value


def unpack(value):
    if isinstance(value, list):
        return [unpack(x) for x in value]
    if isinstance(value, dict):
        if set(value) == {"bytes"}:
            return b64decode(value["bytes"], validate=True)
        if set(value) == {"tuple"}:
            return tuple(unpack(x) for x in value["tuple"])
        if set(value) == {"map"}:
            return {unpack(k): unpack(v) for k, v in value["map"]}
        raise ValueError("Invalid checkpoint encoding")
    return value


class DurableSaver(InMemorySaver):
    def __init__(self, payload, persist):
        super().__init__()
        self._persist = persist
        self._lock = RLock()
        if payload:
            if payload.get("format") != "langgraph-memory-v1":
                raise ValueError("RECOVERY_VERSION_MISMATCH")
            for thread_id, namespaces in unpack(payload["storage"]).items():
                for namespace, checkpoints in namespaces.items():
                    self.storage[thread_id][namespace].update(checkpoints)
            self.writes.update(unpack(payload["writes"]))
            self.blobs.update(unpack(payload["blobs"]))

    def _save(self):
        self._persist(
            {
                "format": "langgraph-memory-v1",
                "storage": pack(self.storage),
                "writes": pack(self.writes),
                "blobs": pack(self.blobs),
            }
        )

    def put(self, config, checkpoint, metadata, new_versions):
        with self._lock:
            output = super().put(config, checkpoint, metadata, new_versions)
            self._save()
            return output

    def put_writes(self, config, writes, task_id, task_path=""):
        with self._lock:
            super().put_writes(config, writes, task_id, task_path)
            self._save()
