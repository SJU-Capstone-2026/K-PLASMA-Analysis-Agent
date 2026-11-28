"""Publish only the verified plan-instruction edit and aggregate scores as a draft PR."""

import ast
import base64
import re
from urllib.parse import quote

from .plan_proposal import digest

GATEWAY = "agent/python/src/kplasma_agent/v2/model_gateway.py"


def replace_prompt_literal(source, baseline, candidate):
    tree = ast.parse(source)
    matches = [node.value for node in tree.body if isinstance(node, ast.Assign)
               and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
               and node.targets[0].id == "PLAN_INSTRUCTIONS"]
    if len(matches) != 1 or not isinstance(matches[0], ast.Constant) or matches[0].value != baseline:
        raise ValueError("Remote source does not contain the evaluated baseline prompt")
    literal = matches[0]
    lines = source.encode().splitlines(keepends=True)
    start = sum(map(len, lines[:literal.lineno - 1])) + literal.col_offset
    end = sum(map(len, lines[:literal.end_lineno - 1])) + literal.end_col_offset
    escaped = candidate.replace("\\", "\\\\").replace("\r", "\\r").replace("\0", "\\x00")
    escaped = re.sub(r'("{3,}|"+$)', lambda m: '\\"' * len(m[0]), escaped)
    replacement = ('"""' + escaped + '"""').encode()
    updated = (source.encode()[:start] + replacement + source.encode()[end:]).decode()
    literal.value = candidate
    if ast.dump(tree) != ast.dump(ast.parse(updated)):
        raise ValueError("The proposed source changes more than the instruction literal")
    return updated


def publish(client, repo, base, original, candidate, source_hash, aggregates):
    def api(method, path, **options):
        response = client.request(method, f"/repos/{repo}/{path}", **options)
        response.raise_for_status()
        return response.json()

    base_sha = api("GET", f"git/ref/heads/{quote(base, safe='/')}")["object"]["sha"]
    source = base64.b64decode(api("GET", f"contents/{GATEWAY}", params={"ref": base_sha})["content"])
    if digest(source) != source_hash:
        raise ValueError("Remote gateway has changed since evaluation")
    updated = replace_prompt_literal(source.decode(), original, candidate)
    branch = f"feat/plan-prompt-{base_sha[:10]}-{digest(candidate.encode())[:12]}"
    root_tree = api("GET", f"git/commits/{base_sha}")["tree"]["sha"]
    tree = api("POST", "git/trees", json={"base_tree": root_tree, "tree": [
        {"path": GATEWAY, "mode": "100644", "type": "blob", "content": updated}]})["sha"]
    ref_path = f"/repos/{repo}/git/ref/heads/{branch}"
    ref = client.get(ref_path)
    if ref.status_code == 404:
        commit = api("POST", "git/commits", json={"message": "feat(agent): 검증된 V2 계획 지시문 적용",
                                                   "tree": tree, "parents": [base_sha]})
        created = client.post(f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
        if created.status_code != 422:  # A concurrent run may already own the same deterministic ref.
            created.raise_for_status()
        ref = client.get(ref_path)
    ref.raise_for_status()
    head = api("GET", "git/commits/" + ref.json()["object"]["sha"])
    if head["tree"]["sha"] != tree or [p["sha"] for p in head["parents"]] != [base_sha]:
        raise ValueError("Existing proposal branch has different changes")
    selector = {"state": "all", "base": base, "head": f"{repo.split('/')[0]}:{branch}"}
    existing = api("GET", "pulls", params=selector)
    if existing:
        return existing[0]["html_url"]
    body = ("일반 V2의 계획 지시문 한 문단을 수정합니다. 표는 동일 문항에서 재계획 전 최초 계획의 통과 건수입니다.\n\n"
            "| 분할 | 문항 | 기존 | 수정 | 실패→통과 | 통과→실패 |\n|---|---:|---:|---:|---:|---:|\n"
            + "\n".join(f"| {name} | {g['trials']} | {g['basePass']} | {g['candidatePass']} | "
                        f"{len(g['improved'])} | {len(g['regressed'])} |" for name, g in aggregates.items()))
    response = client.post(f"/repos/{repo}/pulls", json={"title": "feat(agent): V2 계획 지시문 개선",
                                                         "body": body, "head": branch, "base": base, "draft": True})
    if response.status_code == 422:
        existing = api("GET", "pulls", params=selector)
        if existing:
            return existing[0]["html_url"]
    response.raise_for_status()
    return response.json()["html_url"]
