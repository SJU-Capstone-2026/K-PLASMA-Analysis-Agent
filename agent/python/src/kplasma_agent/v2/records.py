"""Decide how a v2 decision_records step applies the prototype rule before it runs.

The decision follows Agent v1 (`graphs/v1.py` route_records): the original question, never the
model, decides whether Runs are excluded and with which threshold. Notes are never read here.
"""

from ..domain import decision_records as records
from .bindings import BlockedInput


def record_plan(inputs, question, confirmed_threshold=None, *, from_result=False):
    """Return the reserved inputs: action, threshold and an optional notice code.

    Raises BlockedInput("record_threshold") when the user must choose an ambiguous threshold.
    """
    parsed = records.parse_request(question)
    # An exclusion needs both the model's intent and the prototype's wording rule.
    exclude = inputs["action"] == "exclude" and bool(parsed and parsed["exclude"])
    threshold = None
    notice = None
    if exclude:
        threshold = parsed["threshold"] if confirmed_threshold is None else confirmed_threshold
        if not records.mentions_cost(question):
            notice = "COST_ONLY"
        elif threshold is not None and not records.valid_threshold(threshold):
            notice = "THRESHOLD"
    if notice is None and not inputs["runs"] and not from_result:
        notice = "SCOPE"
    if notice is None and exclude:
        if threshold is None:
            raise BlockedInput("record_threshold")
        return {**inputs, "action": "exclude", "threshold": int(threshold), "notice": None}
    return {**inputs, "action": "exclude" if exclude else "view", "threshold": None, "notice": notice}
