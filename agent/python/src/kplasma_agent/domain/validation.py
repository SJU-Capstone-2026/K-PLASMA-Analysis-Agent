"""Replay deterministic results against the pinned source snapshots before publish."""

import json

from .compare import compare_runs
from .forward import lookup_forward
from .reverse import search_reverse


def validate_result(inputs, result, source):
    try:
        # Strict encoding also rejects non-finite floats anywhere in a result.
        actual = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False)
        kind = result.get("kind")
        if kind == "compare_runs":
            if isinstance(source, dict):
                baseline, target = source["baseline"], source["target"]
            else:
                baseline, target = source
            expected = compare_runs(inputs, baseline, target)
        elif kind == "forward_lookup":
            expected = lookup_forward(inputs, source)
        elif kind == "reverse_search":
            expected = search_reverse(inputs, source)
        else:
            return {"valid": False, "errors": [{"code": "UNSUPPORTED_RESULT_KIND"}]}
        equal = actual == json.dumps(expected, sort_keys=True, ensure_ascii=False, allow_nan=False)
        return {"valid": equal, "errors": [] if equal else [{"code": "RESULT_SOURCE_MISMATCH"}]}
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return {"valid": False, "errors": [{"code": "RESULT_VALIDATION_FAILED", "detail": str(error)}]}
