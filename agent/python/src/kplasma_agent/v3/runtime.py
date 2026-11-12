"""Immutable request feature selection for the independently owned V3 runtime."""
import hashlib
import json


def normalize_mode(options=None):
    options = {} if options is None else dict(options)
    if set(options) - {"rulesEnabled", "ragEnabled", "configDigest"}:
        raise ValueError("INVALID_V3_OPTIONS")
    mode = {key: options.get(key, False) for key in ("rulesEnabled", "ragEnabled")}
    if any(type(value) is not bool for value in mode.values()):
        raise ValueError("INVALID_V3_OPTIONS")
    raw = json.dumps(mode, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if "configDigest" in options and options["configDigest"] != digest:
        raise ValueError("INVALID_V3_OPTIONS_DIGEST")
    return {**mode, "configDigest": digest}


def allowed_record_actions(mode):
    mode = normalize_mode(mode)
    return (["search"] if mode["ragEnabled"] else []) + (["cost_exclusion"] if mode["rulesEnabled"] else [])


def require_action(mode, action):
    if action not in allowed_record_actions(mode):
        raise ValueError("V3_FEATURE_DISABLED")
