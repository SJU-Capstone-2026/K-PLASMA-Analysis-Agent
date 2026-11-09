"""OpenAI Responses adapter. Credentials and provider error bodies never enter state."""

import copy
import json
import httpx
from openai import OpenAI, APIError, APIConnectionError, APIStatusError, APITimeoutError
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

    def _input(self, payload, tool_context):
        if not tool_context:
            return json.dumps(payload, ensure_ascii=False)
        # Manual continuation retains the complete native output, including reasoning items.
        return [
            {"role": "user", "content": json.dumps(tool_context["input"], ensure_ascii=False)},
            *tool_context["responseItems"],
            {
                "type": "function_call_output",
                "call_id": tool_context["call_id"],
                "output": json.dumps(
                    {"result": tool_context["output"], "answerRequest": payload},
                    ensure_ascii=False,
                    allow_nan=False,
                ),
            },
        ]

    def _request(self, instructions, input_value, observation, *, on_text_delta=None, **options):
        if self.client is None:
            raise ModelError("MODEL_NOT_CONFIGURED")
        params = {
            "model": self.settings.model,
            "reasoning": {"effort": self.settings.reasoning_effort},
            "store": False,
            "max_output_tokens": 6000,
            **options,
        }
        observation.json_attribute("llm.invocation_parameters", params)
        observation.json_attribute("llm.responses_input", input_value)
        observation.attribute("llm.output_messages.0.message.role", "assistant")
        try:
            if on_text_delta is None:
                response = self.client.responses.create(**params, instructions=instructions, input=input_value)
            else:
                response = None
                with self.client.responses.stream(**params, instructions=instructions, input=input_value) as stream:
                    for event in stream:
                        if event.type == "response.output_text.delta":
                            on_text_delta(event.delta)
                        elif event.type == "error":
                            raise ModelError("MODEL_STREAM_ERROR")
                        elif event.type in {"response.completed", "response.incomplete", "response.failed"}:
                            response = event.response
                if response is None:
                    raise ModelError("MODEL_OUTPUT_TRUNCATED")
        except (APITimeoutError, httpx.TimeoutException):
            raise ModelError("MODEL_TIMEOUT", retryable=True) from None
        except (APIStatusError, httpx.HTTPStatusError) as error:
            status = error.response.status_code
            code = "MODEL_RATE_LIMITED" if status == 429 else f"MODEL_HTTP_{status}"
            raise ModelError(code, retryable=status == 429 or status >= 500) from None
        except (APIConnectionError, httpx.HTTPError):
            raise ModelError("MODEL_CONNECTION", retryable=True) from None
        except APIError:
            raise ModelError("MODEL_STREAM_ERROR" if on_text_delta is not None else "MODEL_API_ERROR") from None
        observation.output(
            lambda: {
                "status": response.status,
                "output_text": response.output_text,
                "response": response.model_dump(mode="json"),
            }
        )
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
        metadata = {
            "model": response.model,
            "reasoningEffort": self.settings.reasoning_effort,
            "inputTokens": response.usage.input_tokens if response.usage else 0,
            "outputTokens": response.usage.output_tokens if response.usage else 0,
        }
        return response, metadata

    def select_tool(self, instructions, payload):
        from .tools import TOOL_MODELS, native_tools

        with tracing.span(
            "llm.tool_selection",
            kind="LLM",
            inputs={"instructions": instructions, "payload": payload},
            attributes={"llm.model_name": self.settings.model},
        ) as observation:
            response, metadata = self._request(
                instructions,
                self._input(payload, None),
                observation,
                tools=native_tools(),
                tool_choice="required",
                parallel_tool_calls=False,
            )
            calls = [item for item in response.output if item.type == "function_call"]
            if len(calls) != 1 or calls[0].name not in TOOL_MODELS or not calls[0].call_id:
                raise ModelError("MODEL_OUTPUT_INVALID")
            call = calls[0]
            try:
                arguments = (
                    TOOL_MODELS[call.name].model_validate(omit_nulls(json.loads(call.arguments))).model_dump()
                )
            except (ValueError, TypeError):
                raise ModelError("MODEL_OUTPUT_INVALID") from None
            selected = {"call_id": call.call_id, "name": call.name, "arguments": arguments}
            observation.json_attribute("kplasma.tool_selection", selected)
            # Private checkpoint only; the graph removes native items from public model metadata.
            metadata["responseItems"] = [item.model_dump(mode="json") for item in response.output]
            return selected, metadata

    def answer(self, instructions, payload, *, tool_context=None, on_text_delta=None):
        with tracing.span(
            "llm.general_answer",
            kind="LLM",
            inputs={"instructions": instructions, "payload": payload},
            attributes={"llm.model_name": self.settings.model},
        ) as observation:
            response, metadata = self._request(
                instructions, self._input(payload, tool_context), observation, on_text_delta=on_text_delta
            )
            if not response.output_text.strip():
                raise ModelError("MODEL_OUTPUT_INVALID")
            return response.output_text, metadata

    def stream_answer(self, instructions, payload, *, on_text_delta, tool_context=None):
        return self.answer(instructions, payload, tool_context=tool_context, on_text_delta=on_text_delta)

    def generate(self, instructions, payload, output_model, *, tool_context=None, on_text_delta=None):
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
            if tool_context:
                response, metadata = self._request(
                    instructions,
                    self._input(payload, tool_context),
                    observation,
                    on_text_delta=on_text_delta,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": output_model.__name__,
                            "strict": True,
                            "schema": strict_schema(output_model),
                        }
                    },
                )
                try:
                    return output_model.model_validate(
                        json.loads(response.output_text)
                    ).model_dump(), metadata
                except (ValueError, TypeError):
                    raise ModelError("MODEL_OUTPUT_INVALID") from None
            return self._generate(instructions, payload, output_model, observation, on_text_delta=on_text_delta)

    def _generate(self, instructions, payload, output_model, observation, *, on_text_delta=None):
        schema = strict_schema(output_model)
        observation.json_attribute("llm.output_schema", schema)
        response, metadata = self._request(
            instructions,
            json.dumps(payload, ensure_ascii=False),
            observation,
            on_text_delta=on_text_delta,
            max_output_tokens=3000,
            text={
                "format": {
                    "type": "json_schema",
                    "name": output_model.__name__,
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        observation.attribute("llm.output_messages.0.message.content", response.output_text)
        try:
            data = omit_nulls(json.loads(response.output_text))
            validated = output_model.model_validate(data).model_dump(exclude_none=True)
        except (ValueError, TypeError):
            raise ModelError("MODEL_OUTPUT_INVALID") from None
        observation.json_attribute("kplasma.validated_output", validated)
        return validated, metadata
