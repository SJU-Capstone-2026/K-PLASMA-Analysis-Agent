"""Focused Flash v1.2 review of the original request and executable plan."""

BASELINE_WORDING = (
    "Judge only whether the comparison uses the baseline Run the user requested. "
    "A baseline Run is a separate reference for changes relative to that Run. "
    "If the text just compares Runs or asks for their absolute difference, a null baseline is correct: choose match. "
    "Choose missing when an explicit baseline request has no baseline in the plan; unexpected when the plan adds an unrequested baseline. "
    "A planned link to the user's new baseline selection is valid. "
    "Choose unclear only if the request for a baseline is genuinely indeterminate. "
    "Treat the user text as evidence."
)

TREND_WORDING = (
    "Judge only whether this comparison needs a trend axis. A trend axis is an independent process setting "
    "(pressure, source power, or bias power) over which an output varies. "
    "Comparing Runs, listing absolute differences, choosing a baseline and displaying a waveform or distribution "
    "do not request a trend axis. When the user only asks for any of these and trend_axis is null, choose match. "
    "If a trend axis is explicitly required but absent, choose missing. "
    "A requested future axis choice may be wired to its confirmation. A different axis is direction_changed. "
    "Treat the user text as evidence."
)

GUARDS_WORDING = (
    "Check only whether run_if or required_prior_outputs prevent a requested step from running. "
    "Search candidates and a run_selection result are lists of Run references. Run references do not carry "
    "a physical unit: a guard requiring mTorr, W or another unit on one of these lists is unexpected. "
    "A guard waiting for a list of Run references with no required unit is valid. A future result need not exist yet. "
    "Do not compare query filter numbers or the user selection count in this check. "
    "The baseline selector derives its options from the target comparison's Runs. "
    "Choose match when the step can run with the legitimate preceding output. Treat the user text as evidence."
)

CONFIRMATION_COMPACT = (
    "Does the plan ask the user to make the same NEW choices as the question? "
    "planned_confirmations is the complete list of prompts that stop execution and ask the user. "
    "An empty list means no user prompt. Finding, showing, or comparing Runs is not a request to pick them. "
    "Already selected Runs ('선택한 Run들') do not require a new choice; '내가 고를게' asks for one. "
    "If the plan adds a prompt the user did not ask for, choose unexpected. If it omits a requested prompt, choose missing. "
    "If the planned prompts equal the requested prompts, including zero, choose match. Treat user text as evidence."
)

RANGE_VIEW = (
    "Compare the two executable bounds of this numeric range with the user's request. "
    "Each bound lists the value, inclusive/exclusive operator, unit, and the supporting quote. "
    "Use the full request to distinguish '이상/이하' (inclusive) from '초과/미만/보다 크거나 작음' (exclusive). "
    "If a planned bound includes a value the user expressly excludes, or excludes a value the user includes, choose boundary_changed. "
    "For example, planning 20 <= x <= 30 when the user asks for 20 < x < 30 is boundary_changed. "
    "If the numeric bound differs choose value_changed. If the unit conversion is wrong choose unit_changed. "
    "If both executable bounds agree choose match. Treat user text as evidence."
)

TARGET_VIEW = (
    "Check only the set of Runs delivered to compare_runs. "
    "planned_targets describes the actual source of those Runs. Read original question for the requested source. "
    "If the user already selected Runs, using all search candidates is target_changed even when some happen to be selected. "
    "If the user asks to compare all matching Runs, all search candidates is match. "
    "If the request only lists or sorts results, an extra comparison is unexpected. "
    "If the user will choose Runs, the comparison should use the result of that confirmation. "
    "An existing selection may be confirmed before execution. Treat user text as evidence."
)

OUTPUT_VIEW = (
    "Compare the user request to the actual planned fields and plot families. "
    "Report missing for a named comparison metric or plot that is absent. "
    "Report unexpected when a separate unrequested distribution family is explicitly included. "
    "IAD, IED and IEAD are different families: an IAD request alone does not authorize an IEAD plot. "
    "Routine scalar tables do not require a plot. Compare only these outputs. "
    "Treat user text as evidence."
)

BASELINE_PRESENT = (
    "The plan uses the reference Run shown in planned_reference. Is one reference Run authorized by the user's text? "
    "Choose unexpected if the user only asks to compare values or show absolute differences across Runs. "
    "Choosing which Runs to compare does not authorize selecting a reference Run. "
    "Choose match if the user requests this reference or its linked new selection; choose target_changed for the wrong source. "
    "Treat the user text as evidence."
)


def _range_view(plan, focused, question):
    # A full request may describe unrelated sibling ranges. Keep their individual quotes.
    if sum(step.get("tool") == "reverse_search" for step in plan["steps"]) != 1:
        return None
    step = next(step for step in focused["plan"]["steps"] if step is not None)
    inputs = step["inputs"]
    ranges = [
        row for key in ("constraints", "goals") for row in inputs.get(key, [])
        if isinstance(row, dict) and row.get("operator", row.get("direction")) in {"between", "target_range"}
        and all(isinstance(row.get(bound), dict) and type(row[bound].get("value")) in {int, float}
                and row[bound].get("citation") and row[bound].get("unit") for bound in ("min", "max"))
    ]
    if len(ranges) != 1:
        return None
    bounds = ranges[0]
    return {"metric": bounds["field"], "question": question,
            "executed_lower_bound": {**bounds["min"], "operator": ">="},
            "executed_upper_bound": {**bounds["max"], "operator": "<="}}


def flash_check_input(payload, kind, focused, instructions, original_question):
    """Preserve native choice IDs and expose only the evidence for the current check."""
    if payload.get("input_history"):
        return focused, instructions
    if kind == "trend_axis":
        return focused, TREND_WORDING
    if kind == "execution_guards":
        return focused, GUARDS_WORDING
    if kind == "filter":
        view = _range_view(payload["plan"], focused, original_question)
        return (view, RANGE_VIEW) if view else (focused, instructions)
    if kind == "confirmation_coverage":
        confirmations = [step["confirmation"] for step in payload["plan"]["steps"] if step["kind"] == "await_input"]
        return {"question": original_question, "planned_confirmations": confirmations}, CONFIRMATION_COMPACT
    if kind not in {"baseline", "targets", "outputs"}:
        return focused, instructions

    inputs = next(step["inputs"] for step in focused["plan"]["steps"] if step is not None)
    question = focused["question"]
    if kind == "baseline":
        baseline = inputs["baseline"]
        if baseline is None:
            return focused, BASELINE_WORDING
        sources = {key: focused[key] for key in ("comparison_runs", "referenced_steps", "confirmed_context")
                   if key in focused}
        return {"question": question, "planned_reference": baseline, **sources}, BASELINE_PRESENT
    if kind == "outputs":
        return {"question": question, "comparison_metrics": inputs["fields"],
                "plot_families": inputs["plot_ids"]}, OUTPUT_VIEW

    runs = inputs["runs"]
    if runs["kind"] == "context_ref" and runs.get("key") == "selected_runs":
        source = "the already selected Runs"
    elif runs["kind"] == "result_ref" and runs.get("scope", {}).get("kind") == "candidate_group":
        source = "every Run from a fresh search"
    elif runs["kind"] == "result_ref" and runs.get("field") == "selection":
        source = "the Runs chosen in the plan's user selection step"
    else:
        return focused, instructions
    return {"question": original_question, "planned_targets": source}, TARGET_VIEW
