"""Prepare a private learning packet. --generate explicitly requests a single editor call."""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path

from kplasma_agent.config import Settings
from kplasma_agent.model_client import ModelClient
from kplasma_agent.v2.model_gateway import PLAN_INSTRUCTIONS

from .plan_proposal import EDITOR_INSTRUCTIONS, Proposal, apply_proposal, digest, prompt_diff, read_packet


def write_text(directory, name, value):
    with (directory / name).open("x", encoding="utf-8") as output:
        output.write(value)


def write_json(directory, name, value):
    write_text(directory, name, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def run(args):
    root = Path(__file__).resolve().parents[3]
    output = args.output.resolve()
    if (any(output.is_relative_to(p.resolve()) for p in (args.dataset, args.baseline))
            or (output.is_relative_to(root) and not output.is_relative_to(root / ".local")
                and not output.is_relative_to(root / "agent/python/.runtime"))):
        raise ValueError("Use a new private output directory outside source and evaluation inputs")
    packet, audit = read_packet(args.baseline, args.dataset, PLAN_INSTRUCTIONS)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_json(args.output, "input.json", packet)
    write_text(args.output, "editor-instructions.txt", EDITOR_INSTRUCTIONS)
    write_json(args.output, "audit.json", {**audit, "editorInstructionsSha256": digest(EDITOR_INSTRUCTIONS.encode()),
                                          "inputSha256": digest((args.output / "input.json").read_bytes())})
    if not args.generate:
        return "prepared"

    if not packet["failures"]:
        write_json(args.output, "result.json", {"status": "no_editable_failures", "modelCalls": 0})
        return "no_editable_failures"
    settings = replace(Settings.from_env(args.env_file), model=args.model, reasoning_effort=args.effort)
    if not settings.api_key:
        raise ValueError("No API key configured for the proposal model")
    client = ModelClient(settings)
    try:
        data, usage = client.generate(EDITOR_INSTRUCTIONS, packet, Proposal)
    finally:
        if client.client:
            client.client.close()
    # Retain the response even when the proposed target/evidence fails validation.
    write_json(args.output, "response.json", {"model": args.model, "effort": args.effort, "usage": usage, "data": data})
    proposal = Proposal.model_validate(data)
    candidate = apply_proposal(proposal, packet, PLAN_INSTRUCTIONS)
    result = {"status": proposal.action, "modelCalls": 1, "baseSha256": audit["planInstructionsSha256"]}
    if candidate is not None:
        write_text(args.output, "candidate.txt", candidate)
        write_text(args.output, "candidate.diff", prompt_diff(PLAN_INSTRUCTIONS, candidate))
        result["candidateSha256"] = digest(candidate.encode())
    write_json(args.output, "result.json", result)
    return proposal.action


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="Completed real V2 learning run directory")
    parser.add_argument("--dataset", type=Path, required=True, help="Directory containing the frozen learning.json")
    parser.add_argument("--output", type=Path, required=True, help="New private local directory")
    parser.add_argument("--generate", action="store_true", help="Request one proposal from the configured API")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--effort", default="low")
    args = parser.parse_args()
    os.umask(0o077)
    print(run(args))


if __name__ == "__main__":
    main()
