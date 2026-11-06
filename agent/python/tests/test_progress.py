import pytest

from kplasma_agent.backend_client import BackendError
from kplasma_agent.progress import ProgressReporter


class Backend:
    def __init__(self):
        self.events = []
        self.revision = 0

    def public_event(self, kind, payload, key):
        if kind == "answer.start":
            self.revision += 1
            payload = {**payload, "answerRevision": self.revision}
        self.events.append((kind, payload, key))
        return {"seq": len(self.events), "payload": payload}


def test_stream_chunks_have_one_global_order_and_rewrite_starts_a_new_version():
    backend = Backend()
    reporter = ProgressReporter(backend)
    first = reporter.start_answer("interpretation")
    first.append("interpretations.0.text", "앞부분")
    first.flush()
    first.append("interpretations.0.assumptions.0", "전제")
    first.flush()
    first.invalidate("rewrite")
    second = reporter.start_answer("interpretation", rewrite=True)
    second.append("interpretations.0.text", "수정문")
    second.flush()
    deltas = [payload for kind, payload, _ in backend.events if kind == "answer.delta"]
    assert [row["chunkIndex"] for row in deltas] == [0, 1, 0]
    assert [row["answerRevision"] for row in deltas] == [1, 1, 2]
    assert deltas[0]["streamId"] != deltas[2]["streamId"]
    assert backend.events[3][0] == "answer.reset"


def test_activity_has_one_identity_across_start_and_completion_and_no_heartbeat_copy():
    backend = Backend()
    reporter = ProgressReporter(backend)
    with reporter.work("COMPARE_RUNS", identity="execution-1", runCount=2):
        pass
    assert [payload["phase"] for _, payload, _ in backend.events] == ["started", "completed"]
    assert {payload["activityId"] for _, payload, _ in backend.events} == {"execution-1"}
    assert len({key for _, _, key in backend.events}) == 2


def test_unavailable_progress_does_not_repeat_a_model_or_prevent_final_result():
    class Offline(Backend):
        def public_event(self, *_):
            raise BackendError("BACKEND_UNAVAILABLE", True)

    reporter = ProgressReporter(Offline())
    stream = reporter.start_answer("general")
    stream.append("paragraphs.0", "답변")
    stream.flush()
    assert not reporter.enabled


def test_stale_worker_cannot_hide_fence_failure_as_a_preview_outage():
    class Stale(Backend):
        def public_event(self, *_):
            raise BackendError("STALE_CLAIM")

    with pytest.raises(BackendError, match="STALE_CLAIM"):
        ProgressReporter(Stale()).start_answer("general")
