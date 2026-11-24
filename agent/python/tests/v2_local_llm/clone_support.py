"""Static evidence for the initial copy; never read a mutable v2 oracle."""

import ast
from collections import Counter
import copy
import hashlib
import importlib.util
import json


NAMESPACE = "kplasma_agent.v2_local_llm"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def absolute_imports(tree, module, *, package=False):
    owner = module if package else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            node.module = importlib.util.resolve_name("." * node.level + (node.module or ""), owner)
            node.level = 0
    return tree


def ast_segments(text, module, *, package=False):
    tree = absolute_imports(ast.parse(text), module, package=package)
    result = []
    counts = Counter()

    def append(node, prefix=""):
        if isinstance(node, ast.ClassDef):
            selector = prefix + "class:" + node.name
            header = copy.deepcopy(node)
            header.body = []
            result.append([selector, ast.dump(header, include_attributes=False)])
            for child in node.body:
                append(child, selector + "/")
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = "function:" + node.name
        elif isinstance(node, ast.ImportFrom):
            name = "import:" + str(node.module) + ":" + ",".join(
                alias.name + (" as " + alias.asname if alias.asname else "") for alias in node.names)
        elif isinstance(node, ast.Import):
            name = "import:" + ",".join(alias.name for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            name = "assign:" + ",".join(ast.unparse(target) for target in targets)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            name = "docstring"
        else:
            name = type(node).__name__
        selector = prefix + name
        counts[selector] += 1
        if counts[selector] > 1:
            selector += "#" + str(counts[selector])
        result.append([selector, ast.dump(node, include_attributes=False)])

    for node in tree.body:
        append(node)
    return result


def check_import_boundary(text, module, *, package=False):
    tree = absolute_imports(ast.parse(text), module, package=package)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
            # A root-package import can otherwise hide an original module as an alias.
            names += [(node.module or "") + "." + alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        for name in names:
            if name == "importlib" or name.startswith("importlib."):
                raise AssertionError("dynamic imports are not allowed in the independent runtime")
            if name == "kplasma_agent" or name.startswith("kplasma_agent."):
                assert name == NAMESPACE or name.startswith(NAMESPACE + "."), (module, name)
        if isinstance(node, ast.Call):
            function = node.func
            name = function.id if isinstance(function, ast.Name) else (
                function.attr if isinstance(function, ast.Attribute) else "")
            assert name not in {"__import__", "import_module", "eval", "exec"}, (module, name)
        if isinstance(node, ast.Attribute) and node.attr == "modules":
            raise AssertionError("sys.modules access could share another runtime's objects")


def allowed_changes(path, changes):
    entries = [entry for entry in changes if entry["path"] == path]
    for entry in entries:
        assert entry.get("reason") and entry.get("tests"), entry
        assert isinstance(entry["selectors"], list), entry
        assert entry.get("newFile") or entry["selectors"], entry
    return {selector for entry in entries for selector in entry["selectors"]}


def check_segments(expected, actual, allowed):
    known = {selector for selector, _ in expected + actual}
    assert allowed <= known, "unknown intentional-difference selector"
    assert [item for item in expected if item[0] not in allowed] == [
        item for item in actual if item[0] not in allowed]


def contract_evidence(gateway, plan_review):
    return {
        "prompts": {name: digest(getattr(gateway, name)) for name in ("PLAN_INSTRUCTIONS", "COMPOSE_INSTRUCTIONS")},
        "questions": json.loads(json.dumps(gateway.QUESTIONS, ensure_ascii=False)),
        "tool": gateway.submit_plan_tool_schema(),
        "schemas": {name: getattr(gateway, name).model_json_schema()
                    for name in ("PlanDraft", "GeneralAnswerDraft", "DataAnswerDraft")},
        "planReviewSchema": plan_review.PlanReviewResult.model_json_schema(),
    }
