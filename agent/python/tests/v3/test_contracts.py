import pytest
from pydantic import ValidationError

from kplasma_agent.v3.core import contracts


def test_rejects_v1_snapshot_as_graph_v2():
    with pytest.raises(ValidationError):
        contracts.GraphV3AnswerSnapshotV1.model_validate(
            {"implementationId": "v1", "graphVersion": "v1", "schemaVersion": 3}
        )


def test_plan_rejects_unregistered_step_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        contracts.PlanDraft.model_validate({
            "schema_version": 2, "request_mode": "data_request", "base_revision": None,
            "requirements": [],
            "steps": [{"id": "s", "kind": "derive", "operation": "max", "inputs": {},
                       "json_path": "$.anything"}],
        })


def test_result_reference_requires_explicit_scope():
    with pytest.raises(ValidationError, match="scope"):
        contracts.ResultRef.model_validate({"kind": "result_ref", "step_id": "s", "field": "ionFlux"})
