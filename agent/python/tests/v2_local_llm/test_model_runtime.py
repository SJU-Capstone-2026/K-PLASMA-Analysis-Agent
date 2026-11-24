import subprocess
import sys

import pytest

from kplasma_agent.v2_local_llm import runtime


def test_status_and_other_processes_cannot_interrupt_an_owned_model_call(tmp_path, monkeypatch):
    lease = getattr(runtime, "model_lease", None)
    assert callable(lease), "cross-process model ownership is missing"
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))
    code = """
from kplasma_agent.v2_local_llm.runtime import model_lease, ModelRuntimeBusy
try:
    with model_lease():
        print('acquired')
except ModelRuntimeBusy:
    print('busy')
"""
    with lease():
        result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, check=True)
        assert result.stdout.strip() == "busy"
    result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "acquired"


def test_failed_model_call_releases_ownership_for_the_next_request(tmp_path, monkeypatch):
    lease = getattr(runtime, "model_lease", None)
    assert callable(lease), "cross-process model ownership is missing"
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(ValueError, match="model failed"):
        with lease():
            raise ValueError("model failed")
    with lease():
        pass
