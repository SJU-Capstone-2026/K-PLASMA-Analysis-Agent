"""Artificial, loopback-only protocol probe. Passing never attests runtime privacy."""

import argparse
from contextlib import nullcontext
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx
from kplasma_agent.v2_local_llm.runtime import ModelRuntime, ModelRuntimeBusy, model_lease

QWEN_MODEL = "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"
D1_MODEL = "LiquidAI/d1-2B-GGUF:Q8_0"
PREFIX = "AGENT_V2_LOCAL_LLM_"
UNIT = "m⁻²s⁻¹"


class SmokeError(ValueError):
    """Only a fixed error code may reach the CLI output."""


def validate_endpoint(value, path):
    try:
        url = urlsplit(value)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
                or not url.port or url.username or url.password or url.query or url.fragment
                or url.path.rstrip("/") != path):
            raise ValueError
        return value.rstrip("/")
    except (ValueError, TypeError, AttributeError):
        raise SmokeError("SMOKE_ENDPOINT_INVALID") from None


def smoke_plan():
    from kplasma_agent.v2_local_llm.core.contracts import PlanDraft

    question = f"인공 검증: 이온 플럭스 단위 {UNIT}를 그대로 설명해줘."
    return PlanDraft.model_validate({
        "schema_version": 2, "request_mode": "general_only", "base_revision": None,
        "requirements": [{"id": "unit", "text": question,
                          "sources": [{"message_key": "question", "quote": question}],
                          "handled_by": ["explain"]}],
        "steps": [{"id": "explain", "kind": "tool", "tool": "explain_answer",
                   "requirement_ids": ["unit"], "inputs": {"mode": "concept"}}],
    }).model_dump(mode="json")


def _usage(data):
    value = data.get("usage")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SmokeError("SMOKE_USAGE_INVALID")
    counters = {key: count for key, count in value.items() if key in {
        "input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens"}}
    if any(type(count) is not int or count < 0 for count in counters.values()):
        raise SmokeError("SMOKE_USAGE_INVALID")
    return counters


def plan_response(data):
    from kplasma_agent.v2_local_llm.core.contracts import PlanDraft

    try:
        if (data["status"] != "completed" or len(data["output"]) != 1
                or data["output"][0].get("type") != "message"):
            raise ValueError
        plan = PlanDraft.model_validate(json.loads(_writer_text(data)))
        if plan.model_dump(mode="json") != smoke_plan():
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SmokeError("SMOKE_PLAN_INVALID") from None
    return _usage(data)


def _writer_text(data):
    return "".join(part["text"] for row in data["output"] if row.get("type") == "message"
                   for part in row["content"] if part.get("type") == "output_text")


def writer_response(data):
    from kplasma_agent.v2_local_llm.core.contracts import GeneralAnswerDraft

    try:
        if data["status"] != "completed":
            raise ValueError
        answer = GeneralAnswerDraft.model_validate(json.loads(_writer_text(data)))
        if not any(UNIT in text for text in answer.paragraphs) or answer.sources:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SmokeError("SMOKE_WRITER_INVALID") from None
    return _usage(data)


