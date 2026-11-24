"""Count local rendered inputs without downloads, truncation or cloud encodings."""

import json
import os

ROLES = {"plan", "answer", "plan_review", "review"}
MAX_INPUT_TOKENS = 16000


def _json(value, *, compact=False):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":") if compact else None)
    except (ValueError, TypeError):
        raise ValueError("LOCAL_INPUT_NOT_JSON") from None


def _role(role):
    if role not in ROLES:
        raise ValueError("LOCAL_BUDGET_ROLE_INVALID")


def _check_count(tokens, limit):
    if type(tokens) is not int or tokens <= 0:
        raise ValueError("LOCAL_TOKEN_COUNT_INVALID")
    if tokens > limit:
        raise ValueError("v2_localLLM input budget exceeded")


def check_payload(payload, role, *, count=None):
    """Retain the scripted counter seam; real workers use make_input_guard."""
    _role(role)
    if count is None:
        raise ValueError("LOCAL_TOKEN_COUNTER_REQUIRED")
    body = _json(payload, compact=True)
    estimate = (len(count(body)) * 11 + 9) // 10 + 1024
    override = {"plan": "AGENT_V2_LOCAL_LLM_PLAN_CONTEXT_TOKENS",
                "plan_review": "AGENT_V2_LOCAL_LLM_PLAN_CONTEXT_TOKENS",
                "answer": "AGENT_V2_LOCAL_LLM_ANSWER_CONTEXT_TOKENS"}.get(role)
    context_limit = int(os.getenv(override, "1050000")) if override else 1050000
    _check_count(estimate, min(MAX_INPUT_TOKENS, context_limit - 6000))


def _context_limit(value):
    if type(value) is not int or value <= 6000:
        raise ValueError("LOCAL_CONTEXT_INVALID")
    return min(MAX_INPUT_TOKENS, value - 6000)


def validate_d1_groups(counted, names, group_size, independent_batch_size=1):
    if (not isinstance(counted, dict) or counted.get("schema_version") != 1
            or group_size != 1 or independent_batch_size != 1
            or counted.get("truncated") is not False or counted.get("input_limit") != MAX_INPUT_TOKENS
            or counted.get("group_size") != group_size
            or counted.get("independent_batch_size", 1) != independent_batch_size
            or counted.get("policy") != "sorted-greedy-full-pack-v1"):
        raise ValueError("LOCAL_TOKEN_COUNT_INVALID")
    groups, counts = counted.get("group_question_ids"), counted.get("group_counts")
    if (not isinstance(groups, list) or not isinstance(counts, list) or not groups or len(groups) != len(counts)
            or any(not isinstance(ids, list) or not 1 <= len(ids) <= group_size
                   or any(not isinstance(name, str) for name in ids) for ids in groups)):
        raise ValueError("LOCAL_TOKEN_COUNT_INVALID")
    flat = [name for ids in groups for name in ids]
    if flat != sorted(names) or len(flat) != len(set(flat)):
        raise ValueError("LOCAL_TOKEN_COUNT_INVALID")
    for count in counts:
        _check_count(count, MAX_INPUT_TOKENS)
    return counts


def d1_count_values(counted):
    return counted["group_counts"] if isinstance(counted, dict) else counted


def make_d1_counter(settings, client):
    """Use the authenticated, origin-locked native tokenizer, never inference or a cloud API."""
    import httpx
    from .decisions import native_request

    def count(payload, role):
        questions = payload["questions"]
        if isinstance(questions, dict):
            questions = [{"name": name, "type": "choice", "instructions": instructions,
                          "choices": [{"value": key, "description": value} for key, value in choices.items()]}
                         for name, (instructions, choices) in questions.items()]
        native = native_request({"input": [{"role": "user", "content": [
            {"type": "input_json", "data": payload["input"]}]}], "questions": questions})
        if settings.d1_engine != "mlx":
            raise ValueError("LOCAL_D1_ENGINE_INVALID")
        response = client.post(httpx.URL(settings.d1_url).copy_with(path="/v1/count"), json=native)
        response.raise_for_status()
        counted = response.json()
        validate_d1_groups(counted, native["questions"], settings.d1_group_size,
                           settings.d1_independent_batch_size)
        return counted

    return count


