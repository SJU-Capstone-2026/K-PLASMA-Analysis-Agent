"""Synthetic proposal, worker binding, holdout gates and GitHub transport tests."""

import base64
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from kplasma_agent.v2.model_gateway import PLAN_INSTRUCTIONS

from . import proposal_worker, run_plan_proposal, validate_plan_proposal as validation
from .automatic_improvement import SPLIT_COUNTS, grade_plan
from .plan_proposal import Proposal, apply_proposal, digest, load_candidate, read_packet
from .proposal_pr import GATEWAY, publish, replace_prompt_literal
from .test_automatic_improvement import reference_case


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


def fake_run(directory, dataset, cases, prompt, passing, *, split="learning", receipt=False):
    source = {GATEWAY: "source-hash"}
    settings = {"planner": "test", "writer": "test", "planEffort": "low", "answerEffort": "low", "decisions": "test",
                "planReviewEnabled": True, "modelTimeoutSeconds": 90}
    record = {"suite": "automatic-improvement", "split": split, "graphVersion": "v2", "evaluationMode": "real_model",
              "settings": settings, "graphPlanReviewEnabled": True, "maxReplans": 2, "maxAnswerRewrites": 1,
              "planInstructionsSha256": digest(prompt.encode()), "sourceSha256": source,
              "inputSha256": {k: digest((dataset / k).read_bytes()) for k in ("learning.json", "evaluation.json")}}
    if receipt:
        record["workerPlanInstructionsSha256"] = record["planInstructionsSha256"]
    dump(directory / "manifest.json", record)
    dump(directory / "matrix.json", [{"case": c["id"], "trial": 1, "mode": "api"} for c in cases])
    for c in cases:
        i = c["id"]
        actual = deepcopy(c["referencePlan"])
        if i not in passing:
            actual["steps"][0]["inputs"]["mode"] = "results"
        models = [{"kind": "PLAN_INITIAL", "id": i, "request_id": i, "outcome": {"data": actual}},
                  {"kind": "REPLAN", "outcome": {"data": "DO_NOT_SEND_REPLANS"}}]
        if receipt:
            for attempt in models:
                attempt["outcome"]["usage"] = {"planInstructionsSha256": digest(prompt.encode())}
        trial = directory / "trials" / f"{i}-1"
        dump(trial / "execution-records.json", {"models": models, "steps": ["PRIVATE_TOOL_PAYLOAD"]})
        dump(trial / "result.json", {"case": i, "trial": 1, "mode": "api", "expectedGraphVersion": "v2",
                                     "view": {"question": c["question"]}, "requestId": i, "evaluationMode": "real_model",
                                     "firstPlan": {"attemptId": i, "modelError": None, **grade_plan(c, actual)}})
    dump(directory / "summary.json", {"automaticImprovement": {"trials": len(cases), "firstPlanPass": len(passing)}})


@pytest.fixture
def study(tmp_path, monkeypatch):
    d = tmp_path / "data"
    def make(split):
        cases = []
        for j in range(1, 4):
            case = reference_case(f"{split} synthetic question {j}", [
                {"id": "explain", "kind": "tool", "tool": "explain_answer", "inputs": {"mode": "concept"}}],
                ("private-run-id",), general=True)
            cases.append({"id": f"{split[0].upper()}10{j}", "steps": 1, "baseline": "private-run-id", **case})
        dump(d / f"{split}.json", cases)
        monkeypatch.setitem(SPLIT_COUNTS, split, {1: 3})
        return cases
    learning, evaluation = make("learning"), make("evaluation")
    args = SimpleNamespace(baseline=tmp_path / "original", dataset=d, output=tmp_path / "proposal", generate=False,
                           env_file=None, model="synthetic-editor", effort="low")
    fake_run(args.baseline, d, learning, PLAN_INSTRUCTIONS, {"L101"})
    return args, learning, evaluation


def example(packet):
    title, section = next(iter(packet["sections"].items()))
    before = section.splitlines()[0]
    return {"action": "replace", "section": title, "before": before, "after": before + " 원문을 확인한다.",
            "reason": "synthetic reason", "failure_ids": [packet["failures"][0]["id"]],
            "success_ids": [packet["successes"][0]["id"]]}


