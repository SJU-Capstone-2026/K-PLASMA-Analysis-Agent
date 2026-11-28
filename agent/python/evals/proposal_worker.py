"""Dedicated evaluation process: bind the reviewed candidate to both initial and revised plans."""

import argparse
import json
import os
from pathlib import Path

from kplasma_agent import tracing, worker
from kplasma_agent.config import Settings
from kplasma_agent.model_client import ModelError
from kplasma_agent.v2 import model_gateway

from .plan_proposal import digest, load_candidate


class CandidateGateway(model_gateway.V2ModelGateway):
    def submit_plan(self, context):
        fingerprint = digest(model_gateway.PLAN_INSTRUCTIONS.encode())
        try:
            data, usage = super().submit_plan(context)
        except (ModelError, ValueError, TypeError) as error:
            error.usage = {**(getattr(error, "usage", None) or {}), "planInstructionsSha256": fingerprint}
            raise
        return data, {**(usage or {}), "planInstructionsSha256": fingerprint}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    candidate = load_candidate(args.proposal, model_gateway.PLAN_INSTRUCTIONS)
    actual = digest(candidate.encode())
    if args.sha256 != actual:
        raise ValueError("Evaluator and worker prompt hashes differ")
    # submit_plan reads this module binding on every invocation in this process.
    model_gateway.PLAN_INSTRUCTIONS = candidate
    worker.V2ModelGateway = CandidateGateway
    pending = args.receipt.with_suffix(".tmp")
    with pending.open("x") as output:
        json.dump({"pid": os.getpid(), "sha256": actual}, output)
    pending.replace(args.receipt)
    try:
        worker.serve(Settings.from_env(args.env_file))
    finally:
        tracing.shutdown()


if __name__ == "__main__":
    main()
