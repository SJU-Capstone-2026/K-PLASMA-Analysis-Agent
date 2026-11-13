from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from evals import local_llm_measure as measurement
from kplasma_agent.v2_local_llm.config import Settings


def test_measurement_verifies_artifacts_before_contacting_the_stack(monkeypatch):
    def reject(_):
        raise ValueError("synthetic artifact mismatch")
    monkeypatch.setattr(measurement,"verify_artifacts",reject,raising=False)
    monkeypatch.setattr(measurement,"local_http_client",lambda *_a,**_k:pytest.fail("HTTP before artifact verification"))
    with pytest.raises(ValueError,match="synthetic artifact mismatch"):
        measurement.measure(Settings(),{"data":"artificial-only","graphVersion":"v2_localLLM", "url":"http://127.0.0.1:9998","web":"http://127.0.0.1:9999"})


def test_critical_pressure_stops_before_model_construction(monkeypatch):
    @contextmanager
    def health(*_a,**_k):
        yield SimpleNamespace(get=lambda _:SimpleNamespace(raise_for_status=lambda:None))
    monkeypatch.setattr(measurement,"local_http_client",health)
    monkeypatch.setattr(measurement,"verify_artifacts",lambda _:"fixed",raising=False)
    monkeypatch.setattr(measurement,"live_facts",lambda _:"fixed",raising=False)
    monkeypatch.setattr(measurement,"memory_sample",lambda:{"pressure":4,"swap_bytes":0,"resident_bytes":1})
    monkeypatch.setattr(measurement,"ModelClient",lambda *_:pytest.fail("model constructed during critical pressure"))
    with pytest.raises(ValueError,match="LOCAL_MEMORY_PRESSURE"):
        measurement.measure(Settings(),{"data":"artificial-only","graphVersion":"v2_localLLM", "url":"http://127.0.0.1:9998","web":"http://127.0.0.1:9999"})
