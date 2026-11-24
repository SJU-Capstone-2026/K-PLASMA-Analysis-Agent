# Agent evaluation

## v2 plan meaning and end-to-end evaluation

For the two manual experiments, see the [v2 evaluation runbook](../../../docs/development/agent-v2-evaluations.md):
fixed-plan Decisions 80 requests and the private frozen bank's 40 browser + 40 API questions.
`npm run eval:agent:local -- --bundle /path/to/bundle --output /tmp/new-plan` performs
offline preflight only; adding `--live --connection /path/to/connection.json --env-file /path/to/eval.env`
runs the actual app. Supply the external frozen oracle and a dedicated local app;
the runner owns its worker and browser, keeps results separate by mode, and never adds paid replacements.
The automatic grade is provisional until flagged answers and visual artifacts are independently reviewed.

All future live Agent evaluations (browser, API and in-memory graph) must keep
plan meaning Decisions enabled. Check both model settings and graph state for
`plan_review_enabled=true` before execution; stop if either is disabled.
`AGENT_V2_PLAN_REVIEW_ENABLED` defaults to `true`. `run_v2 --live` rejects both
`--plan-review off` and an environment setting that disables review. The existing
maximum of two replans per request, applicable answer review and one answer
rewrite remain enabled. Scripted offline unit tests may still exercise the off
path without calling a live model.

Report initial-plan passes, Decisions issues, and final passes/failures after
`REPLAN` separately. A repaired final pass is not an initial-plan pass. Do not
add a separate paid experiment to the evaluation count requested by the user.
The fixed-plan Decisions experiment below is separate from live Agent
end-to-end evaluations and runs only when explicitly requested.

`plan_review_cases.py` contains 14 labelled correct/incorrect plan pairs,
all on artificial identities. Both variants pass the code validator. The default
matrix preserves the original 13 pairs × 3 repeats (78 requests), then adds P14's
correct and incorrect plans once each: **80 Decisions requests, 40 correct plans
and 40 incorrect plans**. This is 28 distinct plans; the historical repetitions
remain. P14 checks that an unrequested pressure filter is rejected. `--repeats`
applies to P01–P13; P14 is included once even when selected with `--case P14`.
No planner is called in this experiment. Historical 78-request measurements
remain unchanged; adding two cases does not establish an 80/80 live result.
The grader reports false acceptance, false rejection, unclear and API failure
separately. Its labels never come from Decisions itself. Synthetic probes such
as 9999.5 distinguish a range from equality even if both return no real Runs.

The **paid 80-request evaluation is local and manual only**. It is not a GitHub
Actions job, a PR gate or an automatic evaluation. CI keeps offline unit tests
of the evaluator; those tests do not call Decisions.

Run this explicitly from the repository root when ready to make paid API calls:

```sh
npm run eval:decisions:local -- --env-file /path/to/local.env --output /tmp/kplasma-decisions80-live
```

Use a new output directory for each experiment. The env file supplies
`OPENAI_API_KEY` and optional `AGENT_V2_DECISIONS_MODEL` / `AGENT_V2_DECISIONS_BASE_URL`.
The command calls Decisions 80 times with the default configuration; no backend,
database, browser or planner is needed. Results stay local in `results.jsonl`
and `summary.json`. The command is never invoked by the CI workflow.

To inspect the matrix without paid calls, run the first command below from
`agent/python`. The remaining commands explicitly call live models.

```sh
PYTHONPATH=src:. .venv/bin/python -m evals.run_plan_review --output /private/tmp/kplasma-plan-review
PYTHONPATH=src:. .venv/bin/python -m evals.run_plan_review --live --env-file /path/to/local.env --output /private/tmp/kplasma-plan-review
PYTHONPATH=src:. .venv/bin/python -m evals.run_v2 --live --plan-review on --output /private/tmp/kplasma-v2-live
```

The existing v2 graph harness retains initial provider output, accepted plan
revisions, each plan verdict, final execution/answer failures, bounded replan
count, role call counts and elapsed provider times. The live CLI explicitly
sets review on in both the gateway settings and graph state. Offline off-path
tests record SKIPPED rather than PASS. Different live planner outputs mean
before/after graph runs alone cannot isolate reviewer quality. Browser/DB tests
exercise persistence and HITL independently of the in-memory harness.

Model failures retain distinct timeout, connection, HTTP status/rate-limit and
stream/API error codes. `MODEL_OUTPUT_TRUNCATED` means the provider explicitly
reported `max_output_tokens`; content filtering, failed responses, unspecified
incomplete responses and a stream without a terminal event use separate codes.
Only fixed codes enter stored outcomes; provider error messages and unknown
reason strings are discarded. Historical `MODEL_OUTPUT_TRUNCATED` records from
before this distinction cannot establish an output-token limit retroactively.
