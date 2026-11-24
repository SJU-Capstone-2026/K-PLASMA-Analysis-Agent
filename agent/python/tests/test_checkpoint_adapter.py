from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from kplasma_agent.persistence.checkpointer import DurableSaver


class State(TypedDict):
    count: int


def test_checkpoint_restores_graph_after_new_worker_and_rejects_stale_write():
    storage = {}
    generation = [1]

    def save(payload):
        assert generation[0] == 1, "stale lease"
        storage["payload"] = payload

    saver = DurableSaver(None, save)
    graph = StateGraph(State)
    graph.add_node("increment", lambda state: {"count": state["count"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    config = {"configurable": {"thread_id": "request-test"}}
    graph.compile(checkpointer=saver).invoke({"count": 4}, config, durability="sync")
    fresh = DurableSaver(storage["payload"], save)
    assert graph.compile(checkpointer=fresh).get_state(config).values["count"] == 5
    generation[0] = 2
    try:
        graph.compile(checkpointer=fresh).invoke({"count": 8}, config, durability="sync")
    except AssertionError:
        pass
    else:
        raise AssertionError("stale writer must fail")
