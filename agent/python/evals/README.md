# Native Tool Calling and answer evaluation

The registry contains four native functions: `forward_lookup`, `reverse_search`,
`compare_runs`, `generate_answer`. The 141 synthetic selection cases retain the
original user wording while judging native names and arguments. They cover units,
misspellings, hard/soft ranges, sort priority, missing inputs, explicit references,
comparison intent and unrestricted general concepts. Query numbers and Run IDs
are artificial inputs, not physical results.

From `agent/python`:

```sh
PYTHONPATH=src:. .venv/bin/python -m pytest tests evals -q
PYTHONPATH=src:. .venv/bin/python -m evals.run_interpretation --dry-run --repeat 3
PYTHONPATH=src:. .venv/bin/python -m evals.run_interpretation --acceptance --repeat 3
PYTHONPATH=src:. .venv/bin/python -m evals.run_interpretation --repeat 3 --concurrency 4
PYTHONPATH=src:. .venv/bin/python -m evals.run_acceptance --repeat 3 --concurrency 3
```

Live commands read `OPENAI_API_KEY` from the environment or repository `.env` and
use `gpt-5.6-luna` with reasoning `none`. The full selection suite has 423 attempts.
`--acceptance` selects 18 core scenarios (54 attempts with three repeats), including
four Korean watt spelling variants. Selection also supports `--case forward-01`,
`--category reverse`, or `--limit 5 --repeat 1` for a smaller run.

`judge.py` checks the native function name, required argument values/units,
ordered goals and metrics, constraint membership, absent fields, explicit alias
membership and expected clarification. Numerical grounding independently checks
mentioned values and slots. A missing unit must remain null; a pure sort needs
no unit. Between filtering cannot silently become an out-of-range soft target.

`run_acceptance` executes the actual graph, including a synthetic five-Run catalog,
trusted picker/options replies and text unit clarification. It checks exact Run
inventories, original-question preservation, general-answer catalog bypass and
completed schema-2 snapshots. Its recorder counts **all** provider requests,
including clarification and repair, rather than only the last call per node.
Phoenix is enabled when configured. This graph harness uses an in-memory saver;
HTTP/PostgreSQL and process-loss coverage come from the browser/restart suites.

## Answer generation checks

```sh
PYTHONPATH=src:. .venv/bin/python -m evals.run_explanations --dry-run --repeat 3
PYTHONPATH=src:. .venv/bin/python -m evals.run_explanations --repeat 3 --concurrency 4
```

This separate 40-case suite contains 20 comparison questions with code-generated
observations and 20 unrestricted general questions. Comparison drafts select
known observation IDs and supply qualitative interpretations, assumptions and
limits. Detectable numeric restatements are rejected with at most one repair.
General answers receive the original question without a concept enum or count
gate, and may use illustrative numbers and formulas. The runtime graph additionally
constrains observation IDs in the provider schema and preserves the native
function-call roundtrip. The separate draft suite is not a substitute for that
full graph test.

## Evidence and limits

Detailed synthetic questions, answers, failures, judgments and token usage remain
in Git-ignored `.runtime/evals/` or `.runtime/full-graph-evals/` directories. Do not
commit raw runtime output, actual user data, actual Run payloads or credentials.
API failures remain visible; graph retries and repairs are bounded and counted.

These scores establish routing, wire contracts and implemented grounding checks.
They do **not** certify scientific truth, identify every semantic contradiction or
guarantee future model outputs. A domain expert should review causal explanations
separately. General answers are LLM knowledge, with no reviewed-literature/RAG
claim. See [implementation verification](../../../docs/verification/agent-v1-tool-calling-and-answers.md)
for the exercised HTTP, UI, database and recovery scope.

## v2 plan meaning and end-to-end evaluation

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