def generate_fake(args, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    class Editor:
        client = None
        def __init__(self, settings):
            assert settings.model == "synthetic-editor"

        def generate(self, instructions, packet, schema):
            assert "no_change" in instructions and schema is Proposal
            return example(packet), {"inputTokens": 12}
    monkeypatch.setattr(run_plan_proposal, "ModelClient", Editor)
    args.generate = True
    assert run_plan_proposal.run(args) == "replace"
    return load_candidate(args.output, PLAN_INSTRUCTIONS)


def test_preparation_reads_learning_only_and_never_creates_model(study, monkeypatch):
    args, _, _ = study
    (args.dataset / "evaluation.json").unlink()
    monkeypatch.setattr(run_plan_proposal, "ModelClient", lambda *_: pytest.fail("model invoked"))
    assert run_plan_proposal.run(args) == "prepared"
    packet = (args.output / "input.json").read_text()
    for forbidden in ("private-run-id", "PRIVATE_TOOL_PAYLOAD", "DO_NOT_SEND_REPLANS", "evaluation synthetic"):
        assert forbidden not in packet
    assert not (args.output / "candidate.txt").exists()
    with pytest.raises(FileExistsError):
        run_plan_proposal.run(args)


@pytest.mark.parametrize("bad", ["prompt", "dataset", "matrix", "link", "review"])
def test_reject_incompatible_baselines(study, bad):
    args, _, _ = study
    prompt = PLAN_INSTRUCTIONS
    if bad == "prompt":
        prompt += " "
    elif bad == "dataset":
        with (args.dataset / "learning.json").open("a") as f:
            f.write(" ")
    elif bad == "matrix":
        dump(args.baseline / "matrix.json", [])
    elif bad == "link":
        path = args.baseline / "trials/L101-1/result.json"
        v = json.loads(path.read_bytes())
        v["requestId"] = "other"
        dump(path, v)
    else:
        path = args.baseline / "manifest.json"
        v = json.loads(path.read_bytes())
        v["graphPlanReviewEnabled"] = False
        dump(path, v)
    with pytest.raises(ValueError):
        read_packet(args.baseline, args.dataset, prompt)


def test_model_selects_passage_and_worker_loads_only_validated_candidate(study, monkeypatch, tmp_path):
    args, _, _ = study
    candidate = generate_fake(args, monkeypatch)
    packet = json.loads((args.output / "input.json").read_bytes())
    change = example(packet)
    assert candidate == PLAN_INSTRUCTIONS.replace(change["before"], change["after"], 1)
    assert (args.output / "candidate.diff").read_text().count("@@") == 2
    monkeypatch.setattr(proposal_worker.model_gateway, "PLAN_INSTRUCTIONS", PLAN_INSTRUCTIONS)
    monkeypatch.setattr(proposal_worker.worker, "V2ModelGateway", proposal_worker.worker.V2ModelGateway)
    seen = []
    monkeypatch.setattr(proposal_worker.worker, "serve", lambda *_: seen.append(proposal_worker.model_gateway.PLAN_INSTRUCTIONS))
    receipt = tmp_path / "receipt"
    monkeypatch.setattr("sys.argv", ["worker", "--proposal", str(args.output), "--sha256", digest(candidate.encode()),
                                     "--receipt", str(receipt)])
    proposal_worker.main()
    assert seen == [candidate] and json.loads(receipt.read_bytes())["sha256"] == digest(candidate.encode())
    (args.output / "candidate.txt").write_text("tampered")
    with pytest.raises(ValueError):
        load_candidate(args.output, PLAN_INSTRUCTIONS)


def test_reject_ungrounded_changes_and_support_no_change(study):
    args, _, _ = study
    packet, _ = read_packet(args.baseline, args.dataset, PLAN_INSTRUCTIONS)
    base = example(packet)
    for override in ({"section": "unknown"}, {"before": "partial line"}, {"failure_ids": ["E101"]},
                     {"success_ids": ["L102"]}, {"after": "# new heading"}, {"after": packet["failures"][0]["question"]}):
        with pytest.raises(ValueError):
            apply_proposal(Proposal(**{**base, **override}), packet, PLAN_INSTRUCTIONS)
    unchanged = Proposal(action="no_change", reason="Evidence insufficient", failure_ids=[], success_ids=[])
    assert apply_proposal(unchanged, packet, PLAN_INSTRUCTIONS) is None


def test_paired_gate_measures_lost_cases_even_when_total_rises():
    result = validation.assess({"L101"}, {"L201", "L301"}, 3, 1)
    assert result["improved"] == ["L201", "L301"] and result["singleStepRegressions"] == ["L101"]
    assert not result["passed"]


def test_pipeline_short_circuits_and_accepts_matching_holdout_without_network(study, monkeypatch, tmp_path):
    proposal_args, learning, evaluation = study
    prompt = generate_fake(proposal_args, monkeypatch)
    args = SimpleNamespace(proposal=proposal_args.output, baseline=proposal_args.baseline, dataset=proposal_args.dataset,
                           output=tmp_path / "arms", evaluate=False, publish=False, min_learning_gain=1, min_evaluation_gain=1)
    monkeypatch.setattr(validation.subprocess, "run", lambda *_a, **_kw: pytest.fail("live evaluation started"))
    fake_run(args.output / "learning-candidate", args.dataset, learning, prompt, {"L101"}, receipt=True)
    assert validation.validate(args)["status"] == "below_threshold"
    assert not (args.output / "evaluation-original").exists()
    fake_run(args.output / "learning-candidate", args.dataset, learning, prompt, {"L101", "L102"}, receipt=True)
    fake_run(args.output / "evaluation-original", args.dataset, evaluation, PLAN_INSTRUCTIONS, {"E101"}, split="evaluation")
    fake_run(args.output / "evaluation-candidate", args.dataset, evaluation, prompt, {"E101", "E102"},
             split="evaluation", receipt=True)
    assert validation.validate(args)["status"] == "eligible"
    path = args.output / "evaluation-candidate" / "manifest.json"
    bad = json.loads(path.read_bytes())
    bad.pop("workerPlanInstructionsSha256")
    dump(path, bad)
    with pytest.raises(ValueError, match="confirmation"):
        validation.validate(args)


def test_publish_creates_single_file_draft_and_reuses_existing_pr():
    source = 'PLAN_INSTRUCTIONS = """원본"""\nOTHER = True\n'
    new = '수정된 "규칙"'
    assert 'OTHER = True' in replace_prompt_literal(source, "원본", new)
    branch_exists = False
    pulls = []
    def github(req):
        nonlocal branch_exists
        path = req.url.path
        body = json.loads(req.content) if req.content else None
        if path.endswith("/git/ref/heads/main"):
            data = {"object": {"sha": "base"}}
        elif "/contents/" in path:
            data = {"content": base64.b64encode(source.encode()).decode()}
        elif path.endswith("/git/commits/base"):
            data = {"tree": {"sha": "oldtree"}}
        elif path.endswith("/git/trees"):
            assert len(body["tree"]) == 1 and body["tree"][0]["path"] == GATEWAY
            assert body["tree"][0]["content"] == replace_prompt_literal(source, "원본", new)
            data = {"sha": "newtree"}
        elif "/git/ref/heads/feat" in path:
            if not branch_exists:
                return httpx.Response(404)
            data = {"object": {"sha": "commit"}}
        elif path.endswith("/git/commits"):
            data = {"sha": "commit"}
        elif path.endswith("/git/refs"):
            branch_exists = True
            data = {}
        elif path.endswith("/git/commits/commit"):
            data = {"parents": [{"sha": "base"}], "tree": {"sha": "newtree"}}
        elif path.endswith("/pulls") and req.method == "POST":
            assert body["draft"] and "L102" not in body["body"]
            data = {"html_url": "https://example.test/pr/1"}
            pulls.append(data)
        elif path.endswith("/pulls"):
            data = pulls
        else:
            pytest.fail(path)
        return httpx.Response(200, json=data)
    stats = {"learning": validation.assess({"L101"}, {"L101", "L102"}, 3, 1)}
    with httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(github)) as client:
        for _ in range(2):
            assert publish(client, "org/repo", "main", "원본", new, digest(source.encode()), stats).endswith("/1")
    assert len(pulls) == 1


