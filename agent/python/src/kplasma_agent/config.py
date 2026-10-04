from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    backend_url: str = "http://127.0.0.1:8080"
    worker_token: str = field(default="", repr=False)
    model: str = "gpt-5.6-luna"
    reasoning_effort: str = "none"
    timeout: float = 30
    poll_seconds: float = 1
    graph_build_id: str = "v1-2026-10-05.2"

    @classmethod
    def from_env(cls, env_file=None):
        # Only a caller-selected file or the repository's local .env; never source shell code.
        load_dotenv(env_file or Path(__file__).resolve().parents[4] / ".env", override=False)
        port = os.getenv("BACKEND_PORT", "8080")
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            backend_url=os.getenv("AGENT_BACKEND_URL", f"http://127.0.0.1:{port}"),
            worker_token=os.getenv("AGENT_WORKER_TOKEN", ""),
            model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
            reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "none"),
            timeout=float(os.getenv("AGENT_MODEL_TIMEOUT_SECONDS", "30")),
            graph_build_id=os.getenv("AGENT_GRAPH_BUILD_ID", "v1-2026-10-05.2"),
        )

    def versions(self):
        from .graphs.v1 import EXPLAIN_PROMPT, INTERPRET_PROMPT

        fields = {
            "graphVersion": "v1",
            "graphBuildId": self.graph_build_id,
            "schemaVersion": "1",
            "promptVersion": "interpret-1",
            "numericPolicyVersion": "v1",
            "explanationPromptVersion": "explain-1",
            "interpretationPromptHash": hashlib.sha256(INTERPRET_PROMPT.encode()).hexdigest(),
            "explanationPromptHash": hashlib.sha256(EXPLAIN_PROMPT.encode()).hexdigest(),
            "explanationSchemaVersion": "1",
            "evidencePolicyVersion": "qualitative-1",
            "model": self.model,
            "reasoningEffort": self.reasoning_effort,
        }
        fields["configFingerprint"] = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
        return fields
