"""The local implementation is a physical copy of the pinned v2 source."""

import ast
import hashlib
import importlib
import inspect
import json
from pathlib import Path

import pytest

from .clone_support import (
    NAMESPACE, allowed_changes, ast_segments, check_import_boundary, check_segments, contract_evidence,
)

PACKAGE = Path(__file__).resolve().parents[2] / "src/kplasma_agent/v2_local_llm"
BASELINE = "51d077c9878b635c96da709eb7eb2aefd36699e1"


def test_independent_local_clone_has_a_pinned_manifest():
    path = PACKAGE / "clone-manifest.json"
    assert path.is_file(), "the independent local clone has not been created"
    manifest = json.loads(path.read_text())
    assert manifest["sourceCommit"] == BASELINE
    assert len(manifest["modules"]) == 36


def test_initial_evidence_is_immutable():
    for path, expected in (
        (PACKAGE / "clone-manifest.json", "7cbe5a9be0ca30f32db35467e174058007ce07931166aaabe6d59d70d5e5ca0b"),
        (Path(__file__).with_name("clone-baseline.json"), "ae68d201fcae5cb57cb7404136e2652f20ae1b3fd4065427b053cb2e80a8e1d1"),
        (Path(__file__).with_name("clone-outputs.json"), "b071617b9c6cfb6f46063bb47add7dab39d0ddd6efcf8e81a5e0dd3e927deeb9"),
    ):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, path


@pytest.fixture
def manifest():
    return json.loads((PACKAGE / "clone-manifest.json").read_text())


@pytest.fixture
def frozen():
    return json.loads(Path(__file__).with_name("clone-baseline.json").read_text())


def test_physical_files_and_pinned_ast_survive_localization(manifest, frozen):
    differences = json.loads((PACKAGE / "intentional-differences.json").read_text())
    assert differences["schemaVersion"] == 1
    changes = differences["changes"]
    expected_paths = {item["targetPath"] for item in manifest["modules"]}
    assert set(frozen["modules"]) == expected_paths
    assert len(expected_paths) == 36
    for item in manifest["modules"]:
        path = PACKAGE / item["targetPath"]
        assert path.is_file() and not path.is_symlink(), path
        allowed = allowed_changes(item["targetPath"], changes)
        if not allowed:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["initialCloneSha256"], path
        actual = ast_segments(path.read_text(), item["targetModule"], package=path.name == "__init__.py")
        check_segments(frozen["modules"][item["targetPath"]], actual, allowed)
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE).as_posix()
        if relative not in expected_paths:
            entries = [entry for entry in changes if entry["path"] == relative]
            assert len(entries) == 1 and entries[0].get("newFile"), path
            assert entries[0]["selectors"] == [], path
            assert entries[0].get("reason") and entries[0].get("tests"), path
    for entry in changes:
        assert (PACKAGE / entry["path"]).is_file(), entry
        assert ".." not in Path(entry["path"]).parts, entry


def test_every_production_file_stays_inside_the_local_namespace():
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE).with_suffix("").parts
        module = ".".join((NAMESPACE, *relative[:-1])) if path.name == "__init__.py" else ".".join(
            (NAMESPACE, *relative))
        check_import_boundary(path.read_text(), module, package=path.name == "__init__.py")


@pytest.mark.parametrize("statement", [
    "from kplasma_agent.v2 import model_gateway as shared",
    "from kplasma_agent import v3 as shared",
    "from ...v2 import contracts",
    "import importlib as loader; loader.import_module('kplasma_agent.v2')",
    "from importlib import import_module as load; load('kplasma_agent.' + 'v2')",
    "__import__('kplasma_agent.v2')",
    "import sys; shared = sys.modules['kplasma_agent.v2']",
    "exec('from kplasma_agent.v2 import PlanDraft')",
])
def test_boundary_rejects_import_alias_and_dynamic_escape(statement):
    with pytest.raises(AssertionError):
        check_import_boundary(statement, NAMESPACE + ".core.gateway")


def test_selectors_cannot_hide_other_logic_or_an_entire_file():
    original = ast_segments("VALUE = 1\ndef request(): return 1\ndef validate(): return 2", NAMESPACE + ".client")
    permitted = ast_segments("VALUE = 1\ndef request(): return 3\ndef validate(): return 2", NAMESPACE + ".client")
    check_segments(original, permitted, {"function:request"})
    escaped = ast_segments("VALUE = 1\ndef request(): return 3\ndef validate(): return 9", NAMESPACE + ".client")
    with pytest.raises(AssertionError):
        check_segments(original, escaped, {"function:request"})
    with pytest.raises(AssertionError):
        check_segments(original, escaped, {"*"})


