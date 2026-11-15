"""The MLX wire boundary is testable without MLX or GPU weights."""

import importlib.util
from pathlib import Path

import pytest


def service():
    path = Path(__file__).parents[2] / "runtimes/d1_mlx/service.py"
    if not path.exists():
        pytest.fail("d1 MLX service is not implemented")
    spec = importlib.util.spec_from_file_location("d1_mlx_service_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def body(n=6):
    return {
        "state": "complete-state",
        "questions": {
            f"q{i:03}": {
                "type": "choice",
                "instructions": "test",
                "criteria": {"match": "same", "changed": "different"},
            }
            for i in range(n)
        },
    }


@pytest.mark.parametrize("n", [1, 6, 16, 17, 400])
def test_singletons_preserve_all_checks_and_full_state(n):
    groups = service().pack_requests(body(n), 1, lambda b: 100 + len(b["questions"]))
    assert len(groups) == n
    assert all(len(b["questions"]) == 1 and b["state"] == "complete-state" for b, _ in groups)
    assert [qid for b, _ in groups for qid in b["questions"]] == list(body(n)["questions"])
    assert all(tokens == 101 for _, tokens in groups)


def test_full_input_limit_never_silently_truncates():
    assert service().pack_requests(body(1), 1, lambda _: 16000)[0][1] == 16000
    with pytest.raises(ValueError, match="LOCAL_D1_INPUT_TOO_LARGE"):
        service().pack_requests(body(1), 1, lambda _: 16001)


@pytest.mark.parametrize("size", [0, 2, 4, 16, True])
def test_v23_rejects_joint_question_groups(size):
    with pytest.raises(ValueError, match="LOCAL_D1_GROUP_CONFIG_INVALID"):
        service().pack_requests(body(4), size, lambda _: 100)


@pytest.mark.parametrize("bad", [None, {}, {"state": {}, "questions": {}},
    {"state": "s", "questions": {}},
    {"state": "s", "questions": {"q": {"type": "choice", "instructions": "", "criteria": {"a": "a", "b": "b"}}}},
    {**body(), "images": ["https://outside.invalid"]}])
def test_invalid_request_is_rejected_before_counting(bad):
    with pytest.raises(ValueError, match="LOCAL_D1_REQUEST_INVALID"):
        service().pack_requests(bad, 1, lambda _: pytest.fail("counted invalid input"))


def test_production_order_and_choice_order_are_deterministic():
    request = body(3)
    request["questions"] = dict(reversed(list(request["questions"].items())))
    groups = service().pack_requests(request, 1, lambda _: 100)
    assert [next(iter(b["questions"])) for b, _ in groups] == sorted(request["questions"])
    assert all(list(next(iter(b["questions"].values()))["criteria"]) == ["changed", "match"] for b, _ in groups)