def test_pipeline_stops_after_one_no_change_response(study, tmp_path, monkeypatch):
    args, _, _ = study
    out = tmp_path / "pipeline-proposal"
    calls = []
    def no_change(editor):
        calls.append(editor.output)
        dump(editor.output / "result.json", {"status": "no_change", "modelCalls": 1})
    monkeypatch.setattr(validation, "run_editor", no_change)
    monkeypatch.setattr(validation, "ensure_run", lambda *_a, **_kw: pytest.fail("evaluation after no_change"))
    monkeypatch.setattr(validation, "publish", lambda *_a, **_kw: pytest.fail("published no_change"))
    pipeline = SimpleNamespace(baseline=args.baseline, dataset=args.dataset, proposal=out,
                               generate_if_missing=True, model="test", effort="low", env_file=None)
    for _ in range(2):
        assert validation.validate(pipeline) == {"status": "no_change", "splits": {}}
    assert calls == [out]


@pytest.mark.parametrize("candidate", ['abc"""', '한글\\\\끝', 'line\n"quote"', '"""code"""\n다음', "복원\r\n끝"])
def test_python_source_round_trip_for_candidate_text(candidate):
    source = 'α = "테스트"\nPLAN_INSTRUCTIONS = """기존 값"""\nx = 2\n'
    updated = replace_prompt_literal(source, "기존 값", candidate)
    assert updated.startswith('α = "테스트"\n') and updated.endswith('\nx = 2\n')


def test_evaluator_rejects_first_plan_or_replan_from_another_worker():
    from .plan_proposal import verify_attempt_prompt
    rows = [{"kind": k, "outcome": {"usage": {"planInstructionsSha256": "candidate"}}}
            for k in ("PLAN_INITIAL", "REPLAN")]
    verify_attempt_prompt(rows, "candidate")
    rows[1]["outcome"]["usage"] = None
    with pytest.raises(ValueError, match="worker"):
        verify_attempt_prompt(rows, "candidate")


def test_recorded_model_output_failure_is_audited_and_never_editor_evidence(study):
    args, _, _ = study
    root = args.baseline / "trials/L102-1"
    logs = json.loads((root / "execution-records.json").read_text())
    logs["models"][0]["outcome"] = {"error": "MODEL_OUTPUT_TRUNCATED", "data": None}
    dump(root / "execution-records.json", logs)
    result = json.loads((root / "result.json").read_text())
    result["firstPlan"].update(modelError="MODEL_OUTPUT_TRUNCATED", failures=[{"check": "plan_missing"}])
    dump(root / "result.json", result)
    packet, audit = read_packet(args.baseline, args.dataset, PLAN_INSTRUCTIONS)
    assert audit["missingPlans"] == [{"id": "L102", "modelError": "MODEL_OUTPUT_TRUNCATED"}]
    assert "L102" not in json.dumps(packet)
