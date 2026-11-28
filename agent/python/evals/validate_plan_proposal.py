"""Pair first-plan scores, gate the holdout, and optionally publish one verified draft PR."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import httpx

from kplasma_agent.v2.model_gateway import PLAN_INSTRUCTIONS

from .plan_proposal import digest, load_candidate, read_trials
from .proposal_pr import GATEWAY, publish
from .run_plan_proposal import run as run_editor


def assess(base_ids, candidate_ids, total, minimum_gain):
    gained = sorted(candidate_ids - base_ids)
    lost = sorted(base_ids - candidate_ids)
    single_step_losses = [i for i in lost if i[1] == "1"]
    return {"trials": total, "basePass": len(base_ids), "candidatePass": len(candidate_ids),
            "improved": gained, "regressed": lost, "singleStepRegressions": single_step_losses,
            "minimumGain": minimum_gain, "passed": len(gained) - len(lost) >= minimum_gain and not single_step_losses}


def manifest(directory):
    return json.loads((directory / "manifest.json").read_bytes())


def comparable(run):
    settings = run["settings"]
    keys = ("planner", "planEffort", "writer", "answerEffort", "decisions", "planReviewEnabled", "modelTimeoutSeconds")
    return (run["inputSha256"], run["sourceSha256"], run["maxReplans"], run["maxAnswerRewrites"],
            {k: settings[k] for k in keys})


def read_scores(directory, dataset, prompt, split, *, candidate):
    run = manifest(directory)
    if candidate and run.get("workerPlanInstructionsSha256") != digest(prompt.encode()):
        raise ValueError("Missing candidate-worker prompt confirmation")
    passed, _, audit = read_trials(directory, dataset, prompt, split)
    return {r["id"] for r in passed}, audit


def ensure_run(args, split, name, *, candidate):
    output = args.output / name
    if output.exists() or not args.evaluate:
        return output
    command = [sys.executable, "-m", "evals.run_flow", "--suite", "automatic-improvement", "--mode", "api",
               "--graph-version", "v2", "--split", split, "--dataset", str(args.dataset), "--output", str(output),
               "--live", "--bundle", str(args.bundle), "--connection", str(args.connection),
               "--env-file", str(args.env_file)]
    if candidate:
        command.extend(["--proposal", str(args.proposal)])
    subprocess.run(command, check=True)
    return output


def validate(args):
    if not args.proposal.exists() and args.generate_if_missing:
        run_editor(SimpleNamespace(baseline=args.baseline, dataset=args.dataset, output=args.proposal,
                                   generate=True, env_file=args.env_file, model=args.model, effort=args.effort))
    proposal_result = json.loads((args.proposal / "result.json").read_bytes())
    if proposal_result["status"] in {"no_change", "no_editable_failures"}:
        return {"status": proposal_result["status"], "splits": {}}
    candidate = load_candidate(args.proposal, PLAN_INSTRUCTIONS)
    source = manifest(args.baseline)
    audit = json.loads((args.proposal / "audit.json").read_bytes())
    if audit["splitSha256"] != source["inputSha256"]["learning.json"]:
        raise ValueError("Proposal does not belong to this learning dataset")
    fingerprint = comparable(source)
    groups = {}
    for split, gain in (("learning", args.min_learning_gain), ("evaluation", args.min_evaluation_gain)):
        original = args.baseline if split == "learning" else ensure_run(args, split, "evaluation-original", candidate=False)
        if comparable(manifest(original)) != fingerprint:
            raise ValueError("Baseline data, runtime sources or model settings changed")
        base_ids, base_audit = read_scores(original, args.dataset, PLAN_INSTRUCTIONS, split, candidate=False)
        if split == "learning" and base_audit["firstAttemptsSha256"] != audit["firstAttemptsSha256"]:
            raise ValueError("Learning baseline differs from the editor's recorded attempts")
        modified = ensure_run(args, split, f"{split}-candidate", candidate=True)
        if comparable(manifest(modified)) != fingerprint:
            raise ValueError("Candidate data, runtime sources or model settings changed")
        candidate_ids, _ = read_scores(modified, args.dataset, candidate, split, candidate=True)
        group = groups[split] = assess(base_ids, candidate_ids, base_audit["trials"], gain)
        if not group["passed"]:
            break

    result = {"status": "eligible" if len(groups) == 2 and groups["evaluation"]["passed"] else "below_threshold",
              "candidateSha256": digest(candidate.encode()), "splits": groups}
    if args.publish and result["status"] == "eligible":
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("Publishing requires GH_TOKEN or GITHUB_TOKEN")
        with httpx.Client(base_url="https://api.github.com", timeout=30, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        }) as client:
            result["pullRequest"] = publish(client, args.repo, args.base, PLAN_INSTRUCTIONS, candidate,
                                            source["sourceSha256"][GATEWAY], groups)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "dataset", "proposal", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--min-learning-gain", required=True, type=int, help="Minimum additional first-pass cases")
    parser.add_argument("--min-evaluation-gain", required=True, type=int)
    parser.add_argument("--evaluate", action="store_true", help="Run missing evaluation arms with real models")
    parser.add_argument("--generate-if-missing", action="store_true", help="Generate one proposal before evaluation")
    parser.add_argument("--model", default="gpt-6-luna", help="Editor model")
    parser.add_argument("--effort", default="low", help="Editor reasoning effort")
    for name in ("bundle", "connection", "env-file"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--publish", action="store_true", help="Open a draft PR if both gates pass")
    parser.add_argument("--repo", default="SJU-Capstone-2026/K-PLASMA-Analysis-Agent")
    parser.add_argument("--base", default="main")
    args = parser.parse_args()
    if not (1 <= args.min_learning_gain <= 100 and 1 <= args.min_evaluation_gain <= 50):
        parser.error("Supply positive gain thresholds within the size of each split")
    if args.evaluate and not all((args.bundle, args.connection, args.env_file)):
        parser.error("--evaluate requires --bundle, --connection, --env-file")
    if args.generate_if_missing and not args.evaluate:
        parser.error("--generate-if-missing requires --evaluate")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        parser.error("Expected an OWNER/REPO")
    os.umask(0o077)
    print(json.dumps(validate(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
