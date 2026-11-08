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
