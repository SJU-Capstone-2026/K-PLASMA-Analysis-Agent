# Synthetic live interpretation evaluation

The 140 cases cover 100 forward lookup/reverse search/Run comparison requests and
40 change/concept explanation requests. They include exact numbers and units,
strict bounds, explicit hard versus soft ranges, goal priority, missing inputs,
context continuation, Korean/English names, spelling variants, and unsupported
scope. All numbers and Run IDs are artificial query inputs, not physical results.

From `agent/python`:

```sh
PYTHONPATH=src:. .venv/bin/python -m pytest evals/test_harness.py -q
PYTHONPATH=src:. .venv/bin/python -m evals.run_interpretation --dry-run --repeat 3
PYTHONPATH=src:. .venv/bin/python -m evals.run_interpretation --repeat 3 --concurrency 4
```

The live command uses `OPENAI_API_KEY` from the local environment or repository
`.env`, `gpt-5.6-luna`, and reasoning effort `none`. It performs 420 independent
interpretation requests. Use `--case forward-01`, `--category reverse`, or
`--limit 5 --repeat 1` for a smaller explicit run. Concurrency cannot exceed four.
The evaluation harness does not silently retry errors; each API failure remains
a failed attempt in the aggregate.

`judge.py` checks operation kind, required values/units/selectors, ordered goals
and metrics, complete constraint membership, fields that must remain absent,
and whether the answer can execute or requires clarification. A generic refusal
or unnecessary question cannot pass a normal executable case. The numerical
grounding gate rejects invented or swapped numeric slots and unmentioned IDs.
The aggregate also reports failed answers that the checked decision rules could
otherwise dispatch. All failures still require review: zero such dispatches
does not certify the absence of every possible unsafe or incorrect interpretation.

Raw synthetic questions, model outputs and detailed judgments are saved only in
the Git-ignored `.runtime/evals/<UTC timestamp>/attempts.jsonl`. An aggregate
`summary.json` is written beside it, and only aggregate progress is printed.
Never move raw runtime output or real user/Run data into committed fixtures.

This suite evaluates interpretation and routing, **not** the physical truth of
generated explanations or production end-to-end recovery. Use the graph/domain
tests and live five-tool scenarios for those execution paths, and have a domain
expert separately assess scientific explanation quality. A passing machine
score must not be described as a scientific correctness guarantee.

## Explanation generation checks

```sh
PYTHONPATH=src:. .venv/bin/python -m pytest evals/test_explanation_harness.py -q
PYTHONPATH=src:. .venv/bin/python -m evals.run_explanations --dry-run --repeat 3
PYTHONPATH=src:. .venv/bin/python -m evals.run_explanations --repeat 3 --concurrency 4
```

The separate explanation suite has 20 distinct change packets and 20 concept
packets. Change cases include a single changed condition, multiple changed
conditions, the same recorded conditions, incomplete conditions, unavailable
metrics and a zero baseline. Concept cases cover definitions, differences and
relationships. Only qualitative packets reach the model: no Run IDs, scalar
measurements, deltas or percentages. An offline test verifies that restriction.

With three repeats, 120 paths are checked. Nine paths have no observed metric
change or no comparable metrics and must return a code-generated limited answer
without calling the model. The other 111 paths make live generation requests,
with at most one semantic repair, matching the graph. The aggregate explicitly
reports actual model calls, repairs and limited responses. Successful validation
means the schema and implemented conservative guards passed; a domain expert
must separately review the scientific interpretation. Output remains under
the ignored `.runtime/evals/explanations/` directory.