def decisions_response(data):
    try:
        answers = data["answers"]
        if not isinstance(answers, dict) or set(answers) != {"unit"}:
            raise ValueError
        row = answers["unit"]
        probabilities = row["probabilities"]
        if (row["type"] != "choice" or row["choice"] != "same"
                or not isinstance(probabilities, dict) or set(probabilities) != {"same", "changed"}
                or any(type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1
                       for value in probabilities.values())
                or not math.isclose(sum(probabilities.values()), 1, abs_tol=1e-5)):
            raise ValueError
        confidence = row.get("confidence")
        if confidence is not None and (type(confidence) not in {int, float}
                                       or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SmokeError("SMOKE_DECISIONS_INVALID") from None
    return _usage(data)


def run_smoke(settings, *, client=None, prepare=None):
    if settings.get("PLAN_REVIEW_ENABLED", "").lower() != "true":
        raise SmokeError("SMOKE_PLAN_REVIEW_REQUIRED")
    qwen = validate_endpoint(settings.get("QWEN_URL", ""), "/v1")
    d1 = validate_endpoint(settings.get("D1_URL", ""), "/v1/systemone")
    qwen_token, d1_token = settings.get("QWEN_TOKEN", ""), settings.get("D1_TOKEN", "")
    if (not qwen_token or not d1_token or d1_token.startswith("sk-")
            or (qwen_token.startswith("sk-") and not qwen_token.startswith("sk-lm-"))):
        raise SmokeError("SMOKE_LOCAL_AUTH_REQUIRED")
    from kplasma_agent.v2_local_llm.core.contracts import GeneralAnswerDraft
    from kplasma_agent.v2_local_llm.core.model_gateway import call_submit_plan, submit_plan_tool_schema
    from kplasma_agent.v2_local_llm.config import Settings
    from kplasma_agent.v2_local_llm.model_client import ModelClient, ModelError, strict_schema
    from kplasma_agent.v2_local_llm import tracing

    started = time.monotonic()
    writer_instructions = "인공 프로토콜 검증입니다. 입력 문장을 paragraphs 하나에 그대로 반환하고 sources는 빈 배열로 반환하세요."
    decision = {"state": {"synthetic": True, "unit": UNIT}, "questions": {"unit": {
        "type": "choice", "instructions": f"state의 unit가 {UNIT}와 같은가?",
        "criteria": {"same": "같은 단위 문자열", "changed": "다른 단위 문자열"}}}}
    usage = {}
    try:
        with model_lease(), (httpx.Client(trust_env=False, follow_redirects=False, timeout=90)
                              if client is None else nullcontext(client)) as http:
            model = ModelClient(Settings(api_key=qwen_token, model_url=qwen, model=QWEN_MODEL,
                                         reasoning_effort="none"), http_client=http)

            def generate(instructions, value, schema, *, on_text_delta=None, limit=3000, role="answer"):
                if prepare is not None:
                    prepare(role)
                with tracing.span("v2_localLLM.synthetic_protocol", kind="LLM") as span:
                    text, metadata = model._json_request(instructions, value, schema, span,
                        max_output_tokens=limit, on_text_delta=on_text_delta)
                return {"status": metadata["status"], "usage": metadata["rawUsage"], "output": [{
                    "type": "message", "content": [{"type": "output_text", "text": text}]}]}

            def post(url, body, token):
                response = http.post(url, json=body, headers={"Authorization": "Bearer " + token},
                                     timeout=90, follow_redirects=False)
                response.raise_for_status()
                return response.json()

            if prepare is not None:
                prepare("plan")
            plan, metadata = call_submit_plan(model,
                "인공 프로토콜 검증입니다. 주어진 계획을 submit_plan으로 동일하게 한 번 제출하세요.",
                json.dumps(smoke_plan(), ensure_ascii=False), submit_plan_tool_schema())
            if plan != smoke_plan():
                raise SmokeError("SMOKE_PLAN_INVALID")
            usage["plan"] = metadata["rawUsage"]
            usage["writer"] = writer_response(generate(writer_instructions, f"인공 검증: {UNIT}", strict_schema(GeneralAnswerDraft)))
            fragments: list[str] = []
            streamed = generate(writer_instructions, f"인공 검증: {UNIT}", strict_schema(GeneralAnswerDraft),
                                on_text_delta=fragments.append)
            if not fragments or "".join(fragments) != _writer_text(streamed):
                raise SmokeError("SMOKE_STREAM_INVALID")
            usage["stream"] = writer_response(streamed)
            if prepare is not None:
                prepare("plan_review")
            usage["decisions"] = decisions_response(post(d1, decision, settings["D1_TOKEN"]))
    except ModelError as error:
        raise SmokeError(error.code) from None
    except httpx.HTTPError:
        raise SmokeError("SMOKE_HTTP_ERROR") from None
    except json.JSONDecodeError:
        raise SmokeError("SMOKE_JSON_INVALID") from None
    return {"schema_version": 1, "graphVersion": "v2_localLLM", "synthetic_only": True, "passed": True,
            "runtime_ready": False, "requested_models": {"qwen": QWEN_MODEL, "d1": D1_MODEL},
            "usage": usage, "elapsed_seconds": round(time.monotonic() - started, 3),
            "remaining_checks": ["LOCAL_AUTHORITATIVE_READINESS_NOT_CHECKED", "LOCAL_ANALYSIS_QUALITY_UNVERIFIED"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Call only the configured loopback servers with built-in artificial inputs.")
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"passed": False, "runtime_ready": False, "code": "SMOKE_LIVE_FLAG_REQUIRED"}))
        return 2
    try:
        from dotenv import dotenv_values

        if not args.env_file.is_file():
            raise SmokeError("SMOKE_ENV_FILE_MISSING")
        profile = {key[len(PREFIX):]: value for key, value in dotenv_values(args.env_file, interpolate=False).items()
                   if key.startswith(PREFIX) and value is not None}
        if profile.get("PLAN_REVIEW_ENABLED", "").lower() != "true":
            raise SmokeError("SMOKE_PLAN_REVIEW_REQUIRED")
        from kplasma_agent.v2_local_llm.config import Settings
        from kplasma_agent.v2_local_llm.network import local_http_client
        settings = Settings.from_env(args.env_file)
        with local_http_client(settings.model_url, timeout=90,
                               headers={"Authorization": "Bearer " + settings.api_key}) as qwen, \
                local_http_client(settings.d1_url, timeout=90,
                                  headers={"Authorization": "Bearer " + settings.d1_token}) as d1:
            result = run_smoke(profile, prepare=ModelRuntime(settings, qwen, d1).prepare)
    except ModelRuntimeBusy:
        result = {"passed": False, "runtime_ready": False, "code": "LOCAL_MODEL_RUNTIME_BUSY"}
    except SmokeError as error:
        result = {"passed": False, "runtime_ready": False, "code": str(error)}
    except Exception:
        result = {"passed": False, "runtime_ready": False, "code": "SMOKE_CHECK_FAILED"}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
