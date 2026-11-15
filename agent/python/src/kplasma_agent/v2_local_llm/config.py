from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from dotenv import dotenv_values

from .network import validate_endpoint

PREFIX = "AGENT_V2_LOCAL_LLM_"


def _reject_contamination(values):
    for key, value in values.items():
        if not value or key.startswith(PREFIX):
            continue
        if (key.startswith(("OPENAI_", "PHOENIX_", "OTEL_", "LANGSMITH_", "LANGCHAIN_", "AGENT_V2_", "AGENT_V3_"))
                or key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}):
            raise ValueError("LOCAL_ENV_CONTAMINATION")


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    backend_url: str = "http://127.0.0.1:8080"
    worker_token: str = field(default="", repr=False)
    model: str = "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"
    reasoning_effort: str = "medium"
    timeout: float = 90
    poll_seconds: float = 1
    graph_build_id: str = "v2-local-llm-v2.4-per-check-context"
    phoenix_endpoint: str = ""
    phoenix_api_key: str = field(default="", repr=False)
    phoenix_project_name: str = "K-PLASMA-local"
    model_url: str = "http://127.0.0.1:8082/v1"
    d1_url: str = "http://127.0.0.1:8083/v1/systemone"
    d1_token: str = field(default="", repr=False)
    d1_model: str = "LiquidAI/d1-2B:MLX8"
    d1_engine: str = "mlx"
    d1_precision: str = "q8"
    d1_input_profile: str = "en-compact-no-view"
    d1_context_mode: str = "full"
    d1_group_size: int = 1
    d1_independent_batch_size: int = 1
    model_path: str = ""
    d1_model_path: str = ""
    tokenizer_path: str = ""
    d1_tokenizer_path: str = ""
    model_revision: str = ""
    d1_revision: str = ""
    runtime_version: str = ""
    d1_runtime_version: str = ""
    context_tokens: int = 24576
    d1_context_tokens: int = 32768
    d1_batch_tokens: int = 16000
    d1_ubatch_tokens: int = 16000
    measurement_path: str = ""
    memory_policy: str = "strict"
    qwen_plan_cache_enabled: bool = False
    qwen_plan_cache_dir: str = field(default_factory=lambda: str(
        Path(__file__).resolve().parents[5] / ".local/cache/v2_localLLM/qwen-plan-cache-KV"))

    @classmethod
    def from_env(cls, env_file=None):
        if env_file is None:
            raise ValueError("LOCAL_ENV_FILE_REQUIRED")
        try:
            path = Path(env_file).expanduser().resolve(strict=True)
            if not path.is_file():
                raise ValueError("LOCAL_ENV_FILE_REQUIRED")
        except OSError:
            raise ValueError("LOCAL_ENV_FILE_REQUIRED") from None
        values = dict(dotenv_values(path, interpolate=False))
        _reject_contamination(values)
        _reject_contamination(os.environ)
        values.update({k: v for k, v in os.environ.items() if k.startswith(PREFIX)})
        def get(name, default=""):
            return values.get(PREFIX + name) or default
        timeout = float(get("TIMEOUT_SECONDS", "90"))
        memory_policy = get("MEMORY_POLICY", "strict").lower()
        if memory_policy not in {"strict", "development"}:
            raise ValueError("LOCAL_MEMORY_POLICY_INVALID")
        cache_enabled = get("QWEN_PLAN_CACHE_ENABLED", "false").lower()
        if cache_enabled not in {"true", "false", "1", "0"}:
            raise ValueError("LOCAL_CACHE_CONFIG_INVALID")
        cache_dir = Path(get("QWEN_PLAN_CACHE_DIR", cls().qwen_plan_cache_dir)).expanduser()
        if not cache_dir.is_absolute():
            cache_dir = Path(__file__).resolve().parents[5] / cache_dir
        if timeout != 90 or get("PLAN_REVIEW_ENABLED", "true").lower() not in {"true", "1"}:
            raise ValueError("LOCAL_REQUIRED_BUDGET_OR_REVIEW_CHANGED")
        d1_engine = get("D1_ENGINE", "mlx")
        try:
            group_size = int(get("D1_GROUP_SIZE", "1"))
            independent_size = int(get("D1_INDEPENDENT_BATCH_SIZE", "1"))
        except ValueError:
            raise ValueError("LOCAL_D1_GROUP_CONFIG_INVALID") from None
        if d1_engine != "mlx" or group_size != 1 or independent_size != 1:
            raise ValueError("LOCAL_D1_GROUP_CONFIG_INVALID")
        precision = get("D1_PRECISION", "q8")
        if precision not in {"q8", "bf16"}:
            raise ValueError("LOCAL_D1_PRECISION_CONFIG_INVALID")
        d1_model = get("D1_MODEL", "LiquidAI/d1-2B:" + ("MLX8" if precision == "q8" else "BF16"))
        if d1_model != "LiquidAI/d1-2B:" + ("MLX8" if precision == "q8" else "BF16"):
            raise ValueError("LOCAL_D1_PRECISION_CONFIG_INVALID")
        input_profile = get("D1_INPUT_PROFILE", "en-compact-no-view")
        if input_profile not in {"ko-full", "en-full", "en-compact", "en-compact-no-view"}:
            raise ValueError("LOCAL_D1_INPUT_CONFIG_INVALID")
        context_mode = get("D1_CONTEXT_MODE", "full")
        if context_mode not in {"full", "per_check"}:
            raise ValueError("LOCAL_D1_CONTEXT_CONFIG_INVALID")
        settings = cls(
            api_key=get("QWEN_TOKEN"), worker_token=get("WORKER_TOKEN"), d1_token=get("D1_TOKEN"),
            backend_url=validate_endpoint(get("BACKEND_URL", "http://127.0.0.1:8080")),
            model_url=validate_endpoint(get("QWEN_URL", "http://127.0.0.1:8082/v1")),
            d1_url=validate_endpoint(get("D1_URL", "http://127.0.0.1:8083/v1/systemone")),
            d1_engine=d1_engine, d1_group_size=group_size, d1_precision=precision,
            d1_input_profile=input_profile,
            d1_context_mode=context_mode,
            d1_independent_batch_size=independent_size,
            d1_model=d1_model,
            model_path=get("MODEL_PATH"), d1_model_path=get("D1_MODEL_PATH"),
            tokenizer_path=get("TOKENIZER_PATH"), d1_tokenizer_path=get("D1_TOKENIZER_PATH"),
            model_revision=get("MODEL_REVISION"), d1_revision=get("D1_REVISION"),
            runtime_version=get("RUNTIME_VERSION"), d1_runtime_version=get("D1_RUNTIME_VERSION"),
            context_tokens=int(get("QWEN_CONTEXT_TOKENS", "24576")),
            d1_context_tokens=int(get("D1_CONTEXT_TOKENS", "32768")),
            d1_batch_tokens=int(get("D1_BATCH_TOKENS", "16000")),
            d1_ubatch_tokens=int(get("D1_UBATCH_TOKENS", "16000")),
            measurement_path=get("MEMORY_MEASUREMENT_PATH"),
            memory_policy=memory_policy,
            qwen_plan_cache_enabled=cache_enabled in {"true", "1"},
            qwen_plan_cache_dir=str(cache_dir.absolute()),
        )
        if settings.context_tokens <= 6000 or min(settings.d1_context_tokens, settings.d1_batch_tokens,
                                                settings.d1_ubatch_tokens) <= 0:
            raise ValueError("LOCAL_CONTEXT_INVALID")
        return settings

    def readiness(self):
        from .runtime import check_readiness
        return check_readiness(self)

    def generation_options(self):
        return {"reasoning_effort": self.reasoning_effort, "temperature": 0.6, "top_p": 0.95,
                "extra_body": {"top_k": 20, "min_p": 0, "presence_penalty": 0, "repeat_penalty": 1,
                               "reasoning_format": "deepseek", "chat_template_kwargs": {
                                   "enable_thinking": self.reasoning_effort not in {"none", "minimal"}}}}

    def versions(self):
        from .core.d1_context import context_identity
        from .core.d1_input import VERSION as D1_INPUT_VERSION
        from .core.model_gateway import PLAN_INSTRUCTIONS, COMPOSE_INSTRUCTIONS, submit_plan_tool_schema
        root = Path(__file__).parent
        fields = {
            "graphVersion": "v2_localLLM", "implementationId": "v2_localLLM",
            "graphBuildId": self.graph_build_id, "schemaVersion": "1", "planSchemaVersion": "2",
            "sourceCommit": "51d077c9878b635c96da709eb7eb2aefd36699e1",
            "implementationHash": hashlib.sha256(b"".join(
                str(path.relative_to(root)).encode() + b"\0" + path.read_bytes()
                for path in sorted(root.rglob("*.py"))
            )).hexdigest(),
            "planner": self.model, "writer": self.model, "decisions": self.d1_model,
            "modelRevision": self.model_revision, "d1Revision": self.d1_revision,
            "quantization": "Q4_K_M",
            "d1Quantization": "MLX-affine8-g64/BF16-embedding" if self.d1_precision == "q8" else "BF16",
            "qwenGeneration": {"planThinking": self.reasoning_effort not in {"none", "minimal"},
                               "writerThinking": False, "reasoningBudget": 2048,
                               "planMaxOutput": 6000, "writerMaxOutput": 3000,
                               "options": self.generation_options()},
            "runtimeVersion": self.runtime_version, "d1RuntimeVersion": self.d1_runtime_version,
            "contextTokens": self.context_tokens, "d1ContextTokens": self.d1_context_tokens,
            "modelResidency": "sequential-16k-v2",
            "planProtocol": "native-submit-plan-chat-v2",
            "qwenPlanCache": {"enabled": self.qwen_plan_cache_enabled, "format": 1,
                              "directoryHash": hashlib.sha256(self.qwen_plan_cache_dir.encode()).hexdigest()},
            "runtimeManifestHash": hashlib.sha256((root / "runtime-manifest.json").read_bytes()).hexdigest(),
            "d1BatchTokens": self.d1_batch_tokens, "d1UbatchTokens": self.d1_ubatch_tokens,
            "d1Input": {"profile": self.d1_input_profile, "version": D1_INPUT_VERSION,
                        "sha256": hashlib.sha256((root / "core/d1_input.py").read_bytes()).hexdigest()},
            "d1Context": context_identity(self.d1_context_mode),
            "timeout": self.timeout, "planReviewEnabled": True,
            "memoryPolicy": self.memory_policy,
            "cloneManifestHash": hashlib.sha256((root / "clone-manifest.json").read_bytes()).hexdigest(),
            "intentionalDifferencesHash": hashlib.sha256((root / "intentional-differences.json").read_bytes()).hexdigest(),
            "promptHash": hashlib.sha256((PLAN_INSTRUCTIONS + COMPOSE_INSTRUCTIONS).encode()).hexdigest(),
            "toolSchemaHash": hashlib.sha256(json.dumps(submit_plan_tool_schema(), sort_keys=True).encode()).hexdigest(),
            "profileHash": hashlib.sha256(json.dumps({
                "backend": self.backend_url, "qwen": self.model_url, "d1": self.d1_url,
                "modelPath": self.model_path, "d1ModelPath": self.d1_model_path,
                "tokenizerPath": self.tokenizer_path, "d1TokenizerPath": self.d1_tokenizer_path,
            }, sort_keys=True).encode()).hexdigest(),
        }
        fields.update(d1Engine=self.d1_engine, d1Precision=self.d1_precision,
                      d1GroupSize=self.d1_group_size, d1IndependentBatchSize=self.d1_independent_batch_size,
                      d1GroupPolicy="sorted-greedy-full-pack-v1")
        fields["configFingerprint"] = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
        return fields
