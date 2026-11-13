import pytest

from kplasma_agent.v2_local_llm.persistence.checkpointer import DurableSaver, pack


@pytest.mark.parametrize("format", ["langgraph-memory-v1", "langgraph-memory-v3-v1"])
def test_saver_rejects_other_graph_formats_even_with_a_copied_request_id(format):
    payload = {"format": format, "storage": pack({}), "writes": pack({}), "blobs": pack({})}
    with pytest.raises(ValueError, match="RECOVERY_VERSION_MISMATCH"):
        DurableSaver(payload, lambda value: None)


def test_saver_round_trips_only_the_owned_format():
    saved = []
    saver = DurableSaver(None, saved.append)
    saver._save()
    assert saved[0]["format"] == "langgraph-memory-v2-local-llm-v1"
    restored = DurableSaver(saved[0], saved.append)
    assert not restored.storage and not restored.writes
