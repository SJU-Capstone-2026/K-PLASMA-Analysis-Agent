"""Preflight the full provider payload. The provider bills its own token count."""

from functools import lru_cache
import json
import os

import tiktoken


@lru_cache(maxsize=1)
def _encoding():
    return tiktoken.get_encoding("o200k_base")


def check_payload(payload, role, *, count=None):
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    counter = count if count is not None else _encoding().encode_ordinary
    estimate = (len(counter(body)) * 11 + 9) // 10 + 1024
    override = {"plan": "AGENT_V2_PLAN_CONTEXT_TOKENS", "answer": "AGENT_V2_ANSWER_CONTEXT_TOKENS"}.get(role)
    context_limit = int(os.getenv(override, "1050000")) if override else 1050000
    if estimate > min(24000, context_limit - 6000):
        raise ValueError("v2 input budget exceeded")
