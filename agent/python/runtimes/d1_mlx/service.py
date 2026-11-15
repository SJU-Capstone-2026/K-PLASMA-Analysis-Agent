"""Text-only d1 MLX singleton service, with pinned BF16 and affine8 weights."""

import argparse
import gc
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import time

SOURCE_COMMIT = "2527a733c97a3fd5e0de54ea19f74fd362ed1ad2"
RUNTIME_VERSION = "mlx-decision-1.3.0@" + SOURCE_COMMIT
MAX_INPUT_TOKENS = 16000
GROUP_POLICY = "sorted-greedy-full-pack-v1"


def canonical_request(body):
    if (
        not isinstance(body, dict)
        or set(body) != {"state", "questions"}
        or not isinstance(body["state"], str)
        or not isinstance(body["questions"], dict)
        or not 1 <= len(body["questions"]) <= 400
    ):
        raise ValueError("LOCAL_D1_REQUEST_INVALID")
    questions = {}
    for name, q in sorted(body["questions"].items()):
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(q, dict)
            or set(q) != {"type", "instructions", "criteria"}
            or q["type"] != "choice"
            or not isinstance(q["instructions"], str)
            or not q["instructions"].strip()
            or not isinstance(q["criteria"], dict)
            or not 2 <= len(q["criteria"]) <= 26
            or any(
                not isinstance(k, str) or not k or (v is not None and not isinstance(v, str))
                for k, v in q["criteria"].items()
            )
        ):
            raise ValueError("LOCAL_D1_REQUEST_INVALID")
        questions[name] = {**q, "criteria": dict(sorted(q["criteria"].items()))}
    return {"state": body["state"], "questions": questions}


