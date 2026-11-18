"""Local Qwen adapters. Credentials and provider error bodies never enter state."""

import copy
import json
import math
import httpx
from openai import OpenAI, APIError, APIConnectionError, APIStatusError, APITimeoutError
from . import tracing
from .network import local_http_client, validate_endpoint


class ModelError(RuntimeError):
    def __init__(self, code, retryable=False, *, usage=None, response=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.usage = usage
        self.response = response_payload(response) if response is not None else None


def response_payload(response):
    """Keep generated output and usage, excluding arbitrary provider error messages."""
    raw = response.model_dump(mode="json") if hasattr(response, "model_dump") else dict(response)
    if raw.get("error"):
        raw["error"] = {"code": raw["error"].get("code")}
    if raw.get("incomplete_details"):
        reason = raw["incomplete_details"].get("reason")
        raw["incomplete_details"] = {"reason": reason if reason in {"max_output_tokens", "content_filter"} else "unknown"}
    return tracing._scrub(raw)


def strict_schema(model):
    schema = copy.deepcopy(model.model_json_schema())

    # Schema container dictionaries must be visited once, without revisiting transformed properties.
    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        node.pop("default", None)
        node.pop("discriminator", None)
        if "oneOf" in node:
            node["anyOf"] = node.pop("oneOf")
        if "properties" in node:
            required = set(node.get("required", []))
            for key, value in list(node["properties"].items()):
                if key not in required:
                    node["properties"][key] = {"anyOf": [value, {"type": "null"}]}
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
        for key, value in node.items():
            if key in ("properties", "$defs"):
                for item in value.values():
                    walk(item)
            else:
                walk(value)

    walk(schema)
    return schema


def omit_nulls(value):
    if isinstance(value, dict):
        return {k: omit_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [omit_nulls(v) for v in value]
    return value


class ModelClient:
    def __init__(self, settings, http_client=None):
        self.settings = settings
        validate_endpoint(settings.model_url)
        if http_client is not None and (http_client.trust_env or http_client.follow_redirects):
            raise ValueError("LOCAL_HTTP_CLIENT_UNSAFE")
        self.client = (
            OpenAI(api_key=settings.api_key, base_url=settings.model_url, timeout=settings.timeout, max_retries=0,
                   http_client=http_client or local_http_client(settings.model_url, timeout=settings.timeout))
            if settings.api_key
            else None
        )

    def _tool_request(self, instructions, input_value, tool, observation):
        if self.client is None:
            raise ModelError("MODEL_NOT_CONFIGURED")
        params = {"model": self.settings.model, "max_tokens": 6000, "store": False,
                  "reasoning_effort": self.settings.reasoning_effort,
                  "messages": [{"role": "system", "content": instructions},
                               {"role": "user", "content": input_value}],
                  "tools": [{"type": "function", "function": {k: v for k, v in tool.items() if k != "type"}}],
                  "tool_choice": "required", "parallel_tool_calls": False}
        params.update(self.settings.generation_options())
        observation.json_attribute("llm.invocation_parameters", params)
        try:
            result = self.client.chat.completions.create(**params)
        except (APITimeoutError, httpx.TimeoutException):
            raise ModelError("MODEL_TIMEOUT", retryable=True) from None
        except (APIStatusError, httpx.HTTPStatusError) as error:
            status = error.response.status_code
            raise ModelError("MODEL_RATE_LIMITED" if status == 429 else f"MODEL_HTTP_{status}",
                             retryable=status == 429 or status >= 500) from None
        except (APIConnectionError, httpx.HTTPError):
            raise ModelError("MODEL_CONNECTION", retryable=True) from None
        except APIError:
            raise ModelError("MODEL_API_ERROR") from None
        if getattr(result, "error", None):
            raise ModelError("MODEL_RESPONSE_FAILED")
        usage = result.usage
        if usage and any(type(value) is not int or value < 0 for value in (
                usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)):
            raise ModelError("MODEL_OUTPUT_INVALID")
        metadata = {"model": result.model, "reasoningEffort": self.settings.reasoning_effort,
                    "inputTokens": usage.prompt_tokens if usage else None,
                    "outputTokens": usage.completion_tokens if usage else None,
                    "usageAvailable": usage is not None, "rawUsage": usage.model_dump(mode="json") if usage else None,
                    "maxOutputTokens": 6000, "responseId": result.id, "status": "incomplete"}
        timings = getattr(result, "timings", None)
        if isinstance(timings, dict):
            measured = {key: value for key, value in timings.items()
                        if key in {"cache_n", "prompt_n", "prompt_ms", "predicted_n", "predicted_ms"}
                        and type(value) in {int, float} and math.isfinite(value) and value >= 0}
            if measured:
                metadata["nativeTimings"] = measured
        if (not isinstance(result.choices, list) or len(result.choices) != 1
                or result.choices[0] is None or result.choices[0].index != 0):
            raise ModelError("MODEL_OUTPUT_INVALID", usage=metadata)
        choice = result.choices[0]
        metadata["reasoningPresent"] = bool(getattr(getattr(choice, "message", None), "reasoning_content", None))
        try:
            calls = choice.message.tool_calls or []
            valid = isinstance(calls, list) and all(call.type == "function"
                and isinstance(call.id, str) and isinstance(call.function.name, str)
                and isinstance(call.function.arguments, str) for call in calls)
        except (AttributeError, TypeError):
            valid = False
        if not valid:
            raise ModelError("MODEL_OUTPUT_INVALID", usage=metadata)
        metadata["status"] = "completed" if choice.finish_reason == "tool_calls" else "incomplete"
        # Preserve actual native calls in the graph's existing failure/replanning envelope.
        response = {"status": metadata["status"], "sourceProtocol": "chat.completions.tool_calls", "output": [
            {"type": "function_call", "name": call.function.name, "call_id": call.id,
             "arguments": call.function.arguments} for call in calls]}
        observation.attribute("llm.model_name", result.model)
        observation.json_attribute("llm.native_tool_response", response)
        if usage:
            observation.attribute("llm.token_count.prompt", usage.prompt_tokens)
            observation.attribute("llm.token_count.completion", usage.completion_tokens)
            observation.attribute("llm.token_count.total", usage.total_tokens)
        if choice.message.refusal:
            raise ModelError("MODEL_REFUSED", usage=metadata, response=response)
        if choice.finish_reason == "length":
            raise ModelError("MODEL_OUTPUT_TRUNCATED", usage=metadata, response=response)
        if choice.finish_reason == "content_filter":
            raise ModelError("MODEL_CONTENT_FILTERED", usage=metadata, response=response)
        if choice.finish_reason is None:
            raise ModelError("MODEL_RESPONSE_INCOMPLETE", usage=metadata, response=response)
        if choice.finish_reason != "tool_calls":
            raise ModelError("MODEL_OUTPUT_INVALID", usage=metadata, response=response)
        return response, metadata

    def _json_request(self, instructions, input_value, schema, observation, *, max_output_tokens=6000,
                      on_text_delta=None):
        if self.client is None:
            raise ModelError("MODEL_NOT_CONFIGURED")
        params = {"model": self.settings.model, "max_tokens": max_output_tokens, "store": False,
                  "reasoning_effort": self.settings.reasoning_effort,
                  "messages": [{"role": "system", "content": instructions},
                               {"role": "user", "content": input_value}],
                  "response_format": {"type": "json_schema", "json_schema": {
                      "name": "local_result", "strict": True, "schema": schema}}}
        params.update(self.settings.generation_options())
        observation.json_attribute("llm.invocation_parameters", params)
        fragments: list[str] = []
        text, response_id, model_name = "", "", self.settings.model
        finish = None
        usage = None
        refusal = None
        reasoning_present = False

        def failure(code, retryable=False):
            partial = {"status": "stream_interrupted", "output_text": "".join(fragments),
                       "usage": None, "max_output_tokens": max_output_tokens} if fragments else None
            return ModelError(code, retryable, response=partial)

        try:
            if on_text_delta is None:
                result = self.client.chat.completions.create(**params)
                if getattr(result, "error", None):
                    raise failure("MODEL_RESPONSE_FAILED")
                if len(result.choices) != 1 or result.choices[0].index != 0:
                    raise failure("MODEL_OUTPUT_INVALID")
                choice = result.choices[0]
                reasoning_present = bool(getattr(choice.message, "reasoning_content", None))
                if choice.message.tool_calls:
                    raise failure("MODEL_OUTPUT_INVALID")
                text = choice.message.content or ""
                refusal, finish = choice.message.refusal, choice.finish_reason
                response_id, model_name, usage = result.id, result.model, result.usage
            else:
                with self.client.chat.completions.create(**params, stream=True,
                        stream_options={"include_usage": True}) as stream:
                    for chunk in stream:
                        response_id, model_name = chunk.id, chunk.model
                        if chunk.usage is not None:
                            usage = chunk.usage
                        if not chunk.choices:
                            continue
                        if len(chunk.choices) != 1 or chunk.choices[0].index != 0:
                            raise failure("MODEL_OUTPUT_INVALID")
                        choice = chunk.choices[0]
                        reasoning_present = reasoning_present or bool(getattr(choice.delta, "reasoning_content", None))
                        if choice.delta.tool_calls or (finish is not None and choice.delta.content):
                            raise failure("MODEL_OUTPUT_INVALID")
                        if choice.delta.refusal:
                            refusal = (refusal or "") + choice.delta.refusal
                        if choice.delta.content:
                            fragments.append(choice.delta.content)
                            on_text_delta(choice.delta.content)
                        if choice.finish_reason is not None:
                            if finish is not None:
                                raise failure("MODEL_OUTPUT_INVALID")
                            finish = choice.finish_reason
                text = "".join(fragments)
                if finish is None:
                    raise failure("MODEL_STREAM_INTERRUPTED")
        except (APITimeoutError, httpx.TimeoutException):
            raise failure("MODEL_TIMEOUT", retryable=True) from None
        except (APIStatusError, httpx.HTTPStatusError) as error:
            status = error.response.status_code
            raise failure("MODEL_RATE_LIMITED" if status == 429 else f"MODEL_HTTP_{status}",
                          retryable=status == 429 or status >= 500) from None
        except (APIConnectionError, httpx.HTTPError):
            raise failure("MODEL_CONNECTION", retryable=True) from None
        except APIError:
            raise failure("MODEL_STREAM_ERROR" if on_text_delta is not None else "MODEL_API_ERROR") from None
        if usage and any(type(value) is not int or value < 0 for value in (
                usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)):
            raise failure("MODEL_OUTPUT_INVALID")
        metadata = {"model": model_name, "reasoningEffort": self.settings.reasoning_effort,
                    "reasoningPresent": reasoning_present,
                    "inputTokens": usage.prompt_tokens if usage else None,
                    "outputTokens": usage.completion_tokens if usage else None,
                    "usageAvailable": usage is not None, "rawUsage": usage.model_dump(mode="json") if usage else None,
                    "maxOutputTokens": max_output_tokens, "responseId": response_id,
                    "status": "completed" if finish == "stop" else "incomplete"}
        observation.attribute("llm.model_name", model_name)
        observation.attribute("llm.response.status", metadata["status"])
        observation.output({"status": metadata["status"], "output_text": text})
        if usage:
            observation.attribute("llm.token_count.prompt", usage.prompt_tokens)
            observation.attribute("llm.token_count.completion", usage.completion_tokens)
            observation.attribute("llm.token_count.total", usage.total_tokens)
        if refusal:
            raise ModelError("MODEL_REFUSED", usage=metadata)
        if finish != "stop":
            code = {"length": "MODEL_OUTPUT_TRUNCATED", "content_filter": "MODEL_CONTENT_FILTERED"}.get(
                finish, "MODEL_RESPONSE_INCOMPLETE")
            raise ModelError(code, usage=metadata, response={"status": metadata["status"], "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}]})
        if not text.strip():
            raise ModelError("MODEL_OUTPUT_INVALID", usage=metadata)
        return text, metadata

    def generate(self, instructions, payload, output_model, *, on_text_delta=None):
        with tracing.span(
            "llm.responses",
            kind="LLM",
            inputs={
                "instructions": instructions,
                "payload": payload,
            },
            attributes={"llm.model_name": self.settings.model},
        ) as observation:
            observation.attribute("llm.input_messages.0.message.role", "system")
            observation.attribute("llm.input_messages.0.message.content", instructions)
            observation.attribute("llm.input_messages.1.message.role", "user")
            observation.json_attribute("llm.input_messages.1.message.content", payload)
            return self._generate(instructions, payload, output_model, observation, on_text_delta=on_text_delta)

    def _generate(self, instructions, payload, output_model, observation, *, on_text_delta=None):
        schema = strict_schema(output_model)
        observation.json_attribute("llm.output_schema", schema)
        text, metadata = self._json_request(
            instructions,
            json.dumps(payload, ensure_ascii=False),
            schema,
            observation,
            on_text_delta=on_text_delta,
            max_output_tokens=3000,
        )
        observation.attribute("llm.output_messages.0.message.content", text)
        try:
            data = omit_nulls(json.loads(text))
            validated = output_model.model_validate(data).model_dump(exclude_none=True)
        except (ValueError, TypeError):
            raise ModelError("MODEL_OUTPUT_INVALID", usage=metadata,
                             response={"status": metadata["status"], "output_text": text}) from None
        observation.json_attribute("kplasma.validated_output", validated)
        return validated, metadata
