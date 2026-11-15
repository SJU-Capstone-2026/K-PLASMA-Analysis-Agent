"""Numerical planner diagnostics; optional CPU tokenization never wakes a model."""

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import time


@lru_cache(maxsize=2)
def _tokenizer(path, size, modified):
    from tokenizers import Tokenizer
    data = Path(path).read_bytes()
    return Tokenizer.from_str(data.decode()), hashlib.sha256(data).hexdigest()


def prepare_tokenizer(path):
    started = time.monotonic()
    if path:
        try:
            file = Path(path)
            stat = file.stat()
            _tokenizer(str(file.resolve()), stat.st_size, stat.st_mtime_ns)
        except Exception:
            pass
    return time.monotonic() - started


def planner_diagnostics(message, calls, usage, timings, finish_reason, tokenizer_path=""):
    started = time.monotonic()
    thought = getattr(message, "reasoning_content", None)
    thought = thought if isinstance(thought, str) else ""
    arguments = [call.function.arguments for call in calls]
    steps = None
    if len(arguments) == 1:
        try:
            plan = json.loads(arguments[0])
            if isinstance(plan, dict) and isinstance(plan.get("steps"), list):
                steps = len(plan["steps"])
        except (ValueError, TypeError):
            pass
    detail = getattr(usage, "completion_tokens_details", None)
    exact = getattr(detail, "reasoning_tokens", None)
    total = getattr(usage, "completion_tokens", None)
    if type(exact) is not int or exact < 0 or type(total) is not int or exact > total:
        exact = None
    result = {"reasoningCharacters": len(thought), "argumentCharacters": sum(map(len, arguments)),
              "planStepCount": steps, "reasoningTokens": exact, "argumentTokens": None,
              "tokenCountSource": "provider" if exact is not None else "unavailable",
              "retokenizedReasoningTokens": None, "retokenizedArgumentTokens": None,
              "tokenizerSha256": None, "finishReason": finish_reason,
              "generationTokensPerSecond": None}
    count, elapsed = timings.get("predicted_n"), timings.get("predicted_ms")
    if (type(count) in {int, float} and type(elapsed) in {int, float}
            and math.isfinite(count) and math.isfinite(elapsed) and count > 0 and elapsed > 0):
        result["generationTokensPerSecond"] = count * 1000 / elapsed
    if tokenizer_path:
        try:
            path = Path(tokenizer_path)
            stat = path.stat()
            tokenizer, digest = _tokenizer(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
            result.update(retokenizedReasoningTokens=len(tokenizer.encode(thought, add_special_tokens=False).ids),
                          retokenizedArgumentTokens=sum(len(tokenizer.encode(x, add_special_tokens=False).ids)
                                                        for x in arguments), tokenizerSha256=digest)
            if exact is None:
                result["tokenCountSource"] = "retokenized_estimate"
        except Exception:
            # Diagnostics must not turn a valid native plan into a model failure.
            pass
    result["diagnosticSeconds"] = time.monotonic() - started
    return result
