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
