"""The initial fork must be a physical, independent copy of the frozen v2 runtime."""

import ast
import hashlib
import importlib
import json
import os
from pathlib import Path
import re

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "src/kplasma_agent"
CLONE = SOURCE / "v3"
BASELINE = "51d077c9878b635c96da709eb7eb2aefd36699e1"


@pytest.fixture
def manifest():
    path = CLONE / "clone-manifest.json"
    assert path.is_file(), "the independent v3 copy has not been created"
    return json.loads(path.read_text())


def test_frozen_v2_source_and_physical_clone_files_match_the_manifest(manifest):
    assert manifest["sourceCommit"] == BASELINE
    assert len(manifest["modules"]) == 36
    for item in manifest["modules"]:
        original = SOURCE / item["sourcePath"]
        copied = CLONE / item["targetPath"]
        assert original.is_file() and copied.is_file()
        assert not copied.is_symlink()
        assert original.resolve() != copied.resolve()
        assert hashlib.sha256(original.read_bytes()).hexdigest() == item["sourceSha256"], original
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == item["cloneSha256"], copied


def test_v3_production_imports_never_use_original_agent_modules(manifest):
    modules = {item["targetModule"] for item in manifest["modules"]}
    for item in manifest["modules"]:
        path = CLONE / item["targetPath"]
        package = item["targetModule"] if path.name == "__init__.py" else item["targetModule"].rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.ImportFrom):
                prefix = package.split(".")[:len(package.split(".")) - node.level + 1] if node.level else []
                target = ".".join([*prefix, *([node.module] if node.module else [])])
                names.append(target)
                names.extend(f"{target}.{alias.name}" for alias in node.names if f"{target}.{alias.name}" in modules)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name.startswith("kplasma_agent"):
                    assert name == "kplasma_agent.v3" or name.startswith("kplasma_agent.v3."), (path, name)


def test_initial_copy_has_no_logic_changes_beyond_imports_and_identity(manifest):
    inverse_modules = {item["targetModule"]: item["sourceModule"] for item in manifest["modules"]}
    inverse_names = {value: key for key, value in manifest["identifierReplacements"].items()}

    def canonical(text, module, path, *, copied=False, source_module=None):
        tree = ast.parse(text)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                prefix = package.split(".")[:len(package.split(".")) - node.level + 1] if node.level else []
                target = ".".join([*prefix, *([node.module] if node.module else [])])
                node.module, node.level = inverse_modules.get(target, target) if copied else target, 0
            if not copied:
                continue
            for field in ("id", "name", "arg", "attr", "asname"):
                value = getattr(node, field, None)
                if isinstance(value, str) and value in inverse_names:
                    setattr(node, field, inverse_names[value])
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.replace("AGENT_V3_", "AGENT_V2_")
                for new, old in inverse_names.items():
                    value = re.sub(r"\b" + new + r"\b", old, value)
                if source_module in {"kplasma_agent.graphs.v2", "kplasma_agent.v2.contracts"} and value == "v3":
                    value = "v2"
                if source_module == "kplasma_agent.v2.model_gateway" and value == "v3.plan":
                    value = "v2.plan"
                node.value = value
        return ast.dump(tree, include_attributes=False)

    for item in manifest["modules"]:
        original, copied = SOURCE / item["sourcePath"], CLONE / item["targetPath"]
        assert canonical(original.read_text(), item["sourceModule"], original) == canonical(
            copied.read_text(), item["targetModule"], copied, copied=True, source_module=item["sourceModule"]), copied


def test_graph_models_and_errors_are_independent_objects(manifest):
    pairs = [
        ("graphs.v2", "v3.graph", "build_v2_graph", "build_v3_graph"),
        ("v2.contracts", "v3.core.contracts", "PlanDraft", "PlanDraft"),
        ("v2.executor", "v3.core.executor", "SequentialExecutor", "SequentialExecutor"),
        ("model_client", "v3.model_client", "ModelError", "ModelError"),
        ("domain.forward", "v3.domain.forward", "lookup_forward", "lookup_forward"),
        ("answer_stream", "v3.answer_stream", "AnswerStreamProjector", "AnswerStreamProjector"),
    ]
    for old_module, new_module, old_name, new_name in pairs:
        old = getattr(importlib.import_module(f"kplasma_agent.{old_module}"), old_name)
        new = getattr(importlib.import_module(f"kplasma_agent.{new_module}"), new_name)
        assert new is not old
        assert new.__module__.startswith("kplasma_agent.v3.")


def test_planner_and_writer_instructions_are_copied_verbatim(manifest):
    original = importlib.import_module("kplasma_agent.v2.model_gateway")
    copied = importlib.import_module("kplasma_agent.v3.core.model_gateway")
    assert copied.PLAN_INSTRUCTIONS == original.PLAN_INSTRUCTIONS
    assert copied.COMPOSE_INSTRUCTIONS == original.COMPOSE_INSTRUCTIONS
    assert copied.QUESTIONS == original.QUESTIONS
    assert copied.submit_plan_tool_schema() == original.submit_plan_tool_schema()


def test_v3_model_settings_do_not_read_v2_overrides(manifest, monkeypatch):
    settings = importlib.import_module("kplasma_agent.v3.config").Settings(api_key="synthetic-key")
    gateway = importlib.import_module("kplasma_agent.v3.core.model_gateway")
    for key in list(os.environ):
        if key.startswith("AGENT_V3_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("AGENT_V2_PLAN_MODEL", "v2-only-model")
    monkeypatch.setenv("AGENT_V2_PLAN_REVIEW_ENABLED", "false")
    value = gateway.V3Settings.from_env(settings)
    assert value.planner.model == "gpt-6-luna"
    assert value.writer.model == "gpt-6-luna"
    assert value.plan_review_enabled is True
    monkeypatch.setenv("AGENT_V3_PLAN_MODEL", "v3-only-model")
    assert gateway.V3Settings.from_env(settings).planner.model == "v3-only-model"
