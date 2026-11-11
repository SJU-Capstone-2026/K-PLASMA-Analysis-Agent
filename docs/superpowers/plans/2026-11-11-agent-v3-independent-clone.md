# Agent v3 Independent Clone Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` inline. The user authorized implementation and prefers no unnecessary subagents. Follow the strict-copy spec without adding RAG or rule-based functionality.

**Goal:** Preserve the v2 implementation and make an independent, mechanically verified v3 copy.

**Architecture:** Copy the Python dependency closure of the v2 graph, model gateway, backend port, checkpoint adapter and worker-injected input budget into `kplasma_agent.v3`. Store v2 planning modules under `v3/core`, shared-root dependencies under `v3`, and the graph under `v3/graph.py`; this is copied source, not runtime reuse. Only package imports and explicit graph/version/config identities change.

**Tech Stack:** Existing Python 3.12, LangGraph, Pydantic, pytest, Ruff and mypy; no new dependencies.

**Spec:** `docs/development/agent-v3-team-development-draft.md`

## Global Constraints

- Frozen source: `51d077c9878b635c96da709eb7eb2aefd36699e1`.
- Do not modify v2 implementation files or import its business modules from v3.
- Copy the graph's complete internal import closure, including numerical tools, prompts, validation, model transport, streaming, progress, tracing and persistence.
- Keep plan schema version 2 and answer schema version 1. Graph v3 identity is separate from those versions.
- No RAG, new decision-record rules, ON/OFF implementation, server/DB/UI activation or paid model calls.
- Existing settings values, prompts, calculations, budget limits and error handling remain unchanged except explicitly recorded version identity substitutions.

## Review Focus

- Transitive imports must not silently reintroduce original business modules.
- Version substitutions must not rename legacy answer schema classes or change numerical data.
- Partial output, invalid plans and HITL/resume must preserve existing behavior.
- Independent model/error/schema classes must not accidentally resolve to original classes.
- A passing offline clone must not be reported as an activated web/API v3.

## Task 1: Freeze and test the copy boundary

**Files:** Create `agent/python/tests/v3/test_clone_boundary.py` and `agent/python/src/kplasma_agent/v3/clone-manifest.json`.

**Interfaces:** The manifest maps frozen source paths and SHA-256 values to copied modules and lists the exact allowed identity substitutions. Tests read local source and copied modules; CI does not require historical Git objects or model keys.

- [ ] Write failing checks for the manifest, complete internal import closure, original file hashes and independent graph/model/schema objects.
- [ ] Run the checks and confirm failure because the v3 package does not exist.
- [ ] Copy the 36-module dependency closure from the frozen Git source. Rewrite internal imports and explicit v2 graph/config identities only.
- [ ] Compare every copied file with its transformed frozen source and reject imports outside the new package except standard/third-party libraries.
- [ ] Run the boundary tests and commit only the clone, manifest and checks.

## Task 2: Prove unchanged graph behavior

**Files:** Create `agent/python/tests/v3/test_clone_parity.py`, copy the frozen v2 graph regression tests into `tests/v3`, and copy only the required scripted model helpers into `tests/v3/runtime_helpers.py`.

**Interfaces:** `kplasma_agent.v3.graph.build_v3_graph(models, executions, checkpointer)` has the same call shape as v2. The copied gateway/port use V3 names and the copied answer snapshot carries v3 identity. Test fixtures may be shared; production graph/node/tool implementations may not.

- [ ] Add failing parity checks for concept answers, comparison/search, code rejection/replan, answer rewrite, HITL/checkpoint resume and missing data.
- [ ] Copy existing regression tests with namespace/identity substitutions; do not rewrite their assertions to accommodate changed behavior.
- [ ] Run v2 and v3 scripted suites, compare serialized outputs and call sequences after normalizing graph identity only.
- [ ] Run Ruff and mypy on copied production modules and regression tests.

## Task 3: Record the completed copy

**Files:** Add `docs/development/agent-v3-clone.md`; keep the development-rules PR separate from implementation.

- [ ] Document source SHA, copied files, identity-only changes, commands/results and package entry points.
- [ ] State explicitly that worker/server/DB/UI registration and new tools are not implemented.
- [ ] Verify the frozen source hashes, local links, public-file guard and unchanged v2 source.
- [ ] Commit the copy on a separate feature branch, preserving the user's unrelated untracked plan.

Verification commands use the existing virtual environment: `pytest -c pytest-v2.ini`, `pytest tests/v3`, `ruff check src tests/v3`, and `mypy src`. No paid evaluation is part of this plan.
