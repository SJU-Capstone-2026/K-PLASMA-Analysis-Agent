"""OpenAI Responses adapter. Credentials and provider error bodies never enter state."""

import copy
import json
from openai import OpenAI, APIError, APIConnectionError, APITimeoutError, RateLimitError
from . import tracing


class ModelError(RuntimeError):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


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
        self.client = (
            OpenAI(api_key=settings.api_key, timeout=settings.timeout, max_retries=0, http_client=http_client)
            if settings.api_key
            else None
        )

    def generate(self, instructions, payload, output_model):
        with tracing.span("llm.responses", kind="LLM", inputs={
            "instructions": instructions, "payload": payload,
        }, attributes={"llm.model_name": self.settings.model}) as observation:
            observation.attribute("llm.input_messages.0.message.role", "system")
            observation.attribute("llm.input_messages.0.message.content", instructions)
            observation.attribute("llm.input_messages.1.message.role", "user")
            observation.json_attribute("llm.input_messages.1.message.content", payload)
            return self._generate(instructions, payload, output_model, observation)

    def _generate(self, instructions, payload, output_model, observation):
        if self.client is None:
            raise ModelError("MODEL_NOT_CONFIGURED")
        schema = strict_schema(output_model)
        observation.json_attribute("llm.output_schema", schema)
        invocation_parameters = {
            "model": self.settings.model, "reasoning": {"effort": self.settings.reasoning_effort},
            "store": False, "max_output_tokens": 3000,
        }
        observation.json_attribute("llm.invocation_parameters", invocation_parameters)
        try:
            response = self.client.responses.create(
                **invocation_parameters,
                instructions=instructions,
                input=json.dumps(payload, ensure_ascii=False),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": output_model.__name__,
                        "strict": True,
                        "schema": schema,
                    }
                },
            )
        except (APIConnectionError, APITimeoutError, RateLimitError):
            raise ModelError("MODEL_UNAVAILABLE", retryable=True) from None
        except APIError as error:
            raise ModelError(
                "MODEL_UNAVAILABLE", retryable=(getattr(error, "status_code", 0) or 0) >= 500
            ) from None
        observation.output(lambda: {
            "status": response.status, "output_text": response.output_text,
            "response": response.model_dump(mode="json"),
        })
        observation.attribute("llm.output_messages.0.message.role", "assistant")
        observation.attribute("llm.output_messages.0.message.content", response.output_text)
        if response.usage:
            observation.attribute("llm.token_count.prompt", response.usage.input_tokens)
            observation.attribute("llm.token_count.completion", response.usage.output_tokens)
            observation.attribute("llm.token_count.total", response.usage.total_tokens)
        if response.status != "completed":
            raise ModelError("MODEL_OUTPUT_TRUNCATED")
        if any(
            part.type == "refusal"
            for item in response.output
            if item.type == "message"
            for part in item.content
        ):
            raise ModelError("MODEL_REFUSED")
        try:
            data = omit_nulls(json.loads(response.output_text))
            validated = output_model.model_validate(data).model_dump(exclude_none=True)
        except (ValueError, TypeError):
            raise ModelError("MODEL_OUTPUT_INVALID") from None
        usage = response.usage
        metadata = {
            "model": response.model,
            "reasoningEffort": self.settings.reasoning_effort,
            "inputTokens": usage.input_tokens if usage else 0,
            "outputTokens": usage.output_tokens if usage else 0,
        }
        observation.json_attribute("kplasma.validated_output", validated)
        return validated, metadata