def pack_requests(body, group_size, count, limit=MAX_INPUT_TOKENS, *, context_mode="full", context_trace=None):
    from kplasma_agent.v2_local_llm.core.d1_context import VERSION, project_state
    if context_mode not in {"full", "per_check"}:
        raise ValueError("LOCAL_D1_CONTEXT_CONFIG_INVALID")
    body = canonical_request(body)
    if group_size != 1 or type(group_size) is not int or not 0 < limit <= MAX_INPUT_TOKENS:
        raise ValueError("LOCAL_D1_GROUP_CONFIG_INVALID")
    groups = []
    for name, question in body["questions"].items():
        state = body["state"]
        if context_mode == "per_check":
            state, trace = project_state(state, name)
        else:
            trace = {"action": "full", "reason": "full_mode", "tool_ids": [], "metric_ids": [],
                     "version": VERSION,
                     "state_sha256": hashlib.sha256(state.encode()).hexdigest()}
        full = {"state": state, "questions": {name: question}}
        n = count(full)
        if type(n) is not int or not 0 < n <= limit:
            raise ValueError("LOCAL_D1_INPUT_TOO_LARGE")
        groups.append((full, n))
        if context_trace is not None:
            context_trace.append({**trace, "question_id": name})
    return groups


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class Runtime:
    def __init__(self, config):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        import sysconfig
        import sys

        root = Path(__file__).resolve().parent
        sys.path.insert(0, str(root.parents[1] / "src"))
        from kplasma_agent.v2_local_llm import runtime_integrity
        from kplasma_agent.v2_local_llm.core.d1_context import context_identity
        from kplasma_agent.v2_local_llm.runtime_integrity import verify_libraries, verify_weights
        pins = json.loads(
            (root.parents[1] / "src/kplasma_agent/v2_local_llm/runtime-manifest.json").read_text()
        )
        self.libraries_hash = verify_libraries(
            sysconfig.get_path("purelib"), root / "uv.lock", pins["d1MLX"]["libraries"]
        )
        import mlx.core as mx
        from mlx_decision.backend import Capabilities
        from mlx_decision.models.d1lfm3.config import settings
        from mlx_decision.models.d1lfm3.model import D1Lfm3Backend
        from tokenizers import Tokenizer

        if importlib.metadata.version("mlx-decision") != "1.3.0" or not mx.metal.is_available():
            raise ValueError("LOCAL_D1_MLX_RUNTIME_MISMATCH")
        direct_text = importlib.metadata.distribution("mlx-decision").read_text("direct_url.json")
        if not direct_text:
            raise ValueError("LOCAL_D1_MLX_RUNTIME_MISMATCH")
        direct = json.loads(direct_text)
        if direct.get("vcs_info", {}).get("commit_id") != SOURCE_COMMIT:
            raise ValueError("LOCAL_D1_MLX_RUNTIME_MISMATCH")
        mx.set_default_device(mx.gpu)
        self.mx = mx
        self.service_hash = file_hash(__file__)
        self.integrity_hash = file_hash(runtime_integrity.__file__)
        self.context_mode = config.get("context_mode", "full")
        self.context_identity = context_identity(self.context_mode)
        self.path = Path(config["model_path"]).resolve(strict=True)
        manifest_path = self.path / "kplasma-manifest.json"
        self.manifest_hash = file_hash(manifest_path)
        manifest = json.loads(manifest_path.read_text())
        files = manifest["files"]
        verify_weights(self.path, files)
        required = {"config.json", "tokenizer.json", "calibration.json"}
        if (
            manifest["model"] != "LiquidAI/d1-2B"
            or not required <= set(files)
            or not any(name.endswith(".safetensors") for name in files)
        ):
            raise ValueError("LOCAL_MODEL_ARTIFACT_MISMATCH")
        for name, digest in files.items():
            p = self.path / name
            if p.resolve().parent != self.path or file_hash(p) != digest:
                raise ValueError("LOCAL_MODEL_ARTIFACT_MISMATCH")
        self.revision = manifest["revision"]
        self.group_size = config["group_size"]
        if type(self.group_size) is not int or self.group_size != 1:
            raise ValueError("LOCAL_D1_GROUP_CONFIG_INVALID")
        self.independent_batch_size = config.get("independent_batch_size", 1)
        if (type(self.independent_batch_size) is not int or self.independent_batch_size != 1):
            raise ValueError("LOCAL_D1_GROUP_CONFIG_INVALID")
        found = settings(self.path)
        if found.set_size != 16:
            raise ValueError("LOCAL_D1_MLX_RUNTIME_MISMATCH")
        self.encoder = D1Lfm3Backend(
            "d1-2B",
            None,
            Tokenizer.from_file(str(self.path / "tokenizer.json")),
            found,
            Capabilities(max_input_tokens=MAX_INPUT_TOKENS),
            self.path,
        )
        self.backend = None
        from weights import load_backend
        self.load_backend = load_backend
        self.weights_hash = file_hash(root / "weights.py")
        self.precision = config.get("precision", "q8")
        if self.precision not in {"bf16", "q8"}:
            raise ValueError("LOCAL_D1_PRECISION_INVALID")
        self.model_alias = "LiquidAI/d1-2B:MLX8" if self.precision == "q8" else "LiquidAI/d1-2B:BF16"
        self.dtype = "mixed-affine8-bf16" if self.precision == "q8" else "bfloat16"
        import mlx.nn as nn

        # First module initialization leaves tiny shared MLX state; measure it before any d1 weights.
        warmup = nn.Linear(2, 2)
        mx.eval(warmup.parameters())
        del warmup
        mx.synchronize()
        gc.collect()
        mx.clear_cache()
        self.idle_active = mx.get_active_memory()
        self.last_release = True

    def count(self, body):
        from mlx_decision.models.d1lfm3.model import question_dict
        from mlx_decision.types import parse_request

        request = parse_request(body)
        questions = {name: question_dict(name, q) for name, q in request.questions.items()}
        packed = self.encoder._packed(request.state, questions, ())
        if len(packed) != 1:
            raise ValueError("LOCAL_D1_PACK_MISMATCH")
        return len(packed[0].ids)

    def groups(self, body, *, context_trace=None):
        groups = pack_requests(body, self.group_size, self.count,
                               context_mode=self.context_mode, context_trace=context_trace)
        if context_trace is not None:
            for (native, _), trace in zip(groups, context_trace, strict=True):
                trace["state_tokens"] = len(self.encoder.tokenizer.encode(
                    native["state"], add_special_tokens=False).ids)
                try:
                    state = json.loads(native["state"])
                except json.JSONDecodeError:
                    continue
                if isinstance(state, dict) and isinstance(state.get("tool_contracts"), dict):
                    contracts = state["tool_contracts"]
                    trace["tool_contract_tokens"] = len(self.encoder.tokenizer.encode(
                        json.dumps(contracts, ensure_ascii=False, separators=(",", ":")),
                        add_special_tokens=False).ids)
        return groups

    def pack_fingerprints(self, groups):
        fingerprints = []
        if self.group_size == 1:
            from mlx_decision.types import parse_request

            for native, _ in groups:
                encoded = self.encoder.encode(parse_request(native))
                packed = encoded.sets[0]
                content = {"ids": packed.ids, "state_length": packed.state_length,
                           "spans": packed.spans, "ends": packed.ends}
                fingerprints.append({"question_ids": packed.question_ids,
                    "sha256": hashlib.sha256(json.dumps(content, separators=(",", ":")).encode()).hexdigest()})
        return fingerprints

    def counts(self, body):
        context: list[dict] = []
        groups = self.groups(body, context_trace=context)
        return {
            "schema_version": 1,
            "group_counts": [n for _, n in groups],
            "group_question_ids": [list(b["questions"]) for b, _ in groups],
            "group_size": self.group_size,
            "policy": GROUP_POLICY,
            "independent_batch_size": self.independent_batch_size,
            "pack_fingerprints": self.pack_fingerprints(groups),
            "context": context,
            "input_limit": MAX_INPUT_TOKENS,
            "truncated": False,
        }

    def memory(self):
        return {
            "active_bytes": self.mx.get_active_memory(),
            "cache_bytes": self.mx.get_cache_memory(),
            "peak_bytes": self.mx.get_peak_memory(),
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }

    def facts(self):
        return {
            "engine": "mlx-decision",
            "runtime_version": RUNTIME_VERSION,
            "source_commit": SOURCE_COMMIT,
            "model": self.model_alias,
            "revision": self.revision,
            "model_path": str(self.path),
            "dtype": self.dtype,
            "precision": self.precision,
            "manifest_sha256": self.manifest_hash,
            "group_size": self.group_size,
            "group_policy": GROUP_POLICY,
            "independent_batch_size": self.independent_batch_size,
            "input_limit": MAX_INPUT_TOKENS,
            "offline": True,
            "device": "gpu",
            "pid": os.getpid(),
            "loaded": self.backend is not None,
            "released": self.backend is None and self.last_release,
            "idle_active_bytes": self.idle_active,
            "memory": self.memory(),
            "service_sha256": self.service_hash,
            "weights_sha256": self.weights_hash,
            "libraries_sha256": self.libraries_hash,
            "integrity_sha256": self.integrity_hash,
            "context": self.context_identity,
        }

    def infer(self, body):
        from mlx_decision.types import parse_request

        context: list[dict] = []
        groups = self.groups(body, context_trace=context)
        fingerprints = self.pack_fingerprints(groups)
        self.mx.synchronize()
        self.mx.reset_peak_memory()
        started = time.monotonic()
        loaded = time.monotonic()
        if self.backend is None:
            self.last_release = False
            self.backend = self.load_backend(self.path, self.precision, MAX_INPUT_TOKENS)
            self.mx.eval(self.backend.model.parameters())
        load_seconds = time.monotonic() - loaded
        answers = {}
        timings = []
        results = []
        for native, tokens in groups:
            before = time.monotonic()
            result = self.backend.score(parse_request(native))
            if result.truncated or result.input_tokens != tokens:
                raise ValueError("LOCAL_D1_PACK_MISMATCH")
            results.append((result, native, tokens, before))
            timings.append({"question_ids": list(native["questions"]), "input_tokens": tokens,
                            "seconds": time.monotonic() - before})
        for result, native, tokens, before in results:
            if result.truncated or result.input_tokens != tokens:
                raise ValueError("LOCAL_D1_PACK_MISMATCH")
            for name, probabilities in result.probabilities.items():
                choice = max(probabilities, key=probabilities.get)
                answers[name] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": probabilities[choice],
                    "probabilities": probabilities,
                }
        return {
            "model": self.model_alias,
            "answers": answers,
            "usage": {"input_tokens": sum(n for _, n in groups), "output_tokens": 0},
            "local_metrics": {
                "groups": timings,
                "context": context,
                "pack_fingerprints": fingerprints,
                "load_seconds": load_seconds,
                "seconds": time.monotonic() - started,
                "memory": self.memory(),
            },
            "truncated": False,
        }

    def unload(self):
        self.mx.synchronize()
        self.backend = None
        gc.collect()
        self.mx.clear_cache()
        self.mx.synchronize()
        self.last_release = (
            self.mx.get_active_memory() <= self.idle_active and self.mx.get_cache_memory() == 0
        )
        if not self.last_release:
            raise ValueError("LOCAL_D1_MEMORY_NOT_RELEASED")
        return self.facts()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("LOCAL_D1_REQUEST_INVALID")
        result[key] = value
    return result


