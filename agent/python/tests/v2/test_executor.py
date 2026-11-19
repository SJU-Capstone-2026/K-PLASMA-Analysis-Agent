import pytest

from kplasma_agent.v2.contracts import DeriveStep, ReverseStep, StepResult
from kplasma_agent.v2.executor import SequentialExecutor


class Port:
    def __init__(self):
        self.calls = []

    def start_step(self, revision, step_id, inputs):
        self.calls.append((revision, step_id, inputs))
        return {"executionId": "execution-" + step_id, "callAllowed": True}

    def save_result(self, result):
        return {"result": result.model_dump(mode="json")}


@pytest.mark.parametrize(("offset", "literal_first", "expected"), [
    (5, False, 145.125),
    (-5, False, 155.125),
    (-5, True, 155.125),
])
def test_energy_bound_can_subtract_a_literal_offset_from_a_verified_mean(offset, literal_first, expected):
    mean = StepResult(executionId="e", stepId="mean", status="verified", outputs={
        "value": {"value": 150.125, "field": "meanIonEnergy", "unit": "eV", "evidence_ids": ["mean-evidence"]},
    })
    ref = {"kind": "result_ref", "step_id": "mean", "field": "value", "scope": {"kind": "scalar"}}
    literal = {"kind": "literal", "value": offset, "unit": "eV",
               "source": {"message_key": "question", "quote": "+- 5 ev"}}
    step = DeriveStep.model_validate({
        "id": "bound", "kind": "derive", "operation": "difference", "depends_on": ["mean"],
        "inputs": {"values": [literal, ref] if literal_first else [ref, literal],
                   "direction": "second_minus_first" if literal_first else "first_minus_second"},
    })

    result = SequentialExecutor(Port()).execute(1, step, {}, {"mean": mean})

    assert result.status == "verified"
    bound = result.outputs["value"]
    assert (bound["field"], bound["unit"], bound["value"]) == ("meanIonEnergy", "eV", expected)
    assert bound["evidence_ids"] == ["mean-evidence"]


def test_no_search_or_calculation_is_reserved_after_a_required_value_is_missing():
    port = Port()
    executor = SequentialExecutor(port)
    step = DeriveStep.model_validate({
        "id": "max", "kind": "derive", "operation": "max",
        "inputs": {"values": {"kind": "result_ref", "step_id": "compare", "field": "ionFlux",
                             "scope": {"kind": "context_selection", "key": "selected_runs"}}},
        "requires": [{"step_id": "compare", "field": "ionFlux", "count": 2}],
    })
    result = StepResult(executionId="e", stepId="compare", status="partial", outputs={"ionFlux": [None, None]})
    assert executor.execute(1, step, {}, {"compare": result}).reason == "MISSING_INPUT:ionFlux"
    assert not port.calls


def test_existing_tool_reservation_without_result_is_not_resent():
    port = Port()
    port.start_step = lambda *_: {"executionId": "previous", "callAllowed": False, "result": None}
    step = ReverseStep.model_validate({"id": "search", "kind": "tool", "tool": "reverse_search",
                                      "inputs": {"constraints": []}})
    assert SequentialExecutor(port).execute(1, step, {}, {}).reason == "EXECUTION_OUTCOME_UNKNOWN"


def test_search_without_a_unit_uses_the_existing_default_unit():
    port = Port()
    port.load_context = lambda _: []
    step = ReverseStep.model_validate({
        "id": "search", "kind": "tool", "tool": "reverse_search",
        "inputs": {"constraints": [{"field": "ionFlux", "operator": "gt", "value": {
            "kind": "literal", "value": 40, "unit": None,
            "source": {"message_key": "question", "quote": "40보다 높은"},
        }}]},
    })
    result = SequentialExecutor(port).execute(1, step, {}, {})
    assert result.status == "empty"
    assert result.outputs["toolResult"]["defaultedUnits"] == ["ionFlux"]
