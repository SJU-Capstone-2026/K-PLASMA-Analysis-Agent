"""Public execution facts and provisional prose; never a source of execution state."""

from contextlib import contextmanager
import logging
import time
from uuid import uuid4

from .backend_client import BackendError

LOG = logging.getLogger("kplasma.progress")
STALE = {"STALE_CLAIM", "STALE_REQUEST", "STALE_CONTEXT", "CONTEXT_CLEARED"}


class ProgressReporter:
    def __init__(self, backend):
        self.backend = backend
        self.enabled = callable(getattr(backend, "public_event", None))
        self.current = None
        self.result_ids = None

    def event(self, kind, payload, key=None):
        if not self.enabled:
            return None
        try:
            return self.backend.public_event(kind, payload, key or str(uuid4()))
        except BackendError as error:
            if error.code in STALE:
                raise
            # Preview delivery must never repeat the provider/tool invocation.
            self.enabled = False
            LOG.warning("PUBLIC_PROGRESS_UNAVAILABLE: final results remain available through request status")
            return None

    def activity(self, code, phase="started", *, identity=None, **fields):
        identity = identity or str(uuid4())
        self.event("activity", {"activityId": identity, "code": code, "phase": phase, **fields},
                   f"activity:{identity}:{phase}")
        return identity

    @contextmanager
    def work(self, code, *, identity=None, **fields):
        identity = self.activity(code, identity=identity, **fields)
        yield
        self.activity(code, "completed", identity=identity, **fields)

    def results(self, execution_ids):
        ids = list(dict.fromkeys(execution_ids))
        if ids != self.result_ids:
            self.event("results.ready", {"executionIds": ids})
            self.result_ids = ids

    def start_answer(self, mode, *, rewrite=False):
        if self.current is not None:
            self.current.invalidate("rewrite" if rewrite else "replaced")
        stream_id = str(uuid4())
        event = self.event("answer.start", {"streamId": stream_id, "mode": mode, "rewrite": rewrite},
                           f"answer:{stream_id}:start")
        revision = (event or {}).get("payload", {}).get("answerRevision", 0)
        self.current = AnswerStream(self, stream_id, revision)
        return self.current

    def discard_answer(self, reason):
        if self.current is not None:
            self.current.invalidate(reason)


class AnswerStream:
    def __init__(self, reporter, stream_id, revision):
        self.reporter = reporter
        self.stream_id = stream_id
        self.revision = revision
        self.chunks = 0
        self.pending = {}
        self.last_flush = 0.0
        self.closed = False

    def append(self, block_id, text):
        if self.closed or not text or not self.reporter.enabled:
            return
        self.pending[block_id] = self.pending.get(block_id, "") + text
        if time.monotonic() - self.last_flush >= 0.075 or sum(map(len, self.pending.values())) >= 2000:
            self.flush()

    def flush(self):
        if self.closed:
            return
        for block_id, text in self.pending.items():
            # Bound each event independently of how the provider groups its output.
            for start in range(0, len(text), 4000):
                self.reporter.event("answer.delta", {
                    "streamId": self.stream_id, "answerRevision": self.revision,
                    "blockId": block_id, "text": text[start:start + 4000], "chunkIndex": self.chunks,
                }, f"answer:{self.stream_id}:{self.chunks}")
                self.chunks += 1
        self.pending.clear()
        self.last_flush = time.monotonic()

    def invalidate(self, reason):
        if not self.closed:
            self.pending.clear()
            self.reporter.event("answer.reset", {
                "streamId": self.stream_id, "answerRevision": self.revision, "reason": reason.upper(),
            }, f"answer:{self.stream_id}:reset")
            self.closed = True