def serve(config):
    token_file = Path(config["token_file"])
    if token_file.stat().st_mode & 0o077:
        raise ValueError("LOCAL_TOKEN_FILE_PERMISSIONS")
    token = token_file.read_text().strip()
    if not token or token.startswith("sk-"):
        raise ValueError("LOCAL_TOKENS_NOT_CONFIGURED")
    runtime = Runtime(config)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(90)

        def log_message(self, *_):
            pass

        def reply(self, status, body):
            data = json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.reply(401, {"error": {"code": "UNAUTHORIZED"}})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            if self.path in {"/runtime", "/health"}:
                self.reply(200, runtime.facts())
            else:
                self.reply(404, {"error": {"code": "NOT_FOUND"}})

        def do_POST(self):
            if not self.authorized():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4 * 1024 * 1024:
                    raise ValueError("LOCAL_D1_REQUEST_INVALID")
                body = json.loads(
                    self.rfile.read(length),
                    object_pairs_hook=unique_object,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("LOCAL_D1_REQUEST_INVALID")),
                )
                if self.path == "/v1/count":
                    result = runtime.counts(body)
                elif self.path == "/v1/systemone":
                    try:
                        result = runtime.infer(body)
                    finally:
                        before = time.monotonic()
                        released = runtime.unload()
                    result["local_metrics"]["release_seconds"] = time.monotonic() - before
                    result["local_metrics"]["released"] = released["released"]
                elif self.path == "/unload" and body == {}:
                    result = runtime.unload()
                else:
                    self.reply(404, {"error": {"code": "NOT_FOUND"}})
                    return
                self.reply(200, result)
            except Exception as error:
                code = str(error)
                code = code if code.startswith("LOCAL_") and code.isupper() else "LOCAL_D1_RUNTIME_ERROR"
                self.reply(
                    422 if code in {"LOCAL_D1_REQUEST_INVALID", "LOCAL_D1_INPUT_TOO_LARGE"} else 503,
                    {"error": {"code": code}},
                )

    # Single request thread owns all MLX work; a release cannot race a pending inference.
    server = HTTPServer(("127.0.0.1", int(config["port"])), Handler)
    server.timeout = 90
    print(json.dumps({"status": "ready", "engine": "mlx-decision", "port": config["port"]}), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        runtime.unload()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    serve(json.loads(Path(args.config).read_text()))