def make_qwen_counter(settings, client):
    """Render and tokenize with the same pinned server, including native tools and thinking."""
    from dataclasses import replace
    import httpx

    def count(payload, role):
        if role not in {"plan", "answer"}:
            raise ValueError("LOCAL_BUDGET_ROLE_INVALID")
        selected = settings if role == "plan" else replace(settings, reasoning_effort="none")
        options = selected.generation_options()
        body = {**options, "messages": [
            {"role": "system", "content": payload.get("instructions", "")},
            {"role": "user", "content": payload["input"] if isinstance(payload["input"], str)
             else _json(payload["input"])}]}
        body.update(body.pop("extra_body"))
        if "tools" in payload:
            body.update(tools=[tool if "function" in tool else {"type": "function", "function": {
                key: value for key, value in tool.items() if key != "type"}} for tool in payload["tools"]],
                tool_choice="required", parallel_tool_calls=False)
        if "schema" in payload:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "local_result", "strict": True, "schema": payload["schema"]}}
        response = client.post(httpx.URL(settings.model_url).copy_with(path="/apply-template"), json=body)
        response.raise_for_status()
        prompt = response.json().get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("LOCAL_TOKEN_TEMPLATE_UNSUPPORTED")
        response = client.post(httpx.URL(settings.model_url).copy_with(path="/tokenize"),
                               json={"content": prompt, "add_special": False, "parse_special": True})
        response.raise_for_status()
        tokens = response.json().get("tokens")
        if not isinstance(tokens, list) or not tokens or any(type(t) is not int or t < 0 for t in tokens):
            raise ValueError("LOCAL_TOKEN_COUNT_INVALID")
        return len(tokens)

    return count


def make_input_guard(settings, *, qwen_count=None, d1_count=None, prepare=None):
    """Bind counters to one profile; native providers count the entire rendered input.

    qwen_count(payload, role) returns an integer including template/tools/schema.
    d1_count(payload, role) returns native MLX counts and complete singleton check IDs.
    """
    def guard(payload, role):
        _role(role)
        _json(payload)
        if prepare is not None:
            prepare(role)
        if role in {"plan_review", "review"}:
            if settings.d1_engine != "mlx":
                raise ValueError("LOCAL_D1_ENGINE_INVALID")
            if d1_count is None:
                raise ValueError("LOCAL_D1_TOKEN_COUNTER_UNAVAILABLE")
            try:
                counted = d1_count(payload, role)
            except Exception:
                raise ValueError("LOCAL_TOKEN_COUNTER_UNAVAILABLE") from None
            questions = payload.get("questions")
            if not isinstance(questions, (dict, list)) or not questions:
                raise ValueError("LOCAL_TOKEN_COUNT_INVALID")
            names = questions if isinstance(questions, dict) else [q["name"] for q in questions]
            counts = validate_d1_groups(counted, names, settings.d1_group_size,
                                        settings.d1_independent_batch_size)
            if type(settings.d1_context_tokens) is not int or settings.d1_context_tokens <= 0:
                raise ValueError("LOCAL_CONTEXT_INVALID")
            # Native decisions emit no generation tokens; the measured 24GB profile caps full inputs.
            limit = min(MAX_INPUT_TOKENS, settings.d1_context_tokens)
            for value in (settings.d1_batch_tokens, settings.d1_ubatch_tokens):
                if type(value) is not int or value <= 0:
                    raise ValueError("LOCAL_CONTEXT_INVALID")
                limit = min(limit, value)
            for count in counts:
                _check_count(count, limit)
            return
        if qwen_count is None:
            raise ValueError("LOCAL_TOKEN_COUNTER_UNAVAILABLE")
        try:
            tokens = qwen_count(payload, role)
        except Exception:
            raise ValueError("LOCAL_TOKEN_COUNTER_UNAVAILABLE") from None
        _check_count(tokens, _context_limit(settings.context_tokens))

    return guard