def test_instructions_schemas_and_choice_meanings_match_the_frozen_source(frozen):
    gateway = importlib.import_module(NAMESPACE + ".core.model_gateway")
    review = importlib.import_module(NAMESPACE + ".core.plan_review")
    current = contract_evidence(gateway, review)

    def original_plan_schema(node):
        if isinstance(node, list):
            return [original_plan_schema(item) for item in node]
        if not isinstance(node, dict):
            return node
        # v2.2 changes descriptive metadata and one field name, never its constraints.
        result = {key: original_plan_schema(value) for key, value in node.items() if key != "description"}
        if result.get("title") == "Required Prior Outputs":
            result["title"] = "Requires"
        properties = result.get("properties", {})
        if "required_prior_outputs" in properties:
            properties["requires"] = properties.pop("required_prior_outputs")
        if "required" in result:
            result["required"] = ["requires" if key == "required_prior_outputs" else key
                                  for key in result["required"]]
        return result

    single_plan_draft = (
        "생각에서는 요청 범위, 조건의 수치·단위·경계와 필요한 단계 연결을 확인한다. "
        "생각 구간에는 JSON을 쓰지 않는다. "
        "계획 JSON은 submit_plan 호출의 인자로만 한 번 작성한다.\n"
    )
    assert gateway.PLAN_INSTRUCTIONS.count(single_plan_draft) == 1
    before, _ = gateway.PLAN_INSTRUCTIONS.replace(single_plan_draft, "", 1).split(
        "# 선행 출력 조건(required_prior_outputs)\n")
    # Prerequisite and replan guidance evolve; the remaining cloned contracts stay pinned.
    after = """각 단계의 requirement_ids는 requirements[].id를, requirements[].handled_by는 steps[].id를 참조한다.
이전 단계에서 만든 값을 쓰는 경우 depends_on에 그 단계의 ID를 넣는다.
앞 결과는 등록 필드와 범위가 있는 result_ref로 연결한다. JSON 경로나 계산된 수치를 만들지 않는다.
결과가 누락되면 입력을 확인하거나 지원되는 복구 계획을 세운다. 없는 데이터는 만들지 않는다.
재계획 시 base_revision을 유지하고 변경과 무관한 유효 단계의 ID와 내용을 보존한다.
메시지 인용은 제공된 messages의 키와 원문 구절을 사용한다.
rejected_plan과 validation_error가 있으면 거절된 계획의 오류 위치·actual·allowed를 보고 수정한다. previous_plan은 마지막 승인 계획이다.
generation_failure는 직전 생성 실패 정보다. 잘린 JSON을 그대로 실행하지 말고 원문 조건을 보존한 완전한 계획을 제출한다."""
    original_instructions = (before + "# 연결·재계획\n" + after).replace("required_prior_outputs", "requires")
    current["prompts"]["PLAN_INSTRUCTIONS"] = hashlib.sha256(original_instructions.encode()).hexdigest()
    before, section = gateway.COMPOSE_INSTRUCTIONS.split("해석·한계의 본문은 text 문자열 대신 segments 배열로 작성하고", 1)
    _, after = section.split("최댓값·최솟값의 부호와 비교 방향은", 1)
    legacy_references = """인용하는 모든 실험값(측정값, 위상, 차이, 배율, 공정 조건)은 근거의 value_parts에서 선택한다.
참조 문법은 {{value:근거ID|항목명}}이다. 근거ID는 이번 evidence[].id 전체를 그대로 복사하고 항목명은 그 근거의 value_parts에서 선택한다.
단계 이름·Run 이름·compare 접두사를 근거 ID에 추가하거나 실행 ID를 생략하지 않는다. 숫자와 단위는 코드가 채운다.
각 참조는 해당 해석·가정·한계의 evidence_ids에 넣은 실제 근거 ID여야 한다. 참조 가능한 값이 없으면 관찰의 범위를 설명한다.
"""
    original_compose = (before + legacy_references + "최댓값·최솟값의 부호와 비교 방향은" + after).replace(
        "실험 답변의 fact_ids에는 evidence_choices의 ref를 넣는다.", "실험 답변의 fact_ids에는 실제 근거 ID를 넣는다.")
    current["prompts"]["COMPOSE_INSTRUCTIONS"] = hashlib.sha256(original_compose.encode()).hexdigest()
    current["schemas"]["PlanDraft"] = original_plan_schema(current["schemas"]["PlanDraft"])
    current["tool"]["parameters"] = original_plan_schema(current["tool"]["parameters"])
    assert current == frozen["contracts"]


def test_local_definitions_and_bases_are_owned_objects(manifest):
    for item in manifest["modules"]:
        module = importlib.import_module(item["targetModule"])
        for _, value in vars(module).items():
            owner = getattr(value, "__module__", "")
            if inspect.isclass(value) or inspect.isfunction(value):
                if owner.startswith("kplasma_agent"):
                    assert owner == NAMESPACE or owner.startswith(NAMESPACE + "."), value
                if inspect.isclass(value):
                    for base in value.__mro__:
                        owner = getattr(base, "__module__", "")
                        if owner.startswith("kplasma_agent"):
                            assert owner == NAMESPACE or owner.startswith(NAMESPACE + "."), base


def test_test_fixtures_do_not_import_another_runtime_or_test_support():
    for path in Path(__file__).parent.rglob("*.py"):
        if path.name in {"test_clone_boundary.py", "test_clone_parity.py"}:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and not node.level:
                name = node.module or ""
                assert not name.startswith(("v2.", "v3.", "evals.v2_cases", "evals.v2_harness", "fixtures")), (path, name)
                if name.startswith("kplasma_agent"):
                    assert name == NAMESPACE or name.startswith(NAMESPACE + "."), (path, name)


@pytest.mark.initial_clone
def test_this_change_preserves_the_original_v2_and_v3_files(manifest):
    root = PACKAGE.parents[4]
    for relative, expected in manifest["preservedFiles"].items():
        path = root / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, path
